# PyInstaller 기본 훅(hook-PySide6.QtGui)과 같되, 아래 Qt 플러그인을 모으지 않는다.
# 사용자 훅(hookspath)이 기본 훅보다 우선한다.
#
# - platforminputcontexts/qtvirtualkeyboardplugin: Qt Virtual Keyboard(GPL-3.0 전용).
#   PySide6 메타 패키지가 PySide6_Addons(Qt6VirtualKeyboard 라이브러리)를 함께 설치하면
#   기본 훅이 이 플러그인과 의존성(Qt6VirtualKeyboard, Qt6Qml, Qt6Quick 등)을 번들에 넣는다.
#   Windows의 한국어 입력(IME)은 플랫폼 플러그인(qwindows)이 처리하므로 필요 없다.
# - imageformats/qpdf: PDF 이미지 형식(Qt PDF, PDFium). 쓰지 않는다.
#
# 근거: docs/07-security-legal/dependency-licenses.md

from pathlib import Path

from PyInstaller.utils.hooks.qt import add_qt6_dependencies


def _excluded(source: str) -> bool:
    name = Path(source).name.lower().removeprefix("lib")
    return "virtualkeyboard" in name or name.startswith("qpdf")


hiddenimports, binaries, datas = add_qt6_dependencies(__file__)
binaries = [entry for entry in binaries if not _excluded(entry[0])]
