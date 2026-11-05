# 뉴스 수집 명세

상태: 초안 · 관련: [LLM 시그널 명세](llm-signal.md), [ADR-0005](../06-architecture/adr/0005-news-sources.md), [법·약관 검토](../07-security-legal/legal-compliance.md)

## 1. 원칙

- 공식 API와 RSS만 쓴다. 웹페이지를 긁어 오지 않는다.
- 제목, 링크, 출처, 발행 시각만 저장한다. 본문은 저장하지도 LLM에 보내지도 않는다.
- 화면에서 제목을 보여 줄 때 출처를 함께 표시한다.

## 2. 출처

| 출처 | 언어 | 방식 | 한도·비용 | 사용 |
|---|---|---|---|---|
| 네이버 검색 API(뉴스) | 한국어 | `GET https://openapi.naver.com/v1/search/news.json`, 헤더 `X-Naver-Client-Id`, `X-Naver-Client-Secret` | 하루 25,000회 무료 | 기본 |
| CoinDesk RSS | 영어 | https://www.coindesk.com/arc/outboundfeeds/rss/ | 무료 | 기본 |
| Cointelegraph RSS | 영어 | https://cointelegraph.com/rss | 무료 | 기본 |
| Decrypt RSS | 영어 | https://decrypt.co/feed | 무료 | 보류 |
| 블록미디어 RSS | 한국어 | blockmedia.co.kr/feed | 무료 | 보류(주소 재확인 필요) |
| 토큰포스트 RSS | 한국어 | tokenpost.kr/rss | 무료 | 보류(주소 재확인 필요) |

보류 출처는 이용 조건을 확인하기 전에는 쓰지 않는다. 쓰려면 약관을 확인하고 결정 로그에 기록한 뒤 추가한다.

### 쓰지 않는 출처

| 출처 | 이유 |
|---|---|
| Google 뉴스 RSS | 피드 안내문이 개인 피드 리더에서 개인·비상업적으로 보는 용도로 제한함 |
| CryptoPanic API | 2026-11 기준 무료 플랜 없음 |
| upbit.com 공지 페이지 | robots.txt가 수집을 막음. 대신 비공개 웹소켓 announcement 사용 |
| Gemini Google 검색 연동 | 무료 등급에서 불가, 표시 의무·분석 금지 조항 |

## 3. 수집 방법

- **시점:** 시그널 평가 직전(4시간마다). 네이버 호출은 하루 18회 안팎이다.
- **네이버:** `query`는 코인 한글명, `sort=date`, `display=20`.
- **RSS:** 피드 전체를 받아 코인 영문명과 티커로 거른다(대소문자 무시, 단어 경계). 티커가 일반 단어와 겹치는 경우의 처리는 4단계 시작 전에 정한다(제안, D-062 대기).
- **범위:** 최근 24시간, 코인당 최신순 최대 10개.
- **정리:** URL로 중복 제거, HTML 태그와 엔티티 제거, 제목 200자로 자르기.
- **실패:** 실패한 출처는 건너뛰고 나머지로 계속한다(MSG-E012). 모든 출처가 실패해도 뉴스 없이 평가한다.

## 4. 저장

- news_items(제목, 링크, 출처, 시각)와 signal_news(어떤 시그널에 어떤 제목이 쓰였는지).

## 5. 확인이 필요한 것

- 네이버 검색 API 이용약관에서 결과 저장과 제3자 서비스(Gemini) 전달 조건. 아직 확인하지 않았다. 4단계 전에 확인한다.
- 선택 출처 RSS의 이용 조건.
