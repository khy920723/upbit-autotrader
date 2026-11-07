# 진행 기록

세션이 끝날 때마다 맨 위에 추가한다. 형식: 날짜 — 단계 / 한 일 / 결정 / 남은 일 / 다음 단계.

## 2026-11-07 — 기획/문서: 뉴스 수집 제외(D-095~D-097)와 Gemini 약관 판단(D-103) 반영 (클라우드 세션)

- 한 일:
  - 지휘 세션이 전달한 4단계 약관 관련 사용자 결정(2026-11-07)을 반영했다. 뉴스를 수집하지 않는 방향으로 바뀌는 큰 변경이다.
  - [결정 로그](decision-log.md):
    - 유효로 바꿈: D-095(네이버 뺀다, 스크래핑·구글 검색 대체도 쓰지 않음), D-096(Cointelegraph 뺀다, 스크래핑으로 우회 불가), D-097(뉴스 없이 지표만).
    - 새로 넣음: D-103(Gemini 추가 약관 문장은 사용자가 본인 개발 목적으로 판단, 무료 유지, 유효), D-104(답 형식 A·B·C, 대기).
    - 대체됨으로 바꿈: D-101(RSS 티커 겹침), D-005(LLM 입력에 뉴스 제목), D-013(뉴스 출처). 모두 D-097로 대체됐다.
    - 상태 칸만 고침: D-099·D-100의 대기 조건(D-097 의존 삭제). D-100에는 사용자 요구와 한계를 반영한 제안을 넣었다.
  - [ADR-0005](../06-architecture/adr/0005-news-sources.md)를 "뉴스를 수집하지 않는다(약관)"로 개정했다. 다시 넣을 때의 조건(약관이 LLM 입력·저장을 허락하는 출처 또는 서면 허락, 공식 API·RSS만, 새 결정으로 기록)을 적었다.
  - 문서 정리. 뉴스 기능은 "하지 않음/쓰지 않음/만들지 않음(D-097)"으로 표시했고, 지우지 않고 이전 설계로 남겼다.
    - [뉴스 수집 명세](../05-integration/news-collection.md)(0장 현재 결정 추가)
    - [LLM 시그널 명세](../05-integration/llm-signal.md)(뉴스 블록 삭제, "검색 없이 답한다"는 한계와 사용자 요구, 프롬프트 제안, D-103·D-104)
    - [4단계 시작 전 결정 묶음](../03-functional/stage4-decisions.md)(0장 정해진 것, 남은 대기 표, 3.6절 대안 확인, 6.3절 D-104)
    - 요구사항 FR-07·NFR-07, 개요서, 용어, 사용자 시나리오, 메시지(MSG-E012), 화면 흐름·정의(마법사 W4 제외, 뉴스 상태 표시 제외), 기능 명세, 설정(네이버 키·뉴스 설정), 매매 로직
    - 데이터 모델(뉴스 테이블 제외), 로그·감사, 시스템 구성도(뉴스 어댑터·`NewsSource` 제외), ADR-0002·0009, 보안 정책, 법·약관 검토(6장 다시 씀, 4·5장 D-103)
    - 리스크 관리 대장(RSK-20 닫힘, RSK-27 "LLM이 최근 사건을 모름" 추가), 가짜 구현 명세(FakeNews 제외, `obedient`는 조작된 응답으로 재정의), 불변식, 리뷰 점검표, 테스트 시나리오(TS-20 재정의, TS-22·107·108 쓰지 않음), 테스트 전략, 추적표, 설치 가이드(네이버 절), 로드맵 4단계 이름과 범위, 문서 지도
  - 사실 확인: Gemini 검색 그라운딩의 무료 등급 불가와 약관(표시 용도 한정, 분석·학습·저장 금지)은 이 세션이 aistudio.google.com에서 다시 확인했다. 네이버 스크래핑·구글 검색 관련 사실은 지휘 세션 확인값으로 출처와 함께 적었다. 해당 페이지가 이 세션의 네트워크 허용 목록 밖이라 원문은 다시 읽지 않았다.
  - 상대 링크와 표 열 수 검사 문제 0건, 바꾼 문서의 mermaid 그림 10개 렌더링 확인.
- 결정: D-095·D-096·D-097·D-103 유효, D-101·D-005·D-013 대체됨(D-097), D-104 대기(새로)
- CLAUDE.md 변경 제안(지휘 세션이 사용자 확인 뒤 처리. 이 세션은 CLAUDE.md를 고치지 않았다):
  - 45행 "외부 연동은 인터페이스 뒤에 둔다: 거래소, 시세, 뉴스, 시그널(LLM), 알림, 시계."에서 "뉴스,"를 뺀다(D-097).
  - 67행 "뉴스 제목은 구분된 데이터 블록에 넣고, 그 안의 지시는 무시하라고 명시한다. 도구 호출은 쓰지 않는다. 제목 길이를 제한한다."를 "입력(시세·지표 요약)은 구분된 데이터 블록에 넣고, 그 안의 지시는 무시하라고 명시한다. 도구 호출은 쓰지 않는다. 뉴스는 수집하지 않는다(D-097). 모델은 검색 없이 받은 데이터만 근거로 답하고, 최근 뉴스나 사건을 아는 것처럼 말하지 않게 한다."로 바꾼다.
  - 65행 응답 스키마는 D-104가 B(긍정%·부정% 필드 추가)로 정해질 때만 바꾼다. A·C면 그대로다.
- 남은 일:
  - 사용자: [결정 묶음](../03-functional/stage4-decisions.md) 1장의 남은 대기(D-054, D-102, D-098, ADR-0007, D-041·D-042·D-044, D-104, 그 뒤 D-057, D-045, D-099, D-100)에 답한다.
  - 지휘 세션: 위 CLAUDE.md 변경 제안을 사용자 확인 뒤 반영한다.
  - 프론트/백엔드: 4단계에서 뉴스 수집·FakeNews·뉴스 테이블·네이버 키를 만들지 않는다. 2026-11-07 main(abb69a7)의 `src/`·`tests/`에는 뉴스·네이버 관련 코드가 없다(읽기만 했고 고치지 않았다).
  - 기획/문서: D-104·D-100이 정해지면 LLM 시그널 명세 4·5장과 화면 정의서(시그널 표시)를 고친다. R22-01이 병합되면 D-091 (4)를 보완한다.
- 다음 단계: 남은 대기 결정 뒤 4단계(LLM 시그널, 뉴스 없음).

## 2026-11-07 — 기획/문서: 4단계 결정 묶음 검증 결과 12건 반영 (클라우드 세션)

- 한 일:
  - 지휘 세션의 독립 검증 결과 12건([PR #27](https://github.com/khy920723/upbit-autotrader/pull/27) 대상)을 원문으로 다시 확인한 뒤 [4단계 시작 전 결정 묶음](../03-functional/stage4-decisions.md), [매매 로직 명세](../03-functional/trading-logic.md) 5장, [LLM 시그널 명세](../05-integration/llm-signal.md) 3·4·6장, [뉴스 수집 명세](../05-integration/news-collection.md) 3장, [결정 로그](decision-log.md), [로드맵](roadmap.md) 외부 사실 표에 반영했다. 결정 상태는 모두 "대기" 그대로다.
  - 원문 대조 결과(2026-11-07):
    - google-genai 2.34.0·3.0.0 sdist 비교: 기본 API 버전(2.34.0 v1beta 고정, 3.0.0 v1과 환경 변수 `GOOGLE_GENAI_API_VERSION`), 코드의 `HttpOptions`가 우선, Interactions 재시도 계산(2.34.0은 attempts = 재시도 횟수, 3.0.0은 재시도 = attempts − 1), 전송 예외의 httpx2 타입, httpx2 전송의 SSL(Windows에서 truststore, 2.34.0은 certifi)을 소스로 확인했다. httpx2·httpcore2 2.16.0 wheel로 truststore 사용도 확인했다. 3.0.0 변경 기록(CHANGELOG)은 GitHub 접근이 안 돼 읽지 못했다.
    - 12번 항목: Interactions 오류 클래스가 `APIError` 하위가 아니라는 점은 두 버전 소스로 다시 확인돼 "미재확인" 대신 확인 날짜를 적었다. 응답 `model` 필드는 v1 API 레퍼런스를 다시 읽었고, 넘겨진 모델의 값은 여전히 문서에 없어 "확인 필요"로 남겼다.
    - 공식 문서: api-versions의 "SDKs default to v1beta" 문구, interactions-overview REST 예시의 `/v1beta`, 업비트 현재가 문서(`signed_change_rate`는 전일 종가(UTC 0시) 대비, 24시간 이동 변동률 필드 없음), 업비트 분 캔들 문서(4시간봉 경계 명시 없음).
    - 저장소: 규칙 조건 리포트 1·5·6.5장(R 중복 6.5~18.9%, 마감 시각 평가 가정, B 청산 하루 최대 19건), 4시간봉 녹화 픽스처(시작 KST 01·05·09·21시), `market/all` 응답(Hive, Safe, Sign, Cap, Kite, Ark, Blur 등 영문명 = 티커).
    - 원문을 읽지 못한 것(우회하지 않음): CoinDesk 약관(자동 접근 검사 화면, 두 번), NAVER API HUB 가이드(자동 접근 보안 필터)와 상품 페이지(연결 끊김). 지휘 세션이 읽은 값(CoinDesk 2026-10-30 시행·자동 접근·비상업 조항, HUB 한시적 무료·검색 월 775,000건·키당 50 RPS)은 "이 세션 미확인"으로 표시해 적었다.
  - 이 클라우드 환경의 네트워크 허용 목록에 www.ncloud.com, guide.ncloud-docs.com을 더했다(사용자 승인).
  - 상대 링크와 표 열 수 검사 문제 0건.
- 결정: 없음(모두 대기)
- 남은 일:
  - 사용자: [결정 묶음](../03-functional/stage4-decisions.md) 1장 질문에 답한다. C-1은 이제 CoinDesk 약관의 자동 접근·비상업 조항을 어떻게 볼지 판단하는 항목이다.
  - 인프라: D-102가 3.0.x로 정해지면 truststore가 D-093(certifi 통일), `--self-test` TLS 점검, PyInstaller 묶음에 주는 영향을 확인한다.
  - 기획/문서: D-102 결과에 맞춰 D-055의 `attempts` 값과 LLM 시그널 명세 3장의 예외 서술을 고친다. R22-01이 병합되면 D-091 (4)를 보완한다.
- 다음 단계: 사용자 결정 뒤 4단계(뉴스 + LLM 시그널).

## 2026-11-07 — 기획/문서: 4단계 시작 전 결정 묶음 (클라우드 세션)

- 한 일:
  - [4단계 시작 전 결정 묶음](../03-functional/stage4-decisions.md)을 새로 썼다. 4단계 전에 사용자가 정할 항목을 질문, 선택지, 선택별 영향, 순서로 모았다. 추천과 수익 판단은 없고, 다른 문서에 있던 제안은 "(문서 제안안)"으로 표시했다.
    - 대상: 뉴스 출처(D-095~D-097, 확인 C-1), Gemini 호출 API(D-054)·SDK 버전(D-102)·기본 모델(D-098)·추가 약관 문장(확인 C-2), 규칙 조건(ADR-0007, D-021·D-072)·평가 시각(D-057)·시그널 유효 시간(D-045), 지표 요약(D-099)·프롬프트 첫 버전(D-100)·RSS 티커 겹침(D-101), 기반 결정(D-041·D-042·D-044).
  - 외부 사실을 공식 문서로 다시 확인했다(2026-11-07).
    - 네이버 검색 API 약관(2026-10-07 개정): 검색 API 특약 2.3이 데이터를 "AI에 입력"하는 행위와 2.4 범위(기기 24시간 또는 새 질의까지, 서버 이력 조회 21일)를 넘는 저장을 금지한다. 개발자센터의 검색 API 신규 신청은 2026-07-30에 끝났다(기존 이용자는 2027-06-30까지, 그 뒤 NAVER API HUB). 뉴스 검색 형식과 공통 오류(401, 429 두 종류)도 확인했다.
    - Cointelegraph 약관 3절: 서면 동의 없는 AI·LLM 이용(학습, 운영 등)을 금지한다.
    - CoinDesk 약관: 페이지가 자동 접근 검사 화면을 보여 읽지 못했다. 검사를 우회하지 않았고 사용자가 브라우저에서 확인한다(C-1).
    - Gemini: 무료 등급 모델 5개의 종료 일정·사고 수준·가격, 한도, Interactions GA와 v1 기능 지원, 429 오류 코드, 추가 약관의 사용 제한 문장을 다시 확인했다. google-genai 3.0.0(2026-11-06)은 HTTP 전송 기본값을 httpx2로 바꿨다(PyPI와 sdist).
    - 업비트 공개 시세 API `GET /v1/market/all`을 1회 불러 KRW 마켓 300개에서 티커가 흔한 영어 단어와 같은 코인과 영문명이 티커와 같은 코인(62개)을 셌다. RSS 두 피드를 받아 제목 55개에 지금 티커 규칙을 적용해 봤다(IN 9개, A 3개 제목에 맞음).
  - 이 클라우드 환경의 네트워크 허용 목록에 developers.naver.com, www.coindesk.com, cointelegraph.com을 더했다(사용자 승인).
  - [결정 로그](decision-log.md)에 D-095~D-102를 "대기"로 추가하고, D-066 행에 세부 결정 번호를 적었다.
  - 확인 결과와 링크를 반영한 문서: [로드맵](roadmap.md) 4단계와 외부 사실 표, [LLM 시그널 명세](../05-integration/llm-signal.md) 2·3·10장, [뉴스 수집 명세](../05-integration/news-collection.md) 2·3·5장, [ADR-0005](../06-architecture/adr/0005-news-sources.md)와 ADR 목록, [법·약관 검토](../07-security-legal/legal-compliance.md) 6장, [리스크 관리 대장](../07-security-legal/risk-register.md) RSK-20, [가짜 구현 명세](../08-quality/fakes-spec.md)(네이버 오류 형식), [설치·초기 설정 가이드](../09-operations/install-guide.md)(네이버 절), [문서 지도](../README.md). ADR-0005, D-013, 설정 기본값 같은 결정 자체는 바꾸지 않았다.
  - 상대 링크와 표 열 수 검사 문제 0건, mermaid 그림 렌더링 확인.
- 결정: 없음(새 항목은 모두 대기)
- 남은 일:
  - 사용자: [결정 묶음](../03-functional/stage4-decisions.md) 1장의 질문에 답한다. C-1(CoinDesk 약관)과 C-2(Gemini 추가 약관 문장)를 확인한다.
  - 기획/문서: 답을 받으면 ADR-0005, ADR-0007, 관련 명세를 고친다. D-097이 B면 새 뉴스 출처를 조사한다. R22-01이 병합되면 D-091 (4)를 보완한다.
  - 인프라: D-102가 정해지면 google-genai를 고정한다(라이선스 목록, PyInstaller 묶음 확인 포함).
- 다음 단계: 사용자 결정 뒤 4단계(뉴스 + LLM 시그널).

## 2026-11-07 — 기획/문서: 결정 D-092·D-094 반영, R22-02 문서 보완, 3단계 완료 표시 (클라우드 세션)

- 한 일:
  - 지휘 세션이 전달한 사용자 결정 2건(2026-11-07)을 반영했다. [결정 로그](decision-log.md)의 두 행을 "유효"로 바꾸고 근거에 "사용자 결정(2026-11-07, 지휘 세션 전달)"을 덧붙였다.
    - D-092 A(공지·시세 상태 매수 차단 세부, 제안 그대로): [업비트 API 연동 명세](../05-integration/upbit-api.md) 9장에 "D-092 공지·시세 상태 판단 세부" 절을 새로 썼다(정한 규칙, 근거, 선택지 기록). [테스트 시나리오](../08-quality/test-scenarios.md) TS-26(PREVIEW·값 없음도 차단)·TS-104를 고치고 TS-155(글자 맞추기 예)를 추가했다. 추적표 Q-06에 D-092를 이었다.
    - D-094 B(개별 주문 조회의 이름 없는 404를 "없음"으로 셈): [매매 로직 명세](../03-functional/trading-logic.md) 9장 표와 "이름 없는 404 처리" 절을 확정 문구로 바꾸고 15장을 유효로 고쳤다. 로그·감사 기록 정의서에 경고 이벤트 UNNAMED_NOT_FOUND, 가짜 구현 명세에 이름 없는 404 주입, TS-154를 추가했다. 어댑터(3a) 코드는 프론트/백엔드 정리 PR이 맞춘다.
  - QA R22-02의 문서 몫: 핸드셰이크 HTTP 401·403·429 거절을 감시 상태(RECONNECTING)에 싣고, 비공개 401·403은 `INVALID_AUTH`처럼(새 JWT로 한 번 다시 연결, 또 오면 5단계에서 REST 키 확인), 공개 401·403과 429는 backoff대로 다시 연결한다는 보완을 D-091 (12)로 썼다. D-080 행과 업비트 명세 9장 D-080 절, 시스템 구성도 7장 오류 처리 표에 같은 내용을 이었다. D-080은 "유효", D-091은 "유효(초안)" 그대로다.
  - R22-01(반쯤 열린 연결, PONG 대기)의 문서 변경은 프론트/백엔드 정리 PR이 아직 병합되지 않아 넣지 않았다.
  - [로드맵](roadmap.md) 3단계를 "(완료)"로 바꾸고 진행 줄을 완료 기록(QA 확인 2026-11-06, PR #24)으로 고쳤다.
- 결정: D-092 유효, D-094 유효. D-091 (12) 보완(초안).
- 남은 일:
  - 프론트/백엔드: 정리 PR(R17·R22, D-094 어댑터 처리, R22-02 상태 전달). R22-01이 병합되면 D-091 (4)의 보완 문구를 기획/문서가 넣는다.
  - 기획/문서: 4단계 시작 전 결정 묶음(다음 PR).
- 다음 단계: 4단계(뉴스 + LLM 시그널) 시작 전 결정.

## 2026-11-06 — 인프라: 라이선스 목록 excludes 설명(R17-05)과 websockets 번들 확인 (클라우드 세션)

- 한 일:
  - QA R17-05: [의존성 라이선스 목록](../07-security-legal/dependency-licenses.md) 4장의 excludes 설명을 `packaging/autotrader.spec` 주석과 맞췄다.
    - 제외 항목 4묶음(setuptools 계열, `PySide6.QtNetwork`, `_pytest`·`pytest`, `httpx._main`·`pygments`)을 끌려오는 경로와 빼도 되는 이유로 표에 정리했다.
    - typing_extensions는 런타임에 들어간다고 고쳤다.
    - 제외 이유는 패키지 코드로 확인했다: anyio `_backends/_asyncio.py`의 pytest 연동 함수 두 곳, `httpx/__init__.py`의 `_main` ImportError 처리, `PySide6/__init__.py`의 실행되지 않는 분기.
    - 수치는 같은 spec의 Linux 빌드(main d6242b6)로 다시 쟀다. 번들 Python 모듈은 excludes가 없으면 1,089개, 있으면 535개다. excludes를 모두 빼면 spec이 `_distutils_hack, _pytest, packaging, pygments, setuptools`에서 멈춘다. 이전 문구의 "531개 → 247개"와 "typing_extensions에서 멈춤"은 지금과 맞지 않았다.
  - websockets 번들 확인: PR #22의 build-exe windows 작업 로그(run 42137330425, job 127628692398, head cbe4a1d)를 읽었다.
    - PyInstaller가 contrib 훅 `hook-websockets.py`(websockets 하위 모듈 전체 수집)를 처리했다. 빌드와 개발 전용 모듈 검사를 통과했다.
    - `--self-test` 6/6 통과. 모듈 import 점검이 autotrader 모듈 30개를 모두 import하므로, 웹소켓 어댑터가 쓰는 `websockets.asyncio.client`·`websockets.exceptions`·`websockets.uri`가 Windows exe 안에서 import됐다.
    - TLS 줄은 "certifi 2026.10.23 묶음, CA 인증서 118개, OpenSSL 3.5.9 29 Sep 2026, 최소 TLSv1_2"로 certifi 묶음을 가리킨다.
    - 작업 로그에는 번들 파일 목록이 없다. 그래서 같은 spec의 Linux 빌드로 보충 확인했다: websockets 하위 모듈 52개, C 확장 `websockets/speedups`, `websockets-17.4.dist-info/licenses/LICENSE`, `certifi/cacert.pem`이 번들에 들어갔다.
  - 3b에서 바뀐 런타임 의존성 확인
    - 3장 표는 `uv.lock`과 맞다(검사 스크립트). 3장 첫 문장의 런타임 패키지 목록이 "PySide6, keyring"뿐이라 httpx, PyJWT, websockets, certifi를 더했다.
    - `packaging/NOTICE.txt`에는 certifi 2026.10.23(MPL-2.0) 고지와 소스 위치가 이미 있다. websockets(BSD-3-Clause)는 2장 규칙상 NOTICE 대상이 아니고, 라이선스 원문은 dist-info에 들어간다. NOTICE.txt는 고칠 것이 없었다.
  - [CI 변경 제안](ci-proposals.md) 2번(Windows에서 네트워크 차단·웹소켓 루프백 테스트)은 사용자 승인(2026-11-07)으로 build-exe.yml에 반영되어(main 554757f, 변경안과 같은 내용) 지웠다.
  - 린트 통과, 테스트 3,763개 통과(9개 건너뜀), 줄·분기 커버리지 합계 96%
- 결정: 없음
- 남은 일:
  - Windows 번들 안의 websockets 파일 목록을 직접 보려면 build-exe를 수동 실행해 올린 결과물을 열어야 한다(이번에는 로그와 Linux 빌드로 확인).
  - PR: 이 세션의 PR 생성(REST)은 auto 모드 권한 검사에서 "외부 시스템 쓰기"로 거부됐고, 지휘 세션이 [PR #25](https://github.com/khy920723/upbit-autotrader/pull/25)를 열었다. 이 세션은 main 병합과 충돌 해결만 했다.
- 다음 단계: 3단계 QA 검토 뒤 정리 PR(R17-04·R17-06·R17-07)

## 2026-11-06 — QA: PR #22(3단계 3b 업비트 웹소켓) 검토와 3단계 완료 확인 (클라우드 세션)

- 한 일:
  - 지휘 세션 요청으로 병합된 [PR #22](https://github.com/khy920723/upbit-autotrader/pull/22)(main `d6242b6`)를 [PR 검토 기준](../08-quality/review-checklist.md)의 공통·인프라·기능·테스트 항목으로 검토했다. 하위 에이전트 없이 직접 했다. `src/`·`tests/`는 바꾸지 않았고, 테스트 보강은 아래 목록으로만 남긴다.
  - 판정: **필수 0건, 권장 6건.** 로드맵 3단계의 완료 기준("가짜 거래소로 테스트 통과")을 충족한다. JWT 서명, 요청 한도, 오류 매핑, 주문 가능 정보, 호가 단위, 종목 경고, 시세·비공개 웹소켓과 재연결 뒤 대조 자리, REST·웹소켓 가짜가 모두 들어왔다. 대조 자리의 내용과 상태 연결은 5단계 몫이다.
  - 웹소켓 확인:
    - D-080: TOO_MANY_REQUEST는 1초(분당 한도면 60초) 뒤 1번 다시 연다. INVALID_AUTH는 새 JWT로 1번 다시 열고, 또 오면 AUTH_CHECK다. 그 밖의 오류 이름은 BROKEN이다.
    - D-091: backoff 1~60초이고 60초 넘게 유지되면 처음으로 돌린다. 공개 시세는 120초 무수신이면 DEGRADED를 알린 뒤 다시 연결한다. PING 프레임은 30초마다다. 재연결 때는 대조 훅이 끝난 뒤 OPEN을 알린다. 프록시와 리다이렉트를 쓰지 않는다.
    - 연결 한도: 스트림 객체마다 연결은 초당 2회, 구독 메시지는 초당 2개·분당 50개다.
    - Origin: `origin=None`이고, 추가 헤더에 넣으면 거부하며, 루프백 테스트가 실제 핸드셰이크에 없음을 본다.
    - 비공개 인증: 연결마다 새 HS512 JWT(access_key·nonce)를 만든다. 헤더 튜플의 repr이 값을 가린다. 라이브러리 DEBUG 로그를 막는다. 예외를 except 밖에서 올려 라이브러리 프레임을 잇지 않는다.
  - 확인한 것:
    - `uv sync --locked`, `uv run ruff check .` 통과. `QT_QPA_PLATFORM=offscreen uv run pytest -q --cov --cov-branch`는 3763개 통과, 9개 건너뜀(IPv6 소켓 없음 8, Windows 전용 1)이다. 커버리지는 전체 96%, `websocket.py` 95%, `streams.py` 93%, `tls.py`·`notices.py` 100%다.
    - PR #22 head `cbe4a1d`의 `test`·`windows`가 성공했다.
    - `windows` 작업 로그(job 127628692398): uv가 websockets 17.4·certifi 2026.10.23을 설치했고, PyInstaller가 `hook-websockets`(contrib)·`hook-certifi`를 처리하고 `autotrader.adapters.upbit.websocket`을 분석했다. 번들 검사를 통과했고 exe 자가 점검이 6/6이다(import "autotrader 모듈 30개", TLS "certifi 2026.10.23 묶음, CA 인증서 118개, OpenSSL 3.5.9, 최소 TLSv1_2"). 이 러너는 windows-2025(Windows 10.0.26100)라 Windows 10 실기 점검은 따로다.
    - 공식 문서 대조: `tests/fixtures/upbit/docs_examples/`의 웹소켓 6개 가운데 5개(ticker, myOrder, myAsset, announcement, 안내 문서)가 2026-11-05에 받은 문서 사본의 예시와 같다(Decimal 비교). `websocket-list-subscriptions.json`은 대조할 사본이 없어 확인하지 못했다. 공지 카테고리 `trade`가 문서 목록에 있고, 구독 파라미터(myOrder의 codes 생략 = 모든 마켓, announcement의 `include_body`)가 문서와 같다.
    - 공개 시세 녹화 `ws_public_recording.json`에 비밀·IP·쿠키가 없다(응답 헤더는 Date·sec-websocket-extensions뿐).
    - websockets 17.4의 라이선스 BSD-3-Clause가 설치 메타데이터·[의존성 라이선스 목록](../07-security-legal/dependency-licenses.md)과 같다.
    - 차이의 비밀 모양 검색: Bearer 값은 모두 가짜이고, IP는 문서용(203.0.113.0/24)·사설·링크 로컬·루프백 주소뿐이다.
  - R17(PR #17 검토) 반영 확인:

| ID | 상태 | 근거 |
|---|---|---|
| R17-01 | 반영 | `src/autotrader/adapters/upbit/errors.py:57`이 `duplicated_identifier`를 `UpbitIdentifierConflict`(`src/autotrader/core/errors.py:95`, UpbitOrderRejected를 상속하지 않음)로 바꾼다. 테스트 `tests/unit/upbit/test_errors.py:112·165·176`, `tests/unit/upbit/test_exchange.py:719`. 시스템 구성도 7장(`docs/06-architecture/system-architecture.md:329·350`)도 고쳤다 |
| R17-02 | 반영(한계 있음) | `tests/conftest.py`의 hook이 `pytest_configure`에서 차단을 걸고(`tests/fakes/network_guard.py`), 삼켜진 시도도 정리 단계에서 실패로 만든다. 차단이 풀리면 실패한다. Windows 경로는 한 번도 돌지 않았고(CI 변경안 2번), 우회 경로는 R22-06 |
| R17-03·D-093 | 반영 | TLS 문맥은 `src/autotrader/adapters/tls.py` 한 곳에서 만든다. REST는 `http.py:187-188·196`(certifi 문맥, `trust_env=False`), 웹소켓은 `websocket.py:327·346`, 자가 점검은 `self_test.py:173·197`이 쓴다. `tests/unit/test_architecture.py:594-596`이 다른 곳에서 문맥을 만들지 못하게 막는다. 자가 점검에 `anyio._backends._asyncio` import를 더했다. Windows exe 결과는 위와 같다 |
| R17-04 | 남음(정리 PR) | 3b의 새 테스트 함수 475개도 docstring 첫 줄 ID가 0개다(R22-04) |
| R17-05 | 남음(인프라) | `docs/07-security-legal/dependency-licenses.md:65` |
| R17-06 | 남음(정리 PR) | 웹소켓 쪽 같은 종류는 R22-03 |
| R17-07 | 남음(정리 PR) | - |
| R17-08 | 반영(PR #23) | 업비트 API 연동 명세 4장이 "지연 차이가 1초보다 작을 때만"으로 고쳐졌고, 넘치면 429·`TOO_MANY_REQUEST` 처리가 막는다고 적었다. INV-13에 "송신 허가 시각 기준"을 밝혔다 |
| R17-09 | 반영(알림은 5단계) | 24시간 상한 `ratelimit.py:82`, 표시 `retry_after_capped`(`ratelimit.py:217·229`), 9자리 초과는 `math.inf`(`errors.py:97`). 테스트 `tests/unit/upbit/test_ratelimit.py:617-700`. 표시가 켜질 때의 긴급 알림은 5단계 앱 계층이 보낸다 |
| R17-10 | 결정됨 | D-093 선택지 A(certifi 묶음) |
| R17-11 | 제안 기록(PR #23, D-094 대기) | 매매 로직 명세 9장 "이름 없는 404 처리"에 선택지 A·B·C와 추천 B를 적었다. 결정 전 구현은 A(세지 않음)와 같다. 사용자 결정이 남았다 |

  - 결과:

| ID | 심각도 | 근거(파일:줄) | 문제와 고칠 방법 | 고칠 세션 |
|---|---|---|---|---|
| R22-01 | 권장(중간) | `src/autotrader/adapters/upbit/websocket.py:175·294·354-355`, `src/autotrader/core/streams.py:386` | 반쯤 열린 연결을 늦게 알아챈다. PING을 보내고 PONG을 기다리지 않으며 라이브러리 keepalive도 껐다. 비공개 스트림에는 무수신 감시도 없다(D-091 (3)). 공유기 NAT 만료나 망 전환으로 TCP가 반쯤 열리면 OS의 TCP 재전송 시간 초과까지 끊김을 모른다. 주문 체결은 JOB-05(30초 REST 재조정)가 메우지만, 그동안 공지(D-079)와 myAsset을 받지 못한다. 고칠 방법: `_keepalive`가 PING의 PONG을 Clock 기준 상한(예: 30초) 안에 받지 못하면 StreamClosed(reason "pong_timeout")로 끝낸다. D-091 (4)에 보완을 적는다. 테스트: 가짜에 PONG을 보내지 않는 주입을 더하고, 상한 뒤 다시 연결되는지 본다 | 프론트/백엔드 |
| R22-02 | 권장(중간) | `src/autotrader/core/streams.py:483·539-546`, `src/autotrader/core/models.py:456-467` | 핸드셰이크 HTTP 상태가 감시 상태로 전달되지 않는다. `StreamConnectFailed.http_status`(401·403·429)를 StreamStatus에 싣지 않아 앱이 인증·한도 문제와 네트워크 끊김을 구분하지 못한다. 업비트가 비공개 연결의 인증 실패(키 만료, 허용 IP 아님)를 핸드셰이크 401·403으로 거절하는지는 문서에 없다(문서는 연결 뒤 INVALID_AUTH 메시지만 적었다). 그렇게 오면 감시는 60초마다 끝없이 다시 연결한다. 고칠 방법: RECONNECTING 상태에 HTTP 상태를 싣는다(예: error_name "HTTP_401"). 5단계에서 401·403 연결 실패가 이어지면 REST로 키를 확인(AUTH_CHECK와 같게)하도록 D-080·D-091에 보완을 적는다 | 프론트/백엔드(상태 전달), 기획/문서(D-080·D-091 보완, 5단계 처리) |
| R22-03 | 권장(낮음) | `src/autotrader/adapters/upbit/websocket.py:227·229·231·678-679·687-688·722`, `src/autotrader/core/streams.py:381-382` | 보내기 전 검사와 예외 변환 분기가 시험되지 않았다(R17-06과 같은 종류). 헤더 검사의 거부(같은 이름 두 번, Origin, User-Agent), OSError → core 오류 변환, `open_stream`이 core 오류를 낼 때가 해당한다. Origin 거부 분기는 CLAUDE.md 규칙이라 먼저 시험한다. 정리 PR에서 R17-06과 함께 한다 | 프론트/백엔드 |
| R22-04 | 권장(낮음) | 3b의 새 테스트 파일 10개 | R17-04의 범위가 넓어졌다. 테스트 함수 475개 중 docstring 첫 줄에 TS·INV ID가 있는 것이 0개다. 우선 넣을 곳: `tests/unit/upbit/test_websocket.py:758`(INV-13 Origin), `:864`(INV-14), `:1540·1559`(INV-13 한도), `:972`(TS-106 PING), `:2017·2055·2530`(INV-07), `tests/unit/test_streams.py:496·585·626`(TS-41, D-091), `tests/unit/test_notices.py:121`(TS-104), `tests/integration/test_websocket_loopback.py:551`(INV-07), `tests/unit/test_network_guard.py:202`(가짜 구현 명세 2.3절) | 프론트/백엔드 |
| R22-05 | 권장(낮음) | `src/autotrader/adapters/upbit/websocket.py:642-649` | 구독 메시지 예산은 연결 전에 확인하고 연결(await)이 끝난 뒤 기록한다. 그래서 같은 스트림 객체로 연결을 동시에 열면 분당 50개를 넘을 수 있다(초당 2개는 연결 예산이 먼저 막는다). 지금은 감시 하나가 연결을 하나씩 열어 생기지 않는다. 고칠 방법: 5단계 조립에서 스트림 객체마다 감시 하나만 쓰게 하거나(3b 남은 일과 같다), 메시지 예산을 연결 전에 예약한다. INV-13의 웹소켓 쪽은 예시 테스트뿐이므로 동시 연결 속성 테스트를 더한다 | 프론트/백엔드 |
| R22-06 | 권장(낮음) | `tests/fakes/network_guard.py:23-25·79-87·207-214` | 네트워크 차단에 우회 경로가 남았다. 루프백을 허용하는데 클라우드 세션의 프록시가 루프백 주소에 있다(이 세션에서 확인). 지금은 프록시 환경 변수를 지우고 앱이 `trust_env=False`·`proxy=None`이라 보통 경로로는 쓰지 않는다. 그러나 그 주소로 직접 연결하는 코드는 막지 못한다. 고칠 방법: `install`이 지우기 전에 프록시 주소(호스트·포트)를 기록하고 그곳으로의 연결도 막는다. 자식 프로세스는 문서화된 한계다(자가 점검의 무네트워크는 `tests/unit/test_self_test.py:77`이 같은 프로세스에서 증명한다) | 프론트/백엔드 |

  - 불변식 증명 현황(3b 범위):
    - INV-13: 웹소켓 연결 초당 2회와 구독 분당 50개를 예시 테스트로 본다(`tests/unit/upbit/test_websocket.py:1540·1559`). 가짜를 쓰는 테스트마다 가짜가 절반 한도를 엄격 검사한다(`tests/fakes/upbit_ws.py:474·835`의 `rate_limit_half`). `Origin` 없음은 `test_websocket.py:758`과 루프백 핸드셰이크가 본다. 남은 것: 동시 연결 속성 테스트(R22-05).
    - INV-07: 로그·예외·repr·traceback 지역 변수에 카나리아가 0건이다(`test_websocket.py:2017·2055·2530`). 라이브러리 DEBUG 로그에 핸드셰이크 헤더가 없다(`tests/integration/test_websocket_loopback.py:551`). 연결 실패 때 비밀이 남지 않는다(`:728`). 남은 것: 가리기 필터, DB·알림(이후 단계).
    - INV-14: 웹소켓 숫자를 float 없이 Decimal로 읽고(`test_websocket.py:864`), 이벤트 모델이 Decimal·int ms만 받는다(`src/autotrader/core/models.py`의 `_check_stream_event`).
    - INV-16: core 감시의 시간(무수신, backoff)과 어댑터의 PING·연결 상한은 Clock으로 잰다(라이브러리에 넘기는 `open_timeout`·`close_timeout`만 실제 시간이다). core 구조 검사가 그대로 돈다.
  - 테스트 보강 목록(코드는 고치지 않았다):
    1. PONG이 오지 않는 연결의 끊김(R22-01).
    2. 핸드셰이크 401·403·429가 상태로 전달되는지(R22-02).
    3. 헤더 검사·예외 변환 분기(R22-03), docstring 첫 줄 ID(R22-04).
    4. 같은 스트림 객체의 동시 연결에서 웹소켓 한도 속성(R22-05).
    5. 루프백 프록시 주소로의 직접 연결 차단(R22-06).
- 결정: 없음.
- 남은 일:
  - 프론트/백엔드(3b 뒤 정리 PR): R17-04·R17-06·R17-07과 R22-01~R22-06.
  - 인프라: R17-05.
  - 기획/문서: R22-02의 D-080·D-091 보완 문구. 로드맵 3단계 "진행" 줄을 완료로 고친다(QA 확인 2026-11-06). R17-08·R17-11은 PR #23에서 처리했다.
  - 사용자: D-094(이름 없는 404, R17-11).
  - 사용자(로컬): CI 변경안 2번(Windows에서 네트워크 차단·웹소켓 루프백 테스트 실행).
  - 5단계: 3b 남은 일의 조립 목록(RateLimiter 공유, 스트림 객체 하나씩, 재연결 뒤 대조 내용, 상태를 매매 상태로, 24시간 상한 긴급 알림, 418 확인 요청을 가벼운 조회로).
- 다음 단계: 4단계(뉴스 + LLM 시그널). 정리 PR이 열리면 R17·R22 반영을 확인한다.

## 2026-11-06 — 기획/문서: QA 후속(R17-08, R17-11)과 설치 가이드 개선 (클라우드 세션)

- 한 일: QA 기록에서 기획/문서 몫으로 넘어온 세 가지를 지휘 세션 지시에 따라 처리했다.
  - R17-08([업비트 API 연동 명세](../05-integration/upbit-api.md) 4장)
    - "연결 지연이 끼어도 실제 한도를 넘지 않는다"를 고쳤다. 한도 장치는 송신 허가 시각을 센다.
    - 요청 사이 지연의 차이가 1초보다 작을 때만 서버의 1초 창에도 한도 이하로 닿는다.
    - 새 연결과 재사용 연결이 섞여 차이가 1초를 넘으면 한도를 넘을 수 있고, 그때는 429 처리가 막는다고 적었다.
    - 3단계 3b의 웹소켓 연결·구독 메시지 계수도 같은 한계가 있고, 넘으면 `TOO_MANY_REQUEST`(D-080) 처리를 따른다고 적었다.
    - [불변식 명세](../08-quality/invariants.md) INV-13에 "송신 허가 시각 기준"을 밝혔다.
  - R17-11([매매 로직 명세](../03-functional/trading-logic.md) 9장 "이름 없는 404 처리")
    - `GET /v1/order`에서 이름 없는 404를 D-046의 "없음"으로 셀지 정하는 제안을 썼다. 쉬운 설명, 공식 문서 사실, 선택지 A·B·C와 선택별 영향을 담았다. 추천은 B("없음"으로 세고 경고 이벤트를 남긴다)다.
    - 공식 문서 사실(2026-11-06 확인): REST 안내의 404 표는 주문 등 "데이터를 찾을 수 없음"의 에러 코드를 "—"로 적었고, 개별 주문 조회 문서의 예시는 `order_not_found`다.
    - [결정 로그](decision-log.md)에 D-094를 "대기"(제안안 포함)로 추가하고, 15장 결정 현황에 행을 넣었다.
  - [설치 가이드](../09-operations/install-guide.md) 3장
    - 명령은 PowerShell에서 실행한다고 밝혔다. cmd에서 실행했다가 "경로를 찾을 수 없습니다"로 실패한 기록이 있다.
    - zip은 앱 폴더 밖에 받는다.
    - 압축을 풀기 전에 차단 해제한다(탐색기 또는 `Unblock-File`).
    - 새 절 "인터넷 표시 확인": 푼 뒤 Zone.Identifier를 확인하고, 남았으면 `Get-ChildItem -Recurse $app | Unblock-File`로 지운다. 반디집이 `_internal\base_library.zip`에만 표시를 남겼던 점검 결과를 근거로 적었다.
    - Defender 절차가 3장 6번으로 바뀌었다.
  - [Windows 10 수동 점검표](../08-quality/manual-checklist-windows10.md)
    - 주의의 PowerShell 안내, M-06(앱 폴더 밖, Unblock-File 대안), M-07(설치 폴더 자리표시, 남으면 지우고 다시 확인, "조치 후 통과" 기록법), M-08(M-07 뒤 실행), M-09(3장 6번 참조)를 맞췄다.
  - [운영 런북](../09-operations/runbook.md) 3장 새 버전 설치에도 "인터넷 표시 확인"을 넣었다.
- 결정: 없음(D-094 대기).
- 남은 일:
  - 사용자: D-094(이름 없는 404), D-092(진행 중), D-060 등 대기 결정.
  - QA: 다음 설치 때 점검표 M-06~M-08을 새 절차로 다시 하고, M-07을 M-08 전에 했는지 적는다. M-11은 방화벽 방법으로 다시 한다.
- 다음 단계: 3단계 완료 확인(QA 검토) 뒤 4단계(뉴스 + LLM 시그널).

## 2026-11-06 — 3단계 3b: 업비트 웹소켓, 재연결 감시, 가짜 웹소켓, QA 권장 반영 (클라우드 세션)

- 한 일:
  - 런타임 의존성 `websockets==17.4`(ADR-0006)와 `certifi==2026.10.23`(직접 의존성으로, D-093)을 고정하고 uv.lock·의존성 라이선스 목록을 갱신했다.
  - core: 웹소켓 이벤트 모델(`StreamOpened`, `TickerEvent`, `MyOrderEvent`, `MyAssetEvent`, `AnnouncementEvent`, `StreamStatus`), 스트림 오류(`StreamClosed`, `StreamConnectFailed`, `StreamError` 계열), 포트(`PublicStream`·`PrivateStream`과 어댑터 계약), 재연결 감시 `core/streams.py`의 `StreamSupervisor`(backoff 1~60초, 60초 유지 뒤 처음으로, 공개 시세 120초 무수신·끊긴 채 재연결 실패 때 DEGRADED, D-080 오류 처리, 재연결 뒤 대조 자리, 대조가 끝난 뒤 OPEN), 공지·시세 상태로 매수 막기 `core/notices.py`(D-079, D-092 제안 A).
  - 어댑터: `adapters/upbit/websocket.py`(공개 ticker·비공개 myOrder·myAsset·announcement, 연결마다 새 JWT, PING 프레임 30초, 연결·메시지 한도 절반, 리다이렉트 금지, 라이브러리 예외를 core 오류로, 라이브러리 DEBUG 로그 차단, 깨진 메시지 안전 처리), `adapters/tls.py`(REST·웹소켓 공용 TLS 설정, certifi 묶음만, 약한 설정 거부, D-093). 자가 점검의 TLS 항목은 이 설정을 만들어 확인하고 import 점검에 `anyio._backends._asyncio`를 더했다(QA R17-03).
  - 가짜: 업비트 웹소켓 와이어 가짜 `tests/fakes/upbit_ws.py`(엄격 검사 16개 규칙, 주입, `make_fake_upbit_ws` 픽스처). 공개 시세 웹소켓을 실제로 녹화했다(`tests/fixtures/upbit/ws_public_recording.json`, 키 없음, 연결 3번): 서버 프레임은 모두 바이너리, 형식 오류 뒤 서버가 close 1000으로 끊음, 문자열 PING에 `{"status":"UP"}`. 공식 문서 웹소켓 예시 6개를 `docs_examples/`에 더했다.
  - QA 권장(PR #17 검토): R17-01 `duplicated_identifier` → 결과 불명 타입 `UpbitIdentifierConflict`(UpbitOrderRejected가 아님), R17-02 테스트 중 실제 네트워크 차단(루트 conftest의 hook, 세션 전체, 넓은 except가 삼켜도 실패, 덮어쓸 수 없음), R17-03 위 TLS·자가 점검. R17-04·06·07은 3b 뒤 정리 PR, R17-05는 인프라 몫으로 남겼다.
  - 사용자 결정 반영: D-088·D-089(A, 유효), D-089 보완(Retry-After 24시간 상한: 넘으면 24시간만 기다리고 상한 표시, 만기 뒤 확인 1건 — 3b에 구현), D-093(TLS 인증서는 certifi 묶음, 유효). 결정 번호는 main의 D-086과 겹치지 않게 3a의 D-086~D-089를 D-087~D-090으로 옮겼다.
  - 문서: 결정 로그 D-091(웹소켓 재연결·감시 세부, 유효(초안))·D-092(공지·시세 상태 판단 세부, 대기)·D-093, 업비트 API 연동 명세 2·4·5·9장, 시스템 구성도 5~7장(포트 계약, 오류 트리·처리 표), 가짜 구현 명세 2.3·2.5·5·7장, 보안 정책서, 테스트 시나리오 TS-137, Windows 수동 점검 M-10, 기능 명세서, 빌드·릴리스 7절(certifi 갱신), ADR-0006, 녹화 README, CI 변경안 2번.
  - 테스트 3763개 통과(9개 건너뜀: IPv6 소켓 없음 8, Windows 전용 1), 커버리지 96%, ruff 통과. 업비트 비공개 API·웹소켓은 부르지 않았다. 공개 시세 웹소켓만 녹화용으로 3번 연결했다.
  - 진행 방식(D-077): 작업 5개(B1 웹소켓 가짜, B2 웹소켓 어댑터, B3 core 감시·공지 판단, B4 TLS, B5 QA 권장·24시간 상한)마다 테스터 → 워커 → 리뷰어 → 수정 1회. 작업별 모델·노력은 PR 설명에 있다. 중간에 사용량 한도로 에이전트가 멈춰 한도가 풀린 뒤 이어서 했고, 컨테이너 재시작으로 리뷰어 하나를 재개했다.
- 결정: D-091 유효(초안), D-092 대기(사용자 선택: 공지 글자 판단 세부와 PREVIEW 매수 차단), D-093 유효, D-088·D-089 유효(D-089 보완 포함).
- 남은 일:
  - 사용자: D-092 선택.
  - 사용자(로컬): CI 변경안 2번(Windows 작업에서 네트워크 차단·웹소켓 루프백 테스트). Windows 전용 차단 경로(`IocpProactor.connect`·`sendto`)는 아직 Windows에서 돌려 보지 못했다.
  - 5단계(조립): 시세·거래 어댑터가 RateLimiter 하나를 공유, 스트림 객체는 앱 수명 동안 하나씩 재사용, 재연결 뒤 대조 내용(잔고·미체결·종목 갱신), OPEN·DEGRADED·BROKEN·AUTH_CHECK를 매매 상태로 옮기기, 24시간 상한 표시가 켜질 때 긴급 알림 한 번, 마켓별 시세 신선도, 418 확인 요청을 가벼운 조회로.
  - 정리 PR(3b 뒤): QA R17-04(테스트 docstring 첫 줄의 TS·INV ID), R17-06(보내기 전 검사 분기 테스트), R17-07(order_types 폐기 예정 표시).
  - 인프라: QA R17-05(라이선스 목록 4장 문구, 새 제외 항목), PyInstaller 묶음에 websockets가 들어가는지 Windows 빌드로 확인(리눅스 빌드에서는 self-test 6/6, TLS 줄 "certifi 2026.10.23 묶음, CA 인증서 118개").
  - 알려진 한계: `SSLKEYLOGFILE`이 있으면 문맥을 만들 때 빈 키 로그 파일이 생길 수 있다(세션 키는 쓰지 않는다). 공지 판단은 한글 이름 부분 문자열이라 "이더리움 클래식" 공지가 이더리움 매수도 막을 수 있다(D-079에서 받아들인 오탐).
- 다음 단계: 3단계 완료 확인(QA 검토) 뒤 4단계(뉴스 + LLM 시그널). 3b 뒤 정리 PR.

## 2026-11-06 — QA: Windows 10 수동 점검 0~2절(2단계 빌드) 결과 기록 (클라우드 세션)

- 한 일:
  - 사용자가 Windows 10 PC에서 한 [Windows 10 수동 점검표](../08-quality/manual-checklist-windows10.md) 0~2절(M-01~M-11) 결과를 점검표 8장 양식으로 기록했다. 결과는 사용자 보고를 지휘 세션이 전달한 것이다. 점검표 8장이 기록 위치를 진행 기록으로 정해 두어 별도 결과 문서는 만들지 않았다.
  - 시험 대상 빌드는 Actions 기록으로 대조했다: run 42024450590은 main `5e20b245d767`(3단계 3a 포함)에서 수동 실행한 build-exe이고 성공했다. 결과물은 `autotrader-windows-5e20b245d767a38783e992309f0f7cec593fe2f2`(34,842,349바이트)다.
  - 공개 저장소라 PC 이름, 사용자 이름, 사용자 폴더 경로의 실제 값은 적지 않았다.

```text
수동 점검 — 날짜: 2026-11-05~06, 앱 커밋: 5e20b24, Windows 빌드: 19045.7807
통과: M-01, M-02(ESU는 간접 확인), M-05, M-08, M-09, M-10
조치 후 통과: M-07(표시가 남은 파일 1개 → Unblock-File 뒤 0개)
절차 미준수: M-06(차단 해제 없이 반디집으로 압축을 품)
하지 않음: M-11(사용자가 그 PC로 작업 중이라 네트워크를 끊지 못함)
기록: M-03(PC 이름·사용자 이름에 한글·공백 없음), M-04(커밋 5e20b24, 2026-11-05)
해당 없음: M-12~M-35(2단계 범위 밖)
메모: 시험 폴더 %USERPROFILE%\Desktop\Project\upbit-autotrader(OneDrive 동기화 아님), SmartScreen 경고 있었음
```

  - 항목별 결과:

| ID | 결과 | 내용 |
|---|---|---|
| M-01 | 통과 | Windows 10 22H2, OS 빌드 19045.7807, 64비트 |
| M-02 | 통과 | Defender 실시간 보호 켜짐, 자동 시간 설정 켜짐(W32Time Type=NTP). ESU는 설정 화면이 아니라 업데이트 기록으로 간접 확인했다: KB5126657, KB5131595, KB5127308이 2026-10-15에 설치됐다. 일반 지원 종료(2025-10-14) 뒤에도 보안 업데이트를 받고 있다 |
| M-03 | 기록 | PC 이름과 사용자 이름에 한글·공백이 없다. 그래서 M-31을 따로 적지 않아도 된다 |
| M-04 | 기록 | 커밋 5e20b24(3단계 3a 포함), 2026-11-05 |
| M-05 | 통과 | zip 이름의 해시가 시험 커밋과 같다(Actions 기록으로도 확인) |
| M-06 | 절차 미준수 | zip을 "차단 해제" 하지 않고 반디집으로 풀었다. M-07 결과가 근거다 |
| M-07 | 조치 후 통과 | 압축을 푼 폴더에서 Zone.Identifier가 남은 파일은 `_internal\base_library.zip` 1개였다. 반디집이 표시를 안쪽 zip에만 옮긴 것으로 보인다. 사용자가 `Unblock-File`로 지운 뒤 0개 |
| M-08 | 통과 | 첫 실행에 SmartScreen 경고가 떴고 "추가 정보 → 실행"으로 실행했다. 빈 창(제목 "업비트 자동매매 0.0.1", 문구 "아직 매매 기능이 없는 빈 창입니다")이 정상으로 떴다 |
| M-09 | 통과 | Defender 보호 기록에 앱 관련 기록 0건 |
| M-10 | 통과 | 종료 코드 0, 보고서 6/6 통과, 보고서는 UTF-8 BOM. import 26개(PySide6 6.12.0, keyring 25.7.0, Python 3.13.17 64bit), Qt offscreen, WinVaultKeyring, SQLite 3.50.4(STRICT·WAL), TLS(OpenSSL 3.5.9, CA 41개, 최소 TLSv1_2), 설정 경로 `%LOCALAPPDATA%\upbit-autotrader` 쓰기 가능 |
| M-11 | 하지 않음 | 대체 방법(방화벽으로 앱의 외부 연결만 막고 자가 점검)은 안내만 했다. 코드 쪽 근거로는 `tests/unit/test_self_test.py:77`이 소켓 연결·이름 해석·keyring 호출을 막은 채 자가 점검을 돌려 통과한다(Linux CI). Windows exe에서의 확인은 남았다. 테스트 전체의 네트워크 차단 픽스처(R17-02)는 3b에서 들어온다 |

  - 확인 필요(보고에 없음): M-08의 게시자 표시("알 수 없는 게시자"인지), M-10에서 창이 뜨지 않았는지. M-07 확인을 M-08 첫 실행 전에 했는지 뒤에 했는지도 보고에 없다. SmartScreen 경고는 인터넷 표시(Zone.Identifier)가 있는 파일에서 뜨므로, exe에 표시가 없었다면 경고가 뜬 것과 맞지 않는다. 다음 설치 때 M-06 → M-07 → M-08 순서로 다시 본다.
  - 참고: M-10 TLS 항목의 CA 41개는 Windows 인증서 저장소를 센 값이다. 앱의 업비트 클라이언트는 certifi 묶음을 쓰므로 이 항목은 앱이 쓰는 인증서를 확인하지 않는다(R17-03, 3b에서 고치는 중).
- 결정: 없음.
- 남은 일:
  - 기획/문서(설치 가이드 개선 제안, 대상: [설치 가이드](../09-operations/install-guide.md) 3장 1~3번과 "자가 점검"):
    - 압축 프로그램마다 인터넷 표시(차단)를 옮기는 범위가 다르다. 이번에 반디집은 안쪽 zip(`_internal\base_library.zip`)에만 표시를 남겼다. 압축 프로그램의 동작에 기대지 않는 절차로 쓴다.
    - 받은 zip을 압축을 풀기 전에 차단 해제하거나, 푼 뒤 PowerShell에서 `Get-ChildItem -Recurse <폴더> | Unblock-File`을 실행하는 절차를 넣는다.
    - 명령은 "PowerShell에서" 실행한다고 명시한다. `Start-Process`와 `Get-ChildItem`은 PowerShell 명령이라 명령 프롬프트(cmd)에서는 실행되지 않는다(사용자가 처음에 cmd에서 실행해 실패했다).
    - zip은 앱 폴더 밖(예: 다운로드 폴더)에 받는다.
  - QA: 설치 가이드가 바뀌면 점검표 M-06·M-07의 절차를 맞춘다(Unblock-File 대체 절차, 시험 폴더 예). M-11은 다음 새 버전을 설치할 때(점검표 "언제 하나": 새 버전마다 1·2절) 방화벽 방법으로 다시 한다.
  - 사용자: 다음 월간 점검(운영 런북 "매월")에서 설정 화면의 ESU 등록 상태를 직접 보고, 그달 정기 보안 업데이트가 설치됐는지 확인한다.
- 다음 단계: 6단계를 마치면 3·6절, 7단계를 마치면 4·5절과 M-33.

## 2026-11-06 — 기획/문서: D-086 반영(하락률 기본값 2%)과 외부 자료 부록 (클라우드 세션)

- 한 일:
  - 지휘 세션이 전달한 사용자 결정(2026-11-06)을 반영했다. 사용자는 처음에 선택지 B(기본값 두기)를 고르고, 값으로 분할 설계 문서 5장 계산 예시의 2%를 골랐다. [결정 로그](decision-log.md) D-086을 "유효"로 바꿨다.
    - 결정 내용: "B: 기본값 2%. 사용자가 직접 고른 값이며 앱이나 지휘 세션이 권한 값이 아니다. 저장 검사(0 < 하락률 < 손절%)는 그대로"
    - 근거: 사용자 결정과 [하락률 리포트](../research/split-drop-rate.md)(PR #19) 링크
  - 기본값 2%를 맞췄다.
    - 설정 항목 정의서(`buy.next_step_drop_pct` 기본값 2.0, 설정 예 JSON)
    - [분할 매수·매도 설계](../03-functional/split-trading.md) 1·3.1·3.2·5.1·9.6·10장
    - ADR-0008, 매매 로직 명세 15장, 화면 정의서 W7, 로드맵 5단계, 문서 지도
  - 손절 %가 2% 이하일 때의 처리를 정했다. 그때는 기본값 2%가 저장 검사에 걸린다.
    - 매수 2단계를 고를 때 하락률 칸을 비워 둔다.
    - 하락률이 2%인 상태에서 손절 %를 2% 이하로 바꾸면 칸을 비운다.
    - 두 경우 모두 MSG-W014(새 문구)로 알리고, 직접 입력해야 저장된다. 저장 검사 자체는 바꾸지 않았다.
  - 문구와 시나리오를 고쳤다.
    - MSG-W013에 "기본값은 미리 채운 값이며 권하는 값이 아니다"를 넣었다.
    - 테스트 시나리오 TS-153(기본값과 손절 2% 이하 처리)을 추가하고, 요구사항 추적표 FR-27에 연결했다.
  - [하락률 리포트](../research/split-drop-rate.md)를 고쳤다.
    - 7장에 결정을 기록했다.
    - "부록 A. 외부 자료 조사(2026-11-06, 지휘 세션)"를 붙였다. 학술 자료, 나눠 사기와 한 번에 사기, 봇 가이드, 국내 커뮤니티, 이 앱의 제약에 대입한 결과, 출처 13개를 담았다.
    - 부록에 한계를 적었다: 검색 결과 요약 기준이고 원문 전체는 확인하지 않았다. 외부 결론의 수익률 비교를 이 앱에 그대로 옮길 수 없다. 추천은 없다.
- 결정: D-086 유효(기본값 2%).
- 남은 일:
  - 기획/문서: upbit-api.md의 R17-08·R17-11은 3b 병합 뒤 지시를 받아 고친다. Q-02 등 명세 공백이 남아 있다.
  - 사용자: D-060 등 나머지 대기 결정.
- 다음 단계: 3단계 3b(업비트 웹소켓, 프론트/백엔드 세션 진행 중). 분할 매매 구현은 5단계.

## 2026-11-05 — 기획/문서: 2단계 하락률 비교 리포트(D-086) (클라우드 세션)

- 한 일:
  - 지휘 세션이 전달한 사용자 요청(2026-11-05)으로 [2단계 하락률 비교 리포트](../research/split-drop-rate.md)를 썼다. 과거 60분봉으로 하락률 1·2·3·4%별 "2단계 가격 조건 도달 빈도"와 "그 뒤 손절로 이어지는 비율"을 수익률 없이 셌다.
    - 데이터: 업비트 공개 시세 API에서 KRW-BTC·ETH·XRP 60분봉을 받았다. 기간은 2024-11-05~2026-11-05 UTC이고, 코인당 17,520개 중 채운 빈 캔들이 31~32개였다.
    - 요청: 265회를 보냈다. 1.1초 창에 5회 이하로 제한했고 실제로는 1초에 최대 2회였다. `Origin` 헤더는 보내지 않았다. 캐시는 `research/data/split/`에 두고 커밋하지 않았다.
    - 모형: 4시간 평가 시점마다 1단계를 산다고 보고(시그널·규칙 없음) 코인당 4,194개, 모두 12,582개 사례를 셌다. 2단계는 평가 시각 시가가 1단계 가격 × (1 − 하락률) 이하일 때 50/50으로 산다. 손절은 평균 단가 × 0.95를 60분봉 저가로 판정했다. 보유 기간은 7일과 30일 두 가지다.
    - 결과 예(7일): 2단계 도달 비율은 1% 72.8%, 4% 14.5%였다. 2단계 전 손절은 1% 3.8%, 4% 30.9%였다. 2단계를 산 사례 중 손절은 46.5~51.0%였다. 손절 깊이 계산값은 5.48~6.94%였다.
    - 한계: 시그널을 넣지 않았다(도달 비율은 상한). 60분봉으로 어림했다. 사례가 서로 겹친다. 기간이 하나다. 추천은 없다.
  - 스크립트 `research/split/`를 추가했다.
    - 구성: `fetch_hourly.py`, `drop_rate.py`, `split_lab.py`, 대조용 `split_reference.py`, 오프라인 테스트 39개
    - PEP 723 형식이고 표준 라이브러리만 쓴다. 테스트만 pytest를 쓴다.
    - 캔들 받기는 `research/rules/candle_store.py`를 불러 썼다.
  - 검증
    - 대조용 구현으로 모든 사례(125,820건)를 다시 셌고, 결과가 같았다.
    - CSV를 직접 읽는 짧은 계산으로 12개 값(1단계만 손절 비율, 2% 도달 비율)을 다시 셌고, 모두 같았다.
    - 손 계산 예는 단위 테스트로 확인했다.
  - [결정 로그](decision-log.md) D-086 행과 [문서 지도](../README.md)에는 링크만 추가했다. D-086은 "대기" 그대로다.
- 결정: 없음(D-086 대기).
- 남은 일:
  - 사용자: 리포트를 보고 D-086(기본값 없음 A, 또는 예시 기본값 B와 그 값)을 정한다.
  - 기획/문서: D-086이 정해지면 설정 항목 정의서·분할 설계 9.6·결정 로그를 고친다.
- 다음 단계: 3단계(업비트 연동, 프론트/백엔드 세션 진행 중). 분할 매매 구현은 5단계.

## 2026-11-05 — QA: PR #17(3단계 3a 업비트 REST) 검토 (클라우드 세션)

- 한 일:
  - 지휘 세션 요청으로 병합된 [PR #17](https://github.com/khy920723/upbit-autotrader/pull/17)(main `5e20b24`)을 [PR 검토 기준](../08-quality/review-checklist.md)의 공통·인프라·기능·테스트 항목으로 검토했다. 하위 에이전트 없이 직접 했다. 프론트/백엔드가 3b를 작업 중이라 `src/`·`tests/`는 바꾸지 않았고, 테스트 보강은 아래 목록으로만 남긴다.
  - 판정: **필수 0건, 권장 8건, 질문 3건.** 주문 안전 규칙은 결정·명세대로다: 자동 재전송 없음(전송 `retries=0`, 리다이렉트를 따라가지 않음, HTTP 계층 실패 15종 × 호출 5종과 거래 어댑터 주입 8종에서 요청 1회), `smp_type=cancel_maker` 항상(속성 테스트), `Origin` 없음, `Content-Type`은 POST에만 1개, 경로 정규식과 경로 표(일괄 취소 경로 없음), query_hash(알려진 값 2개, 가짜가 앱 코드 없이 다시 계산), `Remaining-Req`의 `sec`만, 슬라이딩 창으로 절반 이하(동시 폭주 속성 테스트), 429·`sec=0`은 최소 1초 멈춤, 418은 D-078과 D-089 추천안 A, 오류 분류는 D-088 추천안 A, 로그·예외 문구·traceback 지역 변수에 카나리아 0건.
  - 확인한 것: `uv sync --locked`, `uv run ruff check .` 통과. `QT_QPA_PLATFORM=offscreen uv run pytest -q --cov --cov-branch` 2350개 통과(전체 96%, `adapters/upbit` 92~100%). head `4640270`과 병합 `5e20b24`의 `test`·`windows` 성공. 차이의 비밀·IP 모양 검색 0건. `tests/fixtures/upbit/docs_examples/` 12개가 공식 문서 예시와 같다(Decimal 비교, 키 목록은 자리표시만 다름). 가짜와 오류 매핑의 오류 이름·상태 코드, 주문 유형별 필수값, 주문 조회 파라미터, KRW 호가 단위 표(문서 갱신 2026-05-04), 한도 그룹 표가 공식 문서(2026-11-05 받음)와 같다. 새 런타임 패키지 8개의 라이선스가 설치 메타데이터와 같고, `packaging/NOTICE.txt`에 certifi 소스 주소가 있다.
  - 공개 시세 API로 2건 확인했다(키 없음, 1초 간격, `Origin` 없음): `markets=KRW-BTC%2CKRW-ETH`(쉼표 인코딩)가 ticker와 instruments에서 200이다. instruments 응답의 `Remaining-Req` group은 `orderbook`(경로 표와 같음)이고 `tick_size`는 문자열이다.
  - 결과:

| ID | 심각도 | 근거(파일:줄) | 문제와 고칠 방법 | 고칠 세션 |
|---|---|---|---|---|
| R17-01 | 권장(높음) | `src/autotrader/adapters/upbit/errors.py:54`, `src/autotrader/core/errors.py:3-4·90-91`, `tests/unit/upbit/test_errors.py:102`, `tests/unit/upbit/test_exchange.py:713` | `duplicated_identifier`를 `UpbitOrderRejected`로 바꾼다. 시스템 구성도 7장 트리(`docs/06-architecture/system-architecture.md:318`)대로라 설계 위반은 아니다. 하지만 core 오류 문서는 "UpbitOrderRejected는 거절"이라고 적었고, D-070·매매 로직 명세 8·10장(`docs/03-functional/trading-logic.md:162·199`)·INV-03은 UNKNOWN이다. 5단계가 타입만 보고 REJECTED로 닫으면 거래소에 있을 수 있는 주문을 놓치고 같은 코인에 새 주문을 낼 수 있다(INV-04). 고칠 방법: `UpbitOrderRejected`를 상속하지 않는 형제 타입(예: `UpbitIdentifierConflict`, "결과 불명, identifier로 조회")으로 매핑하고 두 테스트를 고친다. 최소안은 core 오류 문서에 예외를 적고 5단계에서 TS-89를 먼저 쓰는 것이다 | 프론트/백엔드, 기획/문서(타입을 나누면 시스템 구성도 7장) |
| R17-02 | 권장(높음, 3b 전) | `tests/conftest.py`(차단 픽스처 없음), `docs/08-quality/fakes-spec.md:92` | 가짜 구현 명세의 "실제 네트워크 없음" 규칙이 구현되지 않았다. 지금은 모든 `UpbitHttp`가 MockTransport를 받아 위반이 없다(`tests/unit/upbit/conftest.py:45`, `tests/unit/upbit/test_http.py:746`은 보내지 않음). 웹소켓 테스트가 들어오기 전에 `tests/conftest.py`에 autouse 픽스처로 `socket.socket.connect`(AF_INET·AF_INET6), `socket.getaddrinfo`, `socket.create_connection`을 막는다(`tests/unit/test_self_test.py:77-90`과 같은 방식). getaddrinfo도 막아야 Windows Proactor 루프의 연결이 이름 해석에서 걸린다 | 프론트/백엔드 |
| R17-03 | 권장(높음) | `src/autotrader/app/self_test.py:179`, `src/autotrader/adapters/upbit/http.py:167-173` | self-test의 TLS 점검은 `ssl.create_default_context()`(Windows는 시스템 인증서 저장소)를 본다. httpx 0.28.1은 `ssl.create_default_context(cafile=certifi.where())`를 쓴다(`httpx/_config.py`의 `create_ssl_context`). 그래서 번들에서 certifi의 `cacert.pem`이 빠져도 self-test는 통과하고 `UpbitHttp`를 만들 때 실패한다. 또 전송의 `trust_env` 기본값 때문에 `SSL_CERT_FILE`·`SSL_CERT_DIR` 환경 변수가 있으면 그 인증서를 믿는다(프록시 환경 변수는 전송을 직접 넘겨서 쓰지 않는다, `httpx/_client.py:1399`). 고칠 방법: SSL 문맥을 만드는 함수를 하나 두고 `UpbitHttp`와 self-test가 같은 함수를 쓰며, `trust_env`를 명시한다. PR #17이 제안한 `anyio._backends._asyncio` import 점검도 함께 넣는다 | 인프라(self-test), 프론트/백엔드(SSL 문맥) |
| R17-04 | 권장 | PR #17의 새 테스트 파일 15개 | 테스트 함수 612개 중 docstring 첫 줄에 TS·INV ID가 있는 것은 1개(`tests/unit/upbit/test_ratelimit.py:288`)다(RC-E02, 추적표 7장). 모듈 docstring에는 ID가 있다. 불변식·시나리오를 직접 증명하는 테스트부터 첫 줄에 ID를 넣는다: `test_http.py:655·742`(INV-03·TS-72), `:339`(INV-13·TS-72), `:1043`(TS-05), `:1150·1395`(INV-07), `:782`(INV-14), `test_exchange.py:602`(INV-06·TS-13), `:651`(INV-03), `:1246`(INV-07), `test_quotation.py:408`(TS-104), `:179·199`(TS-102), `test_architecture.py:435`(INV-16), `:496`(INV-14) | 프론트/백엔드 |
| R17-05 | 권장(낮음) | `docs/07-security-legal/dependency-licenses.md:63-64`, `packaging/autotrader.spec:171-177` | 4장 설명이 옛 상태다. "excludes를 빼고 빌드하면 `_distutils_hack, packaging, setuptools, typing_extensions`에서 멈춘다"고 적었지만 typing_extensions는 이제 런타임이고, 새 제외 항목 `_pytest`, `pytest`, `httpx._main`, `pygments`와 그 이유가 없다 | 인프라 |
| R17-06 | 권장(낮음) | `src/autotrader/adapters/upbit/exchange.py:67·104·136·336`, `src/autotrader/adapters/upbit/http.py:100·161` | 보내기 전 검사 분기 일부가 시험되지 않았다(테스트 전략 5장의 주문 관련 분기 100% 목표). 특히 `exchange.py:136`(smp_type이 cancel_maker가 아님)은 `OrderRequest`가 먼저 막아 닿지 않는다. 검사를 우회한 요청(`object.__setattr__`로 바꾼 값)을 넣어 ValueError와 전송 0건을 확인한다 | 프론트/백엔드 |
| R17-07 | 권장(낮음) | `src/autotrader/core/models.py:123`, `src/autotrader/adapters/upbit/exchange.py:204` | `market.order_types`는 공식 주문 가능 정보 문서에서 폐기 예정이다(대체: `bid_types`·`ask_types`). 지금은 빠지면 빈 튜플이라 안전하다. 필드 설명에 "폐기 예정, 판단에 쓰지 않는다"를 적거나 필드를 뺀다 | 프론트/백엔드 |
| R17-08 | 권장(낮음) | `docs/05-integration/upbit-api.md:90`, `src/autotrader/adapters/upbit/ratelimit.py:126·185` | "연결 지연이 끼어도 실제 한도를 넘지 않는다"는 요청 사이 지연의 차이가 1초 안일 때만 맞다. 한도 장치는 송신 허가 시각을 센다. 새 연결(TCP·TLS)과 재사용 연결이 섞여 지연 차이가 1초를 넘으면 서버의 1초 창에 한도보다 많이 들어갈 수 있다(그때는 429 처리가 막는다). 문구를 고친다 | 기획/문서 |
| R17-09 | 질문 | `src/autotrader/adapters/upbit/ratelimit.py:224`, `src/autotrader/adapters/upbit/errors.py:83` | `Retry-After`에 상한이 없다(9자리까지 읽어 약 31년). D-089 추천안 그대로지만, 비정상적으로 큰 값이 오면 앱을 다시 시작할 때까지 멈춘다. D-089를 물을 때 상한(예: 24시간)이나 "1시간을 넘으면 알리고 그 뒤 확인 1건"을 함께 묻는다 | 지휘(사용자에게) |
| R17-10 | 질문 | R17-03과 같음 | 신뢰할 인증서를 certifi 묶음으로 할지 Windows 인증서 저장소로 할지 정한다(ADR-0006). 회사망이나 백신이 TLS를 가로채는 PC에서는 그 루트 인증서가 시스템 저장소에만 있어 certifi로는 연결이 실패할 수 있다. 시스템 저장소를 쓰면 그 가로채기를 믿게 된다 | 기획/문서(ADR) → 사용자 |
| R17-11 | 질문 | `src/autotrader/adapters/upbit/exchange.py:322-331` | `GET /v1/order`에서 `order_not_found`만 "없음"(None)이고 이름 없는 404는 `UpbitNotFound`로 올린다. REST 안내 문서의 404 표는 "데이터를 찾을 수 없음"의 에러 코드를 "—"로 적었다(개별 조회 문서 예시는 `order_not_found`). 이름 없는 404를 D-046의 "없음"으로 셀지 정한다. 세지 않으면 그때 UNKNOWN이 풀리지 않아 그 코인 주문이 막힌다(안전하지만 NTF-16까지 간다) | 기획/문서(매매 로직 명세 9장) |

  - 불변식 증명 현황(3a 범위):
    - INV-03: 실패 유형마다 POST 1회(`tests/unit/upbit/test_exchange.py:651`, `tests/unit/upbit/test_http.py:655`), 기본 전송 재시도 0(`test_http.py:742`), 가짜의 `auto_retry`·`identifier` 위반 검출. 남은 것: DB 선커밋, `duplicated_identifier` → UNKNOWN(TS-89), 크래시 주입(5단계).
    - INV-06: 임의 유효 주문 → `smp_type=cancel_maker`로 1회 전송 속성 테스트(`test_exchange.py:602`), `OrderRequest`가 다른 값을 거부. 남은 것: 주문 종류 × 모드(5단계).
    - INV-07: 로그·예외 문구·traceback(capture_locals) 카나리아 0건(`test_http.py:1150·1395`, `test_exchange.py:1246·1717`), 키 목록은 앞 4자. 남은 것: 가리기 필터, DB·설정·CSV·알림·프롬프트(이후 단계).
    - INV-13: 동시 폭주 속성 테스트(정수 초 창·슬라이딩 창·공허한 통과 방지·진행 경계, `tests/unit/upbit/test_ratelimit.py:288`), 429·`sec=0` 멈춤, 418 차단 중 0건, `Origin` 없음(`test_http.py:339`). 남은 것: 웹소켓(3b), 시세·거래 어댑터가 RateLimiter 하나를 함께 쓰는 조립(5단계).
    - INV-14: 응답 JSON 숫자를 모두 Decimal로(`test_http.py:782·807·825`), 주문 숫자 문자열 왕복 속성(`test_exchange.py:1337`), core의 `float(` 0건(`tests/unit/test_architecture.py:496`). 남은 것: DB 저장·읽기 왕복(5단계).
    - INV-16: 구조 검사(`test_architecture.py:435`). 남은 것: PC 시계 점프 속성(5단계), 추적표 Q-14.
  - 테스트 보강 목록(코드는 고치지 않았다):
    1. 네트워크 차단 autouse 픽스처(R17-02).
    2. R17-01을 타입 분리로 고치면: `create_order`가 `reject("duplicated_identifier")`에서 `UpbitOrderRejected`가 아닌 타입을 낸다.
    3. 보내기 전 검사 분기(R17-06).
    4. self-test가 httpx와 같은 SSL 문맥으로 CA를 읽고 `anyio._backends._asyncio`를 import한다(R17-03).
    5. 5단계 몫: 주문 POST 중 태스크 취소(`CancelledError`)도 UNKNOWN으로 둔다(HTTP 계층은 취소를 그대로 올린다, `src/autotrader/adapters/upbit/http.py:280-288`). 418 만기 뒤 첫 요청은 가벼운 조회다(D-078. HTTP 계층은 어떤 요청이든 확인 요청으로 잡는다, `src/autotrader/adapters/upbit/ratelimit.py:255-266`). 시세·거래 어댑터의 RateLimiter 공유. TS-89. 매매 로직 명세 10장 "응답 수준" 표(예외 타입 → 주문 상태)를 표 테스트로.
- 결정: 없음. R17-09~R17-11은 사용자·기획 결정이 필요한 질문이다.
- 남은 일:
  - 프론트/백엔드: R17-01·02·04·06·07(3b PR에 넣거나 최신 main에서 새 PR).
  - 인프라: R17-03(self-test)·R17-05.
  - 기획/문서: R17-01(타입을 나누면 시스템 구성도 7장), R17-08, R17-10(ADR-0006), R17-11.
  - 지휘: R17-09를 D-088·D-089와 함께 사용자에게 묻는다.
- 다음 단계: 3b PR이 열리면 같은 기준으로 검토한다(R17-02의 차단 픽스처, D-080 웹소켓 오류 처리, INV-13의 웹소켓 한도).

## 2026-11-05 — 3단계 3a: 업비트 REST 연동과 가짜 거래소(REST) (클라우드 세션)

- 한 일:
  - 런타임 의존성 `httpx==0.28.1`, `pyjwt==2.15.1`을 정확한 버전으로 고정하고(ADR-0006, D-038) uv.lock과 [의존성 라이선스 목록](../07-security-legal/dependency-licenses.md)을 갱신했다. 함께 들어온 런타임 패키지: anyio 4.16.0, certifi 2026.10.23, h11 0.16.0, httpcore 1.0.9, idna 3.20, typing_extensions 4.16.0(개발 전용에서 런타임으로). PyInstaller spec의 제외 목록에서 typing_extensions를 뺐다(anyio가 쓴다).
  - core 기반: 오류 타입(시스템 구성도 7장, StorageError 포함), `Clock`·`AdjustableClock`·`SystemClock`, 값 모델(Decimal만 받음, 비밀은 복제·피클·asdict로도 안 나옴), 포트(QuotationApi·ExchangeApi), 호가 단위(`core/ticks.py`, 2026-05-04 문서 표).
  - 업비트 어댑터(`adapters/upbit/`): JWT HS512 서명과 query_hash(URL 인코딩 전 문자열, 배열 키 반복, `[]` 미인코딩), 요청 한도(그룹별 슬라이딩 창으로 절반 이하, `Remaining-Req`의 sec만, 429는 최소 1초 멈춤, 418은 D-078 단계 대기와 만기 뒤 확인 1건), `error.name` 기반 오류 매핑, HTTP 전송(자동 재시도 없음, 리다이렉트·쿠키 없음, 경로 표에 그룹과 인증 여부, 일괄 취소 경로 없음, 응답 숫자는 모두 Decimal), 시세 API(종목 목록과 market_event 경고, 캔들, 현재가 404 때 마켓별 재조회, 호가, instruments, 서버 시각), 거래 API(잔고, 주문 가능 정보, 주문 생성·검증의 호출 형식, 조회·취소, 키 목록). 주문 정책(금액 계산, 주문 유형 선택, 분할)은 만들지 않았다(5단계).
  - 가짜: FakeClock(정수 나노초, `run_for`, `suspend`, `true_utc_now`), 카나리아(`find_canaries`, `find_secret_shapes`), 업비트 REST 와이어 가짜 `FakeUpbitServer`(엄격 검사 21개 규칙, 주입, 체결 모형, `assert_clean`과 `make_fake_upbit` 픽스처). 공식 문서 응답 예시 12개를 `tests/fixtures/upbit/docs_examples/`에 두었다(키 값은 자리표시).
  - 구조 검사 강화: core는 표준 라이브러리와 core만 import, `time` 모듈은 core/clock.py만, asyncio 시간 상한·루프 시간 금지, core의 `float(` 금지.
  - 테스트 2350개(커버리지 96%), ruff 통과. 업비트는 공개·비공개 모두 부르지 않았다(문서 사이트만 읽음).
  - 진행 방식(D-077): 작업 4개(T1 기반, T2 서명·한도·전송, T3 가짜 거래소, T4 시세·거래 API)마다 하위 에이전트를 테스터 → 워커 → 리뷰어 → 수정 1회로 썼다. 작업별 모델·노력은 PR 설명에 있다.
  - main의 D-086(#16)과 겹치지 않게 이 단계의 결정 번호를 D-087~D-090으로 정했다.
- 결정:
  - D-087 요청 한도 계산(슬라이딩 창, 유효(초안)), D-090 업비트 HTTP 계층 세부(재시도 없음, Decimal 파싱, PyJWT 키 길이 경고 국소 억제, 경로 표, 값 검사, 쿠키·로그, 유효(초안)).
  - D-088 REST 오류 분류 세부(대기, 추천 A: 418 > 429 > 5xx는 상태 우선, 모르는 401·403은 HALTED 쪽), D-089 418 대기 세부(대기, 추천 A: 차단 중 418은 단계 안 올림, Retry-After는 양의 정수 초만, 만기 뒤 확인 1건). 구현은 추천안대로 해 두었고 사용자가 다른 안을 고르면 고친다.
- 남은 일:
  - 사용자: D-088·D-089 선택(지휘 세션이 묻는다).
  - 인프라 세션: PyInstaller 묶음에 httpx·httpcore·anyio(백엔드 동적 import, `hook-anyio` 있음)·certifi·PyJWT가 제대로 들어가는지 Windows 빌드로 확인. self-test는 앱 모듈을 모두 import하므로 httpx·jwt import는 점검된다. 필요하면 `anyio._backends._asyncio`를 점검 목록에 더한다.
  - 5단계: 조회의 "다음 초에 다시"·"5xx 1회 다시"는 호출하는 쪽이 한다(D-090). 418 확인 요청을 가벼운 조회로 보내는 일, 시세·거래 어댑터가 RateLimiter 하나를 공유하게 조립하는 일, 묶은 현재가 404 때 없는 마켓 기억, 미체결 목록 쪽 넘김 사이에 끝난 주문을 대조에서 잡는 정책.
  - 가짜: `slow`, `lookup_error`, `cancel_error`, `manual_order`, `exchange_only_order`, `balance_drift`, SMP `prevented`, 체결에 따른 잔고 변화, 실제 네트워크 차단 픽스처(fakes-spec 2.3).
  - 확인 필요(사용자 PC, 실제 키): 배열 파라미터의 `[]` 미인코딩이 실제로 통과하는지(upbit-api 3장), 418 응답의 실제 형식.
  - 새 개발 의존성은 넣지 않았다(asyncio 테스트는 표준 `asyncio.run`으로 했다).
- PR #17 Windows 빌드 실패와 조치: 번들 검사가 "개발·빌드 전용 패키지가 번들에 들어갔습니다: _pytest, pygments"로 실패했다(job 127231215977). Linux에서 같은 실패를 재현하고 xref로 확인하니 `anyio._backends._asyncio`가 pytest 연동 함수 안에서 `_pytest.outcomes`를, httpx 명령줄 도구 `httpx._main`이 pygments를 끌어왔다(`hook-anyio`는 `anyio._backends`만 모은다). spec의 excludes에 `_pytest`, `pytest`, `httpx._main`, `pygments`를 더했다(`httpx/__init__.py`는 `_main` import의 ImportError를 처리한다). 번들 검사는 그대로다. 다시 빌드한 Linux exe의 self-test가 6/6 통과했고, 새 런타임 패키지 8개의 라이선스 파일이 번들의 `*.dist-info`에 들어 있음을 확인했다(NOTICE.txt가 그 위치와 certifi 소스 주소를 안내한다).
- 다음 단계: 3b(시세·비공개 웹소켓, 재연결 뒤 REST 대조, D-079 공지 매수 차단, D-080 웹소켓 오류 처리, 웹소켓 가짜). 최신 main에서 새 브랜치로 한다.

## 2026-11-05 — 기획/문서: 분할 매매 결정 5건 반영(D-082~D-085, D-043) (클라우드 세션)

- 한 일:
  - 지휘 세션이 전달한 사용자 결정(2026-11-05)을 반영했다. 결정 로그의 다섯 행을 "유효"로 바꾸고 근거에 "사용자 결정(2026-11-05, 지휘 세션 전달)"을 덧붙였다. D-039와 D-022는 "대체됨(D-082)"으로 바꿨다.
    - D-082 A: 매수 단계별 비율과 익절 단계를 사용자가 입력(기본은 한 번에, 익절 꺼짐)
    - D-083: 매수 최대 2단계, 익절 최대 2단계(사용자가 직접 적은 값). 한 사이클 최대 주문은 코인당 4건, 코인 3개면 12건으로 다시 계산했다
    - D-084 B: 2단계는 시그널 평가 때 매수 조건을 다시 만족하고 현재가 ≤ 평균 단가 × (1 − 하락률)일 때. 하락률은 새 설정 `buy.next_step_drop_pct`(저장할 때 0 < 하락률 < 손절%)
    - D-085 A: 익절만 나눠 판다. 손절과 그 밖의 청산은 전량
    - D-043 A: 매수 최유리 FOK, 매도 시장가, 호가 기반 페이퍼 체결
  - 하락률의 기본값은 설계 문서에 제안 값이 없어 D-086(대기)으로 남겼다. 추천은 기본값 없이 2단계를 고르면 입력하게 하는 것이고, 결정 전까지 문서는 이 방식을 따른다.
  - 설정 화면 안내 문구 초안 MSG-W013을 넣었다. 손실 중에 노출이 늘고 손절이 첫 매수가보다 아래에서 일어난다는 위험과, 지금 설정으로 계산한 손절 위치를 보인다(50/50, 하락률 2%, 손절 5%면 첫 매수가 대비 약 5.96%).
  - [분할 매수·매도 설계](../03-functional/split-trading.md)를 확정 문서로 고쳤다. 선택지 표는 결정 기록으로 남겼다. 예산 현실성 표를 매수 2단계 기준으로 다시 정리했고(50/50 11,580원, 60/40 14,475원, 70/30 19,300원, 익절 50/50 11,586원), 3·4단계 행은 D-083 결과로 쓰지 않는다고 표시했다.
  - [ADR-0008](../06-architecture/adr/0008-buy-method.md)을 결정 내용으로 다시 써서 확정했다.
  - "제안·대기"로 적은 곳을 맞췄다:
    - 설정 항목 정의서: `buy.step_pcts`, `buy.next_step_drop_pct`, `sell.take_profit_steps`를 넣고 이전 키는 뺐다
    - 매매 로직 명세 2·3·4·6·7·10·13·14·15장: 2단계 조건, 익절 단계, 이유 코드 BUY_STEPS_DONE·STEP_DROP_NOT_MET·PLAN_INVALID, 의사코드
    - 상태 전이 정의서 4장, 위험 관리 정책서 2장("기본 설정에서는 분할 매수를 할 수 없다" 문구 포함)
    - 데이터 모델: positions의 `plan_json`·`tp_steps_done`·`tp_base_volume`, orders의 `step_no`, round_trips의 `tp_steps`
    - 메시지: MSG-E015 고침, MSG-E020·MSG-W013·MSG-I010 추가, 체결 문구의 `{step}`
    - 화면 정의서: W7, SCR-06, 코인 카드
    - 테스트 시나리오: TS-60~TS-62·TS-84·TS-92·TS-113·TS-138 고침, TS-146~TS-152 추가
    - 불변식 INV-01 고침, INV-20 추가, 테스트 전략의 불변식 범위
    - 가짜 구현, 요구사항 추적표(FR-26·FR-27, Q-02, Q-10)
    - 요구사항 정의서(FR-27 추가, 우선순위 S), 위험 목록 RSK-22, 용어 정의서, 로드맵 5단계, 문서 지도, ADR 목록
- 결정: D-082~D-085·D-043 유효, D-039·D-022 대체됨(D-082), D-086 대기.
- 남은 일:
  - 사용자: D-086(하락률 기본값), D-060 등 나머지 대기 결정. 요구사항 FR-27의 우선순위(S)는 기획 세션이 붙인 값이라 바꿀 수 있다.
  - 기획/문서: Q-02(일일 주문 수 상한 뒤 익절 허용 여부), 그 밖의 명세 공백.
  - 확인 필요: 매도 수량의 소수점 자릿수(5단계 구현 전).
- 다음 단계: 3단계(업비트 연동, 프론트/백엔드 세션 진행 중). 분할 매매 구현은 5단계.

## 2026-11-05 — 기획/문서: 분할 매수·매도 재설계 제안(D-082~D-085) (클라우드 세션)

- 한 일:
  - 지휘 세션이 전달한 사용자 요청(2026-11-05, D-043 질문에 직접 적은 답: 분할 매수·매도 알고리즘을 다시 설계하고, 단계 수와 비율은 사용자가 입력)에 따라 [분할 매수·매도 설계 제안](../03-functional/split-trading.md)을 새로 썼다. 문서만 썼고 구현은 없다.
    - 사용자 입력: 매수 단계별 비율(`buy.step_pcts`, 기본 `[100]`), 둘째 단계부터의 조건, 익절 단계(발동 수익률·매도 비율). 저장 검사 S1~S7(비율 합, 단계 수 상한, 단계 금액 ≥ 예산 하한, 익절 뒤 남는 원가, 하루 주문 수, 주문 간격, 조건 값)과 못 맞출 때 보여 줄 필요 예산·가능한 최대 단계 수
    - 매수 단계 진행: 둘째 단계부터는 시그널 평가 때 매수 조건(D-006)을 다시 만족해야 산다. 첫 익절 뒤 추가 매수 없음, 계획은 포지션을 열 때 고정, 평균 단가·손절선 다시 계산
    - 둘째 단계 조건 후보 4개(새 긍정 시그널, 하락, 상승, 시간)의 노출·손절선·주문 빈도 비교와 계산 예
    - 분할 매도는 익절만. 손절과 그 밖의 청산은 전량(위험 관리 원칙 2). 남는 부분이 손절 때 팔 수 없으면 그 단계에서 전량. 분할 손절은 제안하지 않는 선택지로만 적었다
    - 단계 주문 유형은 D-043 제안(매수 최유리 FOK, 매도 시장가)을 기본으로 두고 D-043과 함께 묻게 했다
    - 예산 현실성 표: 기본 예산 10,000원에서는 매수 1단계와 익절 1단계(전량)만 된다. 매수 2·3·4단계는 11,580원, 17,546원, 23,160원, 50/50 익절은 11,586원이 필요하다. 전체 노출 상한·일일 손실 한도와의 관계, 단계 수별 하루 주문 수
    - 영향 범위(결정 뒤 고칠 문서 15개)와 확인 필요(매도 수량 소수점 자릿수)
  - 결정 로그에 D-082(분할 구조), D-083(단계 수 상한), D-084(둘째 단계 조건), D-085(분할 매도 범위)를 "대기"로 추가했다. D-039·D-043의 상태를 "대기(D-082~D-085와 함께)"로 바꿨다.
  - [ADR-0008](../06-architecture/adr/0008-buy-method.md) 머리말과 "결정이 필요한 것", [ADR 목록](../06-architecture/adr/README.md), [매매 로직 명세](../03-functional/trading-logic.md) 15장, [설정 항목 정의서](../03-functional/settings.md), [위험 관리 정책서](../03-functional/risk-policy.md) 2장, [문서 지도](../README.md), [로드맵](roadmap.md) 5단계에 제안 문서를 연결했다. 확정 문서의 동작은 바꾸지 않았다.
- 결정: 없음(D-082~D-085 대기). 이 문서의 추천은 수익이 아니라 안전 제약과 단순성으로 골랐다.
- 남은 일:
  - 사용자: D-082 → D-083·D-084·D-085 → D-043 순서로 고른다. 결과에 따라 D-039·D-022를 정리한다.
  - 기획/문서: 결정되면 영향 범위의 문서를 고치고 ADR-0008을 확정한다. Q-02(상한 뒤 익절 허용)는 분할 익절과 함께 정할 수 있다.
- 다음 단계: 3단계(업비트 연동). 분할 매매 구현은 5단계.

## 2026-11-05 — 기획/문서: 결정 D-038·D-040 반영(ADR-0006·0009 확정) (클라우드 세션)

- 한 일:
  - 지휘 세션이 전달한 사용자 결정 2건(2026-11-05, 둘 다 추천안 A)을 반영했다. 결정 로그의 두 행을 "유효"로 바꾸고 근거에 "사용자 결정(2026-11-05, 지휘 세션 전달), 제안안 그대로"를 덧붙였다.
    - D-038 업비트 클라이언트: httpx 기반 자체 클라이언트(httpx, websockets, PyJWT). 공식 `upbit-sdk`는 의존성으로 넣지 않고 대조 자료로만 쓴다
    - D-040 GUI와 asyncio: 전용 core 스레드의 표준 asyncio 루프와 앱 계층 브리지
  - [ADR-0006](../06-architecture/adr/0006-upbit-client.md)과 [ADR-0009](../06-architecture/adr/0009-gui-asyncio-bridge.md)를 "확정"으로 바꿨다. "추천"을 "결정"·"채택"으로 고치고 "결정이 필요한 것" 절을 뺐다. ADR-0009의 D-060(비상 전송, 대기)은 "결과"에 별개 대기 결정으로 옮겼다.
  - 두 결정을 제안·대기로 적은 문서를 맞췄다: [ADR 목록](../06-architecture/adr/README.md), [기술 스택](../06-architecture/tech-stack.md)(httpx·websockets·PyJWT의 "후보" 표시 제거, 남은 대기는 D-041·D-042), [업비트 API 연동 명세](../05-integration/upbit-api.md) 머리말과 8장, [시스템 구성도](../06-architecture/system-architecture.md) 3장 제목과 10장, [법·약관 검토](../07-security-legal/legal-compliance.md) 3장, [문서 지도](../README.md)의 ADR 건수, [로드맵](roadmap.md) 3단계의 시작 조건.
- 결정: D-038·D-040 유효. D-043(주문 유형)은 분할 매매와 함께 다시 보기로 해 대기로 둔다.
- 남은 일:
  - 기획/문서: 분할 매수·매도 재설계 제안(다음 PR, D-043과 함께 묻는다).
  - 사용자: D-039·D-043 등 나머지 대기 결정.
- 다음 단계: 3단계(업비트 연동) 시작 조건이 갖춰졌다.

## 2026-11-05 — 기획/문서: 앱 알림 채널을 디스코드로 교체(D-081) (클라우드 세션)

- 한 일:
  - 지휘 세션이 전달한 사용자 결정(2026-11-05, "디스코드로 교체")을 D-081 "유효"로 기록했다. 앱 알림은 사용자 디스코드 서버의 비공개 채널 `app-alarm`으로 채널 웹후크를 통해 보낸다(보내기 전용). GitHub PR·CI 알림은 다른 채널 `git-alarm`(D-075)으로 가고 웹후크도 다르다. D-012의 상태는 "유효(알림 채널만 D-081로 대체됨)"로 바꿨다.
  - `docs/05-integration/telegram.md`를 지우고 [디스코드 연동 명세](../05-integration/discord.md)를 새로 썼다. 채널 구분, 설정 순서, 전송(`?wait=true`, `content` 2000자, `allowed_mentions` `{"parse": []}`), 속도 제한(응답 헤더, 429의 `retry_after`, 전역 한도, 잘못된 요청 한도), 오류 코드, 보안(웹후크 주소는 비밀값, keyring에만 저장, 로그에서 가림)을 담았다.
  - 디스코드 사실은 discord.com이 이 세션의 네트워크 정책으로 막혀, 공식 원본 저장소 discord/discord-api-docs(커밋 da52492, 2026-11-02)로 2026-11-05에 확인했다. 사이트 원문 대조와 디스코드 앱에서 웹후크를 만드는 메뉴 위치는 확인 필요로 남겼다(명세 6장).
  - 텔레그램을 언급하던 문서를 모두 디스코드에 맞췄다(바뀐 파일 29개, 진행 기록의 지난 기록과 결정 로그의 D-012 원문은 그대로 둠).
    - 설정: `telegram.bot_token`·`telegram.chat_id` → `discord.webhook_url`(keyring), `notify.telegram.enabled` → `notify.discord.enabled`
    - 알림 길이 한도: 4096자 → 2000자. 초당 1건, 묶어 보내기, 자르기, 금지 정보 원칙은 그대로
    - 메시지: MSG-W012(웹후크 사용 불가, 404·401) 추가
    - 가짜 구현 명세 6장 FakeNotifier를 디스코드 응답(200·204, 429, 404 10015, 401 50027, 400 50006·50035)으로 다시 썼다. PR 검토 기준의 비밀값 검사 정규식을 디스코드 웹후크 주소로 바꿨다
    - 그 밖에 요구사항 FR-16, 사용자 시나리오, 프로젝트 헌장, 화면 흐름·정의서(W5), 데이터 모델, 로그·감사, 시스템 구성도, ADR-0009, 보안 정책, 불변식 명세, 테스트 시나리오(TS-48, TS-101), 테스트 전략, 추적표, 페이퍼 평가, Windows 10 점검표, 설치 가이드, 로드맵 7단계, 문서 지도, 루트 README
  - D-060(대기)은 결정하지 않고 문구만 디스코드로 바꿨다. 앱이 완전히 멈추거나 PC가 꺼지거나 인터넷이 끊기면 앱이 알릴 수 없고, 이를 알리는 외부 감시 서비스(heartbeat 수신)는 사용자가 정한다는 점을 D-060 근거, [알림 정의서](../03-functional/notifications.md) 1장, ADR-0009에 적었다.
  - 정리: 지휘 세션이 사용자 승인(2026-11-05)에 따라 CLAUDE.md 두 줄을 PR #9 설명의 문안 그대로 main에 반영했다(커밋 a6291fd). 결정 로그 D-076·D-077과 이전 진행 기록의 "CLAUDE.md 두 곳 반영 여부"를 반영 완료로 고쳤다. PR #12(hypothesis 추가) 병합에 맞춰 [불변식 명세](../08-quality/invariants.md) 2.2절의 "아직 dev 그룹에 없다" 문구를 고쳤다. CLAUDE.md는 고치지 않았다.
- 결정: D-081 유효. 새 대기 결정 없음.
- 남은 일:
  - 코드: `src/autotrader/adapters/__init__.py`의 docstring에 "텔레그램"이 남아 있다. 문서 범위 밖이라 고치지 않았다(코드를 맡은 세션이 고친다).
  - 확인 필요: 디스코드 앱의 웹후크 메뉴 위치, discord.com 사이트 원문 대조(7단계 구현 전).
  - 사용자: D-060 등 나머지 대기 결정, 외부 감시 서비스 사용 여부.
  - 기획/문서: 명세 공백 Q-01, Q-02(남은 질문), Q-03, Q-05, Q-07, Q-08, Q-10~Q-16.
- 다음 단계: 3단계(업비트 연동). 디스코드 알림 구현은 7단계.

## 2026-11-05 — 개발 의존성: hypothesis 추가 (클라우드 세션)

- 한 일:
  - `pyproject.toml` dev 그룹에 `hypothesis>=6.170`을 넣었다(PyPI 최신 안정판 6.170.14). `uv lock`으로 hypothesis 6.170.14와 하위 의존성 sortedcontainers 2.4.0만 추가됐고, 다른 패키지 버전은 바뀌지 않았다. `uv sync --locked` 통과
  - `.gitignore`에 `.hypothesis/`를 넣었다.
  - pytest에 `slow` 마커(상태 기계 같은 장시간 테스트)를 등록했다. 기본 실행에서 빼지 않는다.
  - [의존성 라이선스 목록](../07-security-legal/dependency-licenses.md) 4장을 갱신했다. 휠의 라이선스 파일로 확인한 값은 hypothesis MPL-2.0, sortedcontainers Apache-2.0이다. 둘 다 테스트 전용이라 번들에 없어 `packaging/NOTICE.txt` 고지는 필요 없다고 비고에 적었다.
  - [CI 변경 제안](ci-proposals.md) 1번(커버리지 측정)은 ci.yml에 반영되어(main 5858e59) 지웠다.
  - 린트 통과, 테스트 236개 통과, 줄·분기 커버리지 합계 93%
- 결정: D-076(hypothesis 추가, 사용자 승인 2026-11-05, 결정 로그 기록은 PR #9). CLAUDE.md 개발 의존성 목록은 이 작업 범위가 아니다.
- 남은 일:
  - PR: 이 세션의 PR 생성은 권한 검사에서 거부됐고(다른 세션 요청이라 "사용자가 요청하지 않은 작업"), 지휘 세션이 REST로 [PR #12](https://github.com/khy920723/upbit-autotrader/pull/12)를 열었다. 이 세션은 main 병합과 충돌 해결만 했다.
  - 속성 기반 테스트 작성은 3단계 이후([불변식 명세](../08-quality/invariants.md) 2.2절)
- 다음 단계: 3단계 업비트 연동

## 2026-11-05 — 기획/문서: 2차 결정 3건 반영(D-078·D-079·D-080) (클라우드 세션)

- 한 일:
  - 지휘 세션이 전달한 사용자 결정 3건(모두 추천안 A)을 반영했다. 1차 결정 PR(#10)이 이미 병합돼 최신 main에서 새 브랜치로 진행했다. 결정 로그의 세 행을 "유효"로 바꾸고 근거에 "사용자 결정(2026-11-05, 지휘 세션 전달), 제안안 그대로"를 덧붙였다.
    - D-078 418 차단 뒤 대기: 헤더 우선, 대기 늘림
    - D-079 공지로 매수 막기: 신규 매수만 막음
    - D-080 웹소켓 오류 처리: 오류 종류별 처리
  - [업비트 API 연동 명세](../05-integration/upbit-api.md) 9장을 결정 대기 목록에서 "정한 규칙"으로 바꾸고, 선택지 표는 결정 기록으로 남겼다. 2·4·5장, [기능 명세서](../03-functional/feature-spec.md) FR-04, MSG-W011, NTF-09, [요구사항 추적표](../08-quality/traceability.md) 6장 Q-04·Q-06·Q-17(해결로 표시), TS-05·TS-104·TS-106, 가짜 구현 명세의 418 항목을 확정에 맞췄다.
- 결정: D-078·D-079·D-080 유효.
- 남은 일(사용자): D-061 등 나머지 대기 결정, CLAUDE.md 두 곳(D-076·D-077) 반영 여부(이후 반영됨, 커밋 a6291fd).
- 남은 일(기획/문서): 명세 공백 Q-01, Q-02(남은 질문), Q-03, Q-05, Q-07, Q-08, Q-10~Q-16. 인프라 PR이 병합되면 불변식 명세 2.2절 문구 수정(PR #12 병합 뒤 D-081 PR에서 고침).
- 다음 단계: 3단계(업비트 연동) 구현에 D-078~D-080을 반영한다(프론트/백엔드 세션).

## 2026-11-05 — 기획/문서: 1차 결정 4건 반영(D-058·D-067·D-068·D-069) (클라우드 세션)

- 한 일:
  - 지휘 세션이 전달한 사용자 결정 4건(모두 제안안 A 그대로)을 반영했다. 결정 로그의 네 행을 "유효"로 바꾸고 근거에 "사용자 결정(2026-11-05, 지휘 세션 전달), 제안안 그대로"를 덧붙였다. 결정 내용은 바꾸지 않았다.
    - D-058: 내부 오류면 HALTED(손절 포함 자동 주문 중지, 긴급 알림)
    - D-067: 첫 매수의 예산 하한, 매수·매도 값 구분, 잔량 원가 처리
    - D-068: exit_only 실보유분 감시, 보유 코인 선택 해제 선택지
    - D-069: 정지·전량 매도 규칙 5가지
  - 네 결정을 언급하는 문서의 "제안"·"대기" 표시를 확정 표시로 바꿨다. 대상은 위험 관리 정책서, 매매 로직 명세, 상태 전이, 알림, 기능 명세서, 설정, 데이터 모델, 시스템 구성도, ADR-0008, 업비트 API 연동 명세, 불변식, 가짜 구현, PR 검토 기준이다.
  - 결정과 다르게 적힌 곳을 맞췄다. [정지]가 "미체결 취소"로만 적힌 곳은 "앱이 낸 미체결 주문 취소"로 바꿨다(요구사항 FR-13, 용어집, 사용자 시나리오 UC-07, 화면 흐름도, 화면 정의서, MSG-I009, 운영 런북, TS-32, D-069). 선택 해제의 두 선택지는 세 선택지로 바꿨다(UC-08, 화면 정의서, TS-56, D-068). TS-31에는 사용자 명령 매도의 상한 예외를 넣었다.
  - [위험 관리 정책서](../03-functional/risk-policy.md) 원칙 2의 예외에 [정지]와 함께 내부 오류 HALTED(D-058)를 더했다.
  - [요구사항 추적표](../08-quality/traceability.md) 6장: Q-09는 D-068 ④로 해결로 표시했다. Q-02는 사용자 명령 매도의 상한 예외(D-069)만 닫고, 상한 뒤 익절·LLM 부정 매도·규칙 청산 매도와 손절 매도를 주문 수에 세는지는 열어 두었다.
  - D-056 행에 D-067 ③(잔량 원가를 포지션 정리 때 손실로 계산)과의 관계를 한 줄로 적었다. D-056의 상태(유효(초안))는 바꾸지 않았다.
  - 불변식 명세 2.2절의 hypothesis 문구는 그대로 두었다. PR 직전 main에 hypothesis가 아직 없었다.
- 결정: D-058·D-067·D-068·D-069 유효.
- 남은 일(사용자): D-061(거절된 주문과 최소 주문 간격), D-078~D-080 등 나머지 대기 결정, CLAUDE.md 두 곳(D-076·D-077) 반영 여부(이후 반영됨, 커밋 a6291fd).
- 남은 일(기획/문서): 명세 공백 Q-01, Q-02(남은 질문), Q-03, Q-05, Q-07, Q-08, Q-10~Q-16. 인프라 PR이 병합되면 불변식 명세 2.2절 문구 수정(PR #12 병합 뒤 D-081 PR에서 고침).
- 다음 단계: 3단계(업비트 연동) 구현은 프론트/백엔드 세션이 이 결정들을 반영해 진행한다.

## 2026-11-05 — 기획/문서: 결정 D-075~D-077 기록, 명세 공백 Q-04·Q-06·Q-17 정리 (클라우드 세션)

- 한 일:
  - 지휘 세션이 전달한 사용자 결정 3건을 결정 로그에 "유효"로 기록했다: D-075(디스코드 알림 워크플로, 커밋 90a80aa), D-076(개발 의존성 hypothesis 추가), D-077(프론트/백엔드 하위 에이전트 구성과 난이도별 모델·노력 표). [로드맵](roadmap.md) "진행 방법"에 디스코드 알림 안내와 하위 에이전트 절을 더했다.
  - 함께 적을 사실: CI 변경 제안 1번(테스트 커버리지 표시)은 지휘 세션이 `ci.yml`에 반영했다(커밋 5858e59). [CI 변경 제안](ci-proposals.md) 정리는 인프라 세션이 한다.
  - 명세 공백 Q-04·Q-06·Q-17을 업비트 공식 문서로 다시 확인했다(rate-limits, rest-api-guide, websocket-guide, websocket-ticker·myorder·announcement, list-subscriptions, 2026-11-05). 확인한 사실은 [업비트 API 연동 명세](../05-integration/upbit-api.md) 2·4·5장과 [기능 명세서](../03-functional/feature-spec.md) FR-04에 출처와 함께 적었다.
    - 418: "응답에 포함된 차단 시간 정보"를 보라고만 하고 형식은 없다. `error.name`도 없다.
    - 공지: 종목 코드·공지 종류 필드가 없고 제목·카테고리·본문만 있으며 받지 못할 수도 있다.
    - 웹소켓 오류: 형식과 이름별 권장 조치는 있지만 연결이 끊기는지와 대기 시간은 없다. `TOO_MANY_REQUEST`는 타입별 문서에 있다.
  - 문서로 정할 수 없는 부분은 안전한 쪽 제안과 선택지·영향을 [업비트 API 연동 명세](../05-integration/upbit-api.md) 9장에 적고 결정 로그에 대기로 남겼다(D-078~D-080). [요구사항 추적표](../08-quality/traceability.md) 6장의 Q-04·Q-06·Q-17, TS-05·TS-104·TS-106, 가짜 구현 명세의 418 항목, MSG-W011(제안)과 NTF-09를 맞췄다.
- 결정: D-075·D-076·D-077(유효), D-078(418 차단 뒤 대기), D-079(공지로 매수 막기), D-080(웹소켓 오류 처리)은 대기.
- 하지 않은 것: CLAUDE.md의 개발 의존성 목록(D-076)과 "작업 방식"의 하위 에이전트 안내(D-077)는 고치지 않았다. 다른 세션의 요청만으로 CLAUDE.md를 바꾸지 않는다는 세션 규칙 때문이다. 바꿀 문안은 PR 설명에 있다. 이후 사용자 승인에 따라 지휘 세션이 PR #9 설명의 문안 그대로 반영했다(커밋 a6291fd).
- 남은 일(사용자): D-078~D-080 선택, CLAUDE.md 두 곳 반영 여부(이후 반영됨, 커밋 a6291fd), 그 밖의 1단계 대기 결정.
- 남은 일(기획/문서): 명세 공백 Q-01~Q-03, Q-05, Q-07~Q-16. 인프라 PR이 병합되면 불변식 명세 2.2절의 "아직 dev 그룹에 없다" 문구를 고친다.
- 다음 단계: D-078~D-080이 정해지면 3단계(업비트 연동) 구현에 반영한다.

## 2026-11-05 — 기획/문서: 세션 운영 규칙 기록 (클라우드 세션)

- 한 일:
  - 세션 운영 규칙(역할 4개, 단계가 바뀌어도 같은 역할 세션에 이어서 지시)을 결정 로그와 [로드맵](roadmap.md) "진행 방법"에 기록했다. 사용자 요청에는 번호가 D-039로 적혀 있었지만 D-039는 매수 방식이 이미 써서, 진행 중인 다른 세션의 PR과도 겹치지 않게 D-073으로 기록했다.
  - CLAUDE.md와 `.github/workflows/auto-merge.yml`에만 있던 `claude/` 브랜치 PR 자동 병합 규칙을 결정 로그 D-074로 옮겨 적고, 로드맵 "진행 방법"에 PR·병합 절을 더했다.
  - 로드맵 머리말("단계 하나 = 클라우드 세션 하나 = PR 하나")과 8단계의 "버그 수정 세션" 문구를 새 운영 방식에 맞췄다.
  - QA 세션이 넘긴 문서 지도 갱신: [문서 지도](../README.md)에 QA 문서 5개(요구사항 추적표, 불변식 명세, 가짜 구현 명세, PR 검토 기준, Windows 10 수동 점검표)와 ID 접두어 INV-, Q-, RC-, M-을 더했다. 규칙 비교 세션이 남긴 일(문서 지도·ADR 목록·매매 로직 명세 결정 현황에 [규칙 조건 후보 비교 리포트](../research/rule-candidates.md) 링크)도 함께 했다.
- 결정: [결정 로그](decision-log.md) D-073(세션 역할), D-074(PR 자동 병합). 둘 다 사용자가 정한 내용이라 "유효"로 적었다.
- 남은 일(기획/문서): QA 세션이 넘긴 명세 공백 Q-01~Q-17([요구사항 추적표](../08-quality/traceability.md) 6장). Q-02(주문 수 상한 뒤 매도)와 Q-09(선택 해제 시 [계속 보유])는 대기 중인 D-069·D-068 제안과 겹친다.
- 남은 일(사용자): 1단계 대기 결정, CLAUDE.md `query_hash` 문구 수정 여부.
- 다음 단계: 사용자가 지시하면 Q-01~Q-17을 정리한다. 규칙 조건을 고르면 ADR-0007을 작성한다.

## 2026-11-05 — 2단계 후속: D-064 결정 반영 (클라우드 세션)

- 한 일: 사용자 결정에 따라 [결정 로그](decision-log.md) D-064를 "유효"로 바꾸고 [의존성 라이선스 목록](../07-security-legal/dependency-licenses.md) 7장을 고쳤다. 코드와 의존성 변경은 없다
- 결정: D-064 PySide6 메타 패키지(`PySide6==6.12.0`) 유지. Essentials 전환은 빌드 환경 설치 크기만 줄이고, 배포 번들은 import한 모듈만 묶고 GPL 전용 파일은 D-062의 훅·빌드 검사가 막아 크기·라이선스가 같다
- 남은 일(사용자): 2단계 항목의 Windows 10 확인, CI 변경 제안 1번 반영(D-064는 해결됨)
- 다음 단계: 3단계 업비트 연동

## 2026-11-05 — 1단계: 규칙 조건 후보 비교 (클라우드 세션)

- 한 일: [규칙 조건 후보 비교 리포트](../research/rule-candidates.md) 작성(추천 없음, 수익률 미기재)
  - 데이터: 업비트 공개 캔들(KRW-BTC·ETH·XRP, 240분봉·일봉, 2024-11-05~2026-11-05 UTC)을 받아 `research/data/`에 캐시(커밋 안 함). 요청 79회, 1초 최대 2회, Origin 헤더 없음, 빈 캔들 0개
  - 비교 대상: 후보 4개(종가 > SMA20, SMA20 > SMA60, RSI14 < 70, 거래량 > 직전 20봉 평균)와 AND 조합 15개
  - 지표: 참 비율, 전환 빈도, 참 구간 길이
  - 시뮬레이션: "규칙만 참이면 진입"(손절 5%, 수수료 0.05%, 슬리피지 0.1%)을 손절만(A)과 손절 + 규칙 거짓 시 청산(B) 두 가지로 돌림. 거래 수, 최대 낙폭, 보유 시간 분포, 운영 한도 접근, 민감도, 과최적화 경고를 정리
  - 스크립트: `research/rules/`(PEP 723, 표준 라이브러리, `uv run`, 오프라인 테스트 59개)
  - 검증: 독립 에이전트가 세 관점(시점·시뮬레이션, 지표·통계, 데이터·API·CI)으로 코드를 리뷰하고 지적마다 반박 검증을 거쳤다. 별도 구현으로 재계산한 결과 조건 통계 366건과 시뮬레이션 216건(거래 기록 포함)이 모두 일치했다
  - 리뷰 반영: 낙폭 단위를 "예산 대비"로 명시하고 같은 단위의 단순 보유 낙폭을 추가했다. 보유 시간 통계는 끝난 거래만으로 내고 미청산은 따로 적었다. 레이트 리미터 슬롯은 요청이 끝난 시각부터 세고, 캐시 판정은 CSV 내용까지 대조한다. 갭 손절 보유 계산, `--end` 시간대 처리, pytest 설정 격리도 고쳤다
  - 재현성: 같은 범위를 다시 받아 CSV 6개가 바이트 단위로 같음을 확인했다
  - 최종 리포트 검증: 에이전트 2개가 본문 수치를 결과 파일과 대조하고, 추천 표현과 정의·한계 서술을 점검했다. 지적을 반영해 문장을 고쳤다
- 결정: [결정 로그](decision-log.md) D-072 규칙 조건 비교 완료, 사용자 선택 대기(main 병합 때 D-038이 이미 쓰여 있어 번호를 옮김)
- 남은 일(사용자): 리포트 9장의 항목 선택(규칙 조합, 지표 캔들 단위, 규칙상 청산 조건, 파라미터, 시그널 유효 시간)과 일일 손실 한도의 "실현 손실 합계" 정의(순손익 또는 손실 합) 확인
- 남은 일(세션): 사용자가 고르면 ADR-0007(규칙 조건)을 쓰고 매매 로직 명세, 설정 항목(rules, exit)에 반영. [문서 지도](../README.md)와 ADR 목록에 리포트 링크 추가
- 다음 단계: 1단계 설계 계속

## 2026-11-05 — QA: 검증 기반 (클라우드 세션)

- 한 일:
  - [요구사항 추적표](../08-quality/traceability.md): FR-01~FR-26, NFR-01~NFR-12를 설계 문서, 테스트 시나리오, 불변식, 로드맵 단계와 연결했다. 보완 전 판정은 충분 5개, 빠짐 6개(FR-09, FR-18, FR-24, FR-26, NFR-07, NFR-11), 나머지는 일부. 요구사항 문장이 없는 테스트 7개(TS-15, TS-16, TS-73, TS-74, TS-75, TS-77, TS-116)를 찾았고, 명세 공백 17개(Q-01~Q-17)를 정리했다.
  - [테스트 시나리오](../08-quality/test-scenarios.md)에 빈 곳을 메우는 TS-98~TS-145(48개)를 추가했다. 작업 중에 [1단계 설계 PR](https://github.com/khy920723/upbit-autotrader/pull/2)과 그 후속이 TS-60~TS-97을 써서 병합됐으므로 TS-98부터 붙였다.
  - [불변식 명세](../08-quality/invariants.md): INV-01~INV-19(위험 한도 초과 주문 0건, STOPPED·SUSPENDED·HALTED에서 주문 0건, identifier 재전송 없음, 결과 불명 중 같은 코인 새 주문 없음, 같은 코인 매수·매도 동시 주문 없음, 비밀 없음 등)와 각각을 단위·속성 기반(hypothesis)·통합·구조 검사 중 어떤 테스트로 증명할지 정했다.
  - [가짜 구현 명세](../08-quality/fakes-spec.md): FakeExchange, FakeLLM, FakeNews, FakeClock, FakeNotifier의 응답 형식, 오류 이름, 주입 기능, 엄격 모드 검사, 비밀 검사(카나리아)를 정했다. 업비트 개발자 센터 35쪽과 Gemini API 문서 8쪽을 받아 대조했다. 텔레그램·네이버 문서는 네트워크 정책으로 막혀 검색 요약으로만 확인했다.
  - [녹화 응답](../../tests/fixtures/upbit/README.md): 업비트 공개 시세 API로 market/all(875개 중 8개 항목), 240분봉·일봉 5개, ticker 3개, orderbook, 오류 2개를 받아 저장했다(초당 1회, Origin 없음, 끝 슬래시 없음, 키 없음).
  - [Windows 10 수동 점검표](../08-quality/manual-checklist-windows10.md)(M-01~M-35), [PR 검토 기준](../08-quality/review-checklist.md)(RC-A~RC-E: 공통·문서·인프라·기능·테스트, 결과 작성 형식), [테스트 전략](../08-quality/test-strategy.md)에 새 문서 연결과 속성 기반 테스트 수준을 추가했다.
- 확인한 사실(공식 문서와 녹화): 캔들 응답의 `Remaining-Req` 그룹은 `candles`다(문서 표는 `candle`, main에 이미 반영). ticker에 없는 마켓이 하나라도 섞이면 있는 마켓까지 전체가 404다. 웹소켓 ticker의 `is_trading_suspended`, `market_warning`은 폐기다(main에 이미 반영). 취소 API 예시에 `QUERY_PARAMETER_NOT_SUPPORTED`, `bad_request`가 있다. 418·429 본문 형식과 2026-11-16 경로 오류 형식은 문서에 없다. 시세 REST 숫자 표기가 섞여 있어 Decimal로 읽어야 한다.
- 결정: 없음(결정 로그를 바꾸지 않았다). 제안: NFR-13(외부 API 계약 준수)·NFR-14(데이터 정확성·보존) 추가(Q-11), dev 그룹에 hypothesis 추가.
- 남은 일(기획·문서 세션): 문서 지도에 새 문서 5개와 ID 접두어(INV-, Q-, M-, RC-) 추가, Q-01~Q-17 결정, 업비트 API 연동 명세에 확인한 사실 반영(섞인 마켓 ticker 404, 취소 API 오류 이름), 사용자 승인 뒤 NFR-13·NFR-14 추가, CLAUDE.md dev 그룹 목록에 hypothesis 추가.
- 남은 일(인프라 세션): dev 그룹에 hypothesis 추가, `.gitignore`에 `.hypothesis/` 추가, 느린 테스트 마커 등록.
- 남은 일(개발 세션, 3~7단계): 가짜 구현 명세대로 가짜 구현, 테스트 docstring에 TS·INV ID 적기.
- 남은 일(사용자): 2단계 빌드 뒤 수동 점검표 0~2절 실행, Q-11 승인 여부 결정.
- 참고: 작업 중에 1단계 설계, 2단계 뼈대, 1단계 후속, 라이선스 후속이 main에 병합됐다. main을 두 번 병합하고 QA 문서를 병합본(D-055·D-058·D-059·D-061·D-065~D-071, TS-80~TS-97, NTF-21~NTF-23, 요청 한도 버킷의 경로별 표)에 맞췄다. 독립 검토 1회(지적 23건)를 반영했다: 승인 금액 식, 웹소켓 `TOO_MANY_REQUEST`(처음에 없다고 잘못 적음), identifier 겹침 시험 방법, 체크리스트 A의 주문 검증 예외, 대조 범위, 수동 점검 절차(시계 변경, IP 확인) 등.
- 다음 단계: 열린 PR(규칙 조건 후보 비교 리포트)과 이후 PR을 PR 검토 기준으로 검토.

## 2026-11-05 — 1단계 후속: 설계 검토 반영 (클라우드 세션)

- 한 일:
  - 1단계 PR([#2](https://github.com/khy920723/upbit-autotrader/pull/2))은 외부 출처 대조 검토 반영분까지 자동 병합됐다. 그 뒤에 끝난 검토 2건(범위·문체 15건, 안전·논리 21건)을 근거와 대조해 반영하고 최신 main 위에서 새 PR로 올린다.
  - 범위·문체: 결정 로그 머리말에 "대기"와 "유효(초안)"의 기준을 적고 D-052(단일 인스턴스)·D-061(거절된 주문과 최소 주문 간격)을 대기로, D-055를 D-054 전제로 바꿨다. 규칙 인터페이스를 ADR-0007 가안으로 표시했다. 상태 줄·비유 표현·설정 숫자 형식·Gemini 429 연속 판정 기준을 정리하고, 앱 구성도와 상태 전이도를 Mermaid 10·11에서 렌더링되게 고쳤다.
  - 안전·논리: 첫 매수의 예산 하한 검사, exit_only 실보유분 감시, 정지·전량 매도 규칙을 대기 결정으로 올렸다. `duplicated_identifier` 처리, 최종 상태 유지, REST로 체결 복구, 코인별 주문 직렬화, 체결 1건 반영 = 한 트랜잭션, 숫자 파싱, JOB-02 완료 감시, 마이그레이션 외래 키, 인정일 분 상한을 문서에 넣었다. MSG-E014·E019, NTF-16·21·23, 이벤트 코드 4개, TS-84~TS-97을 추가했다.
  - 소스로 확인: Qt 6.12 QLockFile·QLocalServer(태그 소스), ccxt 4.5.92의 업비트 `create_order`가 `smp_type`을 요청에서 빼는 것, PyInstaller 6.22.3의 메타데이터 자동 수집, SQLite가 트랜잭션 안의 `PRAGMA foreign_keys` 변경을 무시하는 것(sqlite 3.53.1).
- 결정: [결정 로그](decision-log.md) D-066~D-071. 다른 세션이 D-062~D-065를 먼저 써서 이 세션의 새 결정은 D-066부터다.
  - 1단계 관련 사용자 결정 대기(안전·위험 관리에 영향): D-058(내부 오류 때 HALTED, 손절도 멈춤), D-061(거절된 주문과 최소 주문 간격), D-067(첫 매수의 예산 하한, 잔량 원가), D-068(exit_only 실보유분 감시, 보유 코인 선택 해제), D-069(정지·전량 매도 규칙), D-059(키 없는 paper의 주문 정보 추정값), D-060(core 정지 비상 알림), D-048(체크리스트 A 확인 방법), D-049(live-validate 일수)
  - 1단계 관련 사용자 결정 대기(기술·구성): D-038(업비트 클라이언트), D-039(매수 방식), D-040(GUI–asyncio), D-041(DB 접근), D-042(설정 파일 형식), D-043(주문 유형), D-044(실행 모드 저장 위치), D-045(시그널 유효 시간), D-051(공인 IP 확인), D-052(단일 인스턴스), D-054(Gemini 호출 API), D-057(평가 시각 정렬, ADR-0007과 함께), D-066(1단계에서 하지 않은 항목의 시점). D-021(규칙 조건)은 별도 세션.
  - 기술 기본값(유효(초안), 사용자가 확인하면 유효): D-046, D-047, D-053, D-055(D-054 승인 전제), D-056, D-070(주문·체결 처리 세부), D-071(운영 견고성).
- 확인하지 못한 것(확인 필요): 서브포켓 키로 `GET /v1/api_keys`를 부를 때 나오는 목록 범위, 서브포켓을 만드는 화면 위치, 배열 이름의 대괄호를 인코딩하지 않은 요청을 서버가 받는지(REST 안내와 공식 SDK가 다름), SMP가 포켓 사이에도 적용되는지, Interactions 응답의 `model`이 실제 응답 모델인지, ipify·checkip 이용 조건, Microsoft Learn `AllowSetForegroundWindow` 본문, Windows에서 monotonic 시계가 잠자기 시간을 포함하는지(D-071은 포함 여부와 상관없게 정함).
- 남은 일(사용자):
  - 대기 항목 결정. 특히 D-058은 "손절·청산은 막지 않는다" 원칙의 예외라 따로 확인한다.
  - CLAUDE.md "업비트 API 주의"의 `query_hash` 문구("실제 전송 문자열의 SHA512")를 "URL 인코딩 전 쿼리 문자열의 SHA512(전송할 때만 값을 인코딩)"로 고칠지 확인한다. 공식 인증 문서와 공식 SDK가 인코딩 전 문자열로 해시한다.
  - ADR-0007 규칙 조건 선택.

남은 일(1단계 범위 중 하지 않음, 시점 제안 D-066 대기):

| 항목 | 이번에 하지 않은 이유 | 제안 시점 |
|---|---|---|
| 추천 기본 모델 ID | 1단계 세션 요청 범위 밖. 모델 넘김 일정(2026-12-01 등)이 가까워 그때 다시 확인해야 한다 | 4단계 시작 전 |
| 지표 요약 항목 | 규칙 조건(ADR-0007)에 달려 있다 | ADR-0007 확정 뒤, 4단계 시작 전 |
| 프롬프트 첫 버전 | 지표 요약 항목에 달려 있다 | 4단계 시작 전 |
| `llm.max_output_tokens` 값 | 응답 스키마와 사고 수준을 정한 뒤 실제 응답 길이를 재야 한다 | 4단계 |
| RSS에서 티커가 일반 단어와 겹칠 때의 처리 | 1단계 세션 요청 범위 밖. 뉴스 수집 구현과 함께 정한다 | 4단계 시작 전 |
| 진단 묶음 범위 | 로그·감사 기록 정의서가 7단계 전에 정한다고 적었다 | 7단계 시작 전 |

- 다음 단계: 대기 결정 반영 뒤 3단계(업비트 연동). D-067~D-070은 3·5단계 구현 범위(주문 관리, 재조정, 저장)에 들어간다.

## 2026-11-05 — 2단계: 뼈대 + 빌드 검증 (클라우드 세션)

- 한 일: uv 프로젝트(`pyproject.toml`, `uv.lock`, `.python-version` 3.13, 런타임 `PySide6==6.12.0`·`keyring==25.7.0`), `src/autotrader/` 7개 하위 패키지와 `__main__.py`, 빈 메인 창, 런타임 경로(`%LOCALAPPDATA%\upbit-autotrader\` 아래 data·logs·backup)·KST 로그(10MB×10 회전)·SQLite(`data\autotrader.db`, 데이터 모델의 `schema_migrations` 표만 STRICT로, `PRAGMA user_version` 0, WAL) 초기화, `--self-test`(import, Qt offscreen, keyring, SQLite 3.37.0 이상·WAL, TLS, 설정 경로 → `self-test-report.txt`, 0/1 종료), `packaging/autotrader.spec`(onedir·windowed·UPX 끔, `packaging/launcher.py` 진입), [의존성 라이선스 목록](../07-security-legal/dependency-licenses.md)과 `uv.lock` 대조 스크립트, 번들 고지(exe 옆 `NOTICE.txt`, `_internal/licenses/`). 테스트 220개(구조 규칙, spec 계약, 고정 버전, 라이선스 표 포함). Linux에서 같은 spec으로 빌드해 frozen self-test 확인. [PR #1](https://github.com/khy920723/upbit-autotrader/pull/1)에서 ci·build-exe 통과(Windows self-test 6/6, WinVaultKeyring)
- 발견·조치: PySide6 메타 패키지가 Addons까지 설치하면 PyInstaller가 GPL-3.0 전용 Qt Virtual Keyboard 플러그인을 번들에 넣는다 → 사용자 훅으로 빼고, GPL 전용 Qt 바이너리가 남으면 빌드를 멈춘다. PyInstaller가 setuptools·packaging·typing_extensions(개발 전용)까지 넣던 것을 빼고, 런타임 의존성 밖 패키지가 들어가면 빌드를 멈춘다. `ruff format`이 Markdown 코드 블록도 고쳐서 ruff 대상에서 docs를 뺐다. 독립 검토(4개 관점) 지적을 반영했다. 1단계 PR 병합 뒤 DB 초기화를 데이터 모델(`schema_migrations`, `user_version`, STRICT)에 맞췄다
- 결정: [결정 로그](decision-log.md) D-062(GPL 전용 Qt 모듈 금지·빌드 차단), D-063(번들 고지와 개발 전용 패키지 제외), D-064(PySide6 메타 패키지 유지 또는 Essentials만, 대기), D-065(self-test 구현 규칙). 그 밖의 구현 선택: 빌드 백엔드 uv_build, 개발용 비Windows 경로(XDG, macOS Application Support)
- 후속(라이선스 검토 반영, 별도 PR): 번들에서 `opengl32sw.dll`(Mesa)과 QtNetwork 제외, Windows 빌드에서 Python·패키지 밖 DLL(PATH의 OpenSSL 등) 차단, PySide6·shiboken6의 Python 부분을 `.py`로 두어 교체 가능하게(LGPL 4(d)(1)), GPL 검사에 Qt Designer 추가·Qt 3D QML 플러그인 오탐 제거, NOTICE.txt에 앱 소스 위치, 라이선스 표 검사가 uv.lock fork를 거부
- 남은 일(사용자): Windows 10 PC에서 빈 앱 실행과 self-test 확인([설치 가이드](../09-operations/install-guide.md) "자가 점검"). 병합 전에는 Actions → build-exe → Run workflow에서 브랜치 `claude/stage-2-skeleton`을 골라야 zip이 생긴다. [CI 변경 제안](ci-proposals.md) 1번 반영, D-064(PySide6-Essentials 전환) 결정
- 남은 일(다음 단계): 마이그레이션 파일(`storage/migrations/0001_initial.sql`)과 적용 절차, `settings.json`(D-041·D-042 결정 뒤)
- 다음 단계: 3단계 업비트 연동(ADR-0006, D-038 결정 뒤)

## 2026-11-05 — 1단계: 설계 (클라우드 세션)

- 한 일:
  - ADR 3건을 "제안" 상태로 작성: [ADR-0006](../06-architecture/adr/0006-upbit-client.md) 업비트 클라이언트(httpx 기반 자체 클라이언트 추천), [ADR-0008](../06-architecture/adr/0008-buy-method.md) 매수 방식(기본 한 번에, 분할은 회차 금액이 예산 하한 이상일 때만), [ADR-0009](../06-architecture/adr/0009-gui-asyncio-bridge.md) GUI와 asyncio 연결(전용 스레드의 표준 asyncio 루프). ADR-0007(규칙 조건)은 별도 세션의 비교 리포트를 기다리며 만들지 않았다.
  - "1단계 보완" 문서를 채웠다: [매매 로직 명세](../03-functional/trading-logic.md)(시그널 유효 시간, 주문 유형, identifier·금액 규칙, 결과 불명 확인 일정, 업비트 state 대응표, 재조정, 손익 계산, 이유 코드), [데이터 모델](../04-data/data-model.md)(18개 테이블, 인덱스, 마이그레이션, 크기 추정), [시스템 구성도](../06-architecture/system-architecture.md)(스레드 모델, 인터페이스 시그니처, 오류 타입, 단일 인스턴스, 공인 IP), [설정 항목 정의서](../03-functional/settings.md)(JSON 형식 제안, `buy.*`, 실행 모드 DB 저장).
  - 공식 문서로 확인했다. 사용자가 업비트·Google 문서 도메인을 허용한 뒤 docs.upbit.com(141쪽, 각 쪽의 `.md`)과 aistudio.google.com 문서를 받아 읽었다: 업비트 키 만료일 API(`GET /v1/api_keys`의 `expire_at`), 포켓별 키 발급(메인포켓 10개·서브포켓 5개, 서브포켓 키 권한, 포켓별 키 정보는 포켓관리 권한이 있는 메인포켓 키만 조회), Gemini 429의 분당·일일 구분(Interactions API 오류 코드), upbit-sdk의 PyInstaller 호환 위험(휠 정적 분석). 그 밖에 업비트 요청 한도 그룹, 공식 오류 이름 목록, 주문 유형·SMP·identifier 규칙, 웹소켓 유지 규칙, 4시간봉 경계, google-genai 2.34.0 재시도 기본값, PySide6 6.12 QtAsyncio 미구현 범위, qasync 동작을 확인했다.
  - 연관 문서를 고쳤다: 업비트 API 연동 명세, LLM 시그널 명세, 기능 명세서(FR-02·FR-20·FR-21·FR-23, JOB-08), 상태 전이 정의서, 위험 관리 정책서(체크리스트 A 확인 방법, live-validate 일수), 메시지(MSG-E015~E018), 알림(NTF-21·NTF-22), 테스트 시나리오(TS-60~TS-83), 로그·감사 기록(이벤트 코드, 크기 추정), 리스크 대장(RSK-16 상태 오기 수정, RSK-23~RSK-26), 설치 가이드, 화면 정의서(SCR-08), 페이퍼 운영 평가 기준, 법·약관 검토, 기술 스택, ADR 목록, 로드맵 검증 사실표, 문서 지도.
- 결정: [결정 로그](decision-log.md) D-038~D-061.
  - 사용자 결정 대기: D-038(업비트 클라이언트), D-039(매수 방식), D-040(GUI–asyncio), D-041(DB 접근), D-042(설정 파일 형식), D-043(주문 유형), D-044(실행 모드 저장 위치), D-045(시그널 유효 시간), D-048(체크리스트 A 확인 방법), D-049(live-validate 일수), D-051(공인 IP 확인), D-054(Gemini 호출 API), D-057(평가 시각 정렬, ADR-0007과 함께), D-058(내부 오류 때 HALTED, 손절도 멈춤), D-059(키 없는 paper의 주문 정보 추정값), D-060(core 정지 비상 알림). D-021(규칙 조건)은 별도 세션.
  - 기술 기본값(유효(초안)): D-046(결과 불명 확인), D-047(state 대응표·SMP·identifier), D-052(단일 인스턴스), D-053(재조정), D-055(Gemini 429·재시도), D-056(손익 계산), D-061(거절된 주문과 최소 주문 간격). D-052·D-061은 후속 작업에서 대기로 바꿨다(위 기록). 사실 확인 반영(유효): D-050(키 만료일).
- 확인하지 못한 것(확인 필요): 서브포켓 키로 `GET /v1/api_keys`를 부를 때 나오는 목록 범위, 서브포켓을 만드는 화면 위치, Interactions 응답의 `model`이 실제 응답 모델인지, ipify·checkip 이용 조건, Microsoft Learn 문서 본문(이 세션 네트워크 정책에서 막힘. Python·Qt 문서는 태그 소스로 확인), Windows에서의 PyInstaller 빌드 결과.
- 남은 일(사용자): PR의 대기 항목 결정, ADR-0007 규칙 조건 선택, Gemini 추가 약관의 "소비자용 아님" 문장 확인, 공인 IP 조회 서비스 이용 조건 확인.
- 남은 일(1단계 범위 중 이번에 하지 않음): 추천 기본 모델 ID, 지표 요약 항목(ADR-0007과 함께), 프롬프트 첫 버전, `llm.max_output_tokens` 값, 진단 묶음 범위, RSS에서 티커가 일반 단어와 겹칠 때의 처리([뉴스 수집 명세](../05-integration/news-collection.md) 3장).
- 다음 단계: 결정 반영 후 2단계(뼈대 + 빌드 검증). 2단계 세션이 같은 시기에 설정·SQLite 초기화를 만들고 있으므로 D-041·D-042·D-044 결정과 맞춘다.

## 2026-11-03 — 기획 문서 작성 (로컬 세션)

- 한 일: `docs/`를 10개 분류 폴더로 재구성하고 기획 문서를 작성([문서 지도](../README.md)). 기존 SPEC·PLAN·PROGRESS·ci-proposals를 해당 폴더로 이동(요구사항 정의서, 로드맵, 진행 기록, CI 변경 제안). `LICENSE`(MIT) 추가, `CLAUDE.md`와 README 경로 갱신. 검토 에이전트 1회 검토(지적 38건)를 반영해 상태 정의(DEGRADED 추가, 상태 복원 규칙), 실전 전환 2단계 체크리스트, 주문 결과 불명 처리, 알림 문구 ID, 테스트 시나리오(59개)를 보강
- 결정: [결정 로그](decision-log.md) D-016~D-037 (D-032 실전 점검 3일 강제 확정, D-033 자동 로그인은 지금 계정 그대로 + 화면 잠금 필수)
- 남은 일(사용자): Claude GitHub App 설치, 클라우드 환경 생성(로드맵 "사용자 작업"), 집 IP 고정 여부 확인, 네이버 검색 API 약관 확인(4단계 전), 업비트 Open API 약관 확인(9단계 전)
- 다음 단계: 1단계 설계

## 2026-11-03 — 0단계: 준비 (로컬 세션)

- 한 일: 공개 저장소 생성, README·CLAUDE.md·SPEC·PLAN·PROGRESS 작성, CI 워크플로(`ci.yml`, `build-exe.yml`), 클라우드 세션 시작 훅
- 결정: 업비트 KRW 최대 3코인, Python 3.13 + PySide6 6.12, Gemini 무료 등급 시그널 + 규칙 확인, 네이버·RSS 뉴스, paper 기본
- 남은 일(사용자): Claude GitHub App 설치, 클라우드 환경 생성(당시 PLAN.md, 지금은 로드맵의 "사용자 작업"), 집 IP 고정 여부·PC 종류·자동 로그인 결정, 라이선스 결정
- 다음 단계: 1단계 설계
