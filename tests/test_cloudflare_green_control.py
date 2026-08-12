from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "cloudflare_green_control.py"
SPEC = importlib.util.spec_from_file_location("cloudflare_green_control", MODULE_PATH)
assert SPEC and SPEC.loader
control = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = control
SPEC.loader.exec_module(control)


class FakeClient:
    def __init__(self, *, extra_binding=None, deploy_command="npx wrangler deploy"):
        bindings = [
            {"bucket_name": control.STAGING_BUCKET, "name": "STAGING_BUCKET", "type": "r2_bucket"},
            {
                "name": "STAGING_LIMITER",
                "namespace_id": control.STAGING_RATE_LIMIT_NAMESPACE,
                "simple": {"limit": 8, "period": 60},
                "type": "ratelimit",
            },
        ]
        if extra_binding:
            bindings.append(extra_binding)
        self.trigger = {
            "trigger_uuid": control.NONPRODUCTION_TRIGGER_ID,
            "external_script_id": control.PRODUCTION_SCRIPT_TAG,
            "trigger_name": "Deploy non-production branches",
            "branch_includes": ["*"],
            "branch_excludes": ["main"],
            "build_command": "npm run build",
            "deploy_command": deploy_command,
            "root_directory": "/",
            "repo_connection": {
                "repo_name": control.SITE_REPOSITORY,
                "provider_account_name": control.SITE_PROVIDER_ACCOUNT,
                "provider_type": "github",
            },
        }
        paths = control._paths()
        self.responses = {
            paths["settings"]: {"bindings": bindings},
            paths["subdomain"]: {"enabled": False, "previews_enabled": False},
            paths["schedules"]: {"schedules": []},
            paths["domains"]: [
                {"hostname": control.FINAL_DOMAIN, "service": control.PRODUCTION_WORKER}
            ],
            paths["routes"]: [],
            paths["triggers"]: [self.trigger],
        }
        self.calls = []

    def request(self, method, path, body=None):
        self.calls.append((method, path, body))
        if method == "PATCH" and path == control._paths()["trigger"]:
            assert body == {"deploy_command": control.SAFE_SITE_DEPLOY_COMMAND}
            self.trigger["deploy_command"] = control.SAFE_SITE_DEPLOY_COMMAND
            return self.trigger
        if method == "POST" and path == control._paths()["subdomain"]:
            assert body == {"enabled": False, "previews_enabled": False}
            return self.responses[path]
        return self.responses[path]


def test_allowlist_has_no_production_or_arbitrary_operation():
    assert control.ALLOWED_OPERATIONS == (
        "audit",
        "enforce-worker-isolation",
        "disable-site-branch-deploy",
    )
    assert "delete" not in " ".join(control.ALLOWED_OPERATIONS)
    assert "production" not in " ".join(control.ALLOWED_OPERATIONS)


def test_audit_accepts_exact_isolated_state():
    result = control.audit(FakeClient())
    assert result["staging_worker"] == "observatorio-chapada-v2-staging"
    assert result["staging_bucket"] == "araripe-v2-staging"
    assert result["production_mutated"] is False


def test_audit_rejects_any_additional_binding():
    client = FakeClient(extra_binding={"name": "PROD", "type": "r2_bucket", "bucket_name": "araripe-cogs"})
    with pytest.raises(control.ControlError, match="binding count"):
        control.audit(client)


def test_audit_rejects_staging_route():
    client = FakeClient()
    client.responses[control._paths()["routes"]] = [
        {"pattern": "example.invalid/*", "script": control.STAGING_WORKER}
    ]
    with pytest.raises(control.ControlError, match="zone route"):
        control.audit(client)


def test_trigger_mutation_is_fixed_target_and_fixed_body():
    client = FakeClient()
    result = control.disable_site_nonproduction_deploy(client)
    assert ("PATCH", control._paths()["trigger"], {"deploy_command": control.SAFE_SITE_DEPLOY_COMMAND}) in client.calls
    assert result["site_nonproduction_deploy_command"] == control.SAFE_SITE_DEPLOY_COMMAND


def test_trigger_mutation_fails_if_repository_identity_drifts():
    client = FakeClient()
    client.trigger["repo_connection"]["repo_name"] = "unexpected"
    with pytest.raises(control.ControlError, match="connected site repository"):
        control.disable_site_nonproduction_deploy(client)
