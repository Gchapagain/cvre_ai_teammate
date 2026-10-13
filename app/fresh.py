"""Keep a running app from mixing old and new code.

Streamlit re-runs streamlit_app.py when a file changes, but it can keep modules it
already imported. That once left a new screen calling a function that only existed
in the new version of another module. ensure() spots any changed source file and
forgets all of our modules, so the next imports load everything fresh together.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGES = ("app", "services")
SINGLE_MODULES = ("db",)

_seen = {}  # source file -> modified time when our modules were last loaded


def source_times(root=ROOT):
    files = [root / f"{name}.py" for name in SINGLE_MODULES]
    for package in PACKAGES:
        files += (root / package).rglob("*.py")
    return {str(path): path.stat().st_mtime for path in files if path.exists()}


def forget_our_modules():
    for name in list(sys.modules):
        if name in SINGLE_MODULES or name.split(".")[0] in PACKAGES:
            del sys.modules[name]


def ensure(root=ROOT):
    """Call before importing app code. Returns True if stale modules were dropped."""
    current = source_times(root)
    stale = bool(_seen) and _seen != current
    if stale:
        forget_our_modules()
    _seen.clear()
    _seen.update(current)
    return stale
