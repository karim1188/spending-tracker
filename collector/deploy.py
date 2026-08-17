from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from collector.project_paths import DEPLOY_CONFIG_PATH, LOGS_DIR, PROJECT_ROOT


class DeployConfigError(Exception):
    """Deploy is not configured or the token is invalid."""


@dataclass(frozen=True)
class DeploySettings:
    token: str
    branch: str = "main"
    port: int = 8787
    deploy_url: str = "http://192.168.100.59:8787/api/deploy"
    start_command: tuple[str, ...] = ("python3", "scripts/start_app.py", "--no-browser")

    @classmethod
    def load(cls, path: Path | None = None) -> DeploySettings:
        cfg_path = path or DEPLOY_CONFIG_PATH
        data: dict = {}
        if cfg_path.is_file():
            data = json.loads(cfg_path.read_text(encoding="utf-8"))
        token = os.environ.get("DEPLOY_TOKEN") or data.get("token")
        if not token or not str(token).strip():
            raise DeployConfigError(
                "Deploy token missing. Copy config/deploy.example.json to config/deploy.json "
                "and set a long random token (or export DEPLOY_TOKEN)."
            )
        branch = str(os.environ.get("DEPLOY_BRANCH") or data.get("branch") or "main").strip() or "main"
        port_raw = os.environ.get("DEPLOY_PORT") or data.get("port") or 8787
        try:
            port = int(port_raw)
        except (TypeError, ValueError):
            port = 8787
        cmd = data.get("start_command")
        if isinstance(cmd, list) and cmd:
            start_command = tuple(str(part) for part in cmd)
        else:
            start_command = cls.start_command
        return cls(
            token=str(token).strip(),
            branch=branch,
            port=port,
            deploy_url=str(
                os.environ.get("DEPLOY_URL") or data.get("deploy_url") or cls.deploy_url
            ).strip(),
            start_command=start_command,
        )


def token_is_valid(provided: str | None, settings: DeploySettings | None = None) -> bool:
    if not provided:
        return False
    try:
        expected = (settings or DeploySettings.load()).token
    except DeployConfigError:
        return False
    return secrets.compare_digest(provided.strip(), expected)


def extract_deploy_token(headers: dict[str, str], body: dict | None = None) -> str | None:
    auth = headers.get("Authorization") or headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    for key in ("X-Deploy-Token", "x-deploy-token"):
        if headers.get(key):
            return str(headers[key]).strip()
    if body and body.get("token"):
        return str(body["token"]).strip()
    return None


def spawn_restart_worker(settings: DeploySettings | None = None) -> Path:
    """Launch the detached Mac restart script before the server exits."""
    cfg = settings or DeploySettings.load()
    script = PROJECT_ROOT / "scripts" / "restart_after_pull.sh"
    if not script.is_file():
        raise FileNotFoundError(f"Missing restart script: {script}")
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOGS_DIR / "deploy.log"
    env = os.environ.copy()
    env["DEPLOY_BRANCH"] = cfg.branch
    env["DEPLOY_PORT"] = str(cfg.port)
    env["DEPLOY_START_COMMAND"] = " ".join(cfg.start_command)
    with log_path.open("a", encoding="utf-8") as log_file:
        subprocess.Popen(
            ["/bin/bash", str(script)],
            cwd=PROJECT_ROOT,
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            close_fds=True,
        )
    return log_path


def request_deploy_restart(reason: str = "deploy requested") -> dict:
    from notify.shutdown import request_shutdown

    settings = DeploySettings.load()
    log_path = spawn_restart_worker(settings)
    scheduled = request_shutdown(reason)
    if not scheduled:
        raise RuntimeError("Could not schedule app shutdown")
    try:
        log_ref = str(log_path.relative_to(PROJECT_ROOT))
    except ValueError:
        log_ref = str(log_path)
    return {
        "ok": True,
        "message": "Restart scheduled: stop → git pull → start",
        "branch": settings.branch,
        "port": settings.port,
        "log": log_ref,
    }
