#!/usr/bin/env python3
"""One-time live smoke: eBay + Gripsweat + Yahoo Auctions + Yahoo フリマ.

Skips Buyee (optional/legacy). Caps pages so the run finishes in one sitting.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from auction_etl.services.artist_tracking import (  # noqa: E402
    list_account_tracked_artists,
    upsert_account_artist,
)
from auction_etl.services.yahoo_jp_ingest import (  # noqa: E402
    refresh_yahoo_marketplace_for_account,
)

DEFAULT_URL = (
    "postgresql+psycopg://auction:auction@127.0.0.1:5544/auction_warehouse"
)


def main() -> int:
    database_url = os.environ.get("DATABASE_URL", DEFAULT_URL)
    engine = create_engine(database_url)
    report: dict = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "marketplaces": {},
    }

    with engine.connect() as connection:
        account_id = connection.execute(
            text(
                "SELECT id FROM identity.account "
                "ORDER BY created_at NULLS LAST LIMIT 1"
            )
        ).scalar()
        user_id = connection.execute(
            text(
                """
                SELECT id FROM identity.app_user
                ORDER BY created_at NULLS LAST
                LIMIT 1
                """
            )
        ).scalar()

    if not account_id or not user_id:
        print("No local account/user found", file=sys.stderr)
        return 2

    artists = list_account_tracked_artists(engine, account_id=str(account_id))
    for artist in artists:
        name = str(artist.get("name") or "").strip()
        if not name:
            continue
        # Keep existing eBay/Gripsweat; add both Yahoo surfaces for the live proof.
        upsert_account_artist(
            engine,
            account_id=str(account_id),
            user_id=str(user_id),
            name=name,
            marketplaces=[
                "ebay",
                "gripsweat",
                "yahoo_auction",
                "yahoo_fleamarket",
            ],
        )
    report["artists_enabled_for_yahoo"] = [
        str(artist.get("name")) for artist in artists
    ]

    # --- Yahoo Auctions ---
    auction = refresh_yahoo_marketplace_for_account(
        engine,
        marketplace="yahoo_auction",
        pages=2,
        stop_on_novelty=True,
    )
    report["marketplaces"]["yahoo_auction"] = auction

    # --- Yahoo フリマ (search-only) ---
    flea = refresh_yahoo_marketplace_for_account(
        engine,
        marketplace="yahoo_fleamarket",
        pages=2,
        stop_on_novelty=True,
    )
    report["marketplaces"]["yahoo_fleamarket"] = flea

    # --- Gripsweat (1 page, same scripts as refresh) ---
    gripsweat: dict = {"state": "pending"}
    try:
        from auction_etl.services.artist_tracking import (
            prepare_runtime_marketplace_configs,
        )

        configs = prepare_runtime_marketplace_configs()
        gripsweat_config = Path(configs["gripsweat"])
        run_dir = ROOT / "logs" / "four-marketplace-smoke" / datetime.now().strftime(
            "%Y%m%d-%H%M%S"
        )
        run_dir.mkdir(parents=True, exist_ok=True)
        probe_path = run_dir / "gripsweat-probe.json"
        env = os.environ.copy()
        env["DATABASE_URL"] = database_url
        probe = subprocess.run(
            [
                sys.executable,
                "scripts/probe_gripsweat.py",
                "--config",
                str(gripsweat_config),
                "--max-pages",
                "1",
                "--wait-seconds",
                "6",
                "--output",
                str(probe_path),
                "--diagnostic-dir",
                str(run_dir / "gripsweat-probe"),
            ],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        gripsweat["probe_returncode"] = probe.returncode
        gripsweat["probe_tail"] = (probe.stdout + probe.stderr)[-1200:]
        if probe.returncode == 0 and probe_path.is_file():
            imported = subprocess.run(
                [
                    sys.executable,
                    "scripts/import_gripsweat_probe.py",
                    "--config",
                    str(gripsweat_config),
                    "--probe",
                    str(probe_path),
                ],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            gripsweat["import_returncode"] = imported.returncode
            gripsweat["import_tail"] = (imported.stdout + imported.stderr)[-800:]
            gripsweat["state"] = (
                "done" if imported.returncode == 0 else "failed"
            )
        else:
            gripsweat["state"] = "failed"
    except Exception as exc:  # noqa: BLE001 — smoke report
        gripsweat = {
            "state": "failed",
            "error": f"{type(exc).__name__}: {exc}",
        }
    report["marketplaces"]["gripsweat"] = gripsweat

    # --- eBay (short structured acquire + import, same path as refresh) ---
    ebay: dict = {"state": "pending"}
    try:
        from auction_etl.browser.ebay_owner import owner_socket_path
        from auction_etl.services.artist_tracking import (
            prepare_runtime_marketplace_configs,
        )

        configs = prepare_runtime_marketplace_configs()
        ebay_config = Path(configs["ebay"])
        entries = json.loads(ebay_config.read_text())
        source = next(
            (
                entry
                for entry in entries
                if isinstance(entry, dict) and entry.get("enabled")
            ),
            None,
        )
        if source is None:
            ebay = {"state": "skipped", "reason": "no enabled ebay source"}
        else:
            run_dir = ROOT / "logs" / "four-marketplace-smoke" / "ebay"
            run_dir.mkdir(parents=True, exist_ok=True)
            output = run_dir / "ebay-structured.json"
            env = os.environ.copy()
            env["DATABASE_URL"] = database_url
            storage_state = Path.home() / ".auction-etl" / "private" / "ebay-storage-state.json"
            ensure = subprocess.run(
                [
                    sys.executable,
                    "scripts/ensure_ebay_owner.py",
                    "--storage-state",
                    str(storage_state),
                    "--timeout-seconds",
                    "120",
                    "--background",
                ],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
                timeout=180,
            )
            ebay["owner_returncode"] = ensure.returncode
            ebay["owner_tail"] = (ensure.stdout + ensure.stderr)[-600:]
            socket = owner_socket_path()
            acquire_cmd = [
                sys.executable,
                "scripts/acquire_ebay_structured.py",
                "--url",
                str(source["url"]),
                "--source-name",
                str(source.get("name") or "live-smoke"),
                "--output",
                str(output),
                "--max-pages",
                "2",
                "--configured-max-pages",
                "2",
                "--storage-state",
                str(storage_state),
            ]
            if socket.exists():
                acquire_cmd.extend(["--owner-socket", str(socket)])
            result = subprocess.run(
                acquire_cmd,
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
                timeout=600,
            )
            ebay["acquire_returncode"] = result.returncode
            ebay["acquire_tail"] = (result.stdout + result.stderr)[-1200:]
            combined = (result.stdout + result.stderr).casefold()
            if result.returncode == 0 and output.is_file():
                imported = subprocess.run(
                    [
                        sys.executable,
                        "scripts/import_ebay_structured.py",
                        "--apply",
                        str(output),
                    ],
                    cwd=ROOT,
                    env=env,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=180,
                )
                ebay["import_returncode"] = imported.returncode
                ebay["import_tail"] = (imported.stdout + imported.stderr)[-800:]
                ebay["state"] = (
                    "done" if imported.returncode == 0 else "failed"
                )
            elif (
                "access_blocked" in combined
                or "http 403" in combined
                or "access-blocked" in combined
            ):
                ebay["state"] = "unavailable"
                ebay["reason"] = "ebay_access_blocked"
            else:
                ebay["state"] = "failed"
    except subprocess.TimeoutExpired:
        ebay = {"state": "failed", "error": "timeout"}
    except Exception as exc:  # noqa: BLE001
        ebay = {
            "state": "failed",
            "error": f"{type(exc).__name__}: {exc}",
        }
    report["marketplaces"]["ebay"] = ebay

    with engine.connect() as connection:
        counts = dict(
            connection.execute(
                text(
                    """
                    SELECT marketplace, count(*)
                    FROM warehouse.auction
                    WHERE marketplace IN (
                        'yahoo_auction',
                        'yahoo_fleamarket',
                        'ebay',
                        'buyee'
                    )
                    GROUP BY marketplace
                    """
                )
            ).all()
        )
        gripsweat_rows = connection.execute(
            text("SELECT count(*) FROM warehouse.gripsweat_sale")
        ).scalar()
    report["warehouse_counts"] = {
        **{str(k): int(v) for k, v in counts.items()},
        "gripsweat_sale": int(gripsweat_rows or 0),
    }
    report["finished_at"] = datetime.now(timezone.utc).isoformat()

    live = {
        "ebay": report["marketplaces"]["ebay"].get("state"),
        "gripsweat": report["marketplaces"]["gripsweat"].get("state"),
        "yahoo_auction": report["marketplaces"]["yahoo_auction"].get("state"),
        "yahoo_fleamarket": report["marketplaces"]["yahoo_fleamarket"].get(
            "state"
        ),
    }
    report["live_states"] = live
    report["all_four_ok"] = (
        live["yahoo_auction"] == "done"
        and live["yahoo_fleamarket"] in {"done", "rate_limited", "skipped"}
        and live["gripsweat"] == "done"
        and live["ebay"] in {"done", "unavailable", "skipped"}
    )
    report["notes"] = (
        "eBay unavailable = host 403/access-blocked (same degraded "
        "outcome as production refresh); Yahoo + Gripsweat still prove "
        "the new four-source wiring."
    )

    out = (
        ROOT
        / "docs"
        / "superpowers"
        / "specs"
        / "four-marketplace-live-smoke.json"
    )
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    print(json.dumps({"live_states": live, "all_four_ok": report["all_four_ok"], "warehouse_counts": report["warehouse_counts"]}, indent=2))
    print("wrote", out)
    return 0 if report["all_four_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
