"""select_latest_keys: which alert objects to pull from R2."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from fetch_alerts_from_r2 import select_latest_keys  # noqa: E402

KEYS = [
    "alerts/alerts_2026-01-02.geojson",
    "alerts/alerts_2026-07-11.geojson",
    "alerts/alerts_2026-04-27.geojson",
    "alerts/manifest.json",           # non-geojson must be ignored
    "alerts/",                         # prefix "folder" key, ignored
]


def test_latest_returns_n_most_recent_chronologically():
    got = select_latest_keys(KEYS, latest=2)
    assert got == [
        "alerts/alerts_2026-04-27.geojson",
        "alerts/alerts_2026-07-11.geojson",
    ]


def test_zero_or_negative_returns_all_geojson_sorted():
    got = select_latest_keys(KEYS, latest=0)
    assert got == [
        "alerts/alerts_2026-01-02.geojson",
        "alerts/alerts_2026-04-27.geojson",
        "alerts/alerts_2026-07-11.geojson",
    ]
    assert "alerts/manifest.json" not in got


def test_latest_larger_than_available_returns_all():
    assert len(select_latest_keys(KEYS, latest=99)) == 3
