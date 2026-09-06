"""The time-series release signal the site validates (Package 2B.1).

The site used to infer "the backend finished" from a fixed clock offset, and on
2026-08-17 a 67-minute late cron made it publish a stale series while reporting
success (ROADMAP.md §6). The signal replaces that inference with a checkable
claim: what was published, and the checksum of the artifact published.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "write_release_signal.py"
SPEC = importlib.util.spec_from_file_location("write_release_signal", MODULE_PATH)
assert SPEC and SPEC.loader
signal_mod = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = signal_mod
SPEC.loader.exec_module(signal_mod)

FIXED_NOW = datetime(2026, 9, 8, 6, 42, 11, tzinfo=timezone.utc)
CI_ENV = {
    "GITHUB_RUN_ID": "4242",
    "GITHUB_SERVER_URL": "https://github.com",
    "GITHUB_REPOSITORY": "santibravocmcc/Araripe",
    "GITHUB_WORKFLOW": "GEE Deforestation Detection (headless)",
}


@pytest.fixture
def db(tmp_path):
    """A minimal time-series database with two observation dates."""
    path = tmp_path / "timeseries.db"
    con = sqlite3.connect(path)
    con.execute(
        "create table regional_stats "
        "(date text, index_name text, region text, mean real, std real)"
    )
    con.executemany(
        "insert into regional_stats values (?,?,?,?,?)",
        [("2026-08-27", "ndmi", "full_aoi", 0.3, 0.1),
         ("2026-08-30", "ndmi", "full_aoi", 0.4, 0.1)],
    )
    con.commit()
    con.close()
    return path


def test_signal_describes_the_database(db):
    s = signal_mod.build_signal(db, now=FIXED_NOW, env=CI_ENV)
    assert s["schema"] == "araripe.timeseries.release/1"
    assert s["published_utc"] == "2026-09-08T06:42:11Z"
    assert s["latest_observation"] == "2026-08-30"
    assert s["timeseries"]["bytes"] == db.stat().st_size


def test_checksum_matches_the_artifact(db):
    """The site's atomicity gate: signal and DB must describe each other."""
    s = signal_mod.build_signal(db, now=FIXED_NOW, env=CI_ENV)
    assert s["timeseries"]["sha256"] == hashlib.sha256(db.read_bytes()).hexdigest()


def test_checksum_changes_when_the_database_changes(db):
    before = signal_mod.build_signal(db, now=FIXED_NOW, env=CI_ENV)["timeseries"]["sha256"]
    con = sqlite3.connect(db)
    con.execute("insert into regional_stats values ('2026-09-03','ndmi','full_aoi',0.5,0.1)")
    con.commit()
    con.close()
    after = signal_mod.build_signal(db, now=FIXED_NOW, env=CI_ENV)
    assert after["timeseries"]["sha256"] != before
    assert after["latest_observation"] == "2026-09-03"


def test_run_identity_is_recorded(db):
    s = signal_mod.build_signal(db, now=FIXED_NOW, env=CI_ENV)
    assert s["run_id"] == "4242"
    assert s["run_url"] == "https://github.com/santibravocmcc/Araripe/actions/runs/4242"


def test_run_url_is_absent_outside_ci(db):
    """A locally written signal must not claim a run that never happened."""
    s = signal_mod.build_signal(db, now=FIXED_NOW, env={})
    assert s["run_id"] is None and s["run_url"] is None


def test_empty_series_reports_no_observation(tmp_path):
    path = tmp_path / "timeseries.db"
    con = sqlite3.connect(path)
    con.execute("create table regional_stats (date text, index_name text, region text)")
    con.commit()
    con.close()
    assert signal_mod.build_signal(path, now=FIXED_NOW, env={})["latest_observation"] is None


def test_missing_database_fails_closed(tmp_path):
    with pytest.raises(SystemExit):
        signal_mod.build_signal(tmp_path / "absent.db", now=FIXED_NOW, env={})


def test_written_file_is_stable_json(db):
    out = signal_mod.write_signal(db, now=FIXED_NOW, env=CI_ENV)
    assert out.name == "RELEASE.json"
    text = out.read_text()
    assert text.endswith("\n"), "a committed file needs a trailing newline"
    # sort_keys + indent: rewriting an unchanged release yields no diff noise.
    assert text == json.dumps(json.loads(text), indent=2, sort_keys=True) + "\n"


def test_signal_is_written_beside_the_database(db):
    assert signal_mod.write_signal(db, now=FIXED_NOW, env=CI_ENV).parent == db.parent


def test_committed_signal_matches_the_committed_database():
    """The seeded signal on this branch must describe the real DB."""
    repo = Path(__file__).parents[1]
    committed = json.loads((repo / "data/timeseries/RELEASE.json").read_text())
    real = repo / "data/timeseries/timeseries.db"
    assert committed["timeseries"]["sha256"] == hashlib.sha256(real.read_bytes()).hexdigest()
    assert committed["timeseries"]["bytes"] == real.stat().st_size
