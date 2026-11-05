# ADR-0006 업비트 클라이언트: httpx 기반 자체 클라이언트

상태: 확정 · 2026-11-05 · 사용자 결정(D-038, 추천안 A 그대로)

## 맥락

- 앱이 쓰는 업비트 API는 REST 16개와 웹소켓 2개(공개 ticker, 비공개 myOrder·myAsset·announcement)다([업비트 API 연동 명세](../../05-integration/upbit-api.md) 2장).
- 주문 안전 규칙이 엄격하다([매매 로직 명세](../../03-functional/trading-logic.md) 7~9장, [업비트 API 연동 명세](../../05-integration/upbit-api.md) 3~6장).
  - 주문: identifier를 먼저 저장하고 전송한다. **주문 생성은 자동으로 다시 보내지 않는다.** 타임아웃이면 identifier 조회로만 확인한다. `smp_type`은 항상 명시한다.
  - 요청 형식: 같은 헤더 두 번 금지, `Origin` 금지, 경로 슬래시 규칙.
  - 응답 처리: `error.name`으로 분기하고, `Remaining-Req`의 `sec`으로 그룹별 한도의 절반만 쓴다.
- 런타임 의존성은 정확한 버전으로 고정하고, PyInstaller onedir로 Windows에서 묶는다(ADR-0001, ADR-0004).
- 클라이언트 후보: 공식 `upbit-sdk`, httpx 기반 자체 클라이언트, ccxt, pyupbit(유지보수 중단으로 제외).

## 결정

결정: **httpx(REST) + websockets(웹소켓) + PyJWT(서명)로 얇은 자체 클라이언트를 만든다. 공식 `upbit-sdk`는 의존성으로 넣지 않고, 필드 이름·타입·엔드포인트를 대조하는 자료로 쓴다.**

- 자체 클라이언트는 [시스템 구성도](../system-architecture.md) 6장의 `QuotationApi`, `ExchangeApi`, `PublicStream`, `PrivateStream` 인터페이스를 구현한다.
- 지킬 것:
  - 재시도: 자동 재시도 없음. 조회 재시도는 호출하는 쪽이 정한다([매매 로직 명세](../../03-functional/trading-logic.md) 8·9장).
  - 서명: HS512, 매 요청 새 nonce. `query_hash`는 파라미터 순서를 유지한 URL 인코딩 전 문자열(`uuids[]=a&uuids[]=b`, `pairs=KRW-BTC,KRW-ETH`)의 SHA512로 계산하고, 전송할 때만 값을 URL 인코딩한다(배열 이름의 `[]`는 인코딩하지 않음, [업비트 API 연동 명세](../../05-integration/upbit-api.md) 3장).
  - 헤더·URL: `Authorization`·`Content-Type`(POST만)·`Accept`·`User-Agent`를 한 번씩 보내고 `Origin`은 보내지 않는다. 기본 URL `https://api.upbit.com` + `/v1/...`, 리다이렉트를 따라가지 않는다.
  - 한도·오류: 응답마다 `Remaining-Req`를 파싱한다([업비트 API 연동 명세](../../05-integration/upbit-api.md) 4장). 오류는 `error.name`으로 [시스템 구성도](../system-architecture.md) 7장 오류 타입에 매핑한다.
  - 웹소켓: 정상 종료 코드로 끊겨도 앱의 감시 루프가 지수 백오프로 다시 연결하고, 다시 연결한 뒤 REST로 대조한다.
- 테스트: JWT·`query_hash` 알려진 값(TS-16), 보내는 헤더와 URL(TS-15), 자동 재시도 없음(TS-72), httpx `MockTransport`와 공식 문서 예시로 만든 녹화 응답.
- 공식 SDK를 다시 검토할 조건: (1) 주문 생성의 자동 재시도를 기본으로 끄거나 요청별로 안전하게 끌 수 있고, (2) aiohttp가 선택 의존성이 되고, (3) websockets 상한이 풀리고, (4) SDK 라이선스 관계가 분명해지면.
- 절충안: SDK를 `ExchangeApi` 뒤의 어댑터로만 쓰는 방법도 있다(`max_retries=0`, 앱의 한도 조절기, 앱의 웹소켓 감시 루프, 쓰는 메서드만 허용). 서명·쿼리 해시·응답 모델을 업비트가 유지보수하는 이점은 있지만, 위 의존성·라이선스 문제는 그대로다.

## 검토한 대안

| 대안 | 장점 | 단점 | 판단 |
|---|---|---|---|
| **A. httpx 기반 자체 클라이언트** | 요청·재시도·헤더·서명·한도 처리를 완전히 통제한다. 의존성이 작다(httpx, websockets, PyJWT). 가짜 거래소·녹화 응답으로 테스트하기 쉽다. 업비트 규칙 변경(헤더, 경로, SMP)을 바로 반영할 수 있다 | 엔드포인트 16개와 웹소켓 2개를 직접 짜고 유지보수한다. 응답 모델(필드)을 직접 정의한다 | **채택** |
| B. 공식 `upbit-sdk` 1.1.0 | 업비트가 관리한다. 모든 요청·응답 타입이 있고 숫자를 문자열로 받는다. 동기·비동기와 웹소켓을 지원한다. 포켓 API, 기술적 지표 웹소켓 같은 새 기능이 빨리 들어온다 | 아래 "확인한 사실"의 기본 동작(POST 자동 재시도, 429 즉시 재시도, 웹소켓 재연결 방식)이 이 앱의 주문 안전 규칙과 맞지 않아 끄거나 감싸야 한다. 요청 한도 조절은 어차피 앱이 만들어야 한다. 첫 배포가 2026-04로 이력이 짧다(배포 3번). aiohttp 계열을 항상 끌어와 묶음이 커진다. websockets를 16 미만으로 묶는다. 별도 "업비트 개발자 SDK 라이센스"와의 관계가 불분명하다 | 기각(재검토 조건은 위) |
| C. ccxt 4.5.92(2026-11-04, 최신) | 여러 거래소를 같은 방식으로 다룬다. 업비트 포켓 API도 들어 있다 | 업비트 `create_order`는 `smp_type`을 받아도 요청에서 빼고 보낸다(코드에서 주석 처리하고 인자에서 제거). 그래서 "`smp_type` 항상 명시"를 지키려면 저수준 메서드를 직접 불러야 한다. 서명은 HS256이다. 요청 한도는 ccxt 자체 간격 설정(`rateLimit` 50ms와 경로별 비용)으로 조절한다. 의존성이 크다(휠 6.8MB, aiohttp·cryptography·coincurve 등). 이 앱은 거래소가 하나라 공통 인터페이스의 이점이 없다 | 기각 |
| D. pyupbit | - | 2024-06 이후 유지보수 중단 | 제외(CLAUDE.md) |

## 확인한 사실 (2026-11-05, upbit-sdk 1.1.0 휠·공식 저장소와 ccxt 4.5.92 휠 정적 분석)

휠과 저장소 태그 v1.1.0의 소스는 같다(diff 차이 없음). 아래 근거 파일은 따로 적지 않으면 `upbit/` 기준이다.

| 항목 | 내용 | 근거 |
|---|---|---|
| 배포 이력·라이선스 | 0.9.0(2026-04-14), 1.0.0(2026-09-01, 포켓 API), 1.1.0(2026-10-20, 공지·지표 웹소켓). Apache-2.0, NOTICE 파일 없음. Python ≥3.9. 공개 저장소에는 릴리스마다 커밋 1개씩(총 3개)만 있고 CI 설정이 없다. API 리소스 테스트 362개 중 358개가 건너뛰도록 표시돼 있다 | PyPI 메타데이터, 저장소 git 이력, `tests/api_resources/` |
| 생성 방식 | Stainless로 생성한 SDK에 JWT·웹소켓 코드를 덧붙인 구조로 보인다(`X-Stainless-Raw-Response` 상수, `x-should-retry` 처리) | `_constants.py`, `_base_client.py` |
| 자동 재시도 | 기본 `max_retries=2`(최대 3회 전송). 타임아웃, 연결 오류(요청이 이미 서버에 닿았을 수 있는 경우 포함), 408·409·429·5xx에서 **POST를 포함한 모든 메서드**를 다시 보낸다. 418은 다시 보내지 않는다. 다시 보낼 때마다 새 nonce로 JWT를 만들고 멱등성 헤더는 보내지 않는다. 대기는 약 0.4~0.5초, 0.75~1초 | `_constants.py`, `_base_client.py`(`_should_retry`, 요청 루프), `resources/orders.py` |
| 이 동작의 위험 | 주문 생성이 응답 없이 끝났을 때 자동으로 다시 나간다. identifier를 넣었으면 두 번째 요청이 `duplicated_identifier`가 되어 앱이 "실패"로 오인할 수 있고, identifier가 없으면 중복 주문이 될 수 있다. 429를 1초 안에 다시 보내 "그룹 호출을 멈추라"는 업비트 지침과 맞지 않고 418로 이어질 수 있다. `max_retries=0`(클라이언트 전체 또는 `with_options` 사본)으로 끌 수 있지만, 리소스 메서드에는 요청별 재시도 인자가 없다 | 위 동작 + 업비트 identifier·요청 한도 문서(추론 포함) |
| 기본 타임아웃 | 60초(연결 5초). 재시도까지 합치면 최악 약 3분 | `_constants.py` |
| 서명 | JWT를 HS256으로 서명한다. 업비트 문서는 HS512를 권장(필수 아님)하고, 공식 웹소켓 예시도 PyJWT 기본값(HS256)을 쓴다. nonce는 요청마다 uuid4 | `lib/jwt_auth.py`, 업비트 인증 문서 |
| 쿼리 해시와 전송 문자열 | 해시는 URL 디코딩한 쿼리 문자열(`uuids[]=a&uuids[]=b`)로 계산해 문서와 같다. 그러나 실제 전송은 대괄호를 `%5B%5D`로 인코딩한다. 업비트 REST 안내는 배열 이름의 `[`, `]`를 인코딩하지 않는다고 적고 있어 두 공식 출처가 다르다. 서버가 둘 다 받는지는 키가 없어 확인하지 못했다(확인 필요) | `_qs.py`, `_base_client.py`, httpx 0.28.1, 업비트 REST 안내 |
| 기본 헤더 | `Accept`, `User-Agent`(예: `AsyncUpbit/Python 1.1.0`), `X-Upbit-Client-Type`·`Name`·`Version`, `X-Upbit-Runtime`·`Runtime-Version`, `Content-Type: application/json`(GET에서는 뺌, POST·DELETE는 보냄). `X-Stainless-OS` 같은 플랫폼 헤더는 정의만 있고 보내지 않는다. `with_raw_response`를 쓰면 `X-Stainless-Raw-Response` 헤더가 실제로 나간다. `Origin`은 없다. 기본 사용에서는 헤더가 이름마다 1개지만, 앱이 기본 헤더를 다른 대소문자로 또 넣으면 2개가 나갈 수 있다 | `_base_client.py`, `_client.py`, SDK 테스트 |
| 경로 | `https://api.upbit.com/` + `v1/...`로 붙여 슬래시가 겹치지 않는다(2026-11-16 규칙에 맞음). 기본 `follow_redirects=True` | `_base_client.py` |
| 환경 변수 | `UPBIT_BASE_URL`, `UPBIT_ACCESS_KEY`, `UPBIT_SECRET_KEY`(인자가 없을 때), `UPBIT_LOG`(값에 따라 루트 로거 설정)를 읽는다 | `_client.py`, `_utils/_logs.py` |
| smp_type | 선택 항목이고 기본값이 없다. 1.1.0의 값 목록에는 2026-11-09에 추가되는 `none`이 없다 | `types/order_create_params.py`, `types/smp_type_enum.py` |
| 숫자 | REST·웹소켓 모두 소수를 문자열로 받아(`parse_float=str`) 정밀도를 지킨다. 요청 본문에 `Decimal`을 넣으면 JSON 직렬화에서 오류가 나므로 문자열로 넘겨야 한다 | `_response.py`, `lib/ws/_parser.py`, `_utils/_json.py` |
| 웹소켓 | websockets 라이브러리, 기본 PING 20초(120초 무송수신 규칙 충족). 재연결은 1초 고정 간격, 연속 5회까지이고, 정상 종료 코드(1000·1001)에서는 재연결하지 않고 끝난다. 연결·메시지 속도 제한 코드는 없다. 서버 오류 메시지는 예외가 아니라 일반 이벤트로 나온다 | `lib/ws/_async.py`, `lib/ws/_parser.py`, websockets 15.0.1 |
| 요청 한도 | `Remaining-Req`를 해석하거나 스스로 속도를 조절하지 않는다. 헤더는 `with_raw_response`나 httpx event hook으로 읽을 수 있다 | 패키지 전체 검색, `_response.py` |
| 포함 범위 | REST 50개(출금·입금·포켓 이전·트래블룰 포함)와 웹소켓 3종 | `.stats.yml`, `resources/` |
| 의존성 | aiohttp(필수, 상한 없음), httpx-aiohttp(상한 없음), sniffio(상한 없음), httpx, anyio, distro, pydantic, PyJWT, typing-extensions, websockets <16. google-genai 2.34.0(websockets <18)과 함께 설치하면 websockets는 15.0.1(2025-03-05)에 묶인다(최신 17.4) | 휠 METADATA, google-genai `pyproject.toml`, PyPI |
| 라이선스 문서 상충 | 업비트 개발자 센터에 "업비트 개발자 SDK 라이센스 v1.0"(오픈소스 아님, 개인 목적만, 수정·재배포는 전체 소스 공개 시에만, 사업 목적 금지)이 따로 있다. 이 문서가 upbit-sdk-python에 적용되는지는 명시돼 있지 않다(확인 필요) | docs.upbit.com/kr/page/upbit_developer_sdk_license |
| ccxt(대안 C) | 4.5.92(2026-11-04 배포, 2026-11-05 기준 최신). 업비트 `create_order`는 `smp_type`·`selfTradePrevention` 인자를 post_only와의 충돌 검사에만 쓰고 요청에서는 뺀다(`cancel_and_new`의 `new_smp_type`은 보낸다). JWT는 HS256, `query_hash`는 인코딩하지 않은 문자열로 계산. 기본 요청 간격 `rateLimit` 50ms. 의존성에 aiohttp, cryptography, requests, coincurve 등 | ccxt-4.5.92 휠의 `ccxt/async_support/upbit.py`(`create_order`, `sign`), `METADATA`, PyPI |

### PyInstaller 호환 위험 (확인 요청 항목)

| 위험 | 정도 | 근거 | 대응(공식 SDK를 고를 경우) |
|---|---|---|---|
| SDK 코드 자체 | 낮음 | 순수 Python(`.py` 208개 + `py.typed`), 버전이 코드에 박혀 있고 `importlib.metadata`·`pkg_resources`·`__file__` 접근이 없다. `importlib.import_module("upbit.resources")` 지연 import가 있지만 각 리소스 모듈이 함수 안 import로도 들어와 정적 분석에 잡힌다 | - |
| aiohttp 계열을 항상 끌어옴 | 중 | `import upbit`가 모듈을 읽는 순간 `httpx_aiohttp` → aiohttp(C 확장 multidict, yarl, propcache, frozenlist 포함)를 import한다. 기본 경로는 httpx라 쓰지 않는데도 묶음 크기와 DLL 수가 늘어난다. httpx-aiohttp는 import 때 `metadata.version("aiohttp")`를 부른다. PyInstaller 6.22.3은 수집한 코드의 바이트코드에서 인자가 문자열 하나인 `importlib.metadata.version` 등의 호출을 찾아 그 배포판 메타데이터를 자동으로 넣는다(`PyInstaller/depend/analysis.py`의 `metadata_required`, `depend/bytecode.py`). 메타데이터가 빠져도 `PackageNotFoundError`는 `ImportError`의 하위 클래스라 SDK의 `except ImportError`(`upbit/_base_client.py`)가 흡수한다. 실제 빌드로는 확인하지 않았다 | aiohttp를 쓰지 않으면 `excludes=["aiohttp", "httpx_aiohttp"]`를 검토 |
| 상한 없는 의존성 | 중 | aiohttp, httpx-aiohttp, sniffio는 버전 상한이 없다. 마이너 버전에서 호환이 깨질 수 있다고 SDK README가 밝힌다 | `uv.lock`으로 해시까지 고정, 올릴 때 계약 테스트 |
| 훅 | 낮음 | pyinstaller-hooks-contrib 2026.9에 anyio, certifi, pydantic, websockets 훅이 있다. 나머지 의존성(httpx, PyJWT, distro, sniffio, typing-extensions, httpx-aiohttp 등)은 순수 Python이다. httpx는 certifi의 `cacert.pem`이 묶여 있어야 한다(certifi 훅이 처리) | - |
| 실제 Windows 빌드 결과 | 확인 필요 | 이 세션은 Windows 빌드를 돌릴 수 없다 | 2단계 build-exe.yml과 `--self-test`에서 확인 |

- 결론: 패키징을 막는 요소는 찾지 못했다. SDK의 큰 위험은 패키징이 아니라 동작(POST 자동 재시도, 429 즉시 재시도, 웹소켓 재연결 방식)이다.
- 자체 클라이언트(A)를 고르면 aiohttp 계열과 SDK 고유 항목이 빠지고 httpx, websockets, PyJWT, certifi만 남는다.

## 결과

- 의존성: httpx, websockets, PyJWT(정확한 버전 고정, 2026-11-05 PyPI 최신 0.28.1, 17.4, 2.15.1). aiohttp는 넣지 않는다.
- 2~3단계 작업량이 늘어난다: REST 16개, 웹소켓 2개, 응답 모델, 오류 매핑, 토큰 버킷.
- 공식 SDK의 `api.md`와 타입 정의, 공식 문서의 OpenAPI 정의(`.md`로 받을 수 있음)를 필드 이름 대조와 녹화 응답 작성에 쓴다. 단, SDK·문서의 예제 코드는 저장소에 복사하지 않고 명세를 보고 직접 작성한다(업비트 개발자 SDK 라이센스, [법·약관 검토](../../07-security-legal/legal-compliance.md) 3장).
- 업비트 문서의 변경 기록(changelog)을 한 달에 한 번 확인한다(tech-stack 업그레이드 정책과 같은 주기).
