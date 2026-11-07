# ADR-0009 GUI와 asyncio 연결: asyncio 루프를 전용 스레드에서 실행

상태: 확정 · 2026-11-05 · 사용자 결정(D-040, 추천안 A 그대로). 비상 전송 경로(D-060)는 따로 대기

## 맥락

- 화면은 PySide6 6.12(Qt 6.12)이고 Qt 메인 스레드에서만 그린다.
- 네트워크(업비트 REST·웹소켓 2개, Gemini, 디스코드 웹후크. 뉴스는 D-097로 없음)와 스케줄러는 asyncio로 짠다([시스템 구성도](../system-architecture.md)).
- 매매 핵심(`core`)은 Qt를 import하지 않는다(CLAUDE.md 구조 원칙). 그래서 GUI 없이 테스트할 수 있어야 한다.
- 손절 점검은 60초 이하 주기로 돌아야 하고, 네트워크를 기다리는 동안에도 화면이 멈추면 안 된다(NFR-05). 반대로 화면이 모달 대화상자(확인 창, 마법사)나 무거운 그리기로 바쁠 때도 손절과 웹소켓 처리가 멈추면 안 된다.
- 업비트 웹소켓은 120초 동안 주고받은 데이터가 없으면 끊긴다. PING을 제때 보내야 한다.
- Windows 10이 실행 환경이다. Python 3.13의 Windows 기본 이벤트 루프는 Proactor다.

## 결정

결정: **asyncio 이벤트 루프를 GUI와 다른 전용 스레드(core 스레드)에서 표준 asyncio로 돌리고, 앱 계층이 두 스레드를 잇는다.**

- GUI → core: `asyncio.run_coroutine_threadsafe(명령, loop)`. 결과는 `concurrent.futures.Future` 완료 콜백에서 Qt 시그널로 돌려준다.
- core → GUI: core는 순수 Python 관찰자 인터페이스(`CoreObserver`)를 부르고, 앱 계층 구현이 Qt 시그널을 emit한다. 받는 QObject가 GUI 스레드에 있으므로 Qt가 큐 연결로 GUI 스레드에서 처리한다.
- 스레드 사이에는 바뀌지 않는 스냅샷만 넘긴다. 자세한 규칙(시작·종료 순서, heartbeat, 예외 처리)은 [시스템 구성도](../system-architecture.md) 3장에 둔다.

## 검토한 대안

| 대안 | 장점 | 단점 | 판단 |
|---|---|---|---|
| **A. 전용 스레드의 표준 asyncio 루프 + 앱 계층 브리지** | Qt 루프와 독립이라 모달 창·무거운 화면 작업 중에도 손절과 웹소켓 PING이 돈다. 표준 asyncio만 쓴다(추가 의존성 없음). core 테스트가 Qt 없이 표준 루프에서 그대로 돈다. Windows 기본 Proactor 루프를 그대로 써서 httpx·websockets 호환 문제가 적다 | 스레드 경계 규칙을 지켜야 한다(공유 가변 객체 금지, 명령·알림 경로 고정). 종료 순서를 직접 구현한다. 디버깅이 조금 더 어렵다 | **채택** |
| B. qasync(Qt 루프와 asyncio 루프 통합) | 스레드가 하나라 공유 상태 문제가 없다. 슬롯에서 바로 `await`할 수 있다(`@asyncSlot`) | GUI와 매매 루프가 같은 스레드라 화면 작업이 길면 손절·PING도 늦어진다. 코루틴(`@asyncSlot`) 안에서 띄우는 모달 창은 `asyncWrap`으로 감싸 띄우라고 qasync가 안내한다(그런 창마다 지킬 규칙이 생김). Windows에서는 qasync가 자체 IOCP 프로액터와 폴링 스레드를 쓴다. 서드파티 의존성이다 | 기각 |
| C. PySide6 QtAsyncio | PySide6에 들어 있다(추가 의존성 없음) | PySide6 6.12.0의 QtAsyncio는 `create_connection`, `getaddrinfo`, `sock_*`, `start_tls`, `add_reader`, `subprocess_exec` 등이 `NotImplementedError`다. httpx·websockets 같은 네트워크 라이브러리를 쓸 수 없다. B의 단일 스레드 단점도 같다 | 기각 |
| D. asyncio 없이 QThread + 동기 클라이언트 | Qt 방식 그대로 | 웹소켓 2개, REST, 스케줄러를 스레드 여러 개로 나눠 동기화해야 한다. core가 QThread를 쓰면 Qt에 의존하게 된다. 지금 문서의 asyncio 설계와 맞지 않는다 | 기각 |

## 확인한 사실과 출처 (2026-11-05)

| 내용 | 출처 |
|---|---|
| qasync 최신 0.28.0(2025-08-28), requires-python ≥3.8, 분류자 Python 3.13까지, README 요구사항 "Python >=3.8, <3.14", 저장소 마지막 커밋 2026-07-06, 3.14 CI 추가(2025-10-15) | pypi.org/project/qasync, github.com/CabbageDevelopment/qasync(git clone) |
| qasync는 Windows에서 `QIOCPEventLoop`(자체 `_ProactorEventLoop` + `_IocpProactor`, 별도 폴링 스레드)를 쓴다 | qasync `src/qasync/__init__.py`, `_windows.py` |
| qasync `asyncWrap`: "Wrap a blocking function ... run it on the native Qt event loop ... An example usage of this is raising a modal dialogue inside an asyncSlot." | qasync `src/qasync/__init__.py` |
| PySide6 6.12.0 QtAsyncio(`PySide6_Addons` 휠에 포함)의 네트워크·소켓·서브프로세스 메서드가 `NotImplementedError("... is not implemented yet")` | pyside6_addons-6.12.0 휠의 `PySide6/QtAsyncio/events.py` |
| PySide6 6.12.0 배포일 2026-10-08, requires-python ≥3.10,<3.16 | pypi.org/project/PySide6 |
| asyncio 객체는 대부분 스레드 안전하지 않다. 다른 스레드에서 콜백은 `loop.call_soon_threadsafe`로, 코루틴은 `asyncio.run_coroutine_threadsafe`로 넣고, 후자는 `concurrent.futures.Future`를 돌려준다 | CPython v3.13.18 `Doc/library/asyncio-dev.rst` "Concurrency and Multithreading"(태그 소스) |
| 기본 연결(`Qt::AutoConnection`)은 받는 객체가 시그널을 보내는 스레드와 다른 스레드에 있으면 `QueuedConnection`이 되어 받는 쪽 스레드의 이벤트 루프에서 슬롯을 실행한다. 연결 방식은 emit 시점에 정해진다 | qtbase v6.12.0 `src/corelib/global/qnamespace.qdoc` `Qt::ConnectionType`(태그 소스) |

## 결과

- 스레드는 GUI, core(asyncio), 필요할 때의 작업 스레드(keyring, 백업, CSV)로 나뉜다. 역할표는 [시스템 구성도](../system-architecture.md) 3장.
- SQLite 쓰기 연결은 core 스레드 하나가 가진다. 화면은 읽기 전용 연결을 쓴다([데이터 모델](../../04-data/data-model.md) 1장).
- 긴급 정지·일시정지도 같은 명령 경로를 쓴다. core 루프가 GUI와 독립이라 화면이 바빠도 바로 처리된다.
- core가 멈추면 GUI가 heartbeat 끊김(30초)으로 알아채 MSG-E016을 보인다.
- 테스트: core는 표준 asyncio 루프로(가짜 시계·가짜 거래소), 브리지는 pytest-qt로 시그널 전달을 확인한다. 비동기 테스트 도구(pytest-asyncio 추가 여부 등)는 2단계에서 정한다.
- 의존성 추가가 없다.
- 이 ADR과 별개로 대기 중인 결정: core가 멈췄을 때 원격으로 알리는 방법(D-060). 앱 계층의 비상 디스코드 전송(NTF-21, `app-alarm` 웹후크, "네트워크는 core에서만" 규칙의 예외)으로 할지, heartbeat가 2분 넘게 없으면 앱이 스스로 다시 시작하게 할지. 둘 다 없으면 다음 일일 요약이 오지 않을 때까지(최대 약 24시간) 모를 수 있다. 앱이 완전히 멈추거나 PC가 꺼지거나 인터넷이 끊기면 어느 방법으로도 앱이 알릴 수 없다. 이를 알려면 heartbeat를 받는 외부 감시 서비스가 필요하고, 쓸지는 사용자가 정한다.
