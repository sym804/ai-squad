"""라운드 1에서 각 에이전트가 상대 의견을 참조하는지 직접 확인.

두 시나리오:
  A: 순수 라운드 1 (today_conclusions 없음, history 비어있음)
  B: today_conclusions 오염 (이전 스레드 결론에 에이전트 라벨이 섞여 들어감)

각 에이전트에 실제 프롬프트를 던져 응답을 관찰한다.
"""
import asyncio
import sys
import os
import re

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from agents import ClaudeAgent, CodexAgent, GeminiAgent
from modes.debate import DebateMode

# 실제 DebateMode._build_prompt 를 그대로 호출 (slack_client 필요 없음)
_debate = DebateMode(slack_client=None)


def build_prompt(topic: str, history: list[dict], round_num: int) -> str:
    return _debate._build_prompt(topic, history, round_num)


# 상대 의견 참조 검출 패턴
REF_PATTERNS = [
    r"claude(?:가|는|의|와|도|처럼|에\s*따르면)",
    r"codex(?:가|는|의|와|도|처럼|에\s*따르면)",
    r"gemini(?:가|는|의|와|도|처럼|에\s*따르면)",
    r"다른\s*에이전트",
    r"상대(?:방)?의?\s*(?:의견|주장|견해|말)",
    r"앞서\s*(?:언급|말|말씀)",
    r"위에서?\s*(?:언급|말)",
    r"동료\s*에이전트",
    r"타\s*에이전트",
]
REF_REGEX = re.compile("|".join(REF_PATTERNS), re.IGNORECASE)


def detect_peer_refs(text: str) -> list[str]:
    """상대 에이전트 참조 표현 검출."""
    return REF_REGEX.findall(text or "")


async def run_agent(agent, prompt: str, label: str) -> str:
    print(f"\n>>> {label}: {agent.name} 호출 중...", flush=True)
    try:
        result = await agent.ask(prompt, timeout=180)
    except Exception as e:
        return f"[ERROR] {e}"
    return result or "(빈 응답)"


async def run_scenario(name: str, topic: str, history: list[dict], round_num: int = 1):
    print(f"\n{'='*70}")
    print(f"시나리오 {name}")
    print(f"{'='*70}")

    prompt = build_prompt(topic, history, round_num=round_num)
    print(f"\n--- 전달 프롬프트 (길이 {len(prompt)}자) ---")
    print(prompt)
    print("--- 프롬프트 끝 ---\n")

    agents = {
        "Claude": ClaudeAgent(),
        "Codex": CodexAgent(),
        "Gemini": GeminiAgent(),
    }

    # 병렬 실행 (실제 debate와 동일)
    results = await asyncio.gather(
        *[run_agent(a, prompt, name) for a in agents.values()]
    )

    summary = []
    for (label, agent), result in zip(agents.items(), results):
        refs = detect_peer_refs(result)
        print(f"\n--- [{label}] 응답 ({len(result)}자) ---")
        print(result[:1500])
        if len(result) > 1500:
            print(f"... (총 {len(result)}자)")
        if refs:
            print(f"\n[검출] 상대 에이전트 참조 표현: {refs}")
        else:
            print("\n[검출] 상대 에이전트 참조 없음")
        summary.append((label, len(refs), refs))

    return summary


async def main():
    topic = "오늘 저녁 메뉴로 라멘과 파스타 중 뭐가 나아?"

    # 시나리오 A: 완전히 깨끗한 라운드 1
    history_a: list[dict] = []

    # 시나리오 B: today_conclusions 오염 (실제 포맷 그대로)
    fake_prior_conclusion = (
        "🏛️ *전원 합의 도달 (라운드 2)*\n"
        "주제: 점심 메뉴 추천\n\n"
        "📋 *각 에이전트 요약:*\n"
        "🟠 Claude: 김치찌개가 추천됩니다.\n"
        "🟢 Codex: 돈까스가 가성비 좋습니다.\n"
        "🔵 Gemini: 비빔밥이 영양 균형에 좋습니다."
    )
    history_b = [{"name": "이전 토론 결론", "text": fake_prior_conclusion}]

    # 시나리오 C: 라운드 2 회귀 — 라운드 1 발언이 히스토리에 있고, 상대 검토가 실제로 되는지
    history_c = [
        {"name": "Claude", "text": "라멘 추천. 쌀쌀한 저녁엔 뜨끈한 돈코츠 국물이 체온 유지에 좋고, 1그릇으로 완결된 한 끼."},
        {"name": "Codex", "text": "파스타 추천. 오일/토마토 파스타는 15분에 조리 가능, 덜 무겁고 나트륨 부담 적음."},
        {"name": "Gemini", "text": "라멘 추천. 돼지 사골 육수가 든든하고 차슈·아지타마고로 단백질 구성도 준수."},
    ]

    results_a = await run_scenario("A (깨끗한 라운드 1)", topic, history_a, round_num=1)
    results_b = await run_scenario("B (이전 결론 오염, 라운드 1)", topic, history_b, round_num=1)
    results_c = await run_scenario("C (라운드 2 — 상대 검토 확인)", topic, history_c, round_num=2)

    print(f"\n{'='*70}")
    print("최종 요약")
    print(f"{'='*70}")
    for scenario_name, results, expect_refs in [
        ("A 라운드1 (참조 0이어야 함)", results_a, False),
        ("B 라운드1 (참조 0이어야 함)", results_b, False),
        ("C 라운드2 (참조 >=1 이어야 함)", results_c, True),
    ]:
        print(f"\n시나리오 {scenario_name}:")
        for label, count, refs in results:
            if expect_refs:
                mark = "✅" if count > 0 else "⚠️"
            else:
                mark = "🚨" if count > 0 else "✅"
            print(f"  {mark} {label}: 상대참조 {count}건 {refs if refs else ''}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(main())
