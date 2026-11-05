"""Make this folder and research/rules importable for pytest in any import mode."""

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _path in (_HERE, _HERE.parent / "rules"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))
