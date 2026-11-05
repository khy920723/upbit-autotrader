# 규칙 조건 후보 비교 스크립트

[규칙 조건 후보 비교 리포트](../../docs/research/rule-candidates.md)의 수치를 만드는 연구용 스크립트다.

- 앱 코드(`src/`)와 관계없고 `pyproject.toml`도 쓰지 않는다.
- 실행 스크립트는 PEP 723 인라인 메타데이터로 의존성을 적었다. 분석은 표준 라이브러리만 쓰고, 테스트만 pytest를 쓴다.
- LLM을 쓰지 않는다. 외부 호출은 업비트 공개 시세 API(캔들)뿐이고 키는 쓰지 않는다.

| 파일 | 역할 |
|---|---|
| `fetch_candles.py` | 240분봉과 일봉을 받아 `research/data/candles/`에 CSV와 `manifest.json`으로 저장한다 |
| `compare_rules.py` | 캐시만 읽어 후보와 조합의 지표를 계산하고 `research/data/results/`에 표(md)와 JSON을 쓴다 |
| `candle_store.py` | 요청 한도, 헤더·URL 검사, 페이지 처리, 진행 중 캔들 제외, 빈 캔들 채우기, CSV를 맡는다 |
| `rule_lab.py` | 지표(SMA, Wilder RSI), 조건, 조합, 시뮬레이션, 통계를 맡는다 |
| `test_research_candle_store.py`, `test_research_rule_lab.py` | 오프라인 테스트. HTTP는 가짜로 대신한다 |
| `conftest.py`, `__init__.py` | pytest import 방식과 루트 설정에 상관없이 이 폴더의 모듈을 찾게 한다 |
| `pytest.ini` | 단독 테스트 실행이 나중에 생길 루트 pytest 설정(플러그인, addopts)을 물려받지 않게 한다 |

## 실행

데이터 받기(최대 2년, 끝 날짜를 고정하면 같은 범위를 다시 받는다):

```bash
uv run research/rules/fetch_candles.py --end 2026-11-05 --days 730
```

분석(네트워크 없음):

```bash
uv run research/rules/compare_rules.py
```

테스트:

```bash
uv run research/rules/test_research_candle_store.py
```

```bash
uv run research/rules/test_research_rule_lab.py
```

## 업비트 호출 규칙

- 캔들 그룹은 1.1초 창마다 최대 5회만 호출한다. 공개 한도(초당 10회)의 절반 이하다.
  - 창은 요청이 끝난 시각부터 센다. 요청은 한 번에 하나씩 보내므로, 연결 지연이 들쭉날쭉해도 서버에 도착하는 요청이 1초에 5회를 넘지 않는다.
- `Origin` 헤더를 보내지 않는다.
- URL은 `https://api.upbit.com`에 `/v1/...`만 붙이고, 끝 슬래시와 중복 슬래시를 거부한다.
- 오류 처리
  - 429는 다음 초에 같은 요청을 다시 보낸다.
  - 418은 바로 멈춘다.
  - 오류 이름은 `error.name`으로만 읽는다.
- 서버 `Date` 헤더로 서버 시각을 읽고, 그때 아직 진행 중인 캔들은 저장하지 않는다.
- 거래가 없던 시간대에는 업비트가 캔들을 주지 않는다. 그 자리는 직전 종가로 평평한 캔들을 채우고 `filled=1`로 표시하며, 채운 개수를 `manifest.json`에 적는다.

## 데이터 위치

`research/data/`는 루트 `.gitignore`의 `data/` 규칙으로 커밋되지 않는다. 다른 세션에서는 `fetch_candles.py`로 다시 받는다.

- `manifest.json`은 모든 CSV를 쓴 뒤 마지막에 쓴다. 받는 중에 멈추면 manifest가 없으므로 다음 실행에서 다시 받는다.
- 캐시 판정은 범위뿐 아니라 각 CSV의 개수, 첫 캔들, 마지막 캔들까지 manifest와 대조한다.
