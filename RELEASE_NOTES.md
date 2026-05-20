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

