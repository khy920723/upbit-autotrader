# 아키텍처 결정 기록(ADR)

중요한 기술 결정을 하나씩 파일로 남긴다. 결정이 바뀌면 기존 파일을 고치지 않고, 새 ADR을 만들어 이전 것을 "대체됨"으로 표시한다.

## 형식

```text
# ADR-NNNN 제목
상태: 제안 | 확정 | 대체됨(ADR-XXXX) · 날짜
## 맥락
## 결정
## 검토한 대안
## 결과
```

## 목록

| 번호 | 제목 | 상태 |
|---|---|---|
| [0001](0001-python-pyside6-pyinstaller.md) | Python + PySide6 + PyInstaller(onedir) | 확정 |
| [0002](0002-gemini-free-tier-signal.md) | 시그널은 Gemini API 무료 등급 | 확정 |
| [0003](0003-paper-first-risk-precedence.md) | 페이퍼 우선, 위험 관리 우선 | 확정 |
| [0004](0004-github-actions-windows-build.md) | GitHub Actions Windows 빌드와 워크플로 관리 | 확정 |
| [0005](0005-news-sources.md) | 뉴스 출처: 네이버 검색 API + 영어 RSS | 확정 |

## 1단계에서 결정할 것

| 번호 | 주제 |
|---|---|
| 0006 | 업비트 클라이언트(공식 upbit-sdk 또는 자체 구현) |
| 0007 | 규칙 조건(후보 비교 후 사용자가 선택) |
| 0008 | 매수 방식(전액 한 번에 또는 분할) |
| 0009 | GUI와 asyncio 연결 방식 |
