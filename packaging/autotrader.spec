# PyInstaller 설정. CLAUDE.md "CI 계약"을 따른다.
#   - 폴더형(onedir), 창 모드(windowed), UPX 끔
#   - 결과: dist/autotrader/autotrader.exe
# 실행(저장소 루트에서): uv run pyinstaller packaging/autotrader.spec --noconfirm --clean
#
# exe 옆에 NOTICE.txt(LGPL-3.0 4(a)의 눈에 띄는 고지)를 두고,
# 라이선스 원문과 목록은 dist/autotrader/_internal/licenses/ 아래에 넣는다:
#   이 앱의 LICENSE(MIT), 의존성 라이선스 목록, LGPL-3.0·GPL-3.0 원문(PySide6·Qt),
#   PyInstaller(부트로더·런타임 훅)와 Python 런타임(및 Python에 포함된 외부 소프트웨어)의 라이선스.
# 런타임 패키지 각자의 라이선스 파일은 *.dist-info 폴더째 들어간다.
# 근거: docs/07-security-legal/dependency-licenses.md

import importlib.metadata
import re
import shutil
import sys
import sysconfig
import tomllib
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules, copy_metadata

ROOT = Path(SPECPATH).resolve().parent
SRC = ROOT / "src"
LICENSES = "licenses"

# 오픈소스로는 GPL-3.0(또는 상용)으로만 제공되는 Qt 모듈의 바이너리 이름. 하나라도 번들에 들어가면
# 배포 전체가 GPL 조건을 따라야 하므로 빌드를 멈춘다. Qt 6.12 Licensing 페이지의 목록에
# 모듈 페이지 기준 GPL 전용인 Charts, Data Visualization을 더했다.
# Qt6Quick3DSpatialAudio는 Qt Multimedia 소속(LGPL-3.0)이라 뺀다(GPL 전용인 Quick 3D에 의존한다).
GPL_ONLY_QT_BINARY = re.compile(
    r"canvaspainter|coap|qt6graphs|graphswidgets|grpc|httpserver|lottie|mqtt|networkauth"
    r"|qmlcompiler|quick3d(?!spatialaudio)|quicktimeline|virtualkeyboard|qtvkb|waylandcompositor"
    r"|qt6charts|chartsqml|datavisualization",
    re.IGNORECASE,
)


def runtime_distributions():
    """pyproject.toml의 런타임 의존성 이름(버전 조건을 뗀 것)."""
    with (ROOT / "pyproject.toml").open("rb") as file:
        requirements = tomllib.load(file)["project"]["dependencies"]
    return [re.split(r"[\s;\[<>=!~]", requirement, maxsplit=1)[0] for requirement in requirements]


def canonical(name):
    """배포판 이름 정규화(PEP 503)."""
    return re.sub(r"[-_.]+", "-", name).lower()


def runtime_closure():
    """런타임 의존성과 그 의존성 중 이 플랫폼에 설치되는 것의 정규화 이름."""
    from packaging.requirements import Requirement  # 빌드 환경에만 있으면 된다(PyInstaller 의존성)

    todo = list(runtime_distributions())
    seen = set()
    while todo:
        name = canonical(todo.pop())
        if name in seen:
            continue
        seen.add(name)
        for text in importlib.metadata.distribution(name).requires or []:
            requirement = Requirement(text)
            if requirement.marker is None or requirement.marker.evaluate({"extra": ""}):
                todo.append(requirement.name)
    return seen


def foreign_modules(module_names, owners, allowed):
    """번들 모듈 중 allowed 밖의 배포판(개발·빌드 전용)이 설치한 최상위 모듈.

    표준 라이브러리 모듈은 owners(packages_distributions)에 없으므로 걸리지 않는다.
    """
    found = set()
    for module_name in module_names:
        top = module_name.split(".")[0]
        distributions = {canonical(d) for d in owners.get(top, [])}
        if distributions and not distributions & allowed:
            found.add(top)
    return sorted(found)


def license_files(distribution):
    dist = importlib.metadata.distribution(distribution)
    names = ("LICENSE", "LICENCE", "COPYING", "NOTICE")
    return [Path(dist.locate_file(f)) for f in dist.files or [] if f.name.upper().startswith(names)]


def python_license_files():
    stdlib = Path(sysconfig.get_paths()["stdlib"])
    for candidate in (Path(sys.base_prefix) / "LICENSE.txt", stdlib / "LICENSE.txt"):
        if candidate.is_file():
            return [candidate]
    print("WARNING: Python LICENSE.txt를 찾지 못해 licenses/python에 넣지 못했습니다.")
    return []


datas = [
    (str(ROOT / "LICENSE"), LICENSES),
    (str(ROOT / "docs" / "07-security-legal" / "dependency-licenses.md"), LICENSES),
    (str(ROOT / "packaging" / "licenses" / "LGPL-3.0.txt"), LICENSES),
    (str(ROOT / "packaging" / "licenses" / "GPL-3.0.txt"), LICENSES),
]
for name in runtime_distributions():
    datas += copy_metadata(name, recursive=True)
# exe에 PyInstaller 부트로더(GPL + 예외)와 런타임 훅(Apache-2.0)이 들어간다.
for tool in ("pyinstaller", "pyinstaller-hooks-contrib"):
    datas += [(str(path), f"{LICENSES}/{tool}") for path in license_files(tool)]
# Python 런타임: 빌드에 쓴 Python의 LICENSE.txt와, 거기에 빠진 외부 소프트웨어(expat, libmpdec,
# mimalloc, HACL* 등)의 고지.
datas += [(str(path), f"{LICENSES}/python") for path in python_license_files()]
for name in ("cpython-3.13.18-license.rst", "hacl-star-MIT.txt"):
    datas.append((str(ROOT / "packaging" / "licenses" / name), f"{LICENSES}/python"))

a = Analysis(
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(SRC)],
    binaries=[],
    datas=datas,
    # self-test가 앱 모듈을 모두 import해 보므로, 동적으로만 쓰이는 모듈도 빠짐없이 넣는다.
    hiddenimports=collect_submodules("autotrader"),
    # GPL 전용 Qt 플러그인을 모으지 않는 QtGui 훅(packaging/hooks/hook-PySide6.QtGui.py)
    hookspath=[str(ROOT / "packaging" / "hooks")],
    hooksconfig={},
    runtime_hooks=[],
    # PyInstaller의 jaraco 네임스페이스 처리가 setuptools(벤더링한 jaraco)를 끌어와
    # 개발·빌드 전용 패키지가 번들에 들어간다. 앱은 쓰지 않는다
    # (typing_extensions는 jaraco가 타입 검사 때만 import한다).
    excludes=["setuptools", "_distutils_hack", "pkg_resources", "packaging", "typing_extensions"],
    noarchive=False,
    optimize=0,
)

gpl_only = sorted(
    dest
    for dest, _source, _kind in (*a.binaries, *a.datas)
    if dest.replace("\\", "/").startswith("PySide6/") and GPL_ONLY_QT_BINARY.search(Path(dest).name)
)
if gpl_only:
    raise SystemExit("GPL 전용 Qt 바이너리가 번들에 들어갔습니다:\n  " + "\n  ".join(gpl_only))

# 라이선스 목록은 개발·빌드 전용 패키지를 "배포하지 않음"으로 적는다. 번들 모듈로 이를 확인한다.
dev_only = foreign_modules(
    (module_name for module_name, _source, _kind in a.pure),
    importlib.metadata.packages_distributions(),
    runtime_closure() | {"upbit-autotrader"},
)
if dev_only:
    raise SystemExit("개발·빌드 전용 패키지가 번들에 들어갔습니다: " + ", ".join(dev_only))

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="autotrader",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="autotrader",
)

# LGPL-3.0 4(a): 사본마다 Qt를 LGPL로 쓴다는 고지를 눈에 띄게 둔다.
# COLLECT가 폴더를 만든 뒤에 복사한다.
shutil.copy2(ROOT / "packaging" / "NOTICE.txt", Path(coll.name) / "NOTICE.txt")

# NOTICE.txt가 가리키는 파일이 실제로 들어갔는지 확인한다.
contents = Path(coll.name) / (exe.contents_directory or ".")
missing = [
    relative
    for relative in (
        "licenses/LICENSE",
        "licenses/LGPL-3.0.txt",
        "licenses/GPL-3.0.txt",
        "licenses/dependency-licenses.md",
        "PySide6",
        "shiboken6",
    )
    if not (contents / relative).exists()
]
if missing:
    raise SystemExit("NOTICE.txt가 가리키는 파일이 번들에 없습니다: " + ", ".join(missing))
