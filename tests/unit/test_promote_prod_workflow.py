"""`.github/workflows/promote-prod.yml` (CIW-10.2): manual only, the tag is
validated before the approval gate, the deploy promotes the exact GHCR image
to ciw-prod with no build, and the smoke check expects the promoted tag.

The format check (a) is not re-implemented here: the test runs the
workflow's own `run:` script with bash, the way the runner does."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "promote-prod.yml"
TEXT = WORKFLOW_PATH.read_text(encoding="utf-8")
WORKFLOW = yaml.safe_load(TEXT)
# PyYAML reads the bare key `on` as the boolean True.
TRIGGERS = WORKFLOW.get("on", WORKFLOW.get(True))
JOBS = WORKFLOW["jobs"]
VALIDATE = JOBS["validate"]
DEPLOY = JOBS["deploy"]

SHA = "0123456789abcdef0123456789abcdef01234567"


def _bash() -> str | None:
    if os.name == "nt":  # C:\Windows\System32\bash.exe is WSL, not Git Bash
        git_bash = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git/bin/bash.exe"
        return str(git_bash) if git_bash.exists() else None
    return shutil.which("bash")


BASH = _bash()


def _step(job: dict, name_prefix: str) -> dict:
    matches = [s for s in job["steps"] if s.get("name", "").startswith(name_prefix)]
    assert len(matches) == 1, name_prefix
    return matches[0]


def _run_format_check(tag: str, tmp_path: Path) -> tuple[int, str, str]:
    step = _step(VALIDATE, "(a)")
    output = tmp_path / "github_output"
    output.write_text("", encoding="utf-8")
    env = {**os.environ, "TAG": tag, "GITHUB_OUTPUT": str(output)}
    # `shell: bash` on the runner is `bash --noprofile --norc -eo pipefail {0}`.
    result = subprocess.run(
        [BASH, "--noprofile", "--norc", "-eo", "pipefail", "-c", step["run"]],
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result.returncode, result.stdout, output.read_text(encoding="utf-8")


# --- triggers ---------------------------------------------------------------


def test_triggered_only_by_workflow_dispatch_with_one_required_tag_input():
    assert list(TRIGGERS) == ["workflow_dispatch"]
    inputs = TRIGGERS["workflow_dispatch"]["inputs"]
    assert list(inputs) == ["tag"]
    assert inputs["tag"]["required"] is True
    assert inputs["tag"]["type"] == "string"


# --- (a) tag format, run through the workflow's own script -------------------


@pytest.mark.skipif(BASH is None, reason="needs bash (Git Bash on Windows)")
def test_a_full_lowercase_sha_tag_passes_and_is_the_job_output(tmp_path):
    code, _, output = _run_format_check(f"sha-{SHA}", tmp_path)
    assert code == 0
    assert output == f"tag=sha-{SHA}\n"
    assert VALIDATE["outputs"]["tag"] == "${{ steps.format.outputs.tag }}"


@pytest.mark.skipif(BASH is None, reason="needs bash (Git Bash on Windows)")
@pytest.mark.parametrize(
    "tag",
    [
        "dev",
        "latest",
        "",
        f"sha-{SHA[:7]}",  # short SHA
        f"sha-{SHA[:39]}",  # one character short
        f"sha-{SHA}0",  # one character long
        f"sha-{SHA.upper()}",  # uppercase hex
        f"sha-{SHA[:-1]}A",  # one uppercase character
        f" sha-{SHA}",  # surrounding spaces
        f"sha-{SHA} ",
        f"sha-{SHA}\n",
        SHA,  # no sha- prefix
        f"SHA-{SHA}",
        f"sha-{SHA[:-1]}g",  # not hex
        f"sha-{SHA}\nsha-{SHA}",
    ],
)
def test_a_malformed_tag_is_refused_with_the_reason_and_no_output(tmp_path, tag):
    code, stdout, output = _run_format_check(tag, tmp_path)
    assert code != 0
    assert "::error::Refused:" in stdout
    assert "40-character lowercase hex" in stdout
    assert output == ""
    # Printed with %q: a newline in the input cannot start a new log line.
    assert len(stdout.strip().splitlines()) == 1


def test_the_input_reaches_the_shell_only_through_the_environment():
    for job in JOBS.values():
        for step in job["steps"]:
            assert "inputs." not in step.get("run", ""), step.get("name")
    assert _step(VALIDATE, "(a)")["env"]["TAG"] == "${{ inputs.tag }}"


# --- (b) GHCR and (c) dev ran it ---------------------------------------------


def test_b_refuses_a_tag_missing_from_ghcr():
    step = _step(VALIDATE, "(b)")
    assert 'docker manifest inspect "$IMAGE:$TAG"' in step["run"]
    assert "::error::Refused:" in step["run"] and "does not exist in GHCR" in step["run"]
    assert WORKFLOW["env"]["IMAGE"] == "ghcr.io/elugardo/catalog-import-watchtower"


def test_c_refuses_a_tag_dev_never_deployed_successfully():
    run = _step(VALIDATE, "(c)")["run"]
    assert "actions/workflows/deploy-dev.yml/runs?head_sha=$sha&status=success" in run
    assert 'sha="${TAG#sha-}"' in run
    assert "::error::Refused: dev never ran" in run


def test_validation_runs_before_the_gate_without_environment_secret_or_flyctl():
    assert "environment" not in VALIDATE
    assert DEPLOY["needs"] == "validate"
    validate_text = yaml.safe_dump(VALIDATE)
    assert "secrets." not in validate_text
    assert "flyctl" not in validate_text
    assert VALIDATE["steps"][0].get("id") == "format"


# --- deploy ------------------------------------------------------------------


def test_deploy_job_is_gated_by_the_production_environment():
    assert DEPLOY["environment"]["name"] == "production"
    assert WORKFLOW["env"]["PROD_URL"] == "https://ciw-prod.fly.dev"
    assert DEPLOY["env"]["TAG"] == "${{ needs.validate.outputs.tag }}"


def test_token_is_checked_before_the_first_flyctl_call():
    runs = [s.get("run", "") for s in DEPLOY["steps"]]
    token_check = next(i for i, r in enumerate(runs) if '-z "$FLY_API_TOKEN"' in r)
    first_flyctl = next(i for i, r in enumerate(runs) if "flyctl " in r)
    assert token_check < first_flyctl


def test_deploys_the_exact_ghcr_image_to_ciw_prod_app_group_only():
    assert WORKFLOW["env"]["FLY_APP"] == "ciw-prod"
    run = _step(DEPLOY, "flyctl deploy")["run"]
    assert 'flyctl deploy --config fly.prod.toml -a "$FLY_APP"' in run
    assert '--image "$IMAGE:$TAG"' in run
    assert "--process-groups app" in run


def test_keeps_zero_worker_machines():
    run = _step(DEPLOY, "Keep zero worker machines")["run"]
    assert "flyctl scale count worker=0" in run
    assert run.strip().splitlines()[-1].endswith("= 0")


def test_smoke_check_expects_the_promoted_tag_on_the_prod_url():
    run = _step(DEPLOY, "Smoke check")["run"]
    assert run.startswith('python3 scripts/smoke_check.py "$PROD_URL" "$TAG"')
    assert DEPLOY["steps"][-1]["name"].startswith("Smoke check")


@pytest.mark.parametrize(
    "pattern",
    [
        r"docker build",
        r"buildx build",
        r"build-push-action",
        r"--build-only",
        r"--remote-only",
        r"--local-only",
        r"--dockerfile",
    ],
)
def test_no_build_step_anywhere(pattern):
    assert pattern not in TEXT


# --- concurrency, permissions, secrets ----------------------------------------


def test_promotions_run_one_at_a_time_and_are_never_cancelled():
    assert DEPLOY["concurrency"] == {"group": "promote-prod", "cancel-in-progress": False}
    assert "concurrency" not in WORKFLOW  # validation never queues behind a deploy


def test_token_permissions_are_read_only():
    assert WORKFLOW["permissions"] == {"contents": "read"}
    assert VALIDATE["permissions"] == {"actions": "read"}  # check (c) only
    assert "permissions" not in DEPLOY
    assert "write" not in yaml.safe_dump(WORKFLOW.get("permissions"))


def test_the_only_secret_is_the_fly_token_in_the_deploy_job():
    assert set(re.findall(r"secrets\.(\w+)", TEXT)) == {"FLY_API_TOKEN"}
    for step in DEPLOY["steps"]:
        assert "secrets." not in step.get("run", "")  # only via env, never echoed


def test_names_only_ciw_prod():
    assert set(re.findall(r"\bciw-[a-z]+\b", TEXT)) == {"ciw-prod"}
    for other in ["fly.toml", ".github/workflows/deploy-dev.yml", ".github/workflows/ci.yml"]:
        assert "ciw-prod" not in (ROOT / other).read_text(encoding="utf-8"), other
