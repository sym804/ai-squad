# AI Squad

Slack에서 Claude, Codex, Gemini 3개 AI가 토론하거나 역할 분담 코딩을 수행하는 봇.

## 빠른 시작

```bash
git clone https://github.com/sym804/ai-squad.git
cd ai-squad
pip install -r requirements.txt
cp .env.example .env
```

`.env` 파일을 열어 토큰과 채널 ID를 입력한 후:

```bash
python slack_bot.py
```

## 사전 요구사항

- Python 3.11+
- Claude Code CLI (`claude`) 로그인 완료
- Codex CLI (`codex`) 로그인 완료
- Gemini CLI (`gemini`) 로그인 완료

## 채널 구성

| 채널 | 모드 | 설명 |
|------|------|------|
| `#ai-협업` | 토론 | 3개 AI 자유 토론, 합의 시 종료 |
| `#ai-코딩` | 코딩 | Claude 기획+개발, Codex 리뷰+테스트 리더, 전원 테스트 |

## 기능

- 자유 토론 + 자동 합의 감지 (전원 합의 / 다수 합의)
- 코딩 파이프라인 (기획 → 개발 → 리뷰 → 테스트)
- 스레드에서 추가 질문 → 맥락 기반 추가 토론
- 타임아웃 시 백업 에이전트 자동 투입
- 당일 이전 합의 결론 자동 참조
- 에러 발생 시 Slack 알림

## .env 설정

```
SLACK_BOT_TOKEN=xoxb-...
SLACK_APP_TOKEN=xapp-...
DEBATE_CHANNEL_ID=채널ID
CODING_CHANNEL_ID=채널ID
MAX_DEBATE_ROUNDS=10
CONSENSUS_EARLY_ROUNDS=5
```

Slack App 설정 방법은 [SETUP.md](SETUP.md) 참고.
