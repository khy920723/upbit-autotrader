# ADR-0001 Python + PySide6 + PyInstaller(onedir)

상태: 확정 · 2026-11-03

## 맥락

- Windows 10에서 실행되는 데스크톱 exe가 필요하다.
- 개발은 리눅스 클라우드 세션에서 한다. 사용자는 Vue·TypeScript와 Java 경험이 있다.
- 자동매매·지표 계산 자료와 라이브러리는 Python 쪽이 가장 많다.

## 결정

Python 3.13 + PySide6 6.12.x + PyInstaller 폴더형(onedir) 빌드를 쓴다.

## 검토한 대안

| 대안 | 장점 | 단점 |
|---|---|---|
| TypeScript + Electron + Vue | 사용자에게 익숙함 | 앱이 큼(100MB 안팎), 백테스트 라이브러리가 적음 |
| C# + .NET | Windows 네이티브 | 리눅스 클라우드에서 화면을 띄워 테스트할 수 없음 |
| Java | 사용자에게 익숙함 | 데스크톱 패키징이 번거롭고 Windows에서 빌드해야 함 |

## 결과

- 같은 코드로 Mac에서도 화면을 확인할 수 있다.
- Qt 6.12가 Windows 10을 지원하는 마지막 버전이라 PySide6 6.13 이상은 쓰지 않는다.
- onedir이라 실행이 빠르고, Qt DLL을 교체할 수 있어 LGPL 의무를 지키기 쉽다.
- PyInstaller는 크로스 컴파일을 못 하므로 Windows 러너에서 빌드한다(ADR-0004).
- 서명 없는 exe라 SmartScreen 경고가 뜬다. 설치 가이드에서 안내한다.
