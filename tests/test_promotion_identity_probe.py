"""The probe must fail when isolation is broken, not when it is intact.

The probe's job is to prove the promotion identity cannot reach production.
That check is written inverted -- the *refusal* is the pass condition -- and an
inverted check with the polarity wrong is worse than no check: it would report
PASS for a token that can read `araripe-cogs`, green-lighting exactly the
breakage it exists to catch.

So the polarity is asserted in both directions here. No network: `boto3.client`
is replaced, and nothing reaches an object store.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from src.publication import conditional_store as cs
from tests.fake_object_store import client_error

MODULE_PATH = Path(__file__).parents[1] / "scripts" / "probe_promotion_identity.py"
SPEC = importlib.util.spec_from_file_location("probe_promotion_identity", MODULE_PATH)
assert SPEC and SPEC.loader
probe = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = probe
SPEC.loader.exec_module(probe)

CREDENTIALS = {"access_key_id": "unused", "secret_access_key": "unused", "region": "auto"}


@pytest.fixture(autouse=True)
def clean_checks():
    probe.CHECKS.clear()
    yield
    probe.CHECKS.clear()


def _install_client(monkeypatch, behaviour):
    """Replace boto3.client with one whose list_objects_v2 does `behaviour`."""

    class Fake:
        def list_objects_v2(self, Bucket, MaxKeys=None):
            return behaviour(Bucket)

    import boto3

    monkeypatch.setattr(boto3, "client", lambda *a, **k: Fake())


def test_a_denied_production_bucket_is_a_pass(monkeypatch):
    def denied(bucket):
        assert bucket == cs.PRODUCTION_BUCKET
        raise client_error("AccessDenied", "ListObjectsV2", 403)

    _install_client(monkeypatch, denied)
    probe.probe_production_is_denied(CREDENTIALS, cs.STAGING_ENDPOINT)
    assert [ok for _, ok, _ in probe.CHECKS] == [True]
    assert probe.report() == 0


def test_a_readable_production_bucket_is_a_failure(monkeypatch):
    """The inverted check's polarity: a SUCCESSFUL list must fail the probe."""

    _install_client(monkeypatch, lambda bucket: {"KeyCount": 0})
    probe.probe_production_is_denied(CREDENTIALS, cs.STAGING_ENDPOINT)
    name, ok, detail = probe.CHECKS[0]
    assert ok is False
    assert "over-scoped" in detail
    assert probe.report() == 1


@pytest.mark.parametrize("code,status", [("403", 403), ("InvalidAccessKeyId", 403),
                                        ("NoSuchBucket", 404)])
def test_other_refusals_also_count_as_denied(monkeypatch, code, status):
    def denied(bucket):
        raise client_error(code, "ListObjectsV2", status)

    _install_client(monkeypatch, denied)
    probe.probe_production_is_denied(CREDENTIALS, cs.STAGING_ENDPOINT)
    assert probe.CHECKS[0][1] is True


def test_an_unexpected_error_is_reported_with_its_code(monkeypatch):
    """A 500 is not evidence of denial; it is evidence of nothing."""

    def broken(bucket):
        raise client_error("InternalError", "ListObjectsV2", 500)

    _install_client(monkeypatch, broken)
    probe.probe_production_is_denied(CREDENTIALS, cs.STAGING_ENDPOINT)
    name, ok, detail = probe.CHECKS[0]
    assert ok is False
    assert "InternalError" in detail


def test_the_probe_fails_closed_without_a_credential(monkeypatch, capsys):
    monkeypatch.setenv("R2_STAGING_BUCKET", cs.STAGING_BUCKET)
    monkeypatch.setenv("R2_ENDPOINT_URL", cs.STAGING_ENDPOINT)
    monkeypatch.delenv("R2_PROMOTION_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("R2_PROMOTION_SECRET_ACCESS_KEY", raising=False)
    assert probe.main(["--run-id", "t"]) == 1
    assert "missing R2 credentials" in capsys.readouterr().err


def test_the_probe_refuses_a_production_target(monkeypatch, capsys):
    monkeypatch.setenv("R2_STAGING_BUCKET", cs.PRODUCTION_BUCKET)
    monkeypatch.setenv("R2_ENDPOINT_URL", cs.STAGING_ENDPOINT)
    monkeypatch.setenv("R2_PROMOTION_ACCESS_KEY_ID", "unused")
    monkeypatch.setenv("R2_PROMOTION_SECRET_ACCESS_KEY", "unused")
    assert probe.main(["--run-id", "t"]) == 1
    assert "production is frozen" in capsys.readouterr().err


def test_no_secret_is_ever_printed(monkeypatch, capsys):
    """The probe reports whether a value is set, never the value.

    ``build_client`` is replaced so this stays offline. Without that, ``main``
    gets past the guards and issues a real ``list_objects_v2`` against the
    account endpoint -- which the probe swallows into a FAIL line, so the test
    would still pass while quietly making a network call on every run.
    """

    def refuse(bucket, endpoint, credentials):
        raise cs.ObjectStoreError("stopped before any network call")

    monkeypatch.setattr(cs, "build_client", refuse)
    monkeypatch.setattr(probe.cs, "build_client", refuse)
    monkeypatch.setenv("R2_STAGING_BUCKET", cs.STAGING_BUCKET)
    monkeypatch.setenv("R2_ENDPOINT_URL", cs.STAGING_ENDPOINT)
    monkeypatch.setenv("R2_PROMOTION_ACCESS_KEY_ID", "AKIAsecretlooking")
    monkeypatch.setenv("R2_PROMOTION_SECRET_ACCESS_KEY", "verysecretvalue")
    assert probe.main(["--run-id", "t"]) == 1
    captured = capsys.readouterr()
    assert "AKIAsecretlooking" not in captured.out + captured.err
    assert "verysecretvalue" not in captured.out + captured.err
    assert "key id   : set" in captured.out


def test_no_test_in_this_file_can_reach_the_network(monkeypatch):
    """Guard the guard: every path above stops before an S3 call.

    Asserted by making a real client construction explode. If a future edit
    lets `main` through to `list_objects_v2`, that test fails here instead of
    silently issuing requests from CI or from a laptop with no connection.
    """

    import boto3

    def explode(*args, **kwargs):
        raise AssertionError("a test tried to build a real S3 client")

    monkeypatch.setattr(boto3, "client", explode)
    monkeypatch.setenv("R2_STAGING_BUCKET", cs.STAGING_BUCKET)
    monkeypatch.setenv("R2_ENDPOINT_URL", cs.STAGING_ENDPOINT)
    monkeypatch.delenv("R2_PROMOTION_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("R2_PROMOTION_SECRET_ACCESS_KEY", raising=False)
    assert probe.main(["--run-id", "t"]) == 1
