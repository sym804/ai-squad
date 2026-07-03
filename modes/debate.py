import re
import json
import asyncio
import logging
import random
import datetime

from agents import (
    ClaudeAgent, CodexAgent, GeminiAgent,
    ClaudeBackupAgent, CodexBackupAgent, GeminiBackupAgent,
)
from config import MAX_DEBATE_ROUNDS, CONSENSUS_EARLY_ROUNDS, COMPLEX_MIN_ROUNDS
from cancel import is_cancelled, cleanup

logger = logging.getLogger(__name__)

CONSENSUS_PATTERN = re.compile(r"<!--CONSENSUS:(.*?)-->", re.DOTALL)

SYSTEM_PROMPT = (
    "당신은 AI 토론 에이전트입니다. 여러 라운드에 걸쳐 다른 에이전트들과 합의에 도달하세요.\n"
    "최종 답변은 반드시 500자 이내로 작성하세요. (웹 검색/도구 호출은 글자수에 포함되지 않음)\n"
    "핵심 원칙:\n"
    "- 사용자가 구체적인 정보를 요구하면 (상품명, 수치, 목록, 링크 등) 반드시 구체적으로 답하세요.\n"
    "- 추상적 요약이나 일반론으로 끝내지 말고, 사용자의 요구사항에 맞는 실질적 답변을 제시하세요.\n"
    "- **실시간 수치/시세/뉴스/환율/지수/가격**이 필요한 질문이면 **첫 번째 행동으로** 반드시 웹 검색 툴을 호출해 최신 값을 조회하세요. 출처(URL 또는 출처명)와 조회 시각을 답변에 명시하세요. 학습 데이터 기억만으로 수치를 단정 제시하는 것은 금지입니다.\n"
    "  * Gemini: `google_web_search` 툴을 호출하세요.\n"
    "  * Claude: `WebSearch` 또는 `WebFetch` 툴을 호출하세요.\n"
    "  * Codex: `web_search` 툴을 호출하세요.\n"
    "- 검색 결과가 서로 엇갈리면 가장 권위 있는 공식 출처(거래소, 통계청, 공식 API 등)를 우선하세요.\n"
    "- 상대 에이전트 검토 여부는 각 라운드 지시문에 따르세요. 지시 없이 임의로 '다른 에이전트'를 언급/추측하지 마세요.\n"
    "\n답변 마지막에 반드시 아래 형식의 합의 JSON을 포함하세요:\n"
    '<!--CONSENSUS:{"agree": true/false, "summary": "사용자 질문에 대한 구체적 답변 (상품명, 수치 등 포함, 1~3줄)", "disagreements": [{"agent": "에이전트명", "point": "쟁점", "why": "왜 동의하지 않는지"}]}-->\n'
    "agree=true: 본인 입장이 **최소 1명의 다른 에이전트와 충분히 일치**한다고 판단할 때 "
    "(전원 일치 필요 없음, 2/3 다수 합의 케이스에서도 true).\n"
    "agree=false: 본인 입장이 다른 모든 에이전트와 갈리거나, 아직 논의가 더 필요하다고 판단할 때.\n"
    "summary에는 단순 '합의함' 이 아니라, 사용자가 원하는 답변 자체를 담으세요.\n"
    "disagreements: 다른 에이전트와 의견이 실제로 갈리는 지점이 있을 때만 채우세요. "
    "의견이 정말로 같으면 빈 배열 []로 두세요(억지 반박 금지). "
    "단, 차이가 있는데 얼버무리지 말고 어느 에이전트의 어떤 주장에 왜 동의하지 않는지 구체적으로 적으세요."
)


def _strip_consensus(text: str) -> str:
    """응답에서 CONSENSUS 태그를 제거."""
    return CONSENSUS_PATTERN.sub('', text).strip()


def _parse_consensus(text: str) -> dict | None:
    """Extract consensus JSON from agent response.

    1) 표준 json.loads. 2) trailing comma 제거 후 재시도.
    3) 정규식으로 agree/summary salvage. 모두 실패 시 WARNING 로깅 후 None.
    """
    match = CONSENSUS_PATTERN.search(text)
    if not match:
        return None
    raw = match.group(1).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    # salvage 1: trailing comma 제거
    salvaged = re.sub(r",\s*([}\]])", r"\1", raw)
    if salvaged != raw:
        try:
            return json.loads(salvaged)
        except json.JSONDecodeError:
            pass
    # salvage 2: agree/summary 정규식 추출
    m_agree = re.search(r'"agree"\s*:\s*(true|false)', raw, re.IGNORECASE)
    m_sum = re.search(r'"summary"\s*:\s*"((?:[^"\\]|\\.)*)"', raw)
    if m_agree or m_sum:
        out: dict = {}
        if m_agree:
            out["agree"] = m_agree.group(1).lower() == "true"
        if m_sum:
            out["summary"] = m_sum.group(1)
        logger.warning("CONSENSUS JSON salvaged via regex: %s", raw[:200])
        return out
    logger.warning("CONSENSUS JSON parse failed: %s", raw[:200])
    return None


# 요약 발산 임계: 평균 페어와이즈 Jaccard 가 이 값 미만이면 발산
DIVERGE_THRESHOLD = 0.25

_TOKEN_RE = re.compile(r"[0-9a-z가-힣]+")
_DIFFICULTY_TECH = re.compile(
    r"코드|함수|클래스|버그|디버그|리뷰|아키텍처|리팩터|스택트레이스|"
    r"배포|알고리즘|구현|컴파일|예외|모듈|엔드포인트|스키마|마이그레이션",
    re.IGNORECASE,
)
_DIFFICULTY_REALTIME = re.compile(
    r"시세|환율|지수|가격|뉴스|실시간|주가|주식|시가총액", re.IGNORECASE
)
_DIFFICULTY_NUMBERED = re.compile(r"(?m)^\s*\d+[.)]")


def _tokens(text: str) -> set[str]:
    return set(_TOKEN_RE.findall((text or "").lower()))


def _summaries_diverge(round_consensuses: list[dict]) -> tuple[bool, str]:
    """그 라운드 각 에이전트 CONSENSUS summary 간 어휘 발산 여부.

    LLM 없이 결정론적. 평균 페어와이즈 Jaccard 가 DIVERGE_THRESHOLD 미만이면
    발산으로 판정하고 사람이 읽을 수 있는 쟁점 노트를 함께 반환한다.
    비교 가능한 summary 가 2개 미만이면 (False, "").
    """
    valid = []  # (agent_name, summary, consensus_dict)
    for r in round_consensuses:
        c = r.get("consensus")
        if c and c.get("summary"):
            valid.append((r.get("agent_name", "?"), c["summary"], c))
    if len(valid) < 2:
        return False, ""

    token_sets = [_tokens(s) for _, s, _ in valid]
    sims = []
    for i in range(len(token_sets)):
        for j in range(i + 1, len(token_sets)):
            a, b = token_sets[i], token_sets[j]
            union = a | b
            sims.append((len(a & b) / len(union)) if union else 1.0)
    # 평균이 아닌 **최소** pair 유사도 기준: A·B 동일·C만 outlier 인
    # 2:1 이탈도 발산으로 잡는다 (평균이면 0.33 으로 놓침).
    min_sim = min(sims) if sims else 1.0
    if min_sim >= DIVERGE_THRESHOLD:
        return False, ""
    return True, _format_issue_note(valid)


def _format_issue_note(valid: list[tuple[str, str, dict]]) -> str:
    """발산 라운드의 미해결 쟁점 노트 생성.

    각 CONSENSUS 의 disagreements(실제 대립점: point/why)만 사용한다.
    결론 메시지의 "각 에이전트 요약"이 이미 모든 summary 를 나열하므로
    summary 기반 노트는 항상 "각 에이전트 요약"·"합의된 답변"과 중복된다.
    따라서 구조적 대립점이 하나도 없으면 빈 문자열을 반환해 "미해결 쟁점"
    줄 자체가 표시/주입되지 않게 한다(중복 제거). 호출부는 모두
    `if issue_note:` 로 가드되어 있어 빈 문자열이면 자연히 생략된다.

    valid: (agent_name, summary, consensus_dict) 튜플 목록.
    """
    parts = []
    for name, _summary, c in valid:
        disagreements = c.get("disagreements") if isinstance(c, dict) else None
        if not isinstance(disagreements, list):
            continue
        points = []
        for d in disagreements:
            if not isinstance(d, dict):
                continue
            point = str(d.get("point") or "").strip()
            why = str(d.get("why") or "").strip()
            if point and why:
                points.append(f"{point} ({why})")
            elif point or why:
                points.append(point or why)
        if points:
            parts.append(f"{name}: {'; '.join(points)[:160]}")
    return " / ".join(parts)


# 자기-반복 임계: 직전 라운드 대비 토큰 Jaccard 가 이 값 이상이면 "그대로 반복"
NO_PROGRESS_THRESHOLD = 0.6

# 2-vs-1 페어 합의 감지 임계.
# - 페어 합의(2명 동의) Jaccard 가 이 값 이상이면 그 페어는 충분히 비슷한 입장으로 본다.
# - 다른 두 페어(outlier 가 끼는 페어)는 이 값보다 낮아야 outlier 확정.
# 0.30 으로 설정(_summaries_diverge 의 DIVERGE_THRESHOLD 0.25 보다 약간 높음 → 발산 판정 보다 보수적).
PAIR_AGREE_THRESHOLD = 0.30


def _pair_outlier(round_consensuses: list[dict], skip_names: set[str] | None = None) -> str | None:
    """3-에이전트 토론에서 2-vs-1 outlier 감지.

    각 페어 Jaccard 를 계산해 (1) 최고 페어 sim >= PAIR_AGREE_THRESHOLD 이고
    (2) outlier 가 포함된 나머지 두 페어 sim 모두 max_pair_sim 의 60% 이하이면,
    outlier 에이전트 이름을 반환. 그 외 None.

    예: A·B 가 sim=0.45 로 묶이고 (A,C)=0.10, (B,C)=0.08 이면 C 가 outlier.
    페어가 3개 미만(=summary 가 3명 다 안 들어옴)이면 None (판정 불가).

    skip_names: 이번 라운드에 백업으로 교체된 원본 에이전트 이름. 이들의 consensus 는
    무시한다 (Codex F1 회귀 방지: 원본이 부분 응답 + 백업 별도 응답 시 둘 다
    valid 에 들어가면 첫 3개 가져갈 때 원본이 잡혀 backup 가 무시되는 사고).
    """
    valid = []
    skip = skip_names or set()
    for r in round_consensuses:
        name = r.get("agent_name", "?")
        if name in skip:
            continue
        c = r.get("consensus")
        if c and c.get("summary"):
            valid.append((name, c["summary"]))
    if len(valid) < 3:
        return None
    # 첫 3명만 사용 (백업 투입 등으로 4+ 인 경우 안전)
    valid = valid[:3]
    names = [n for n, _ in valid]
    token_sets = [_tokens(s) for _, s in valid]

    def _jacc(a: set[str], b: set[str]) -> float:
        union = a | b
        return (len(a & b) / len(union)) if union else 1.0

    # 페어별 sim: (i, j, sim) i<j
    pairs = [
        (0, 1, _jacc(token_sets[0], token_sets[1])),
        (0, 2, _jacc(token_sets[0], token_sets[2])),
        (1, 2, _jacc(token_sets[1], token_sets[2])),
    ]
    # 가장 비슷한 페어
    best = max(pairs, key=lambda p: p[2])
    if best[2] < PAIR_AGREE_THRESHOLD:
        return None  # 그 어떤 페어도 충분히 비슷하지 않음 → 3 갈래 발산
    outlier_idx = ({0, 1, 2} - {best[0], best[1]}).pop()
    # outlier 가 끼는 나머지 두 페어 sim 이 best 의 60% 이하라야 outlier 확정
    other_sims = [p[2] for p in pairs if outlier_idx in (p[0], p[1])]
    if max(other_sims) > best[2] * 0.6:
        return None  # outlier 가 충분히 멀지 않음 (애매한 3 갈래)
    return names[outlier_idx]


def _persistent_outlier(outlier_history: list[str | None]) -> str | None:
    """같은 outlier 가 최근 2R 연속 잡혔는지 확인. 그렇다면 그 이름 반환."""
    if len(outlier_history) < 2:
        return None
    a, b = outlier_history[-2], outlier_history[-1]
    if a is not None and a == b:
        return a
    return None


def _round_summaries(round_consensuses: list[dict]) -> dict[str, str]:
    """그 라운드의 {에이전트명: summary} 매핑 (summary 있는 항목만)."""
    out: dict[str, str] = {}
    for r in round_consensuses:
        c = r.get("consensus")
        if c and c.get("summary"):
            out[r.get("agent_name", "?")] = c["summary"]
    return out


def _no_progress(prev: dict[str, str], curr: dict[str, str]) -> bool:
    """직전 라운드 대비 진전이 없는지(모든 에이전트가 자기 발언을 반복).

    cross-agent 발산이나 agree 플래그에 의존하지 않는다. 양 라운드에 모두
    존재하는 에이전트만 비교하고, 그중 **가장 많이 바뀐** 에이전트조차
    NO_PROGRESS_THRESHOLD 이상 자기 유사하면(= 아무도 실질적으로 안 바뀜)
    진전 없음으로 판정. 비교 가능한 에이전트가 2명 미만이면 False.
    """
    common = [name for name in curr if name in prev]
    if len(common) < 2:
        return False
    sims = []
    for name in common:
        a, b = _tokens(prev[name]), _tokens(curr[name])
        union = a | b
        sims.append((len(a & b) / len(union)) if union else 1.0)
    return min(sims) >= NO_PROGRESS_THRESHOLD


def _classify_difficulty(topic: str) -> str:
    """질문 난이도 휴리스틱 분류. LLM 호출 없음. 'simple' | 'complex'."""
    t = topic or ""
    if len(t) > 200:
        return "complex"
    if "```" in t:
        return "complex"
    if _DIFFICULTY_TECH.search(t):
        return "complex"
    if _DIFFICULTY_REALTIME.search(t):
        return "complex"
    if len(_DIFFICULTY_NUMBERED.findall(t)) >= 2:
        return "complex"
    return "simple"


def _count_agrees(round_consensuses: list[dict]) -> list[dict]:
    """agree=true 인 (유효 consensus) 항목 목록."""
    return [
        r for r in round_consensuses
        if r.get("consensus") is not None and r["consensus"].get("agree") is True
    ]


class DebateMode:
    def __init__(self, slack_client):
        self.slack = slack_client
        self.agents = [ClaudeAgent(), CodexAgent(), GeminiAgent()]
        # 백업 풀: 3계열 distinct 인스턴스. 동적 선택이 이 풀에서 고른다.
        self._claude_b = ClaudeBackupAgent()
        self._codex_b = CodexBackupAgent()
        self._gemini_b = GeminiBackupAgent()
        self._backup_pool = [self._claude_b, self._codex_b, self._gemini_b]
        # 정적 기본/타이브레이크 매핑(계열 회전, 자기 계열 회피).
        # values() 가 풀 전체를 distinct 로 커버한다.
        self._backup_map = {
            "Claude": self._codex_b,
            "Codex": self._gemini_b,
            "Gemini": self._claude_b,
        }
        self._replaced = set()  # 이미 교체된 에이전트 이름
        self._bot_user_id = None

    def _bind_thread(self, thread_ts: str, request_text: str = ""):
        """모든 에이전트에 현재 스레드 정보 + 작업 디렉토리(cwd) 설정.

        토론 주제/후속 질문에 ALLOWED_WORK_DIRS 안의 경로가 명시되면 그 경로를 모든
        에이전트의 cwd 로 잡는다. Codex 는 `-s workspace-write` 샌드박스가 cwd 밖 파일
        접근을 막아, cwd 를 설정하지 않으면 외부 경로(평가 대상 프로젝트 등)를 읽지 못한다
        (Windows 에서 0xC0000142 STATUS_DLL_INIT_FAILED 로 표면화). Gemini/Claude CLI 는
        이런 워크스페이스 스코프가 없어 영향받지 않는다. 경로 미지정/비허용이면 cwd 는
        None(기존 동작 유지).
        """
        from config import ALLOWED_WORK_DIRS
        from security import validate_work_dir, extract_work_path
        work_dir = validate_work_dir(extract_work_path(request_text), ALLOWED_WORK_DIRS)
        for agent in self.agents:
            agent._current_thread_ts = thread_ts
            agent._cwd = work_dir
        for backup in self._backup_pool:
            backup._current_thread_ts = thread_ts
            backup._cwd = work_dir

    def _get_backup(self, agent):
        """동적 백업 선택.

        우선순위: (1)장애 계열 아님 & 살아있는 계열 아님 > (2)장애 계열 아님 >
        (3)살아있는 계열 아님 > (4)그 외. 동순위는 정적 매핑 → 풀 순서로 결정론적.
        이중 장애 시에도 살아있는 에이전트 계열 다양성을 최대한 유지한다.
        """
        failing = getattr(agent, "base_family", None)
        live = {
            getattr(a, "base_family", None)
            for a in self.agents if a is not agent
        }
        static = self._backup_map.get(agent.name)

        # 이미 self.agents 에 들어있는 백업 인스턴스는 후보에서 제외해야
        # 동일 객체 중복(에이전트 리스트에 같은 인스턴스 2개)을 막는다.
        candidates = [b for b in self._backup_pool if b not in self.agents]
        if not candidates:
            candidates = list(self._backup_pool)

        def rank(b):
            not_failing = b.base_family != failing
            not_live = b.base_family not in live
            if not_failing and not_live:
                return 0
            if not_failing:
                return 1
            if not_live:
                return 2
            return 3

        ordered = sorted(
            candidates,
            key=lambda b: (rank(b), 0 if b is static else 1),
        )
        return ordered[0]

    def _make_progress_handler(self, channel, thread_ts, thinking_ts, agent):
        """경과 시간 + 내용 표시 핸들러."""
        import time, threading
        stop_event = threading.Event()
        start_time = time.time()
        state = {"text": ""}

        def _update_loop():
            while not stop_event.wait(15):
                if stop_event.is_set():
                    break
                elapsed = int(time.time() - start_time)
                preview = state["text"][-500:] if state["text"] else "응답 대기 중..."
                msg = f"💭 {agent.emoji} *[{agent.name}]* 작업 중... ({elapsed}초)\n```{preview}```"
                try:
                    self.slack.chat_update(channel=channel, ts=thinking_ts, text=msg)
                except Exception:
                    break

        def on_progress(text):
            state["text"] = text

        t = threading.Thread(target=_update_loop, daemon=True)
        t.start()
        return stop_event, on_progress

    def _replace_agent(self, agent, channel, thread_ts, reason="타임아웃"):
        """오류/타임아웃된 에이전트를 백업으로 교체. 이후 라운드에도 유지."""
        if agent.name in self._replaced:
            return
        backup = self._get_backup(agent)
        if not backup:
            return
        self._post(channel, thread_ts,
            f"⚠️ *{agent.name} {reason} → 이후 라운드부터 {backup.name} 교체*")
        self.agents = [backup if a is agent else a for a in self.agents]
        self._replaced.add(agent.name)

    async def followup(self, channel: str, thread_ts: str, question: str, attachments: list[dict] | None = None):
        """스레드에서 사용자가 추가 질문 → 기존 대화 기반 추가 토론 (합의까지).

        attachments 가 있으면 각 라운드의 ask_with_progress 호출에 그대로 전달해
        비전 지원 에이전트가 분석하도록 한다.
        """
        original_topic = self._fetch_original_topic(channel, thread_ts)
        # 경로는 보통 원 주제에 있으므로 후속 질문 + 원 주제를 함께 넘겨 cwd 를 잡는다.
        self._bind_thread(thread_ts, f"{question}\n{original_topic}")
        history = self._fetch_thread_history(channel, thread_ts)

        self._post(channel, thread_ts, f"💬 *추가 토론 시작*\n질문: {question}")

        history.append({"name": "사용자", "text": question})

        # 원 주제가 복잡하면 후속 질문이 짧아도 complex 유지 (F4)
        difficulty = _classify_difficulty(f"{original_topic}\n{question}")
        min_rounds = COMPLEX_MIN_ROUNDS if difficulty == "complex" else 1
        round_history: list[dict] = []
        pending_issue: str | None = None
        divergence_challenged = False
        prev_summaries: dict[str, str] | None = None
        outlier_history: list[str | None] = []  # 라운드별 2-vs-1 outlier 이름(없으면 None)

        for round_num in range(1, MAX_DEBATE_ROUNDS + 1):
            if is_cancelled(thread_ts):
                self._post(channel, thread_ts, "🛑 *작업이 취소되었습니다*")
                cleanup(thread_ts)
                return

            self._post(channel, thread_ts, f"--- *추가 토론 라운드 {round_num}* ---")

            shuffled = list(self.agents)
            random.shuffle(shuffled)

            thinking_msgs = {}
            handlers = {}
            for agent in shuffled:
                msg = self.slack.chat_postMessage(
                    channel=channel, thread_ts=thread_ts,
                    text=f"💭 {agent.emoji} *[{agent.name}]* 생각 중..."
                )
                thinking_msgs[agent.name] = msg["ts"]
                handlers[agent.name] = self._make_progress_handler(
                    channel, thread_ts, msg["ts"], agent)

            prompt = self._build_followup_prompt(original_topic, question, history, round_num, issue_note=pending_issue)

            async def _ask_followup_and_post(a):
                stop, cb = handlers[a.name]
                result = await a.ask_with_progress(prompt, on_progress=cb, attachments=attachments)
                stop.set()
                try:
                    self.slack.chat_delete(channel=channel, ts=thinking_msgs[a.name])
                except Exception:
                    pass
                # 완료 즉시 응답 포스트
                self._post(channel, thread_ts, a.format_message(_strip_consensus(result)))
                return result

            responses = await asyncio.gather(
                *[_ask_followup_and_post(agent) for agent in shuffled]
            )

            round_consensuses = []
            for agent, response in zip(shuffled, responses):
                history.append({"name": agent.name, "text": response})
                round_consensuses.append({
                    "agent_name": agent.name,
                    "agent_emoji": agent.emoji,
                    "consensus": _parse_consensus(response),
                })

            # 오류/타임아웃된 에이전트 → 백업 투입 + 이후 라운드 교체
            for agent, response in zip(shuffled, responses):
                if getattr(agent, 'needs_replacement', False):
                    backup = self._get_backup(agent)
                    if not backup:
                        continue
                    reason = "타임아웃" if getattr(agent, 'timed_out', False) else "오류 감지"
                    self._post(channel, thread_ts, f"⚠️ *{agent.name} {reason} → {backup.name} 대체 투입*")
                    thinking = self.slack.chat_postMessage(
                        channel=channel, thread_ts=thread_ts,
                        text=f"💭 {backup.emoji} *[{backup.name}]* 생각 중..."
                    )
                    backup_response = await backup.ask(prompt, attachments=attachments)
                    try:
                        self.slack.chat_delete(channel=channel, ts=thinking["ts"])
                    except Exception:
                        pass
                    self._post(channel, thread_ts, backup.format_message(_strip_consensus(backup_response)))
                    history.append({"name": backup.name, "text": backup_response})
                    round_consensuses.append({
                        "agent_name": backup.name,
                        "agent_emoji": backup.emoji,
                        "consensus": _parse_consensus(backup_response),
                    })
                    # 다음 라운드부터 이 에이전트를 백업으로 교체
                    self._replace_agent(agent, channel, thread_ts, reason)

            diverged, issue_note = _summaries_diverge(round_consensuses)
            agrees = _count_agrees(round_consensuses)
            round_history.append({"agrees": len(agrees), "diverged": diverged})
            curr_summaries = _round_summaries(round_consensuses)
            no_progress = prev_summaries is not None and _no_progress(prev_summaries, curr_summaries)
            prev_summaries = curr_summaries
            outlier_history.append(_pair_outlier(round_consensuses, skip_names=self._replaced))
            persistent_outlier = _persistent_outlier(outlier_history)
            can_conclude = round_num >= min_rounds

            if can_conclude and len(agrees) >= 3:
                if diverged and not divergence_challenged:
                    divergence_challenged = True
                    pending_issue = issue_note
                else:
                    header = self._build_conclusion(
                        "추가 토론 전원 합의", round_num, question, round_consensuses,
                        issue_note=issue_note if diverged else None,
                    )
                    final = await self._generate_final_answer(question, history, round_consensuses)
                    self._broadcast(channel, thread_ts, f"{header}\n\n💡 *합의된 답변:*\n{final}")
                    return
            elif can_conclude and len(agrees) >= 2 and self._is_stalemate(round_history):
                header = self._build_conclusion(
                    f"추가 토론 다수 합의 ({len(agrees)}/3)", round_num, question,
                    round_consensuses, issue_note=issue_note if diverged else None,
                )
                final = await self._generate_final_answer(question, history, round_consensuses)
                self._broadcast(channel, thread_ts, f"{header}\n\n💡 *합의된 답변:*\n{final}")
                return
            elif can_conclude and persistent_outlier:
                # 2-vs-1 outlier 2R 연속 (Slack thread 1779271920 패턴 종료용)
                header = self._build_conclusion(
                    f"추가 토론 다수 합의 (2/3, {persistent_outlier} 이견 지속)", round_num, question,
                    round_consensuses, issue_note=issue_note if diverged else None,
                )
                final = await self._generate_final_answer(question, history, round_consensuses)
                self._broadcast(channel, thread_ts, f"{header}\n\n💡 *합의된 답변:*\n{final}")
                return
            elif can_conclude and no_progress:
                # 모든 에이전트가 직전 라운드를 그대로 반복 = 추가 토론은 토큰 낭비
                title = (f"추가 토론 다수 합의 (수렴, {len(agrees)}/3 동의)"
                         if len(agrees) >= 2
                         else "추가 토론 종료 (합의 불발, 추가 진전 없음)")
                header = self._build_conclusion(
                    title, round_num, question,
                    round_consensuses, issue_note=issue_note if diverged else None,
                )
                final = await self._generate_final_answer(question, history, round_consensuses)
                self._broadcast(channel, thread_ts, f"{header}\n\n💡 *합의된 답변:*\n{final}")
                return
            else:
                pending_issue = issue_note if diverged else None

            # 라운드 사이 사용자 메시지 수집
            user_messages = self._fetch_user_messages(channel, thread_ts)
            for um in user_messages:
                if um not in [h["text"] for h in history if h["name"] == "사용자"]:
                    history.append({"name": "사용자", "text": um})

        # 최대 라운드 도달
        header = self._build_conclusion(
            "추가 토론 최대 라운드 도달", MAX_DEBATE_ROUNDS, question,
            round_consensuses, issue_note=pending_issue,
        )
        final = await self._generate_final_answer(question, history, round_consensuses)
        self._broadcast(channel, thread_ts, f"{header}\n\n💡 *합의된 답변:*\n{final}")

    def _build_followup_prompt(self, original_topic: str, question: str, history: list[dict], round_num: int, issue_note: str | None = None) -> str:
        """추가 토론 프롬프트. followup의 [이전 토론 내용]은 실제 과거 발언이므로 라운드 1부터 노출.
        단, 이번 추가 토론 **현재 라운드**의 상대 발언은 아직 없으므로 추측 금지."""
        # 15 -> 30 으로 확대. 3 에이전트 × 3 라운드 + 사용자/합의문이면
        # 15 윈도우는 라운드 2~3 만에 초반 메시지(첫 이미지 등)가 잘림.
        recent = history[-30:] if len(history) > 30 else history
        parts = [
            SYSTEM_PROMPT,
            f"\n[원래 토론 주제] {original_topic}",
            f"[사용자 추가 질문] {question}",
            f"[현재 라운드] {round_num}/{MAX_DEBATE_ROUNDS}",
        ]
        if recent:
            parts.append("\n[이전 토론 내용]")
            for entry in recent:
                # 300자 -> 1500자. _fetch_thread_history 저장본과 일관성 유지.
                parts.append(f"- {entry['name']}: {entry['text'][:1500]}")

        if round_num == 1:
            parts.append(
                "\n⚠️ 추가 토론 **라운드 1**입니다. 위 [이전 토론 내용]은 과거 기록이므로 맥락으로 참고하세요.\n"
                "- 하지만 이번 추가 질문에 대한 다른 에이전트의 **현재 라운드 답변**은 아직 없습니다.\n"
                "- 현재 라운드에서 다른 에이전트가 뭐라고 할지 추측/언급하지 마세요.\n"
                "- 사용자 추가 질문에 본인의 독립적 견해만 제시하세요.\n"
                "- 라운드 1의 agree 필드는 반드시 false로 설정하세요. (500자 이내)"
            )
        else:
            parts.append(
                "\n원래 주제와 사용자 추가 질문의 맥락을 반드시 참고하세요. "
                "위 [이전 토론 내용] 중 **본인 의견과 다른 지점**이 있으면 해당 에이전트와 주장을 "
                "구체적으로 인용해 왜 동의하지 않는지 명시하고 CONSENSUS의 disagreements에 기록하세요. "
                "의견이 실제로 같으면 같다고 밝혀도 됩니다(억지 반박 금지). 차이를 얼버무리지 마세요. "
                "사용자 의견이 최우선입니다. 구체적 정보(이름, 수치, 목록 등)를 포함하세요. (500자 이내)"
            )
            if issue_note:
                parts.append(
                    f"\n⚠️ 직전 라운드 **미해결 쟁점**입니다. 회피하지 말고 정면으로 다루세요:\n{issue_note}"
                )
        return "\n".join(parts)

    def _fetch_original_topic(self, channel: str, thread_ts: str) -> str:
        """스레드의 첫 번째 메시지(원래 주제)를 가져온다."""
        try:
            result = self.slack.conversations_replies(
                channel=channel, ts=thread_ts, limit=1
            )
            messages = result.get("messages", [])
            if messages:
                return messages[0].get("text", "").strip()
        except Exception as e:
            print(f"[SLACK ERROR] fetch original topic: {e}")
        return ""

    def _fetch_thread_history(self, channel: str, thread_ts: str) -> list[dict]:
        """스레드의 전체 대화를 히스토리로 변환."""
        try:
            if self._bot_user_id is None:
                self._bot_user_id = self.slack.auth_test()["user_id"]

            result = self.slack.conversations_replies(
                channel=channel, ts=thread_ts, limit=50
            )
            history = []
            for msg in result.get("messages", []):
                if msg.get("ts") == thread_ts:
                    continue
                text = msg.get("text", "").strip()
                files = msg.get("files", []) or []

                # 첨부파일 메타를 텍스트 마커로 보존 (사용자가 같은 이미지를
                # 여러 번 올려도 다음 라운드 LLM 입력에서 사라지지 않게).
                if files:
                    markers = []
                    for f in files:
                        fname = f.get("name") or f.get("title") or "?"
                        ftype = f.get("mimetype") or f.get("filetype") or ""
                        markers.append(f"[첨부: {fname} ({ftype})]")
                    text = (text + "\n" + "\n".join(markers)) if text else "\n".join(markers)

                if not text:
                    continue

                if msg.get("bot_id") or msg.get("user") == self._bot_user_id:
                    all_agents = list(self.agents) + list(self._backup_map.values())
                    name = None
                    for agent in all_agents:
                        if text.startswith(f"{agent.emoji} *[{agent.name}]*"):
                            name = agent.name
                            text = text.split("\n", 1)[-1] if "\n" in text else text
                            break
                    if name is None:
                        # 합의문/결론 메시지는 history에 포함 (이게 빠지면
                        # 에이전트가 자기 직전 합의를 부정하는 현상이 생김).
                        # 진행상태/생각중 같은 잡음 메시지는 제외.
                        if "🏛️" in text or "💡 *합의" in text or "*합의된 답변" in text:
                            name = "이전 라운드 합의"
                        else:
                            continue
                else:
                    name = "사용자"
                # 300자 절단을 1500자로 완화. 합의문이 머리만 남아 본문이
                # 사라지던 문제 방지.
                history.append({"name": name, "text": text[:1500]})
            return history
        except Exception as e:
            print(f"[SLACK ERROR] fetch thread history: {e}")
            return []

    def _fetch_today_conclusions(self, channel: str, current_thread_ts: str) -> list[str]:
        """당일 채널의 합의 결론 메시지만 가져온다."""
        try:
            today_start = datetime.datetime.now().replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            oldest = str(today_start.timestamp())

            result = self.slack.conversations_history(
                channel=channel, oldest=oldest, limit=200
            )
            conclusions = []
            for msg in result.get("messages", []):
                text = msg.get("text", "")
                # 합의 결론 메시지만 필터
                if "🏛️" in text and ("합의" in text or "라운드 도달" in text):
                    # 현재 스레드의 결론은 제외
                    if msg.get("thread_ts") == current_thread_ts:
                        continue
                    conclusions.append(text.strip())
            return conclusions
        except Exception as e:
            print(f"[SLACK ERROR] fetch today conclusions: {e}")
            return []

    async def start(self, channel: str, thread_ts: str, topic: str, attachments: list[dict] | None = None):
        """Main entry point for debate mode.

        attachments 는 사용자 첨부 파일 메타데이터 리스트 (이미지/PDF). 지원 에이전트가 분석.
        """
        self._bind_thread(thread_ts, topic)
        self._post(channel, thread_ts, f"*토론을 시작합니다*\n주제: {topic}")

        # 당일 이전 토론 합의 결론을 컨텍스트에 포함
        today_conclusions = self._fetch_today_conclusions(channel, thread_ts)

        history: list[dict] = []  # {"name": str, "text": str}
        if today_conclusions:
            for c in today_conclusions:
                history.append({"name": "이전 토론 결론", "text": c})
        final_summary = None

        difficulty = _classify_difficulty(topic)
        min_rounds = COMPLEX_MIN_ROUNDS if difficulty == "complex" else 1
        round_history: list[dict] = []  # 라운드별 {"agrees", "diverged"} 스냅샷
        pending_issue: str | None = None  # 다음 라운드에 주입할 미해결 쟁점
        divergence_challenged = False  # 발산 교전 라운드를 이미 1회 강제했는지
        prev_summaries: dict[str, str] | None = None  # 직전 라운드 summary (자기-반복 감지용)
        outlier_history: list[str | None] = []  # 라운드별 2-vs-1 outlier 이름(없으면 None)

        for round_num in range(1, MAX_DEBATE_ROUNDS + 1):
            if is_cancelled(thread_ts):
                self._post(channel, thread_ts, "🛑 *작업이 취소되었습니다*")
                cleanup(thread_ts)
                return

            # 라운드 시작 전 스레드에서 사용자 메시지 수집
            user_messages = self._fetch_user_messages(channel, thread_ts)
            for um in user_messages:
                if um not in [h["text"] for h in history if h["name"] == "사용자"]:
                    history.append({"name": "사용자", "text": um})
                    print(f"[DEBUG] 사용자 의견 반영: {um[:50]}")

            self._post(channel, thread_ts, f"--- *라운드 {round_num}* ---")

            round_consensuses: list[dict | None] = []

            # 매 라운드 순서 랜덤
            shuffled = list(self.agents)
            random.shuffle(shuffled)

            # 에이전트별 생각 중 표시 + 경과 시간
            thinking_msgs = {}
            handlers = {}
            for agent in shuffled:
                msg = self.slack.chat_postMessage(
                    channel=channel, thread_ts=thread_ts,
                    text=f"💭 {agent.emoji} *[{agent.name}]* 생각 중..."
                )
                thinking_msgs[agent.name] = msg["ts"]
                handlers[agent.name] = self._make_progress_handler(
                    channel, thread_ts, msg["ts"], agent)

            # 3개 AI 동시 실행, 완료 즉시 포스트 (slowest 대기 공백 제거)
            prompt = self._build_prompt(topic, history, round_num, issue_note=pending_issue)

            async def _ask_and_post(a):
                stop, cb = handlers[a.name]
                result = await a.ask_with_progress(prompt, on_progress=cb, attachments=attachments)
                stop.set()
                try:
                    self.slack.chat_delete(channel=channel, ts=thinking_msgs[a.name])
                except Exception:
                    pass
                # 완료 즉시 응답 포스트 (실제 완료 순서대로 사용자에게 표시)
                self._post(channel, thread_ts, a.format_message(_strip_consensus(result)))
                return result

            responses = await asyncio.gather(
                *[_ask_and_post(agent) for agent in shuffled]
            )

            # history/consensus는 shuffled 순서로 기록 (재현성 유지)
            for agent, response in zip(shuffled, responses):
                history.append({"name": agent.name, "text": response})
                round_consensuses.append({
                    "agent_name": agent.name,
                    "agent_emoji": agent.emoji,
                    "consensus": _parse_consensus(response),
                })

            # 오류/타임아웃된 에이전트 → 백업 투입 + 이후 라운드 교체
            for agent, response in zip(shuffled, responses):
                if getattr(agent, 'needs_replacement', False):
                    backup = self._get_backup(agent)
                    if not backup:
                        continue
                    reason = "타임아웃" if getattr(agent, 'timed_out', False) else "오류 감지"
                    self._post(channel, thread_ts, f"⚠️ *{agent.name} {reason} → {backup.name} 대체 투입*")
                    thinking = self.slack.chat_postMessage(
                        channel=channel, thread_ts=thread_ts,
                        text=f"💭 {backup.emoji} *[{backup.name}]* 생각 중..."
                    )
                    backup_response = await backup.ask(prompt, attachments=attachments)
                    try:
                        self.slack.chat_delete(channel=channel, ts=thinking["ts"])
                    except Exception:
                        pass
                    self._post(channel, thread_ts, backup.format_message(_strip_consensus(backup_response)))
                    history.append({"name": backup.name, "text": backup_response})
                    round_consensuses.append({
                        "agent_name": backup.name,
                        "agent_emoji": backup.emoji,
                        "consensus": _parse_consensus(backup_response),
                    })
                    # 다음 라운드부터 이 에이전트를 백업으로 교체
                    self._replace_agent(agent, channel, thread_ts, reason)

            # 합의 평가: 요약 발산 감지 후 반동조 게이트 적용
            diverged, issue_note = _summaries_diverge(round_consensuses)
            agrees = _count_agrees(round_consensuses)
            round_history.append({"agrees": len(agrees), "diverged": diverged})
            curr_summaries = _round_summaries(round_consensuses)
            no_progress = prev_summaries is not None and _no_progress(prev_summaries, curr_summaries)
            prev_summaries = curr_summaries
            outlier_history.append(_pair_outlier(round_consensuses, skip_names=self._replaced))
            persistent_outlier = _persistent_outlier(outlier_history)
            print(f"[DEBUG] Round {round_num} agrees: {len(agrees)}/{len(round_consensuses)} diverged={diverged} no_progress={no_progress} outlier={outlier_history[-1]} persistent={persistent_outlier}")

            can_conclude = round_num >= min_rounds

            if can_conclude and len(agrees) >= 3:
                if diverged and not divergence_challenged:
                    # 발산 상태인데 전원 agree=true 이고 아무도 차이를 안 다룸:
                    # 영구 차단이 아니라 딱 1회 교전 라운드만 강제한다.
                    divergence_challenged = True
                    pending_issue = issue_note
                else:
                    header = self._build_conclusion(
                        "전원 합의 도달", round_num, topic, round_consensuses,
                        issue_note=issue_note if diverged else None,
                    )
                    final = await self._generate_final_answer(topic, history, round_consensuses)
                    self._broadcast(channel, thread_ts, f"{header}\n\n💡 *합의된 답변:*\n{final}")
                    return
            elif can_conclude and len(agrees) >= 2 and self._is_stalemate(round_history):
                # 2개 동의 + 교착 상태: 다수결 종료 (미해결 쟁점 명시)
                header = self._build_conclusion(
                    f"다수 합의 (교착 상태, {len(agrees)}/3 동의)", round_num, topic,
                    round_consensuses, issue_note=issue_note if diverged else None,
                )
                final = await self._generate_final_answer(topic, history, round_consensuses)
                self._broadcast(channel, thread_ts, f"{header}\n\n💡 *합의된 답변:*\n{final}")
                return
            elif can_conclude and persistent_outlier:
                # 2-vs-1 outlier 가 2R 연속 같은 에이전트: agree 카운트 무관하게
                # 다수 페어 입장으로 종료 (Slack thread 1779271920 패턴: Claude·Codex 합의,
                # Gemini 출처 없는 인용 고집해서 agrees<2 로 stalemate 도 발동 안 되던 케이스).
                header = self._build_conclusion(
                    f"다수 합의 (2/3, {persistent_outlier} 이견 지속)", round_num, topic,
                    round_consensuses, issue_note=issue_note if diverged else None,
                )
                final = await self._generate_final_answer(topic, history, round_consensuses)
                self._broadcast(channel, thread_ts, f"{header}\n\n💡 *합의된 답변:*\n{final}")
                return
            elif can_conclude and no_progress:
                # 모든 에이전트가 직전 라운드를 그대로 반복 = 추가 토론은 토큰 낭비.
                # agree/발산에 무관하게 종료 (실시간/사실 주제의 무한 반복 방지).
                title = (f"다수 합의 (수렴, {len(agrees)}/3 동의)"
                         if len(agrees) >= 2
                         else "토론 종료 (합의 불발, 추가 진전 없음)")
                header = self._build_conclusion(
                    title, round_num, topic,
                    round_consensuses, issue_note=issue_note if diverged else None,
                )
                final = await self._generate_final_answer(topic, history, round_consensuses)
                self._broadcast(channel, thread_ts, f"{header}\n\n💡 *합의된 답변:*\n{final}")
                return
            else:
                # 발산 시에만 다음 라운드에 미해결 쟁점 주입
                pending_issue = issue_note if diverged else None
        else:
            # Max rounds exhausted
            header = self._build_conclusion(
                f"최대 라운드({MAX_DEBATE_ROUNDS}) 도달", MAX_DEBATE_ROUNDS, topic,
                round_consensuses, issue_note=pending_issue,
            )
            final = await self._generate_final_answer(topic, history, round_consensuses)
            self._broadcast(channel, thread_ts, f"{header}\n\n💡 *합의된 답변:*\n{final}")

    def _build_prompt(
        self, topic: str, history: list[dict], round_num: int,
        issue_note: str | None = None,
    ) -> str:
        """Build prompt with topic, recent history, and round-aware instructions.

        라운드 1: 아직 상대 발언이 없음 → 사용자 메시지만 노출, 본인 독립 견해만.
                 (today_conclusions 등 에이전트 라벨 섞인 히스토리는 라운드 1에서 제외)
        라운드 2+: 라운드 1 발언을 검토/반박/보완.
        """
        # 라운드 1: 에이전트 라벨 섞인 히스토리(이전 토론 결론 등) 제거, 사용자 메시지만
        if round_num == 1:
            filtered = [h for h in history if h.get("name") == "사용자"]
        else:
            filtered = history
        recent = filtered[-10:] if len(filtered) > 10 else filtered

        parts = [
            SYSTEM_PROMPT,
            f"\n[토론 주제] {topic}",
            f"[현재 라운드] {round_num}/{MAX_DEBATE_ROUNDS}",
        ]

        if recent:
            parts.append("\n[이전 발언]")
            for entry in recent:
                parts.append(f"- {entry['name']}: {entry['text'][:300]}")

        if round_num == 1:
            parts.append(
                "\n⚠️ 이번은 **라운드 1**입니다. 아직 다른 에이전트의 발언이 없습니다.\n"
                "- 다른 에이전트가 무슨 말을 했을지 추측/가정/언급하지 마세요.\n"
                "- '다른 에이전트', '상대', '앞서 언급된', '한 에이전트는' 같은 표현 금지.\n"
                "- 라운드 1의 agree 필드는 반드시 false로 설정하세요 (비교할 발언이 없음).\n"
                "- 사용자 질문에 본인의 독립적 견해만 구체적으로 제시하세요. (500자 이내)"
            )
        else:
            parts.append(
                "\n위 [이전 발언] 중 **본인 의견과 다른 지점**이 있으면, 해당 에이전트와 그 주장을 "
                "구체적으로 인용해 왜 동의하지 않는지 명시하고 CONSENSUS의 disagreements에 기록하세요. "
                "의견이 실제로 같으면 같다고 밝혀도 됩니다(억지 반박 금지). "
                "단, 차이를 얼버무리거나 상대 발언을 무시한 병렬 독백은 금지합니다. "
                "사용자 요구사항에 직접 답변하고, 구체적 정보(이름, 수치, 목록 등)를 포함하세요. (500자 이내)"
            )
            if issue_note:
                parts.append(
                    f"\n⚠️ 직전 라운드 **미해결 쟁점**입니다. 회피하지 말고 정면으로 다루세요:\n{issue_note}"
                )
        return "\n".join(parts)

    @staticmethod
    def _is_stalemate(round_history: list[dict]) -> bool:
        """라운드 스냅샷 기반 교착 감지.

        round_history: 라운드별 {"agrees": int, "diverged": bool} 스냅샷.
        최근 2개 라운드가 모두 발산이고 합의 수가 늘지 않았으면 교착.
        """
        if len(round_history) < 2:
            return False
        a, b = round_history[-2], round_history[-1]
        return bool(
            a.get("diverged")
            and b.get("diverged")
            and b.get("agrees", 0) <= a.get("agrees", 0)
        )

    @staticmethod
    def _build_conclusion(title: str, round_num: int, topic: str, round_consensuses: list[dict], issue_note: str | None = None) -> str:
        """각 에이전트 요약 + 합의된 답변 구조의 결론 메시지 생성."""
        lines = [f"🏛️ *{title} (라운드 {round_num})*", f"주제: {topic}", ""]

        # 항상 각 에이전트 요약 표시
        lines.append("📋 *각 에이전트 요약:*")
        for r in round_consensuses:
            c = r.get("consensus")
            if c and c.get("summary"):
                lines.append(f"{r['agent_emoji']} {r['agent_name']}: {c['summary']}")

        if issue_note:
            lines.append(f"\n⚠️ *미해결 쟁점:* {issue_note}")

        return "\n".join(lines)

    def _select_final_answer_agent(self):
        """통합문 생성 에이전트 선택. 교체된 백업이 아닌 원본 에이전트 우선.

        원본이 하나도 없으면(전부 교체) None → 호출부가 결정론적 머지로 폴백.
        """
        for a in self.agents:
            if a.name not in self._replaced and not a.name.endswith("-B"):
                return a
        return None

    @staticmethod
    def _deterministic_merge(round_consensuses: list[dict]) -> str:
        """LLM 없이 각 에이전트 요약을 결정론적으로 나열."""
        lines = []
        for r in round_consensuses:
            c = r.get("consensus")
            if c and c.get("summary"):
                lines.append(f"{r['agent_emoji']} {r['agent_name']}: {c['summary']}")
        return "\n".join(lines)

    async def _generate_final_answer(self, topic: str, history: list[dict], round_consensuses: list[dict]) -> str:
        """합의된 에이전트들의 의견을 종합하여 하나의 통합 답변 생성."""
        summaries = []
        for r in round_consensuses:
            c = r.get("consensus")
            if c and c.get("agree") and c.get("summary"):
                summaries.append(f"- {r['agent_name']}: {c['summary']}")

        # 최근 토론 내용도 참고
        recent_history = []
        for h in history[-9:]:
            recent_history.append(f"- {h['name']}: {h['text'][:300]}")

        prompt = (
            "아래는 3명의 AI 에이전트가 토론 후 합의한 내용입니다.\n"
            f"사용자 질문: {topic}\n\n"
            "[각 에이전트 합의 요약]\n" + "\n".join(summaries) + "\n\n"
            "[최근 토론 내용]\n" + "\n".join(recent_history) + "\n\n"
            "위 내용을 종합하여 사용자의 질문에 대한 하나의 통합 답변을 작성하세요.\n"
            "규칙:\n"
            "- 에이전트들이 공통으로 추천/동의한 내용을 중심으로 정리\n"
            "- 구체적 정보(상품명, 수치, 링크 등)가 있으면 반드시 포함\n"
            "- 에이전트 이름을 언급하지 말고 하나의 합의된 답변으로 작성\n"
            "- 500자 이내"
        )

        # 통합문 생성: 교체 안 된 원본 에이전트 우선, 실패 시 다음 후보, 최종 결정론적 머지.
        # 핵심: agent.ask() 는 API 5xx/과부하를 예외가 아니라 "API Error: 500 ..." 문자열로
        # 정상 반환한다(try/except 로 못 잡음). 그래서 반환값이 에러/빈 응답인지 직접 검사해야
        # 그 에러 문자열이 "💡 합의된 답변" 으로 방송되는 회귀(thread 1780056574)를 막을 수 있다.
        candidates = [
            a for a in self.agents
            if a.name not in self._replaced and not a.name.endswith("-B")
        ]
        if not candidates:
            # 원본 전멸 → LLM 호출 없이 결정론적 머지
            return self._deterministic_merge(round_consensuses)

        for idx, agent in enumerate(candidates):
            # 첫 후보는 transient(5xx/과부하) 에러 시 1회 재시도 (인프라 에러 최대 1회 규칙).
            attempts = 2 if idx == 0 else 1
            for _ in range(attempts):
                try:
                    result = await agent.ask(prompt)
                except Exception:
                    break  # 이 후보 포기 → 다음 후보
                answer = _strip_consensus(result).strip()
                if not self._is_bad_final_answer(agent, answer):
                    return answer
                # 에러/빈 응답 → (남은 시도 있으면) 재시도, 없으면 다음 후보

        # 모든 후보 실패 → 결정론적 머지로 폴백 (에러 문자열 방송 방지)
        return self._deterministic_merge(round_consensuses)

    @staticmethod
    def _is_bad_final_answer(agent, answer: str) -> bool:
        """합의문으로 방송하면 안 되는 응답인지 판정.

        - 빈 응답
        - fatal error(5xx/과부하/쿼터/rate limit/세션 한도) 가 _is_fatal_error 로 감지된 경우
        - 타임아웃/취소 등 에이전트 내부 폴백 메시지(`[Name] ...`)
        """
        if not answer:
            return True
        if getattr(agent, "has_error", False) or getattr(agent, "timed_out", False):
            return True
        # 방어선(defense-in-depth): has_error 플래그가 어떤 이유로 안 잡혔더라도
        # fatal 패턴(세션 한도 등)이 답변 본문에 있으면 방송 차단. _is_fatal_error 는
        # _FATAL_SUBSTRINGS/_FATAL_REGEX 를 단일 소스로 쓰므로 탐지 계층과 자동 동기.
        # callable 가드: 비표준 에이전트가 동명의 호출불가 속성을 가져도 TypeError 방지.
        checker = getattr(agent, "_is_fatal_error", None)
        if callable(checker) and checker(answer):
            return True
        # "[Claude] 오류: ...", "[Codex] 응답 시간 초과 (...)", "[Gemini] 작업 취소됨" 등
        # 에이전트 내부 상태 메시지는 답변이 아니다.
        if answer.startswith(f"[{agent.name}]"):
            return True
        return False

    def _fetch_user_messages(self, channel: str, thread_ts: str) -> list[str]:
        """스레드에서 사용자(봇이 아닌)의 메시지를 가져온다."""
        try:
            if self._bot_user_id is None:
                self._bot_user_id = self.slack.auth_test()["user_id"]

            result = self.slack.conversations_replies(
                channel=channel, ts=thread_ts, limit=50
            )
            messages = result.get("messages", [])
            user_texts = []
            for msg in messages:
                # 봇 메시지 제외, 사용자 메시지만
                if msg.get("bot_id") or msg.get("user") == self._bot_user_id:
                    continue
                # 원본 메시지(토론 주제) 제외
                if msg.get("ts") == thread_ts:
                    continue
                text = msg.get("text", "").strip()
                if text:
                    user_texts.append(text)
            return user_texts
        except Exception as e:
            print(f"[SLACK ERROR] fetch replies: {e}")
            return []

    def _post(self, channel: str, thread_ts: str | None, text: str):
        """Post a message to Slack, optionally in a thread."""
        kwargs = {"channel": channel, "text": text}
        if thread_ts:
            kwargs["thread_ts"] = thread_ts
        try:
            self.slack.chat_postMessage(**kwargs)
        except Exception as e:
            print(f"[SLACK ERROR] {e}")

    def _broadcast(self, channel: str, thread_ts: str, text: str):
        """Post a message to thread AND show in channel (reply_broadcast)."""
        try:
            self.slack.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                text=text,
                reply_broadcast=True,
            )
        except Exception as e:
            print(f"[SLACK ERROR] {e}")
