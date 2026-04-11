"""최근 토론 스레드 N개에서 에이전트별 라운드 1 소요 시간을 집계.

최근 threads를 돌며 에이전트별 평균/최소/최대/개별 값을 출력한다.
수정 전 커밋(26053b9 이전)과 비교하려면 TS cutoff 로 나눠서 본다.
"""
import sys
import os
import re
import statistics

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.stdout.reconfigure(encoding="utf-8")

from slack_sdk import WebClient
from config import SLACK_BOT_TOKEN, DEBATE_CHANNEL_ID


def fetch_round_timings(client, thread_ts):
    """해당 스레드의 라운드별 {agent: duration} 반환."""
    try:
        res = client.conversations_replies(
            channel=DEBATE_CHANNEL_ID, ts=thread_ts, limit=200
        )
    except Exception as e:
        return None
    messages = res.get("messages", [])
    rounds = {}
    current_round = 0
    for msg in messages:
        text = msg.get("text", "")
        ts = float(msg.get("ts", 0))
        m = re.match(r"--- \*라운드 (\d+)\* ---", text)
        if m:
            current_round = int(m.group(1))
            rounds[current_round] = {"start": ts, "agents": {}}
            continue
        if current_round == 0:
            continue
        for emoji, name in [
            (":large_orange_circle:", "Claude"),
            (":large_green_circle:", "Codex"),
            (":large_blue_circle:", "Gemini"),
        ]:
            if text.startswith(f"{emoji} *[{name}]*"):
                if name not in rounds[current_round]["agents"]:
                    start = rounds[current_round]["start"]
                    rounds[current_round]["agents"][name] = ts - start
                break
    return rounds


def main():
    client = WebClient(token=SLACK_BOT_TOKEN)
    # 토론 채널의 최근 top-level 메시지 조회
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 40
    res = client.conversations_history(channel=DEBATE_CHANNEL_ID, limit=limit)
    toplevel_messages = [
        m for m in res.get("messages", [])
        if not m.get("subtype") and m.get("thread_ts", m.get("ts")) == m.get("ts")
    ]
    print(f"최근 top-level 메시지 {len(toplevel_messages)}개 분석 중...\n")

    # 커밋 ts (2026-04-11 기준 — 대략적 추정)
    # 실제 커밋 ts는 26053b9인데, Slack ts 기준으로 알 수 없으므로 thread_ts로 비교
    # 가장 최근에 push한 라이브 테스트는 1775917820.233929
    FIX_BOUNDARY = 1775917000.0  # 이 값보다 크면 수정 후

    before = {"Claude": [], "Codex": [], "Gemini": []}
    after = {"Claude": [], "Codex": [], "Gemini": []}
    thread_count_before = 0
    thread_count_after = 0

    for msg in toplevel_messages:
        ts = msg.get("ts")
        if not ts:
            continue
        rounds = fetch_round_timings(client, ts)
        if not rounds or 1 not in rounds:
            continue
        agents_r1 = rounds[1]["agents"]
        if not agents_r1:
            continue
        is_after = float(ts) >= FIX_BOUNDARY
        bucket = after if is_after else before
        if is_after:
            thread_count_after += 1
        else:
            thread_count_before += 1
        for name, dur in agents_r1.items():
            bucket[name].append(dur)

    def summarize(label, bucket, count):
        print(f"\n=== {label} (스레드 {count}개) ===")
        for name in ["Claude", "Codex", "Gemini"]:
            durs = bucket[name]
            if not durs:
                print(f"  {name:8s}: 데이터 없음")
                continue
            avg = statistics.mean(durs)
            med = statistics.median(durs)
            mn = min(durs)
            mx = max(durs)
            print(f"  {name:8s}: 평균 {avg:5.1f}초  중앙 {med:5.1f}초  "
                  f"최소 {mn:5.1f}  최대 {mx:5.1f}  (n={len(durs)})")

    summarize("수정 전 (라운드 1)", before, thread_count_before)
    summarize("수정 후 (라운드 1)", after, thread_count_after)


if __name__ == "__main__":
    main()
