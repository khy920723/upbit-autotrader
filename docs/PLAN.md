# 단계별 계획 (PLAN)

2026-11-03 작성. 단계 하나 = 클라우드 세션 하나 = PR 하나.

## 진행 방법

각 세션은 이렇게 시작한다.

```text
docs/PLAN.md의 N단계(이름)를 진행해줘.
먼저 CLAUDE.md, docs/SPEC.md, docs/PROGRESS.md를 읽고 계획부터 보여줘.
테스트를 먼저 쓰고, 실제 키나 실제 주문은 쓰지 마.
끝나면 docs/PROGRESS.md를 갱신하고 PR을 만들어줘.
```

PR이 생기면 Changes 카드에서 PR의 ⋮ 메뉴를 열어 Auto-fix를 켠다. 테스트나 빌드가 실패하면 Claude가 원인을 찾아 고친다. 빌드 설정 파일 자체는 고치지 못한다.

## 단계

### 0단계: 준비 (완료, 로컬 세션)

- 저장소, 문서, CI 설정
- 남은 사용자 작업은 아래 "사용자 작업" 참고

### 1단계: 설계 (Plan 모드)

- docs/ARCHITECTURE.md: 모듈과 인터페이스, 주문 상태 흐름, DB 구조, 위험 정책 기본값, LLM 프롬프트와 스키마, 규칙 조건 정의, 테스트 계획
- 결정 기록: 업비트 클라이언트(upbit-sdk 또는 httpx 자체 구현), GUI와 asyncio 연결 방식, 기본 모델 ID
- 완료 기준: 문서 PR 승인

### 2단계: 뼈대 + 빌드 검증

- uv 프로젝트, 빈 창 앱, 설정·로그·SQLite 초기화, `--self-test`, `packaging/autotrader.spec`
- 완료 기준: CI와 Windows 빌드 통과. 사용자가 Windows 10 PC에서 빈 앱 실행과 self-test 통과를 확인

### 3단계: 업비트 연동

- JWT 서명(알려진 값으로 테스트), 요청 한도, 오류 매핑, `/v1/orders/chance`, 호가 단위, 종목 목록과 경고, 시세·비공개 웹소켓(재연결 후 REST로 대조), 가짜 거래소
- 완료 기준: 가짜 거래소로 테스트 통과

### 4단계: 뉴스 + LLM 시그널

- 네이버·RSS 수집(중복 제거, 길이 제한), Gemini 호출(스키마 검증, 실패 시 neutral, 429 처리, 사고·출력 토큰 제한), 입출력 원문 기록, 가짜 LLM
- 완료 기준: signal-only 모드 동작

### 5단계: 규칙·위험·주문 관리 + 페이퍼

- 규칙 조건, 위험 관리, 주문 관리(identifier 먼저 저장, 조회로 확인), 페이퍼 체결(수수료·슬리피지), 일정(LLM 4시간, 손절 1분), 규칙 부분 백테스트(캔들은 api.upbit.com에서 받음)
- 완료 기준: 장애 시나리오(타임아웃, 429/418, 연결 끊김, 재시작) 테스트 통과

### 6단계: 화면

- 첫 실행 마법사, 코인 선택, 메인 창(상태, 코인별 포지션·손익, 시그널과 이유, 로그), 트레이, 긴급 정지, 시작 앱 등록, 중복 실행 방지
- 완료 기준: pytest-qt 테스트 통과

### 7단계: 운영 기능

- 텔레그램, 절전 방지, 잠자기 복귀·재시작 후 재동기화, 시계 오차 점검, 키 만료 알림, 데이터 끊김 감시, CSV 내보내기, 로그 회전
- 완료 기준: 재시작 시나리오 테스트 통과

### 8단계: v0.1 페이퍼 실사용

- Windows 10 PC에서 몇 주 이상 paper로 운영하고 버그 수정 세션 진행
- 완료 기준: 시그널과 가상 손익 기록 확보

### 9단계: 실전 전환

- live-validate로 며칠 운영 → 서브 포켓에 소액을 넣고 live
- 완료 기준: 사용자 판단

## 사용자 작업

### 클라우드 세션 준비

1. Claude GitHub App을 이 저장소에 설치한다. Auto-fix에 필요하다.
2. 클라우드 환경을 새로 만든다.
   - Network access: Custom. Allowed domains에 `api.upbit.com`을 넣고 "Also include default list of common package managers"를 체크한다.
   - 환경 변수와 비밀값은 넣지 않는다.
   - Setup script:

```bash
#!/bin/bash
apt-get update -qq || true
apt-get install -y -qq --no-install-recommends libgl1 libegl1 libdbus-1-3 libxkbcommon0 libfontconfig1 || true
exit 0
```

### 빌드와 설치

1. GitHub → Actions → build-exe → Run workflow.
2. 끝나면 실행 화면의 Artifacts에서 zip을 받는다.
3. Windows PC에서 zip 속성 → "차단 해제" → 압축 해제 → `autotrader.exe` 실행. SmartScreen 경고가 뜨면 "추가 정보 → 실행".

빌드 설정(`.github/workflows/`)을 바꿔야 하면 Mac의 로컬 세션에서 반영한다.

### 계정 (실사용 전)

- 업비트: 본인 인증, 2채널 인증, 서브 포켓 생성, API 키 발급(자산조회·주문조회·주문하기만, PC 공인 IP 등록), 발급일 메모
- Google AI Studio: Gemini API 키 발급, 모델별 무료 한도 확인
- 네이버 개발자센터: 검색 API 애플리케이션 등록 → Client ID/Secret
- 텔레그램: BotFather로 봇 생성 → 토큰

### Windows 10 PC

- 22H2인지 확인, ESU 등록(무료: Windows 백업 동기화, 2027-10-12까지)
- 절전 "안 함", 업데이트 활성 시간 설정(최대 18시간), 노트북이면 덮개 닫기 "아무것도 안 함"
- 재부팅 후 자동 재개가 필요하면 자동 로그인 여부를 정한다(보안과 편의의 트레이드오프)

## 검증된 외부 사실 (2026-11-03 기준)

| 주제 | 내용 | 출처 |
|---|---|---|
| 클라우드 세션 | `.github/workflows` push 불가(GitHub App에 workflow 권한 없음), 태그 push 불가, gh는 REST만 | code.claude.com/docs/en/claude-code-on-the-web, /cloud-environments; anthropics/claude-code-action FAQ |
| 클라우드 VM | Ubuntu 24.04 x86_64, 약 4 vCPU·16GB·30GB, Python·uv·pytest·ruff 포함, 유휴 시 일시정지 | code.claude.com/docs/en/cloud-environments |
| 클라우드 네트워크 | Trusted 목록에 업비트 없음 → Custom으로 api.upbit.com 추가 | 같은 문서 |
| Qt | 6.12가 Windows 10(1809+)을 지원하는 마지막 버전, 6.12는 LTS | doc.qt.io/qt-6/supported-platforms.html |
| Python | 3.13·3.14는 Windows 10 지원, 3.12는 Windows 바이너리 배포 종료 | docs.python.org/3/using/windows.html |
| PyInstaller | 6.22.x, Python 3.8~3.15, onedir 먼저 권장, UPX 비권장 | pyinstaller.org |
| GitHub Actions | windows-latest = Server 2025, ubuntu-latest는 2026-11에 26.04로 이동 → 라벨 고정 | github.com/actions/runner-images |
| 업비트 키 | 고정 공인 IPv4 필수(최대 10개), 1년 유효·연장 불가, KYC·2채널 인증 후 PC 웹에서만 발급 | docs.upbit.com/kr/docs/api-key |
| 업비트 요청 한도 | 시세 그룹별 초당 10회(IP), 주문 초당 12회(포켓), 반복 위반 시 418 차단 | docs.upbit.com/kr/reference/rate-limits |
| 업비트 변경 | 헤더 중복 400(2026-07-31), smp_type 기본값 변경(2026-11-09), 경로 형식 오류 처리(2026-11-16) | docs.upbit.com/kr/changelog |
| 업비트 테스트 | 테스트넷 없음, `/v1/orders/test`는 주문 형식만 검증 | docs.upbit.com/kr/reference/order-test |
| 업비트 공지 | 비공개 웹소켓 `announcement`(2026-08-31부터), upbit.com 수집은 robots.txt로 금지 | docs.upbit.com/kr/reference/websocket-announcement |
| Gemini | 무료 등급 한국 이용 가능, 한도는 AI Studio에서만 표시·프로젝트 단위·보장 없음, 무료 등급 입력은 사람 검토 가능 | aistudio.google.com/docs/rate-limits, /docs/terms |
| Gemini SDK | google-genai(Python 3.11+), 구 SDK 지원 종료, gemini-2.5-pro·2.5-flash 폐기(2026-11-02) | pypi.org/project/google-genai, aistudio.google.com/docs/changelog |
| 검색 연동 | Gemini 3 이상은 무료 등급에서 Google 검색 연동 불가 | aistudio.google.com/docs/pricing |
| 뉴스 | 네이버 검색 API 하루 25,000회 무료, CryptoPanic 무료 플랜 없음, Google 뉴스 RSS는 개인 리더 용도로 제한 | developers.naver.com, cryptopanic.com |
| 법 | 가상자산이용자보호법 불공정거래 처벌, API 고빈도 반복 주문을 시세조종으로 수사 의뢰한 사례(2025-11-05) | fsc.go.kr |
| Windows 10 | 지원 종료 2025-10-14, 개인용 ESU는 2027-10-12까지 | microsoft.com/windows/extended-security-updates |
| 백테스트 | LLM 감성 시그널에는 look-ahead bias가 있음 | arxiv.org/abs/2309.17322 |
