from __future__ import annotations

import argparse
import os
import sys
import threading
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collector.logging_config import setup_logging
from notify.shutdown import register_shutdown
from web.server import HOST, PORT, advertised_urls, serve


def _run_telegram_alerts() -> None:
    from notify.alerts import run_loop

    run_loop(interval=60.0)


def main() -> int:
    parser = argparse.ArgumentParser(description="Open the local spending ledger")
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument(
        "--localhost",
        action="store_true",
        help="Bind only to 127.0.0.1 instead of the local network",
    )
    args = parser.parse_args()
    host = "127.0.0.1" if args.localhost else args.host

    setup_logging()
    httpd = serve(host, args.port)

    def _on_shutdown(reason: str) -> None:
        print(f"[WARN] Shutting down: {reason}")
        try:
            httpd.shutdown()
        finally:
            # Brief pause so an in-flight Telegram send can finish, then hard-exit.
            time.sleep(0.8)
            os._exit(0)

    register_shutdown(_on_shutdown)

    urls = advertised_urls(host, args.port)
    print(f"[INFO] Ledger UI on this Mac: {urls[0]}")
    for url in urls[1:]:
        print(f"[INFO] On your phone (same Wi-Fi): {url}")
    if host in {"0.0.0.0", "::"}:
        print("[INFO] Open on the local network. No cloud. chat.db stays read-only.")
        print("[INFO] Anyone on this Wi-Fi can open the ledger. Use --localhost to keep it private.")
    else:
        print("[INFO] Bound to localhost only. No cloud. chat.db stays read-only.")
    print("[INFO] Idle mode: wakes on new Messages or Telegram; no timed chat.db polling.")
    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(urls[0])).start()
    threading.Thread(target=_run_telegram_alerts, daemon=True, name="idle-runtime").start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[INFO] Ledger stopped")
        httpd.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
