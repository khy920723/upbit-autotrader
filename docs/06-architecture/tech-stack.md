# 기술 스택·버전 정책

상태: 확정 · 2026-11-03 확인 · 관련: [ADR-0001](adr/0001-python-pyside6-pyinstaller.md), [시스템 구성도](system-architecture.md)

## 1. 스택

| 영역 | 선택 | 버전 정책 | 이유 |
|---|---|---|---|
| 언어 | Python | 3.13.x (`>=3.13,<3.14`) | Windows 10 지원. PySide6·PyInstaller·google-genai 지원 범위 안 |
| 패키지 관리 | uv | `uv.lock` 커밋, CI는 `--locked` | 재현 가능한 설치 |
| 화면 | PySide6 | `>=6.12,<6.13` | Qt 6.12가 Windows 10을 지원하는 마지막 버전(LTS) |
| 패키징 | PyInstaller | 6.22.x, onedir·windowed·UPX 끔 | 크로스 컴파일 불가 → Windows 러너에서 빌드 |
| LLM SDK | google-genai | 정확한 버전 고정(기준 2.34.0) | 공식 SDK. 구 SDK는 지원 종료 |
| 업비트 클라이언트 | upbit-sdk 또는 자체 구현 | 1단계(ADR-0006) | |
| HTTP·웹소켓 | httpx, websockets(후보) | 정확한 버전 고정 | 비동기, 웹소켓 헤더에 JWT |
| JWT | PyJWT(후보) | 고정 | HS512 서명 |
| 데이터 검증 | pydantic 2 | 고정 | LLM 출력·설정 검증 |
| 비밀 저장 | keyring | 25.x | Windows 자격 증명 관리자. PyInstaller에 훅 있음 |
| DB | SQLite(표준 라이브러리) | - | 단일 사용자 로컬 앱 |
| 테스트 | pytest, pytest-qt | dev 그룹 | 화면 테스트는 offscreen |
| 린트 | ruff | dev 그룹 | |
| CI 액션 | actions/checkout@v7, astral-sh/setup-uv@v10.3.3, actions/upload-artifact@v7 | setup-uv는 주 버전 태그가 없어 정확한 버전으로 고정 | |
| CI 러너 | ubuntu-24.04, windows-2025 | 라벨 고정 | ubuntu-latest는 2026-11에 26.04로 바뀜 |

"후보"는 1단계에서 확정한다.

## 2. 업그레이드 정책

- **정기 점검:** 의존성은 한 달에 한 번 점검한다. 보안 공지가 있으면 바로 올린다.
- **PySide6:** 6.13 이상으로 올리지 않는다. Windows 11로 옮긴 뒤 다시 검토한다. 의존성 자동 업데이트 도구를 쓰면 6.13 이상을 무시하게 설정한다.
- **google-genai:** 변경 기록을 확인하고, 시그널 관련 테스트를 통과해야 올린다.
- **Python:** 마이너 버전(3.14 등)을 바꿀 때는 ADR을 남긴다.
- **러너 라벨:** 바꿀 때는 Windows 10 PC에서 실행 확인까지 한다.

## 3. Windows 10 이후

- Windows 10 개인용 ESU는 2027-10-12에 끝난다. 그 전에 Windows 11로 옮긴다.
- Windows 11에서는 스마트 앱 컨트롤이 서명 없는 exe를 막을 수 있다. 옮길 때 코드 서명 필요 여부를 다시 본다.
- Windows 11로 옮기면 PySide6 6.13 이상과 Python 새 버전을 검토한다.
