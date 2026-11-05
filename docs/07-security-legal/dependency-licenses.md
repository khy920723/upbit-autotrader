# 의존성 라이선스 목록

상태: 초안 · 2026-11-05 작성(2단계) · 기준: `uv.lock` · 관련: [법·약관·라이선스 검토](legal-compliance.md), [기술 스택·버전 정책](../06-architecture/tech-stack.md)

이 문서는 법률 자문이 아니다. 패키지 메타데이터, 휠 안의 라이선스 파일, Qt·CPython 소스의 라이선스 문서를 근거로 정리했다(8장).

## 1. 결론

- Windows 배포 번들(`dist/autotrader/`)에 들어가는 구성 요소는 모두 MIT 앱과 함께 배포할 수 있다. 조건이 붙는 것은 Qt·PySide6(LGPL-3.0)다(5.1).
- PySide6 메타 패키지는 Essentials 외에 Addons·WebEngine·Pdf까지 설치한다. 그중 일부 Qt 모듈은 오픈소스로는 GPL-3.0으로만 제공된다. 앱은 이 모듈을 쓰지 않고, 빌드가 GPL 전용 바이너리를 막는다(5.3).
- 개발·빌드 전용 패키지는 배포하지 않는다. 빌드가 번들 모듈을 런타임 의존성과 대조해 확인한다(4장). 다만 PyInstaller의 부트로더와 런타임 훅은 exe에 들어가며, 예외 조항과 Apache-2.0으로 배포할 수 있다(5장).

## 2. 갱신 방법

| 언제 | 할 일 |
|---|---|
| 의존성을 바꿨을 때(`uv lock`) | `uv run python scripts/license_inventory.py --write`로 3·4장 표의 패키지·버전·플랫폼을 다시 쓴다. 라이선스·비고 칸은 유지된다 |
| 새 패키지가 "확인 필요"로 들어오면 | 휠 안의 라이선스 파일과 PyPI 정보를 확인해 SPDX 식으로 적고, 번들 포함 여부를 비고에 적는다. 비고에 적힌 "메타데이터: …"는 참고값이라 그대로 믿지 않는다. 조건이 붙는 라이선스(LGPL, MPL)면 `packaging/NOTICE.txt`에 고지와 소스 위치를 더한다 |
| 확인 | `uv run python scripts/license_inventory.py`(검사만). `tests/unit/test_license_inventory.py`도 같은 검사를 한다 |

- 검사 내용: 표와 `uv.lock`의 패키지·버전·설치 플랫폼이 같은지, 런타임 라이선스가 배포 가능한 것만으로 되어 있는지(OR는 하나 이상, AND는 모두), 설치된 패키지 메타데이터에 `License-Expression`이 있으면 표와 같은지.
- "설치 플랫폼"은 `uv.lock`의 마커로 계산한 설치 대상 OS다. 번들에 실제로 들어가는지는 비고에 적는다. PyInstaller는 import한 모듈과 그 의존 파일만 묶는다.
- 배포 가능 라이선스: MIT, MIT-0, BSD-2-Clause, BSD-3-Clause, Apache-2.0, PSF-2.0, ISC, 0BSD, Unlicense, MPL-2.0(파일 단위 카피레프트: 번들에 넣으면 NOTICE.txt에 소스 위치를 적는다), LGPL-3.0(동적 링크·교체 가능·원문 동봉 조건).

## 3. 런타임 의존성

앱이 import하는 패키지(PySide6, keyring)와 그 의존성이다.

<!-- license-inventory:runtime:start -->
| 패키지 | 버전 | 라이선스 | 설치 플랫폼 | 비고 |
|---|---|---|---|---|
| anyio | 4.16.0 | MIT | Windows, Linux, macOS | httpx 의존. 번들에 들어감 |
| certifi | 2026.10.23 | MPL-2.0 | Windows, Linux, macOS | httpx 의존(CA 인증서 묶음). 번들에 들어감. 고치지 않고 쓰며 소스 위치를 NOTICE.txt에 적음 |
| cffi | 2.1.1 | MIT-0 | Linux | Linux 전용(SecretStorage → cryptography). Windows 번들에 없음 |
| cryptography | 50.0.2 | Apache-2.0 OR BSD-3-Clause | Linux | Linux 전용(SecretStorage). Windows 번들에 없음 |
| h11 | 0.16.0 | MIT | Windows, Linux, macOS | httpcore 의존. 번들에 들어감 |
| httpcore | 1.0.9 | BSD-3-Clause | Windows, Linux, macOS | httpx 의존. 번들에 들어감 |
| httpx | 0.28.1 | BSD-3-Clause | Windows, Linux, macOS | 직접 의존(업비트 REST, ADR-0006). 번들에 들어감 |
| idna | 3.20 | BSD-3-Clause | Windows, Linux, macOS | httpx·anyio 의존. 번들에 들어감 |
| jaraco.classes | 3.4.0 | MIT | Windows, Linux, macOS | keyring 의존. 번들에 들어감 |
| jaraco.context | 6.1.2 | MIT | Windows, Linux, macOS | keyring 의존. 번들에 들어감 |
| jaraco.functools | 4.6.0 | MIT | Windows, Linux, macOS | keyring 의존. 번들에 들어감 |
| jeepney | 0.9.0 | MIT | Linux | Linux 전용(Secret Service D-Bus). Windows 번들에 없음 |
| keyring | 25.7.0 | MIT | Windows, Linux, macOS | 직접 의존. 번들에 들어감(Windows 자격 증명 관리자 백엔드) |
| more-itertools | 11.2.1 | MIT | Windows, Linux, macOS | jaraco.classes·jaraco.functools 의존. 번들에 들어감 |
| pycparser | 3.12 | BSD-3-Clause | Linux | Linux 전용(cffi). Windows 번들에 없음 |
| PyJWT | 2.15.1 | MIT | Windows, Linux, macOS | 직접 의존(업비트 JWT 서명, ADR-0006). 번들에 들어감 |
| PySide6 | 6.12.0 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only | Windows, Linux, macOS | 직접 의존. 메타 패키지(코드 없음), 메타데이터만 번들에 들어감 |
| PySide6_Addons | 6.12.0 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only | Windows, Linux, macOS | 설치만 됨. import하지 않아 바이너리는 번들에 없음. GPL 전용 모듈 포함(5.3) |
| PySide6_Essentials | 6.12.0 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only | Windows, Linux, macOS | QtCore·QtGui·QtWidgets와 Qt DLL·플러그인이 번들에 들어감(5장) |
| PySide6_Pdf | 6.12.0.140 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only | Windows, Linux, macOS | 설치만 됨. 쓰지 않음 |
| PySide6_WebEngine | 6.12.0.140 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only | Windows, Linux, macOS | 설치만 됨(Chromium 포함). 쓰지 않음 |
| pywin32-ctypes | 0.2.3 | BSD-3-Clause | Windows | Windows 전용. keyring의 Windows 백엔드가 씀. 번들에 들어감 |
| SecretStorage | 3.5.0 | BSD-3-Clause | Linux | Linux 전용(keyring의 Secret Service 백엔드). Windows 번들에 없음 |
| shiboken6 | 6.12.0 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only | Windows, Linux, macOS | PySide6 바인딩 런타임. 번들에 들어감 |
| typing_extensions | 4.16.0 | PSF-2.0 | Windows, Linux, macOS | anyio 의존(Python 3.15 미만). 번들에 들어감 |
| websockets | 17.4 | BSD-3-Clause | Windows, Linux, macOS | 직접 의존(업비트 웹소켓, ADR-0006). 번들에 들어감 |
<!-- license-inventory:runtime:end -->

## 4. 개발·빌드 전용

배포하지 않는다. 테스트·린트·빌드에만 쓴다.

- PyInstaller는 jaraco 네임스페이스 패키지를 처리하면서 setuptools(벤더링한 jaraco)를 끌어오고, 그 의존성인 packaging까지 번들에 넣는다. 앱은 이것들을 쓰지 않으므로 spec의 `excludes`로 뺐다(Linux 빌드 기준 번들 모듈 531개 → 247개). typing_extensions는 3단계부터 런타임 의존성(anyio)이라 빼지 않는다.
- spec은 번들의 Python 모듈이 런타임 의존성(3장) 밖의 배포판에 속하면 빌드를 멈춘다. `excludes`를 빼고 빌드하면 `_distutils_hack, packaging, setuptools, typing_extensions`에서 멈추는 것을 확인했다.

<!-- license-inventory:dev:start -->
| 패키지 | 버전 | 라이선스 | 설치 플랫폼 | 비고 |
|---|---|---|---|---|
| altgraph | 0.17.5 | MIT | Windows, Linux, macOS | PyInstaller 의존 |
| colorama | 0.4.6 | BSD-3-Clause | Windows | pytest 의존(Windows) |
| coverage | 7.17.2 | Apache-2.0 | Windows, Linux, macOS | pytest-cov 의존 |
| hypothesis | 6.170.14 | MPL-2.0 | Windows, Linux, macOS | 속성 기반 테스트(D-076, 불변식 명세 2.2절). 테스트에서만 쓰고 앱·빌드가 import하지 않아 번들에 없다. MPL-2.0 의무는 배포할 때 생기므로 NOTICE.txt 고지는 필요 없다. 벤더링한 `hypothesis/vendor/pretty.py`에는 IPython에서 온 BSD 코드가 섞여 있다 |
| iniconfig | 2.3.1 | MIT | Windows, Linux, macOS | pytest 의존 |
| macholib | 1.16.4 | MIT | macOS | PyInstaller 의존(macOS) |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause | Windows, Linux, macOS | pytest·PyInstaller 의존. 라이선스 검사 스크립트도 씀 |
| pefile | 2024.8.26 | MIT | Windows | PyInstaller 의존(Windows) |
| pluggy | 1.7.0 | MIT | Windows, Linux, macOS | pytest 의존 |
| Pygments | 2.21.0 | BSD-2-Clause | Windows, Linux, macOS | pytest 의존 |
| pyinstaller | 6.22.3 | GPL-2.0-or-later WITH Bootloader-exception AND Apache-2.0 | Windows, Linux, macOS | 빌드 도구. 부트로더와 런타임 훅이 exe에 들어감(5장) |
| pyinstaller-hooks-contrib | 2026.9 | GPL-2.0-or-later AND Apache-2.0 | Windows, Linux, macOS | PyInstaller 훅 모음. 런타임 훅만 Apache-2.0(5장) |
| pytest | 9.2.0 | MIT | Windows, Linux, macOS | 테스트 |
| pytest-cov | 7.1.0 | MIT | Windows, Linux, macOS | 커버리지 측정 |
| pytest-qt | 4.5.0 | MIT | Windows, Linux, macOS | 화면 테스트 |
| ruff | 0.17.3 | MIT | Windows, Linux, macOS | 린트 |
| setuptools | 84.2.1 | MIT | Windows, Linux, macOS | PyInstaller 의존 |
| sortedcontainers | 2.4.0 | Apache-2.0 | Windows, Linux, macOS | hypothesis 의존. 휠의 LICENSE가 Apache-2.0(메타데이터에는 License-Expression 없이 "Apache 2.0"). 번들에 없음 |
<!-- license-inventory:dev:end -->

## 5. 번들에 함께 들어가는 구성 요소

| 구성 요소 | 라이선스 | 지킬 것 | 번들 안 고지 |
|---|---|---|---|
| Qt 6.12.0 라이브러리(QtCore·QtGui·QtWidgets·QtSvg DLL, platforms·styles·imageformats·iconengines·generic 플러그인)와 PySide6·shiboken6 | LGPL-3.0-only(오픈소스 선택지) | 5.1 | `licenses/LGPL-3.0.txt`, `licenses/GPL-3.0.txt` |
| PyInstaller 부트로더(exe 본체) | GPL-2.0-or-later WITH Bootloader-exception | 예외 조항으로 묶은 프로그램을 제한 없이 배포할 수 있다 | `licenses/pyinstaller/COPYING.txt` |
| PyInstaller 런타임 훅·런타임 모듈 | Apache-2.0 | 라이선스 사본 제공 | 같은 파일(Apache-2.0 본문 포함) |
| CPython 3.13 런타임(python313.dll, 표준 라이브러리) | PSF-2.0 | PSF 라이선스와 저작권 고지 유지 | `licenses/python/LICENSE.txt`(빌드한 Python에 있을 때) |
| CPython에 포함된 외부 소프트웨어(OpenSSL 3, libffi, expat, libmpdec, mimalloc, bzip2, zlib, xz, SQLite, Mersenne Twister, SipHash, dtoa, Unicode 데이터 등) | Apache-2.0, MIT, BSD, zlib, 퍼블릭 도메인 등 | 이진 배포 때 고지를 요구하는 것이 있다 | `licenses/python/cpython-3.13.18-license.rst` |
| HACL*(CPython의 해시 구현) | MIT | 고지 포함 | `licenses/python/hacl-star-MIT.txt`(CPython 문서에 빠져 있어 따로 넣음) |
| Microsoft Visual C++ 런타임(vcruntime140*.dll, msvcp140*.dll)과 Universal CRT(ucrtbase.dll, api-ms-win-*.dll 42개) | Microsoft 재배포 조건 | Python Windows 빌드·PySide6·shiboken6 휠·빌드 PC의 Windows에 딸린 파일을 고치지 않고 쓴다. UCRT는 PyInstaller가 빌드 PC의 Windows에서 모은다(2026-11-05 빌드에서 확인) | Python `LICENSE.txt`의 "Additional Conditions for this Windows binary build" |

- 넣지 않는 것: `opengl32sw.dll`(Mesa llvmpipe 소프트웨어 OpenGL, MIT·BSL-1.0, 약 20MB)은 위젯 앱에 필요 없어 spec이 뺀다. QtNetwork는 `PySide6/__init__.py`가 실행되지 않는 분기에서 import해 끌려오고, 넣으면 PyInstaller가 OpenSSL DLL을 PATH(러너에 설치된 다른 OpenSSL)에서 가져올 수 있어 `excludes`로 뺐다. Windows 빌드는 Python 설치·가상 환경·저장소 밖에서 가져온 바이너리가 있으면 멈춘다(Universal CRT만 예외).
- python.org Windows 빌드의 `LICENSE.txt`에는 CPython, MS 런타임 조건, bzip2, libffi, OpenSSL, Tcl/Tk 라이선스가 들어 있다(Tcl/Tk는 앱이 쓰지 않아 번들에 없다). 나머지 외부 소프트웨어의 고지는 CPython 문서(`Doc/license.rst`)에 있어 그 사본을 넣는다.
- 고지 파일 출처: LGPL·GPL 원문은 qtbase v6.12.0의 `LICENSES/`, CPython 문서는 v3.13.18 태그의 `Doc/license.rst`, HACL* 고지는 같은 태그의 `Modules/_hacl/*.c` 머리말이다.

### 5.1 Qt·PySide6(LGPL-3.0)

| 의무 | 이 앱의 방법 |
|---|---|
| 사용자가 라이브러리를 바꿀 수 있어야 함(4d1) | onedir 빌드라 Qt DLL이 `_internal/PySide6/`에 따로 있다. PySide6·shiboken6의 Python 부분도 exe에 묶지 않고 `.py`로 둔다(spec `module_collection_mode`). onefile로 바꾸거나 정적 링크하지 않는다. 앱 소스 위치도 `NOTICE.txt`에 적는다 |
| 사본마다 눈에 띄는 고지(4a): 라이브러리를 쓰고 LGPL이 적용된다는 사실 | exe 옆 `NOTICE.txt` |
| GPL과 LGPL 사본 동봉(4b) | `licenses/LGPL-3.0.txt`, `licenses/GPL-3.0.txt` |
| 실행 중 저작권을 보여 주면 라이브러리 고지와 라이선스 사본 위치도 함께(4c) | 정보 화면(SCR-11, 6단계) |
| 소스 제공 | Qt·PySide6를 고치지 않는다. 공식 소스 위치를 안내한다(5.2) |

### 5.2 Qt·PySide6 소스 위치

번들의 Qt·PySide6는 6.12.0이고 고치지 않았다. 소스는 Qt 프로젝트가 공개한 v6.12.0 태그에 있다.

| 대상 | 위치(태그 v6.12.0) |
|---|---|
| PySide6·Shiboken6 | https://github.com/qtproject/pyside-pyside-setup/tree/v6.12.0 |
| Qt 6.12.0 전체(모듈 묶음) | https://github.com/qt/qt5/tree/v6.12.0 |
| Qt Base(QtCore·QtGui·QtWidgets) | https://github.com/qt/qtbase/tree/v6.12.0 |

- PyPI의 PySide6 6.12.0 메타데이터는 공식 저장소를 https://code.qt.io/cgit/pyside/pyside-setup.git/ 로 적는다. PyPI에는 소스 배포본(sdist)이 없다.
- 위 GitHub 주소는 Qt 프로젝트의 미러이고, 2026-11-05에 태그가 있는 것을 확인했다. 공식 배포처(download.qt.io)의 소스 압축 파일은 이 세션의 네트워크 제한으로 확인하지 못했다.
- GPLv3 6(d)(LGPL-3.0에 포함): 소스를 다른 서버에 두고 안내해도 되지만, 필요한 기간 동안 받을 수 있게 할 책임은 배포자에게 남는다. 공개 릴리스 때 소스 압축 파일을 Release에 함께 올릴지 정한다(7장).

### 5.3 GPL 전용 Qt 모듈

Qt 6.12에서 오픈소스로는 GPL-3.0(또는 상용)으로만 제공되는 모듈이다. MIT 앱에 묶으면 배포 전체가 GPL 조건을 따라야 한다.

- Qt Licensing 페이지 목록: Canvas Painter, CoAP, Graphs, GRPC, HTTP Server, Lottie Animation, MQTT, Network Authorization, Qml Compiler, Quick 3D, Quick 3D Physics, Quick Timeline, Virtual Keyboard, Wayland Compositor.
- 목록에는 없지만 모듈 페이지가 GPL-3.0 전용이라고 하는 것: Charts, Data Visualization.
- Qt Designer(`Qt6Designer.dll`, `Qt6DesignerComponents.dll`, `designer.exe`)는 GPL-3.0 + Qt GPL 예외다. 예외는 도구가 만든 출력에만 해당해서 링크하면 GPL이다. Essentials 휠에 들어 있다.
- Qt 3D의 QML 플러그인(`quick3dcoreplugin` 등)과 `Qt6Quick3DSpatialAudio`는 이름에 quick3d가 있지만 LGPL이라 빌드 검사에서 걸리지 않게 했다.

| 막는 곳 | 방법 |
|---|---|
| 코드 | `tests/unit/test_architecture.py`가 PySide6.QtCanvasPainter, QtCharts, QtDataVisualization, QtDesigner, QtGraphs, QtGraphsWidgets, QtHttpServer, QtNetworkAuth, QtQuick3D import를 막는다. 쓰지 않을 WebEngine, Pdf, Network도 막는다 |
| 빌드 수집 | Essentials 휠의 `platforminputcontexts/qtvirtualkeyboardplugin`(Virtual Keyboard)은 import하지 않아도 PyInstaller의 QtGui 훅이 모은다. 의존 라이브러리(Qt6VirtualKeyboard)가 Addons에 있어 메타 패키지를 쓰면 해결되기 때문이다. `packaging/hooks/hook-PySide6.QtGui.py`가 이 플러그인과 PDF 이미지 플러그인(qpdf)을 빼고 모은다 |
| 빌드 검사 | `packaging/autotrader.spec`은 GPL 전용 Qt 바이너리 이름이 번들 목록에 남아 있으면 빌드를 멈춘다 |

- 2단계 Linux 빌드로 확인: 훅이 없으면 `libqtvirtualkeyboardplugin.so`, `libQt6VirtualKeyboard.so.6`, `libQt6VirtualKeyboardQml.so.6`이 들어갔고 빌드 검사가 멈췄다. 훅을 넣은 뒤에는 이 파일과 함께 끌려오던 Qt6Qml·Qt6Quick·Qt6Pdf도 빠졌다(190MB, 6/6 self-test 통과). Windows 빌드(build-exe, 2026-11-05)도 빌드 검사를 통과했다.
- Windows용 Essentials 휠에는 이 밖에도 GPL 전용 파일이 있다: `Qt6Lottie*.dll`, `Qt6QmlCompiler.dll`, `Qt6QuickTimeline*.dll`, `plugins/vectorimageformats/qlottievectorimage.dll`, `plugins/qmltooling/qmldbg_quick3dprofiler.dll`, `qml/QtQuick/VirtualKeyboard/`의 `qtvkb*plugin.dll`. PyInstaller는 QML·Quick 모듈을 import할 때 이것들을 모은다. QML을 쓰게 되면 빌드 검사 결과를 다시 확인한다.
- `Qt6Quick3DSpatialAudio.dll`은 Qt Multimedia 소속(LGPL-3.0)이라 빌드 검사에서 뺐다. 다만 GPL 전용인 Quick 3D에 의존하므로 함께 들어오면 그쪽이 걸린다.
- Windows의 한국어 입력(IME)은 플랫폼 플러그인(qwindows)이 처리하므로 입력 플러그인을 빼도 된다.
- 대시보드에 차트가 필요하면 QPainter로 그리거나 LGPL 이하 라이브러리를 쓴다(Charts·Graphs 금지).

## 6. 번들 안 위치

`NOTICE.txt`는 exe 옆(`dist/autotrader/`)에, 나머지는 `dist/autotrader/_internal/` 아래에 있다.

| 경로 | 내용 |
|---|---|
| `NOTICE.txt`(exe 옆) | Qt·PySide6를 LGPL-3.0으로 쓴다는 고지, 라이선스 사본·소스 위치, 아래 파일 안내 |
| `licenses/LICENSE` | 이 앱(MIT) |
| `licenses/dependency-licenses.md` | 이 문서 |
| `licenses/LGPL-3.0.txt`, `licenses/GPL-3.0.txt` | Qt·PySide6 |
| `licenses/pyinstaller/`, `licenses/pyinstaller-hooks-contrib/` | PyInstaller |
| `licenses/python/` | CPython과 포함된 외부 소프트웨어 |
| `<패키지>-<버전>.dist-info/` | 런타임 패키지 메타데이터와 라이선스 파일(keyring, jaraco.*, more-itertools, pywin32-ctypes 등) |
| `PySide6/`, `shiboken6/` | Qt·PySide6 DLL과 Python 파일(`.py`). 사용자가 바꿀 수 있다 |

## 7. 남은 일

| 항목 | 시점 |
|---|---|
| Qt 라이브러리 안의 서드파티 코드(HarfBuzz, FreeType, libpng, libjpeg, PCRE2 등) 고지. Qt 문서는 실제로 배포하는 구성 요소만 고지하면 된다고 한다. 번들에 든 DLL·플러그인 기준으로 정리한다 | 릴리스(8단계) 전 |
| 정보 화면(SCR-11)에서 이 고지들을 보여 주기 | 6단계 |
| 공개 릴리스 때 Qt·PySide6 소스 압축 파일을 Release에 함께 올릴지(5.2, GPLv3 6(d)) | 릴리스(8단계) 전 |
| Windows 빌드의 Python이 python.org 빌드가 아니면 `LICENSE.txt` 위치가 다를 수 있다. 빌드 로그에 "Python LICENSE.txt를 찾지 못해" 경고가 없는지 본다(2026-11-05 빌드는 python.org 3.13.17이라 경고 없음) | Windows 빌드마다 |
| (결정됨) PySide6 메타 패키지를 그대로 쓴다(D-064). Essentials만 의존하는 안은 빌드 환경 설치 크기만 줄이고 배포 번들의 크기·라이선스는 같다 | 2026-11-05 결정 |

## 8. 근거 (2026-11-05 확인)

| 내용 | 출처 |
|---|---|
| 패키지 라이선스 | 설치된 휠의 `*.dist-info` 메타데이터·라이선스 파일. Windows·macOS 전용 패키지(pywin32-ctypes, pefile, colorama, macholib)는 PyPI의 휠을 받아 라이선스 파일 확인 |
| Qt 모듈별 라이선스 | Qt 6.12 Licensing 페이지(doc.qt.io/qt-6/licensing.html)의 원본 `qtdoc` v6.12.0 `doc/src/legal/licenses.qdoc`, 각 모듈 저장소 v6.12.0의 문서·`licenseRule.json` |
| Essentials 휠의 가상 키보드 플러그인 | PySide6_Essentials 6.12.0 휠의 RECORD, 2단계 Linux 빌드 결과 |
| Windows용 Essentials 휠의 파일 목록 | PyPI에서 `pyside6_essentials-6.12.0-cp310-abi3-win_amd64.whl`을 받아 확인 |
| `Qt6Quick3DSpatialAudio` 라이선스 | qtmultimedia v6.12.0 `licenseRule.json`(`src/spatialaudioquick3d/`) |
| LGPL-3.0 4절, GPLv3 6절 | `packaging/licenses/`의 원문(qtbase v6.12.0 `LICENSES/`) |
| PySide6 공식 저장소 | PyPI의 PySide6 6.12.0 메타데이터(project_urls) |
| PyInstaller | 6.22.3 휠의 `COPYING.txt`, pyinstaller-hooks-contrib 2026.9의 `LICENSE` |
| CPython | docs.python.org/3.13/license.html의 원본 `Doc/license.rst`(v3.13.18), Windows `LICENSE.txt` 구성(`PCbuild/regen.targets`) |
