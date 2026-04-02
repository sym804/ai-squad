# Slack Multi-Agent Bot 설정 가이드

## 1. Slack App 생성

1. [https://api.slack.com/apps](https://api.slack.com/apps) 접속
2. **Create New App** > **From scratch** 선택
3. App 이름 입력 (예: `AI Multi-Agent`) 후 워크스페이스 선택

## 2. Socket Mode 활성화

1. 좌측 메뉴 **Settings > Socket Mode** 클릭
2. **Enable Socket Mode** 토글 ON
3. App-Level Token 이름 입력 (예: `socket-token`) 후 생성
4. `xapp-` 로 시작하는 토큰을 복사해 보관

## 3. Bot Token Scopes 설정

1. 좌측 메뉴 **Features > OAuth & Permissions** 클릭
2. **Scopes > Bot Token Scopes** 섹션에서 아래 scope 추가:
   - `chat:write` - 메시지 전송
   - `channels:history` - 공개 채널 메시지 읽기
   - `channels:read` - 채널 정보 조회

## 4. Event Subscriptions 설정

1. 좌측 메뉴 **Features > Event Subscriptions** 클릭
2. **Enable Events** 토글 ON
3. **Subscribe to bot events** 섹션에서 추가:
   - `message.channels` - 공개 채널의 메시지 이벤트

## 5. App 설치 및 Bot Token 획득

1. 좌측 메뉴 **Settings > Install App** 클릭
2. **Install to Workspace** 버튼 클릭 후 권한 허용
3. `xoxb-` 로 시작하는 **Bot User OAuth Token**을 복사해 보관

## 6. 채널 생성 및 봇 초대

1. Slack에서 채널 2개 생성:
   - `#ai-debate` - 토론 모드 전용
   - `#ai-coding` - 코딩 모드 전용
2. 각 채널에서 봇 초대:
   - 채널 입력창에 `/invite @AI Multi-Agent` 입력
   - 또는 채널 설정 > 통합 > 앱 추가

## 7. 채널 ID 확인 방법

아래 방법 중 하나를 사용합니다:

- **방법 1 (데스크톱)**: 채널명 우클릭 > **링크 복사** > URL 마지막 부분이 채널 ID
  - 예: `https://app.slack.com/client/T.../C07XXXXXXXX` → `C07XXXXXXXX`
- **방법 2 (채널 상세)**: 채널명 클릭 > 하단의 채널 ID 복사
- **방법 3 (API)**: `https://api.slack.com/methods/conversations.list/test` 에서 확인

채널 ID는 `C` 로 시작하는 11자리 문자열입니다.

## 8. .env 파일 설정

프로젝트 루트에 `.env` 파일을 생성합니다:

```env
SLACK_BOT_TOKEN=xoxb-xxxxxxxxxxxx-xxxxxxxxxxxx-xxxxxxxxxxxxxxxxxxxxxxxx
SLACK_APP_TOKEN=xapp-1-xxxxxxxxxxxx-xxxxxxxxxxxxx-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
DEBATE_CHANNEL_ID=C07XXXXXXXX
CODING_CHANNEL_ID=C07YYYYYYYY
```

## 9. 실행

```bash
# 의존성 설치
pip install -r requirements.txt

# 봇 실행
python slack_bot.py
```

정상 실행 시 아래와 같은 메시지가 출력됩니다:

```
==================================================
Slack Multi-Agent Bot 시작
  Debate Channel : C07XXXXXXXX
  Coding Channel : C07YYYYYYYY
==================================================
```

`#ai-debate` 채널에 메시지를 보내면 토론 모드가, `#ai-coding` 채널에 메시지를 보내면 코딩 모드가 작동합니다.
