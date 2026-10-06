"""Start or reuse a hidden local Google Chrome CDP endpoint."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.ensure_buyee_cdp_browser import (  # noqa: E402
    endpoint_ready,
    endpoint_url,
    launch_hidden_chrome,
    wait_until_ready,
)


DEFAULT_PORT = 9223


def parse_arguments() -> argparse.Namespace:
    """Parse hidden-Chrome arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Ensure a hidden headed Google Chrome instance exposes "
            "a persistent profile over localhost CDP."
        ),
    )
    parser.add_argument("--profile-dir", type=Path, required=True)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    return parser.parse_args()


def main() -> int:
    """Ensure the hidden Chrome CDP endpoint is available."""
    arguments = parse_arguments()
    profile_dir = arguments.profile_dir.expanduser().resolve()
    profile_dir.mkdir(parents=True, exist_ok=True)

    if arguments.port < 1:
        raise SystemExit("ERROR: --port must be positive.")

    base_url = endpoint_url(arguments.port)
    if endpoint_ready(base_url):
        print("HIDDEN_CHROME_BROWSER=reused")
        print("HIDDEN_CHROME_CDP_URL=" + base_url)
        print("VISIBLE_BROWSER_LAUNCHED=true")
        return 0

    launch_hidden_chrome(profile_dir, arguments.port)
    wait_until_ready(base_url)
    print("HIDDEN_CHROME_BROWSER=started")
    print("HIDDEN_CHROME_CDP_URL=" + base_url)
    print("HIDDEN_CHROME_PROFILE=" + str(profile_dir))
    print("CHROME_HEADLESS=false")
    print("CHROME_APPLICATION_HIDDEN=false")
    print("VISIBLE_BROWSER_LAUNCHED=true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
