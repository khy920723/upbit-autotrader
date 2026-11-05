# 2단계 하락률 비교 스크립트

[2단계 하락률 비교 리포트](../../docs/research/split-drop-rate.md)(D-086)의 수치를 만드는 연구용 스크립트다.

- 앱 코드(`src/`)와 관계없고 `pyproject.toml`도 쓰지 않는다.
- 실행 스크립트는 PEP 723 인라인 메타데이터로 의존성을 적었다. 분석은 표준 라이브러리만 쓰고, 테스트만 pytest를 쓴다.
- LLM을 쓰지 않는다. 외부 호출은 업비트 공개 시세 API(캔들)뿐이고 키는 쓰지 않는다.
- 수익률과 손익 금액은 계산하지 않는다. 비율, 걸린 시간, 손절선 위치만 센다.
- 캔들 받기와 요청 한도는 [research/rules](../rules/README.md)의 `candle_store.py`를 그대로 불러 쓴다.

| 파일 | 역할 |
|---|---|
| `fetch_hourly.py` | 60분봉을 받아 `research/data/split/candles/`에 CSV와 `manifest.json`으로 저장한다 |
| `drop_rate.py` | 캐시만 읽어 하락률·보유 기간별로 집계하고 `research/data/split/results/`에 표(md)와 JSON을 쓴다 |
| `split_lab.py` | 시뮬레이션(1단계 매수, 2단계 가격 조건, 손절, 보유 기간)과 집계를 맡는다 |
| `split_reference.py` | 같은 규칙을 사건 순서로 다시 계산하는 대조용 구현이다. `--crosscheck`와 테스트에서만 쓴다 |
| `test_split_lab.py` | 오프라인 테스트(손 계산 예, 무작위 경로에서 두 구현 대조) |
| `conftest.py`, `__init__.py`, `pytest.ini` | research/rules와 같은 방식으로 pytest가 이 폴더와 `research/rules`의 모듈을 찾게 한다 |

## 실행

데이터 받기(끝 날짜를 고정하면 같은 범위를 다시 받는다):

```bash
uv run research/split/fetch_hourly.py --end 2026-11-05 --days 730
```

분석(네트워크 없음, `--crosscheck`는 모든 사례를 대조용 구현으로 다시 센다):

```bash
uv run research/split/drop_rate.py --crosscheck
```

테스트:

```bash
uv run research/split/test_split_lab.py
```

## 업비트 호출 규칙

`candle_store.py`의 규칙을 그대로 따른다. 1.1초 창마다 최대 5회(공개 한도의 절반 이하), `Origin` 헤더 없음, URL 슬래시 검사, 429는 다음 초에 다시, 418은 멈춤, 진행 중인 캔들은 저장하지 않음, 거래가 없던 시간은 직전 종가로 채우고 표시한다.

## 데이터 위치

`research/data/`는 루트 `.gitignore`의 `data/` 규칙으로 커밋되지 않는다. 다른 세션에서는 `fetch_hourly.py`로 다시 받는다.
