# upbit-autotrader

업비트 원화(KRW) 마켓에서 최대 3개 코인을 자동으로 매매하는 **개인용 Windows 데스크톱 앱**입니다. 시세·지표와 뉴스 헤드라인을 LLM(Gemini)이 긍정·부정으로 평가하고, 규칙 조건과 위험 한도를 모두 통과할 때만 주문합니다.

> **현재 상태:** 1단계(설계, 사용자 결정 대기 항목 있음)와 2단계(뼈대·빌드 검증: 빈 창 앱, `--self-test`, Windows 빌드)를 마쳤고 매매 기능은 아직 없습니다. 진행 상황은 [진행 기록](docs/10-management/progress.md)에 남깁니다.

> **면책:** 이 프로젝트는 투자 자문이 아니며 수익을 보장하지 않습니다. 자동매매는 버그, 장애, 급변동으로 손실이 날 수 있습니다. 실제 자금을 쓰기 전에 페이퍼(모의) 모드로 충분히 검증하세요.

## 주요 기능 (계획)

- Windows 시작 시 자동 실행, 시작 점검(키·IP·잔고·미체결 주문 대조) 후 매매 재개
- 첫 실행 마법사: API 키를 Windows 자격 증명 관리자에 암호화해 저장
- 코인 최대 3개 선택, 유의·주의 종목과 거래지원 종료 예정 종목은 매수 차단
- LLM 시그널(4시간 주기) + 규칙 조건 + 위험 한도의 3중 확인
- 손절(1분마다 점검), 일일 손실 한도, 주문 간격·횟수 상한, 긴급 정지
- 모드: 페이퍼(기본) → 시그널 기록 → 실전 점검(주문 검증 API) → 실전
- 텔레그램 알림, 거래 기록 CSV 내보내기

## 구조

```text
[시세·지표]   [뉴스 제목]
      \         /
   LLM 시그널 (긍정/부정/중립 JSON) ──┐
   규칙 조건 (예: 상승 추세) ─────────┼──▶ 위험 관리 ──▶ 주문 관리 ──▶ 업비트
   종목 경고·손절·일일 한도 ──────────┘    (항상 우선)
```

## 기술 스택

| 영역 | 사용 기술 |
|---|---|
| 언어 | Python 3.13 (uv) |
| 화면 | PySide6 6.12 (Windows 10을 지원하는 마지막 Qt) |
| 배포 | PyInstaller 폴더형 빌드, GitHub Actions Windows 러너 |
| 거래소 | 업비트 Open API (REST, WebSocket) |
| 시그널 | Gemini API (google-genai, 구조화 출력) |
| 뉴스 | 네이버 검색 API, CoinDesk·Cointelegraph RSS |
| 저장 | SQLite, Windows 자격 증명 관리자(keyring) |
| 테스트 | pytest, pytest-qt, ruff |

## 안전 설계

- 실제 키는 저장소, CI, 클라우드에 두지 않고 사용자 PC에만 저장합니다.
- 업비트 키는 조회·주문 권한만 쓰고 출금 권한은 쓰지 않습니다.
- LLM 응답은 스키마로 검증하고, 오류·한도 초과·형식 불일치는 모두 "매수 안 함"으로 처리합니다.
- LLM 시그널은 과거 데이터 백테스트로 평가하지 않습니다. 모델이 학습 중에 그 기간의 결과를 봤을 수 있기 때문입니다(look-ahead bias). 대신 페이퍼 실적으로 확인합니다.

## 개발 방식

[Claude Code](https://claude.com/claude-code) 클라우드 세션으로 단계별로 개발합니다. 단계 하나가 세션 하나, PR 하나입니다.

- [문서 지도](docs/README.md): 기획 문서 전체 목록(10개 분류)
- [요구사항 정의서](docs/01-planning/requirements.md)
- [시스템 구성도](docs/06-architecture/system-architecture.md)
- [로드맵](docs/10-management/roadmap.md): 단계별 계획과 검증된 외부 사실
- [진행 기록](docs/10-management/progress.md)
- [CLAUDE.md](CLAUDE.md): 개발 규칙

## 라이선스

[MIT](LICENSE)
