"""Run the long-lived headed/offscreen Buyee Playwright owner."""

from __future__ import annotations

import argparse
import contextlib
import importlib
import importlib.util
import inspect
import io
import json
import os
import signal
import socketserver
import sys
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType
from typing import Any, Iterator, Mapping

from playwright.sync_api import BrowserContext, Playwright, sync_playwright

from auction_etl.browser.buyee_owner import OWNER_PROTOCOL_VERSION


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
VERIFIER_PATH = REPOSITORY_ROOT / "scripts" / "verify_buyee_session.py"
DETAIL_CRAWLER_PATH = (
    REPOSITORY_ROOT
    / "scripts"
    / "crawl_buyee_live_details.py"
)


def parse_arguments() -> argparse.Namespace:
    """Parse owner daemon arguments."""

    parser = argparse.ArgumentParser(
        description=(
            "Own one persistent Buyee browser and execute "
            "high-level Buyee jobs internally."
        )
    )
    parser.add_argument(
        "--profile-dir",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--socket-path",
        type=Path,
        required=True,
    )
    return parser.parse_args()


@contextmanager
def temporary_environment(
    values: Mapping[str, str],
) -> Iterator[None]:
    """Temporarily apply request-scoped production environment values."""

    keys = set(values)
    keys.add(
        "AUCTION_BUYEE_CDP_URL"
    )

    previous = {
        key: os.environ.get(
            key
        )
        for key in keys
    }

    try:
        os.environ.pop(
            "AUCTION_BUYEE_CDP_URL",
            None,
        )

        for key, value in values.items():
            os.environ[
                str(key)
            ] = str(
                value
            )

        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(
                    key,
                    None,
                )
            else:
                os.environ[
                    key
                ] = value


@contextmanager
def temporary_argv(
    program: str,
    arguments: list[str],
) -> Iterator[None]:
    """Temporarily replace sys.argv for one in-process CLI job."""

    previous = sys.argv[:]

    try:
        sys.argv = [
            program,
            *arguments,
        ]
        yield
    finally:
        sys.argv = previous


class BorrowedSyncPlaywright:
    """Context manager that yields the owner's existing Playwright instance."""

    def __init__(
        self,
        playwright: Playwright,
    ) -> None:
        self._playwright = playwright

    def __enter__(
        self,
    ) -> Playwright:
        return self._playwright

    def __exit__(
        self,
        _exc_type: object,
        _exc: object,
        _traceback: object,
    ) -> bool:
        return False


def load_script_module(
    path: Path,
) -> tuple[str, ModuleType]:
    """Load one repository script as a fresh importable module."""

    module_name = (
        "_auction_buyee_owner_"
        + path.stem
        + "_"
        + uuid.uuid4().hex
    )

    spec = importlib.util.spec_from_file_location(
        module_name,
        path,
    )

    if (
        spec is None
        or spec.loader is None
    ):
        raise RuntimeError(
            f"Could not load script module: {path}"
        )

    module = importlib.util.module_from_spec(
        spec
    )
    sys.modules[
        module_name
    ] = module

    try:
        spec.loader.exec_module(
            module
        )
    except Exception:
        sys.modules.pop(
            module_name,
            None,
        )
        raise

    return (
        module_name,
        module,
    )


def normalize_exit_code(
    value: object,
) -> int:
    """Convert a CLI return value into a process-style exit code."""

    if value is None:
        return 0

    if isinstance(
        value,
        bool,
    ):
        return int(
            value
        )

    try:
        return int(
            value
        )
    except (
        TypeError,
        ValueError,
    ) as error:
        raise RuntimeError(
            f"Unsupported CLI return value: {value!r}"
        ) from error


def invoke_main(
    module: ModuleType,
    arguments: list[str],
    *,
    program: str,
) -> tuple[int, str]:
    """Run one module main function while capturing terminal output."""

    main = getattr(
        module,
        "main",
        None,
    )

    if not callable(main):
        typer_app = getattr(
            module,
            "app",
            None,
        )

        if not callable(typer_app):
            module_name = getattr(
                module,
                "__name__",
                "<module>",
            )

            raise RuntimeError(
                f"{module_name} exposes neither a callable "
                "main() nor a callable app."
            )

        def invoke_typer_app() -> object:
            """Invoke a Typer application without exiting the owner."""

            return typer_app(
                standalone_mode=False,
            )

        main = invoke_typer_app

    output = io.StringIO()

    with (
        temporary_argv(
            program,
            arguments,
        ),
        contextlib.redirect_stdout(
            output
        ),
        contextlib.redirect_stderr(
            output
        ),
    ):
        try:
            signature = inspect.signature(
                main
            )

            if len(
                signature.parameters
            ) == 0:
                result = main()
            else:
                result = main(
                    arguments
                )
        except SystemExit as error:
            result = error.code

    return (
        normalize_exit_code(
            result
        ),
        output.getvalue(),
    )


class BuyeeOwner:
    """Execute all Buyee browser work inside one persistent context."""

    def __init__(
        self,
        *,
        playwright: Playwright,
        context: BrowserContext,
        profile_dir: Path,
        executable: Path,
        stop_event: threading.Event,
    ) -> None:
        self._playwright = playwright
        self._context = context
        self._profile_dir = (
            profile_dir
            .expanduser()
            .resolve()
        )
        self._executable = executable
        self._stop_event = stop_event

    def _borrowed_open_context(
        self,
        _playwright: Playwright,
        *,
        profile_dir: Path,
        headless: bool,
        launch_options: Mapping[str, Any] | None = None,
    ) -> tuple[BrowserContext, bool, None]:
        """Return the owner's context to an owner-executed repository script."""

        del headless
        del launch_options

        requested_profile = (
            Path(
                profile_dir
            )
            .expanduser()
            .resolve()
        )

        if (
            requested_profile
            != self._profile_dir
        ):
            raise RuntimeError(
                "Owner job requested a different Buyee profile: "
                f"{requested_profile}"
            )

        return (
            self._context,
            False,
            None,
        )

    def _run_repository_script(
        self,
        path: Path,
        *,
        arguments: list[str],
        environment: Mapping[str, str],
    ) -> dict[str, Any]:
        """Run an existing Buyee script against the owner's context."""

        module_name = ""
        module: ModuleType | None = None

        with temporary_environment(
            environment
        ):
            try:
                module_name, module = load_script_module(
                    path
                )

                module.sync_playwright = (
                    lambda: BorrowedSyncPlaywright(
                        self._playwright
                    )
                )

                if not hasattr(
                    module,
                    "open_buyee_context",
                ):
                    raise RuntimeError(
                        f"{path.name} no longer exposes open_buyee_context."
                    )

                module.open_buyee_context = (
                    self._borrowed_open_context
                )

                exit_code, output = invoke_main(
                    module,
                    arguments,
                    program=str(
                        path
                    ),
                )
            finally:
                if module_name:
                    sys.modules.pop(
                        module_name,
                        None,
                    )

        return {
            "ok": True,
            "exit_code": exit_code,
            "output": output,
        }

    def _run_closed_watchlist_cli(
        self,
        *,
        arguments: list[str],
        environment: Mapping[str, str],
    ) -> dict[str, Any]:
        """Run the existing crawl CLI with BrowserManager borrowing the owner."""

        manager_module = importlib.import_module(
            "auction_etl.browser.manager"
        )
        cli_module = importlib.import_module(
            "auction_etl.cli.main"
        )

        manager_class = getattr(
            manager_module,
            "BrowserManager",
        )
        original_context = (
            manager_class.context
        )
        owner_profile = (
            self._profile_dir.name
        )

        def borrowed_context(
            manager: object,
            profile: str = "anonymous",
        ) -> BrowserContext:
            if (
                profile
                == owner_profile
            ):
                return self._context

            return original_context(
                manager,
                profile,
            )

        manager_class.context = (
            borrowed_context
        )

        try:
            with temporary_environment(
                environment
            ):
                exit_code, output = invoke_main(
                    cli_module,
                    arguments,
                    program="auction_etl.cli.main",
                )
        finally:
            manager_class.context = (
                original_context
            )

            browser = getattr(
                manager_module,
                "browser",
                None,
            )

            if browser is not None:
                try:
                    # The owner must retain its persistent browser across jobs.
                    pass
                except Exception:
                    pass

        return {
            "ok": True,
            "exit_code": exit_code,
            "output": output,
        }

    def handle(
        self,
        request: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Handle one versioned owner request."""

        protocol_version = request.get(
            "protocol_version"
        )

        if (
            protocol_version
            != OWNER_PROTOCOL_VERSION
        ):
            raise RuntimeError(
                "Unsupported Buyee owner protocol version: "
                f"{protocol_version!r}"
            )

        command = str(
            request.get(
                "command",
                "",
            )
        )

        payload = request.get(
            "payload",
            {},
        )

        if not isinstance(
            payload,
            dict,
        ):
            raise RuntimeError(
                "Owner request payload must be an object."
            )

        arguments = payload.get(
            "arguments",
            [],
        )
        environment = payload.get(
            "environment",
            {},
        )

        if not isinstance(
            arguments,
            list,
        ) or not all(
            isinstance(
                value,
                str,
            )
            for value in arguments
        ):
            raise RuntimeError(
                "Owner job arguments must be a list of strings."
            )

        if not isinstance(
            environment,
            dict,
        ) or not all(
            isinstance(
                key,
                str,
            )
            and isinstance(
                value,
                str,
            )
            for key, value in environment.items()
        ):
            raise RuntimeError(
                "Owner job environment must map strings to strings."
            )

        environment = {
            key: value
            for key, value in environment.items()
            if key == "DATABASE_URL"
            or key.startswith(
                "AUCTION_"
            )
        }
        environment.pop(
            "AUCTION_BUYEE_CDP_URL",
            None,
        )
        environment.pop(
            "AUCTION_BUYEE_OWNER_SOCKET",
            None,
        )

        if command == "health":
            return {
                "ok": True,
                "protocol_version": OWNER_PROTOCOL_VERSION,
                "pid": os.getpid(),
                "profile": str(
                    self._profile_dir
                ),
                "executable": str(
                    self._executable
                ),
                "headless": False,
                "cdp": False,
            }

        if command == "shutdown":
            self._stop_event.set()

            return {
                "ok": True,
                "exit_code": 0,
                "output": "",
            }

        if command == "verify_closed_watchlist":
            return self._run_repository_script(
                VERIFIER_PATH,
                arguments=arguments,
                environment=environment,
            )

        if command == "crawl_live_details":
            return self._run_repository_script(
                DETAIL_CRAWLER_PATH,
                arguments=arguments,
                environment=environment,
            )

        if command == "crawl_closed_watchlist":
            return self._run_closed_watchlist_cli(
                arguments=arguments,
                environment=environment,
            )

        raise RuntimeError(
            f"Unsupported Buyee owner command: {command}"
        )


class OwnerServer(
    socketserver.UnixStreamServer
):
    """Sequential Unix server so all Playwright calls stay on the owner thread."""

    allow_reuse_address = False

    def __init__(
        self,
        socket_path: Path,
        owner: BuyeeOwner,
    ) -> None:
        self.owner = owner
        super().__init__(
            str(
                socket_path
            ),
            OwnerRequestHandler,
        )


class OwnerRequestHandler(
    socketserver.StreamRequestHandler
):
    """Process one newline-delimited JSON owner request."""

    def handle(
        self,
    ) -> None:
        raw = self.rfile.readline(
            10 * 1024 * 1024
        )

        if not raw:
            return

        try:
            request = json.loads(
                raw.decode(
                    "utf-8"
                )
            )

            if not isinstance(
                request,
                dict,
            ):
                raise RuntimeError(
                    "Owner request must be a JSON object."
                )

            response = self.server.owner.handle(
                request
            )
        except Exception as error:
            response = {
                "ok": False,
                "error": (
                    f"{type(error).__name__}: {error}"
                ),
            }

        encoded = (
            json.dumps(
                response,
                ensure_ascii=False,
                separators=(",", ":"),
            )
            + "\n"
        ).encode(
            "utf-8"
        )

        self.wfile.write(
            encoded
        )
        self.wfile.flush()


def main() -> int:
    """Launch one persistent headed/offscreen Buyee owner."""

    arguments = parse_arguments()
    profile_dir = (
        arguments.profile_dir
        .expanduser()
        .resolve()
    )
    socket_path = (
        arguments.socket_path
        .expanduser()
        .resolve()
    )

    if not profile_dir.is_dir():
        raise RuntimeError(
            f"Buyee profile is missing: {profile_dir}"
        )

    socket_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

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

    signal.signal(
        signal.SIGTERM,
        request_stop,
    )
    signal.signal(
        signal.SIGINT,
        request_stop,
    )

    with sync_playwright() as playwright:
        executable = Path(
            playwright.chromium.executable_path
        ).resolve()

        context = (
            playwright.chromium.launch_persistent_context(
                user_data_dir=str(
                    profile_dir
                ),
                executable_path=str(
                    executable
                ),
                headless=False,
                locale="en-US",
                timezone_id="Asia/Tokyo",
                viewport={
                    "width": 1600,
                    "height": 1200,
                },
                args=[
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--disable-popup-blocking",
                    "--window-position=-32000,-32000",
                    "--window-size=1200,900",
                ],
            )
        )

        try:
            owner = BuyeeOwner(
                playwright=playwright,
                context=context,
                profile_dir=profile_dir,
                executable=executable,
                stop_event=stop_event,
            )

            with OwnerServer(
                socket_path,
                owner,
            ) as server:
                os.chmod(
                    socket_path,
                    0o600,
                )
                server.timeout = 0.5

                print(
                    "BUYEE_OWNER_READY=true",
                    flush=True,
                )
                print(
                    f"BUYEE_OWNER_PID={os.getpid()}",
                    flush=True,
                )
                print(
                    f"BUYEE_OWNER_PROFILE={profile_dir}",
                    flush=True,
                )
                print(
                    f"BUYEE_OWNER_SOCKET={socket_path}",
                    flush=True,
                )
                print(
                    f"BUYEE_OWNER_EXECUTABLE={executable}",
                    flush=True,
                )
                print(
                    "BUYEE_OWNER_HEADLESS=false",
                    flush=True,
                )
                print(
                    "BUYEE_OWNER_CDP=false",
                    flush=True,
                )

                while not stop_event.is_set():
                    server.handle_request()
        finally:
            context.close()

            try:
                socket_path.unlink(
                    missing_ok=True
                )
            except OSError:
                pass

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
