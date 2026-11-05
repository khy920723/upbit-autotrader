# 설정 항목 정의서

상태: 초안(1단계 제안 반영, 사용자 결정 대기: D-042 파일 형식, D-044 실행 모드 저장 위치, D-086 2단계 하락률 기본값, D-021 규칙 조건) · 관련: [화면 정의서](../02-ux/screen-spec.md), [위험 관리 정책서](risk-policy.md), [보안 정책](../07-security-legal/security-policy.md)

## 1. 저장 위치

| 종류 | 위치 | 비고 |
|---|---|---|
| 비밀(키, 토큰) | Windows 자격 증명 관리자(keyring, 서비스 이름 `upbit-autotrader`) | 파일·로그·DB에 쓰지 않음 |
| 일반 설정 | `%LOCALAPPDATA%\upbit-autotrader\settings.json` | 형식 제안은 1.1절(D-042 대기). `schema_version` 포함 |
| 실행 모드, 직전 매매 상태, 페이퍼 시작 시각, 인정일 | DB(`app_meta`, `daily_stats`) | 설정 파일에 두지 않는다(D-044 대기). 파일을 고쳐 실전 전환 게이트를 건너뛸 수 없게 하려는 것이다 |
| 시작 앱 등록 | `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` | 켜고 끌 때만 씀 |
| 런타임 데이터 | 같은 폴더의 `data\`, `logs\`, `backup\` | 저장소에 커밋하지 않음 |

### 1.1 설정 파일 형식 (제안, D-042 대기)

| 후보 | 장점 | 단점 |
|---|---|---|
| **JSON (추천)** | 표준 라이브러리(`json`)로 읽고 쓴다. 추가 의존성이 없다. pydantic으로 바로 검증한다 | 주석을 못 단다. 손으로 고치면 쉼표 실수가 잦다 |
| TOML | 사람이 읽기 좋고 주석을 단다 | Python 3.13 표준 라이브러리 `tomllib`는 읽기만 한다. 쓰려면 `tomli-w` 같은 의존성이 더 필요하다. 앱이 파일을 다시 쓰면 주석이 사라져 주석의 이점이 거의 없다 |
| QSettings | Qt가 제공한다 | Windows 기본 저장소가 레지스트리라 백업·비교가 어렵다. core가 Qt에 의존하게 된다(구조 원칙 위반) |
| SQLite에 저장 | 한 곳에 모인다 | 사람이 확인하기 어렵다. DB가 손상되면 설정도 잃는다 |

추천 이유: 설정은 화면(SCR-06)과 마법사에서만 바꾸고 사람이 파일을 직접 고칠 일이 없게 한다. 그러면 주석의 장점이 작고, 의존성이 없는 JSON이 낫다.

### 1.2 파일 규칙 (제안)

- UTF-8, 들여쓰기 2칸. 최상위에 `schema_version`(정수, 1부터)을 둔다. 항목 키는 2장의 키를 점(.) 기준으로 중첩한 것이다.

```json
{
  "schema_version": 1,
  "coins": ["KRW-BTC", "KRW-ETH"],
  "signal": { "interval_hours": 4, "confidence_threshold": 0.7, "sell_on_negative": false },
  "buy": { "step_pcts": [100], "next_step_drop_pct": null },
  "sell": { "take_profit_steps": [] },
  "risk": { "budget_per_coin_krw": 10000, "stop_loss_pct": "5.0" }
}
```

- 백분율과 금액 항목은 Decimal로 읽는다. 부동소수 오차를 피하려고 백분율처럼 소수가 들어가는 항목은 JSON에 문자열로 쓰고(예: `"5.0"`), 원 단위 금액은 정수로 쓴다. 확신도처럼 0~1 범위의 비교용 값은 숫자로 쓴다(예: `0.7`).
- **쓰기:** 같은 폴더에 임시 파일을 쓰고 디스크에 반영한 뒤 `os.replace`로 바꾼다(중간에 꺼져도 반쯤 쓴 파일이 남지 않음). 바꾸기 전 기존 파일을 `settings.json.bak`으로 남긴다.
- **읽기:** pydantic 모델로 형식·범위를 검증하고, 모르는 키가 있으면 오류로 본다.

| 상황 | 동작 |
|---|---|
| 파일이 없음 | 첫 실행 마법사(SCR-01) |
| 형식·검증 오류 | 매매를 시작하지 않고 시작 점검 결과(SCR-07)에 오류를 보여 준다. 사용자는 [백업에서 복원]과 [마법사 다시 실행] 중에서 고른다. [백업에서 복원]은 `settings.json.bak`을 되살린다. 기본값으로 조용히 바꾸지 않는다 |
| `schema_version`이 앱보다 낮음 | 자동으로 옮기고(마이그레이션) 이전 파일을 `backup\settings.v{번호}.json`으로 남긴다 |
| `schema_version`이 앱보다 높음 | 새 버전 앱이 만든 파일이다. 매매를 시작하지 않고 안내한다. 파일을 덮어쓰지 않는다 |
| 앱 밖에서 고쳐짐(DB의 `settings_applied_json`과 다름) | 바뀐 항목을 이벤트(SETTING_EXTERNAL_CHANGE)로 남긴다. 위험 한도를 엄격하게 바꾼 값만 바로 적용한다. 나머지(위험 한도 완화, `coins`, `buy.*`, `sell.*`, `signal.*`, `llm.*` 등)는 이전 값으로 매매하면서 대시보드에서 확인을 받은 뒤 적용한다(완화는 MSG-C006). 보유 중인 코인이 `coins`에서 빠졌으면 MSG-C007 응답 전까지 계속 관리한다. 외부에서 바꾼 값도 화면 저장과 같은 검사(예산 하한, 분할 매수 조건)를 하고, 못 맞추면 이전 값을 유지한다(D-068) |

## 2. 항목

기본값은 초안이다. 위험 한도 기본값은 페이퍼 시작용 예시이며 투자 판단이 아니다.

### 계정·키

| 키 | 설명 | 기본값 | 저장 |
|---|---|---|---|
| `upbit.access_key`, `upbit.secret_key` | 업비트 API 키(자산조회·주문조회·주문하기 권한) | - | keyring |
| `upbit.key_issued_at` | 키 발급일(보조 값). 만료일은 `GET /v1/api_keys`의 `expire_at`을 우선 쓰고, 조회하지 못할 때만 발급일 + 1년으로 계산한다(D-050) | - | 설정 파일 |
| `gemini.api_key` | Gemini API 키 | - | keyring |
| `naver.client_id`, `naver.client_secret` | 네이버 검색 API | - | keyring |
| `discord.webhook_url` | 디스코드 `app-alarm` 채널의 웹후크 주소(선택). 비밀값이라 입력 후 가린다 | - | keyring |

### 코인

| 키 | 설명 | 기본값 | 범위 |
|---|---|---|---|
| `coins` | 매매할 마켓 코드 목록(예: KRW-BTC). 선택 이력은 DB `selected_coins`에 남는다 | - | 1~3개, 경고 종목 불가 |

### 시그널

| 키 | 설명 | 기본값 | 범위 |
|---|---|---|---|
| `signal.interval_hours` | 평가 주기 | 4 | 1~24 |
| `signal.confidence_threshold` | 시그널을 쓰는 최소 확신도(매수·부정 매도 공통) | 0.7 | 0.5~0.95 |
| `signal.sell_on_negative` | LLM 부정(확신도 ≥ 임계값) 시 보유분 매도 | false | true/false |
| `llm.model_id` | Gemini 모델 ID | 마법사에서 선택 | 2.5 계열 불가 |
| `llm.timeout_sec` | 응답 대기 시간 | 30 | 10~120 |
| `llm.max_output_tokens` | 출력 토큰 상한 | 미정(남은 일, [LLM 시그널 명세](../05-integration/llm-signal.md) 10장) | - |
| `news.lookback_hours` | 뉴스 수집 기간 | 24 | 1~72 |
| `news.max_headlines` | 코인당 최대 제목 수 | 10 | 1~30 |
| `news.sources` | 사용할 출처 | naver, coindesk, cointelegraph | 이 3개 중에서 선택(다른 출처는 약관 확인 후 결정 로그에 기록하고 추가) |

### 매매 규칙

| 키 | 설명 | 기본값 | 범위 |
|---|---|---|---|
| `rules.*` | 규칙 조건 종류와 파라미터 | ADR-0007 확정 후 정의(D-021 대기) | - |
| `buy.step_pcts` | 매수 단계별 비율(%). `[100]`이면 한 번에 산다(D-082) | `[100]` | 1~2개(D-083), 1% 단위 정수, 합 100. 단계 금액(내림(코인별 예산 × 비율 ÷ 100)) ≥ 예산 하한이어야 저장된다. 못 맞추면 MSG-E015 |
| `buy.next_step_drop_pct` | 2단계 하락률(%): 시그널 평가 때 매수 조건을 다시 만족하고 현재가가 평균 단가보다 이만큼 이상 낮을 때만 2단계를 산다(D-084) | 없음(D-086 대기) | 매수가 2단계면 꼭 입력. 0 < 하락률 < 손절%. 화면에 MSG-W013을 늘 보인다 |
| `sell.take_profit_steps` | 익절 단계: 발동 수익률(%)과 매도 비율(%). 비우면 익절 꺼짐(D-085) | 비어 있음 | 0~2개(D-083). 발동 수익률 0.5~500이고 단계마다 커야 한다. 매도 비율 1% 단위 정수, 합 100. 나눠 판 뒤 남는 원가 ≥ 예산 하한이어야 저장된다 |
| `exit.*` | 규칙상 청산 조건 | ADR-0007 확정 후 정의 | - |

신규 매수 주문 유형(최유리 FOK)과 매도 주문 유형(시장가)은 설정이 아니라 고정 동작이다([매매 로직 명세](trading-logic.md) 6장, D-043).

- 단계 계획(`buy.*`, `sell.*`)은 포지션을 열 때 고정한다. 바꾸면 다음 포지션부터 적용하고 MSG-I010으로 알린다. 저장 검사 S1~S7과 실패 문구(MSG-E015, MSG-E020)는 [분할 매수·매도 설계](split-trading.md) 3.2에 있다.
- 이전의 `buy.method`, `buy.split_count`, `risk.take_profit_pct`는 쓰지 않는다(D-082).

### 위험 한도

| 키 | 설명 | 기본값(초안) | 범위 |
|---|---|---|---|
| `risk.budget_per_coin_krw` | 코인별 예산 | 10,000 | ≥ 예산 하한: 최소 주문 금액 ÷ (1 − 손절%/100) × 1.1. 매수 2단계면 단계마다, 익절을 나누면 나눠 판 뒤 남는 금액도 이 기준([분할 매수·매도 설계](split-trading.md) 3.2) |
| `risk.max_total_exposure_krw` | 전체 노출 상한 | 30,000 | ≥ 코인별 예산 |
| `risk.stop_loss_pct` | 손절 비율(%) | 5.0 | 0.5~50 |
| `risk.daily_loss_limit_krw` | 일일 손실 한도 | 3,000 | > 0 |
| `risk.min_order_interval_sec` | 같은 코인 최소 주문 간격 | 60 | ≥ 10 |
| `risk.max_orders_per_day` | 일일 주문 수 상한 | 20 | 1~100 |
| `risk.reentry_policy` | 손절 후 재진입: none, hours, today, manual | none | 목록 |
| `risk.reentry_hours` | hours일 때 대기 시간 | 24 | 1~168 |
| `risk.max_data_staleness_sec` | 시세 끊김 허용 시간 | 120 | 30~600 |
| `risk.max_clock_skew_sec` | 시계 오차 허용 | 5 | 1~30 |

### 알림

| 키 | 설명 | 기본값 |
|---|---|---|
| `notify.discord.enabled` | 디스코드 알림 | 마법사 결과 |
| `notify.levels` | 받을 등급(긴급과 일일 요약은 항상) | 긴급, 경고, 정보 |
| `notify.daily_summary_time` | 일일 요약 시각(KST) | 09:00 |

### 실행·시작

| 키 | 설명 | 기본값 |
|---|---|---|
| `app.autostart` | Windows 시작 시 실행 | true |
| `app.resume_last_mode` | 직전 모드·상태로 자동 재개 | true |
| `app.close_to_tray` | 창 닫기 = 트레이 | true |
| `app.keep_awake` | 매매 중 절전 방지 | true |
| `app.disclaimer_accepted_at` | 마법사 W1 면책 동의 시각 | - |

- 실행 모드(paper 기본)는 설정 파일 항목이 아니다. DB `app_meta.mode`에 저장하고, 바꿀 때는 화면의 전환 절차와 실전 전환 게이트를 거친다(D-044 대기).
- 페이퍼 시작 시각과 인정일은 DB(`app_meta`, `daily_stats`)에만 저장하고, 실전 전환 게이트(인정일 28일, live-validate 3일)는 설정으로 바꿀 수 없다.

### 고급

| 키 | 설명 | 기본값 |
|---|---|---|
| `market.refresh_hours` | 종목·경고 갱신 주기 | 3 |
| `paper.slippage_pct` | 페이퍼 고정 슬리피지. 호가를 받지 못했을 때만 쓴다([매매 로직 명세](trading-logic.md) 6장) | 0.1 |
| `log.level` | 로그 수준 | INFO |
| `log.retention_days` | 로그 보관 기간 | 90 |
| `backup.keep` | DB 백업 보관 개수 | 7 |

## 3. 변경 규칙

- 위험 한도를 느슨하게 바꾸면 MSG-C006으로 확인한다. 앱 밖에서 파일을 고쳐 느슨해진 경우도 같다(1.2절).
- 키를 바꾸면 즉시 검증하고, 실패하면 이전 키를 유지한다.
- 설정 파일 스키마가 바뀌면 앱이 자동으로 옮기고(마이그레이션) 이전 파일을 백업한다(1.2절).
