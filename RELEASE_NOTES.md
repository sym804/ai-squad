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
| v0.8.2 | 2026-06-11 | agy 자동 업데이트 비활성화(가동 중 자가 교체 방지, 안정성) + agy 업데이터 콘솔 깜빡임 조사·수용(외부 차단 불가) |
| v0.8.3 | 2026-06-11 | 리서치 리포트 출처를 Slack 하이퍼링크(`<url\|짧은라벨>`)로 축약: 긴 URL(특히 Gemini 그라운딩 redirect 200자+) 숨김 |
| v0.8.4 | 2026-06-11 | v0.8.3 후속: 종합 답변/finding 본문의 인라인 URL도 축약(마크다운 `[x](url)`·꺾쇠·raw 전부 짧은 하이퍼링크로) |
| v0.8.5 | 2026-06-11 | 리서치 응답성: 하위 주제 6→4 축소(호출 13→10회) + 분담조사/교차검증 진행 카운터(`(n/N)` 실시간 갱신) |
| v0.8.6 | 2026-06-16 | 리서치 모드 재설계: 1차 출처 정독 + 결론 정교화(검증 NOTE 반영·증거 게이트·진행중/종료 구분) + 링크 안전 분할(긴 그라운딩 URL 두 동강 방지) |
| v0.8.7 | 2026-06-16 | v0.8.6 라이브 검증서 드러난 리서치 약점 3건 수정: 분해가 부모 질문·제약 누락(F1) / 종합 실패 시 raw 에러 방송(F2) / 타임아웃성 응답이 finding 으로 노출(F3) |
| v0.8.8 | 2026-06-25 | 토론 모드 cwd 미설정으로 Codex(workspace-write 샌드박스)가 외부 경로 평가 시 차단되던 버그 수정: 주제/질문의 화이트리스트 경로를 모든 에이전트 cwd 로 바인딩 |
| v0.8.9 | 2026-06-25 | `!bot restart` 한 번에 봇이 5중 spawn 되던 버그 수정: 재시작 디바운스+재진입 가드. 단일 인스턴스 lock 을 Windows named mutex(원자적·자동해제)로 하드닝 |
| v0.8.10 | 2026-06-25 | v0.8.9 후속: mutex 전환으로 lockfile 을 안 쓰게 되며 watchdog_guard 의 lockfile 기반 생존체크가 3분마다 헛 재기동(churn)하던 문제를, mutex 획득 후 lockfile 에 PID heartbeat 기록으로 해소 |
| v0.8.11 | 2026-07-03 | Claude 세션 한도 초과 메시지가 fatal 로 안 잡혀 백업 미투입 + "합의된 답변"으로 방송되던 버그 수정: 세션/사용량 한도 문자열 탐지 추가 + 최종답변 방어선 |
| v0.8.12 | 2026-07-03 | 테스트 격리: dev `.env` 의 `GEMINI_CLI_BINARY=agy` 가 config reload 시 monkeypatch 를 덮어써 `test_gemini.py::TestBinarySelection` 4건이 실패하던 문제를 load_dotenv 무력화로 해소(production config 미변경) |
| v0.8.13 | 2026-07-03 | `!bot restart` 한 번에 봇이 세션 수만큼(4중) 중복 spawn 되던 회귀 완화: `Local\` mutex 가 세션별이라 크로스세션 워치독을 못 막던 것을 lockfile PID alive-check 로 보강(잔여 동시 cold-start 레이스는 후속 LockFileEx 로 추적) |
| v0.8.14 | 2026-07-03 | v0.8.13 후속: 워치독 크로스세션 단일 인스턴스를 커널 파일락(`msvcrt.locking`)으로 원자적 봉합. 동시 cold-start 잔여 레이스 제거(비원자 PID pre-check 대체). 실측(크로스프로세스 배제+강제 kill 자동해제) 검증 |
| v0.8.15 | 2026-07-04 | agy 1.0.16 에서 upstream #76(`-p` stdout 미출력) 해소 실측 확인 + winpty 우회 부적합 판정(비-TTY 에서 실행 불가). 현재 디스크 복구 방식 유지(무비용 안전망). 코드 변경 없음(검증/문서) |
| v0.8.16 | 2026-07-08 | Codex exec 실행 로그(`exited -1073741502`=0xC0000142 등) Slack 누출 필터 보강(음수 exit·소수 duration·MCP failed/error·`Output:` 단독). 근본원인 규명: 봇이 S4U 세션0(무데스크톱)에서 뜨면 Codex 셸/스킬 자식이 STATUS_DLL_INIT_FAILED 로 전멸→무근거 답변(아키텍처 수정은 별도 이슈 추적) |
| v0.8.17 | 2026-07-08 | issue #131 대응(Option 1): 봇 S4U 세션0 에서 Codex 로컬 셸 도구가 0xC0000142 로 죽는 문제를, 토론/리서치 Codex 에 "로컬 셸 말고 MCP/지식으로 답하라" 지시(`avoid_shell`) 주입으로 doomed 셸 시도 억제. 무깜빡임 S4U 유지 + openaiDeveloperDocs MCP 그라운딩 존치 |
| v0.8.18 | 2026-07-08 | 재기동 후 Codex 오류: 원격 MCP openaiDeveloperDocs 의 일시적 HTTP 503 이 rmcp tracing 로그로 답변 누출 + fatal 오탐(→Codex 백업 교체). `_CODEX_TRACING_LOG` 필터 + `ask_with_progress` 가 정제된 답변으로 has_error 재판정(진짜 API fatal 은 유지) |
| v0.8.19 | 2026-07-13 | Slack 최근 대화 실측 분석에서 나온 6대 결함 수정: 실패 응답 원문 게시 차단(P1) + 폴백 경고 중복 제거 + 동일 엔진 2인 구성 고지(P2) + 스레드 단위 교체 유지(P3) + 합의 종료 게이트 재설계(P4, 어휘 유사도는 수렴 확인에만) + Codex 툴콜 preamble 제거(P6, `codex exec -o`) + dead config 제거 |
| v0.8.20 | 2026-07-13 | 타임아웃 정책/kill 사정거리 수정(이슈 #143~#149): 형제 에이전트 동반 사망 차단 + 에이전트별 숨은 타임아웃 배수 제거 + Claude 외부 가드 + 낡은 elapsed 보고 수정 + 코딩 백업 예산 동일화 + 리서치 자기-동시호출 제거 |

## v0.8.20 (2026-07-13)

Codex 교차검증이 지적하고 **Claude 가 코드로 재확인**한 타임아웃 계열 결함 6건. (Codex 가 자율적으로 커밋한 v0.8.21 은 리뷰 없이 들어가 되돌렸고(`0ced80b`), 여기서 직접 TDD 로 다시 구현했다.)

### 원인과 수정

- **[Major / backend] 한 에이전트의 타임아웃이 형제 에이전트 프로세스까지 죽였다** (`agents/base.py`, 이슈 #145)
  - `_kill_registered_processes()` 는 이름과 달리 `cancel.active_processes[thread_ts]` **전체**를 죽였다. 그런데 한 토론/리서치의 3개 에이전트는 같은 thread_ts 를 공유하며 `gather` 로 병렬 실행된다. 즉 Codex 가 타임아웃되면 답변 중이던 Claude/Gemini 의 CLI 를 같이 죽였다.
  - 실측 증거: 7/9 리서치 런 로그에 `[Claude-B] 응답 시간 초과 (180초)` 와 `[Codex-B] 응답 시간 초과 (180초)` 가 같은 런에서 동시에 찍혔다(조사 1건 유실).
  - 수정: `contextvars` 기반 **호출 스코프**(`_call_scope`/`_register_proc`) 도입. 타임아웃 정리는 **그 호출이 띄운 프로세스만** 죽인다. 같은 인스턴스를 동시에 두 번 호출해도(리서치 라운드로빈) 섞이지 않는다. `/cancel` 의 스레드 전체 kill 은 의도된 동작이라 그대로 유지.

- **[Major / backend] 같은 timeout 인자가 에이전트마다 다른 예산을 뜻했다** (`config.py`, `agents/claude.py`, `agents/gemini.py`, 이슈 #144)
  - base(Codex)=t, Claude=t*2, Gemini=t*2(외부 가드 t*2.5). `CLI_TIMEOUT_CODING=300` 하나로 Codex 는 300초, Claude 는 600초, Gemini 는 750초를 받았다. 코딩 모드에서 Codex 만 먼저 죽고, 그 타임아웃이 #145 를 타고 형제까지 죽였다.
  - 수정: 숨은 배수 전부 제거. `timeout=t` 는 모든 에이전트에서 "이 호출의 예산 t 초". 실효 예산을 유지하려고 상수를 올렸다: `CLI_TIMEOUT 180 → 360`, `CLI_TIMEOUT_CODING 300 → 600`.

- **[Major / backend] 코딩 모드 백업이 primary 보다 짧은 예산으로 호출됐다** (`modes/coding.py`, 이슈 #148)
  - `backup.ask(prompt)` 에 timeout 인자가 없어 기본 `CLI_TIMEOUT` 로 줄었다. primary 가 코딩 예산으로도 못 끝낸 일을 백업에 더 짧은 시간으로 시키는 꼴이라 이중 실패 확률만 올렸다. `timeout=CLI_TIMEOUT_CODING` 명시.

- **[Major / backend] 리서치가 같은 에이전트 인스턴스에 소주제 2건을 동시 배정했다** (`modes/research.py`, 이슈 #149)
  - 소주제 4개를 에이전트 3개에 라운드로빈하면 한 인스턴스가 2건을 맡는다. 동시에 돌리면 `timed_out`/`has_error`/`last_usage` 인스턴스 상태가 서로 덮어써져 멀쩡한 조사가 "실패" 로 버려질 수 있다.
  - 수정: `_run_assigned()` 로 분리해 **에이전트 간에는 병렬, 같은 에이전트 안에서는 순차** 실행. 에이전트 간 병렬성은 그대로 유지된다.

- **[Minor / backend] Claude 스트리밍에 외부 가드가 없어 읽기 루프 밖 hang 이 영구 대기** (`agents/base.py`, `agents/claude.py`, 이슈 #146)
  - `await proc.stdin.drain()` 등 읽기 루프 **밖** await 에는 데드라인이 없었다(Gemini 33분 hang 사고와 같은 계열).
  - 수정: `base.ask_with_progress` 가 `_stream_once` 를 `t * GUARD_FACTOR(1.25)` 로 감싸고, 가드 발동 시 그 호출의 프로세스만 정리한다. Claude 는 `_stream_once` 만 오버라이드하므로 자동 적용. Gemini 의 기존 가드도 `t*2.5 → t*1.25` 로 통일.

- **[Minor / backend] 타임아웃 보고 숫자가 최대 60초 낡은 값이었다** (`agents/claude.py`, 이슈 #143)
  - 루프 진입 시점에 `elapsed` 를 재고 readline 을 고정 60초 기다린 뒤 그 값을 보고했다(실측 "574초" = 실제 634초). 한도 검사도 루프 진입 시점에만 해서 실효 상한이 `t + 60` 이었다.
  - 수정: readline 대기를 `min(60, 남은 예산)` 으로 자르고, 보고 직전 `elapsed` 재측정. `start_time` 을 spawn 전으로 옮겨 spawn/drain 도 예산에 포함.

- 이슈 #147(가드 취소 시 부산물 누수)은 Codex 가 **자기가 새로 넣은 가드**를 전제로 쓴 지적이라 현재 코드엔 해당 없음. codex `-o` 파일은 v0.8.19 에서 이미 `finally` 정리된다.

### 테스트
- 신규 7건(`tests/test_timeout_and_kill_scope.py`): 형제 프로세스 보호 / `/cancel` 은 전체 kill 유지 / timeout 인자 = 실제 예산 / 낡은 elapsed 금지 / 루프 밖 hang 가드 / 코딩 백업 예산 동일 / 리서치 자기-동시호출 0. 전체 478건 통과.
- 실제 CLI 3개(Claude·Codex·Gemini) 병렬 호출로 회귀 확인: 3개 모두 정상 응답, 형제 kill 없음.

## v0.8.19 (2026-07-13)

Slack 최근 대화 12건(토론 5 / 코딩 1 / 리서치 6)과 `bot_output.log` 10,643줄을 대조 분석해 나온 결함을 한 번에 수정. 개별 답변 품질이 아니라 **폴백 처리**와 **합의 판정** 두 축의 설계 결함이었다.

### 원인과 수정

- **[Major / backend] 실패 응답 원문이 정상 답변으로 게시됨** (`modes/debate.py`, `modes/coding.py`)
  - 증상: `You've hit your session limit · resets 1:20am` 이 🟠 *[Claude]* 말풍선 + `출력 0 | $0.000` 으로 게시된 뒤에야 폴백 경고가 붙었다(최근 대화 6회). 코딩 모드도 `[Claude] 응답 대기 시간 초과 (574초)` 를 같은 방식으로 게시.
  - 원인: `_ask_and_post()` 가 응답을 **먼저 post** 하고, 오류 판정 루프는 `asyncio.gather()` 완료 **후에** 따로 돌았다. `agent.has_error` 는 post 시점에 이미 True 인데 post 경로가 그 플래그를 안 봤다.
  - 수정: post 전에 `needs_replacement` 를 확인해 실패 응답은 게시하지 않는다. 실패 응답은 `history`/`round_consensuses` 에서도 제외해 다음 라운드 프롬프트 오염을 막는다. 백업이 없으면 침묵 대신 "대체 에이전트 없음" 을 고지.

- **[Minor / backend] 같은 사건에 폴백 경고 2개 중복 게시** (`modes/debate.py`, `modes/coding.py`)
  - `⚠️ 대체 투입` (폴백 루프) 과 `⚠️ 이후 라운드부터 교체` (`_replace_agent`) 가 항상 쌍으로 나왔다. 한 줄로 병합.

- **[Major / backend] 동일 엔진 2인 구성인데 "전원 합의" 로 선언** (`modes/debate.py`)
  - Claude 장애 시 폴백이 Codex-B(= Codex 와 같은 CLI/모델)라 3자 중 2인이 같은 엔진이 된다. 3계열을 3에이전트가 점유한 상태에서 하나가 죽으면 구조상 피할 수 없다(같은 계열 백업은 세션 한도를 공유하므로 더 나쁨).
  - 수정: 백업 선택 로직은 유지하되, 결론 브로드캐스트에 `동일 엔진 2인 구성(...)` 고지를 붙여 합의가 실제보다 강해 보이지 않게 한다.

- **[Major / backend] 후속 질문마다 죽은 에이전트를 다시 호출** (`modes/debate.py`)
  - 증상: 콜드브루 스레드에서 22:39 / 22:50 / 22:56 세 번, 매 추가 토론 첫 라운드마다 같은 세션 한도 에러가 다시 노출되고 폴백 절차를 처음부터 다시 밟았다.
  - 원인: 봇이 메시지마다 `DebateMode` 를 새로 만들어(`slack_bot.py:194,205`) 교체 상태(`self._replaced`)가 스레드 안에서 유지되지 않았다.
  - 수정: 모듈 전역 `_THREAD_REPLACED[thread_ts]` 에 교체를 기억하고 `_bind_thread` 에서 복원해 첫 라운드부터 백업으로 시작한다. 상한 200스레드(오래된 것부터 폐기). 프로세스 재기동 시 초기화 = 원본 재시도.

- **[Major / backend] 합의 조기 종료가 사실상 불가능** (`modes/debate.py`)
  - 증상: 로그의 라운드 판정 639건 중 `diverged=True` 가 606건(94.8%). 3/3 만장일치인 354건조차 발산으로 찍혀 교전 라운드(에이전트 3회 호출)를 매번 낭비했다.
  - 원인: `_summaries_diverge()` 가 한국어를 어절 단위로 자르는 토크나이저로 Jaccard 유사도를 재고 **최소** 페어값을 썼다. 실측 보정 결과 **어휘 유사도로는 합의와 불합의를 구분할 수 없다**: 같은 결론을 다른 표현으로 쓴 진짜 합의가 bigram 0.027 인데, 서로 배타적인 결론(라멘/파스타/초밥)이 0.045 로 오히려 더 높았다. 토크나이저나 임계값을 바꿔도 해결되지 않는다.
  - 수정: 유사도는 **수렴 확인**에만 쓴다. 요약이 확실히 수렴하면 라운드 1 즉시 종료를 허용하고, 그 외에는 **상호 검토 1회(라운드 2)** 를 채운 뒤 종료한다(라운드 1은 서로의 발언을 보기 전이라 `agree=true` 가 근거 없는 자기신고다). 교전 라운드는 `CONSENSUS.disagreements` 에 구조적 쟁점이 실제로 기록됐을 때만 1회 강제. 실측 기준 축구/AI비교 스레드가 3라운드 → 2라운드로 줄어든다.

- **[Minor / backend] Codex 툴콜 preamble 이 답변에 노출** (`agents/codex.py`)
  - 증상: "현재 판매처와 가격을 먼저 확인하겠습니다" 같은 준비 문장이 답변 앞머리에 붙었다(에이전트 발언 121건 중 32건, 26%).
  - 원인: Codex 는 최종 메시지 추출 로직 없이 `codex exec` 의 stdout 전량을 누적한 뒤 라인 단위 노이즈 필터만 태웠다. 툴 호출 직전 모델이 뱉은 preamble 은 산문이라 필터를 통과한다. (Claude 는 stream-json 의 `result` 이벤트만 채택한다.)
  - 수정: `codex exec -o FILE` 로 **마지막 에이전트 메시지만** 받아 답변으로 채택한다. stdout 은 진행 표시용으로 계속 읽는다. 파일이 없으면 기존 stdout 정제 경로로 폴백하고, 타임아웃이면 이전 호출의 잔여 파일을 쓰지 않는다. 실제 CLI 로 검증 완료.

- **[Trivial / etc] dead config 제거** (`config.py`, `.env.example`, `README.md`)
  - `CONSENSUS_EARLY_ROUNDS` 는 `debate.py` 가 import 만 하고 한 번도 쓰지 않았다. `.env` 의 값 5는 아무 효과가 없었다.

### Codex 교차검증에서 추가로 잡은 결함 (커밋 전 수정)

- **[Major / backend] 백업까지 실패하면 백업의 에러 원문이 게시됨** (`modes/debate.py`, `modes/coding.py`)
  - 1차 실패는 막았는데 이중 장애 경로가 그대로였다. 백업 응답도 `needs_replacement` 를 확인해 원문 대신 "백업도 실패" 만 알리고, 그 슬롯 없이 라운드를 진행한다.
- **[Major / backend] 코딩 Phase 3(테스트 작성)에는 실패 응답 게시 가드가 없었음** (`modes/coding.py`)
  - Phase 3 는 세 에이전트 결과를 먼저 게시한 뒤 교체를 검사했다. 실측 5월 스레드에서 Gemini 의 node-pty 경로 에러와 Claude 의 574초 타임아웃이 답변 말풍선으로 올라온 지점.
- **[Major / backend] 백업 풀 소진 시 이미 투입된 백업 인스턴스를 중복 삽입** (`modes/debate.py`)
  - `_get_backup()` 이 후보가 없으면 풀 전체로 되돌아가, 같은 객체가 `self.agents` 에 두 번 들어가고 한 인스턴스가 동시에 호출될 수 있었다(기존 코드부터 있던 잠재 결함). 이제 `None` 을 반환하고 호출부가 "대체 에이전트 없음" 을 고지한다.
- **[Major / backend] codex `-o` 파일 경로를 인스턴스 필드에 두어 동시 호출이 충돌** (`agents/base.py`, `agents/codex.py`)
  - 리서치 분담 조사는 같은 에이전트 인스턴스에 소주제 2건을 동시에 배정할 수 있다. 이때 두 호출이 같은 필드를 덮어써 서로의 출력 파일을 읽거나 지운다. 경로를 호출별 prompt tmp 에서 파생(`<tmp>.last.md`)하고, base 에 `_finalize_output`/`_cleanup_artifact` 훅을 추가해 타임아웃/취소/예외 경로에서도 `finally` 로 반드시 삭제한다.
- **[Major / backend] 스레드 교체 기록 eviction 이 자기 자신을 지움** (`modes/debate.py`)
  - 용량(200) 초과 시 무조건 가장 오래된 키를 버렸는데, 그 키가 지금 기록 중인 스레드면 앞선 교체가 날아가 죽은 에이전트가 다시 투입된다. 새 스레드를 넣을 때만 폐기하도록 고치고, 스레드별 OS 스레드에서 접근하므로 `threading.Lock` 으로 read-modify-write 를 직렬화했다.
- Codex 가 지적한 `MAX_DEBATE_ROUNDS` 경계(1 또는 `COMPLEX_MIN_ROUNDS` 미만)는 기존 "최대 라운드 도달" 분기가 결론을 내므로 회귀가 아님을 회귀 테스트로 확인하고 코드는 두었다.

### 테스트
- 신규 30건: `tests/test_debate_failure_flow.py`(10), `tests/test_codex_last_message.py`(8), `tests/test_coding_failure_post.py`(3), `tests/test_codex_review_v0819.py`(9). 전체 474건 통과.
- `tests/conftest.py` 에 `_THREAD_REPLACED` 초기화 fixture 추가(전역 상태가 테스트 간 누수돼 다른 파일의 `ts1` 케이스를 오염시켰다).
- 실제 Codex CLI 로 최종 메시지 추출·임시 파일 정리를 실측 확인(응답에 preamble 없음, `*.last.md` 잔존 0건).

### 알려진 한계 (후속)
- **합의 선언 시점의 수치 불일치**: 붓코미메시 스레드가 최저가 16,580원 vs 19,110원으로 갈린 채 "전원 합의"로 끝났다. 합의 판정이 자기신고 `agree` 플래그에 의존할 뿐 숫자/사실 충돌을 검증하지 않기 때문. 별도 설계 변경 필요.
- **리서치 소주제 드롭**: 조사 실패 시 재시도 없이 해당 소주제가 리포트에서 통째로 빠진다(`modes/research.py:575-594`).
- 인프라 잡음: 소켓 SSL 에러 197회, socket-mode JSONDecodeError, 워치독 CRASH 감지 13회.

## v0.8.18 (2026-07-08)

v0.8.16/17 적용 후 봇 재기동(`!bot restart`, 세션0 유지)에서 셸 크래시(`exited -1073741502`)는 사라졌으나, 재기동 직후 토론에서 Codex 가 원격 MCP `openaiDeveloperDocs` 초기화 중 **일시적 HTTP 503**을 만나 그 rmcp 로그가 답변에 누출되고 봇이 Codex 를 백업(Gemini-B)으로 교체하는 새 증상이 나타났다. Slack thread `1783481931`.

### 원인
- `openaiDeveloperDocs` MCP 는 **원격**(`url=https://developers.openai.com/mcp`)이라 세션과 무관. 재기동 직후 이 엔드포인트가 일시적으로 503(연결 거부)을 반환 -> Codex 가 `<ISO8601>Z ERROR rmcp::transport::worker: ... HTTP 503 ...` tracing 로그를 출력.
- (1) 이 로그가 답변 본문에 누출됨(v0.8.16 필터는 exec-log/`Output:`/`mcp:` 형식만 잡아 tracing 로그는 못 잡음).
- (2) 로그의 `HTTP 503` 이 봇 `_is_fatal_error`(base) 를 오탐 -> `has_error=True` -> Codex 가 유효 답변(두산에너빌리티/한화에어로스페이스 추천)을 냈는데도 백업으로 교체됨. 봇은 progress 경로에서 **정제 전 raw** 로 fatal 을 판정하므로 필터만으론 교체를 못 막음.
- 엔드포인트는 조사 시점 정상(HTTP 200) -> 503 은 재기동 직후의 일시적 blip.

### 수정
- **[Minor / backend] tracing 로그 라인 필터 + fatal 재판정** (`agents/codex.py`):
  - `_CODEX_TRACING_LOG` 정규식(`<ISO8601 타임스탬프>Z LEVEL target:` 형식) 신설 -> rmcp/transport 등 Codex 내부 tracing 로그 라인 제거(누출 봉합). `LEVEL target:` 까지 요구해 일반 산문/로그 예시 오삭제 최소화.
  - `CodexAgent.ask_with_progress` 가 base 의 raw 기반 `has_error` 를 **정제된 답변 기준으로 재판정**(cleaned 비어있지 않고 timed_out 아닐 때). 일시적 MCP 오류로 유효 답변을 낸 Codex 가 벤치되지 않게. 진짜 API fatal(쿼터/5xx/세션한도)은 필터가 안 지우므로 그대로 유지.
- 회귀 테스트 6건(tracing 제거 3 + 재판정 3: 일시오류 비fatal / 진짜fatal 유지 / 빈답변 base유지), 전체 443건 통과. Codex 교차검증 반영(정규식 엄격화 `LEVEL target:`, 넓은 `rmcp::` substring 제거).

### 참고
- MCP 엔드포인트가 지속적으로 죽으면 별개 문제. `openaiDeveloperDocs` 는 OpenAI 문서 검색용이라 일반 토론엔 무관하나(정상 시 OpenAI-docs 질문엔 유용), 이번 수정으로 그 일시적 실패를 답변 누출·fatal 오탐 없이 견딘다.

## v0.8.17 (2026-07-08)

v0.8.16 에서 규명한 근본 원인(봇이 S4U 세션0=무데스크톱에서 뜨면 Codex 로컬 `shell` 도구가 콘솔 자식 생성 실패 `0xC0000142` 로 즉사)에 대해 **Option 1(S4U 무깜빡임 유지 + Codex 셸 억제)** 을 적용한다. 봇 소유자 결정: Slack 은 주로 토론/리서치 용도라 로컬 셸이 거의 불필요하고, cmd 창 깜빡임(v0.8.1~v0.8.2 에서 제거/수용)을 되살리지 않는 쪽을 택함.

### 배경 (config 실측)
- Codex MCP 서버는 `openaiDeveloperDocs`(search/fetch) 1개뿐이며 in-process 라 **세션0 에서도 정상 동작**. `~/.codex/skills` 는 비어 있어 로컬 스킬 없음. `features.memories` 도 in-process. 즉 세션0 에서 유일하게 죽는 건 내장 `shell`(PowerShell spawn) 도구 하나.
- 토론/리서치(일반 지식·사실 주제)는 셸이 거의 불필요(범용 웹검색 도구도 없음) -> 셸 억제해도 실질 손실 없음. 셸이 필요한 건 코딩/로컬프로젝트 평가뿐(드묾).

### 수정
- **[Minor / backend] 토론/리서치 Codex 에 셸 억제 지시(`avoid_shell`)** (`agents/codex.py`, `modes/debate.py`, `modes/research.py`): `_NO_SHELL_DIRECTIVE`(로컬 셸 쓰지 말고 openaiDeveloperDocs MCP·지식으로 답하라; read/MCP 는 허용) 를 `CodexAgent(avoid_shell=True)` 일 때 프롬프트 앞에 1회 주입. 토론/리서치 Codex 메인+백업에 적용. 코딩 모드는 기본 False(셸 필요, 대화형 세션이면 정상 동작).
- doomed 셸 시도 자체를 줄여 크래시·지연·토큰낭비 방지. 잔여 크래시는 v0.8.16 필터가 안전망.

### 검증
- 실측(`avoid_shell=True` + 스레드 질문): raw 에 `exited -1073741502`·PowerShell 시도 흔적 없음, Codex 가 openaiDeveloperDocs MCP·지식으로 그라운딩된 답변 + 미확인 항목(agy)은 단정하지 않음(스레드의 과잉단정 개선).
- 회귀 테스트 4건(`TestCodexAvoidShellDirective`), 전체 436건 통과. Codex 교차검증.

### 남은 것
- 코딩 모드 Codex 의 셸은 세션0 에서 여전히 못 씀(드문 용도라 수용). 완전 복구가 필요하면 Option 2(대화형 세션 상주 = 깜빡임 부활)를 별도 선택. issue #131 은 Option 1 적용으로 종료.

## v0.8.16 (2026-07-08)

Slack `#ai-토론` 스레드(`1783475712`)에서 Codex 답변에 `Output:` 빈 블록과 `exited -1073741502 in 31ms:`, `mcp: openaiDeveloperDocs/search_openai_docs (completed)` 같은 실행 로그 조각이 누출되고, Codex 가 실제 도구 없이 무근거로 답하던 문제를 조사했다. 표면 누출은 노이즈 필터로 봉합하고, 근본 원인(세션/데스크톱)을 규명했다.

### 근본 원인 (규명)
- `exited -1073741502` = `0xC0000142` = **STATUS_DLL_INIT_FAILED**: 자식 콘솔 프로세스가 데스크톱/윈도우 스테이션 없이 초기화에 실패하는 Windows 코드.
- 봇이 **S4U 세션 0(대화형 데스크톱 없음)**에서 구동되면 Codex 가 셸/스킬용으로 띄우는 PowerShell·스킬 러너 자식이 전부 이 코드로 즉사한다. in-process MCP(`search_openai_docs (completed)`)는 콘솔 자식이 아니라 정상 -> 스레드에서 MCP 만 성공하고 셸/스킬만 죽은 것과 일치.
- 어느 워치독이 단일 인스턴스 락을 먼저 잡느냐로 세션이 갈린다: `watchdog_guard.py`(S4U, 세션 0)의 `start_watchdog()` 가 이기면 봇->Codex->PowerShell 트리가 세션 0에 뜬다. Interactive 워치독이 이기면 데스크톱이 있어 Codex 도구가 정상 동작(활성 세션 A/B 실측: workspace-write·danger-full-access 둘 다 무크래시).
- 즉 v0.8.1 의 "S4U 비대화형으로 옮겨 cmd 창 깜빡임 제거"가 Codex 셸/스킬 도구를 깨뜨린 상충. **아키텍처 수정(봇을 항상 데스크톱 세션에서 구동 vs 깜빡임 감수)은 별도 이슈로 추적.**

### 수정 (이번 커밋 = 표면 누출 필터)
- **[Minor / backend] Codex 실행 로그 누출 필터 보강** (`agents/codex.py`): `_CODEX_EXEC_LOG_LINE` 앵커드 정규식 신설. 단독 라인 `exited -?\d+ in \d+(.\d+)?m?s:`(음수·소수 duration 포함), `mcp: <srv>/<tool> started|completed|failed|error`, `Output:` 를 제거. 기존 `exited 0/1 in` 서브스트링 리터럴은 산문 오삭제 위험이 있어 제거하고 앵커드 정규식이 전담(`^...$` 라 "함수의 Output: 42"·"process exited 0 in my demo" 같은 본문은 보존).
- 회귀 테스트 7건(`tests/test_codex_clean.py::TestExecLogLeak`), 전체 432건 통과.
- Codex 교차검증 PASS(앵커링·백트래킹·커버리지). 제안 3건(소수 duration·MCP failed/error·기존 리터럴 제거) 전부 반영.

### 참고
- danger-full-access 로 샌드박스를 여는 방향도 검토했으나, 활성 세션 A/B 에서 workspace-write 든 danger-full-access 든 크래시가 재현되지 않아 **크래시의 원인이 샌드박스가 아님**을 확인 -> 채택하지 않음(보안 유지, workspace-write 존치).

## v0.8.15 (2026-07-04)

`agy -p` stdout 미출력 버그(upstream #76, v0.7.10 에서 디스크 transcript 복구로 우회)에 대해, "winpty 를 앞에 붙여 가상 TTY 를 강제하면 agy 가 stdout 을 뱉는다"는 대안 우회를 실호출로 비교 검증했다. 결론: **winpty 방식은 봇 환경에서 원천적으로 실행 불가**이며, 부수적으로 **agy 1.0.16(7/3 갱신)에서 #76 자체가 해소**됐음을 확인했다. 코드/테스트 변경 없음(현행 유지).

### 실측 (봇과 동일 조건: `stdin=DEVNULL`, `stdout=PIPE`, `AGY_CLI_DISABLE_AUTO_UPDATE=1`)
- **A) 순수 `agy -p`**: `exit=0`, stdout=`"51\n"`(정상 출력). 반복 4회 100% 재현(51/100/101/102), 회당 약 6.5초. **#76 이 1.0.16 에서는 비-TTY(pipe/subprocess)에서도 재현되지 않음** (릴리즈 노트상 원 버그는 1.0.0~1.0.6 기준).
- **B) `winpty agy -p`**: `exit=1`, stdout 0바이트, stderr=`"stdin is not a tty"`. `stdin=DEVNULL`/`PIPE` 둘 다 동일 실패. winpty `--help` 에 non-TTY 우회 옵션 없음. **winpty 자체가 stdin 이 실제 TTY 가 아니면 실행을 거부**하므로, 봇(headless subprocess)에서는 agy 실행조차 불가.
- **C) 현재 디스크 복구(`_recover_agy_response_retry`, 실코드)**: agy 원출력이 3바이트로 나오므로 실제 봇 경로에선 `if GEMINI_CLI_BINARY == "agy" and not out_text:` 가 거짓 -> 복구 미발동, stdout 직접 사용. 복구 함수 자체는 정상 동작(`"51"` 회수) 확인.

### 판정
- **winpty 교체 안 함**: winpty 는 대화형 터미널 전용 도구라 봇의 비-TTY subprocess 에서 `stdin is not a tty` 로 죽는다. 이식성/출력 오염(ANSI 이스케이프) 이전에 실행 자체가 안 되므로 후보에서 제외.
- **현재 방식 유지**: #76 이 1.0.16 에서 해소돼 봇은 이제 빠른 stdout 직행 경로로 동작한다. 디스크 복구 코드는 stdout 결손 시에만 발동(발동 시에도 무비용)하므로, agy 향후 회귀 대비 **무비용 안전망**으로 존치. `AGY_CLI_DISABLE_AUTO_UPDATE=1` 로 버전 고정 중이나 수동 업데이트 회귀 대비 목적.

### 참고
- agy 1.0.16 로 `& agy -p` 직접 호출 hang(#76 부작용, v0.7.10 참고)도 재현되지 않음(봇은 `stdin=DEVNULL` 이라 원래도 영향권 밖).
- 코드/테스트 무변경이라 커밋 대상은 문서(RELEASE_NOTES.md)/이슈로그뿐.

## v0.8.14 (2026-07-03)

v0.8.13 의 lockfile PID alive-check 는 서로 다른 세션의 두 워치독이 stale lockfile 상태로 동시에 cold-start 하면 둘 다 통과할 수 있는 잔여 레이스가 있었다(Codex Major). 이를 커널 바이트영역 파일락으로 **원자적으로** 봉합한다.

### 개선
- **[Major / etc] 크로스세션 단일 인스턴스 원자적 봉합(커널 파일락)**: `_acquire_single_instance_filelock()` 신설. `.watchdog.single` 파일을 열어 `msvcrt.locking(LK_NBLCK, 1)` 로 1바이트 배타 잠금. `acquire_lock`(win32)에서 mutex 획득 후 이 파일락을 획득하고, 실패하면 `exit(0)`. v0.8.13 의 비원자 PID pre-check 는 제거(파일락이 대체하며 PID 재사용 오탐도 함께 제거). `release_lock` 에 핸들 해제 추가.
  - **원자성**: 커널 byte-range 락이라 open→lock 사이 TOCTOU 없이 정확히 하나만 승리. 동시 cold-start 레이스 제거.
  - **세션 무관**: named mutex `Local\` 가 세션별이라 S4U 세션 0 vs 대화형 세션 워치독을 못 막던 게 근본 원인이었는데, 파일락은 세션 경계와 무관하게 배제.
  - **자동 해제**: 프로세스가 죽으면(크래시/kill/로그아웃) OS 가 락을 회수 → stale lock 없음.
  - **특권 불필요**: `Global\` mutex 와 달리 `SeCreateGlobalPrivilege` 불필요 → S4U Limited 에서도 fail-closed 안 됨.
  - heartbeat 용 `.watchdog.lock`(guard 가 read) 과 락 파일 `.watchdog.single` 을 분리해 mandatory 락이 guard 의 PID read 를 막지 않게 함.

### 검증
- **실측(mock 아님)**: (1) pytest win32 - 동일 프로세스 두 핸들 상호배제 + close 시 자동해제, 파일락 보유 중 `.watchdog.lock` read 정상. (2) 크로스프로세스 스크립트 - 자식이 락 보유 중 부모 배제(None), 자식 **강제 kill** 후 부모 획득 성공(OS 자동해제). (3) 실제 프로젝트 디렉터리(OneDrive 밖, 로컬 NTFS)에서 바이트락 배제 동작 확인.
- watchdog 21건 / 전체 425건 통과(회귀 없음). v0.8.13 의 비원자 pre-check 테스트 3건은 파일락 테스트로 교체.
- **Codex 교차검증**: 원자성·fail-closed·핸들 수명·guard 분리·release/restart 무회귀 전부 PASS. 이전 Major(동시 cold-start 레이스) 해소 확인. Minor 하나(락 성공 전 non-OSError 예외 시 핸들 누수) 반영(try/finally 로 close). 나머지 Trivial(heartbeat 실패 로깅, mutex 잉여)은 무해로 유지.

### 한계 (문서화)
- **로컬 파일시스템 전용**: OneDrive/네트워크 공유처럼 서로 다른 머신의 동기화 복사본은 동일 커널 파일 객체가 아니라 cross-machine 배제는 제공하지 않는다(단일 머신 단일 인스턴스가 목표라 무관). 현 배포 경로는 로컬 NTFS(OneDrive 밖) 확인.
- 가동 중 `.watchdog.single` 을 수동 삭제/이동하지 말 것(핸들 보유 중 삭제는 로컬 NTFS 에서 기본 거부됨).

## v0.8.13 (2026-07-03)

사용자가 `!bot restart` 를 한 번 눌렀는데 "재시작 완료, Bot 시작됨" 메시지가 서로 다른 PID 로 **4번** 떴다. 실측(Win32 프로세스 트리): watchdog.py 프로세스가 **5개**(S4U 세션 0 에 4개 + 대화형 세션에 1개) 동시 가동 중이었고, 각 워치독이 `!bot restart` 를 독립 처리해 봇을 하나씩 spawn 했다. 근본 원인은 watchdog.py 의 단일 인스턴스 mutex 이름이 `Local\slack_multi_agent_watchdog` 로 **세션별(per-logon-session) 네임스페이스**라, 예약작업 2개(`SlackBotWatchdog`=Interactive, `SlackBotWatchdogGuard`=S4U 세션 0)가 서로 다른 세션에서 띄운 워치독끼리 mutex 로 배제되지 않고 무기한 공존한 것(+ mutex 도입 전 기동된 6월 스테일 워치독 누적).

### 버그 수정
- **[Major / etc] 크로스세션 워치독 중복 완화(lockfile alive-check)**: `acquire_lock` 의 win32 경로에서 mutex 획득 전에 `.watchdog.lock` 의 PID 를 `_is_pid_alive`(OpenProcess, 세션 무관)로 확인해, **살아있는 다른 워치독이 있으면 exit(0)**. `Local\` mutex 는 동일 세션 원자성용으로 유지. 후발 기동이 항상 기존 워치독을 보고 종료하므로 정상상태는 단일 인스턴스로 수렴한다. `Global\` mutex 는 S4U Limited 에서 `SeCreateGlobalPrivilege` 부재 시 생성 실패(fail-closed)로 워치독이 아예 안 뜰 위험이 있어 채택하지 않았다.

### 알려진 한계 (후속 추적)
- 서로 다른 세션의 두 워치독이 **stale lockfile 상태에서 동시에 cold-start** 하면 둘 다 pre-check 를 통과할 수 있는 잔여 레이스가 남는다(예약작업 주기 3분/5분로 정렬 확률은 낮음). 완전한 원자적 크로스세션 배제는 `LockFileEx`(커널 파일락, 세션 무관·특권 불필요·종료 시 자동 해제)로 봉합 예정. GitHub 이슈로 추적.
- lockfile PID 가 무관 프로세스에 재사용되면 `_is_pid_alive` 오탐으로 기동이 억제될 수 있다(기존 `watchdog_guard.is_watchdog_running` 과 동일한 한계). PID 신원검증(생성시각/cmdline)은 후속 하드닝에서 함께 처리.

### 검증
- 신규 테스트 3건(`test_acquire_lock_exits_when_other_session_watchdog_alive`/`_proceeds_when_lockfile_pid_dead`/`_proceeds_when_lockfile_pid_is_self`) + 기존 mutex 테스트 2건을 tmp_path 로 결정론화. watchdog 테스트 20건 통과, 전체 424건 통과(회귀 없음).
- **Codex 교차검증**: pre-check 로직 정합성·정상 재시작 무영향·기존 mutex 경로 보존·Global 회피 정당성 전부 PASS. Major(잔여 동시 cold-start 레이스)는 mitigation 의 알려진 한계로 위 '알려진 한계'에 명시 + 후속 이슈로 추적. Minor(PID 재사용)는 기존 공유 한계로 문서화.
- **스테일 프로세스 정리**: 이미 떠 있는 세션 0 스테일 워치독/봇은 코드로 못 죽인다(대화형 세션에서 Access denied, 관리자 권한 필요). 운영자가 elevated 로 정리.

## v0.8.12 (2026-07-03)

`tests/test_gemini.py::TestBinarySelection` 4건(default/empty/explicit-gemini/invalid)이 봇을 agy 로 가동 중인 개발 머신에서 실패했다. 원인은 `config.py` 가 import 시 `load_dotenv(override=True)` 로 .env 를 읽는데, 이 테스트들이 `GEMINI_CLI_BINARY` 를 monkeypatch 한 뒤 `importlib.reload(config)` 를 하면 reload 가 `load_dotenv(override=True)` 를 재실행하면서 dev `.env` 의 `GEMINI_CLI_BINARY=agy` 가 monkeypatch 값을 덮어써 config 가 항상 agy 로 잡힌 것(테스트 격리 결함). v0.8.11 작업 중 발견.

### 버그 수정
- **[Minor / etc] TestBinarySelection 의 .env 누수 차단(테스트 격리)**: `_restore_gemini_default` autouse fixture 에 `monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: False)` 추가. config reload 가 .env 를 다시 읽지 않아 monkeypatch 한 값이 유지된다. monkeypatch 가 fixture teardown 이후 마지막에 undo 되므로 teardown 의 reload 동안에도 패치가 유효해, teardown 이 config 를 gemini 기본값으로 정상 복원한다. production `config.py` 의 `override=True`(shell env 보다 .env 우선)는 봇 동작상 의도된 정책이라 미변경.

### 검증
- `test_gemini.py::TestBinarySelection` 10건 전부 통과(이전 4 실패 → 0), 전체 스위트 421건 통과(회귀 없음).
- **Codex 교차검증**: 병합 차단 사유 없음(통과). 패치 재바인딩 방식·fixture/monkeypatch teardown 순서·격리 범위·conftest 무충돌·override=True 유지 판단 전부 확인. 발견 이슈 전부 Minor/Trivial(제품 결함 아님).

## v0.8.11 (2026-07-03)

Slack thread 1782980989 회귀. Claude Code CLI 가 5시간 세션 한도에 걸리면 예외가 아니라 평범한 stdout 텍스트 `You've hit your session limit · resets 7:50pm (Asia/Seoul)` 를 정상 반환하는데, 기존 fatal 에러 탐지(`agents/base.py` `_is_fatal_error`)의 `_FATAL_SUBSTRINGS`/`_FATAL_REGEX` 가 이 문자열을 커버하지 않았다. 그 결과 (1) `has_error=False` → `needs_replacement=False` → 백업 대체 투입이 트리거되지 않아 Claude 가 9라운드 내내 `출력 0` 죽은 참가자로 남고, (2) `_generate_final_answer` 가 교체 안 된 Claude 를 통합문 후보로 잡고 `_is_bad_final_answer` 도 이 메시지를 못 걸러서, 최종 "💡 합의된 답변" 이 세션 한도 메시지 그 자체로 방송됐다(사용자 질문에 대한 답이 "너 세션 한도 초과됨"). v0.7.7(API 500 방송 수정)과 동형 버그의 세션 한도 버전.

### 버그 수정
- **[Major / backend] 세션 한도 메시지 fatal 탐지 추가(탐지 계층)**: `_FATAL_SUBSTRINGS` 에 `hit your session limit`/`reached your session limit`/`usage limit reached` 3개 full-phrase 추가. 실측 문구(`You've hit your session limit ·`) + 널리 문서화된 변형(`Claude usage limit reached ...`)을 커버. full-phrase 라 일반 토론의 `session limit`/`한도` 단독 언급에는 오탐하지 않음(benign 테스트로 확인). 이 하나로 백업 자동 투입이 정상화되고, 교체된 Claude 가 최종답변 후보에서도 자동 제외됨.
- **[Major / backend] 최종답변 방어선(defense-in-depth)**: `_is_bad_final_answer` 에 `_is_fatal_error(answer)` 검사 추가(`callable` 가드 포함). 탐지 계층이 어떤 이유로 놓치더라도 fatal 패턴이 답변 본문에 있으면 "합의된 답변" 방송을 차단. `_is_fatal_error` 가 `_FATAL_SUBSTRINGS`/`_FATAL_REGEX` 단일 소스를 쓰므로 탐지 계층과 자동 동기.

### 검증
- 신규 테스트 11건(`test_session_limit_detected` 5 파라미터 + `test_benign_limit_mentions_not_flagged` 4 파라미터 + `test_session_limit_not_broadcast_as_answer` + `test_session_limit_first_agent_falls_back_to_second`) 통과. TDD 레드→그린 확인.
- 전체 스위트: 기존 회귀 없음(무관한 `test_gemini.py::TestBinarySelection` 4건은 로컬 `.env` 의 `GEMINI_CLI_BINARY=agy` 로 인한 기존 실패, stash 대조로 이번 변경과 무관 확인).
- **Codex 교차검증**: 병합 차단 사유 없음(통과). 탐지 경로(has_error→needs_replacement→백업 교체)·최종답변 guard 통합·import 정합성·보안 전부 통과. 발견 이슈 전부 Minor/Trivial: Trivial(guard `callable` 가드)만 반영, 나머지(변형 문구 추정 확장 자제·긴 로그 가운데 미검사·결정적 merge fatal 필터)는 기존 설계 트레이드오프이거나 별개 하드닝(scope)이라 이번 변경서 제외.

## v0.8.10 (2026-06-25)

v0.8.9 의 named mutex 전환 후, 배포 점검 중 `watchdog_guard.py`(3분 주기 예약작업)의 `is_watchdog_running()` 이 `.watchdog.lock` 의 PID 로 워치독 생존을 판정한다는 사실을 확인. 새 워치독이 mutex 만 쓰고 lockfile 을 안 써서 가드가 'dead' 로 오판 → 3분마다 워치독을 재기동(매번 mutex `ERROR_ALREADY_EXISTS` 로 즉시 종료)하는 churn/콘솔 깜빡임이 발생할 수 있었다(실제로 구버전 lock 의 중복 방지 실패로 워치독 2개가 동시 가동 중인 것도 확인).

### 버그 수정
- **[Minor / etc] mutex 전환 후 watchdog_guard churn 방지(lockfile heartbeat)**: `acquire_lock()` 의 Windows 경로에서 mutex 획득 성공 후 `.watchdog.lock` 에 현재 PID 를 heartbeat 로 기록. 실제 단일 인스턴스 보장은 여전히 mutex(원자적·종료 시 OS 자동해제)가 하고, lockfile 은 가드 생존체크용 정보일 뿐이라 race 와 무관. 가드가 live PID 를 보는 동안 lockfile 을 건드리지 않으므로 1회 기록으로 churn 해소. 종료/크래시 시 stale 가 되면 가드가 dead 로 보고 정상 재기동(새 워치독이 mutex 획득 후 lockfile 갱신).

### 검증
- `test_watchdog` 17건(`test_acquire_lock_uses_mutex_on_win32` 이 tmp lockfile 에 PID heartbeat 기록을 단언, 실제 `.watchdog.lock` 미오염 확인) + 전체 405 통과.
- **Codex 교차검증**: 핵심 4항목(heartbeat 가 mutex 단일성 불침해 / 가드 churn 해소 / 정상·크래시 시 stale→재기동 흐름 / 테스트 적절성) 전부 통과. 잔여 Minor/Trivial(lockfile 쓰기 실패 시 churn 잔존-단 중복은 mutex 가 차단, PID 재사용, 동시 가드 경합)은 모두 기존 가드 liveness 방식의 한계로 이번 변경과 무관.

## v0.8.9 (2026-06-25)

`!bot restart` 를 한 번 보냈는데 워치독이 봇을 5개(서로 다른 PID, 일부 6ms 간격 동시) spawn 한 사고. 워치독은 단일 인스턴스(`.watchdog.lock`)·단일 스레드인데도 `start_bot()` 의 재진입 가드(`bot_process.poll() is None`)가 비원자적(TOCTOU)이라 재시작이 짧게 겹치면 중복 spawn 됐다. 중복 봇들은 Slack 소켓 충돌로 곧 죽고 1개로 수렴했으나, 근본 원인을 제거했다.

### 버그 수정
- **[Major / etc] `!bot restart` 1회에 봇 다중 spawn**: `restart_bot()` 에 재진입 가드(`_restart_in_progress`)와 디바운스(`RESTART_DEBOUNCE=10`초, `time.monotonic` 기준)를 추가해 단일 명령 = 단일 재시작을 보장. 진행 중이거나 직전 재시작 직후의 중복 요청은 무시. `finally` 에서 `auto_restart`/`manual_stop`/`_restart_in_progress` 를 항상 정상 post-restart 값으로 복구해, 도중 `stop_bot()`/`notify` 예외로 플래그가 누수돼 이후 크래시 자동재시작을 건너뛰던 결함도 차단.

### 하드닝
- **[Major / etc] 단일 인스턴스 lock 을 Windows named mutex 로 전환**: 기존 PID lockfile 의 `acquire_lock()` 은 `O_EXCL` 경쟁 패배 시 lock 을 덮어쓰고 계속 실행해 중복 워치독을 허용할 수 있었다(원인 사고와는 별개의 잠재 결함). Windows 는 커널 named mutex(`CreateMutexW`)로 전환 - 생성이 원자적이고 프로세스 종료 시 OS 가 자동 해제하므로 stale lock/빈창/double-takeover race 가 원천 소거된다. 이미 보유 중이면(`ERROR_ALREADY_EXISTS`) 즉시 종료, 생성 실패 시 racy 폴백으로 내려가지 않고 fail-closed 종료. 비-Windows 폴백 파일락도 takeover 없이 fail-closed 로 단순화.

### 검증
- 신규/강화 테스트(`test_watchdog`) 총 **17건**: restart 디바운스/재진입/예외 시 상태복구, Windows mutex 디스패치·이미보유시종료·생성실패 fail-closed, `_acquire_win_mutex` 단위(신규생성/ALREADY_EXISTS/실패), 파일락 생성·기존존재 종료, `release_lock`(mutex CloseHandle/파일 unlink). 전체 회귀 **405건 통과**(사전이슈 `test_gemini` 4건은 `.env` `GEMINI_CLI_BINARY=agy` 환경누수로 무관).
- **Codex 교차검증 5라운드**: Major 4건(자연어 경로추출, 파일락 race 2건, Windows 폴백 도달성, 비-Windows takeover race) + Minor 4건(monotonic, manual_stop/auto_restart 누수, 테스트 커버리지)을 라운드별로 전부 반영. 최종 6라운드(확인)는 Codex 컴패니언 작업이 멈춰 보류, 마지막 1줄(auto_restart) 수정은 직전 라운드에서 승인된 manual_stop 수정과 동일 패턴 + 테스트 커버.

## v0.8.8 (2026-06-25)

토론 모드에서 "경로 X 의 프로젝트를 평가해줘" 류 주제를 줄 때 Codex 만 해당 경로를 읽지 못하고 실패(Windows `exited -1073741502` = 0xC0000142 STATUS_DLL_INIT_FAILED)하던 문제. Codex 는 `codex exec -s workspace-write` 샌드박스라 cwd(워크스페이스) 밖 파일 접근이 막히는데, 토론 모드는 coding/bridge 모드와 달리 작업 디렉토리를 전혀 설정하지 않아 Codex 워크스페이스가 봇 폴더에 고정됐다. Gemini/Claude CLI 는 워크스페이스 스코프가 없어 영향받지 않아, 같은 토론에서 Codex 만 "권한 문제"처럼 보이며 평가를 보류했다(실제로는 권한이 아니라 샌드박스 자식 프로세스 시작 실패).

### 버그 수정
- **[Major / backend] 토론 모드가 cwd 미설정이라 Codex 가 외부 경로를 못 읽음**: `DebateMode._bind_thread(thread_ts, request_text)` 로 변경해, 주제(start)·후속질문+원주제(followup)에서 화이트리스트(`ALLOWED_WORK_DIRS`) 안의 경로를 추출(`security.extract_work_path`)·검증(`validate_work_dir`)해 모든 에이전트와 백업 풀의 `_cwd` 로 바인딩한다(미지정/비허용 시 None 으로 초기화해 스레드 간 cwd 누수 방지). 경로 추출 로직은 `CodingMode._extract_path` 에서 `security.extract_work_path` 로 공유화하고, 자연어 suffix("...경로 를 평가해줘")도 디렉토리까지 줄여 찾도록 보강.

### 검증
- 신규 테스트 7건(`test_debate_cwd`): 화이트리스트 경로/하위경로/자연어 suffix/비허용/무경로/스레드 reset/followup 원주제 바인딩. 광범위 회귀 **123건 통과**(coding_gate·config·debate integration/improvements/gates·consensus·bridge·process 포함).
- **Codex 교차검증 2라운드**: 1차에서 Major 1건(다단어 suffix 추출 실패) + Minor 3건 지적 → 전부 반영. 2차에서 잔여 이슈 없음 확인.
- **운영자 조치 필요**: 토론으로 평가할 프로젝트는 `.env` 의 `CODING_ALLOWED_DIRS` 에 등록해야 한다. sym-ui 평가용으로 `C:\Users\ymseo\Documents\sym-ui` 추가. 이 화이트리스트는 coding 모드 쓰기 범위도 겸하므로, 등록 경로는 coding 쓰기 신뢰 대상이기도 하다(읽기 전용 분리는 추후 옵션).

## v0.8.7 (2026-06-16)

v0.8.6 배포 후 6개 주제 라이브 검증(리서치 vs 토론)에서 리서치 모드의 별개 약점 3건 확인. 특히 "87키 풀알루미늄 키보드 15만원 이하 추천"에서 리서치가 분해 과정에 예산·사양 제약을 흘려 75% 키보드(87키 위반)를 섞어 추천하고, Claude CLI 세션 한도 소진 시 "You've hit your session limit" 에러가 종합 답변으로 방송됐다.

### 버그 수정
- **[Major / backend] F1 - 분해가 부모 질문·제약을 하위질문에 누락**: 일부 서브에이전트가 제약 위반 답("87키" 요구에 75% 보드)을 내거나 "위 두 금리"처럼 맥락이 빠져 조사 불가가 됨. (1) `_build_decompose_prompt`에 자기완결성 지시(대명사 금지·대상·제약 직접 명시) (2) `_build_research_prompt(subq, question=None)`로 원질문 전문을 각 조사 프롬프트에 주입(`_research_one`이 전달) (3) `_build_synthesize_prompt`에 "원질문 제약 모두 충족 점검, 위반 후보 제외" 규칙 추가.
- **[Major / backend] F2 - 종합 실패 시 raw 에러 방송**: 신규 `_looks_like_failure()`로 종합 실패(세션한도/예외/빈값) 감지 → 에러 문자열 대신 검증 리포트로 폴백 방송. 봇 실패 래퍼(`[name] …시간 초과/할당량 초과/호출 예외`)는 정규식, CLI 한도 에러는 길이 무관, 일반어(rate limit/quota 등)는 짧은 에러 응답형에서만 매칭해 정상 finding 오탐 방지.
- **[Minor / backend] F3 - 타임아웃성 응답이 finding 으로 노출**: `_research_one`에서 `_looks_like_failure`로 실패성 텍스트(`…시간 초과` 등)를 finding 에서 드롭(드롭 수는 "조사 N건 실패" 안내에 포함). F1 컨텍스트 주입으로 모호한 하위질문발 타임아웃 트리거 자체도 감소.

### 검증
- 리서치 단위 테스트 신규 8건(원질문 임베드·하위호환·자기완결 분해·제약 재확인·실패 감지 헬퍼·타임아웃 변형/오탐·종합 폴백·실패 finding 드롭), 리서치 테스트 총 **70건 통과**. 전체 386건 수집 정상.
- **Codex 교차검증**: 1차에서 4건 지적(영문 타임아웃 미탐·일반 마커 substring 오탐·짧은 synth·dropped 카운터) → 전부 반영. 단 "영문 response timeout 추가" 제안은 코드 확인 결과 실제 실패 문자열이 전부 한국어(`시간 초과`/`할당량 초과`)임을 확인해 한국어 정규식으로 정확 매칭(Codex 제안 교정).
- 라이브 재검증: v0.8.7 로 봇 재시작 후 키보드 토픽 재실행으로 F1(제약 유지) 확인 예정.
- (참고) `test_gemini` 4건 실패는 `.env`의 `GEMINI_CLI_BINARY=agy` 환경 결합 사전 이슈로 무관.

## v0.8.6 (2026-06-16)

실사용 비교(#ai-리서치 vs #ai-토론, 동일 질문 "중개형 ISA 이벤트 증권사 추천")에서 리서치가 토론보다 느린데도 더 나쁜 결과를 낸 문제. (1) 교차검증(Codex)이 한국투자증권의 6월 진행 이벤트를 찾아 "키움뿐" 결론과 충돌한다고 플래그까지 걸었는데 종합 단계가 이를 무시 → 틀린 결론, (2) 메시지 분할이 긴 Gemini 그라운딩 URL을 두 동강 내 출력 깨짐.

### 버그 수정
- **[Major / backend]** 교차검증이 찾은 교정 사실이 종합에 전달되지 않던 결함: `_findings_block`이 종합 프롬프트에 `[status] 본문+출처`만 넘기고 **검증자 NOTE(교정 사실)를 누락**해 틀린 결론("키움뿐")이 생존. NOTE를 블록에 포함하도록 수정(modes/research.py).
- **[Major / backend]** `_post_long`/`_broadcast_long`의 맹목 분할(`text[:3900]`)이 긴 `<url|label>` 링크(특히 Gemini 그라운딩 200자+ redirect) 한가운데를 잘라 두 메시지에서 모두 깨지던 문제: 신규 `_split_for_slack()`로 줄/링크 경계를 보존해 분할(링크 토큰 내부 비절단, max_len 초과 링크는 통째로). 이중/중첩 꺾쇠(`<<...>>`) 잔재도 `_shorten_urls_in_text`에서 연속 꺾쇠 축약으로 방어.

### 개선
- **[Major / backend]** 리서치 정확도·정교화 재설계(단일 패스 유지): 조사 단계에 **1차 출처(공식·공시·규제기관) 직접 fetch·정독** + 최신성(현재 진행중/과거 종료) 구분 의무화. 종합 단계는 disputed면 NOTE를 사실로 받아 **결론 교정/철회**, 주장마다 1차 1개 포함 출처 ≥2개일 때만 '확정', 진행중/종료/불확실 3구간 분리 + 비교형은 순위표(혜택·기간·조건·1차출처). 검증 단계는 인용된 1차 출처 재fetch로 시점·수치 대조. 분량 1500→2500자.
- **[Minor / frontend]** 쟁점 미리보기가 60자에서 말줄임 없이 끊겨 깨진 듯 읽히던 문제: 60자 초과 시 `...` 말줄임 + 개행 정규화.

### 검증
- 리서치 단위 테스트 신규 11건 추가(링크 안전 분할/초과링크 통째/이중꺾쇠 방어/findings_block NOTE 포함/종합·조사·분해 프롬프트 규칙/쟁점 말줄임), 리서치 테스트 총 **62건 통과**. 전체 378건 수집 정상.
- **Codex 교차검증**: 통과(지정 테스트 61건) + Minor 1건(긴 단일 링크 경계 케이스가 "링크 비절단" 주석과 불일치) 지적 → 초과 링크를 쪼개지 않고 통째로 내보내도록 수정 + 회귀 테스트 추가로 반영.
- 설계 문서: `docs/superpowers/specs/2026-06-16-research-mode-redesign-design.md`.
- 잔여: 1차 출처 정독은 외부 CLI 도구 사용에 의존(프롬프트 계약+검증 재fetch로 보강). 라이브 재실행(동일 ISA 질문으로 한투가 진행중으로 잡히는지 실측)은 봇 가동·실제 CLI 환경 필요로 미수행.
- (참고) `test_gemini` 4건 실패는 `.env`의 `GEMINI_CLI_BINARY=agy`(agy 실가동) 환경 결합 사전 이슈로 본 변경과 무관.

## v0.8.5 (2026-06-11)

리서치 1건 처리에 약 7분이 걸리고 그동안 진행 단계가 불투명해 "멈춘 건가?" 답답함이 있던 문제 개선(실사용 피드백).

### 개선
- **[Minor / backend]** `RESEARCH_SUBQ_MAX` 기본값 6 → **4** 로 축소. 질문당 AI 호출이 약 13회(분해1+조사6+검증6+종합1) → 약 10회(분해1+조사4+검증4+종합1)로 줄어 체감 소요시간 단축. config 기본값·`.env`·`.env.example` 동기화.
- **[Minor / frontend]** 분담 조사·교차검증 단계에 **진행 카운터** 추가. 기존 "분담 조사 중..." 정적 메시지를 `(0/N)` 으로 게시한 뒤, 각 병렬 작업이 끝날 때마다 `chat_update` 로 `(n/N)` 실시간 갱신 → 어디까지 진행됐는지 눈에 보임("멈춤" 오인 방지). 신규 헬퍼 `_post_get_ts()`/`_update()`. 게시 실패(ts None) 시 graceful 무시.

### 검증
- 진행 카운터: `gather` 병렬 코루틴의 `nonlocal` 카운터는 await 이후 동기 구간에서 증가 → 이벤트 루프 단일 스레드 특성상 경합 없음. 단위 테스트(`(0/N)` 게시 + `chat_update` 카운터 갱신) 포함, 리서치 테스트 총 51건 통과.
- `RESEARCH_SUBQ_MAX = 4` 적용 확인.
- Codex 교차검증.

## v0.8.4 (2026-06-11)

v0.8.3 배포 후 라이브 확인 결과, 구조화된 `📚 출처:` 블록은 축약됐으나 **모델이 생성한 `💡 종합 답변:` 본문**에 여전히 긴 URL이 노출되는 문제 확인. 원인: LLM 이 출처를 `[매체명](<url>)` 마크다운으로 박는데 **Slack 은 마크다운 링크를 미지원**해 URL 원문이 그대로 풀림(특히 Gemini 그라운딩 redirect 200자+).

### 개선
- **[Minor / frontend]** 신규 `_shorten_urls_in_text()`(modes/research.py)로 **모델 생성 본문의 모든 URL 형태**(마크다운 `[label](<url>)`/`[label](url)`, 꺾쇠 `<url>`·`<url|label>`, raw URL)를 Slack 짧은 하이퍼링크 `<url|라벨>`로 정규화. 종합 답변(`synth`)과 리포트 finding 본문에 적용. **견고성**: 균형 괄호 URL(예: Wikipedia `/wiki/Mercury_(planet)`) 보존, 잉여 닫는 괄호·trailing 문장부호(`.,;:!?…` 등)는 본문으로 복원, 이미 감싼 URL 재치환 방지(lookbehind), **멱등성** 보장.

### 검증
- 실사용 #ai-리서치 스레드의 실제 본문 패턴(마크다운 링크 안 200자+ redirect, raw URL+콤마, 괄호 URL 등)으로 before/after 확인.
- 단위 테스트 13건 추가(마크다운 꺾쇠/bare·괄호 보존·문장부호 절단·멱등성·잉여 괄호 종료 등), 리서치 테스트 총 50건 통과.
- **Codex 교차검증 4회**: 1차(방향) → 2차(raw 괄호/문장부호 Medium) → 3차(마크다운 괄호 Medium) → 4차(해소 확인, Low 성능만). 각 라운드 지적을 반영해 정규식 견고화.

## v0.8.3 (2026-06-11)

리서치 리포트 `📚 출처:` 블록이 `도메인: 전체URL` 형식이라 URL이 너무 길게 표시되던 문제 개선(실사용 #ai-리서치 스레드에서 확인).

### 개선
- **[Minor / frontend]** 출처를 Slack 하이퍼링크 `<url|라벨>`로 렌더해 **긴 URL을 링크 뒤로 숨기고 짧은 라벨만 노출**. 라벨 = 도메인 + 짧고 의미있는 경로 끝 세그먼트(percent-encoding 디코딩), 경로가 없거나 28자 초과/무의미하면 도메인만. 특히 Gemini 웹 그라운딩의 `vertexaisearch.cloud.google.com/grounding-api-redirect/...`(토큰 200자+)가 도메인 한 줄로 정리됨. 같은 도메인 다중 출처(wikipedia 등)는 경로 끝으로 구분. 신규 함수 `_short_source_label()`(modes/research.py), Slack `<url|label>` 파싱을 깨는 `|`·`<`·`>`는 라벨에서 제거.

### 검증
- 실사용 스레드의 실제 URL 24종으로 before/after 시연(redirect 200자+ → 도메인 한 줄).
- 단위 테스트 7건 추가(라벨 도메인+경로끝/동일도메인 구분/긴 토큰 fallback/경로없음/디코딩/특수문자 제거/리포트 하이퍼링크 렌더), 리서치 테스트 총 33건 통과.
- Codex 교차검증.

## v0.8.2 (2026-06-11)

리서치 모드 실사용 중 재발한 cmd 콘솔 깜빡임을 근본 원인까지 추적한 결과, agy 자체의 자동 업데이터(`agy --bg-updater` → `agy --version`)가 매 호출마다 잠깐 띄우는 콘솔 창이 원인임을 ground-truth(실행 중 봇 자손 프로세스 트리 + 보이는 창 실측)로 확정.

### 조사 결론 (깜빡임)
- **근본 원인**: agy 가 호출될 때마다 백그라운드 업데이터를 띄우고, 그 안의 `agy --version`(버전 체크) 콘솔 창이 대화형 데스크톱에 수십 ms 노출됨. 리서치 모드는 agy 를 6+개 병렬 호출하므로 깜빡임이 몰려 눈에 띔. (v0.7.11 의 claude→context7, v0.8.1 의 agy statusline 과는 또 다른 제3의 원인)
- **외부 차단 불가 (전부 실측)**: `AGY_CLI_DISABLE_AUTO_UPDATE=1`(업데이트만 막고 버전체크 창은 잔존), `last_check.timestamp` 미래화(매 호출 spawn + agy 가 즉시 리셋), S4U 세션 격리(로그인 중이면 같은 세션), 부모 `CREATE_NO_WINDOW`(detached 손자라 안 닿음), 숨김 데스크톱 `lpDesktop`(6중 4 여전히 표시 - agy 가 대화형 데스크톱 직접 타깃), agy CLI 플래그(그런 옵션 없음) 모두 무효 확인.
- **처분**: 알려진 agy 한계로 **수용/문서화**(Trivial 외관 이슈, 기능 영향 없음). gemini tier 종료(2026-06-18) 후 agy 필수라 바이너리 복귀도 임시방편.

### 변경 (안정성)
- **[Minor / backend]** `config.make_filtered_env()` 에서 agy 사용 시 자식 env 에 `AGY_CLI_DISABLE_AUTO_UPDATE=1` 주입. 봇 가동 중 agy 가 자기 실행 파일을 자동 교체(update_status.json 에 "Update successful, restart CLI to use" 실제 발생 이력)하면 진행 중 호출이 깨질 수 있어 차단. **깜빡임 방지가 아니라 안정성 목적**(주석 명시).

### 검증
- 깜빡임 근본 원인: 실행 중 slack_bot.py 자손 트리 모니터로 `agy --version` 보이는 창 ground-truth 포착.
- 억제 시도 6종 전부 A/B·반복 실측으로 무효 확인(1회 표본의 위양성 배제).
- config 변경: agy 일 때 env 주입 동작 단위 확인 + 기존 테스트 29건 통과 + Codex 교차검증(Medium 지적은 정규화 로직 미반영 위양성으로 기각).

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

