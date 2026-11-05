# 진행 기록

세션이 끝날 때마다 맨 위에 추가한다. 형식: 날짜 — 단계 / 한 일 / 결정 / 남은 일 / 다음 단계.

## 2026-11-05 — 2단계: 뼈대 + 빌드 검증 (클라우드 세션)

- 한 일: uv 프로젝트(`pyproject.toml`, `uv.lock`, `.python-version` 3.13, 런타임 `PySide6==6.12.0`·`keyring==25.7.0`), `src/autotrader/` 7개 하위 패키지와 `__main__.py`, 빈 메인 창, 런타임 경로(`%LOCALAPPDATA%\upbit-autotrader\` 아래 data·logs·backup)·KST 로그(10MB×10 회전)·SQLite(`data\autotrader.db`, `schema_version` 표만, WAL) 초기화, `--self-test`(import, Qt offscreen, keyring, SQLite, TLS, 설정 경로 → `self-test-report.txt`, 0/1 종료), `packaging/autotrader.spec`(onedir·windowed·UPX 끔, `packaging/launcher.py` 진입), [의존성 라이선스 목록](../07-security-legal/dependency-licenses.md)과 `uv.lock` 대조 스크립트, 번들 고지(exe 옆 `NOTICE.txt`, `_internal/licenses/`). 테스트 210개(구조 규칙, spec 계약, 고정 버전, 라이선스 표 포함). Linux에서 같은 spec으로 빌드해 frozen self-test 확인. [PR #1](https://github.com/khy920723/upbit-autotrader/pull/1)에서 ci·build-exe 통과(Windows self-test 6/6, WinVaultKeyring)
- 발견·조치: PySide6 메타 패키지가 Addons까지 설치하면 PyInstaller가 GPL-3.0 전용 Qt Virtual Keyboard 플러그인을 번들에 넣는다 → 사용자 훅으로 빼고, GPL 전용 Qt 바이너리가 남으면 빌드를 멈춘다. PyInstaller가 setuptools·packaging·typing_extensions(개발 전용)까지 넣던 것을 빼고, 런타임 의존성 밖 패키지가 들어가면 빌드를 멈춘다. `ruff format`이 Markdown 코드 블록도 고쳐서 ruff 대상에서 docs를 뺐다. 독립 검토(4개 관점) 지적을 반영했다
- 결정(1단계 PR 병합 뒤 결정 로그에 번호를 맞춰 추가): GPL 전용 Qt 모듈(Charts, Graphs, Virtual Keyboard 등) 사용 금지와 빌드 차단(6단계 대시보드 차트는 QPainter 등으로), 고지 동봉 방식(NOTICE.txt + `_internal/licenses/`), self-test 보고서는 UTF-8(BOM), PyInstaller 진입 스크립트 분리(`autotrader/platform`이 표준 `platform`을 가리는 문제), 빌드 백엔드 uv_build, 개발용 비Windows 경로(XDG, macOS Application Support)
- 남은 일(사용자): Windows 10 PC에서 빈 앱 실행과 self-test 확인([설치 가이드](../09-operations/install-guide.md) "자가 점검"). 병합 전에는 Actions → build-exe → Run workflow에서 브랜치 `claude/stage-2-skeleton`을 골라야 zip이 생긴다. [CI 변경 제안](ci-proposals.md) 1번 반영, PySide6-Essentials 전환 여부 결정, README "현재 상태" 줄 갱신(1단계와 충돌을 피하려고 두었다)
- 남은 일(1단계와 정리): 스키마 버전 위치(`schema_version` 표 vs 데이터 모델 초안의 `app_meta`), 설정 파일 이름·형식, 위 결정들의 결정 로그 번호
- 다음 단계: 3단계 업비트 연동(1단계 설계 PR 병합 후)

## 2026-11-03 — 기획 문서 작성 (로컬 세션)

- 한 일: `docs/`를 10개 분류 폴더로 재구성하고 기획 문서를 작성([문서 지도](../README.md)). 기존 SPEC·PLAN·PROGRESS·ci-proposals를 해당 폴더로 이동(요구사항 정의서, 로드맵, 진행 기록, CI 변경 제안). `LICENSE`(MIT) 추가, `CLAUDE.md`와 README 경로 갱신. 검토 에이전트 1회 검토(지적 38건)를 반영해 상태 정의(DEGRADED 추가, 상태 복원 규칙), 실전 전환 2단계 체크리스트, 주문 결과 불명 처리, 알림 문구 ID, 테스트 시나리오(59개)를 보강
- 결정: [결정 로그](decision-log.md) D-016~D-037 (D-032 실전 점검 3일 강제 확정, D-033 자동 로그인은 지금 계정 그대로 + 화면 잠금 필수)
- 남은 일(사용자): Claude GitHub App 설치, 클라우드 환경 생성(로드맵 "사용자 작업"), 집 IP 고정 여부 확인, 네이버 검색 API 약관 확인(4단계 전), 업비트 Open API 약관 확인(9단계 전)
- 다음 단계: 1단계 설계

## 2026-11-03 — 0단계: 준비 (로컬 세션)

- 한 일: 공개 저장소 생성, README·CLAUDE.md·SPEC·PLAN·PROGRESS 작성, CI 워크플로(`ci.yml`, `build-exe.yml`), 클라우드 세션 시작 훅
- 결정: 업비트 KRW 최대 3코인, Python 3.13 + PySide6 6.12, Gemini 무료 등급 시그널 + 규칙 확인, 네이버·RSS 뉴스, paper 기본
- 남은 일(사용자): Claude GitHub App 설치, 클라우드 환경 생성(당시 PLAN.md, 지금은 로드맵의 "사용자 작업"), 집 IP 고정 여부·PC 종류·자동 로그인 결정, 라이선스 결정
- 다음 단계: 1단계 설계
