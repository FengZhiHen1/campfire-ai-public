"""api-server test path setup."""

from __future__ import annotations

import os
import sys

_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

# Add packages to path
_packages_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "packages"))
for pkg in [
    "py-config",
    "py-db",
    "py-schemas",
    "py-rag",
    "py-llm",
    "py-cache",
    "py-storage",
    "py-auth",
    "py-logger",
    "py-security",
    "py-health",
]:
    pkg_path = os.path.join(_packages_root, pkg)
    if os.path.isdir(pkg_path) and pkg_path not in sys.path:
        sys.path.insert(0, pkg_path)
