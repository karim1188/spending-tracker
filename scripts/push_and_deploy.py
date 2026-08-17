from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collector.deploy import DeploySettings


def _run_git_push() -> None:
    subprocess.run(["git", "push", "origin", "HEAD"], check=True, cwd=ROOT)


def _deploy_request(url: str, token: str) -> dict:
    payload = json.dumps({}).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def _wait_for_health(base_url: str, timeout_sec: float) -> bool:
    health_url = base_url.rstrip("/")
    if health_url.endswith("/api/deploy"):
        health_url = health_url[: -len("/api/deploy")]
    health_url = f"{health_url}/api/health"
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(health_url, timeout=5) as response:
                body = json.loads(response.read().decode("utf-8"))
            if body.get("ok"):
                return True
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError):
            pass
        time.sleep(2)
    return False


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Push to GitHub then auto-deploy the Mac ledger (stop → pull → restart)"
    )
    parser.add_argument(
        "--url",
        default=None,
        help="Deploy API URL on the Mac (default: config/deploy.json deploy_url)",
    )
    parser.add_argument("--token", default=None, help="Deploy token (default: config/deploy.json)")
    parser.add_argument(
        "--no-push",
        action="store_true",
        help="Skip git push (use from post-push hook)",
    )
    parser.add_argument(
        "--no-wait",
        action="store_true",
        help="Do not wait for the ledger to come back after restart",
    )
    parser.add_argument(
        "--wait-seconds",
        type=float,
        default=120.0,
        help="Max seconds to wait for health (default 120)",
    )
    args = parser.parse_args()

    token = args.token
    deploy_url = args.url
    if not token or not deploy_url:
        try:
            settings = DeploySettings.load()
            token = token or settings.token
            deploy_url = deploy_url or settings.deploy_url
        except Exception as exc:
            print(str(exc))
            return 2

    if not args.no_push:
        print("Pushing to origin…")
        try:
            _run_git_push()
        except subprocess.CalledProcessError as exc:
            print(f"git push failed (exit {exc.returncode})")
            return exc.returncode or 1

    print(f"Triggering deploy at {deploy_url} …")
    try:
        body = _deploy_request(deploy_url, token)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        print(f"Deploy failed ({exc.code}): {detail}")
        return 1
    except urllib.error.URLError as exc:
        print(f"Could not reach ledger: {exc.reason}")
        return 1

    if not body.get("ok"):
        print(body.get("error") or "Deploy failed")
        return 1

    print(body.get("message") or "Deploy triggered")
    if body.get("log"):
        print(f"Log on Mac: {body['log']}")

    if not args.no_wait:
        print("Waiting for ledger to come back…")
        if _wait_for_health(deploy_url, args.wait_seconds):
            base = deploy_url.replace("/api/deploy", "")
            print(f"Ledger is up: {base}")
            return 0
        print("Timed out waiting for /api/health")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
