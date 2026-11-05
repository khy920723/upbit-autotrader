# 디스코드 연동 명세

상태: 확정(D-081, 2026-11-05) · 출처: 디스코드 개발자 문서 https://discord.com/developers/docs (Webhook, Message, Rate Limits, Opcodes and Status Codes). 이 세션에서는 discord.com 접근이 네트워크 정책으로 막혀, 공식 원본 저장소 github.com/discord/discord-api-docs(커밋 da52492, 2026-11-02)로 2026-11-05에 확인했다 · 관련: [알림 정의서](../03-functional/notifications.md), [보안 정책](../07-security-legal/security-policy.md)

## 1. 채널과 웹후크

- 앱 알림은 사용자 디스코드 서버의 비공개 채널 `app-alarm`으로 채널 웹후크(Incoming Webhook)를 통해 보낸다. 보내기 전용이다. 디스코드로 매매 명령을 받지 않는다(D-081).
- GitHub PR·CI 알림은 다른 채널 `git-alarm`으로 간다(D-075, `.github/workflows/notify-discord.yml`). 두 채널은 서로 다른 웹후크를 쓴다.
- 채널 웹후크는 특정 채널에 묶인 HTTP 주소다. 그 주소로 POST하면 그 채널에 글이 올라가고, 봇이나 상시 연결이 필요 없다(공식: Webhooks, "Incoming Webhooks").

## 2. 설정 순서

1. 디스코드 서버에 비공개 채널 `app-alarm`을 만든다.
2. 그 채널의 웹후크를 만들고 웹후크 주소를 복사한다. 디스코드 앱의 채널 설정에서 만든다(정확한 메뉴 위치는 개발자 문서에 없고 이 세션에서 확인하지 못했다).
3. 앱의 마법사(W5)나 설정에서 웹후크 주소를 붙여 넣는다. 앱은 주소 형식(`https://discord.com/api/webhooks/{id}/{token}`)을 검사하고 keyring에 저장한다.
4. "테스트 알림 보내기"로 확인한다.

## 3. 전송

| 항목 | 내용 | 출처(공식) |
|---|---|---|
| 요청 | 웹후크 주소(`POST /webhooks/{webhook.id}/{webhook.token}`)로 JSON 본문을 보낸다 | Webhook, "Execute Webhook" |
| `wait` | 앱은 `?wait=true`를 붙인다. 기본값(false)에서는 저장되지 않은 메시지도 오류를 돌려주지 않는다. true면 서버가 저장을 확인한 뒤 만든 메시지를 돌려준다 | Execute Webhook, Query String Params |
| 본문 | `content`만 쓴다. 최대 2000자다. `embeds`, 파일, 컴포넌트, `tts`, `poll`은 쓰지 않는다 | Execute Webhook, JSON Params |
| 멘션 막기 | 항상 `"allowed_mentions": {"parse": []}`를 넣는다. 웹후크의 기본값은 사용자 멘션을 해석한다(`{"parse": ["users"]}`). `{"parse": []}`는 메시지의 모든 멘션을 막는다 | Message, "Allowed Mentions Object" |
| 문자 | 디스코드는 잘못된 유니코드나 서식을 깨는 문자를 지울 수 있다. 외부에서 온 문자열(코인 이름, 공지 제목, 오류 문구)은 길이를 자르고 제어 문자를 지운 뒤 Markdown 특수 문자를 이스케이프한다 | Execute Webhook, 경고 |

- 2000자를 넘으면 2000자 안에서 자르고 끝에 "…(잘림)"을 붙인다. 몰린 알림을 묶을 때도 2000자를 넘지 않게 나눈다([알림 정의서](../03-functional/notifications.md) 1장).

## 4. 속도 제한과 실패

| 항목 | 내용 | 출처(공식) |
|---|---|---|
| 앱 규칙 | 초당 1건 이하로 보낸다(알림 정의서 1장). 몰리면 묶어서 보낸다 | - |
| 한도 헤더 | 요청 한도는 바뀔 수 있으므로 숫자를 코드에 박지 말고 응답 헤더(`X-RateLimit-Limit`, `-Remaining`, `-Reset`, `-Reset-After`, `-Bucket`)를 읽으라고 한다. 앱은 `X-RateLimit-Remaining`이 0이면 `X-RateLimit-Reset-After`초 동안 보내지 않는다 | Rate Limits, "Header Format" |
| 429 | JSON 본문의 `retry_after`(초, 소수)나 `Retry-After` 헤더만큼 기다린 뒤 다시 보낸다. 같은 알림의 재시도는 3회까지다. 기다리는 동안 들어온 알림은 묶는다 | Rate Limits, "Exceeding A Rate Limit" |
| 전역 한도 | 인증 헤더가 없으면 IP 기준 초당 50회다. 앱은 초당 1건이라 닿지 않는다 | Rate Limits, "Global Rate Limit" |
| 잘못된 요청 한도 | 401·403·429 응답이 10분에 10,000번을 넘으면 그 IP가 디스코드 API에서 일시적으로 막힌다. 웹후크가 404를 돌려주면 그 웹후크를 다시 쓰지 말라고 한다(반복하면 일시 제한) | Rate Limits, "Invalid Request Limit" |
| 오류 형식 | `{"message": "...", "code": 숫자}`. 예: 10015 Unknown webhook, 50027 Invalid webhook token provided, 50006 Cannot send an empty message, 50035 Invalid form body | Opcodes and Status Codes, "JSON" |

- 404(10015)나 401(50027)이면 웹후크가 지워졌거나 주소가 틀린 것이다. 다시 보내지 않고 디스코드 전송을 멈춘 뒤, 앱 화면에 MSG-W012(웹후크 다시 입력)를 띄운다. 새 주소를 저장하면 다시 보낸다.
- 전송에 실패해도 매매에는 영향이 없다. 실패는 notifications 테이블(`status`: `failed`, `rate_limited`)과 로그에 남긴다.

## 5. 보안

- 웹후크 주소는 비밀값이다. 주소에 웹후크 토큰("the secure token of the webhook")이 들어 있고, 토큰이 든 주소로는 인증 없이 그 웹후크를 쓸 수 있다(공식: Webhook Object, "Get Webhook with Token"). 주소를 아는 사람은 누구나 그 채널에 글을 쓸 수 있다.
- 앱 설정 화면에서 입력받아 keyring(Windows 자격 증명 관리자)에만 저장한다. 코드, 설정 파일, 로그, DB, 저장소, GitHub 비밀값에는 두지 않는다. git-alarm용 웹후크(GitHub 비밀값 `DISCORD_WEBHOOK_SECRET`, D-075)와 다른 웹후크를 쓴다.
- 로그와 예외 메시지에서는 주소의 토큰 부분(`/webhooks/{id}/` 뒤)을 가린다. 전송 실패 때 HTTP 라이브러리의 예외 메시지에 주소가 찍히지 않는지 카나리아로 시험한다([가짜 구현 명세](../08-quality/fakes-spec.md) 7장).
- 유출되면 디스코드에서 그 웹후크를 지우고 새 웹후크를 만들어 앱에 넣는다.
- 보내는 글에는 키, 토큰, 계정 정보, 잔고 총액을 넣지 않는다(알림 정의서 1장).

## 6. 확인하지 못한 것 (확인 필요)

| 항목 | 이유 | 확인 방법 |
|---|---|---|
| 디스코드 앱에서 채널 웹후크를 만드는 메뉴 위치 | 개발자 문서에 없고, 이 세션에서 discord.com 접근이 막혔다 | 사용자가 설정할 때 확인해 설치 가이드에 적는다 |
| discord.com 개발자 문서 사이트 원문 | 이 세션에서 접근이 막혀 공식 원본 저장소로 확인했다 | 7단계 구현 전에 사이트와 대조 |
