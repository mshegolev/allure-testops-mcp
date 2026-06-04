"""Version single-source-of-truth guard (v0.4 Phase 3).

`pyproject.toml` is the one canonical version. This test fails if any other
declared location drifts from it — the regression that bit us when
`__init__.py` sat at 0.1.2 while the package was already 0.2.1.

Covered:
- `server.json` top-level `.version` == pyproject version.
- `server.json` `.packages[0].version` == pyproject version.
- `allure_testops_mcp.__version__` is derived from installed metadata, so it
  either equals pyproject (installed) or is the explicit source-run sentinel
  (never a hand-typed literal that can silently drift).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised only on 3.10
    import tomli as tomllib  # type: ignore[no-redef]

_ROOT = Path(__file__).resolve().parent.parent


def _pyproject_version() -> str:
    data = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return data["project"]["version"]


def _server_json() -> dict:
    return json.loads((_ROOT / "server.json").read_text(encoding="utf-8"))


def test_server_json_top_level_matches_pyproject() -> None:
    assert _server_json()["version"] == _pyproject_version()


def test_server_json_package_matches_pyproject() -> None:
    packages = _server_json()["packages"]
    assert packages, "server.json must declare at least one package"
    assert packages[0]["version"] == _pyproject_version()


def test_dunder_version_does_not_drift() -> None:
    """__version__ must come from metadata, not a hand-typed literal.

    When the package is installed (CI, wheel smoke-test), it equals the
    pyproject version. When running from a bare source checkout without an
    install, importlib.metadata can't find it, so __init__ falls back to the
    explicit ``0+unknown`` sentinel — which is acceptable precisely because it
    is *not* a stale real-looking version someone forgot to bump.
    """
    import allure_testops_mcp

    version = allure_testops_mcp.__version__
    assert version in (_pyproject_version(), "0+unknown"), (
        f"__version__={version!r} is neither the pyproject version nor the "
        "source-run sentinel — it looks hand-edited and may have drifted"
    )
