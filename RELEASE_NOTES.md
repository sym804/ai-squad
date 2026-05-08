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

