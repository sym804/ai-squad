"""방금 실행한 라이브 토론 스레드를 fetch해서 라운드 1 응답 확인."""
import sys
import os
import re

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.stdout.reconfigure(encoding="utf-8")

from slack_sdk import WebClient
from config import SLACK_BOT_TOKEN, DEBATE_CHANNEL_ID

THREAD_TS = sys.argv[1] if len(sys.argv) > 1 else "1775917820.233929"

REF_PATTERNS = [
    r"claude(?:가|는|의|와|도|처럼|에\s*따르면)",
    r"codex(?:가|는|의|와|도|처럼|에\s*따르면)",
    r"gemini(?:가|는|의|와|도|처럼|에\s*따르면)",
    r"다른\s*에이전트",
    r"상대(?:방)?의?\s*(?:의견|주장|견해|말)",
    r"앞서\s*(?:언급|말|말씀)",
    r"동료\s*에이전트",
    r"타\s*에이전트",
]
REF_REGEX = re.compile("|".join(REF_PATTERNS), re.IGNORECASE)


def main():
    client = WebClient(token=SLACK_BOT_TOKEN)
    res = client.conversations_replies(
        channel=DEBATE_CHANNEL_ID,
        ts=THREAD_TS,
        limit=200,
    )
    messages = res.get("messages", [])
    print(f"총 {len(messages)}개 메시지\n")

    # 라운드 구분
    current_round = 0
    round1_agent_msgs = []
    round2_agent_msgs = []

    for msg in messages:
        text = msg.get("text", "")
        # 라운드 구분선
        m = re.search(r"라운드\s*(\d+)", text)
        if "--- *라운드" in text and m:
            current_round = int(m.group(1))
            print(f"\n===== 라운드 {current_round} =====")
            continue
        # 생각 중 메시지 스킵
        if "생각 중" in text or "작업 중" in text:
            continue
        # 에이전트 응답 식별 (Slack API는 이모지를 :name: 형태로 반환)
        for emoji_name, name in [
            (":large_orange_circle:", "Claude"),
            (":large_green_circle:", "Codex"),
            (":large_blue_circle:", "Gemini"),
        ]:
            if text.startswith(f"{emoji_name} *[{name}]*"):
                if current_round == 1:
                    round1_agent_msgs.append((name, text))
                elif current_round == 2:
                    round2_agent_msgs.append((name, text))
                print(f"\n--- [{name}] (라운드 {current_round}, {len(text)}자) ---")
                print(text[:2000])
                refs = REF_REGEX.findall(text)
                if refs:
                    print(f"\n  🚨 상대 참조: {refs}")
                else:
                    print(f"\n  ✅ 상대 참조 없음")
                break

    print(f"\n{'='*60}")
    print("라운드 1 요약:")
    for name, text in round1_agent_msgs:
        refs = REF_REGEX.findall(text)
        mark = "🚨" if refs else "✅"
        print(f"  {mark} {name}: 참조 {len(refs)}건 {refs if refs else ''}")

    print(f"\n라운드 2 요약 (참조 >=1 이어야 함):")
    for name, text in round2_agent_msgs:
        refs = REF_REGEX.findall(text)
        mark = "✅" if refs else "⚠️"
        print(f"  {mark} {name}: 참조 {len(refs)}건 {refs if refs else ''}")


if __name__ == "__main__":
    main()
