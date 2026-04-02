# Slack Multi-Agent Debate & Coding System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Slack 채널에서 Claude/Codex/Gemini 3개 AI가 자유 토론하거나 역할 분담 코딩을 수행하는 봇

**Architecture:** Python Slack Bolt (Socket Mode)로 이벤트 수신, subprocess로 각 CLI 호출, 채널별 모드 라우팅 (토론/코딩)

**Tech Stack:** Python 3.11+, slack-bolt, python-dotenv, asyncio, subprocess

---

## File Structure

```
slack-multi-agent/
├── slack_bot.py          # 진입점, Slack 이벤트 수신 및 채널별 라우팅
├── config.py             # 설정값 로드 (.env)
├── agents/
│   ├── base.py           # AgentBase 클래스 (subprocess CLI 호출 공통)
│   ├── claude.py         # Claude CLI 래퍼
│   ├── codex.py          # Codex CLI 래퍼
│   └── gemini.py         # Gemini CLI 래퍼
├── modes/
│   ├── debate.py         # 토론 모드 로직
│   └── coding.py         # 코딩 모드 로직
├── .env                  # 시크릿 (SLACK_BOT_TOKEN, SLACK_APP_TOKEN, 채널 ID)
├── requirements.txt      # 의존성
└── docs/
```

---

### Task 1: 프로젝트 초기화 + 의존성

**Files:**
- Create: `requirements.txt`
- Create: `.env`
- Create: `config.py`

- [ ] **Step 1: requirements.txt 작성**

```
slack-bolt>=1.18.0
python-dotenv>=1.0.0
```

- [ ] **Step 2: .env 템플릿 작성**

```
SLACK_BOT_TOKEN=xoxb-your-bot-token
SLACK_APP_TOKEN=xapp-your-app-token
DEBATE_CHANNEL_ID=C0123456789
CODING_CHANNEL_ID=C9876543210
MAX_DEBATE_ROUNDS=10
CONSENSUS_EARLY_ROUNDS=5
```

- [ ] **Step 3: config.py 작성**

```python
import os
from dotenv import load_dotenv

load_dotenv()

SLACK_BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]
SLACK_APP_TOKEN = os.environ["SLACK_APP_TOKEN"]
DEBATE_CHANNEL_ID = os.environ["DEBATE_CHANNEL_ID"]
CODING_CHANNEL_ID = os.environ["CODING_CHANNEL_ID"]
MAX_DEBATE_ROUNDS = int(os.environ.get("MAX_DEBATE_ROUNDS", "10"))
CONSENSUS_EARLY_ROUNDS = int(os.environ.get("CONSENSUS_EARLY_ROUNDS", "5"))
CLI_TIMEOUT = 120
```

- [ ] **Step 4: 의존성 설치**

Run: `pip install -r requirements.txt`

- [ ] **Step 5: 커밋**

```bash
git init
git add requirements.txt .env config.py
git commit -m "init: project setup with config and dependencies"
```

---

### Task 2: Agent 베이스 클래스

**Files:**
- Create: `agents/__init__.py`
- Create: `agents/base.py`

- [ ] **Step 1: agents/__init__.py 작성**

```python
from agents.claude import ClaudeAgent
from agents.codex import CodexAgent
from agents.gemini import GeminiAgent
```

- [ ] **Step 2: agents/base.py 작성**

```python
import subprocess
import asyncio
from config import CLI_TIMEOUT


class AgentBase:
    name: str = "Agent"
    emoji: str = "🤖"
    cli_command: list[str] = []

    async def ask(self, prompt: str) -> str:
        """CLI를 subprocess로 호출하여 응답을 받는다."""
        try:
            result = await asyncio.wait_for(
                self._run_cli(prompt),
                timeout=CLI_TIMEOUT
            )
            return result
        except asyncio.TimeoutError:
            return f"[{self.name}] 응답 시간 초과 ({CLI_TIMEOUT}초)"
        except Exception as e:
            return f"[{self.name}] 오류: {str(e)}"

    async def _run_cli(self, prompt: str) -> str:
        proc = await asyncio.create_subprocess_exec(
            *self.cli_command, prompt,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        output = stdout.decode("utf-8", errors="replace").strip()
        if not output and stderr:
            output = stderr.decode("utf-8", errors="replace").strip()
        return output

    def format_message(self, response: str) -> str:
        return f"{self.emoji} *[{self.name}]*\n{response}"
```

- [ ] **Step 3: 커밋**

```bash
git add agents/
git commit -m "feat: add AgentBase class with subprocess CLI execution"
```

---

### Task 3: 개별 Agent 구현

**Files:**
- Create: `agents/claude.py`
- Create: `agents/codex.py`
- Create: `agents/gemini.py`

- [ ] **Step 1: agents/claude.py 작성**

```python
from agents.base import AgentBase


class ClaudeAgent(AgentBase):
    name = "Claude"
    emoji = "🟠"
    cli_command = ["claude", "-p"]
```

- [ ] **Step 2: agents/codex.py 작성**

```python
from agents.base import AgentBase


class CodexAgent(AgentBase):
    name = "Codex"
    emoji = "🟢"
    cli_command = ["codex", "exec"]
```

- [ ] **Step 3: agents/gemini.py 작성**

```python
from agents.base import AgentBase


class GeminiAgent(AgentBase):
    name = "Gemini"
    emoji = "🔵"
    cli_command = ["gemini", "-p"]
```

- [ ] **Step 4: 커밋**

```bash
git add agents/
git commit -m "feat: add Claude, Codex, Gemini agent wrappers"
```

---

### Task 4: 토론 모드

**Files:**
- Create: `modes/__init__.py`
- Create: `modes/debate.py`

- [ ] **Step 1: modes/__init__.py 작성**

```python
from modes.debate import DebateMode
from modes.coding import CodingMode
```

- [ ] **Step 2: modes/debate.py 작성**

```python
import asyncio
import json
import re
from agents import ClaudeAgent, CodexAgent, GeminiAgent
from config import MAX_DEBATE_ROUNDS, CONSENSUS_EARLY_ROUNDS


class DebateMode:
    def __init__(self, slack_client):
        self.client = slack_client
        self.agents = [ClaudeAgent(), CodexAgent(), GeminiAgent()]

    async def start(self, channel: str, thread_ts: str, topic: str):
        self.client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text="🏛️ *토론을 시작합니다*\n"
                 f"주제: {topic}\n"
                 f"참여: {', '.join(a.name for a in self.agents)}"
        )

        conversation_history = [f"토론 주제: {topic}"]
        round_num = 0

        while round_num < MAX_DEBATE_ROUNDS:
            round_num += 1
            round_responses = []

            self.client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                text=f"━━━ *Round {round_num}* ━━━"
            )

            for agent in self.agents:
                prompt = self._build_prompt(topic, conversation_history, agent.name, round_num)
                response = await agent.ask(prompt)

                self.client.chat_postMessage(
                    channel=channel,
                    thread_ts=thread_ts,
                    text=agent.format_message(response)
                )

                conversation_history.append(f"[{agent.name}] (Round {round_num}): {response}")
                round_responses.append({
                    "agent": agent.name,
                    "response": response,
                    "consensus": self._parse_consensus(response)
                })

            # 합의 체크
            agrees = [r for r in round_responses if r["consensus"]["agree"]]

            if len(agrees) >= 3:
                await self._post_conclusion(channel, thread_ts, agrees, "만장일치 합의")
                return

            if round_num >= CONSENSUS_EARLY_ROUNDS and len(agrees) >= 2:
                await self._post_conclusion(channel, thread_ts, agrees, f"다수 합의 (Round {round_num})")
                return

        # 최대 라운드 도달
        agrees = [r for r in round_responses if r["consensus"]["agree"]]
        if len(agrees) >= 2:
            await self._post_conclusion(channel, thread_ts, agrees, "최대 라운드 도달 (다수결)")
        else:
            self.client.chat_postMessage(
                channel=channel,
                text=f"🏛️ *토론 결과: 합의 실패*\n"
                     f"주제: {topic}\n"
                     f"{MAX_DEBATE_ROUNDS}라운드 동안 합의에 도달하지 못했습니다."
            )

    def _build_prompt(self, topic: str, history: list, agent_name: str, round_num: int) -> str:
        history_text = "\n".join(history[-10:])  # 최근 10개만
        return (
            f"당신은 '{agent_name}'입니다. 다음 주제에 대해 토론 중입니다.\n\n"
            f"주제: {topic}\n\n"
            f"지금까지의 대화:\n{history_text}\n\n"
            f"현재 Round {round_num}입니다.\n"
            f"다른 참가자의 의견에 동의하거나 반박하며 자유롭게 토론하세요.\n"
            f"간결하게 답변하세요 (500자 이내).\n\n"
            f"응답 마지막에 반드시 아래 형식을 포함하세요:\n"
            f'<!--CONSENSUS:{{"agree": true/false, "summary": "한줄 결론"}}-->'
        )

    def _parse_consensus(self, response: str) -> dict:
        match = re.search(r'<!--CONSENSUS:(.*?)-->', response)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass
        return {"agree": False, "summary": ""}

    async def _post_conclusion(self, channel: str, thread_ts: str, agrees: list, reason: str):
        summaries = "\n".join(
            f"• [{a['agent']}] {a['consensus']['summary']}" for a in agrees
        )
        # 스레드에 결론
        self.client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text=f"✅ *토론 종료: {reason}*\n\n{summaries}"
        )
        # 채널에 결론 (스레드 밖)
        self.client.chat_postMessage(
            channel=channel,
            text=f"🏛️ *토론 결론 ({reason})*\n\n{summaries}"
        )
```

- [ ] **Step 3: 커밋**

```bash
git add modes/
git commit -m "feat: add debate mode with consensus detection"
```

---

### Task 5: 코딩 모드

**Files:**
- Create: `modes/coding.py`

- [ ] **Step 1: modes/coding.py 작성**

```python
import asyncio
from agents import ClaudeAgent, CodexAgent, GeminiAgent


class CodingMode:
    def __init__(self, slack_client):
        self.client = slack_client
        self.claude = ClaudeAgent()
        self.codex = CodexAgent()
        self.gemini = GeminiAgent()
        self.max_fix_rounds = 3

    async def start(self, channel: str, thread_ts: str, request: str):
        self.client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text="⚙️ *코딩 모드 시작*\n"
                 f"요청: {request}\n"
                 "🟠 Claude: 기획 + 개발 | 🟢 Codex: 리뷰 + 테스트 리더 | 🔵 Gemini: 테스트"
        )

        # Phase 1: Claude 기획 + 개발
        self.client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text="━━━ *Phase 1: 기획 + 개발 (Claude)* ━━━"
        )

        claude_prompt = (
            f"다음 요청에 대해 기획하고 코드를 작성하세요.\n\n"
            f"요청: {request}\n\n"
            f"1. 먼저 간단한 기획/설계를 제시하세요\n"
            f"2. 그 다음 완전한 코드를 작성하세요\n"
            f"파일 경로와 함께 코드를 제공하세요."
        )
        claude_result = await self.claude.ask(claude_prompt)
        self.client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text=self.claude.format_message(claude_result)
        )

        # Phase 2: Codex 코드 리뷰
        self.client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text="━━━ *Phase 2: 코드 리뷰 (Codex)* ━━━"
        )

        review_prompt = (
            f"다음 코드를 리뷰하세요. 버그, 보안 이슈, 개선점을 찾아주세요.\n\n"
            f"원래 요청: {request}\n\n"
            f"Claude가 작성한 코드:\n{claude_result}"
        )
        review_result = await self.codex.ask(review_prompt)
        self.client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text=self.codex.format_message(review_result)
        )

        # Phase 3: 테스트 (Codex 리더 + Claude, Gemini 참여)
        self.client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text="━━━ *Phase 3: 테스트 (리더: Codex)* ━━━"
        )

        test_base_prompt = (
            f"다음 코드에 대한 테스트를 작성하세요.\n\n"
            f"원래 요청: {request}\n\n"
            f"코드:\n{claude_result}\n\n"
            f"리뷰 결과:\n{review_result}"
        )

        # Codex: 테스트 리더 (테스트 설계 + 핵심 테스트)
        codex_test_prompt = (
            f"당신은 테스트 리더입니다.\n"
            f"테스트 전략을 설계하고 핵심 테스트 케이스를 작성하세요.\n\n"
            f"{test_base_prompt}"
        )

        # Claude, Gemini: 추가 테스트
        member_test_prompt = (
            f"당신은 테스트 참여자입니다.\n"
            f"엣지 케이스와 추가 테스트를 작성하세요.\n\n"
            f"{test_base_prompt}"
        )

        codex_test, claude_test, gemini_test = await asyncio.gather(
            self.codex.ask(codex_test_prompt),
            self.claude.ask(member_test_prompt),
            self.gemini.ask(member_test_prompt),
        )

        self.client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text=self.codex.format_message(f"*[테스트 리더]*\n{codex_test}")
        )
        self.client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text=self.claude.format_message(f"*[테스트 참여]*\n{claude_test}")
        )
        self.client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text=self.gemini.format_message(f"*[테스트 참여]*\n{gemini_test}")
        )

        # 최종 결론 채널에 포스팅
        self.client.chat_postMessage(
            channel=channel,
            text=(
                f"⚙️ *코딩 완료*\n"
                f"요청: {request}\n\n"
                f"• 🟠 Claude: 기획 + 개발 완료\n"
                f"• 🟢 Codex: 코드 리뷰 + 테스트 리더 완료\n"
                f"• 🟠🟢🔵: 테스트 완료\n\n"
                f"상세 내용은 스레드를 확인하세요."
            )
        )
```

- [ ] **Step 2: 커밋**

```bash
git add modes/coding.py
git commit -m "feat: add coding mode with role-based pipeline"
```

---

### Task 6: Slack 봇 메인

**Files:**
- Create: `slack_bot.py`

- [ ] **Step 1: slack_bot.py 작성**

```python
import asyncio
import threading
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from config import SLACK_BOT_TOKEN, SLACK_APP_TOKEN, DEBATE_CHANNEL_ID, CODING_CHANNEL_ID
from modes.debate import DebateMode
from modes.coding import CodingMode

app = App(token=SLACK_BOT_TOKEN)

# 봇 자신의 메시지 무시용
bot_user_id = None


@app.event("message")
def handle_message(event, say, client):
    global bot_user_id
    if bot_user_id is None:
        bot_user_id = client.auth_test()["user_id"]

    # 봇 자신의 메시지 무시
    if event.get("bot_id") or event.get("user") == bot_user_id:
        return

    # 스레드 답글 무시 (원본 메시지만 처리)
    if event.get("thread_ts"):
        return

    # 서브타입 무시 (메시지 수정, 삭제 등)
    if event.get("subtype"):
        return

    channel = event["channel"]
    text = event.get("text", "")
    ts = event["ts"]

    if not text.strip():
        return

    if channel == DEBATE_CHANNEL_ID:
        debate = DebateMode(client)
        thread = threading.Thread(
            target=_run_async,
            args=(debate.start(channel, ts, text),)
        )
        thread.start()

    elif channel == CODING_CHANNEL_ID:
        coding = CodingMode(client)
        thread = threading.Thread(
            target=_run_async,
            args=(coding.start(channel, ts, text),)
        )
        thread.start()


def _run_async(coro):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(coro)
    finally:
        loop.close()


if __name__ == "__main__":
    print("🚀 Slack Multi-Agent Bot 시작")
    print(f"  토론 채널: {DEBATE_CHANNEL_ID}")
    print(f"  코딩 채널: {CODING_CHANNEL_ID}")
    handler = SocketModeHandler(app, SLACK_APP_TOKEN)
    handler.start()
```

- [ ] **Step 2: 커밋**

```bash
git add slack_bot.py
git commit -m "feat: add main Slack bot with channel routing"
```

---

### Task 7: Slack App 설정 가이드

**Files:**
- Create: `SETUP.md`

- [ ] **Step 1: SETUP.md 작성**

```markdown
# Slack Multi-Agent Bot 설정 가이드

## 1. Slack App 생성

1. https://api.slack.com/apps 접속
2. "Create New App" → "From scratch"
3. App 이름: `AI Multi-Agent` (자유)
4. Workspace 선택

## 2. Socket Mode 활성화

1. 좌측 "Socket Mode" 클릭
2. "Enable Socket Mode" 활성화
3. App-Level Token 생성 (이름: `socket`, scope: `connections:write`)
4. 생성된 `xapp-...` 토큰을 `.env`의 `SLACK_APP_TOKEN`에 입력

## 3. Bot Token Scopes 설정

좌측 "OAuth & Permissions" → "Scopes" → Bot Token Scopes:
- `chat:write`
- `channels:history`
- `channels:read`

## 4. Event Subscriptions

좌측 "Event Subscriptions" → Enable Events → Subscribe to bot events:
- `message.channels`

## 5. App 설치

좌측 "Install App" → "Install to Workspace"
생성된 `xoxb-...` 토큰을 `.env`의 `SLACK_BOT_TOKEN`에 입력

## 6. 채널 설정

1. Slack에서 `#ai-debate`, `#ai-coding` 채널 생성
2. 각 채널에 봇 초대 (`/invite @AI Multi-Agent`)
3. 각 채널 ID를 `.env`에 입력
   - 채널 이름 우클릭 → "Copy link" → URL 끝의 ID가 채널 ID

## 7. 실행

```bash
pip install -r requirements.txt
python slack_bot.py
```
```

- [ ] **Step 2: 커밋**

```bash
git add SETUP.md
git commit -m "docs: add Slack app setup guide"
```

---

### Task 8: 테스트 실행 + 최종 확인

- [ ] **Step 1: CLI 동작 확인**

```bash
claude -p "hello" 
codex exec "hello"
gemini -p "hello"
```
각 CLI가 응답하는지 확인.

- [ ] **Step 2: .env에 실제 토큰 입력**

Slack App에서 발급받은 토큰과 채널 ID를 `.env`에 입력.

- [ ] **Step 3: 봇 실행**

```bash
cd C:\Users\ymseo\Documents\slack-multi-agent
python slack_bot.py
```

- [ ] **Step 4: 토론 테스트**

`#ai-debate` 채널에 메시지 입력하여 3개 AI가 토론하는지 확인.

- [ ] **Step 5: 코딩 테스트**

`#ai-coding` 채널에 메시지 입력하여 Claude→Codex→테스트 파이프라인 동작 확인.

- [ ] **Step 6: 최종 커밋**

```bash
git add -A
git commit -m "chore: finalize slack multi-agent bot v1.0.0.0"
```
