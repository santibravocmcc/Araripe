#!/usr/bin/env python3
"""Fixed-target Cloudflare control broker for the isolated Araripe green lane."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

API_BASE = "https://api.cloudflare.com/client/v4"
ACCOUNT_ID = "9416750169311ee4afc18a8ff3c771d4"
ZONE_ID = "ffb40294871f38028e925208c3f9110a"
STAGING_WORKER = "observatorio-chapada-v2-staging"
STAGING_BUCKET = "araripe-v2-staging"
STAGING_RATE_LIMIT_NAMESPACE = "2001"
PRODUCTION_WORKER = "observatorio-chapada"
FINAL_DOMAIN = "observatoriodachapadadoararipe.com"
SITE_REPOSITORY = "observatorio-site"
SITE_PROVIDER_ACCOUNT = "santibravocmcc"
PRODUCTION_SCRIPT_TAG = "43503f539c80410b938e3cdf6a4f2bc7"
NONPRODUCTION_TRIGGER_ID = "0040d17d-10be-4329-bba4-ac614a9d5bef"
SAFE_SITE_DEPLOY_COMMAND = "exit 0"
MUTATION_CONFIRMATION = "GREEN-ONLY"
ALLOWED_OPERATIONS = (
    "audit",
    "enforce-worker-isolation",
    "disable-site-branch-deploy",
)


class ControlError(RuntimeError):
    """Fail-closed broker validation or API failure."""


@dataclass
class CloudflareClient:
    token: str

    def request(
        self, method: str, path: str, body: dict[str, Any] | None = None
    ) -> Any:
        if not path.startswith("/") or ".." in path or "?" in path:
            raise ControlError("refusing unsafe API path")
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            API_BASE + path,
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "araripe-green-control/1",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.load(response)
        except urllib.error.HTTPError as error:
            raise ControlError(
                f"Cloudflare API returned HTTP {error.code} for fixed operation"
            ) from None
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            raise ControlError(f"Cloudflare API request failed: {type(error).__name__}") from None
        if not payload.get("success"):
            codes = [str(item.get("code", "unknown")) for item in payload.get("errors", [])]
            raise ControlError("Cloudflare API rejected fixed operation; codes=" + ",".join(codes))
        return payload.get("result")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ControlError(message)


def _paths() -> dict[str, str]:
    account = f"/accounts/{ACCOUNT_ID}"
    return {
        "settings": f"{account}/workers/scripts/{STAGING_WORKER}/settings",
        "subdomain": f"{account}/workers/scripts/{STAGING_WORKER}/subdomain",
        "schedules": f"{account}/workers/scripts/{STAGING_WORKER}/schedules",
        "domains": f"{account}/workers/domains",
        "routes": f"/zones/{ZONE_ID}/workers/routes",
        "triggers": f"{account}/builds/workers/{PRODUCTION_SCRIPT_TAG}/triggers",
        "trigger": f"{account}/builds/triggers/{NONPRODUCTION_TRIGGER_ID}",
    }


def _get_nonproduction_trigger(client: CloudflareClient, path: str) -> dict[str, Any]:
    triggers = client.request("GET", path)
    matches = [
        item for item in triggers
        if item.get("trigger_uuid") == NONPRODUCTION_TRIGGER_ID
    ]
    _require(len(matches) == 1, "expected non-production trigger identity is absent")
    trigger = matches[0]
    repo = trigger.get("repo_connection") or {}
    _require(trigger.get("external_script_id") == PRODUCTION_SCRIPT_TAG, "unexpected trigger script tag")
    _require(trigger.get("trigger_name") == "Deploy non-production branches", "unexpected trigger name")
    _require(trigger.get("branch_includes") == ["*"], "unexpected non-production branch includes")
    _require(trigger.get("branch_excludes") == ["main"], "unexpected non-production branch excludes")
    _require(trigger.get("build_command") == "npm run build", "unexpected site build command")
    _require(trigger.get("root_directory") == "/", "unexpected site build root")
    _require(repo.get("repo_name") == SITE_REPOSITORY, "unexpected connected site repository")
    _require(repo.get("provider_account_name") == SITE_PROVIDER_ACCOUNT, "unexpected repository owner")
    _require(repo.get("provider_type") == "github", "unexpected repository provider")
    return trigger


def audit(client: CloudflareClient) -> dict[str, Any]:
    paths = _paths()
    settings = client.request("GET", paths["settings"])
    subdomain = client.request("GET", paths["subdomain"])
    schedules = client.request("GET", paths["schedules"])
    domains = client.request("GET", paths["domains"])
    routes = client.request("GET", paths["routes"])
    trigger = _get_nonproduction_trigger(client, paths["triggers"])

    bindings = settings.get("bindings") or []
    _require(len(bindings) == 2, "staging Worker has unexpected binding count")
    r2 = [item for item in bindings if item.get("type") == "r2_bucket"]
    limiter = [item for item in bindings if item.get("type") == "ratelimit"]
    _require(
        r2 == [{"bucket_name": STAGING_BUCKET, "name": "STAGING_BUCKET", "type": "r2_bucket"}],
        "staging Worker R2 binding differs from the fixed green bucket",
    )
    _require(len(limiter) == 1, "staging Worker rate-limit binding is absent")
    _require(limiter[0].get("name") == "STAGING_LIMITER", "unexpected rate-limit binding name")
    _require(limiter[0].get("namespace_id") == STAGING_RATE_LIMIT_NAMESPACE, "unexpected rate-limit namespace")
    _require(limiter[0].get("simple") == {"limit": 8, "period": 60}, "unexpected rate-limit policy")
    _require(subdomain == {"enabled": False, "previews_enabled": False}, "staging public subdomain is not disabled")
    _require((schedules or {}).get("schedules") == [], "staging Worker has a schedule")
    _require(not any(item.get("service") == STAGING_WORKER for item in domains), "staging Worker has a custom domain")
    final = [item for item in domains if item.get("hostname") == FINAL_DOMAIN]
    _require(len(final) == 1 and final[0].get("service") == PRODUCTION_WORKER, "final domain ownership changed")
    _require(not any(item.get("script") == STAGING_WORKER for item in routes), "staging Worker has a zone route")

    return {
        "account": "approved-account",
        "staging_worker": STAGING_WORKER,
        "staging_bucket": STAGING_BUCKET,
        "staging_rate_limit_namespace": STAGING_RATE_LIMIT_NAMESPACE,
        "public_subdomain_enabled": False,
        "custom_domain_count": 0,
        "route_count": 0,
        "schedule_count": 0,
        "site_nonproduction_deploy_command": trigger.get("deploy_command"),
        "production_mutated": False,
    }


def enforce_worker_isolation(client: CloudflareClient) -> dict[str, Any]:
    client.request(
        "POST",
        _paths()["subdomain"],
        {"enabled": False, "previews_enabled": False},
    )
    return audit(client)


def disable_site_nonproduction_deploy(client: CloudflareClient) -> dict[str, Any]:
    paths = _paths()
    _get_nonproduction_trigger(client, paths["triggers"])
    client.request(
        "PATCH",
        paths["trigger"],
        {"deploy_command": SAFE_SITE_DEPLOY_COMMAND},
    )
    result = audit(client)
    _require(
        result["site_nonproduction_deploy_command"] == SAFE_SITE_DEPLOY_COMMAND,
        "non-production deploy command did not converge to inert state",
    )
    return result


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--operation", choices=ALLOWED_OPERATIONS, required=True)
    parser.add_argument("--confirmation", default="")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    token = os.environ.get("CLOUDFLARE_GREEN_CONTROL_TOKEN", "")
    if not token:
        raise ControlError("protected GitHub Environment token is unavailable")
    if args.operation == "audit":
        _require(args.confirmation == "", "audit must not carry mutation confirmation")
    else:
        _require(args.confirmation == MUTATION_CONFIRMATION, "mutation confirmation mismatch")

    client = CloudflareClient(token)
    if args.operation == "audit":
        result = audit(client)
    elif args.operation == "enforce-worker-isolation":
        result = enforce_worker_isolation(client)
    else:
        result = disable_site_nonproduction_deploy(client)
    json.dump(result, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ControlError as error:
        print(f"green control refused: {error}", file=sys.stderr)
        raise SystemExit(1) from None
