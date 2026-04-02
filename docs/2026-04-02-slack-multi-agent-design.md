# Slack Multi-Agent Debate & Coding System

## Overview
Slack 채널에서 Claude Code, Codex CLI, Gemini CLI 3개 AI 에이전트가 자유 토론하거나 역할 분담 코딩을 수행하는 시스템. API 비용 없이 로컬 CLI 기반으로 동작.

## 채널 구성

### #ai-debate (토론 채널)
- 메시지 작성 시 3개 AI가 자유 토론 시작
- 역할 없음, 자유 발언
- 토론은 스레드에서 진행
- 합의 도달 시 결론을 채널에 포스팅

### #ai-coding (코딩 채널)
- 메시지 작성 시 역할 분담 코딩 시작
- Claude: 기획 + 풀스택 개발 (설계/코드 작성) + 테스트 참여
- Codex: 코드 리뷰 + 테스트 리더 (테스트 설계/작성/판정)
- Gemini: 테스트 참여
- 결과를 채널에 요약

## Architecture

```
slack-multi-agent/
├── slack_bot.py        # Slack Socket Mode 이벤트 수신, 채널별 라우팅
├── agents/
│   ├── base.py         # Agent 공통 인터페이스 (subprocess CLI 호출)
│   ├── claude.py       # Claude Code CLI 래퍼
│   ├── codex.py        # Codex CLI 래퍼
│   └── gemini.py       # Gemini CLI 래퍼
├── modes/
│   ├── debate.py       # 토론 모드 (자유 토론, 합의 감지, 라운드 관리)
│   └── coding.py       # 코딩 모드 (개발→리뷰→테스트 파이프라인)
├── config.py           # 채널 ID, 설정값
├── .env                # SLACK_BOT_TOKEN, SLACK_APP_TOKEN
├── requirements.txt    # slack-bolt, python-dotenv
└── docs/
    └── 2026-04-02-slack-multi-agent-design.md
```

## Debate Mode Flow

1. 사용자가 #ai-debate에 메시지 작성
2. 봇이 스레드 생성, "토론을 시작합니다" 안내
3. 3개 AI에게 동시에(비동기) 질문 전달
4. 각 AI가 스레드에 답변 (이름 표시: [Claude], [Codex], [Gemini])
5. 각 AI가 이전 답변들을 컨텍스트로 받아 반응
6. 합의 감지:
   - 3개 합의 → 즉시 종료
   - 5라운드 이상 + 2개 합의 → 종료
   - 최대 10라운드 → 강제 종료 + 다수결
7. 결론 요약을 채널(스레드 밖)에 포스팅

### 합의 감지
각 AI 응답 시 시스템 프롬프트에 합의 판정 요청:
```
응답 마지막에 아래 JSON을 반드시 포함하세요:
<!--CONSENSUS:{"agree": true/false, "summary": "한줄 결론"}-->
```
파싱하여 합의 여부 판단. JSON이 없으면 agree=false로 처리.

## Coding Mode Flow

1. 사용자가 #ai-coding에 메시지 작성
2. 봇이 스레드 생성
3. Phase 1: Claude가 기획 + 설계 + 코드 작성 → 스레드에 결과 포스팅
4. Phase 2: Codex가 코드 리뷰 → 스레드에 포스팅
5. Phase 3: 테스트 (Codex가 리더로 테스트 설계/작성, Claude + Gemini도 테스트 참여) → 스레드에 결과 포스팅
6. 이슈 발견 시 → Claude에게 수정 요청 (최대 3회 반복)
7. 완료 시 최종 결과를 채널에 요약

## Agent Subprocess Interface

각 에이전트는 CLI를 subprocess로 호출:
```python
# Claude
subprocess.run(["claude", "-p", prompt, "--no-input"], capture_output=True, text=True)

# Codex
subprocess.run(["codex", "-p", prompt], capture_output=True, text=True)

# Gemini
subprocess.run(["gemini", "-p", prompt], capture_output=True, text=True)
```

타임아웃: 120초. 초과 시 해당 에이전트 응답 스킵.

## Slack 설정 요구사항

1. Slack App 생성 (api.slack.com)
2. Socket Mode 활성화 (서버/ngrok 불필요)
3. Bot Token Scopes: `chat:write`, `channels:history`, `channels:read`, `app_mentions:read`
4. Event Subscriptions: `message.channels`
5. 봇을 #ai-debate, #ai-coding 채널에 초대

## 환경 변수 (.env)
```
SLACK_BOT_TOKEN=xoxb-...
SLACK_APP_TOKEN=xapp-...
DEBATE_CHANNEL_ID=C0123456789
CODING_CHANNEL_ID=C9876543210
MAX_DEBATE_ROUNDS=10
CONSENSUS_THRESHOLD=5
```

## 의존성
```
slack-bolt>=1.18.0
python-dotenv>=1.0.0
```

## 제약사항
- PC가 켜져 있어야 동작 (Socket Mode)
- CLI 응답 속도에 따라 토론 속도 결정 (각 응답 ~30-120초)
- 각 CLI가 로그인된 상태여야 함
