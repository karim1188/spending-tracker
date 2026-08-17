from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collector.deploy import DeploySettings


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Trigger a remote deploy: stop app → git pull → restart"
    )
    parser.add_argument(
        "--url",
        default=None,
        help="Ledger deploy API URL (default: config/deploy.json deploy_url)",
    )
    parser.add_argument(
        "--token",
        default=None,
        help="Deploy token (default: config/deploy.json or DEPLOY_TOKEN env)",
    )
    parser.add_argument(
        "--wait",
        action="store_true",
        help="Wait until /api/health responds after restart",
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

    payload = json.dumps({}).encode("utf-8")
    request = urllib.request.Request(
        deploy_url,
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        print(f"Deploy failed ({exc.code}): {detail}")
        return 1
    except urllib.error.URLError as exc:
        print(f"Could not reach ledger: {exc.reason}")
        return 1

    print(body.get("message") or "Deploy triggered")
    if body.get("log"):
        print(f"Log on Mac: logs/{Path(str(body['log'])).name}")

    if args.wait:
        health_url = deploy_url.replace("/api/deploy", "/api/health")
        deadline = time.time() + args.wait_seconds
        print("Waiting for ledger to come back…")
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(health_url, timeout=5) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                if payload.get("ok"):
                    print(f"Ledger is up: {deploy_url.replace('/api/deploy', '')}")
                    return 0
            except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError):
                pass
            time.sleep(2)
        print("Timed out waiting for /api/health")
        return 1

    return 0 if body.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
