"""Start or reuse the hidden local Chrome service used for Buyee CDP."""

from __future__ import annotations

import argparse
import json
import platform
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path


DEFAULT_PORT = 9334
STARTUP_TIMEOUT_SECONDS = 20.0


def parse_arguments() -> argparse.Namespace:
    """Parse background-browser arguments."""

    parser = argparse.ArgumentParser(
        description=(
            "Ensure a hidden headed Chrome instance exposes "
            "the persistent Buyee profile over localhost CDP."
        ),
    )

    parser.add_argument(
        "--profile-dir",
        type=Path,
        required=True,
    )

    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
    )

    return parser.parse_args()


def endpoint_url(
    port: int,
) -> str:
    """Return the local Chrome DevTools endpoint."""

    return (
        f"http://127.0.0.1:{port}"
    )


def endpoint_ready(
    base_url: str,
) -> bool:
    """Return whether a Chromium DevTools endpoint is available."""

    request = urllib.request.Request(
        base_url + "/json/version",
        headers={
            "Accept":
                "application/json",
        },
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=1.0,
        ) as response:
            if response.status != 200:
                return False

            payload = json.loads(
                response.read().decode(
                    "utf-8"
                )
            )
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        urllib.error.URLError,
    ):
        return False

    return bool(
        isinstance(
            payload,
            dict,
        )
        and payload.get(
            "webSocketDebuggerUrl"
        )
    )


def launch_hidden_chrome(
    profile_dir: Path,
    port: int,
) -> None:
    """Launch normal Chrome hidden without activating a browser window."""

    if platform.system() != "Darwin":
        raise RuntimeError(
            "The current background Buyee launcher "
            "supports macOS only."
        )

    command = [
        "open",
        "-g",
        "-j",
        "-n",
        "-a",
        "Google Chrome",
        "--args",
        (
            "--remote-debugging-address="
            "127.0.0.1"
        ),
        (
            "--remote-debugging-port="
            + str(
                port
            )
        ),
        (
            "--user-data-dir="
            + str(
                profile_dir
            )
        ),
        "--remote-allow-origins=*",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-popup-blocking",
        "--window-position=-32000,-32000",
        "--window-size=1200,900",
        "about:blank",
    ]

    subprocess.run(
        command,
        check=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def wait_until_ready(
    base_url: str,
) -> None:
    """Wait for the newly launched local CDP endpoint."""

    deadline = (
        time.monotonic()
        + STARTUP_TIMEOUT_SECONDS
    )

    while time.monotonic() < deadline:
        if endpoint_ready(
            base_url
        ):
            return

        time.sleep(
            0.25
        )

    raise RuntimeError(
        "Hidden Buyee Chrome did not expose "
        f"CDP at {base_url}."
    )


def main() -> int:
    """Ensure the hidden authenticated Buyee browser is running."""

    arguments = parse_arguments()

    profile_dir = (
        arguments.profile_dir
        .expanduser()
        .resolve()
    )

    if not profile_dir.is_dir():
        raise SystemExit(
            "ERROR: Buyee profile directory "
            f"does not exist: {profile_dir}"
        )

    if arguments.port < 1:
        raise SystemExit(
            "ERROR: --port must be positive."
        )

    base_url = endpoint_url(
        arguments.port
    )

    if endpoint_ready(
        base_url
    ):
        print(
            "BUYEE_BACKGROUND_BROWSER=reused"
        )

        print(
            "BUYEE_CDP_URL="
            + base_url
        )

        print(
            "VISIBLE_BROWSER_LAUNCHED=false"
        )

        return 0

    launch_hidden_chrome(
        profile_dir,
        arguments.port,
    )

    wait_until_ready(
        base_url
    )

    print(
        "BUYEE_BACKGROUND_BROWSER=started"
    )

    print(
        "BUYEE_CDP_URL="
        + base_url
    )

    print(
        "BUYEE_PROFILE="
        + str(
            profile_dir
        )
    )

    print(
        "CHROME_HEADLESS=false"
    )

    print(
        "CHROME_APPLICATION_HIDDEN=true"
    )

    print(
        "VISIBLE_BROWSER_LAUNCHED=false"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
