# ADR-0006 업비트 클라이언트: httpx 기반 자체 클라이언트

상태: 제안 · 2026-11-05 · 결정 대기(D-038)

## 맥락

- 앱이 쓰는 업비트 API는 REST 17개와 웹소켓 2개(공개 ticker, 비공개 myOrder·myAsset·announcement)다([업비트 API 연동 명세](../../05-integration/upbit-api.md) 2장).
- 주문 안전 규칙이 엄격하다: identifier를 먼저 저장하고 전송, **주문 생성은 자동으로 다시 보내지 않음**, 타임아웃이면 identifier 조회로만 확인, `smp_type` 항상 명시, 같은 헤더 두 번 금지, `Origin` 금지, 경로 슬래시 규칙, `error.name`으로 분기, `Remaining-Req`의 `sec`으로 그룹별 한도의 절반만 사용([매매 로직 명세](../../03-functional/trading-logic.md) 8~9장).
- 런타임 의존성은 정확한 버전으로 고정하고, PyInstaller onedir로 Windows에서 묶는다(ADR-0001, ADR-0004).
- 클라이언트 후보: 공식 `upbit-sdk`, httpx 기반 자체 클라이언트, ccxt, pyupbit(유지보수 중단으로 제외).

## 결정

추천: **httpx(REST) + websockets(웹소켓) + PyJWT(서명)로 얇은 자체 클라이언트를 만든다. 공식 `upbit-sdk`는 의존성으로 넣지 않고, 필드 이름·타입·엔드포인트를 대조하는 자료로 쓴다.**

- 자체 클라이언트는 [시스템 구성도](../system-architecture.md) 6장의 `QuotationApi`, `ExchangeApi`, `PublicStream`, `PrivateStream` 인터페이스를 구현한다.
- 지킬 것: 자동 재시도 없음(조회 재시도는 호출하는 쪽이 정함), HS512 서명, 매 요청 새 nonce, 실제 전송하는 쿼리 문자열로 `query_hash`, 헤더는 `Authorization`·`Content-Type`(POST만)·`Accept`·`User-Agent` 한 번씩, `Origin` 없음, 기본 URL `https://api.upbit.com` + `/v1/...`, 응답마다 `Remaining-Req` 파싱, 오류는 `error.name`으로 7장 오류 타입에 매핑.
- 테스트: JWT·`query_hash` 알려진 값(TS-16), 보내는 헤더와 URL(TS-15), 자동 재시도 없음(TS-72), httpx `MockTransport`와 공식 문서 예시로 만든 녹화 응답.
- 공식 SDK를 다시 검토할 조건: (1) 주문 생성의 자동 재시도를 기본으로 끄거나 요청별로 안전하게 끌 수 있고, (2) aiohttp가 선택 의존성이 되고, (3) websockets 상한이 풀리면.

## 검토한 대안

| 대안 | 장점 | 단점 | 판단 |
|---|---|---|---|
| **A. httpx 기반 자체 클라이언트** | 요청·재시도·헤더·서명·한도 처리를 완전히 통제한다. 의존성이 작다(httpx, websockets, PyJWT, 모두 tech-stack 후보). 가짜 거래소·녹화 응답으로 테스트하기 쉽다. 업비트 규칙 변경(헤더, 경로, SMP)을 바로 반영할 수 있다 | 엔드포인트 17개와 웹소켓 2개를 직접 짜고 유지보수한다. 응답 모델(필드)을 직접 정의한다 | **추천** |
| B. 공식 `upbit-sdk` 1.1.0 | 업비트가 관리한다. 모든 요청·응답 타입이 있다. 동기·비동기와 웹소켓을 지원한다. 포켓 API, 기술적 지표 웹소켓 같은 새 기능이 빨리 들어온다 | 아래 "확인한 사실"의 기본 동작이 이 앱의 주문 안전 규칙과 맞지 않아 매번 덮어써야 한다. 첫 배포가 2026-04로 이력이 짧다(배포 3번). aiohttp(C 확장)를 필수로 끌어와 묶음 크기와 PyInstaller 확인 대상이 늘어난다. websockets를 16 미만으로 묶어 최신 17.x를 쓸 수 없다 | 기각(재검토 조건은 위) |
| C. ccxt | 여러 거래소를 같은 방식으로 다룬다 | 무겁고, 업비트 최신 한도·SMP·포켓 같은 변경 반영이 늦다. 이 앱은 거래소가 하나다 | 기각 |
| D. pyupbit | - | 2024-06 이후 유지보수 중단 | 제외(CLAUDE.md) |

## 확인한 사실 (2026-11-05, upbit-sdk 1.1.0 휠과 공식 저장소 정적 분석)

| 항목 | 내용 | 근거(파일) |
|---|---|---|
| 배포 이력·라이선스 | 0.9.0(2026-04-14), 1.0.0(2026-09-01), 1.1.0(2026-10-20). Apache-2.0. Python ≥3.9 | PyPI 메타데이터 |
| 생성 방식 | Stainless로 생성한 SDK(`X-Stainless-*` 헤더, `_base_client.py`) | `upbit/_base_client.py`, `upbit/_constants.py` |
| 자동 재시도 | 기본 `max_retries=2`. 타임아웃·연결 오류와 408·409·429·5xx에서 **POST를 포함한 모든 메서드**를 다시 보낸다(0.5초에서 시작, 최대 8초). 멱등성 헤더는 보내지 않는다 | `_constants.py`(DEFAULT_MAX_RETRIES=2), `_base_client.py`(`_should_retry`, 요청 루프), `_idempotency_header=None` |
| 이 동작의 위험 | 주문 생성이 타임아웃 뒤 자동으로 다시 나가면, identifier를 넣은 경우 두 번째 요청이 `duplicated_identifier`로 실패해 "주문 실패"로 오인할 수 있고, identifier가 없으면 중복 주문이 될 수 있다. 429 재시도는 주문 한도를 더 쓴다. `max_retries=0`으로 끌 수는 있다 | 추론(위 동작 + 업비트 identifier 규칙) |
| 기본 타임아웃 | 60초(연결 5초) | `_constants.py` |
| 서명 | JWT를 **HS256**으로 서명한다(업비트 문서는 HS512 권장). nonce는 요청마다 uuid4. `query_hash`는 URL 디코딩한 쿼리 문자열의 SHA512 | `upbit/lib/jwt_auth.py` |
| 기본 헤더 | `Accept`, `Content-Type: application/json`(GET 포함), `User-Agent`, `X-Stainless-Lang`·`Package-Version`·`OS`·`Arch`·`Runtime`·`Runtime-Version` | `_base_client.py`(`default_headers`, `platform_headers`) |
| smp_type | 주문 생성 파라미터에서 선택 항목이고 기본값이 없다. 앱이 항상 넣어야 한다 | `upbit/types/order_create_params.py` |
| 의존성 | aiohttp, httpx-aiohttp, httpx, anyio, distro, pydantic, pyjwt, sniffio, typing-extensions, websockets(<16). aiohttp는 선택이 아니라 필수다 | 휠 METADATA |
| 다른 의존성과 겹침 | google-genai 2.34.0은 websockets <18을 요구한다. 둘을 함께 쓰면 websockets는 13~15로 묶인다. aiohttp가 설치되면 google-genai의 비동기 `models` 경로가 aiohttp를 쓰게 된다 | 휠 METADATA, google-genai `pyproject.toml`, `_api_client.py` |

### PyInstaller 호환 위험 (확인 요청 항목)

| 위험 | 정도 | 근거 | 대응(공식 SDK를 고를 경우) |
|---|---|---|---|
| 지연 import: `importlib.import_module("upbit.resources")` | 중 | `upbit/_utils/_resources_proxy.py`. PyInstaller는 문자열로 하는 import를 따라가지 못할 수 있다 | spec에 `collect_submodules("upbit")` 또는 hidden import를 넣고 `--self-test`에서 클라이언트 생성까지 확인 |
| aiohttp C 확장(필수 의존성) | 중 | pyinstaller-hooks-contrib 2026.9에 aiohttp 훅이 없다. 컴파일된 모듈은 보통 import 분석으로 따라오지만 확인이 필요하다 | Windows 빌드에서 aiohttp import 확인 |
| 그 밖의 의존성 | 낮음 | 훅이 있다: anyio, certifi, pydantic, websockets(hooks-contrib 2026.9 `stdhooks`). httpx, jwt, distro, sniffio, typing-extensions, httpx-aiohttp는 순수 Python이라 훅이 필요 없을 가능성이 높다 | 빌드에서 확인 |
| 데이터 파일 | 낮음 | 패키지에 `.py`가 아닌 파일은 `py.typed`뿐이다 | - |
| 실제 빌드 결과 | 확인 필요 | 이 세션은 Windows 빌드를 돌릴 수 없다 | 2단계 build-exe.yml에서 확인 |

- 자체 클라이언트(A)를 고르면 위 위험 중 SDK 고유 항목(지연 import, aiohttp)은 없어진다. httpx, websockets, PyJWT, certifi만 남는다.

## 결과

- 의존성: httpx, websockets, PyJWT(정확한 버전 고정, 2026-11-05 PyPI 최신 0.28.1, 17.4, 2.15.1). aiohttp는 넣지 않는다.
- 2~3단계 작업량이 늘어난다: REST 17개, 웹소켓 2개, 응답 모델, 오류 매핑, 토큰 버킷.
- 공식 SDK의 `api.md`와 타입 정의, 공식 문서의 OpenAPI 정의(`.md`로 받을 수 있음)를 필드 이름 대조와 녹화 응답 작성에 쓴다.
- 업비트 문서의 변경 기록(changelog)을 한 달에 한 번 확인한다(tech-stack 업그레이드 정책과 같은 주기).

## 결정이 필요한 것

- 추천안 A(자체 클라이언트)로 할지, B(공식 SDK + `max_retries=0`, `smp_type` 강제, 헤더 확인을 앱이 보장)로 할지.
