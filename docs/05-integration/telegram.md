# 텔레그램 연동 명세

상태: 확정 · 출처: https://core.telegram.org/bots/api · 관련: [알림 정의서](../03-functional/notifications.md)

## 1. 설정 순서

1. 텔레그램에서 BotFather와 대화해 `/newbot`으로 봇을 만들고 토큰을 받는다.
2. 만든 봇에게 `/start`를 보낸다.
3. 앱의 마법사(W5)나 설정에서 토큰을 입력하고 "chat_id 찾기"를 누른다. 앱이 `getUpdates`로 chat_id를 찾는다.
4. "테스트 알림 보내기"로 확인한다.

## 2. 전송

- `POST https://api.telegram.org/bot<token>/sendMessage`, 본문은 `chat_id`, `text`.
- 서식 없이 일반 텍스트로 보낸다(서식 문자로 인한 오류와 주입을 피함).
- 4096자를 넘으면 자른다.

## 3. 제한과 실패

- 한 채팅에 초당 1건을 넘기지 않는다. 계속 넘기면 429가 온다.
- 429를 받으면 응답의 `retry_after`만큼 기다렸다가 다시 보낸다.
- 전송에 실패해도 매매에는 영향이 없다. 실패는 notifications 테이블과 로그에 남긴다.

## 4. 보안

- 토큰은 keyring에만 저장한다. 토큰이 들어간 URL은 로그에 남기지 않는다.
- 토큰이 있으면 누구나 봇을 조종할 수 있다. 유출되면 BotFather에서 토큰을 다시 발급하고 앱에 새 토큰을 넣는다.
- 보내기 전용이다. 텔레그램으로 매매 명령을 받지 않는다. chat_id를 찾을 때만 `getUpdates`를 쓴다.
