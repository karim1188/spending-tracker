from __future__ import annotations

import argparse
import sys
import threading
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collector.logging_config import setup_logging
from web.server import HOST, PORT, serve


def main() -> int:
    parser = argparse.ArgumentParser(description="Open the local spending ledger")
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    setup_logging()
    httpd = serve(args.host, args.port)
    url = f"http://{args.host}:{args.port}"
    print(f"[INFO] Ledger UI at {url}")
    print("[INFO] Bound to localhost only. No cloud. chat.db stays read-only.")
    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[INFO] Ledger stopped")
        httpd.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
