"""The green Earth Engine probe must fail when the identity is wrong or too wide.

Two of its checks are inverted -- creating an asset and starting an export must
be REFUSED -- and an inverted check with the polarity wrong is worse than none:
it would report PASS for exactly the over-scoped identity it exists to catch.
So each polarity is asserted in both directions, and a refusal for the wrong
reason is asserted to be a failure, because it proves nothing about scope.

No network: Earth Engine is replaced by ``FakeEE`` and HTTP by a stub.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "probe_gee_green_identity.py"
WORKFLOW = ROOT / ".github" / "workflows" / "v2_gee_green_identity_probe.yml"

SPEC = importlib.util.spec_from_file_location("probe_gee_green_identity", SCRIPT)
assert SPEC and SPEC.loader
probe = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = probe
SPEC.loader.exec_module(probe)

PRIVATE = "-----BEGIN PRIVATE KEY-----\nverysecretmaterial\n-----END PRIVATE KEY-----\n"
TIFF = b"II*\x00" + b"\x00" * 64


def key(email=probe.EXPECTED_EMAIL, **extra) -> str:
    body = {
        "type": "service_account",
        "project_id": "ee-araripe",
        "private_key_id": "abcdef0123456789",
        "private_key": PRIVATE,
        "client_email": email,
    }
    body.update(extra)
    return json.dumps(body)


class Value:
    def __init__(self, value):
        self.value = value

    def getInfo(self):
        return self.value


class FakeEE:
    """Just enough of the ``ee`` module for the probe's calls."""

    class EEException(Exception):
        pass

    def __init__(self, *, create=None, export=None, images=3, compute=42):
        self.initialised_with = None
        self.cancelled = False
        self.created = []
        self._create = create
        self._export = export
        self._images = images
        self._compute = compute
        outer = self

        class Number:
            def __init__(self, n):
                self.n = n

            def add(self, m):
                return Value(outer._compute)

        class Image:
            def select(self, band):
                return self

            def reduceRegion(self, reducer, geometry, scale):
                return type("D", (), {"get": lambda s, k: Value(1234.5)})()

            def getDownloadURL(self, params):
                assert params["format"] == "GEO_TIFF"
                return "https://example.invalid/pixels"

        class Collection:
            def __init__(self, *a):
                pass

            def filterBounds(self, g):
                return self

            def filterDate(self, a, b):
                return self

            def size(self):
                return Value(outer._images)

            def first(self):
                return Image()

        class Data:
            def createAsset(self, value, path):
                if outer._create is None:
                    outer.created.append(path)
                    return {"name": path}
                raise outer._create

        class Task:
            def start(self):
                if outer._export is not None:
                    raise outer._export

            def cancel(self):
                outer.cancelled = True

        class Table:
            @staticmethod
            def toAsset(**kwargs):
                return Task()

        self.Number = Number
        self.ImageCollection = Collection
        self.Geometry = type("G", (), {"Rectangle": staticmethod(lambda c: ("box", c))})
        self.Reducer = type("R", (), {"mean": staticmethod(lambda: "mean")})
        self.Feature = lambda geometry, props: ("feature", props)
        self.FeatureCollection = lambda items: ("fc", items)
        self.data = Data()
        self.batch = type("B", (), {"Export": type("E", (), {"table": Table})})

    def ServiceAccountCredentials(self, email, key_data):
        return ("credentials", email)

    def Initialize(self, credentials, project):
        self.initialised_with = (credentials, project)


DENIED = FakeEE.EEException(
    "Permission 'earthengine.assets.create' denied on resource 'projects/ee-araripe'."
)


class Response:
    def __init__(self, status=200, content=TIFF):
        self.status_code = status
        self.content = content


def ok_http(url, timeout):
    return Response()


@pytest.fixture(autouse=True)
def clean_checks():
    probe.CHECKS.clear()
    yield
    probe.CHECKS.clear()


def results():
    return {name: ok for name, ok, _ in probe.CHECKS}


def detail(name):
    return next(d for n, _, d in probe.CHECKS if n == name)


def run(ee, environ=None, http_get=ok_http):
    environ = {probe.KEY_VAR: key()} if environ is None else environ
    return probe.main([], environ=environ, ee=ee, http_get=http_get)


# ─── the happy path is what a correctly scoped identity produces ─────────────


def test_a_compute_only_identity_passes_every_check():
    ee = FakeEE(create=DENIED, export=DENIED)
    assert run(ee) == 0
    assert all(results().values())
    assert len(probe.CHECKS) == 9
    assert ee.initialised_with == (("credentials", probe.EXPECTED_EMAIL), "ee-araripe")
    assert ee.created == []


# ─── the two inverted checks, in both polarities ─────────────────────────────


def test_an_accepted_asset_creation_is_a_failure():
    """Kills: treating a successful createAsset as a pass."""

    ee = FakeEE(create=None, export=DENIED)
    assert run(ee) == 1
    name = "creating an asset is refused"
    assert results()[name] is False
    assert "over-scoped" in detail(name)
    assert ee.created == [probe.REFUSED_FOLDER]


def test_an_accepted_export_is_a_failure_and_is_cancelled():
    """Kills: treating a started export as a pass, or leaving it running."""

    ee = FakeEE(create=DENIED, export=None)
    assert run(ee) == 1
    name = "starting an export is refused"
    assert results()[name] is False
    assert "over-scoped" in detail(name)
    assert ee.cancelled is True


@pytest.mark.parametrize("message", [
    "Asset 'projects/ee-araripe/assets' not found.",
    "Invalid asset name.",
    "Internal error.",
])
def test_a_refusal_for_another_reason_proves_nothing(message):
    """Kills: counting ANY exception as a scope refusal.

    A missing parent or a server error refuses the write too, and says nothing
    about what the identity is allowed to do.
    """

    ee = FakeEE(create=FakeEE.EEException(message), export=FakeEE.EEException(message))
    assert run(ee) == 1
    for name in ("creating an asset is refused", "starting an export is refused"):
        assert results()[name] is False
        assert "NOT for a permission reason" in detail(name)


@pytest.mark.parametrize("message", [
    "Permission 'earthengine.assets.create' denied on resource 'projects/ee-araripe'.",
    "Caller does not have required permission to use project ee-araripe.",
    "HTTP 403 Forbidden",
])
def test_permission_refusals_are_recognised(message):
    ee = FakeEE(create=FakeEE.EEException(message), export=FakeEE.EEException(message))
    assert run(ee) == 0


# ─── the positive checks can fail ────────────────────────────────────────────


def test_a_wrong_computation_is_a_failure():
    assert run(FakeEE(create=DENIED, export=DENIED, compute=41)) == 1
    assert results()["an interactive computation answers"] is False


def test_an_empty_catalog_window_is_a_failure_not_a_pass():
    assert run(FakeEE(create=DENIED, export=DENIED, images=0)) == 1
    assert results()["Sentinel-2 is readable and reducible over the extent"] is False


@pytest.mark.parametrize("response", [Response(403, b"denied"), Response(200, b"<html>")])
def test_a_download_that_is_not_a_tiff_is_a_failure(response):
    assert run(FakeEE(create=DENIED, export=DENIED), http_get=lambda u, timeout: response) == 1
    assert results()["a GeoTIFF downloads through getDownloadURL"] is False


# ─── the key checks stop before Earth Engine is touched ──────────────────────


class Exploding:
    """Records any use instead of raising.

    Raising is not enough: ``main`` catches the failure of ``initialise`` and
    records it as a FAIL, so a test built on an exception passed with the
    account check deleted (mutation M5 survived that way). The assertion is
    that nothing touched Earth Engine at all.
    """

    def __init__(self):
        self.touched = []

    def __getattr__(self, name):
        self.__dict__.setdefault("touched", []).append(name)
        raise AssertionError(f"Earth Engine was touched ({name}) after a key refusal")


def test_the_blue_key_name_in_the_environment_is_a_refusal():
    """Kills: a probe that could fall back to the production identity."""

    environ = {probe.KEY_VAR: key(), probe.BLUE_KEY_VAR: key()}
    ee = Exploding()
    assert run(ee, environ=environ) == 1
    assert ee.touched == []
    assert results()[f"the blue key name {probe.BLUE_KEY_VAR} is absent"] is False


@pytest.mark.parametrize("raw", ["", "   ", "not json", json.dumps({"type": "authorized_user"})])
def test_a_missing_or_malformed_key_fails_closed(raw):
    ee = Exploding()
    assert run(ee, environ={probe.KEY_VAR: raw}) == 1
    assert ee.touched == []
    assert not all(results().values())


def test_a_key_for_another_account_is_named_and_refused():
    """Kills: accepting any service account, including the blue one."""

    other = "araripe-detect@ee-araripe.iam.gserviceaccount.com"
    ee = Exploding()
    assert run(ee, environ={probe.KEY_VAR: key(email=other)}) == 1
    assert ee.touched == [], "Earth Engine was initialised with another account's key"
    name = "the key belongs to the green detection account"
    assert results()[name] is False
    assert other in detail(name)


def test_no_part_of_the_key_is_ever_printed(capsys):
    run(FakeEE(create=DENIED, export=DENIED))
    run(Exploding(), environ={probe.KEY_VAR: key(email="someone@else.iam.gserviceaccount.com")})
    out = capsys.readouterr()
    text = out.out + out.err
    assert "verysecretmaterial" not in text
    assert "abcdef0123456789" not in text
    assert "key      : set" in text


# ─── the file itself ─────────────────────────────────────────────────────────


def test_the_probe_does_not_import_config():
    """``config/settings.py`` loads the production ``.env`` at import."""

    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert not (node.module or "").startswith(("config", "src")), node.module
        if isinstance(node, ast.Import):
            assert not any(a.name.startswith(("config", "src")) for a in node.names)


def test_the_probe_reads_only_its_own_key_name():
    source = SCRIPT.read_text(encoding="utf-8")
    assert probe.KEY_VAR == "GEE_GREEN_SA_KEY"
    assert probe.BLUE_KEY_VAR == "GEE_SA_KEY"
    reads = set(re.findall(r"environ(?:\.get)?\(\s*([A-Z_]+)", source))
    reads |= set(re.findall(r"environ\[\s*([A-Z_]+)", source))
    assert reads <= {"KEY_VAR"}, reads


# ─── the workflow ────────────────────────────────────────────────────────────


def workflow():
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def test_the_workflow_is_manual_only_and_read_only():
    doc = workflow()
    triggers = doc.get(True) or doc.get("on")  # PyYAML reads `on:` as True
    assert set(triggers) == {"workflow_dispatch"}
    assert doc["permissions"] == {"contents": "read"}


def test_the_workflow_uses_the_existing_environment_and_nothing_else():
    """Never name an Environment that does not exist: GitHub creates it unprotected."""

    jobs = workflow()["jobs"]
    assert [job.get("environment") for job in jobs.values()] == ["v2-staging"]


def test_the_green_key_is_the_only_secret_and_only_the_probe_step_holds_it():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert re.findall(r"secrets\.([A-Za-z0-9_]+)", text) == ["GEE_GREEN_SA_KEY"]
    steps = workflow()["jobs"]["probe"]["steps"]
    holders = [s["name"] for s in steps if "secrets." in str(s.get("env") or {})]
    assert holders == ["Probe the green identity"]


def test_no_blue_or_r2_secret_name_appears_in_the_workflow():
    for line in WORKFLOW.read_text(encoding="utf-8").splitlines():
        code = line.split("#", 1)[0]
        assert "GEE_SA_KEY" not in code.replace("GEE_GREEN_SA_KEY", "")
        assert "R2_" not in code
