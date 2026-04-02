"""Watchdog - slack_bot.py 프로세스 감시 및 원격 제어

기능:
  - slack_bot.py 크래시 시 자동 재시작
  - Slack 채널에서 원격 명령 (!bot status/restart/stop/start)
  - 크래시/재시작 알림

사용법:
  python watchdog.py

환경변수 (.env):
  WATCHDOG_CHANNEL_ID  - 명령을 받을 채널 ID (미설정 시 DEBATE_CHANNEL_ID 사용)
"""

import os
import sys
import time
import subprocess
import signal
from datetime import datetime

# Windows cp949 인코딩 에러 방지
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv
from slack_sdk import WebClient

load_dotenv()

SLACK_BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]
WATCHDOG_CHANNEL_ID = os.environ.get(
    "WATCHDOG_CHANNEL_ID",
    os.environ.get("DEBATE_CHANNEL_ID", ""),
)

POLL_INTERVAL = 15  # 초마다 채널 폴링
RESTART_DELAY = 5   # 크래시 후 재시작 대기 (초)
MAX_RAPID_CRASHES = 5  # 연속 빠른 크래시 허용 횟수
RAPID_CRASH_WINDOW = 60  # 이 시간(초) 안에 MAX_RAPID_CRASHES번 죽으면 중단

client = WebClient(token=SLACK_BOT_TOKEN)
bot_process = None
bot_user_id = None
auto_restart = True
crash_times = []


def get_bot_user_id():
    """봇 자신의 user_id를 가져옵니다."""
    global bot_user_id
    try:
        resp = client.auth_test()
        bot_user_id = resp["user_id"]
    except Exception as e:
        print(f"[WATCHDOG] auth_test 실패: {e}")


def notify(text):
    """Slack 채널에 알림을 보냅니다."""
    if not WATCHDOG_CHANNEL_ID:
        return
    try:
        client.chat_postMessage(channel=WATCHDOG_CHANNEL_ID, text=text)
    except Exception as e:
        print(f"[WATCHDOG] 알림 실패: {e}")


def start_bot():
    """slack_bot.py를 subprocess로 시작합니다."""
    global bot_process, auto_restart
    if bot_process and bot_process.poll() is None:
        return "⚠️ 이미 실행 중입니다."

    auto_restart = True
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "slack_bot.py")
    bot_process = subprocess.Popen(
        [sys.executable, script],
        cwd=os.path.dirname(os.path.abspath(__file__)),
    )
    msg = f"✅ Bot 시작됨 (PID: {bot_process.pid})"
    print(f"[WATCHDOG] {msg}")
    return msg


def stop_bot():
    """실행 중인 봇을 종료합니다."""
    global bot_process, auto_restart
    auto_restart = False
    if bot_process and bot_process.poll() is None:
        bot_process.terminate()
        try:
            bot_process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            bot_process.kill()
        msg = "🛑 Bot 종료됨"
        print(f"[WATCHDOG] {msg}")
        return msg
    return "⚠️ 실행 중인 봇이 없습니다."


def restart_bot():
    """봇을 재시작합니다."""
    stop_bot()
    time.sleep(2)
    auto_restart = True
    return start_bot()


def bot_status():
    """봇 상태를 확인합니다."""
    if bot_process and bot_process.poll() is None:
        uptime = ""
        return f"✅ 실행 중 (PID: {bot_process.pid}, auto_restart: {auto_restart})"
    return f"❌ 중지됨 (auto_restart: {auto_restart})"


def check_bot_health():
    """봇 프로세스가 죽었는지 확인하고, 필요 시 재시작합니다."""
    global bot_process, crash_times

    if bot_process is None:
        return

    exit_code = bot_process.poll()
    if exit_code is None:
        return  # 정상 실행 중

    now = time.time()
    crash_times.append(now)
    # 오래된 크래시 기록 정리
    crash_times = [t for t in crash_times if now - t < RAPID_CRASH_WINDOW]

    ts = datetime.now().strftime("%H:%M:%S")

    if len(crash_times) >= MAX_RAPID_CRASHES:
        msg = (
            f"🚨 *Bot 반복 크래시 감지* ({ts})\n"
            f"{RAPID_CRASH_WINDOW}초 안에 {len(crash_times)}번 크래시.\n"
            f"자동 재시작을 중단합니다.\n"
            f"`!bot start` 로 수동 시작하세요."
        )
        notify(msg)
        print(f"[WATCHDOG] 반복 크래시 - 자동 재시작 중단")
        crash_times.clear()
        return

    if auto_restart:
        notify(
            f"⚠️ *Bot 크래시 감지* ({ts}, exit code: {exit_code})\n"
            f"{RESTART_DELAY}초 후 자동 재시작합니다..."
        )
        print(f"[WATCHDOG] 크래시 감지 (exit: {exit_code}), {RESTART_DELAY}초 후 재시작")
        time.sleep(RESTART_DELAY)
        result = start_bot()
        notify(result)


def poll_commands():
    """채널에서 !bot 명령어를 폴링합니다."""
    if not WATCHDOG_CHANNEL_ID:
        return

    try:
        resp = client.conversations_history(
            channel=WATCHDOG_CHANNEL_ID,
            limit=5,
        )
    except Exception:
        return

    for msg in resp.get("messages", []):
        text = msg.get("text", "").strip().lower()
        if not text.startswith("!bot"):
            continue

        # 봇 자신의 메시지 무시
        if msg.get("bot_id") or msg.get("user") == bot_user_id:
            continue

        # 이미 처리된 메시지인지 확인 (리액션으로 마킹)
        reactions = msg.get("reactions", [])
        already_handled = any(
            r.get("name") == "white_check_mark"
            and bot_user_id in r.get("users", [])
            for r in reactions
        )
        if already_handled:
            continue

        # 리액션으로 처리 완료 마킹
        try:
            client.reactions_add(
                channel=WATCHDOG_CHANNEL_ID,
                timestamp=msg["ts"],
                name="white_check_mark",
            )
        except Exception:
            pass

        parts = text.split()
        cmd = parts[1] if len(parts) > 1 else "help"

        if cmd == "status":
            notify(bot_status())
        elif cmd == "restart":
            notify("🔄 재시작 중...")
            result = restart_bot()
            notify(result)
        elif cmd == "stop":
            result = stop_bot()
            notify(result)
        elif cmd == "start":
            result = start_bot()
            notify(result)
        else:
            notify(
                "*사용 가능한 명령어:*\n"
                "• `!bot status` - 봇 상태 확인\n"
                "• `!bot start` - 봇 시작\n"
                "• `!bot stop` - 봇 종료\n"
                "• `!bot restart` - 봇 재시작"
            )


def main():
    print("=" * 50)
    print("Watchdog 시작")
    print(f"  감시 채널: {WATCHDOG_CHANNEL_ID}")
    print(f"  폴링 간격: {POLL_INTERVAL}초")
    print("=" * 50)

    get_bot_user_id()

    # 봇 자동 시작
    result = start_bot()
    notify(f"🐕 *Watchdog 가동*\n{result}\n\n명령어: `!bot status/start/stop/restart`")

    try:
        while True:
            check_bot_health()
            poll_commands()
            time.sleep(POLL_INTERVAL)
    except KeyboardInterrupt:
        print("\n[WATCHDOG] 종료 중...")
        stop_bot()
        notify("🐕 Watchdog 종료됨")


if __name__ == "__main__":
    main()
