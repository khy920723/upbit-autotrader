# 설정 항목 정의서

상태: 초안 · 관련: [화면 정의서](../02-ux/screen-spec.md), [위험 관리 정책서](risk-policy.md), [보안 정책](../07-security-legal/security-policy.md)

## 1. 저장 위치

| 종류 | 위치 | 비고 |
|---|---|---|
| 비밀(키, 토큰) | Windows 자격 증명 관리자(keyring, 서비스 이름 `upbit-autotrader`) | 파일·로그·DB에 쓰지 않음 |
| 일반 설정 | `%LOCALAPPDATA%\upbit-autotrader\` 아래 설정 파일 | 형식(JSON 또는 TOML)은 1단계에서 결정, 스키마 버전 포함 |
| 시작 앱 등록 | `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` | 켜고 끌 때만 씀 |
| 런타임 데이터 | 같은 폴더의 `data\`, `logs\`, `backup\` | 저장소에 커밋하지 않음 |

## 2. 항목

기본값은 초안이다. 위험 한도 기본값은 페이퍼 시작용 예시이며 투자 판단이 아니다.

### 계정·키

| 키 | 설명 | 기본값 | 저장 |
|---|---|---|---|
| `upbit.access_key`, `upbit.secret_key` | 업비트 API 키(자산조회·주문조회·주문하기 권한) | - | keyring |
| `upbit.key_issued_at` | 키 발급일. 만료일 = 발급일 + 1년 | - | 설정 파일 |
| `gemini.api_key` | Gemini API 키 | - | keyring |
| `naver.client_id`, `naver.client_secret` | 네이버 검색 API | - | keyring |
| `telegram.bot_token` | 텔레그램 봇 토큰(선택) | - | keyring |
| `telegram.chat_id` | 알림 받을 채팅 ID | - | 설정 파일 |

### 코인

| 키 | 설명 | 기본값 | 범위 |
|---|---|---|---|
| `coins` | 매매할 마켓 코드 목록(예: KRW-BTC) | - | 1~3개, 경고 종목 불가 |

### 시그널

| 키 | 설명 | 기본값 | 범위 |
|---|---|---|---|
| `signal.interval_hours` | 평가 주기 | 4 | 1~24 |
| `signal.confidence_threshold` | 시그널을 쓰는 최소 확신도(매수·부정 매도 공통) | 0.7 | 0.5~0.95 |
| `signal.sell_on_negative` | LLM 부정(확신도 ≥ 임계값) 시 보유분 매도 | false | true/false |
| `llm.model_id` | Gemini 모델 ID | 마법사에서 선택 | 2.5 계열 불가 |
| `llm.timeout_sec` | 응답 대기 시간 | 30 | 10~120 |
| `llm.max_output_tokens` | 출력 토큰 상한 | 1단계에서 결정 | - |
| `news.lookback_hours` | 뉴스 수집 기간 | 24 | 1~72 |
| `news.max_headlines` | 코인당 최대 제목 수 | 10 | 1~30 |
| `news.sources` | 사용할 출처 | naver, coindesk, cointelegraph | 이 3개 중에서 선택(다른 출처는 약관 확인 후 결정 로그에 기록하고 추가) |

### 매매 규칙 (1단계에서 확정)

| 키 | 설명 |
|---|---|
| `rules.*` | 규칙 조건 종류와 파라미터 |
| `buy.method` | 전액 한 번에 또는 분할 |
| `exit.*` | 규칙상 청산 조건 |

### 위험 한도

| 키 | 설명 | 기본값(초안) | 범위 |
|---|---|---|---|
| `risk.budget_per_coin_krw` | 코인별 예산 | 10,000 | ≥ 예산 하한: 최소 주문 금액 ÷ (1 − 손절%/100) × 1.1. 분할 매수면 회차당 금액 기준 |
| `risk.max_total_exposure_krw` | 전체 노출 상한 | 30,000 | ≥ 코인별 예산 |
| `risk.stop_loss_pct` | 손절 비율(%) | 5.0 | 0.5~50 |
| `risk.take_profit_pct` | 익절 비율(%), 비우면 꺼짐 | 꺼짐 | 0.5~500 |
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
| `notify.telegram.enabled` | 텔레그램 알림 | 마법사 결과 |
| `notify.levels` | 받을 등급(긴급과 일일 요약은 항상) | 긴급, 경고, 정보 |
| `notify.daily_summary_time` | 일일 요약 시각(KST) | 09:00 |

### 실행·시작

| 키 | 설명 | 기본값 |
|---|---|---|
| `app.autostart` | Windows 시작 시 실행 | true |
| `app.resume_last_mode` | 직전 모드·상태로 자동 재개 | true |
| `app.close_to_tray` | 창 닫기 = 트레이 | true |
| `app.keep_awake` | 매매 중 절전 방지 | true |
| `mode` | 실행 모드 | paper |

페이퍼 시작 시각과 인정일은 DB(app_meta, daily_stats)에만 저장하고, 실전 전환 게이트(인정일 28일, live-validate 3일)는 설정으로 바꿀 수 없다.

### 고급

| 키 | 설명 | 기본값 |
|---|---|---|
| `market.refresh_hours` | 종목·경고 갱신 주기 | 3 |
| `paper.slippage_pct` | 페이퍼 슬리피지 | 0.1 |
| `log.level` | 로그 수준 | INFO |
| `log.retention_days` | 로그 보관 기간 | 90 |
| `backup.keep` | DB 백업 보관 개수 | 7 |

## 3. 변경 규칙

- 위험 한도를 느슨하게 바꾸면 MSG-C006으로 확인한다.
- 키를 바꾸면 즉시 검증하고, 실패하면 이전 키를 유지한다.
- 설정 파일 스키마가 바뀌면 앱이 자동으로 옮기고(마이그레이션) 이전 파일을 백업한다.
