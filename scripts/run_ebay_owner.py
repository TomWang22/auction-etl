"""Run the long-lived headed/offscreen eBay Playwright owner."""

from __future__ import annotations

import argparse
import json
import os
import signal
import socketserver
import sys
import threading
from pathlib import Path
from typing import Any, Mapping

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]

if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from playwright.sync_api import Browser, Playwright, sync_playwright

from auction_etl.browser.ebay_owner import OWNER_PROTOCOL_VERSION
from auction_etl.runtime_authority import (
    LOCAL_DATABASE_TARGET,
    cloud_runtime_detected,
)
from scripts.acquire_ebay_structured import acquire_page


def parse_arguments() -> argparse.Namespace:
    """Parse owner daemon arguments."""

    parser = argparse.ArgumentParser(
        description=(
            "Own one persistent headed eBay Chromium process and "
            "create a fresh authenticated context per acquisition."
        )
    )
    parser.add_argument(
        "--storage-state",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--socket-path",
        type=Path,
        required=True,
    )
    return parser.parse_args()


class EbayOwner:
    """Keep one headed Chromium and mint a fresh context per acquire."""

    def __init__(
        self,
        *,
        playwright: Playwright,
        browser: Browser,
        storage_state: Path,
        executable: Path,
        stop_event: threading.Event,
    ) -> None:
        self._playwright = playwright
        self._browser = browser
        self._storage_state = storage_state.expanduser().resolve()
        self._executable = executable
        self._stop_event = stop_event

    def _assert_browser_alive(self) -> None:
        """Require a live Chromium before reusing the owner."""

        try:
            if not self._browser.is_connected():
                raise RuntimeError(
                    "eBay owner Chromium is not connected."
                )
        except Exception:
            self._stop_event.set()
            raise

    def handle(
        self,
        request: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Handle one versioned owner request."""

        protocol_version = request.get("protocol_version")

        if protocol_version != OWNER_PROTOCOL_VERSION:
            raise RuntimeError(
                "Unsupported eBay owner protocol version: "
                f"{protocol_version!r}"
            )

        command = str(request.get("command", ""))
        payload = request.get("payload", {})

        if not isinstance(payload, dict):
            raise RuntimeError(
                "Owner request payload must be an object."
            )

        if command == "health":
            self._assert_browser_alive()

            return {
                "ok": True,
                "protocol_version": OWNER_PROTOCOL_VERSION,
                "pid": os.getpid(),
                "storage_state": str(self._storage_state),
                "executable": str(self._executable),
                "headless": False,
                "cdp": False,
                "browser_reuse": True,
            }

        if command == "shutdown":
            self._stop_event.set()

            return {
                "ok": True,
                "exit_code": 0,
                "output": "",
            }

        if command == "acquire_structured":
            return self._acquire_structured(payload)

        raise RuntimeError(
            f"Unsupported eBay owner command: {command}"
        )

    def _acquire_structured(
        self,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Acquire one search page through a fresh authenticated context."""

        self._assert_browser_alive()

        url = str(payload.get("url", "")).strip()
        timeout_seconds = float(payload.get("timeout_seconds", 30.0))
        settle_seconds = float(payload.get("settle_seconds", 2.0))
        requested_state = str(payload.get("storage_state", "")).strip()

        if requested_state:
            requested_path = Path(requested_state).expanduser().resolve()

            if requested_path != self._storage_state:
                raise RuntimeError(
                    "Owner job requested a different eBay storage-state file: "
                    f"{requested_path}"
                )

        acquired = acquire_page(
            url=url,
            profile_dir=None,
            storage_state=self._storage_state,
            headless=False,
            timeout_seconds=timeout_seconds,
            settle_seconds=settle_seconds,
            browser=self._browser,
        )

        return {
            "ok": True,
            "requested_url": acquired.requested_url,
            "final_url": acquired.final_url,
            "http_status": acquired.http_status,
            "item_link_count": acquired.item_link_count,
            "html": acquired.html,
        }


class OwnerServer(socketserver.UnixStreamServer):
    """Sequential Unix server so all Playwright calls stay on the owner thread."""

    allow_reuse_address = False

    def __init__(
        self,
        socket_path: Path,
        owner: EbayOwner,
    ) -> None:
        self.owner = owner
        super().__init__(
            str(socket_path),
            OwnerRequestHandler,
        )


class OwnerRequestHandler(socketserver.StreamRequestHandler):
    """Process one newline-delimited JSON owner request."""

    def handle(self) -> None:
        raw = self.rfile.readline(10 * 1024 * 1024)

        if not raw:
            return

        try:
            request = json.loads(raw.decode("utf-8"))

            if not isinstance(request, dict):
                raise RuntimeError(
                    "Owner request must be a JSON object."
                )

            response = self.server.owner.handle(request)
        except Exception as error:
            response = {
                "ok": False,
                "error": f"{type(error).__name__}: {error}",
            }

        encoded = (
            json.dumps(
                response,
                ensure_ascii=False,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")

        self.wfile.write(encoded)
        self.wfile.flush()


def main() -> int:
    """Launch one headed Chromium and serve local owner jobs."""

    if cloud_runtime_detected():
        raise RuntimeError(
            "The eBay browser owner may only run on the local machine. "
            "Vercel and Railway must not acquire eBay. "
            f"Local warehouse remains {LOCAL_DATABASE_TARGET}."
        )

    arguments = parse_arguments()
    storage_state = arguments.storage_state.expanduser().resolve()
    socket_path = arguments.socket_path.expanduser().resolve()

    if not storage_state.is_file():
        raise RuntimeError(
            f"eBay storage-state file is missing: {storage_state}"
        )

    socket_path.parent.mkdir(parents=True, exist_ok=True)

    if socket_path.exists():
        raise RuntimeError(
            f"Owner socket already exists: {socket_path}"
        )

    stop_event = threading.Event()

    def request_stop(
        _signum: int,
        _frame: object,
    ) -> None:
        stop_event.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)

    with sync_playwright() as playwright:
        executable = Path(
            playwright.chromium.executable_path
        ).resolve()

        browser = playwright.chromium.launch(
            channel="chrome",
            headless=False,
            args=[
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-popup-blocking",
                "--window-position=80,80",
                "--window-size=1200,900",
            ],
        )

        try:
            owner = EbayOwner(
                playwright=playwright,
                browser=browser,
                storage_state=storage_state,
                executable=executable,
                stop_event=stop_event,
            )

            with OwnerServer(socket_path, owner) as server:
                os.chmod(socket_path, 0o600)
                server.timeout = 0.5

                print("EBAY_OWNER_READY=true", flush=True)
                print(f"EBAY_OWNER_PID={os.getpid()}", flush=True)
                print(
                    f"EBAY_OWNER_STORAGE_STATE={storage_state}",
                    flush=True,
                )
                print(f"EBAY_OWNER_SOCKET={socket_path}", flush=True)
                print(
                    f"EBAY_OWNER_EXECUTABLE={executable}",
                    flush=True,
                )
                print("EBAY_OWNER_HEADLESS=false", flush=True)
                print("EBAY_OWNER_CDP=false", flush=True)

                while not stop_event.is_set():
                    server.handle_request()
        finally:
            try:
                browser.close()
            except Exception:
                pass

            try:
                socket_path.unlink(missing_ok=True)
            except OSError:
                pass

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
