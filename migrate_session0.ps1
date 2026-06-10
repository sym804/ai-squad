# 봇을 S4U 비대화형 예약작업으로 전환 (cmd 창 깜빡임 근본 제거)
# ── 반드시 "관리자 권한 PowerShell"에서 실행 ──
#   예: 시작 → PowerShell 우클릭 → 관리자 권한으로 실행 → 아래 한 줄
#       powershell -ExecutionPolicy Bypass -File "C:\Users\ymseo\Documents\slack-multi-agent\migrate_session0.ps1"
#
# 하는 일: (1) 예약작업을 S4U 비대화형으로 재등록 → (2) 대화형 watchdog/bot 종료
#          (respawn 레이스 방지: watchdog 먼저) → (3) 예약작업 즉시 실행으로
#          비대화형 재가동 → (4) 검증.

$ErrorActionPreference = "Continue"
$dir = $PSScriptRoot
if (-not $dir) { $dir = "C:\Users\ymseo\Documents\slack-multi-agent" }
$python = "C:\Python311\python.exe"
$task = "SlackBotWatchdogGuard"

# 관리자 권한 확인
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
            ).IsInRole([Security.Principal.WindowsBuiltinRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "[!] 관리자 권한이 아닙니다. PowerShell을 '관리자 권한으로 실행'한 뒤 다시 시도하세요." -ForegroundColor Red
    exit 1
}

Write-Host "[1/4] 예약작업을 S4U 비대화형으로 재등록..." -ForegroundColor Cyan
& $python "$dir\watchdog_guard.py" --install

Write-Host "[2/4] 대화형 watchdog/bot 종료 (respawn 방지 위해 watchdog 먼저)..." -ForegroundColor Cyan
# watchdog + cmd 래퍼 먼저 종료 → 봇 자동 재시작 차단
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match "watchdog\.py" } |
    ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue } catch {} }
Start-Sleep -Seconds 1
# 남은 bot 종료
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match "slack_bot\.py" } |
    ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue } catch {} }
Start-Sleep -Seconds 2

Write-Host "[3/4] S4U 예약작업 즉시 실행 (watchdog→bot 비대화형 재가동)..." -ForegroundColor Cyan
Start-ScheduledTask -TaskName $task
Start-Sleep -Seconds 14

Write-Host "[4/4] 검증..." -ForegroundColor Cyan
try {
    $t = Get-ScheduledTask -TaskName $task
    Write-Host ("  예약작업 LogonType = " + $t.Principal.LogonType + " (S4U 여야 정상)")
} catch { Write-Host "  예약작업 조회 실패: $($_.Exception.Message)" }
$bot = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match "slack_bot\.py" } | Select-Object -First 1
if ($bot) {
    Write-Host ("  bot 재가동 OK: PID=" + $bot.ProcessId + ", SessionId=" + $bot.SessionId)
} else {
    Write-Host "  bot 미가동 - bot_output.log 확인 필요" -ForegroundColor Yellow
}
Write-Host ""
Write-Host "완료. 슬랙 #ai-리서치 또는 #ai-협업에 질문을 보내 깜빡임이 사라졌는지 확인하세요." -ForegroundColor Green
Write-Host "(되돌리려면: 관리자 PowerShell에서 'python `"$dir\watchdog_guard.py`" --uninstall' 후 기존 방식으로 재기동)"
