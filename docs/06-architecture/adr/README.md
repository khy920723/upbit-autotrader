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
| [0006](0006-upbit-client.md) | 업비트 클라이언트 | 제안(D-038 대기) |
| 0007 | 규칙 조건 | 대기(별도 세션이 비교 리포트 작성 중, D-021) |
| [0008](0008-buy-method.md) | 매수 방식: 기본은 한 번에, 분할은 회차 금액이 예산 하한 이상일 때만 | 제안(D-039 대기) |
| [0009](0009-gui-asyncio-bridge.md) | GUI와 asyncio 연결: asyncio 루프를 전용 스레드에서 실행 | 제안(D-040 대기) |

## 결정 대기

- "제안" ADR은 사용자가 승인하면 "확정"으로 바꾸고 [결정 로그](../../10-management/decision-log.md)의 해당 항목 상태를 "유효"로 바꾼다.
- 0007(규칙 조건)은 별도 세션의 후보 비교 리포트를 보고 사용자가 고른 뒤 작성한다.
