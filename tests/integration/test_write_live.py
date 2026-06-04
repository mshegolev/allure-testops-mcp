"""Live-instance integration tests for the write tools (v0.4 Phase 2).

These exercise the real create -> update -> delete lifecycle against an actual
Allure TestOps project. They are:

* **Deselected by default** — marked ``integration``; ``addopts = -m 'not
  integration'`` in pyproject keeps ``pytest`` and CI green without them.
* **Self-skipping** — if the required env vars are absent they skip (never
  fail), so running ``pytest -m integration`` on a machine without credentials
  is a no-op rather than a red build.

To run against a real instance::

    export ALLURE_URL=https://allure.example.com
    export ALLURE_TOKEN=...                 # token with write scope
    export ALLURE_ENABLE_WRITE=true
    export ALLURE_TEST_PROJECT_ID=63        # a throwaway project you can write to
    # optional, to verify Phase 1 once implemented:
    # export ALLURE_TEST_STATUS=Draft
    # export ALLURE_TEST_LAYER=API
    pytest -m integration tests/integration -v

This suite is also the verification vehicle for the still-blocked Phase 1
(name->id lookup) and the Phase 4 PATCH/PUT fallback: once credentials exist,
``test_create_update_delete_lifecycle`` proves the verb fallback end-to-end and
``test_status_layer_by_name`` proves name-based refs resolve on the target
deployment.
"""

from __future__ import annotations

import os

import pytest

_REQUIRED = ("ALLURE_URL", "ALLURE_TOKEN", "ALLURE_ENABLE_WRITE", "ALLURE_TEST_PROJECT_ID")
_missing = [name for name in _REQUIRED if not os.environ.get(name)]
if not _missing and os.environ.get("ALLURE_ENABLE_WRITE", "").strip().lower() in ("false", "0", "no", "off", ""):
    _missing.append("ALLURE_ENABLE_WRITE=true")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        bool(_missing),
        reason=f"live Allure credentials not configured (missing: {', '.join(_missing)})",
    ),
]


@pytest.fixture(scope="module")
def project_id() -> int:
    return int(os.environ["ALLURE_TEST_PROJECT_ID"])


@pytest.fixture()
def write_tools():
    """Import the write tools with the live client.

    Imported lazily inside the fixture so the module import never triggers a
    client build when the suite is skipped.
    """
    from allure_testops_mcp import tools_write

    return tools_write


def _structured(result):
    """Unwrap a FastMCP CallToolResult to its structured payload."""
    return result.structuredContent


def test_create_update_delete_lifecycle(write_tools, project_id):
    """Full round-trip against the live instance.

    Proves: create returns a real id; update succeeds (exercising the
    PATCH->PUT fallback transparently on whatever verb this deployment
    supports); delete removes it.
    """
    created = _structured(
        write_tools.allure_create_test_case(
            project_id=project_id,
            name="[mcp-integration] lifecycle probe",
            automated=False,
        )
    )
    tc_id = created["id"]
    assert tc_id >= 1

    try:
        updated = _structured(
            write_tools.allure_update_test_case(
                test_case_id=tc_id,
                name="[mcp-integration] lifecycle probe (renamed)",
            )
        )
        assert updated["id"] == tc_id
        assert "name" in updated["updated_fields"]
    finally:
        deleted = _structured(write_tools.allure_delete_test_case(test_case_id=tc_id, confirm=True))
        assert deleted == {"id": tc_id, "deleted": True}


@pytest.mark.skipif(
    not (os.environ.get("ALLURE_TEST_STATUS") and os.environ.get("ALLURE_TEST_LAYER")),
    reason="set ALLURE_TEST_STATUS and ALLURE_TEST_LAYER to verify name-based refs (Phase 1)",
)
def test_status_layer_by_name(write_tools, project_id):
    """Verify the target deployment accepts name-based status/layer refs.

    If this FAILS with HTTP 400 on a given instance, that is the concrete
    evidence that Phase 1 (name->id lookup) is required for that deployment.
    """
    status = os.environ["ALLURE_TEST_STATUS"]
    layer = os.environ["ALLURE_TEST_LAYER"]
    created = _structured(
        write_tools.allure_create_test_case(
            project_id=project_id,
            name="[mcp-integration] name-ref probe",
            status=status,
            layer=layer,
            tags=["mcp-integration"],
        )
    )
    tc_id = created["id"]
    write_tools.allure_delete_test_case(test_case_id=tc_id, confirm=True)
