"""라이브 Slack 토론 스레드에서 에이전트별 라운드 소요 시간 측정.

각 라운드의 시작 마커(`--- *라운드 N* ---`)와 에이전트 응답 ts의 델타를 계산.
"""
import sys
import os
import re

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.stdout.reconfigure(encoding="utf-8")

from slack_sdk import WebClient
from config import SLACK_BOT_TOKEN, DEBATE_CHANNEL_ID


def main():
    thread_ts = sys.argv[1] if len(sys.argv) > 1 else "1775917820.233929"
    client = WebClient(token=SLACK_BOT_TOKEN)
    res = client.conversations_replies(
        channel=DEBATE_CHANNEL_ID, ts=thread_ts, limit=200
    )
    messages = res.get("messages", [])

    rounds = {}  # round_num -> {"start": ts, "agents": [(name, ts)]}
    current_round = 0

    for msg in messages:
        text = msg.get("text", "")
        ts = float(msg.get("ts", 0))
        m = re.match(r"--- \*라운드 (\d+)\* ---", text)
        if m:
            current_round = int(m.group(1))
            rounds[current_round] = {"start": ts, "agents": []}
            continue
        if current_round == 0:
            continue
        for emoji, name in [
            (":large_orange_circle:", "Claude"),
            (":large_green_circle:", "Codex"),
            (":large_blue_circle:", "Gemini"),
        ]:
            if text.startswith(f"{emoji} *[{name}]*"):
                rounds[current_round]["agents"].append((name, ts, len(text)))
                break

    print(f"{'='*70}")
    print(f"스레드 ts={thread_ts}")
    print(f"{'='*70}")
    for rn, data in sorted(rounds.items()):
        start = data["start"]
        print(f"\n===== 라운드 {rn} =====")
        print(f"  라운드 시작 ts: {start}")
        # 가장 마지막 에이전트 응답 ts - 시작 ts = 라운드 전체 소요시간
        if data["agents"]:
            # 병렬 실행이므로 각 에이전트가 완료된 시각(= 메시지 post 시각)
            sorted_agents = sorted(data["agents"], key=lambda x: x[1])
            last_ts = sorted_agents[-1][1]
            print(f"  라운드 전체 소요 (병렬): {last_ts - start:.1f}초")
            print(f"  에이전트별 완료 시각 (순서대로):")
            for name, ts, textlen in sorted_agents:
                delta = ts - start
                print(f"    {name:8s} +{delta:6.1f}초 ({textlen}자)")


if __name__ == "__main__":
    main()
