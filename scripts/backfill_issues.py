"""과거 커밋을 issue_log.xlsx / RELEASE_NOTES.md / GitHub Issues로 소급 백필.

사용법:
  python scripts/backfill_issues.py xlsx      # issue_log.xlsx 생성
  python scripts/backfill_issues.py notes     # RELEASE_NOTES.md 생성
  python scripts/backfill_issues.py gh        # GitHub 이슈 생성+close
  python scripts/backfill_issues.py all       # 위 3개 전부 (주의: gh 많이 호출됨)
"""
import sys
import subprocess
import os
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

REPO = "sym804/ai-squad"

# (hash, date, type, severity, area, title, body_summary)
# type: bug | enhancement
# severity: block | critical | major | minor | trivial
# area: backend | db | frontend | security | etc
ISSUES = [
    ("47f15ab", "2026-04-02", "enhancement", "major",    "backend",  "watchdog 자동 재시작 + Slack 원격 제어 추가",                          "슬랙 봇 프로세스를 watchdog으로 감시하여 크래시 시 자동 재시작하고, 슬랙 메시지로 원격 제어 가능하도록 함."),
    ("a910778", "2026-04-02", "bug",         "minor",    "backend",  "watchdog 알림 중복 방지 및 안정성 개선",                              "동일 이벤트에 대해 watchdog 알림이 중복 전송되던 문제 수정."),
    ("52c08d9", "2026-04-04", "enhancement", "major",    "backend",  "Bridge 모드 + 오류 감지 대체 투입 + load_dotenv override",           "외부 디렉토리를 slack 채널로 브리징하는 Bridge 모드 추가. 에이전트 오류 감지 시 대체 에이전트 투입. load_dotenv override 처리."),
    ("28d15de", "2026-04-04", "bug",         "minor",    "backend",  "coding followup에 누락된 기능 동기화 (debate와 통일)",                "coding 모드 followup 처리가 debate 모드와 일부 기능이 불일치하여 통일."),
    ("dda0ea9", "2026-04-04", "enhancement", "major",    "backend",  "!stop 강제 중단 + 코딩 모드 개선 + 작업 취소 시스템",                 "!stop 명령으로 진행 중인 에이전트 강제 중단. 작업 취소 상태 관리 시스템 도입."),
    ("919e3ab", "2026-04-04", "enhancement", "minor",    "backend",  "Claude 응답에 토큰 사용량 표시 (k 단위)",                             "Claude 에이전트 응답 말미에 사용한 토큰 수를 k 단위로 표시."),
    ("a7137ba", "2026-04-04", "enhancement", "major",    "backend",  "코딩 모드 스트리밍 진행 표시 + idle 타임아웃",                        "코딩 모드에서 Claude 진행 상황을 실시간 스트리밍으로 표시하고 idle 타임아웃 추가."),
    ("6ac67f3", "2026-04-04", "bug",         "minor",    "backend",  "코딩 채널 스레드 답글을 Claude 추가 지시로 변경",                     "코딩 채널 스레드 답글이 새 작업으로 인식되던 문제 → 기존 작업에 대한 추가 지시로 처리."),
    ("58ed3f1", "2026-04-04", "enhancement", "minor",    "backend",  "코딩 채널 followup 에이전트 자동 선택",                               "코딩 채널 followup 시 컨텍스트 기반으로 적절한 에이전트를 자동 선택."),
    ("0d07943", "2026-04-04", "enhancement", "major",    "backend",  "전 에이전트 스트리밍 진행 표시 + 복수 에이전트 동시 지정",           "Claude뿐 아니라 Codex/Gemini도 스트리밍 진행 표시. 메시지에 복수 에이전트 동시 지정 가능."),
    ("c0d9a3f", "2026-04-04", "bug",         "minor",    "backend",  "Codex 코드 리뷰 지적사항 4건 수정",                                   "Codex 리뷰에서 지적된 4건(리소스 관리, 예외 처리 등)을 반영."),
    ("2922da9", "2026-04-04", "bug",         "major",    "backend",  "코딩 모드 에이전트를 임시 디렉토리에서 실행",                         "에이전트가 임의 디렉토리에서 실행되며 보안/안정성 우려 → 임시 디렉토리로 격리."),
    ("168e061", "2026-04-04", "bug",         "minor",    "backend",  "코딩 채널 followup에 스레드 히스토리 포함",                           "followup 처리 시 스레드 히스토리가 누락되어 컨텍스트 부족 → 히스토리 포함."),
    ("f7190a1", "2026-04-04", "enhancement", "major",    "backend",  "코딩 채널 병렬 모드 지원",                                            "코딩 채널에서 복수 에이전트가 동시에 작업하는 병렬 모드 추가."),
    ("7fb2588", "2026-04-04", "bug",         "minor",    "backend",  "stream-json 제거, 경과 시간 표시로 변경",                             "stream-json 파싱 불안정 → 경과 시간 표시 방식으로 단순화."),
    ("40709f4", "2026-04-04", "enhancement", "minor",    "backend",  "Claude 작업 내용 실시간 표시 + Codex/Gemini 경과 시간",               "Claude는 내용, Codex/Gemini는 경과 시간으로 실시간 표시."),
    ("aac1c0b", "2026-04-04", "enhancement", "minor",    "backend",  "모든 에이전트 작업 내용 실시간 표시 통일",                            "모든 에이전트가 동일 형식으로 실시간 작업 내용 표시."),
    ("d8d93bf", "2026-04-04", "enhancement", "minor",    "backend",  "봇 재시작 시 모든 채널에 작업 중단 알림",                             "봇 재시작 시 모든 감시 채널에 작업이 중단되었음을 알림."),
    ("fc92628", "2026-04-04", "enhancement", "minor",    "backend",  "모든 에이전트 경과 시간 + 내용 하이브리드 표시",                      "에이전트별로 경과 시간과 내용을 혼합한 하이브리드 포맷 표시."),
    ("1ba2a03", "2026-04-04", "bug",         "minor",    "backend",  "코딩 모드 cwd를 홈 디렉토리로 변경",                                  "코딩 모드 에이전트의 cwd가 의도치 않은 위치였던 문제 수정."),
    ("8903462", "2026-04-04", "enhancement", "minor",    "backend",  "봇 재시작 시 진행 중이던 스레드에 중단 알림",                         "채널 전체가 아닌 실제 진행 중이던 스레드에만 중단 알림."),
    ("a3a8fa6", "2026-04-04", "bug",         "trivial",  "backend",  "진행 박스 항상 코드블록 표시",                                        "진행 박스가 조건부로 평문 표시되던 문제 → 항상 코드블록으로 통일."),
    ("70ca6da", "2026-04-04", "bug",         "minor",    "backend",  "ask_with_progress stderr를 stdout으로 합쳐서 읽기",                   "stderr 소실 문제로 에러 진단 불가 → stdout과 병합."),
    ("572d6ff", "2026-04-04", "enhancement", "minor",    "backend",  "Codex --full-auto 모드로 셸 실행 권한 부여",                          "Codex가 셸 명령을 자동 실행하도록 --full-auto 옵션 부여."),
    ("ae6fe10", "2026-04-04", "enhancement", "minor",    "backend",  "Gemini -y (YOLO) 모드로 도구 자동 승인",                              "Gemini가 도구 호출을 자동 승인하도록 -y 옵션 부여."),
    ("3d93409", "2026-04-04", "bug",         "minor",    "backend",  "Gemini stderr 무시 (xterm.js 터미널 이스케이프 차단)",                "Gemini stderr에 xterm.js 이스케이프 코드 혼입 → stderr 무시."),
    ("ad710b4", "2026-04-04", "bug",         "minor",    "backend",  "진행 메시지 삭제 안 되는 문제 수정",                                  "작업 완료 후에도 진행 메시지가 삭제되지 않던 문제 수정."),
    ("9bb9434", "2026-04-04", "bug",         "minor",    "backend",  "Gemini stderr 다시 캡처 + xterm.js 노이즈 라인 필터링",               "stderr 무시로 인한 진단 정보 손실 → 캡처하되 xterm.js 노이즈는 라인 단위 필터."),
    ("a7ee916", "2026-04-04", "bug",         "minor",    "backend",  "Codex CLI 헤더 노이즈 제거 + Slack 메시지 분할 전송",                 "Codex 출력 헤더의 노이즈가 Slack 메시지에 포함되던 문제 수정. 장문은 분할 전송."),
    ("d761822", "2026-04-04", "enhancement", "minor",    "backend",  "병렬 모드 완료 후 Codex가 최종 보고서 작성",                          "병렬 모드 완료 시 Codex가 각 에이전트 결과를 통합하여 최종 보고서 작성."),
    ("422d6b7", "2026-04-04", "enhancement", "minor",    "backend",  "파이프라인 모드 최종 보고서도 Codex가 작성",                          "병렬뿐 아니라 파이프라인 모드에서도 Codex가 최종 보고서 작성."),
    ("87ad4f4", "2026-04-04", "bug",         "major",    "backend",  "Gemini quota 재시도 3회 초과 시 즉시 중단 + 대체 에이전트 투입",      "Gemini quota 초과 시 무한 재시도로 자원 낭비 → 3회 초과 시 중단하고 대체 에이전트 투입."),
    ("fa0fda3", "2026-04-04", "enhancement", "minor",    "backend",  "병렬 모드에 대체 에이전트 투입 추가",                                 "병렬 모드에서도 에이전트 실패 시 대체 에이전트 자동 투입."),
    ("437b129", "2026-04-04", "bug",         "minor",    "backend",  "에이전트 출력 정리",                                                  "각 에이전트별 출력 포맷 정리."),
    ("8674f6c", "2026-04-04", "bug",         "major",    "backend",  "자기 자신의 bot_id만 무시, 다른 봇 메시지는 처리",                    "모든 봇 메시지를 무시하여 다른 봇과 연계 불가 → 자기 자신의 bot_id만 무시."),
    ("0273fdd", "2026-04-04", "bug",         "minor",    "backend",  "ClaudeBackupAgent를 ClaudeAgent 상속으로 변경",                       "중복 구현 → ClaudeAgent 상속 구조로 단순화."),
    ("8518091", "2026-04-04", "bug",         "major",    "backend",  "병렬 모드 타임아웃 + 크래시 복구 강화",                               "병렬 모드에서 한 에이전트가 무한 대기 시 전체 멈춤 → 타임아웃 적용하고 크래시 시 복구."),
    ("3709496", "2026-04-04", "bug",         "trivial",  "etc",      "테스트 mock 불일치 수정 + send_test.py 제거",                         "테스트 mock 시그니처 불일치 수정. 불필요한 send_test.py 제거."),
    ("4b1a95e", "2026-04-04", "bug",         "minor",    "backend",  "Codex 검증 지적 3건 수정",                                            "Codex 코드 리뷰에서 지적된 3건 수정."),
    ("10fdfd4", "2026-04-04", "bug",         "minor",    "backend",  "Codex 프롬프트 에코 제거 + Gemini YOLO 노이즈 필터",                  "Codex 출력에 프롬프트가 에코되던 문제 + Gemini YOLO 모드 노이즈 필터."),
    ("bf7c024", "2026-04-04", "bug",         "minor",    "backend",  "Codex 프롬프트 에코 제거 강화 + 도구 로그 노이즈 추가",               "프롬프트 에코 제거 필터 강화 및 도구 로그 노이즈 패턴 추가."),
    ("897f318", "2026-04-04", "bug",         "minor",    "backend",  "Codex tokens used 노이즈 + 응답 중복 제거",                           "Codex 출력 말미의 tokens used 노이즈 제거 및 응답 중복 제거."),
    ("661205c", "2026-04-04", "bug",         "minor",    "backend",  "Codex progress 메시지에서 헤더/프롬프트 노이즈 제거",                 "Codex progress 메시지에 헤더/프롬프트 텍스트 혼입 문제 수정."),
    ("2ccb09d", "2026-04-04", "bug",         "minor",    "backend",  "Codex 응답 중복 제거 강화",                                           "Codex 응답 중복 제거 휴리스틱 강화."),
    ("05f7189", "2026-04-05", "bug",         "major",    "backend",  "Windows에서 프로세스 트리 전체 종료 (taskkill /F /T)",                "Windows에서 자식 프로세스가 종료되지 않아 좀비 프로세스 누적 → taskkill /F /T로 프로세스 트리 전체 종료."),
    ("df4631e", "2026-04-05", "enhancement", "minor",    "backend",  "kill_process_tree를 process.py로 통합",                               "각 모듈에 중복되던 kill 로직을 process.py로 통합."),
    ("4730134", "2026-04-05", "enhancement", "major",    "security", "security.py에 경로 화이트리스트 검증 추가",                           "에이전트가 임의 경로에서 실행되는 것을 방지하기 위해 경로 화이트리스트 검증 도입."),
    ("474f7a7", "2026-04-05", "enhancement", "minor",    "security", "bridge paths를 .env로 외부화 + env 필터링",                          "bridge 경로 하드코딩 제거. 에이전트 서브프로세스에 전달할 env 필터링."),
    ("52dbef8", "2026-04-05", "bug",         "minor",    "backend",  "cancel.py에서 kill_process_tree 사용",                                "cancel 시 자식 프로세스가 남아 좀비 프로세스 원인 → kill_process_tree로 정리."),
    ("1eb5303", "2026-04-05", "bug",         "major",    "security", "CodingMode._bind_thread에 경로 화이트리스트 강제 적용",              "thread 바인딩 시 경로 검증이 누락되어 화이트리스트 우회 가능 → 강제 적용."),
    ("0e8b1ed", "2026-04-05", "bug",         "major",    "security", "bridge 모드에서 shell=True 제거",                                     "shell=True 사용으로 명령 주입 가능성 → 리스트 인자 방식으로 변경."),
    ("396027e", "2026-04-05", "bug",         "major",    "security", "AgentBase에서 shell=True 제거 + 필터링된 env 사용",                   "AgentBase 역시 shell=True 취약 → 리스트 인자 + 필터링된 env."),
    ("ce76225", "2026-04-05", "bug",         "major",    "security", "모든 에이전트에서 shell=True 제거",                                   "모든 에이전트 구현체에서 shell=True 제거 및 stdin 파이프 사용."),
    ("8d3860d", "2026-04-05", "bug",         "major",    "security", "fail-closed 경로 화이트리스트 — fallback 금지",                       "화이트리스트 불일치 시 홈 디렉토리로 fallback하던 문제 → 거부 또는 안전 기본값, fallback 금지."),
    ("4bf87c2", "2026-04-05", "bug",         "major",    "security", "명시적 비화이트리스트 경로는 거부",                                    "명시적으로 지정된 비화이트리스트 경로를 fallback 없이 거부."),
    ("da5539b", "2026-04-05", "bug",         "critical", "backend",  "Windows .cmd CLI 래퍼용 platform_cmd() 추가",                         "Windows에서 codex/gemini가 .cmd 래퍼여서 shell 경유 없이는 호출 불가 → platform_cmd()로 감싸 Windows에서 정상 호출."),
    ("fd08351", "2026-04-05", "bug",         "minor",    "backend",  "AgentBase.ask_with_progress에 stdin 파이프 추가",                     "stdin 파이프 누락으로 일부 CLI가 EOF 대기하며 블로킹 → stdin 파이프 추가."),
    ("852ea4b", "2026-04-05", "bug",         "minor",    "backend",  "Codex 출력 정리 강화 — 파일 경로 노이즈 필터 + 중복 제거 threshold", "Codex 출력의 파일 경로 노이즈 필터 추가 및 중복 제거 threshold 조정."),
    ("743dba1", "2026-04-05", "bug",         "minor",    "backend",  "Codex PowerShell dir 출력 노이즈 필터 추가",                          "PowerShell dir 출력이 Slack 메시지에 포함되던 문제 수정."),
    ("8f5e841", "2026-04-10", "bug",         "major",    "backend",  "Codex 프롬프트 누출 수정 + Gemini 429 재시도/모델 fallback",         "Codex 응답에 시스템 프롬프트가 누출되던 문제 + Gemini 429 시 모델 fallback 구현."),
    ("6045e6c", "2026-04-10", "bug",         "minor",    "backend",  "Codex 오탐 감지 수정 — fatal error 패턴 맥락화 + head/tail 스캔",     "정상 응답의 일부 단어를 fatal error로 오탐 → 패턴 맥락화 및 head/tail 스캔."),
    ("db55108", "2026-04-10", "bug",         "minor",    "backend",  "Windows에서 에이전트 CLI 호출 시 cmd 창 깜빡임 제거",                 "Windows에서 에이전트 호출마다 cmd 창이 깜빡이던 UX 문제 → CREATE_NO_WINDOW."),
    ("4bc1602", "2026-04-10", "enhancement", "major",    "backend",  "토론 합의 후 통합 답변 생성",                                         "토론 모드에서 합의 도달 후 통합 답변을 생성하여 채널에 포스트."),
    ("7b9390d", "2026-04-10", "enhancement", "major",    "backend",  "watchdog 복원력 강화 + watchdog_guard 추가",                          "watchdog 자체가 죽을 경우를 대비해 watchdog_guard 추가."),
    ("908ad29", "2026-04-11", "bug",         "major",    "backend",  "Gemini 429 남발 해결 — preview/lite 모델 제거 + rate-limit 탐지 맥락화","Gemini 429가 자주 발생 → preview/lite 모델 제거하고 rate-limit 탐지 맥락화."),
    ("e116b46", "2026-04-11", "bug",         "major",    "backend",  "Gemini readline 타임아웃 이중화",                                     "복잡한 프롬프트에서 Gemini가 버퍼링되어 readline이 멈추던 문제 → 타임아웃 이중화."),
    ("c6764d2", "2026-04-11", "bug",         "major",    "backend",  "Gemini CLI 내부 재시도를 실패로 오판 — exit code 기반 판정",         "Gemini CLI 내부 재시도 메시지를 실패로 오판 → exit code 기반으로 판정."),
    ("149a1a8", "2026-04-11", "enhancement", "minor",    "backend",  "Gemini primary를 gemini-2.5-flash-lite로 교체 + semaphore 완화",     "속도 개선을 위해 primary 모델 교체 및 동시성 semaphore 완화."),
    ("15a2702", "2026-04-11", "enhancement", "minor",    "backend",  "Gemini primary를 gemini-3-flash-preview로 교체",                     "신규 3세대 flash preview 모델로 primary 교체."),
    ("8b01197", "2026-04-11", "bug",         "major",    "backend",  "토론 모드 라운드 1에서 상대 의견 환각 방지",                          "라운드 1에서 존재하지 않는 상대 의견을 환각하던 문제 → 프롬프트 조정."),
    ("0dffe59", "2026-04-12", "bug",         "minor",    "backend",  "토론 모드 에이전트 응답을 완료 즉시 포스트",                          "응답 완료 후 일괄 포스트로 지연 → 완료 즉시 개별 포스트."),
    ("cabf07c", "2026-04-13", "bug",         "major",    "backend",  "토론 모드 실시간 수치 환각 방지 — 웹 검색 강제",                      "실시간 수치를 에이전트가 임의로 환각 → 웹 검색 강제."),
    ("bc7cbfa", "2026-04-13", "bug",         "major",    "backend",  "에이전트 실행 안정화 — 누적 deadline + 백업 PERSPECTIVE 누락 보정",   "개별 타임아웃만 있어 누적 시 무한 실행 가능 → 누적 deadline. 백업 에이전트의 PERSPECTIVE 누락 보정."),
    ("f41b461", "2026-04-13", "bug",         "major",    "backend",  "cancel 모듈 동시성 개선 — lock 보호 + atomic write + 좀비 proc 정리", "cancel 플래그 쓰기가 동시성 버그 → lock + atomic write. 좀비 프로세스도 정리."),
    ("28005ea", "2026-04-13", "bug",         "minor",    "backend",  "코딩 모드 히스토리에서 백업 에이전트 메시지도 인식",                  "백업 에이전트 메시지가 히스토리에 반영되지 않던 문제 수정."),
    ("41acfbc", "2026-04-13", "bug",         "major",    "backend",  "watchdog 리소스 누수·동시성 수정 + 단위 테스트 추가",                 "watchdog에 리소스 누수 및 동시성 이슈 → 수정 및 단위 테스트 추가."),
    ("e6c2195", "2026-04-13", "enhancement", "minor",    "backend",  "부팅 시 CLI 헬스체크 (claude/codex/gemini --version)",                "부팅 시 필수 CLI의 --version을 호출하여 사용 가능 여부 확인."),
]


def get_issues():
    """이미 #1(크래시 루프)은 수기 등록됐으므로 나머지만 반환."""
    return ISSUES


def issue_body(row):
    h, date, typ, sev, area, title, summary = row
    if typ == "bug":
        return f"""## 심각도
{sev.capitalize()}

## 발생 버전
발견일 {date} 이전 (구체 커밋 불특정)

## 사전 조건
없음 (해당 없음)

## 재현 방법
커밋 메시지 기준 배경: {title}

## 발생 원인 및 수정사항
{summary}

## 영향 범위
{area}

## 수정 버전
commit `{h}`
"""
    else:
        return f"""## 심각도
{sev.capitalize()}

## 발생 버전
{date} 이전

## 개선 사항
{title} — {summary}

## 개선 사유
기능 확장 또는 UX 개선을 위해 도입.

## 영향 범위
{area}

## 수정 버전
commit `{h}`
"""


def gen_xlsx(out_path: Path):
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "issues"
    headers = [
        "이슈번호", "발견일", "유형", "제목", "사전 조건",
        "재현 방법 / 개선 사항", "원인 및 수정 / 개선 사유", "영향 범위",
        "발생 버전", "수정 버전", "상태", "비고",
    ]
    ws.append(headers)

    # #1은 이미 등록됨 — 수기 삽입
    ws.append([
        1, "2026-04-21", "bug",
        "부팅 시 CLI 헬스체크에서 UnicodeEncodeError로 크래시 루프",
        "Windows + cp949 기본 콘솔 인코딩",
        "slack_bot.py 실행 → [HEALTH] 블록 print(✅) 호출 시 UnicodeEncodeError",
        "print()가 cp949로 ✅ 인코딩 실패 → watchdog이 5초마다 재시작. sys.stdout/stderr.reconfigure(utf-8)로 수정",
        "backend (slack_bot.py 부팅 전체)",
        "commit e6c2195", "commit 1d8b683", "완료", "Block",
    ])

    for idx, row in enumerate(ISSUES, start=2):
        h, date, typ, sev, area, title, summary = row
        ws.append([
            idx, date, typ, title,
            "" if typ == "enhancement" else "해당 없음",
            title if typ == "enhancement" else f"커밋 {h} 참조",
            summary,
            area,
            f"{date} 이전",
            f"commit {h}",
            "완료",
            sev.capitalize(),
        ])

    # 컬럼 폭 간단 조정
    widths = [8, 12, 12, 50, 25, 40, 60, 15, 20, 20, 8, 10]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[chr(64 + i)].width = w

    wb.save(out_path)
    print(f"[xlsx] wrote {out_path}  rows={len(ISSUES) + 1}")


def gen_release_notes(out_path: Path):
    # 날짜별 그룹핑
    from collections import defaultdict
    groups = defaultdict(list)
    # #1도 포함
    groups["2026-04-21"].append(("1d8b683", "bug", "block", "부팅 크래시 루프 해결 — stdout/stderr UTF-8 재설정"))
    for h, date, typ, sev, area, title, _ in ISSUES:
        groups[date].append((h, typ, sev, title))

    lines = [
        "# Release Notes",
        "",
        "슬랙 멀티 에이전트 봇 릴리즈 히스토리. 날짜별로 묶인 주요 변경사항과 대응 커밋을 기록합니다.",
        "",
        "## 버전 테이블",
        "",
        "| 버전 | 날짜 | 요약 |",
        "|------|------|------|",
    ]
    # 버전 체계: v0.1 (4/2), v0.2 (4/4), v0.3 (4/5), v0.4 (4/10~11), v0.5 (4/12~13), v0.6 (4/21)
    version_map = {
        "2026-04-02": ("v0.1.0", "초기 릴리즈 + watchdog"),
        "2026-04-04": ("v0.2.0", "Bridge 모드, 코딩 모드 개선, 스트리밍, Codex 노이즈 정리"),
        "2026-04-05": ("v0.3.0", "Windows 호환성 + 보안 화이트리스트 + shell=True 제거"),
        "2026-04-10": ("v0.4.0", "Gemini 안정화 + watchdog_guard + 토론 통합 답변"),
        "2026-04-11": ("v0.4.1", "Gemini 모델 교체 + readline 타임아웃 + 토론 환각 방지"),
        "2026-04-12": ("v0.4.2", "토론 응답 즉시 포스트"),
        "2026-04-13": ("v0.5.0", "에이전트 실행 안정화 + CLI 헬스체크 + 단위 테스트"),
        "2026-04-21": ("v0.5.1", "부팅 크래시 루프 핫픽스"),
    }
    for date in sorted(version_map.keys()):
        ver, desc = version_map[date]
        lines.append(f"| {ver} | {date} | {desc} |")

    lines.append("")

    for date in sorted(groups.keys(), reverse=True):
        ver = version_map.get(date, (date, ""))[0]
        lines.append(f"## {ver} ({date})")
        lines.append("")
        bugs = [e for e in groups[date] if e[1] == "bug"]
        feats = [e for e in groups[date] if e[1] in ("enhancement", )]
        if feats:
            lines.append("### 개선")
            for h, _t, sev, title in feats:
                lines.append(f"- **[{sev.capitalize()}]** {title} (`{h}`)")
            lines.append("")
        if bugs:
            lines.append("### 버그 수정")
            for h, _t, sev, title in bugs:
                lines.append(f"- **[{sev.capitalize()}]** {title} (`{h}`)")
            lines.append("")

    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[notes] wrote {out_path}  sections={len(groups)}")


def gh_create_close():
    """gh CLI로 이슈 생성 후 바로 close."""
    total = len(ISSUES)
    for i, row in enumerate(ISSUES, start=1):
        h, date, typ, sev, area, title, _ = row
        labels = f"{typ},{sev},{area}"
        body = issue_body(row)
        # 이슈 생성
        try:
            r = subprocess.run(
                ["gh", "issue", "create",
                 "--repo", REPO,
                 "--label", labels,
                 "--title", f"[{h}] {title}",
                 "--body", body],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=30,
            )
        except Exception as e:
            print(f"[{i}/{total}] {h} EXC {e}")
            continue
        if r.returncode != 0:
            print(f"[{i}/{total}] {h} FAIL create: {r.stderr.strip()[:200]}")
            continue
        url = r.stdout.strip()
        num = url.rsplit("/", 1)[-1]
        # 즉시 close
        c = subprocess.run(
            ["gh", "issue", "close", num,
             "--repo", REPO,
             "--comment", f"소급 등록 — 수정 커밋 `{h}`로 완료."],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=30,
        )
        status = "closed" if c.returncode == 0 else f"close-fail {c.stderr.strip()[:80]}"
        print(f"[{i}/{total}] {h} #{num} {status}")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"
    root = Path(__file__).resolve().parent.parent
    if cmd == "xlsx":
        gen_xlsx(root / "issue_log.xlsx")
    elif cmd == "notes":
        gen_release_notes(root / "RELEASE_NOTES.md")
    elif cmd == "gh":
        gh_create_close()
    elif cmd == "all":
        gen_release_notes(root / "RELEASE_NOTES.md")
        gen_xlsx(root / "issue_log.xlsx")
        gh_create_close()
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
