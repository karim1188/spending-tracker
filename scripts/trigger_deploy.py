from __future__ import annotations

import argparse
import json
import sys
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
        default="http://192.168.100.59:8787/api/deploy",
        help="Ledger deploy API URL",
    )
    parser.add_argument(
        "--token",
        default=None,
        help="Deploy token (default: config/deploy.json or DEPLOY_TOKEN env)",
    )
    args = parser.parse_args()

    token = args.token
    if not token:
        try:
            token = DeploySettings.load().token
        except Exception as exc:
            print(str(exc))
            return 2

    payload = json.dumps({}).encode("utf-8")
    request = urllib.request.Request(
        args.url,
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
    return 0 if body.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
