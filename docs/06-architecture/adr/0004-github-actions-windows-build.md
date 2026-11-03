# ADR-0004 GitHub Actions Windows 빌드와 워크플로 관리

상태: 확정 · 2026-11-03

## 맥락

- 클라우드 세션 VM은 리눅스이고, PyInstaller는 크로스 컴파일을 못 한다.
- 클라우드 세션은 `.github/workflows/` 아래 파일을 push할 수 없다(Claude GitHub App에 workflow 권한이 없음). 태그 push도 막혀 있다.
- 저장소는 공개라 GitHub Actions 표준 러너를 무료로 쓸 수 있다.

## 결정

- `windows-2025` 러너에서 PyInstaller로 빌드하고 `--self-test`로 검사한다.
- PR에서는 코드 경로가 바뀌었을 때 빌드·검사만 하고, 수동 실행(workflow_dispatch)일 때만 결과물을 올린다(보관 7일).
- 리눅스 러너(`ubuntu-24.04`)에서 린트와 테스트를 돌린다.
- 워크플로 파일은 사용자 Mac(로컬 세션)에서 관리한다. 클라우드 세션은 바꿀 내용을 `docs/10-management/ci-proposals.md`에 적는다.

## 검토한 대안

| 대안 | 판단 |
|---|---|
| 사용자 PC에서 직접 빌드 | 매매 PC에 개발 환경을 깔아야 함 |
| 자체 호스팅 러너 | 키가 있는 PC를 외부 작업에 노출. 기각 |
| 태그 push로 릴리스 | 클라우드 세션에서 불가 |

## 결과

- Auto-fix로 빌드·테스트 실패를 자동 수정할 수 있다. 워크플로 파일 자체는 고치지 못한다.
- exe는 서명하지 않는다. 배포할 일이 생기면 개인용 OV 인증서를 검토한다(Azure Artifact Signing은 한국 개인 개발자가 쓸 수 없음).
