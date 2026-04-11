"""각 에이전트 wall-clock 응답 지연 벤치마크.

실제 debate 라운드 1에 전달되는 것과 동일한 프롬프트로 ask()를 N회 호출하고
median/min/max를 출력.
"""
import asyncio
import sys
import os
import time
import statistics

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.stdout.reconfigure(encoding="utf-8")

from agents import ClaudeAgent, CodexAgent, GeminiAgent
from modes.debate import DebateMode

TRIALS = 3
TOPIC = "파이썬과 Go 중 백엔드 신규 프로젝트에 뭐가 더 나아?"

_debate = DebateMode(slack_client=None)
ROUND1_PROMPT = _debate._build_prompt(TOPIC, history=[], round_num=1)


async def time_ask(agent_cls, label, trial):
    agent = agent_cls()
    start = time.monotonic()
    try:
        result = await agent.ask(ROUND1_PROMPT, timeout=180)
    except Exception as e:
        result = f"[ERROR] {e}"
    elapsed = time.monotonic() - start
    print(f"  [{label}] trial {trial+1}: {elapsed:5.1f}초 ({len(result)}자)")
    return elapsed


async def bench(agent_cls, label):
    print(f"\n>>> {label} 벤치마크 ({TRIALS}회 순차)")
    timings = []
    for i in range(TRIALS):
        t = await time_ask(agent_cls, label, i)
        timings.append(t)
    return timings


async def bench_parallel(trial):
    """Debate 라운드와 동일하게 3개 동시 실행."""
    claude = ClaudeAgent()
    codex = CodexAgent()
    gemini = GeminiAgent()

    async def timed(agent, label):
        start = time.monotonic()
        try:
            result = await agent.ask(ROUND1_PROMPT, timeout=180)
        except Exception as e:
            result = f"[ERROR] {e}"
        elapsed = time.monotonic() - start
        return (label, elapsed, len(result))

    print(f"\n>>> 병렬 trial {trial+1} (3개 동시 실행)")
    results = await asyncio.gather(
        timed(claude, "Claude"),
        timed(codex, "Codex"),
        timed(gemini, "Gemini"),
    )
    for label, t, length in results:
        print(f"  [{label}] {t:5.1f}초 ({length}자)")
    return {label: t for label, t, _ in results}


async def main():
    print("=" * 70)
    print(f"라운드 1 프롬프트 길이: {len(ROUND1_PROMPT)}자")
    print(f"주제: {TOPIC}")
    print("=" * 70)

    print("\n[A] 순차 실행 (baseline, 1 에이전트씩)")
    claude_times = await bench(ClaudeAgent, "Claude")
    codex_times = await bench(CodexAgent, "Codex")
    gemini_times = await bench(GeminiAgent, "Gemini")

    print("\n" + "=" * 70)
    print("[B] 병렬 실행 (debate와 동일한 asyncio.gather 3동시)")
    print("=" * 70)
    parallel_results = []
    for i in range(TRIALS):
        parallel_results.append(await bench_parallel(i))

    print("\n" + "=" * 70)
    print("요약")
    print("=" * 70)
    print("\n[A] 순차 (wall-clock 초):")
    for label, times in [
        ("Claude", claude_times),
        ("Codex", codex_times),
        ("Gemini", gemini_times),
    ]:
        valid = [t for t in times if t < 180]
        if not valid:
            print(f"  {label:8s}: 전부 타임아웃/에러")
            continue
        print(f"  {label:8s}: "
              f"중앙 {statistics.median(valid):5.1f}s "
              f"평균 {statistics.mean(valid):5.1f}s "
              f"최소 {min(valid):5.1f}s "
              f"최대 {max(valid):5.1f}s "
              f"(n={len(valid)})")

    print("\n[B] 병렬 (wall-clock 초):")
    for label in ["Claude", "Codex", "Gemini"]:
        values = [r[label] for r in parallel_results if r[label] < 180]
        if not values:
            print(f"  {label:8s}: 전부 타임아웃/에러")
            continue
        print(f"  {label:8s}: "
              f"중앙 {statistics.median(values):5.1f}s "
              f"평균 {statistics.mean(values):5.1f}s "
              f"최소 {min(values):5.1f}s "
              f"최대 {max(values):5.1f}s "
              f"(n={len(values)})")


if __name__ == "__main__":
    asyncio.run(main())
