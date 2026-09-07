"""Fail-closed contract of the R2 persistence-state helper (Package 2B.1).

The regression these tests exist for: `scripts/r2_state.py` used to wrap its
download in a bare `except Exception` that printed "primeira execução?" and
continued. Bad credentials, a network blip, a truncated body or a corrupt
object were therefore indistinguishable from a genuine first run, and the
pipeline carried on with an EMPTY state — silently resetting `n_sightings`,
`first_seen` and `last_seen` for every track.

So every test below asserts the same thing from a different angle: only a real
404 may be read as a first run; everything else must raise.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest
from botocore.exceptions import ClientError


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "r2_state.py"
SPEC = importlib.util.spec_from_file_location("r2_state", MODULE_PATH)
assert SPEC and SPEC.loader
r2_state = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = r2_state
SPEC.loader.exec_module(r2_state)

BUCKET = "araripe-cogs"


def track(n=3, first="2026-01-05", last="2026-02-10"):
    return {
        "type": "Feature",
        "properties": {"n_sightings": n, "first_seen": first, "last_seen": last},
        "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [0, 1], [1, 1], [0, 0]]]},
    }


def state_bytes(features):
    return json.dumps({"type": "FeatureCollection", "features": features}).encode()


def client_error(code, op="HeadObject"):
    return ClientError({"Error": {"Code": code, "Message": code}}, op)


class FakeClient:
    """Minimal S3 stand-in: serves `payload`, or raises `head_error`."""

    def __init__(self, payload=None, *, head_error=None, download_error=None,
                 upload_error=None, stored_length=None, content_length=None):
        self.payload = payload
        self.head_error = head_error
        self.download_error = download_error
        self.upload_error = upload_error
        self.stored_length = stored_length
        self.content_length = content_length
        self.uploaded = []
        self.downloads = []

    def head_object(self, Bucket, Key):
        if self.head_error is not None:
            raise self.head_error
        if self.uploaded:
            length = self.stored_length
            if length is None:
                length = len(self.uploaded[-1][0])
            return {"ContentLength": length}
        if self.payload is None:
            raise client_error("404")
        length = self.content_length
        return {"ContentLength": len(self.payload) if length is None else length}

    def download_file(self, Bucket, Key, path):
        if self.download_error is not None:
            raise self.download_error
        self.downloads.append(path)
        Path(path).write_bytes(self.payload)

    def upload_file(self, path, Bucket, Key, ExtraArgs=None):
        if self.upload_error is not None:
            raise self.upload_error
        self.uploaded.append((Path(path).read_bytes(), Bucket, Key, ExtraArgs))


# ─── the benign path: a genuine first run ────────────────────────────────────

def test_absent_object_is_a_first_run(tmp_path):
    dest = tmp_path / "persistence_state.geojson"
    assert r2_state.get(FakeClient(None), BUCKET, str(dest)) is False
    assert not dest.exists()


def test_absent_object_fails_closed_when_existence_is_required(tmp_path):
    dest = tmp_path / "persistence_state.geojson"
    with pytest.raises(r2_state.StateError, match="require-existing"):
        r2_state.get(FakeClient(None), BUCKET, str(dest), require_existing=True)


# ─── everything else must fail closed ────────────────────────────────────────

@pytest.mark.parametrize(
    "code",
    ["403", "AccessDenied", "InvalidAccessKeyId", "SignatureDoesNotMatch",
     "ExpiredToken", "NoSuchBucket", "500", "SlowDown"],
)
def test_non_404_errors_are_never_a_first_run(tmp_path, code):
    """The core regression: a credential or bucket problem must not reset tracks."""
    client = FakeClient(None, head_error=client_error(code))
    dest = tmp_path / "persistence_state.geojson"
    with pytest.raises(r2_state.StateError):
        r2_state.get(client, BUCKET, str(dest))
    assert not dest.exists()


def test_network_failure_is_not_a_first_run(tmp_path):
    client = FakeClient(None, head_error=OSError("connection reset by peer"))
    dest = tmp_path / "persistence_state.geojson"
    with pytest.raises(r2_state.StateError, match="cannot reach R2"):
        r2_state.get(client, BUCKET, str(dest))
    assert not dest.exists()


def test_only_404_and_nosuchkey_count_as_absent():
    assert r2_state.is_absent(client_error("404"))
    assert r2_state.is_absent(client_error("NoSuchKey"))
    assert not r2_state.is_absent(client_error("403"))
    assert not r2_state.is_absent(OSError("boom"))


def test_truncated_download_fails_closed(tmp_path):
    payload = state_bytes([track()])
    client = FakeClient(payload, content_length=len(payload) + 500)
    dest = tmp_path / "persistence_state.geojson"
    with pytest.raises(r2_state.StateError, match="truncated"):
        r2_state.get(client, BUCKET, str(dest))
    assert not dest.exists()


def test_failed_download_leaves_the_previous_state_untouched(tmp_path):
    """A partial fetch must never replace a good local state."""
    dest = tmp_path / "persistence_state.geojson"
    good = state_bytes([track(n=9)])
    dest.write_bytes(good)
    client = FakeClient(b"{ truncated", content_length=999)
    with pytest.raises(r2_state.StateError):
        r2_state.get(client, BUCKET, str(dest))
    assert dest.read_bytes() == good
    assert not (tmp_path / "persistence_state.geojson.part").exists()


def test_download_error_fails_closed(tmp_path):
    client = FakeClient(state_bytes([track()]), download_error=OSError("reset"))
    dest = tmp_path / "persistence_state.geojson"
    with pytest.raises(r2_state.StateError, match="download"):
        r2_state.get(client, BUCKET, str(dest))


# ─── payload validation ──────────────────────────────────────────────────────

def test_valid_state_is_written_with_its_track_count(tmp_path):
    payload = state_bytes([track(), track(n=20)])
    dest = tmp_path / "persistence_state.geojson"
    assert r2_state.get(FakeClient(payload), BUCKET, str(dest)) is True
    assert json.loads(dest.read_bytes())["features"][1]["properties"]["n_sightings"] == 20


def test_empty_feature_collection_is_valid():
    """A run that has never seen an alert legitimately stores zero tracks."""
    assert r2_state.validate_state(state_bytes([]))["tracks"] == 0


@pytest.mark.parametrize(
    "raw, expected",
    [
        (b"", "empty payload"),
        (b"   ", "empty payload"),
        (b"{ not json", "not valid JSON"),
        (b"[1, 2, 3]", "expected a GeoJSON object"),
        (b'{"type": "Feature"}', "expected a FeatureCollection"),
        (b'{"type": "FeatureCollection"}', "no 'features' list"),
        (b'{"type": "FeatureCollection", "features": {}}', "no 'features' list"),
        (b'{"type": "FeatureCollection", "features": ["x"]}', "expected an object"),
    ],
)
def test_malformed_payloads_are_rejected(raw, expected):
    with pytest.raises(r2_state.StateError, match=expected):
        r2_state.validate_state(raw)


def test_feature_without_properties_is_rejected():
    payload = json.dumps({"type": "FeatureCollection", "features": [{"type": "Feature"}]}).encode()
    with pytest.raises(r2_state.StateError, match="no properties"):
        r2_state.validate_state(payload)


@pytest.mark.parametrize("missing", ["n_sightings", "first_seen", "last_seen"])
def test_feature_missing_a_track_column_is_rejected(missing):
    feature = track()
    del feature["properties"][missing]
    with pytest.raises(r2_state.StateError, match=missing):
        r2_state.validate_state(state_bytes([feature]))


def test_feature_without_geometry_is_rejected():
    feature = track()
    feature["geometry"] = None
    with pytest.raises(r2_state.StateError, match="no geometry"):
        r2_state.validate_state(state_bytes([feature]))


def test_unparseable_last_seen_is_fatal():
    """`update_tracks` chama `_days_between` nele; o run morreria depois."""
    feature = track()
    feature["properties"]["last_seen"] = "30/07/2026"
    with pytest.raises(r2_state.StateError, match="not a YYYY-MM-DD date"):
        r2_state.validate_state(state_bytes([feature]))


# ─── anomalias contadas, nunca fatais ────────────────────────────────────────

def test_first_seen_after_last_seen_is_counted_not_fatal():
    """A regressão de 2026-09-07: esta checagem derrubou a produção.

    O log foi `feature 101684: first_seen 2026-07-13 is after last_seen
    2026-07-11`. O estado estava íntegro — em `update_tracks`,
    `w_last[t] = date` sobrescreve `last_seen` com a data em processamento
    enquanto `first_seen` é preservado, e cada rodada reprocessa 16 dias, então
    casar uma track numa data mais antiga empurra `last_seen` para trás.
    Ver tests/test_update_tracks.py::test_last_seen_can_move_backwards.
    """
    summary = r2_state.validate_state(state_bytes([
        track(first="2026-07-13", last="2026-07-11"),
        track(first="2026-06-01", last="2026-06-20"),
        track(first="2026-08-02", last="2026-07-30"),
    ]))
    assert summary["tracks"] == 3
    odd = summary["anomalies"]["first_seen_after_last_seen"]
    assert odd["count"] == 2
    assert "2026-07-13 > 2026-07-11" in odd["first_example"]


@pytest.mark.parametrize("props, kind", [
    ({"n_sightings": "muitas"}, "n_sightings_not_a_positive_int"),
    ({"n_sightings": 0}, "n_sightings_not_a_positive_int"),
    ({"first_seen": "05/01/2026"}, "first_seen_not_iso"),
])
def test_survivable_oddities_are_counted(props, kind):
    """`pd.to_numeric(...).fillna(1)` e o `first_seen` só-string dão conta."""
    feature = track()
    feature["properties"].update(props)
    summary = r2_state.validate_state(state_bytes([feature]))
    assert summary["anomalies"][kind]["count"] == 1


def test_a_clean_state_reports_no_anomalies():
    assert r2_state.validate_state(state_bytes([track(), track()]))["anomalies"] == {}


def test_anomalies_are_warned_with_a_count_and_an_example(capsys):
    """O operador precisa da escala, não só do primeiro caso."""
    r2_state.validate_state(state_bytes(
        [track(first="2026-07-13", last="2026-07-11")] * 4 + [track()]))
    out = capsys.readouterr().out
    assert "5 tracks, 4 com first_seen_after_last_seen" in out


def test_an_odd_state_is_still_written_and_uploaded(tmp_path):
    """Anomalia não bloqueia: o pipeline tem de continuar rodando."""
    payload = state_bytes([track(first="2026-07-13", last="2026-07-11")])
    dest = tmp_path / "persistence_state.geojson"
    assert r2_state.get(FakeClient(payload), BUCKET, str(dest)) is True
    client = FakeClient()
    r2_state.put(client, BUCKET, str(dest))
    assert client.uploaded[0][0] == payload


# ─── put ─────────────────────────────────────────────────────────────────────

def test_put_refuses_a_missing_file(tmp_path):
    """Detection produced no state: exiting 0 would leave the old state live."""
    client = FakeClient()
    with pytest.raises(r2_state.StateError, match="does not exist"):
        r2_state.put(client, BUCKET, str(tmp_path / "absent.geojson"))
    assert client.uploaded == []


def test_put_refuses_a_corrupt_file(tmp_path):
    path = tmp_path / "persistence_state.geojson"
    path.write_bytes(b"{ half written")
    client = FakeClient()
    with pytest.raises(r2_state.StateError, match="not valid JSON"):
        r2_state.put(client, BUCKET, str(path))
    assert client.uploaded == []


def test_put_uploads_and_confirms_the_stored_size(tmp_path):
    path = tmp_path / "persistence_state.geojson"
    payload = state_bytes([track(), track()])
    path.write_bytes(payload)
    client = FakeClient()
    r2_state.put(client, BUCKET, str(path))
    assert client.uploaded[0][0] == payload
    assert client.uploaded[0][2] == r2_state.KEY


def test_put_fails_closed_when_the_stored_size_disagrees(tmp_path):
    path = tmp_path / "persistence_state.geojson"
    path.write_bytes(state_bytes([track()]))
    client = FakeClient(stored_length=12)
    with pytest.raises(r2_state.StateError, match="upload is incomplete"):
        r2_state.put(client, BUCKET, str(path))


def test_put_fails_closed_when_the_upload_raises(tmp_path):
    path = tmp_path / "persistence_state.geojson"
    path.write_bytes(state_bytes([track()]))
    with pytest.raises(r2_state.StateError, match="upload of"):
        r2_state.put(FakeClient(upload_error=OSError("reset")), BUCKET, str(path))


# ─── CLI boundary ────────────────────────────────────────────────────────────

def test_missing_credentials_fail_closed(monkeypatch):
    for var in r2_state._ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(r2_state.StateError, match="missing R2 credentials"):
        r2_state._client()


def test_main_exits_non_zero_on_a_state_error(monkeypatch, tmp_path):
    """Fail-closed all the way to the workflow step's exit status."""
    for var in r2_state._ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(SystemExit) as exc:
        r2_state.main(["get", str(tmp_path / "state.geojson")])
    assert exc.value.code not in (0, None)


def test_main_rejects_an_unknown_action():
    with pytest.raises(SystemExit):
        r2_state.main(["delete", "state.geojson"])


def test_main_accepts_the_require_existing_flag(monkeypatch, tmp_path):
    seen = {}
    monkeypatch.setattr(r2_state, "_client", lambda: "fake")
    monkeypatch.setattr(
        r2_state, "get",
        lambda client, bucket, path, require_existing=False: seen.update(
            require_existing=require_existing, bucket=bucket
        ),
    )
    r2_state.main(["get", str(tmp_path / "state.geojson"), "--require-existing"])
    assert seen == {"require_existing": True, "bucket": "araripe-cogs"}
