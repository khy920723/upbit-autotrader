"""packaging/autotrader.spec가 CI 계약을 지키는지 본다.

계약: onedir, windowed, UPX 끔, 결과는 dist/autotrader/autotrader.exe.

Windows 빌드는 build-exe.yml에서만 돌기 때문에, 설정 회귀를 Linux 테스트에서 먼저 잡는다.
"""

import ast
import re
from pathlib import Path

import pytest

SPEC_CALLS = ("Analysis", "PYZ", "EXE", "COLLECT")


@pytest.fixture
def spec_text(repo_root) -> str:
    return (repo_root / "packaging" / "autotrader.spec").read_text(encoding="utf-8")


@pytest.fixture
def calls(spec_text) -> dict[str, ast.Call]:
    found: dict[str, ast.Call] = {}
    for node in ast.walk(ast.parse(spec_text)):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in SPEC_CALLS
        ):
            assert node.func.id not in found, f"{node.func.id}가 두 번 나온다"
            found[node.func.id] = node
    assert set(found) == set(SPEC_CALLS)
    return found


def keyword_node(call: ast.Call, name: str) -> ast.expr:
    for kw in call.keywords:
        if kw.arg == name:
            return kw.value
    raise AssertionError(f"{name}= 인자가 없다")


def keyword(call: ast.Call, name: str):
    return ast.literal_eval(keyword_node(call, name))


def path_parts(node: ast.expr) -> tuple[str, ...]:
    """`str(ROOT / "a" / "b")` 같은 경로 식의 문자열 조각을 왼쪽부터 모은다."""
    if isinstance(node, ast.Call) and node.args:
        return path_parts(node.args[0])
    if isinstance(node, ast.BinOp):
        return path_parts(node.left) + path_parts(node.right)
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return (node.value,)
    return ()


def module_statements(spec_text: str) -> list[ast.stmt]:
    """주석 처리된 줄은 빠진, 실제로 실행되는 최상위 문장들."""
    return ast.parse(spec_text).body


def datas_entries(spec_text: str) -> set[tuple[tuple[str, ...], str]]:
    """`datas = [...]`의 (경로 조각, 대상 폴더) 집합."""
    for node in module_statements(spec_text):
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "datas" for target in node.targets
        ):
            return {
                (path_parts(element.elts[0]), ast.unparse(element.elts[1]))
                for element in node.value.elts
            }
    raise AssertionError("spec에 datas 목록이 없다")


def test_exe_is_a_windowed_autotrader_exe_without_upx(calls):
    exe = calls["EXE"]

    assert keyword(exe, "name") == "autotrader"
    assert keyword(exe, "console") is False
    assert keyword(exe, "upx") is False


def test_build_is_onedir(calls):
    exe = calls["EXE"]
    passed = {ast.unparse(arg) for arg in exe.args}

    assert keyword(exe, "exclude_binaries") is True
    assert "a.binaries" not in passed
    assert "a.datas" not in passed
    assert keyword(calls["COLLECT"], "name") == "autotrader"
    assert keyword(calls["COLLECT"], "upx") is False


def test_entry_script_is_the_launcher_outside_the_package(calls, repo_root):
    assert "launcher.py" in ast.unparse(calls["Analysis"].args[0])

    tree = ast.parse((repo_root / "packaging" / "launcher.py").read_text(encoding="utf-8"))
    imports = [
        (node.module, [alias.name for alias in node.names])
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    ]
    assert ("autotrader.__main__", ["main"]) in imports


@pytest.mark.parametrize(
    ("relative_path", "first_line"),
    [
        ("packaging/licenses/LGPL-3.0.txt", "GNU LESSER GENERAL PUBLIC LICENSE"),
        ("packaging/licenses/GPL-3.0.txt", "GNU GENERAL PUBLIC LICENSE"),
        ("LICENSE", "MIT License"),
        ("packaging/licenses/cpython-3.13.18-license.rst", ".. highlight:: none"),
        ("packaging/licenses/hacl-star-MIT.txt", "HACL* - CPython 3.13 Modules/_hacl/*.c"),
        ("docs/07-security-legal/dependency-licenses.md", "# 의존성 라이선스 목록"),
    ],
)
def test_license_notice_files_have_the_expected_text(repo_root, relative_path, first_line):
    path = repo_root / relative_path

    first = next(
        line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    )
    assert first.startswith(first_line)


@pytest.mark.parametrize(
    "parts",
    [
        ("LICENSE",),
        ("docs", "07-security-legal", "dependency-licenses.md"),
        ("packaging", "licenses", "LGPL-3.0.txt"),
        ("packaging", "licenses", "GPL-3.0.txt"),
    ],
)
def test_license_texts_are_listed_in_datas(spec_text, parts):
    assert (parts, "LICENSES") in datas_entries(spec_text)


def test_python_notices_are_appended_to_datas(spec_text):
    loops = [
        node
        for node in module_statements(spec_text)
        if isinstance(node, ast.For) and isinstance(node.iter, ast.Tuple)
    ]
    names = {
        element.value
        for loop in loops
        for element in loop.iter.elts
        if isinstance(element, ast.Constant)
        and any("datas.append" in ast.unparse(statement) for statement in loop.body)
    }

    assert {"cpython-3.13.18-license.rst", "hacl-star-MIT.txt"} <= names


def test_license_texts_are_version_3(repo_root):
    for name in ("LGPL-3.0.txt", "GPL-3.0.txt"):
        text = (repo_root / "packaging" / "licenses" / name).read_text(encoding="utf-8")
        assert "Version 3, 29 June 2007" in text, name


# --- GPL 전용 Qt 바이너리 차단 -------------------------------------------------------


@pytest.fixture
def gpl_only_pattern(spec_text) -> re.Pattern[str]:
    for node in ast.walk(ast.parse(spec_text)):
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "GPL_ONLY_QT_BINARY"
            for target in node.targets
        ):
            return re.compile(ast.literal_eval(node.value.args[0]), re.IGNORECASE)
    raise AssertionError("spec에 GPL_ONLY_QT_BINARY가 없다")


@pytest.fixture
def hook_excludes(repo_root):
    """훅 파일에서 _excluded 함수만 꺼내 실행한다(훅 전체는 PyInstaller 분석을 돌린다)."""
    source = (repo_root / "packaging" / "hooks" / "hook-PySide6.QtGui.py").read_text(
        encoding="utf-8"
    )
    function = next(
        node
        for node in ast.parse(source).body
        if isinstance(node, ast.FunctionDef) and node.name == "_excluded"
    )
    namespace = {"Path": Path}
    exec(compile(ast.Module(body=[function], type_ignores=[]), "hook", "exec"), namespace)
    return namespace["_excluded"]


@pytest.mark.parametrize(
    "name",
    [
        "qtvirtualkeyboardplugin.dll",
        "qtvkbplugin.dll",
        "Qt6VirtualKeyboard.dll",
        "libQt6VirtualKeyboardQml.so.6",
        "Qt6Charts.dll",
        "Qt6ChartsQml.dll",
        "Qt6DataVisualization.dll",
        "Qt6Graphs.dll",
        "Qt6GraphsWidgets.dll",
        "Qt6HttpServer.dll",
        "Qt6NetworkAuth.dll",
        "Qt6Quick3D.dll",
        "Qt6Quick3DPhysics.dll",
        "Qt6Quick3DRuntimeRender.dll",
        "qmldbg_quick3dprofiler.dll",
        "qlottievectorimage.dll",
        "Qt6QuickTimeline.dll",
        "Qt6CanvasPainter.dll",
        "Qt6Lottie.dll",
        "Qt6Mqtt.dll",
        "Qt6Coap.dll",
        "Qt6Grpc.dll",
        "Qt6QmlCompiler.dll",
        "Qt6WaylandCompositor.dll",
        "Qt6Designer.dll",
        "Qt6DesignerComponents.dll",
        "designer.exe",
        "qquick3dplugin.dll",
        "qtquick3dhelpersplugin.dll",
        "assimp.dll",
    ],
)
def test_guard_flags_gpl_only_qt_binaries(gpl_only_pattern, name):
    assert gpl_only_pattern.search(name)


@pytest.mark.parametrize(
    "name",
    [
        "Qt6Core.dll",
        "Qt6Gui.dll",
        "Qt6Widgets.dll",
        "Qt6Svg.dll",
        "Qt6Network.dll",
        "Qt6Qml.dll",
        "Qt6Quick.dll",
        "Qt6QuickControls2.dll",
        "Qt6OpenGL.dll",
        "Qt6Pdf.dll",
        "Qt6SpatialAudio.dll",
        "Qt6Quick3DSpatialAudio.dll",
        "quick3dspatialaudioplugin.dll",
        "quick3dcoreplugin.dll",
        "quick3drenderplugin.dll",
        "quick3dextrasplugin.dll",
        "Qt6UiTools.dll",
        "libQt6WaylandClient.so.6",
        "qwindows.dll",
        "qoffscreen.dll",
        "qsvgicon.dll",
        "qmodernwindowsstyle.dll",
        "pyside6.abi3.dll",
        "shiboken6.abi3.dll",
    ],
)
def test_guard_keeps_lgpl_qt_binaries(gpl_only_pattern, name):
    assert not gpl_only_pattern.search(name)


def test_spec_uses_the_custom_qtgui_hook(calls, repo_root):
    assert (repo_root / "packaging" / "hooks" / "hook-PySide6.QtGui.py").is_file()
    [hook_dir] = keyword_node(calls["Analysis"], "hookspath").elts
    assert path_parts(hook_dir) == ("packaging", "hooks")


@pytest.mark.parametrize(
    ("path", "excluded"),
    [
        ("C:/sp/PySide6/plugins/platforminputcontexts/qtvirtualkeyboardplugin.dll", True),
        ("/sp/PySide6/Qt/plugins/platforminputcontexts/libqtvirtualkeyboardplugin.so", True),
        ("C:/sp/PySide6/plugins/imageformats/qpdf.dll", True),
        ("/sp/PySide6/Qt/plugins/imageformats/libqpdf.so", True),
        ("C:/sp/PySide6/plugins/imageformats/qjpeg.dll", False),
        ("C:/sp/PySide6/plugins/imageformats/qsvg.dll", False),
        ("C:/sp/PySide6/plugins/platforms/qwindows.dll", False),
        ("/sp/PySide6/Qt/plugins/platforms/libqxcb.so", False),
    ],
)
def test_custom_hook_drops_virtual_keyboard_and_pdf_plugins(hook_excludes, path, excluded):
    assert hook_excludes(path) is excluded


# --- LGPL-3.0 4(a): exe 옆의 고지 ----------------------------------------------------


def test_notice_is_copied_next_to_the_exe(spec_text):
    copies = [
        node.value
        for node in module_statements(spec_text)
        if isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Call)
        and ast.unparse(node.value.func) == "shutil.copy2"
    ]

    assert [(path_parts(c.args[0]), ast.unparse(c.args[1])) for c in copies] == [
        (("packaging", "NOTICE.txt"), "Path(coll.name) / 'NOTICE.txt'")
    ]


def test_build_checks_that_notice_targets_exist(spec_text):
    checked = next(
        node.value
        for node in module_statements(spec_text)
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "missing" for target in node.targets)
    )
    constants = {c.value for c in ast.walk(checked) if isinstance(c, ast.Constant)}

    assert {
        "licenses/LICENSE",
        "licenses/LGPL-3.0.txt",
        "licenses/GPL-3.0.txt",
        "licenses/dependency-licenses.md",
        "PySide6",
        "shiboken6",
    } <= constants


@pytest.mark.parametrize(
    "needed",
    [
        "GNU LGPL",
        "6.12.0",
        r"_internal\PySide6",
        r"_internal\shiboken6",
        r"_internal\licenses\LICENSE",
        r"_internal\licenses\LGPL-3.0.txt",
        r"_internal\licenses\GPL-3.0.txt",
        r"_internal\licenses\dependency-licenses.md",
        "https://code.qt.io/cgit/pyside/pyside-setup.git/",
        "https://github.com/qt/qt5/tree/v6.12.0",
        "https://github.com/khy920723/upbit-autotrader",
    ],
)
def test_notice_names_the_lgpl_libraries_texts_and_sources(repo_root, needed):
    assert needed in (repo_root / "packaging" / "NOTICE.txt").read_text(encoding="utf-8")


# --- 개발·빌드 전용 패키지 차단 -----------------------------------------------------


def spec_function(spec_text: str, name: str):
    """spec에서 함수 하나만 꺼내 실행한다(spec 전체는 PyInstaller 안에서만 돈다)."""
    function = next(
        node
        for node in ast.parse(spec_text).body
        if isinstance(node, ast.FunctionDef) and node.name == name
    )
    namespace = {"re": re}
    exec(compile(ast.Module(body=[function], type_ignores=[]), "spec", "exec"), namespace)
    return namespace[name]


def test_analysis_excludes_build_only_packages(calls):
    excludes = keyword(calls["Analysis"], "excludes")

    assert {
        "setuptools",
        "_distutils_hack",
        "pkg_resources",
        "packaging",
        "PySide6.QtNetwork",
    } <= set(excludes)
    # typing_extensions는 anyio(httpx 의존성)가 런타임에 쓴다.
    assert "typing_extensions" not in excludes


def test_dev_only_guard_flags_modules_of_non_runtime_distributions(spec_text):
    canonical = spec_function(spec_text, "canonical")
    foreign_modules = spec_function(spec_text, "foreign_modules")
    foreign_modules.__globals__["canonical"] = canonical
    owners = {
        "keyring": ["keyring"],
        "jaraco": ["jaraco.classes", "jaraco.context"],
        "PySide6": ["PySide6_Essentials", "PySide6"],
        "setuptools": ["setuptools"],
        "_distutils_hack": ["setuptools"],
        "packaging": ["packaging"],
    }
    runtime = {"keyring", "jaraco-classes", "jaraco-context", "pyside6", "pyside6-essentials"}
    modules = [
        "keyring.backends.Windows",
        "jaraco.context",
        "PySide6.QtCore",
        "ssl",
        "autotrader.app.self_test",
        "setuptools._vendor.jaraco.text",
        "_distutils_hack.override",
        "packaging.version",
    ]

    assert foreign_modules(modules, owners, runtime) == [
        "_distutils_hack",
        "packaging",
        "setuptools",
    ]


def test_spec_checks_bundled_modules_against_runtime_dependencies(spec_text):
    guard = next(
        node
        for node in module_statements(spec_text)
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "dev_only" for target in node.targets)
    )

    assert ast.unparse(guard.value.func) == "foreign_modules"
    assert "importlib.metadata.packages_distributions()" in ast.unparse(guard.value)


# --- 그 밖의 번들 내용 --------------------------------------------------------------


def test_software_opengl_dll_is_dropped(spec_text):
    # opengl32sw.dll(Mesa llvmpipe, 20MB)은 위젯 앱에 필요 없고 고지 의무만 늘린다.
    drop = spec_function(spec_text, "without_software_opengl")
    binaries = [
        ("PySide6/opengl32sw.dll", "C:/sp/PySide6/opengl32sw.dll", "BINARY"),
        ("PySide6/Qt6Core.dll", "C:/sp/PySide6/Qt6Core.dll", "BINARY"),
    ]

    assert drop(binaries) == [binaries[1]]
    assert "a.binaries = without_software_opengl(a.binaries)" in spec_text


def test_pyside_python_parts_stay_replaceable(calls):
    # LGPL-3.0 4(d)(1): PySide6·shiboken6의 .py도 exe(PYZ) 밖에 두어 사용자가 바꿀 수 있게 한다.
    assert keyword(calls["Analysis"], "module_collection_mode") == {
        "PySide6": "py",
        "shiboken6": "py",
    }


def test_windows_build_rejects_binaries_from_outside_python_and_packages(spec_text):
    outside = spec_function(spec_text, "binaries_outside")
    roots = ["C:/Python313", "D:/a/repo/.venv/Lib/site-packages"]
    binaries = [
        ("python313.dll", "C:/Python313/python313.dll", "BINARY"),
        ("PySide6/Qt6Core.dll", "D:/a/repo/.venv/Lib/site-packages/PySide6/Qt6Core.dll", "BINARY"),
        ("libssl-3-x64.dll", "C:/Program Files/OpenSSL/bin/libssl-3-x64.dll", "BINARY"),
        # Microsoft Universal CRT: PyInstaller가 시스템에서 일부러 모은다(2026-11-05 Windows 빌드).
        ("ucrtbase.dll", "C:/Windows/System32/ucrtbase.dll", "BINARY"),
        (
            "api-ms-win-crt-runtime-l1-1-0.dll",
            "C:/Windows/System32/downlevel/api-ms-win-crt-runtime-l1-1-0.dll",
            "BINARY",
        ),
    ]

    assert outside(binaries, roots) == ["libssl-3-x64.dll"]
