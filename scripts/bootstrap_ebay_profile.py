from __future__ import annotations

import argparse
from pathlib import Path

from playwright.sync_api import sync_playwright

from auction_etl.browser.profiles import profile_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Initialize an authenticated persistent eBay browser profile."
    )
    parser.add_argument(
        "--profile",
        default="facerecords",
    )
    parser.add_argument(
        "--url",
        required=True,
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    user_data_dir = Path(
        profile_path(args.profile)
    )
    user_data_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    print(f"Profile directory: {user_data_dir}")
    print()
    print("A browser window will remain open.")
    print("Complete any normal eBay login or verification.")
    print("Confirm the completed-results page is visible.")
    print("Return to this terminal and press Enter only when finished.")
    print()

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(user_data_dir),
            headless=False,
            viewport={
                "width": 1440,
                "height": 1000,
            },
            locale="en-US",
        )

        page = (
            context.pages[0]
            if context.pages
            else context.new_page()
        )

        try:
            response = page.goto(
                args.url,
                wait_until="domcontentloaded",
                timeout=120_000,
            )

            status = (
                response.status
                if response is not None
                else "unknown"
            )

            print(f"Initial HTTP status: {status}")
            print(f"Current URL: {page.url}")
            print()

            input(
                "Press Enter after eBay results are visible..."
            )

            page.reload(
                wait_until="domcontentloaded",
                timeout=120_000,
            )

            page.wait_for_timeout(5_000)

            print()
            print(f"Saved URL: {page.url}")
            print(f"Saved title: {page.title()}")
            print(
                "The persistent profile has been saved."
            )

        finally:
            context.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
