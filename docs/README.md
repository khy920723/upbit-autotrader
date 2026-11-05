# 문서 지도

업비트 자동매매 앱의 기획 문서 모음이다. 2026-11-03 기준으로 작성했다. 결정이 바뀌면 [결정 로그](10-management/decision-log.md)에 먼저 기록한 뒤 관련 문서를 고친다.

## 읽는 순서

- **처음 보는 사람:** 프로젝트 개요서 → 요구사항 정의서 → 시스템 구성도 → 로드맵
- **클라우드 세션(개발):** 루트 `CLAUDE.md` → 요구사항 정의서 → 로드맵의 해당 단계 → 진행 기록 → 그 단계와 관련된 문서
- **운영(사용자):** 설치·초기 설정 가이드 → 운영 런북

## 상태 표시

- **확정:** 사용자와 정한 내용
- **초안:** 제안한 내용. 1단계 설계나 페이퍼 운영 결과에 따라 바뀔 수 있음
- **1단계 보완:** 1단계 설계 세션이 채워야 하는 부분이 있음

## 문서 목록

| 분류 | 문서 | 상태 |
|---|---|---|
| 01 기획 | [프로젝트 개요서](01-planning/project-charter.md) | 확정 |
| | [요구사항 정의서](01-planning/requirements.md) | 확정 |
| | [사용자 시나리오](01-planning/user-scenarios.md) | 초안 |
| | [용어 정의서](01-planning/glossary.md) | 확정 |
| 02 화면 | [화면 흐름도](02-ux/screen-flow.md) | 초안 |
| | [화면 정의서](02-ux/screen-spec.md) | 초안 |
| | [메시지·문구 정의서](02-ux/messages.md) | 초안 |
| 03 기능 | [기능 명세서](03-functional/feature-spec.md) | 초안 |
| | [매매 로직 명세](03-functional/trading-logic.md) | 1단계 보완 |
| | [위험 관리 정책서](03-functional/risk-policy.md) | 확정(수치는 초안) |
| | [상태 전이 정의서](03-functional/state-machines.md) | 초안 |
| | [알림 정의서](03-functional/notifications.md) | 초안 |
| | [설정 항목 정의서](03-functional/settings.md) | 초안 |
| 04 데이터 | [데이터 모델](04-data/data-model.md) | 1단계 보완 |
| | [로그·감사 기록 정의서](04-data/logging-audit.md) | 초안 |
| 05 연동 | [업비트 API 연동 명세](05-integration/upbit-api.md) | 확정(2026-11 기준) |
| | [LLM 시그널 명세](05-integration/llm-signal.md) | 초안 |
| | [뉴스 수집 명세](05-integration/news-collection.md) | 초안 |
| | [텔레그램 연동 명세](05-integration/telegram.md) | 확정 |
| 06 아키텍처 | [시스템 구성도](06-architecture/system-architecture.md) | 1단계 보완 |
| | [기술 스택·버전 정책](06-architecture/tech-stack.md) | 확정 |
| | [결정 기록(ADR)](06-architecture/adr/README.md) | 확정 5건, 대기 4건 |
| 07 보안·법무 | [보안 정책·위협 모델](07-security-legal/security-policy.md) | 확정 |
| | [리스크 관리 대장](07-security-legal/risk-register.md) | 초안 |
| | [법·약관·라이선스 검토](07-security-legal/legal-compliance.md) | 초안(일부 미확인) |
| | [의존성 라이선스 목록](07-security-legal/dependency-licenses.md) | 초안 |
| 08 품질 | [테스트 전략](08-quality/test-strategy.md) | 초안 |
| | [테스트 시나리오](08-quality/test-scenarios.md) | 초안 |
| | [페이퍼 운영 평가 기준](08-quality/paper-evaluation.md) | 확정 |
| 09 운영 | [빌드·배포 절차](09-operations/build-release.md) | 확정 |
| | [설치·초기 설정 가이드](09-operations/install-guide.md) | 초안 |
| | [운영 런북](09-operations/runbook.md) | 초안 |
| 10 관리 | [로드맵](10-management/roadmap.md) | 확정 |
| | [진행 기록](10-management/progress.md) | 진행 중 |
| | [결정 로그](10-management/decision-log.md) | 진행 중 |
| | [CI 변경 제안](10-management/ci-proposals.md) | 진행 중 |

## ID 규칙

| 접두어 | 대상 | 정의 문서 |
|---|---|---|
| FR-, NFR- | 기능·비기능 요구사항 | 요구사항 정의서 |
| UC- | 사용자 시나리오 | 사용자 시나리오 |
| SCR- | 화면 | 화면 정의서 |
| MSG- | 화면 문구 | 메시지·문구 정의서 |
| JOB- | 주기 작업 | 기능 명세서 |
| NTF- | 알림 | 알림 정의서 |
| RSK- | 리스크 | 리스크 관리 대장 |
| TS- | 테스트 시나리오 | 테스트 시나리오 |
| D- | 결정 | 결정 로그 |
| ADR- | 아키텍처 결정 | 결정 기록(ADR) |
