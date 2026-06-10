# Release Notes

슬랙 멀티 에이전트 봇 릴리즈 히스토리. 날짜별로 묶인 주요 변경사항과 대응 커밋을 기록합니다.

## 버전 테이블

| 버전 | 날짜 | 요약 |
|------|------|------|
| v0.1.0 | 2026-04-02 | 초기 릴리즈 + watchdog |
| v0.2.0 | 2026-04-04 | Bridge 모드, 코딩 모드 개선, 스트리밍, Codex 노이즈 정리 |
| v0.3.0 | 2026-04-05 | Windows 호환성 + 보안 화이트리스트 + shell=True 제거 |
| v0.4.0 | 2026-04-10 | Gemini 안정화 + watchdog_guard + 토론 통합 답변 |
| v0.4.1 | 2026-04-11 | Gemini 모델 교체 + readline 타임아웃 + 토론 환각 방지 |
| v0.4.2 | 2026-04-12 | 토론 응답 즉시 포스트 |
| v0.5.0 | 2026-04-13 | 에이전트 실행 안정화 + CLI 헬스체크 + 단위 테스트 |
| v0.5.1 | 2026-04-21 | 부팅 크래시 루프 핫픽스 |
| v0.6.0 | 2026-05-08 | 이미지 첨부 분석 (Claude/Gemini Vision SDK) |
| v0.6.1 | 2026-05-08 | 이미지 첨부를 CLI prompt 첨부 방식으로 정정 (API 키 의존 제거) |
| v0.6.2 | 2026-05-08 | file_share/thread_broadcast subtype 차단 회귀 수정 (텍스트+이미지 라우팅 복구) |
| v0.6.3 | 2026-05-09 | Claude readline 64KB 한계 수정 + Codex/Gemini 노이즈 누출 정리 + Gemini vision 가드 |
| v0.6.4 | 2026-05-12 | 코딩 모드 Phase 1 게이트 (Claude 코드 완성 전 Codex/Gemini 자동 진입 차단) |
| v0.7.0 | 2026-05-19 | 토론 시스템 6대 개선 (교착 재설계, 백업 풀 분산, 파싱 견고화, 통합문 분리, 난이도 라우팅, 조건부 반박) |
| v0.7.1 | 2026-05-19 | 자기-반복(no-progress) 조기 종료 (실시간/사실 주제 무한 반복·토큰 낭비 차단) |
| v0.7.2 | 2026-05-20 | Antigravity CLI(agy) 마이그레이션 준비: GEMINI_CLI_BINARY 환경변수 토글 + agy 분기 |
| v0.7.2.1 | 2026-05-20 | Codex 교차검증 피드백 반영: cmd /c 셸 파싱 우회 + argv 길이 가드 + _build_cmd 안전성 강화 |
| v0.7.3 | 2026-05-20 | 2-vs-1 deadlock 조기 종료: agree=true 의미 완화 + 페어 outlier 명시 감지 |
| v0.7.3.2 | 2026-05-20 | Gemini 이벤트 루프 회귀(Semaphore 멀티-루프 바인딩) 핫픽스 + 외부 timeout 가드 |
| v0.7.3.3 | 2026-05-20 | v0.7.3.2 Codex 교차검증 Block/Major 핫픽스: _run_progress_once 누락 교체 + cancel cleanup |
| v0.7.4 | 2026-05-26 | PDF 첨부 지원 (이미지에 더해 application/pdf 도 각 CLI read 도구로 직접 처리) + 전체 images → attachments 리네이밍 |
| v0.7.5 | 2026-05-26 | PDF 첨부 실전 회귀 핫픽스: Gemini workspace 격리 + Codex read 도구 PDF 미지원 → tmp_dir 을 workspace 내부 (.tmp/) 로 + pypdf 텍스트 prompt 인라인 첨부 |
| v0.7.6 | 2026-05-26 | v0.7.5 자체 핫픽스: slack_bot.py 의 os import 누락으로 PDF/이미지 첨부 시 _runner NameError → 무응답. import os 추가 + 회귀 테스트 |
| v0.7.7 | 2026-05-29 | 합의된 답변이 "API Error: 500" 로 방송되는 회귀 수정: 5xx/과부하 fatal 감지 추가 + 통합문 생성 에러 가드(재시도/폴백) |
| v0.7.8 | 2026-05-29 | Gemini "True color (24-bit) support not detected" 터미널 경고 누출 수정 (노이즈 필터 키워드 일반화) |
| v0.7.9 | 2026-06-08 | 토론 "미해결 쟁점"이 각 에이전트 요약/합의된 답변과 중복되던 문제 수정 (disagreements 필드 소비, summary 폴백 제거) |
| v0.7.10 | 2026-06-09 | agy `-p` stdout 미출력 버그(upstream #76) 우회: 응답을 디스크 transcript 에서 호출별 trace 토큰으로 복구해 비대화형 회수 |
| v0.7.11 | 2026-06-10 | Windows cmd 콘솔 깜빡임 제거: claude 호출에 `--strict-mcp-config` 추가해 전역 MCP(context7 npx) spawn 차단 |
| v0.8.0 | 2026-06-11 | 리서치 모드 신설: #ai-리서치 채널에서 3 AI 분담형 팬아웃(분해→분담 조사→교차검증→출처 리포트) |
| v0.8.1 | 2026-06-11 | 리서치 종합 답변 채널 브로드캐스트 + 봇 비대화형(S4U) 전환 + agy statusline 깜빡임 제거 |

## v0.8.1 (2026-06-11)

v0.8.0 리서치 모드 실사용 중 발견된 2건 수정 + 봇 실행 방식 강화.

### 수정
- **[Minor / backend]** 리서치 최종 종합 답변이 스레드에만 남고 채널 타임라인엔 안 보이던 문제 수정. debate 처럼 `_broadcast_long`(첫 청크 `reply_broadcast=True`)로 종합 답변을 채널에도 노출, 상세 출처/쟁점 리포트는 스레드 유지. 회귀 테스트 포함(26건). 라이브 확인 완료.
- **[Minor / etc]** Windows cmd 콘솔 깜빡임(agy statusline) 제거. 원인: agy 가 statusline 을 주기적으로 셸(`cmd /c`·`sh -c`)로 실행 → 그 셸 콘솔이 깜빡임. 세션 격리(S4U)는 상시 로그인 시 같은 세션이라 무효, 명령 변경도 agy 가 항상 셸 래핑이라 무효. 최종적으로 agy 전역 설정 `statusLine.enabled=false`로 비활성(사용자 선택). 격리 실측으로 새 agy 가 statusline 0건 확인. (v0.7.11 의 claude context7 와는 별개 원인)
- **[Minor / etc]** watchdog 운영 강화: 예약작업을 S4U(LogonType)로 재등록해 **로그아웃해도 봇 유지**(기존 Interactive only 는 로그아웃 시 종료). S4U 예약작업의 Job Object 가 task 종료 시 자식을 회수하는 문제는 watchdog 를 `DETACHED_PROCESS | CREATE_BREAKAWAY_FROM_JOB` 로 분리 기동해 해결(생존 검증 완료). `watchdog.py` 봇 기동에 `CREATE_NO_WINDOW` 보강, `install_task` 실패 메시지 cp949 안전 출력. 일괄 전환용 `migrate_session0.ps1`(UTF-8 BOM) 추가.

### 검증
- 리서치 브로드캐스트: #ai-협업 채널 타임라인에 종합 답변 표출 확인.
- 깜빡임: 특정 agy PID 자식 트리 격리 실측 → statusline.bat/.py 0건.
- S4U breakaway: 예약작업 종료 후에도 watchdog/bot 생존(20초 후 PID 유지) 확인.

## v0.8.0 (2026-06-11)

새 **리서치 모드** 추가. `#ai-리서치` 채널에 질문을 던지면 3 AI 가 분담형 팬아웃으로 웹 조사해 출처 달린 리포트를 스레드로 돌려준다. 토론 고도화(Phase 2)와 공유할 "근거 기반 협업 엔진"을 분리 가능한 함수 경계로 구현. (단위 25건 + 라이브 슬랙 3건 실증 + Codex 교차검증 통과)

### 배경
기능 확장 방향으로 (1) 토론 고도화와 (2) 리서치 모드를 원했고, 둘은 웹 근거 수집·상호 교차검증·출처라는 같은 코어를 공유한다. 이를 한 번 만들어 두 모드로 노출하기로 하고, Phase 1 에서 리서치 모드를 먼저 구현했다. 설계: `docs/2026-06-10-research-mode-design.md`.

### 기능 (5단계 파이프라인, 전부 Python 코드 오케스트레이션)
- **[Major / backend]** `modes/research.py` 신설. ResearchMode 가 분해(claude, 하위질문 JSON) → 하위질문 라운드로빈 분담 조사(claude/codex/gemini 병렬, 웹) → **생산자!=검증자** 교차검증(병렬, supported/disputed/unverified 판정) → claude 종합 → Slack 스레드 전송(`_post_long` 4000자 분할)을 오케스트레이션. 진행 단계를 스레드에 표시(💭분해→🔎분담조사→🔬교차검증→📝종합). 순수 엔진 함수(`_parse_subquestions`/`_assign_subquestions`/`_assign_verifiers`/`_extract_sources`/`_parse_verdict`/`_format_report`/프롬프트 빌더)는 Phase 2 재사용 위해 분리.
- **[Major / backend]** `config.py` `RESEARCH_CHANNEL_ID`/`RESEARCH_SUBQ_MAX`, `slack_bot.py` 라우팅 분기(미설정 시 비활성 가드). 기존 에이전트 풀·백업 인계·취소·gemini 동시성·`_post_long` 재사용. claude 호출은 v0.7.11 `--strict-mcp-config` 유지.
- **[Minor / backend]** 견고성: 분해 실패 시 단일질문 degrade, 조사/검증 태스크는 `asyncio.gather(return_exceptions=True)` 로 한 에이전트 실패가 전체를 중단시키지 않음(조사 실패는 건수 표기 후 제외=조용한 누락 금지, 검증 실패는 unverified 대체). `_ask_named` 는 primary 예외 시 try/except 백업 인계, disputed/unverified 는 리포트에 드롭 없이 표기.

### 검증
- 단위 테스트 `tests/test_research.py` 25건(파싱·배정·출처추출·판정·리포트·프롬프트 + 오케스트레이션 mock + 예외 견딤). 전체 통과.
- **라이브 슬랙 실증 3건**(#ai-협업 스레드): 사실/실시간형(전기차 보조금), 비교/분석형(RAG vs 파인튜닝), 광범위 조사형(QA 채용 트렌드). 분해 6개 → 분담조사 → 교차검증 → 종합 → 출처 리포트 흐름이 스레드에 정상 표출, 실제 출처 URL(korea.kr/me.go.kr/zdnet/ev.or.kr 등) 첨부, disputed/unverified 가 검증자명과 함께 표기됨 확인. 3/3 exit 0.
- Codex 교차검증 통과: Major 2건(gather return_exceptions 누락, _ask_named 예외 미처리) 발견 → 즉시 반영·재검증.

## v0.7.11 (2026-06-10)

슬랙 문의 시(에이전트 "생각 중" 진입 시점) Windows 콘솔 창이 잠깐 떴다 사라지는 깜빡임 제거. 라이브 프로세스 트리 추적으로 원인을 특정하고, 격리 비교 실측 + Codex 교차검증으로 검증.

### 배경 (근본 원인)
봇은 `cmd /c claude -p ...` 로 Claude Code CLI 를 호출하는데, 사용자 전역 Claude 설정에 등록된 MCP 서버 `context7`(`npx -y @upstash/context7-mcp`, stdio 방식)이 `claude` 부팅마다 `cmd /c npx ...` 로 새로 spawn 된다. `claude.exe` 가 `CREATE_NO_WINDOW`(숨김 콘솔)로 떠 있어 이 손자 프로세스가 부모의 숨김 콘솔을 못 물려받고 **새 conhost 콘솔을 할당** → 잠깐 떴다 사라지는 깜빡임으로 보인다. 나머지 전역 MCP(Drive/Gmail/Calendar/slack/github)는 HTTP 원격이라 로컬 프로세스를 안 띄워 무관. 봇 답변 경로는 MCP 도구를 쓰지 않으며 빌트인 `WebSearch/WebFetch/Read` 만 사용한다.

### 수정
- **[Minor / backend]** `agents/claude.py` `_build_cmd`/`_build_stream_cmd`, `modes/bridge.py` `_call_claude`: claude 호출 명령에 `--strict-mcp-config` 추가. 이 플래그는 `--mcp-config` 없이 주면 MCP 서버를 0개 로드(전역 MCP 무시)하므로 context7 npx spawn 자체가 사라진다. 부수 효과로 에이전트 부팅이 빨라지고, 봇이 사용자의 github/slack MCP 도구를 실수로 건드릴 여지도 없어진다. 첨부/백업/코딩/토론 경로는 모두 `ClaudeAgent` 경유라 두 빌더 수정으로 자동 커버. codex 의 유일한 MCP(`openaiDeveloperDocs`)는 `url=` HTTP 원격이라 로컬 콘솔을 안 띄워 손대지 않음.

### 검증
- **격리 비교 실측**: 동일 prompt 로 특정 PID 서브트리 추적. `--strict-mcp-config` 있음 → context7/npx 자식 spawn = False(깜빡임 없음), 없음(기존) → True(깜빡임 발생). 라이브로 원인·해소 모두 확인.
- 단위 테스트 `tests/test_agent_vision.py::test_strict_mcp_config_disables_global_mcp` 신규: 두 빌더 모두 `-p` 뒤·`--output-format` 앞 위치에 플래그가 들어가는지 순서까지 단언. vision/bridge/process 묶음 38건 통과.
- Codex 교차검증 통과: 4개 항목(플래그 위치 정합성·누락 호출부·부작용·codex 경로) 전부 통과, 발견 이슈 2건 모두 Trivial(외부 CLI 파서 미확정→라이브로 해소, 테스트 순서 미검증→순서 단언 보강).

## v0.7.10 (2026-06-09)

agy(Antigravity CLI)를 봇 백엔드로 쓸 수 있도록 `-p` stdout 미출력 버그를 우회. Gemini CLI 개인 티어가 2026-06-18 종료 예정이라 그 전에 agy 경로를 실사용 가능 상태로 준비. (Codex 3차 교차검증 통과 + 라이브 실측 3회)

### 배경 (upstream 버그)
Antigravity CLI `agy --print`/`-p` 가 non-TTY(pipe/subprocess/redirect) 컨텍스트에서 모델 응답을 stdout 에 쓰지 않는다 (exit 0 + 0 바이트). 공식 추적 이슈 `google-antigravity/antigravity-cli#76` 은 2026-06-09 기준 OPEN, 1.0.0~1.0.6 전 버전에서 재현되며 메인테이너 응답/수정 PR 없음. 봇이 stdout 을 파싱하므로 agy 백엔드(`GEMINI_CLI_BINARY=agy`)에선 빈 응답이 된다. 단 응답 본문은 디스크에 정상 저장된다(`~/.gemini/antigravity-cli/brain/<cid>/.system_generated/logs/transcript.jsonl`).

### 수정
- **[Major / backend]** `agents/gemini.py`: agy 빈 stdout 시 디스크 transcript 에서 응답 복구. 호출마다 고유 trace 토큰(`AGYTRACE`+uuid)을 prompt 끝에 심고(`_build_subprocess_args` 가 argv 절단 **이후** append 해 유실 방지), transcript 의 USER_INPUT 에서 그 토큰이 박힌 턴의 최종 `PLANNER_RESPONSE` 만 회수한다(`_recover_agy_response`/`_extract_traced_response`/`_iter_turns`/`_trace_in`). cwd→cid 매핑(`last_conversations.json`) 1차 + `since_ts` 이후 transcript 스캔 2차, 둘 다 토큰 매칭이라 공통 prompt prefix·대화 재사용·동시 호출에도 다른 호출 응답을 오회수하지 않는다. `_run_cli`/`_run_progress_once` 양쪽 통합. gemini 기본 경로는 토큰을 무시해 무영향.
- **[Minor / security]** cid 를 UUID 형식으로 검증(`_valid_cid`)해 `last_conversations.json` 경유 path traversal 을 차단(매핑·폴백 스캔 양 경로). transcript content 가 비문자열 스키마로 바뀌어도 죽지 않도록 `_as_text` 정규화. 모델이 trace 마커를 echo 하면 `_strip_trace` 로 제거.

### 검증
- 라이브 실측(봇과 동일한 `stdin=DEVNULL`): agy 1.0.6 가 `EXIT=0 / STDOUT_LEN=0`(버그 재현)인데 trace 토큰 복구로 응답을 정확히 회수(8~10초) + 마커 strip 확인.
- 단위 테스트 `tests/test_gemini.py::TestAgyDiskRecovery` 22건 신규(파싱·토큰 매칭·cid 검증·복구 경로·예외). 전체 통과.
- Codex 교차검증 3회 반영: 1차(prompt head 약점) → 2차(루프별 직렬화 한계·prefix 충돌·시간필터 부재) → 3차(토큰 방식으로 2차 Major 해소 확인 + 폴백 cid 검증/content 정규화 보강).
- 주의: PowerShell `& agy -p` 직접 호출은 stdin 상속으로 무한 hang(이슈 #76 보고). 봇은 `stdin=DEVNULL` 이라 영향 없음(실측 hang 없이 완주).

## v0.7.9 (2026-06-08)

토론 결론 메시지의 `⚠️ *미해결 쟁점:*` 이 각 에이전트의 `summary` 를 그대로 나열해, 같은 메시지의 `📋 각 에이전트 요약` 및 `💡 합의된 답변` 과 내용이 중복되던 문제 수정. (사용자 지적 + 자체 슬랙 E2E 3종 검증)

### 발생 원인
CONSENSUS JSON 스키마에는 실제 대립점을 담는 전용 `disagreements`(`[{agent, point, why}]`) 필드가 있고, 시스템 프롬프트가 에이전트에게 "동의하지 않으면 disagreements 에 기록하라" 고 지시한다. 그러나 코드 어디에서도 이 필드를 읽지 않는 **dead data** 였다. `_summaries_diverge()` 가 발산 시 쟁점 노트(issue_note)를 `disagreements` 가 아니라 각 에이전트 `summary[:120]` 로 만들었기 때문에, 결론의 "각 에이전트 요약"(summary 전체) 및 "합의된 답변"(agree=true summary 종합)과 같은 내용이 반복됐다. 이 노트는 다음 라운드 프롬프트에도 "미해결 쟁점" 으로 주입되어 수렴 유도 효과도 약화됐다.

### 수정
- **[Major / backend]** `modes/debate.py`: `_format_issue_note()` 헬퍼 신설. issue_note 를 각 CONSENSUS 의 `disagreements` point/why 로만 생성한다(`"{name}: {point} ({why})"`). 결론의 "각 에이전트 요약" 이 이미 모든 summary 를 나열하므로 summary 기반 노트는 항상 중복 → 구조적 대립점이 하나도 없으면 빈 문자열을 반환해 "미해결 쟁점" 줄 자체를 생략한다(표시·다음 라운드 주입 3곳 모두 `if issue_note:` 가드로 자동 생략). `_summaries_diverge()` 는 발산 감지(summary Jaccard)는 그대로 두고 consensus dict 를 함께 보관해 노트 생성에 넘긴다.
- 발산 감지(diverged 불리언)와 교전-강제(divergence_challenge) 로직은 변경 없음.
- 테스트: `tests/test_debate_improvements.py` 에 disagreements 우선 / 빈 노트 / malformed / 일부만 기록 케이스 추가. `tests/test_debate_gates.py::test_divergence_forces_one_challenge_round_then_concludes` 를 새 동작(요약 재나열 대신 각 에이전트 요약으로 투명성 유지, "미해결 쟁점" 미표시)에 맞게 갱신.

### 검증
- 단위 테스트 294 passed (신규 포함, 회귀 0).
- 실제 슬랙 봇 E2E 3종(부먹/찍먹, 탭/스페이스, 비밀번호 해시): 모두 "미해결 쟁점" 이 disagreements 의 point/why 만 표시하고 각 에이전트 요약·합의된 답변과 중복 0건 확인. 발산 케이스에서 LLM 들이 잔여 이견을 disagreements 에 안정적으로 기록함을 실측(그래서 summary 폴백은 애초에 불필요).
- Codex 교차검증: 정적 분석으로 호출부 정합성(반환값 unpack 2곳 한정, issue_note 양용도 `if issue_note:` 가드) 확인.

## v0.7.8 (2026-05-29)

Gemini 의 매 발언 첫 줄에 터미널 경고 `Warning: True color (24-bit) support not detected. Using a terminal with true color enabled will result in a better visual experience.` 가 누출되어 Slack 답변에 그대로 노출되던 문제 수정. (자체 테스트 thread 1780059304 에서 사용자가 발견)

### 발생 원인
`agents/gemini.py` 의 `_clean_output` 노이즈 필터는 `_NOISE_KEYWORDS` 에 포함된 키워드가 있는 라인을 제거한다. 그런데 색상 경고 키워드로 `"256-color support not detected"` 만 등록돼 있어, non-TTY 환경에서 실제로 출력되는 `"True color (24-bit) support not detected"` 변종은 필터를 통과해 응답 본문에 섞였다.

### 수정
- **[Minor / backend]** `agents/gemini.py`: `_NOISE_KEYWORDS` 의 `"256-color support not detected"` 를 공통 꼬리 `"support not detected"` 로 교체. "256-color"/"True color (24-bit)" 및 향후 변종을 모두 필터.
- 회귀 테스트 추가: `tests/test_gemini.py::TestCleanOutput` 에 true-color 24-bit 경고 케이스 추가.

### 검증
- 단위 테스트 269 passed. 실제 Gemini CLI 호출로 응답에 경고 미포함 확인. Codex 교차검증 통과(false positive 위험 낮음). 슬랙 전수 스캔 자체 테스트로 모든 에이전트 발언에 노이즈/에러 누출 0건 확인.
- 자체 테스트 방법론 개선: 합의문만 보던 기존 방식 → 스레드 전 메시지를 `_NOISE_KEYWORDS` + 에러 마커로 전수 스캔.

## v0.7.7 (2026-05-29)

토론 종료 시 `💡 *합의된 답변:*` 자리에 모델 답변 대신 `API Error: 500 Internal server error. ...` 라는 에러 문구가 그대로 방송되는 회귀 수정. (Slack thread 1780056574)

### 발생 원인
합의문은 `_generate_final_answer()` 가 통합문 생성 에이전트(교체 안 된 원본, 보통 Claude)에게 `agent.ask()` 로 생성시킨다. 그런데 Claude Code CLI 는 API 5xx 를 맞으면 **예외를 던지지 않고** `--output-format json` 의 `result` 필드에 `"API Error: 500 ..."` 라는 에러 문구를 담아 정상 종료한다(`agents/claude.py` 의 `_run_cli`/`ask_with_progress` 가 `data["result"]` 를 그대로 반환). 두 방어선이 모두 이를 놓쳤다.
- `agents/base.py` 의 `_is_fatal_error` 가 429/quota 패턴만 알고 **5xx/overloaded 패턴이 없어** `has_error` 가 False 로 남음 (라운드 중 5xx 시 백업 교체도 안 됨).
- `_generate_final_answer` 의 `try/except` 는 파이썬 예외만 잡아서, 문자열로 정상 반환된 에러는 통과 → `_strip_consensus` 후 그대로 합의문으로 broadcast.

### 수정
- **[Major / backend]** `agents/base.py`: `_FATAL_SUBSTRINGS` 에 `internal server error`, `overloaded_error` 추가. `_FATAL_REGEX` 에 5xx alternative 추가 (`error|status|code` 앵커 뒤 5xx, `API Error`/`APIError`/`statusCode`/`HTTP/1.1` 포맷 포함). `500자`, `약 500조`, `목표가 529,000원`, `handler.py:500` 등 앵커 없는 숫자는 오탐 안 함.
- **[Major / backend]** `modes/debate.py` `_generate_final_answer`: 원본 후보를 순회하며 첫 후보는 transient(5xx/과부하) 에러 시 1회 재시도(인프라 에러 최대 1회 규칙), 새 `_is_bad_final_answer` 헬퍼(빈 응답 / `has_error` / `timed_out` / `[Name]` 내부 메시지)로 각 결과를 검사, 모든 후보 실패 시 `_deterministic_merge` 로 폴백. 에러 문자열은 절대 방송되지 않는다.

### 검증
- 회귀 테스트 추가: `tests/test_agent_base.py` (5xx/overloaded 감지 + 5xx-유사 숫자 오탐 방지), `tests/test_consensus.py::TestGenerateFinalAnswerErrorGuard` (500 → 폴백 머지 / 재시도 성공 / 다음 후보 폴백 / 정상 통과).
- Codex 교차검증: 5xx 정규식 false negative(`APIError: 500`, `HTTP/1.1 503`, `statusCode: 500`) 지적 반영 후 재통과. 전체 268 passed.

## v0.7.6 (2026-05-26)

v0.7.5 자체 핫픽스. v0.7.5 commit (a37ae5f) 직후 실전 PDF 첨부 테스트에서 봇이 완전 무응답. bot_output.log 에 `NameError: name 'os' is not defined` 가 `_runner` 라인 173 에서 던져지고 thread 전체가 죽음.

### 회귀 원인
v0.7.5 에서 `tmp_dir` 을 `<project>/.tmp/` 내부로 옮길 때 `_runner` 안에서 `os.path.join(...)`, `os.makedirs(...)` 를 추가했는데 **모듈 전역에 `import os` 가 없음**. 함수 내부 `import tempfile, shutil` 만 추가하고 `os` 는 빠뜨림. 따라서 첨부 다운로드 진입점이 즉시 NameError 로 죽고 봇이 무응답.

### 수정
- **[Critical / FE/backend]** `slack_bot.py` 모듈 전역에 `import os` 추가
- **[Critical / 테스트]** `tests/test_slack_bot.py::test_os_module_imported` 회귀 테스트 추가 (모듈에 `os` attribute 존재 + 진짜 os 모듈인지 검증)

### 영향 범위
- v0.7.5 commit (a37ae5f) 부터 v0.7.6 fix 까지 약 30분간 모든 첨부 (PDF + 이미지) 메시지가 봇 무응답
- 첨부 없는 일반 메시지는 정상 동작 (라우팅 흐름이 _runner 진입 전 분기)

### 검증
- `pytest tests/` 비-라이브 269 passed (기존 268 + 신규 1)
- `python -c "import slack_bot"` 로 모듈 로드 sanity check 통과
- 봇 재시작 + 실전 PDF 첨부 테스트 예정

## v0.7.5 (2026-05-26)

v0.7.4 출시 직후 실전 PDF 첨부에서 발견된 회귀 2건 핫픽스. 실제 슬랙 스레드(`1779791375.628899`) 에서 Claude 만 정상 동작했고 Gemini/Codex 는 PDF 분석 실패.

### 회귀 진단
- **Gemini (실패)**: `read_file` 도구가 workspace 외부 경로를 거부. 임시 디렉토리가 `C:\Users\ymseo\AppData\Local\Temp\slack_attachments_*` 라 "Path not in workspace" 에러로 PDF 자체 못 읽음.
- **Codex (부분 성공)**: `read` 도구가 PDF native 미지원. `pdftotext` (poppler) 시도 → 미설치 실패 → `pypdf` import 시도 → 일부 페이지만 추출 후 끝까지 가지 못함.
- **Claude (정상)**: Read 도구가 PDF native 지원이라 무관하게 동작.

### 수정
- **[Minor / FE/backend]** `slack_bot.py:_runner` 의 tmp_dir 을 `<project>/.tmp/` 내부로 변경 (`tempfile.mkdtemp(dir=base_tmp)`). Gemini workspace 격리 회피. `.tmp/` 는 `.gitignore` 추가.
- **[Minor / FE/backend]** `slack_files.py` 에 `extract_pdf_text(path, max_chars=100_000)` 헬퍼 + `format_pdf_text_inline(attachments)` 헬퍼 추가. `extract_attachments` 가 PDF 다운로드 직후 pypdf 로 텍스트 추출해 반환 dict 의 `text` 필드에 채움. 100KB 초과 시 잘라내고 "절대경로로 추가 확인 권장" 안내.
- **[Minor / FE/backend]** 각 에이전트의 `_augment_with_attachments` 가 PDF text 가 있으면 prompt 에 인라인 블록 (`[첨부 PDF 본문: name]\n<text>\n[/첨부 PDF 본문]`) 으로 첨부:
  - Claude: prompt 끝 [첨부 파일] 블록 직전, instruction 도 "인라인 본문 직접 분석 + Read fallback" 으로 변경
  - Codex: prompt 끝 note 안, instruction 에 "`pdftotext` 시도 금지" + "read 도구로 PDF 다시 읽지 말 것" 명시 (v0.7.4 시행착오 차단)
  - Gemini: `@<path>` 직후 + PDF 가드 앞 (순서: @path → text → guard → prompt)
- **[Minor / 의존성]** `requirements.txt` 에 `pypdf>=4.0` 추가 (개발 환경 확인 결과 pypdf 6.9.2 이미 설치되어 있어 즉시 적용 가능).

### 효과
- Gemini: workspace 내부 경로 + 인라인 본문 fallback 으로 read_file 실패해도 분석 가능
- Codex: pdftotext/pypdf 시도 없이 prompt 안의 텍스트 바로 사용 (시행착오 시간 단축 + 일관성)
- Claude: 기존 동작 유지 + 인라인 본문 있어서 Read 호출 비용 절감 (선택적)

### 테스트
- `tests/test_slack_files.py`: 신규 5건 (text 필드 회귀, pypdf 미설치 fallback, truncation, format_pdf_text_inline 헬퍼 2건)
- `tests/test_agent_vision.py`: 각 에이전트 PDF text 인라인 회귀 3건 + 기존 PDF 안내 문구 assert 갱신
- 전체 비-라이브 **267 passed** (기존 259 + 신규 8)

### 검증
- `pytest tests/` 비-라이브 268/268 PASS (truncation fix 회귀 1건 추가)
- Codex 교차 검증 (`bgks61h3e`): 진행 중 정지 (1시간 무응답), **발견된 1건 fix 적용 후 마감**:
  - **Minor**: `extract_pdf_text` 의 truncation 이 페이지 단위 break 라 단일 큰 페이지 PDF 에서 `max_chars` 를 크게 초과 가능 → 페이지 안에서도 잘라내도록 수정 + 회귀 테스트 (`test_extract_pdf_text_truncates_inside_large_page`) 추가
- 수정 후 `slack_files` 단위 17/17 PASS, 전체 268 PASS

## v0.7.4 (2026-05-26)

PDF 첨부 지원 확장. 기존에는 Slack 에 PDF 던지면 봇이 무시했지만, 이제 image/* 와 동일 흐름으로 다운로드되어 각 CLI 의 read 도구(Claude Code Read native PDF 지원, Gemini `@<path>`, Codex read 텍스트 추출)가 직접 처리한다. Python 단 PDF 파싱 의존성 추가 없음 (글로벌 CPU 과열 룰의 "PDF 파싱은 실시간 API 에서 제거" 정책과 부합).

### 기능 추가
- **[Minor / enhancement]** `slack_files.py` 의 MIME 필터에 `application/pdf` 추가. PDF 는 별도 size 상한 20MB (이미지 5MB 대비 큼). 반환 dict 에 `kind` 필드 ("image" | "pdf") 부여.
- **[Minor / enhancement]** 각 에이전트 (Claude/Codex/Gemini) 의 prompt augment 함수가 첨부 kind 에 따라 분기된 안내 문구를 생성:
  - Claude: PDF 면 "Read 도구로 읽고 본문 분석/요약, 10페이지 초과 시 pages 인자 분할"
  - Codex: PDF 면 "read 도구로 PDF 텍스트 추출하여 분석"
  - Gemini: PDF 가드 ("PDF 본문에서 답 도출, 외부 지식으로 추정 금지") 추가, 이미지 가드는 image kind 있을 때만 활성화

### 리팩토링 (사용자 결정: 전체 리네이밍)
- `slack_files.extract_images` → `extract_attachments`
- 모든 함수의 `images: list[dict] | None = None` 인자 → `attachments: list[dict] | None = None` (base/claude/codex/gemini + 3 backup + bridge/coding/debate + slack_bot 일관)
- 키워드 호출 `images=` → `attachments=`
- 변수명 `images` (지역변수, dict key, pending dict 의 "images" key 포함) → `attachments`
- `_augment_with_image_paths` (Claude/Gemini), `_augment_with_image_note` (Codex) → `_augment_with_attachments` 통일
- `BridgeMode._call_claude_vision` → `_call_claude_with_attachments` (의미 일반화)

### 테스트
- `tests/test_slack_files.py`: 함수명 변경 + PDF 통과 케이스 4건 추가 (`pdf_mime_downloaded_with_kind`, `pdf_size_limit_larger_than_image`, `pdf_size_above_pdf_limit_skipped`, `mixed_image_and_pdf`)
- `tests/test_agent_vision.py`: 함수명/인자명 변경 + 각 에이전트 PDF 회귀 케이스 (Claude `pages` 안내, Gemini PDF 가드 분기, Codex PDF instruction)
- `tests/{test_bridge,test_agent_base,test_coding_gate}.py`: 인자명 변경 동기

### 검증
- 전체 비-라이브 테스트 **259 passed** (회귀 없음)
- `slack_files` 단위 11건 PASS (기존 7 + 신규 4)
- `test_agent_vision` 단위 18건 PASS (기존 13 + 신규 5)
- Codex 교차 검증 완료 (agent `a0badc879ccde98a5`):
  - 통과 17건 (MIME/size 분기, kind 분기, augment instruction, backup 호환, lambda 인자, pending dict key, cleanup, mixed 등)
  - Minor 1건 + Trivial 1건 발견, **모두 fix 적용**:
    - Minor: `modes/coding.py` 의 `_image_key` helper + `img` 매개변수 + `tests/test_coding_gate.py` 의 `test_image_key_priority` 가 리네이밍 누락 → `_attachment_key` / `attachment` / `test_attachment_key_priority` 로 통일
    - Trivial: `modes/coding.py:357` + `modes/debate.py:639` 의 docstring 에 "이미지" 표현 잔재 → "첨부 파일" 로 일반화
- 수정 후 전체 비-라이브 테스트 **259 passed** 재확인

## v0.7.3.3 (2026-05-20)

v0.7.3.2 직후 Codex 교차검증에서 Block 1건 + Major 1건 발견, 즉시 교정.

### 버그 수정
- **[Block]** `agents/gemini.py:293` 의 `_run_progress_once` 가 v0.7.3.2 fix 에서 누락되어 여전히 모듈 전역 `_gemini_concurrency` 를 참조. 모듈 reload 후 해당 심볼이 더 이상 정의되어 있지 않아 첫 호출에 `NameError` 로 모든 Gemini 진행성 호출(`ask_with_progress`)이 즉시 실패. 토론·코딩 모드 전반 영향. `replace_all=true` 가 들여쓰기 차이로 한 곳만 잡고 다른 한 곳은 놓친 사고. `_get_gemini_concurrency()` 로 교체.
- **[Major]** `_run_progress_once` 의 subprocess lifecycle 에 cancellation cleanup 부재. 외부 `wait_for` cancel 또는 `_current_thread_ts` 미설정 환경에서 spawn 직후~register 이전 cancel window 가 발생하면 `_kill_registered_processes` 가 해당 proc 을 못 찾아 좀비 프로세스 leak. spawn 이후 try/finally 로 `proc.returncode is None` 확인 후 `kill_process_tree(proc) + asyncio.wait_for(proc.wait(), timeout=2)` 정리 보장. `_run_cli` 의 `proc.communicate(input=stdin_data)` 호출도 같은 패턴(`except BaseException` cleanup + `raise`)으로 보강.

### 검증
- 전체 비-라이브 250 passed (회귀 없음)
- import 시 NameError 부재 확인 (`python -c "import agents.gemini"`)
- 봇 재시작 시 v0.7.3.3 자동 반영, watchdog 정상 동작

### Codex Minor 후속 추적
- `_get_gemini_concurrency()` 의 thread-safety: 현재 async-only 호출이지만, Slack 핸들러가 worker thread 띄울 가능성 고려해 `threading.Lock` 추가 검토 (별도 이슈)
- `_run_progress_once` 단위 테스트 부재(subprocess mocking 필요): Block 버그를 잡지 못한 원인. 후속 작업으로 분리

## v0.7.3.2 (2026-05-20)

v0.7.3 라이브 검증(2차 5개 토론)에서 발견된 Major 2건 즉시 교정.

### 버그 수정
- **[Major]** `asyncio.Semaphore` 이벤트 루프 바인딩 회귀. `agents/gemini.py` 의 모듈 전역 `_gemini_concurrency = asyncio.Semaphore(3)` 가 첫 사용 이벤트 루프에 묶이는 Python asyncio 한계 때문에, Slack Bolt 가 새 이벤트 루프에서 호출하면 매번 `<asyncio.locks.Semaphore object at 0x... [locked, waiters:1]> is bound to a different event loop` 에러로 acquire 자체가 실패하거나 영구 block. 2차 라이브 5/5 토론 모두 R1 또는 R2 에서 Gemini 응답 손실 확인.
  - 수정: per-loop lazy init 구조로 재설계. `_GEMINI_CONCURRENCY_LIMIT = 3` + `WeakKeyDictionary[loop, Semaphore]` 캐시 + `_get_gemini_concurrency()` 헬퍼. 호출 시점에 현재 이벤트 루프의 세마포어를 lazy-create. 두 호출 사이트(`_run_cli`, `_run_progress_once`) 갱신. 루프 GC 시 WeakKeyDictionary 가 캐시 엔트리 자동 해제.
- **[Major]** 토론 33분 hang 사고. Semaphore acquire 단계에서 block 되면 `_run_progress_once` 의 `while True` 루프 자체에 진입 못 해 내부 `overall_timeout(t*2)` 검사가 발동 못 함. 슬랙 thread 1779275130 (등산 vs 헬스 토픽) 에서 Gemini "작업 중 2019초(33분)" 표시 + R1 종료 마크 없이 영구 멈춤.
  - 수정: `ask_with_progress` 의 `_run_progress_once` 호출을 `asyncio.wait_for(timeout=t * 2.5)` 외부 가드로 래핑. 내부 timeout 이 발동 못 해도 외부 가드가 강제 cancel + `_kill_registered_processes()` 로 subprocess 정리 + `[Gemini] 외부 가드 시간 초과 (~450초, 내부 hang 감지)` 메시지 반환. 백업 투입 경로 정상 작동.

### 검증
- 신규 단위 테스트 `tests/test_gemini.py::TestConcurrencyPerLoop` 5건:
  - `test_returns_semaphore_with_correct_limit`: 임계값 3 보장
  - `test_same_loop_returns_same_instance`: idempotent
  - `test_different_loops_get_independent_semaphores`: 핵심 회귀 차단(다른 루프 = 다른 인스턴스)
  - `test_acquire_succeeds_after_loop_replacement`: 실제 사고 시나리오(3회 연속 새 루프 acquire) 재현 후 정상 동작 확인
  - `test_cache_keyed_by_loop_not_grow_unbounded`: 한 루프 내 50회 호출 후 캐시 1개 유지
- 전체 비-라이브 테스트 250 passed (+5 신규, 회귀 없음)
- 봇 재시작 후 라이브 재검증 권장(현재 코드는 main 반영, watchdog 가 자동 재시작)
- Codex 교차검증: 본 변경의 WeakKeyDictionary 사용 안전성·outer timeout cancel 경로·thread-safety 를 별도 디스패치로 의뢰(결과는 PR 코멘트로 기록)

## v0.7.3 (2026-05-20)

토론 모드에서 2명이 합의하고 1명이 출처 없이 이견을 고집하는 deadlock 케이스가 MAX_ROUNDS 까지 끌리던 결함 수정. Slack thread 1779271920 (런던고라니 정치-경제 분리 발언 추적) 에서 Claude·Codex 가 "출처 URL 없는 인용에 동의 불가" 입장 유지, Gemini 가 5R 동안 매번 약간 다른 인용 변형 시도. 기존 `_is_stalemate` 분기는 `agrees>=2` 필요한데 Claude/Codex 가 Gemini 와 일치 안 하니 agree=false 마킹해서 발동 불가. 결국 `no_progress` 가 R5 에서 가까스로 발동.

### 개선 (Major) - 두 갈래 보완책

1. **SYSTEM_PROMPT agree=true 의미 완화** (`modes/debate.py` L33-34, prompt-only 변경):
   - 기존: `"agree=true: 다른 에이전트들과 의견이 충분히 일치"` (전원 일치 묵시)
   - 신규: `"agree=true: 본인 입장이 **최소 1명의 다른 에이전트와 충분히 일치** (전원 일치 필요 없음, 2/3 다수 합의 케이스에서도 true)"`
   - 효과: 2/3 동의 케이스에서 `agrees=2` 도달 가능 → 기존 `_is_stalemate` 분기 (`agrees >= 2 + 발산 2R 지속`) 정상 발동

2. **페어 outlier 명시 감지 + 지속 종료 분기 신설** (코드 변경):
   - 신규 헬퍼 `_pair_outlier(round_consensuses) -> str | None`: 3 에이전트 summary 의 페어와이즈 Jaccard 계산. 최고 페어 sim >= `PAIR_AGREE_THRESHOLD(0.30)` 이고 outlier 가 끼는 두 페어 sim 모두 최고 페어의 60% 이하면 outlier 이름 반환. 그 외 None (3 갈래 발산이나 애매한 케이스).
   - 신규 헬퍼 `_persistent_outlier(outlier_history)`: 같은 outlier 가 최근 2R 연속 잡혔는지 확인.
   - `start()` 와 `followup()` 양 루프에 새 조기종료 분기: `elif can_conclude and persistent_outlier:` 발동 시 `"다수 합의 (2/3, {outlier_name} 이견 지속)"` 제목으로 종료. agree 카운트 무관하게 작동해서 LLM 이 프롬프트 변경을 100% 흡수 못 해도 안전망 역할.
   - 분기 순서: `agrees>=3` → `agrees>=2 + stalemate` → **`persistent_outlier`(신규)** → `no_progress` → 다음 라운드. 기존 보수적 종료가 우선.

### 검증
- 신규 단위 13건: `TestPairOutlier(6)` + `TestPersistentOutlier(5)` + `TestSlackThread1779271920Pattern(2)` (Gemini outlier 2R 연속 감지 / 1R 만 잡혀선 종료 안 함). 전체 비-라이브 244 passed (회귀 없음).
- 효과 예측: Slack thread 1779271920 패턴이 v0.7.3 환경에서 R3 에 종료(기존 R5+ → 라운드 비용 40%+ 절감).
- Codex 교차검증: 본 변경의 분기 순서·임계값·SYSTEM_PROMPT 완화 영향을 별도 디스패치로 의뢰(결과는 PR 코멘트로 기록).

## v0.7.2.1 (2026-05-20)

v0.7.2 직후 Codex 교차검증에서 발견된 Major 2건 + Minor 2건 + Trivial 1건을 즉시 교정한 핫픽스.

### 버그 수정
- **[Major]** `agy` 호출이 `cmd /c agy -p <prompt>` 로 래핑되어 prompt 가 `cmd.exe` 셸 파싱 대상이 됨. Slack 사용자 텍스트에 `&`, `|`, `^`, `%`, `<`, `>` 메타문자가 들어가면 셸이 가로채 인자가 깨짐. `process.py` 의 `platform_cmd()` 에 `_NATIVE_EXE_NAMES` 화이트리스트(현재 `{"agy"}`)를 도입해 네이티브 .exe 는 `cmd /c` 우회하고 `%LOCALAPPDATA%\agy\bin\agy.exe` 절대경로로 직접 실행 (설치 경로에 없으면 PATH 검색 폴백). npm 래퍼(gemini/codex/claude)는 기존대로 `cmd /c`.
- **[Major]** `agy` 경로의 prompt 가 argv 로 직접 전달되는데 Windows CreateProcess CommandLine 한계 ~32KB. 일반 토론 prompt 는 5KB 이하지만 코딩 모드(Claude 응답+코드 포함) 에서 초과 가능. `agents/gemini.py` 에 `_AGY_PROMPT_ARGV_LIMIT = 25000` 안전 마진 + `_truncate_for_agy_argv()` 헬퍼 추가. 초과 시 머리만 사용 + `[...truncated]` 표식 + stderr 경고.
- **[Minor]** `_build_cmd()` 인스턴스 메서드(AgentBase.ask_with_progress 폴백용)가 `agy` 경로에서 빈/누락 tmp 에 대해 `["agy",...,"-p",""]` 를 만들 수 있었음. agy 는 `-p ""` 거부하므로 `ValueError` 로 명시적 실패하도록 변경. 실제 호출 경로엔 영향 없음(`GeminiAgent` 가 `ask_with_progress` 오버라이드).
- **[Minor]** `tests/test_gemini.py::TestBinarySelection::test_default_is_gemini_binary` 가 `setenv("", "")` 후 검증해 "absent env" 가 아닌 "empty value" 폴백을 검증함. `test_default_when_env_absent` 로 진짜 absent 케이스 분리 + `test_default_when_env_empty_string` 으로 빈 문자열 케이스도 별도 보장.

### 개선
- **[Trivial]** `_run_progress_once` 의 미사용 변수 `agy_stdin` 제거.

### 검증
- 신규 단위 테스트:
  - `tests/test_process.py::TestPlatformCmdNativeExeBypass` 4건 (npm 래퍼는 cmd /c 유지, agy 는 절대경로 직접 호출, agy 폴백, Unix 무변경)
  - `tests/test_gemini.py::TestBinarySelection` 에 5건 추가 (absent env, empty env, argv 길이 잘림, 정상 길이 그대로, 메타문자 prompt 통과)
- 전체 비-라이브 테스트 231 passed (+8 신규, 회귀 없음).
- 라이브 검증은 여전히 인터랙티브 OAuth 필요로 v0.7.2 와 동일하게 GitHub Issue #96 에서 추적.

## v0.7.2 (2026-05-20)

Google 발표(2026-05-19, I/O 2026)에 따라 2026-06-18부터 Pro/Ultra/무료 사용자 대상 Gemini CLI 서비스가 종료되고 Antigravity CLI(`agy`)로 통합된다. 사전에 코드 경로를 분기 가능하도록 준비. 안전 기본값 `gemini` 유지로 즉시 배포해도 기존 동작은 그대로.

### 개선
- **[Major]** `agents/gemini.py` 에 `agy` 분기 추가. `config.GEMINI_CLI_BINARY` 환경변수(기본 `gemini`, 허용 값 `gemini`/`agy`, 그 외는 안전하게 `gemini` 폴백)로 런타임 토글.
  - 신규 헬퍼 `_build_subprocess_args(model, prompt) -> (cmd_list, stdin_bytes | None)`: gemini 면 `["gemini","-m",model,"-y","-p",""]` + prompt 를 stdin 으로, agy 면 `["agy","--dangerously-skip-permissions","-p",prompt]` + stdin 사용 안함.
  - agy 는 `-m` 미지원이라 `_available_models()` 가 placeholder `["__agy_default__"]` 만 반환해 모델 fallback 루프가 1회만 돈다. `_mark_failed()` 는 agy 경로에서 no-op.
  - `_run_cli`, `_run_progress_once` 가 헬퍼와 `asyncio.subprocess.DEVNULL` 조건부 분기를 사용. 기존 gemini 경로 동작은 변경 없음(서명/세마포어/취소/재시도/타임아웃 그대로).
  - 마이그레이션 트리거 변경 없음: 사용자가 `agy` 를 한 번 인터랙티브 실행해 OAuth 마치고 `GEMINI_CLI_BINARY=agy` 설정 후 봇 재기동하면 전환 완료.

### 마이그레이션 가이드
1. Antigravity CLI 설치 (Windows PowerShell): `irm https://antigravity.google/cli/install.ps1 | iex`
2. 새 터미널 열어 `agy --version` 으로 PATH 확인 (현재 1.0.0)
3. Gemini 익스텐션/설정 import: `agy plugin import gemini`
4. `agy -i` 한 번 실행해 OAuth 첫 인증 완료 (브라우저 토큰 발급)
5. `.env` 또는 시스템 환경변수에 `GEMINI_CLI_BINARY=agy` 추가
6. 봇 재기동 후 슬랙 토론 1회 트리거로 응답 정상 확인
7. 2026-06-18 이후 Gemini CLI 완전 제거

### 검증
- 신규 단위 테스트 `tests/test_gemini.py::TestBinarySelection` 6건 (default → gemini, explicit gemini, agy 명령어/플래그/no-stdin, agy `_available_models` placeholder, agy `_mark_failed` no-op, 잘못된 값 안전 폴백). autouse fixture 로 각 테스트 후 모듈 상태를 기본값으로 복구.
- 전체 비-라이브 테스트 223 passed (회귀 없음).
- agy CLI 실제 호출 dry-run: 첫 호출에 인터랙티브 OAuth 가 필요해 비대화식 자동화 환경에서 검증 불가. 사용자가 인터랙티브 OAuth 1회 마친 뒤 `GEMINI_CLI_BINARY=agy` 토글 + 실제 슬랙 토론 1회 라이브 확인 필요(이 라이브 확인은 후속 작업으로 분리).
- Codex 교차검증: 본 변경의 분기 안전성/회귀 위험을 별도 디스패치로 의뢰(결과는 PR 코멘트로 기록).

## v0.7.1 (2026-05-19)

### 버그 수정
- **[Major]** 실시간/사실 주제(예: "오늘 코스피 매수?")에서 라운드 3부터 핵심 권고가 3사 동일한데도 MAX 라운드까지 진행해 토큰을 낭비하던 결함 수정(실측 1건 7라운드 ~$4). 근본 원인: `_summaries_diverge`가 summary 전체(인용 수치·출처 포함) 어휘 Jaccard를 비교해, 권고가 수렴해도 인용부 차이로 `diverged=True`가 영구 고착. 동시에 에이전트들이 곁가지 쟁점으로 `agree=false`를 유지하면 `agrees<2`라 challenge-once(>=3)/`_is_stalemate`(>=2+비증가) 출구가 모두 미발동. 수정: agree 플래그·cross-agent 발산에 무관한 자기-반복 신호 `_no_progress(prev, curr)` 도입(양 라운드 공통 에이전트의 자기 summary 토큰 Jaccard 최소값 >= `NO_PROGRESS_THRESHOLD` 0.6, 공통 2명 미만이면 False). `start()`/`followup()` 양 루프에 `prev_summaries` 추적 + `_is_stalemate` elif 다음에 `elif can_conclude and no_progress:` 추가. agree>=2면 "다수 합의 (수렴)", 아니면 "합의 불발 (추가 진전 없음)"으로 조기 종료. `min_rounds`(난이도 게이트) 이후에만 작동하고 정상 합의/교착 경로보다 후순위라 조기 가로채기 없음.

### 검증
- 신규 단위 테스트 `TestNoProgress`(5) + KOSPI 낭비 재현 통합 테스트 `TestConvergenceEarlyExit`(RED: 라운드 10 완주 → GREEN: 라운드 ≤4 종료). `TestMaxRoundsExhaustion`을 정정된 조기 종료 동작에 맞춰 갱신. 비라이브 전체 160 passed.
- Codex 교차검증: 플러그인 공유 런타임이 23시간 좀비화로 디스패치 불가(좀비 프로세스 6종 회수 조치). 메모리 원칙(인프라 실패 시 테스트 근거로 진행)에 따라 RED→GREEN 재현 테스트로 갈음.

## v0.7.0 (2026-05-19)

토론(debate) 시스템 품질/안정성 6개 항목 개선. AI 멀티에이전트 토론 결과 검토에서 도출된 결함을 코드 대조로 확인 후 일괄 수정.

### 버그 수정
- **[Major]** 교착 감지(`_is_stalemate`) 사실상 미발동: 메시지 앞 100자 문자열 set 비교는 매 라운드 도입부가 달라 `overlap>=2`가 사실상 불가. 전원 합의 실패 시 `MAX_DEBATE_ROUNDS(10)`까지 불필요 진행. 라운드별 `{agrees, diverged}` 스냅샷 기반(최근 2라운드 정체+발산 시 교착)으로 재설계, 시그니처 `history -> round_history`.
- **[Major]** 백업 풀 비대칭 + 이중 장애 다양성 붕괴: 정적 매핑이 Codex/Gemini 모두 Claude-B로 수렴해 동시/순차 장애 시 살아있는 에이전트가 동일 모델 3중. `GeminiBackupAgent` 신설 + `base_family` 속성 + 실패/생존 계열 회피 동적 선택. 이미 live인 백업 인스턴스는 후보에서 제외(없으면 풀 폴백)해 동일 객체 중복 방지.
- **[Major]** `_parse_consensus` 무음 실패: JSON 파싱 실패 시 조용히 None 반환으로 합의 누락. salvage 단계화(trailing comma 제거 재시도 -> agree/summary 정규식 추출) + 실패 시 WARNING 로깅.
- **[Minor]** 최종 통합문 `self.agents[0]` 단독 생성으로 교체된 백업 모델 편향. `_select_final_answer_agent()`로 교체 안 된 원본 우선 선택, 원본 전멸 시 LLM 없이 결정론적 머지 폴백.

### 개선
- **[Major]** 조건부 반박 강제(challenge-once 반동조 게이트): 라운드2+ 프롬프트를 "의견 갈리면 상대 주장 구체 인용해 지적, 같으면 같다고(억지 반박 금지)"로 변경, CONSENSUS에 `disagreements` 필드 추가. 요약 발산(min-pair Jaccard) 시 전원 agree인데 아무도 차이를 안 다루면 1회 교전 라운드만 강제 후 미해결 쟁점 명시하고 종료(영구 차단 아님).
- **[Minor]** 난이도 기반 라운드 라우팅: `_classify_difficulty` 휴리스틱(길이/코드·기술 키워드/다항/실시간)으로 단순=조기 종료 허용, 복잡=`COMPLEX_MIN_ROUNDS(3)` 전 조기 종료 금지. followup은 원주제+질문 합산 분류. 3개 AI 교차검증은 유지하고 비용만 절감.

### 검증
- 신규 단위 테스트: `tests/test_debate_improvements.py`, `tests/test_debate_gates.py`, `tests/test_agent_family.py` + `test_consensus.py`/`test_replacement.py` 갱신. 비라이브 전체 154 passed.
- Codex 교차 검증: 1차에서 5개 이슈 지적(백업 인스턴스 중복, 평균 Jaccard로 2:1 발산 미감지, 정상 합의 false-positive 차단, followup 난이도 원주제 무시, disagreements 구조 검증). 전부 교정 + 해당 버그 회귀 테스트 추가(`triple_failure_no_duplicate_instance`, `two_vs_one_outlier_diverged`, `divergence_forces_one_challenge_round_then_concludes`).

## v0.6.4 (2026-05-12)

### 버그 수정
- **[Major]** 코딩 모드에서 Phase 1 Claude 가 요구사항을 되묻는 질문 응답을 줬을 때, 봇이 그것을 그대로 "코드"로 간주하여 Phase 2 Codex 리뷰가 곧장 시작되고 Codex 가 엉뚱한 stockradar stacktrace 같은 컨텍스트를 끌어와 응답하던 회귀 수정. Phase 2 가 묶여 있는 동안 Phase 3 Gemini 는 도달조차 못 해 응답이 없던 사용자 보고가 원인. `modes/coding.py` 에 Phase 1 게이트 도입:
  - `AWAIT_USER_PATTERN` (`<!--AWAIT_USER:사유-->`) 줄 단위 정규식 + Phase 1 프롬프트 suffix 로 Claude 에게 "추가 정보 필요하면 응답 마지막 줄에 태그를 추가하라" 지시
  - 모듈 전역 `_PENDING_THREADS` + `_PENDING_LOCK` + `_RESUMING_THREADS` + `_INFLIGHT_PHASE1` 으로 동시 start/followup race 직렬화
  - `start()` 본문을 `_start_inner()` 로 분리하고 `_try_enter_inflight` / `_leave_inflight` 가드를 try/finally 로 감쌈
  - `_run_review_and_test()` 메서드로 Phase 2/3 분리. Phase 1 응답에 태그가 있으면 `_PENDING_THREADS` 에 첨부 이미지 포함 등록 후 Phase 2/3 호출 없이 종료
  - `followup()` 진입 시 pending + 명시적 codex/gemini 호출 아닐 경우 `_resume_pending()` 호출. 사용자 답변과 스레드 히스토리를 합쳐 Claude 재호출, 응답에 태그가 사라지면 Phase 2/3 자동 트리거
  - fenced code block 안 단독 태그 오탐 방지 (`_FENCED_BLOCK.sub('', text)` 후 매칭), `_strip_await_user` 는 UUID sentinel 로 fenced block 보존
  - `_image_key()` (path → name → id) 헬퍼로 최초 이미지 + followup 이미지 dedup 병합
  - `_check_cancel()` 이 cancel cleanup 외에 `_drop_pending()` 호출하여 stale pending 차단

### 검증
- 단위 테스트 23건 추가 (`tests/test_coding_gate.py`): AWAIT_USER 정규식 / fenced 보존 / placeholder 충돌 안전성 / start 게이트 / followup pending 트리거 / cancel 정리 / 동시 followup 직렬화 / start inflight 가드 / image key 우선순위
- 인접 회귀 38건 전부 통과 (총 61 passed)
- Codex 교차 검증 3차 라운드 → 미통과 → race / cancel / fenced 오탐 / image key / placeholder 충돌 등 5개 이슈 전부 반영 후 통과

### 버그 수정
- **[Critical]** Claude 가 이미지 첨부 입력에서 항상 `[Claude] 오류: Separator is not found, and chunk exceed the limit` 으로 실패하던 회귀 수정. asyncio `proc.stdout.readline()` 의 기본 64KB 라인 한도를 16MB 로 키워(`_STREAM_LINE_LIMIT`) 이미지 Read tool_result 한 줄이 한도를 넘기는 stream-json 파싱 실패 차단. `_run_cli` / `ask_with_progress` 양쪽에 적용.
- **[Major]** Codex CLI 응답 머리에 `warning: --full-auto is deprecated; use --sandbox workspace-write instead.` 가 그대로 노출되던 문제 해결. `_build_cmd` 에서 `--full-auto` → `-s workspace-write` 로 교체하고, 방어선으로 `_CODEX_DEPRECATION_LINE` 정규식(`^\s*warning:\s+\`--<flag>\`\s+is\s+deprecated`)을 노이즈 필터에 추가. 일반 답변 본문의 deprecation 언급은 보존.
- **[Minor]** Gemini CLI 응답 머리에 `Ripgrep is not available. Falling back to GrepTool.` 가 노출되던 문제 해결. `_NOISE_KEYWORDS` 와 `_run_progress_once` 의 라인별 키워드 양쪽에 추가.

### 개선
- **[Minor]** Gemini-3-flash-preview 가 차트 이미지의 종목을 잘못 식별(현대차 → 토스)하던 vision 한계 보강. `_augment_with_image_paths` 머리에 종목명/티커/현재가 식별을 먼저 명시하고 신뢰도가 낮으면 '식별 불확실' 로 표기하도록 가드 prompt 추가.

### 검증
- 단위 테스트 9건 추가 (Claude limit / Codex sandbox / Codex deprecation 정규식 / Gemini ripgrep 노이즈), 전체 159 passed
- Codex 교차 검증 → generic deprecation substring 부작용 지적 받아 정규식으로 좁힘

## v0.6.2 (2026-05-08)

### 버그 수정
- **[Critical]** 텍스트+이미지를 한 번에 보내면 봇이 반응 못 하던 회귀 수정. Slack 이 첨부 동반 메시지에 `subtype: "file_share"` 를 붙이는데 `slack_bot.handle_message` 가 모든 subtype 을 무조건 차단하고 있어 v0.6.0 이후 멀티모달 입력 라우팅이 전부 막혀 있었음. `_PROCESS_SUBTYPES` 화이트리스트(`{None, "file_share", "thread_broadcast"}`) + `should_process_event` 헬퍼 도입, 단위 테스트 10건 추가 (총 150 passed).

## v0.6.1 (2026-05-08)

### 버그 수정
- **[Major]** 이미지 첨부 분석을 SDK 직호출에서 CLI prompt 첨부 방식으로 정정. v0.6.0 이 Anthropic/google-genai SDK 직호출로 구현되어 사용자 운영 모델(Claude Code / Codex / Gemini CLI 의 OAuth 구독)과 불일치, API 키가 새로 필요해진 회귀를 해결. 이제 Slack 첨부 이미지를 임시 파일로 저장하고 절대경로를 각 CLI 의 첨부 syntax 로 prompt 에 끼워 넣어 호출한다 (Claude: 절대경로 + Read 도구, Gemini: `@<path>`, Codex: 절대경로 + read 도구). 의존성에서 anthropic, google-genai 제거.

## v0.6.0 (2026-05-08)

### 개선
- **[Major]** Slack 첨부 이미지 분석 지원 (Debate / Coding / Bridge 3개 모드). v0.6.1 에서 호출 방식 정정.

## v0.5.1 (2026-04-21)

### 버그 수정
- **[Block]** 부팅 크래시 루프 해결 — stdout/stderr UTF-8 재설정 (`1d8b683`)

## v0.5.0 (2026-04-13)

### 개선
- **[Minor]** 부팅 시 CLI 헬스체크 (claude/codex/gemini --version) (`e6c2195`)

### 버그 수정
- **[Major]** 토론 모드 실시간 수치 환각 방지 — 웹 검색 강제 (`cabf07c`)
- **[Major]** 에이전트 실행 안정화 — 누적 deadline + 백업 PERSPECTIVE 누락 보정 (`bc7cbfa`)
- **[Major]** cancel 모듈 동시성 개선 — lock 보호 + atomic write + 좀비 proc 정리 (`f41b461`)
- **[Minor]** 코딩 모드 히스토리에서 백업 에이전트 메시지도 인식 (`28005ea`)
- **[Major]** watchdog 리소스 누수·동시성 수정 + 단위 테스트 추가 (`41acfbc`)

## v0.4.2 (2026-04-12)

### 버그 수정
- **[Minor]** 토론 모드 에이전트 응답을 완료 즉시 포스트 (`0dffe59`)

## v0.4.1 (2026-04-11)

### 개선
- **[Minor]** Gemini primary를 gemini-2.5-flash-lite로 교체 + semaphore 완화 (`149a1a8`)
- **[Minor]** Gemini primary를 gemini-3-flash-preview로 교체 (`15a2702`)

### 버그 수정
- **[Major]** Gemini 429 남발 해결 — preview/lite 모델 제거 + rate-limit 탐지 맥락화 (`908ad29`)
- **[Major]** Gemini readline 타임아웃 이중화 (`e116b46`)
- **[Major]** Gemini CLI 내부 재시도를 실패로 오판 — exit code 기반 판정 (`c6764d2`)
- **[Major]** 토론 모드 라운드 1에서 상대 의견 환각 방지 (`8b01197`)

## v0.4.0 (2026-04-10)

### 개선
- **[Major]** 토론 합의 후 통합 답변 생성 (`4bc1602`)
- **[Major]** watchdog 복원력 강화 + watchdog_guard 추가 (`7b9390d`)

### 버그 수정
- **[Major]** Codex 프롬프트 누출 수정 + Gemini 429 재시도/모델 fallback (`8f5e841`)
- **[Minor]** Codex 오탐 감지 수정 — fatal error 패턴 맥락화 + head/tail 스캔 (`6045e6c`)
- **[Minor]** Windows에서 에이전트 CLI 호출 시 cmd 창 깜빡임 제거 (`db55108`)

## v0.3.0 (2026-04-05)

### 개선
- **[Minor]** kill_process_tree를 process.py로 통합 (`df4631e`)
- **[Major]** security.py에 경로 화이트리스트 검증 추가 (`4730134`)
- **[Minor]** bridge paths를 .env로 외부화 + env 필터링 (`474f7a7`)

### 버그 수정
- **[Major]** Windows에서 프로세스 트리 전체 종료 (taskkill /F /T) (`05f7189`)
- **[Minor]** cancel.py에서 kill_process_tree 사용 (`52dbef8`)
- **[Major]** CodingMode._bind_thread에 경로 화이트리스트 강제 적용 (`1eb5303`)
- **[Major]** bridge 모드에서 shell=True 제거 (`0e8b1ed`)
- **[Major]** AgentBase에서 shell=True 제거 + 필터링된 env 사용 (`396027e`)
- **[Major]** 모든 에이전트에서 shell=True 제거 (`ce76225`)
- **[Major]** fail-closed 경로 화이트리스트 — fallback 금지 (`8d3860d`)
- **[Major]** 명시적 비화이트리스트 경로는 거부 (`4bf87c2`)
- **[Critical]** Windows .cmd CLI 래퍼용 platform_cmd() 추가 (`da5539b`)
- **[Minor]** AgentBase.ask_with_progress에 stdin 파이프 추가 (`fd08351`)
- **[Minor]** Codex 출력 정리 강화 — 파일 경로 노이즈 필터 + 중복 제거 threshold (`852ea4b`)
- **[Minor]** Codex PowerShell dir 출력 노이즈 필터 추가 (`743dba1`)

## v0.2.0 (2026-04-04)

### 개선
- **[Major]** Bridge 모드 + 오류 감지 대체 투입 + load_dotenv override (`52c08d9`)
- **[Major]** !stop 강제 중단 + 코딩 모드 개선 + 작업 취소 시스템 (`dda0ea9`)
- **[Minor]** Claude 응답에 토큰 사용량 표시 (k 단위) (`919e3ab`)
- **[Major]** 코딩 모드 스트리밍 진행 표시 + idle 타임아웃 (`a7137ba`)
- **[Minor]** 코딩 채널 followup 에이전트 자동 선택 (`58ed3f1`)
- **[Major]** 전 에이전트 스트리밍 진행 표시 + 복수 에이전트 동시 지정 (`0d07943`)
- **[Major]** 코딩 채널 병렬 모드 지원 (`f7190a1`)
- **[Minor]** Claude 작업 내용 실시간 표시 + Codex/Gemini 경과 시간 (`40709f4`)
- **[Minor]** 모든 에이전트 작업 내용 실시간 표시 통일 (`aac1c0b`)
- **[Minor]** 봇 재시작 시 모든 채널에 작업 중단 알림 (`d8d93bf`)
- **[Minor]** 모든 에이전트 경과 시간 + 내용 하이브리드 표시 (`fc92628`)
- **[Minor]** 봇 재시작 시 진행 중이던 스레드에 중단 알림 (`8903462`)
- **[Minor]** Codex --full-auto 모드로 셸 실행 권한 부여 (`572d6ff`)
- **[Minor]** Gemini -y (YOLO) 모드로 도구 자동 승인 (`ae6fe10`)
- **[Minor]** 병렬 모드 완료 후 Codex가 최종 보고서 작성 (`d761822`)
- **[Minor]** 파이프라인 모드 최종 보고서도 Codex가 작성 (`422d6b7`)
- **[Minor]** 병렬 모드에 대체 에이전트 투입 추가 (`fa0fda3`)

### 버그 수정
- **[Minor]** coding followup에 누락된 기능 동기화 (debate와 통일) (`28d15de`)
- **[Minor]** 코딩 채널 스레드 답글을 Claude 추가 지시로 변경 (`6ac67f3`)
- **[Minor]** Codex 코드 리뷰 지적사항 4건 수정 (`c0d9a3f`)
- **[Major]** 코딩 모드 에이전트를 임시 디렉토리에서 실행 (`2922da9`)
- **[Minor]** 코딩 채널 followup에 스레드 히스토리 포함 (`168e061`)
- **[Minor]** stream-json 제거, 경과 시간 표시로 변경 (`7fb2588`)
- **[Minor]** 코딩 모드 cwd를 홈 디렉토리로 변경 (`1ba2a03`)
- **[Trivial]** 진행 박스 항상 코드블록 표시 (`a3a8fa6`)
- **[Minor]** ask_with_progress stderr를 stdout으로 합쳐서 읽기 (`70ca6da`)
- **[Minor]** Gemini stderr 무시 (xterm.js 터미널 이스케이프 차단) (`3d93409`)
- **[Minor]** 진행 메시지 삭제 안 되는 문제 수정 (`ad710b4`)
- **[Minor]** Gemini stderr 다시 캡처 + xterm.js 노이즈 라인 필터링 (`9bb9434`)
- **[Minor]** Codex CLI 헤더 노이즈 제거 + Slack 메시지 분할 전송 (`a7ee916`)
- **[Major]** Gemini quota 재시도 3회 초과 시 즉시 중단 + 대체 에이전트 투입 (`87ad4f4`)
- **[Minor]** 에이전트 출력 정리 (`437b129`)
- **[Major]** 자기 자신의 bot_id만 무시, 다른 봇 메시지는 처리 (`8674f6c`)
- **[Minor]** ClaudeBackupAgent를 ClaudeAgent 상속으로 변경 (`0273fdd`)
- **[Major]** 병렬 모드 타임아웃 + 크래시 복구 강화 (`8518091`)
- **[Trivial]** 테스트 mock 불일치 수정 + send_test.py 제거 (`3709496`)
- **[Minor]** Codex 검증 지적 3건 수정 (`4b1a95e`)
- **[Minor]** Codex 프롬프트 에코 제거 + Gemini YOLO 노이즈 필터 (`10fdfd4`)
- **[Minor]** Codex 프롬프트 에코 제거 강화 + 도구 로그 노이즈 추가 (`bf7c024`)
- **[Minor]** Codex tokens used 노이즈 + 응답 중복 제거 (`897f318`)
- **[Minor]** Codex progress 메시지에서 헤더/프롬프트 노이즈 제거 (`661205c`)
- **[Minor]** Codex 응답 중복 제거 강화 (`2ccb09d`)

## v0.1.0 (2026-04-02)

### 개선
- **[Major]** watchdog 자동 재시작 + Slack 원격 제어 추가 (`47f15ab`)

### 버그 수정
- **[Minor]** watchdog 알림 중복 방지 및 안정성 개선 (`a910778`)

