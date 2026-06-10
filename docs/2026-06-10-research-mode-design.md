# 리서치 모드 + 근거 기반 협업 엔진 설계

- 작성일: 2026-06-10
- 대상 버전: v0.8.0
- 상태: 설계 확정 (구현 계획 작성 전)

## 1. 배경과 목표

AI Squad 는 현재 토론(3 AI 자유토론+합의), 코딩 파이프라인, 브릿지 모드를 제공한다. 다음 발전 방향으로 **기능 확장**을 택했고, 그 안에서 두 가지를 원했다.

1. 토론 모드 고도화 (웹 사실검증 + 출처 + 상호 검증)
2. 새 모드: 리서치/조사 (3 AI 가 웹 조사를 분담 → 교차검증 → 출처 달린 리포트)

이 둘은 **같은 코어**를 공유한다: 웹 근거 수집, 상호 교차검증, 출처/인용. 따라서 "근거 기반 협업 엔진"을 한 번 만들고 두 모드로 노출한다.

**이 문서의 범위는 Phase 1 으로 한정한다**: 엔진 + 리서치 모드. 토론 고도화는 이 엔진을 재사용하는 별도 스펙(Phase 2)으로 분리한다.

### 성공 기준
- `#ai-리서치` 채널에 질문을 던지면, 3 AI 가 분담 조사 + 교차검증한 **출처 달린 리포트**가 스레드로 돌아온다.
- 검증되지 않았거나 충돌하는 주장은 드롭하지 않고 리포트에 명시된다(쟁점·불확실 섹션).
- 한 에이전트가 죽어도(타임아웃/rate limit) 백업 투입으로 결과가 나오며, 끝내 빈 부분은 "미완료"로 표기된다.

## 2. 협업 모델: 분담형 팬아웃 (Approach A)

질문을 하위 주제로 분해 → 에이전트별 조사 분담 → 병합 → **생산자가 아닌 다른 에이전트가 교차검증** → 출처 달린 통합 리포트.

선택 이유: 사용자가 떠올린 "분담" 의도와 일치, 커버리지·속도가 좋고, 생산자≠검증자 구조라 교차검증이 자연스럽게 신뢰도를 올린다.

대안(채택 안 함):
- B. 독립 조사 → 합의/충돌: 단순·견고하나 작업 중복, 넓은 주제에서 얕음.
- C. 초안-검증 파이프라인: 검증 강하나 1차 병목 + 순차라 느림.

## 3. 트리거 / 라우팅

- 기존 패턴(debate=채널, bridge=채널+prefix)을 따라 **전용 채널 `#ai-리서치`** 신설. `RESEARCH_CHANNEL_ID` env 로 바인딩.
- 채널 신규 메시지 → 리서치 시작. 스레드 답글 → 후속 심화 질문(맥락 유지).
- `modes/research.py` 의 `ResearchMode` 클래스가 오케스트레이션 (구조는 `modes/debate.py` 와 동일).
- `slack_bot.py` 라우팅에 리서치 채널 분기 추가.

## 4. 파이프라인 (엔진 5단계, 전부 Python 코드 오케스트레이션)

| 단계 | 내용 | 담당 |
|------|------|------|
| 0. 분해 | 질문 → 하위 주제 3~6개를 구조화 JSON 으로 | claude 1회 (저비용) |
| 1. 분담 조사 | 하위 주제를 3 에이전트에 분배 → 각자 웹 조사 → 발견+출처 반환 | claude/codex/gemini 병렬 |
| 2. 교차검증 | 각 발견을 생산자가 아닌 다른 에이전트가 검증(출처 확인·반증 탐색) → supported/disputed/unverified 판정 | 교차 배정 |
| 3. 종합 | 검증된 발견을 출처 달린 리포트로 통합 (+ 쟁점·불확실 섹션) | claude (fallback 가용 에이전트) |
| 4. 전송 | 4000자 분할 스레드 전송 (기존 `_post_long`) | - |

### 진행 표시
각 단계 진입 시 스레드 메시지를 갱신: "💭 분해 중 → 🔎 조사 중(3) → 🔬 교차검증 중 → 📝 종합 중". 기존 "생각 중" 패턴의 확장.

## 5. 엔진 구성요소 (분리·재사용 가능 단위)

`ResearchMode`(오케스트레이션) 와 분리해 순수 함수/헬퍼로 둔다. Phase 2(토론 고도화)에서 그대로 import.

- `decompose(question) -> list[SubQuestion]`: claude 호출 + JSON 파싱(견고). 실패 시 단일 질문 1개로 degrade.
- `fan_out_research(subqs, agents) -> list[Finding]`: 하위 주제를 에이전트에 분배, `asyncio.gather` 병렬 조사. gemini 동시성 세마포어 준수.
- `cross_verify(findings, agents) -> list[Verdict]`: 각 발견을 생산자≠검증자 에이전트에 배정해 검증.
- `synthesize(findings, verdicts, question) -> Report`: claude 가 출처 달린 마크다운 리포트 작성(긴 구조화 종합에 가장 안정적). claude 가용 불가 시 가용 에이전트로 fallback.

배치(위치) 후보: `modes/research.py` 안에 헬퍼로 시작하되, 모듈 상단에 명확한 함수 경계로 분리해 두어 Phase 2 에서 `research_engine.py` 로 추출 가능하게 한다. (Phase 1 에서는 과도한 추상화 금지 - YAGNI.)

## 6. 데이터 구조 (단계 간 인터페이스)

```
SubQuestion = {id: str, text: str, assigned_agent: str}
Finding     = {subq_id: str, agent: str, claim: str, sources: list[{title, url}], raw: str}
Verdict     = {finding_id: str, verifier: str, status: "supported"|"disputed"|"unverified", note: str}
Report      = str  # 마크다운: 본문 + 출처 목록 + 쟁점·불확실 섹션
```

각 단계는 위 구조만 주고받아 독립 테스트가 가능하다.

## 7. 기존 인프라 재사용 (신규 제작 안 함)

- **에이전트 풀 + 백업 투입**: 타임아웃/fatal 시 `needs_replacement` 로 백업 에이전트 자동 대체 (debate 와 동일).
- **병렬 + gemini 동시성 세마포어**: 1단계 조사는 `asyncio.gather`, gemini 직렬화 락 그대로 적용.
- **취소(cancel) / 보안 env 필터(make_filtered_env) / 토큰 사용량 / `_post_long` 분할 / watchdog**: 전부 재사용.
- **웹 도구**: claude `--allowedTools WebSearch WebFetch`(이미 적용), gemini 그라운딩, codex web search. 세 에이전트 모두 웹 조사 가능 확인됨.
- **MCP**: v0.7.11 의 `--strict-mcp-config` 유지 (전역 MCP 미로드).

## 8. 에러 처리 (조용한 누락 금지 - 글로벌 규칙)

- 분해 실패 → 단일 질문 통째 조사로 graceful degrade.
- 하위 주제 조사 타임아웃 → 백업 에이전트 인계, 그래도 실패 시 해당 주제 "미완료"로 명시 표기(드롭 금지).
- 교차검증 충돌 → 드롭 대신 `disputed` 로 리포트에 노출.
- 출처 없는 주장 → `unverified` 플래그.
- 웹 결과 없음/모순 → 리포트에 솔직히 기술.
- 분배 시 가용 에이전트 3개 미만(쿨다운 등) → 가용 에이전트로 라운드로빈 재분배, 0개면 에러 알림.

## 9. 테스트

- **단위 테스트** (기존처럼 에이전트 mock):
  - 분해 JSON 파싱 견고성(코드펜스/잡음 포함 출력, 파싱 실패 fallback)
  - 분배 로직(에이전트 3개 / 2개 / 1개 케이스, 라운드로빈)
  - 교차검증 배정(생산자≠검증자 보장)
  - 판정 집계(supported/disputed/unverified)
  - 출처 추출·포맷, 4000자 분할
- **라이브 스모크 1회**: 실제 질문 → 리포트 산출 확인.
- **Codex 교차검증**: 구현 후 정합성/부작용 검증 (글로벌 규칙).

## 10. 설정 / 버전 / 기록

- 새 env: `RESEARCH_CHANNEL_ID`(필수), `RESEARCH_SUBQ_MAX`(기본 6), 리서치 단계 타임아웃(기본값은 기존 `CLI_TIMEOUT` 재사용).
- `.env.example`, `README.md`(채널 표), `SETUP.md` 갱신.
- 버전: 새 모드 추가 → **v0.8.0** (minor).
- 기록 순서(글로벌 규칙): 교차검증 통과 → RELEASE_NOTES → issue_log → git commit/push → GitHub Issues 등록·close.

## 11. 범위 밖 (이번 Phase 에서 안 함)

- 토론 모드 고도화(엔진 재사용) → Phase 2 별도 스펙.
- Canvas/PDF/HTML 산출물 → 이번엔 Slack 스레드 메시지만.
- 영구 저장/검색 인덱스, 리포트 아카이브 → 추후.
