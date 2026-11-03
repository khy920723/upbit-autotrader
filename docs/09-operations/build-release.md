# 빌드·배포 절차

상태: 확정 · 관련: [ADR-0004](../06-architecture/adr/0004-github-actions-windows-build.md), [설치 가이드](install-guide.md), [운영 런북](runbook.md)

## 1. 버전

- SemVer 0.x를 쓰고 `pyproject.toml`의 version에 적는다.
- 0.1.0은 페이퍼 실사용을 시작하는 첫 버전이다(8단계).

## 2. 자동 검사

| 워크플로 | 언제 | 무엇을 |
|---|---|---|
| ci.yml | main push, 모든 PR, 수동 | ruff 린트, pytest(offscreen) — ubuntu-24.04 |
| build-exe.yml | src·packaging·pyproject·uv.lock이 바뀐 PR | PyInstaller 빌드 + `--self-test` — windows-2025. 결과물은 올리지 않음 |
| build-exe.yml | 수동 실행 | 위와 같고 결과물(zip)을 7일 동안 보관 |

`pyproject.toml`과 `packaging/autotrader.spec`이 생기기 전에는 해당 단계를 건너뛴다.

## 3. 빌드 받기

1. GitHub 저장소 → Actions → build-exe → Run workflow(브랜치 main).
2. 끝나면 실행 화면 아래 Artifacts에서 `autotrader-windows-<커밋 해시>`를 받는다.
3. 로그의 Smoke test 단계에서 `self-test-report.txt` 내용이 통과인지 확인한다.

## 4. 오래 보관할 버전

- 결과물은 7일 뒤 지워진다. 계속 쓸 버전은 GitHub 웹에서 Release를 만들고 zip을 첨부한다(태그는 사용자가 만든다. 클라우드 세션은 태그를 push할 수 없다).
- Release 설명에는 진행 기록의 해당 내용을 옮긴다.

## 5. 서명

- exe는 서명하지 않는다. 처음 실행할 때 SmartScreen 경고가 뜬다. 설치 가이드에서 안내한다.

## 6. 빌드 설정 바꾸기

- `.github/workflows/`는 사용자 Mac의 로컬 세션에서 고치고 push한다.
- 클라우드 세션은 바꿀 내용을 `docs/10-management/ci-proposals.md`에 적는다.
