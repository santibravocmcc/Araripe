"""The replay authenticates as the green account, or refuses — never as the blue one.

``scripts/replay_2026.py`` ran the 2026 replay on the owner's own
``earthengine authenticate`` credential. On a runner that credential does not
exist, and the bare ``ee.Initialize(project=…)`` fails with a misleading
"run earthengine authenticate". ``--service-account`` reads the green key from
``GEE_GREEN_SA_KEY`` and from nowhere else (PHASE_6E §1.5).
"""

from __future__ import annotations

import ast
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("replay_2026_sa", ROOT / "scripts" / "replay_2026.py")
replay = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(replay)

GREEN = "araripe-green-detect@ee-araripe.iam.gserviceaccount.com"
KEY = json.dumps({"type": "service_account", "client_email": GREEN,
                  "private_key": "-----BEGIN PRIVATE KEY-----\nsecret\n"})


class FakeEE:
    def __init__(self):
        self.calls = []

    def ServiceAccountCredentials(self, email, key_data):
        self.calls.append(("credentials", email, key_data))
        return ("credentials", email)

    def Initialize(self, credentials=None, project=None):
        self.calls.append(("initialize", credentials, project))


def test_without_the_flag_the_operator_credential_is_used_as_before(monkeypatch):
    """The 2026 replay's call, unchanged — and the green key is ignored."""

    monkeypatch.setenv("GEE_GREEN_SA_KEY", KEY)
    ee = FakeEE()
    replay.initialize_earth_engine(ee, project="ee-araripe", service_account=False)
    assert ee.calls == [("initialize", None, "ee-araripe")]


def test_with_the_flag_the_green_key_is_the_credential(monkeypatch, capsys):
    monkeypatch.setenv("GEE_GREEN_SA_KEY", KEY)
    ee = FakeEE()
    replay.initialize_earth_engine(ee, project="ee-araripe", service_account=True)
    assert ee.calls == [
        ("credentials", GREEN, KEY),
        ("initialize", ("credentials", GREEN), "ee-araripe"),
    ]
    out = capsys.readouterr().out
    assert GREEN in out
    assert "secret" not in out


@pytest.mark.parametrize("value", [None, "", "   "])
def test_a_missing_green_key_is_a_refusal_not_a_fallback(monkeypatch, value):
    """Kills: falling back to the interactive credential when the key is absent.

    That fallback works on the owner's laptop and fails on a runner, so the
    lane's identity would depend on where it ran.
    """

    if value is None:
        monkeypatch.delenv("GEE_GREEN_SA_KEY", raising=False)
    else:
        monkeypatch.setenv("GEE_GREEN_SA_KEY", value)
    ee = FakeEE()
    with pytest.raises(SystemExit, match="refusing to fall back"):
        replay.initialize_earth_engine(ee, project="ee-araripe", service_account=True)
    assert ee.calls == []


def test_the_blue_key_is_never_read(monkeypatch):
    """Kills: reading GEE_SA_KEY, or routing through gee_download.ee_initialize."""

    monkeypatch.delenv("GEE_GREEN_SA_KEY", raising=False)
    monkeypatch.setenv("GEE_SA_KEY", KEY)
    ee = FakeEE()
    with pytest.raises(SystemExit):
        replay.initialize_earth_engine(ee, project="ee-araripe", service_account=True)
    assert ee.calls == []
    # By the structure, not the text: the docstring names both on purpose, to
    # say why they are not used, and a text sweep flagged exactly that.
    tree = ast.parse((ROOT / "scripts" / "replay_2026.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        assert not (isinstance(node, ast.Constant) and node.value == "GEE_SA_KEY")
        if isinstance(node, ast.ImportFrom):
            assert "ee_initialize" not in {a.name for a in node.names}
        if isinstance(node, (ast.Name, ast.Attribute)):
            assert getattr(node, "id", getattr(node, "attr", None)) != "ee_initialize"


def test_an_unparsable_key_is_a_refusal(monkeypatch):
    monkeypatch.setenv("GEE_GREEN_SA_KEY", "not json")
    ee = FakeEE()
    with pytest.raises(SystemExit, match="not a service-account"):
        replay.initialize_earth_engine(ee, project="ee-araripe", service_account=True)
    assert ee.calls == []


def test_the_key_name_is_a_constant_and_not_an_argument():
    assert replay.GREEN_EE_KEY_VAR == "GEE_GREEN_SA_KEY"
    tree = ast.parse((ROOT / "scripts" / "replay_2026.py").read_text(encoding="utf-8"))
    bare = [
        node.lineno for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute) and node.func.attr == "Initialize"
        and not node.args
    ]
    # exactly one bare Initialize: the operator branch inside the helper
    assert len(bare) == 1, f"a bare Initialize outside the helper bypasses --service-account: {bare}"
