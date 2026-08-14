#!/usr/bin/env bash

set -Eeuo pipefail

cd /app

DATABASE_URL="${DATABASE_URL:-postgresql://auction:auction@db:5432/auction_warehouse}"
GRIPSWEAT_CONFIG="${GRIPSWEAT_CONFIG:-config/gripsweat_sources.json}"

TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
RUN_DIR="logs/source-refresh/container-${TIMESTAMP}"
RUN_LOG="${RUN_DIR}/refresh.log"

mkdir -p \
    "$RUN_DIR" \
    logs/buyee \
    logs/ebay \
    logs/gripsweat/probe \
    logs/gripsweat/pagination-audit \
    logs/gripsweat/detail

touch "$RUN_LOG"

run_logged() {
    printf '\nCommand:'
    printf ' %q' "$@"
    printf '\n\n'

    "$@" 2>&1 | tee -a "$RUN_LOG"

    local command_status="${PIPESTATUS[0]}"

    if [[ "$command_status" -ne 0 ]]; then
        echo
        echo "ERROR: Command failed with status ${command_status}"
        echo "Run log: ${RUN_LOG}"
        exit "$command_status"
    fi
}

option_supported() {
    local help_text="$1"
    local option="$2"

    printf '%s\n' "$help_text" |
        grep -q -- "$option"
}

run_script_adaptively() {
    local script_path="$1"
    local marketplace="$2"
    local apply_mode="$3"
    local limit="${4:-}"
    local help_text
    local arguments

    [[ -f "$script_path" ]] || return 2

    help_text="$(
        python "$script_path" --help 2>&1 || true
    )"

    arguments=(
        python
        "$script_path"
    )

    if [[ "$apply_mode" == "apply" ]] \
        && option_supported "$help_text" "--apply"
    then
        arguments+=("--apply")
    fi

    if option_supported "$help_text" "--refresh"; then
        arguments+=("--refresh")
    fi

    if [[ -n "$limit" ]] \
        && option_supported "$help_text" "--limit"
    then
        arguments+=("--limit" "$limit")
    fi

    if option_supported "$help_text" "--delay"; then
        arguments+=("--delay" "2")
    fi

    if option_supported "$help_text" "--timeout"; then
        arguments+=("--timeout" "45")
    fi

    if option_supported "$help_text" "--wait-seconds"; then
        arguments+=("--wait-seconds" "6")
    fi

    if option_supported "$help_text" "--log-dir"; then
        arguments+=(
            "--log-dir"
            "logs/${marketplace}/live-${TIMESTAMP}/${apply_mode}"
        )
    fi

    run_logged "${arguments[@]}"
}

run_marketplace_cli() {
    local marketplace="$1"
    local subcommand
    local help_text
    local arguments

    for subcommand in run source marketplace start; do
        help_text="$(
            python -m auction_etl.cli.main \
                crawl \
                "$subcommand" \
                --help \
                2>&1 ||
                true
        )"

        if printf '%s\n' "$help_text" |
            grep -qiE 'No such command|UsageError|Invalid value'
        then
            continue
        fi

        if ! printf '%s\n' "$help_text" |
            grep -q 'Usage:'
        then
            continue
        fi

        arguments=(
            python
            -m
            auction_etl.cli.main
            crawl
            "$subcommand"
        )

        if option_supported "$help_text" "--marketplace"; then
            arguments+=("--marketplace" "$marketplace")
        elif option_supported "$help_text" "--source"; then
            arguments+=("--source" "$marketplace")
        elif printf '%s\n' "$help_text" |
            grep -qE '\b(MARKETPLACE|SOURCE)\b'
        then
            arguments+=("$marketplace")
        else
            continue
        fi

        if option_supported "$help_text" "--refresh"; then
            arguments+=("--refresh")
        fi

        if option_supported "$help_text" "--apply"; then
            arguments+=("--apply")
        fi

        run_logged "${arguments[@]}"
        return 0
    done

    return 1
}

run_optional_pipeline_command() {
    local group="$1"
    local subcommand="$2"
    local help_text

    help_text="$(
        python -m auction_etl.cli.main \
            "$group" \
            "$subcommand" \
            --help \
            2>&1 ||
            true
    )"

    if ! printf '%s\n' "$help_text" |
        grep -q 'Usage:'
    then
        return 0
    fi

    if printf '%s\n' "$help_text" |
        grep -qiE 'No such command|UsageError'
    then
        return 0
    fi

    run_logged \
        python -m auction_etl.cli.main \
        "$group" \
        "$subcommand"
}

echo
echo "Auction ETL in-container all-source refresh"
echo "==========================================="
echo "Database: ${DATABASE_URL}"
echo "Log     : ${RUN_LOG}"

echo
echo "1. Verify Chromium"
echo "=================="

run_logged \
    python - <<'PY'
from playwright.sync_api import sync_playwright

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    page = browser.new_page()
    page.goto("about:blank")
    print("Chromium:", browser.browser_type.name)
    print("Page:", page.url)
    browser.close()
PY

echo
echo "2. Verify database identity and baseline"
echo "========================================"

run_logged \
    psql \
    "$DATABASE_URL" \
    -v ON_ERROR_STOP=1 \
    -c "
        SELECT
            current_database() AS database_name,
            current_user AS database_user;

        SELECT
            marketplace,
            COUNT(*) AS rows,
            COUNT(DISTINCT listing_id) AS unique_rows
        FROM warehouse.auction
        GROUP BY marketplace
        ORDER BY marketplace;
    "

echo
echo "3. Compile refresh tools"
echo "========================"

compile_paths=(
    scripts/normalize_gripsweat_source_schema.py
    scripts/probe_gripsweat.py
    scripts/setup_gripsweat_schema.py
    scripts/import_gripsweat_probe.py
    scripts/audit_gripsweat_pagination.py
    scripts/import_gripsweat_pagination_audit.py
    scripts/enrich_gripsweat_details.py
)

for optional_path in \
    scripts/crawl_buyee_live_details.py \
    scripts/crawl_ebay_live_details.py \
    scripts/enrich_ebay_details.py \
    scripts/collector_features.py \
    scripts/reclassify_collector.py \
    scripts/update_auction_fx.py
do
    if [[ -f "$optional_path" ]]; then
        compile_paths+=("$optional_path")
    fi
done

run_logged \
    python -m py_compile \
    "${compile_paths[@]}"

echo
echo "4. Refresh Buyee search results"
echo "================================"

if run_marketplace_cli buyee; then
    echo "✓ Buyee marketplace crawl completed."
else
    echo "WARNING: No compatible generic Buyee crawl command was detected."
    echo "The known Buyee live-detail crawler will still run."
fi

echo
echo "5. Test and apply Buyee live details"
echo "===================================="

if [[ -f scripts/crawl_buyee_live_details.py ]]; then
    run_script_adaptively \
        scripts/crawl_buyee_live_details.py \
        buyee \
        dry-run \
        5

    run_script_adaptively \
        scripts/crawl_buyee_live_details.py \
        buyee \
        apply
else
    echo "WARNING: scripts/crawl_buyee_live_details.py is missing."
fi

echo
echo "6. Refresh eBay search results"
echo "=============================="

if ! run_marketplace_cli ebay; then
    echo
    echo "ERROR: No compatible eBay marketplace crawl command was detected."
    echo
    echo "Detected eBay-related files:"
    find \
        auction_etl \
        scripts \
        -maxdepth 4 \
        -type f \
        -iname '*ebay*' \
        -print \
        2>/dev/null ||
        true

    exit 1
fi

echo "✓ eBay marketplace crawl completed."

echo
echo "7. Test and apply eBay detail refresh"
echo "====================================="

if [[ -f scripts/crawl_ebay_live_details.py ]]; then
    run_script_adaptively \
        scripts/crawl_ebay_live_details.py \
        ebay \
        dry-run \
        5

    run_script_adaptively \
        scripts/crawl_ebay_live_details.py \
        ebay \
        apply
elif [[ -f scripts/enrich_ebay_details.py ]]; then
    run_script_adaptively \
        scripts/enrich_ebay_details.py \
        ebay \
        dry-run \
        5

    run_script_adaptively \
        scripts/enrich_ebay_details.py \
        ebay \
        apply
else
    echo "No separate eBay detail script exists."
    echo "The repository marketplace crawl was applied."
fi

echo
echo "8. Run available ETL synchronization commands"
echo "============================================="

run_optional_pipeline_command parse run
run_optional_pipeline_command normalize run
run_optional_pipeline_command sync run

echo
echo "9. Prepare the Gripsweat schema"
echo "==============================="

run_logged \
    python scripts/setup_gripsweat_schema.py

run_logged \
    env GRIPSWEAT_CONFIG="$GRIPSWEAT_CONFIG" \
    python scripts/normalize_gripsweat_source_schema.py

echo
echo "10. Run the Gripsweat page-one probe"
echo "===================================="

PROBE_OUTPUT="logs/gripsweat/probe/gripsweat_probe_${TIMESTAMP}.json"

run_logged \
    python scripts/probe_gripsweat.py \
    --config "$GRIPSWEAT_CONFIG" \
    --max-pages 1 \
    --wait-seconds 8 \
    --output "$PROBE_OUTPUT" \
    --diagnostic-dir logs/gripsweat

[[ -s "$PROBE_OUTPUT" ]] || {
    echo "ERROR: Gripsweat probe output is missing: ${PROBE_OUTPUT}"
    exit 1
}

run_logged \
    python scripts/import_gripsweat_probe.py \
    --config "$GRIPSWEAT_CONFIG" \
    --probe "$PROBE_OUTPUT"

echo
echo "11. Refresh Gripsweat pagination"
echo "================================"

run_logged \
    python scripts/audit_gripsweat_pagination.py \
    --pages 10 \
    --wait-seconds 6 \
    --delay 2 \
    --empty-page-limit 2

PAGINATION_INPUT="logs/gripsweat/pagination-audit/gripsweat_pagination_audit.json"

[[ -s "$PAGINATION_INPUT" ]] || {
    echo "ERROR: Gripsweat pagination audit is missing."
    exit 1
}

run_logged \
    python scripts/import_gripsweat_pagination_audit.py \
    --input "$PAGINATION_INPUT" \
    --dry-run

run_logged \
    python scripts/import_gripsweat_pagination_audit.py \
    --input "$PAGINATION_INPUT"

echo
echo "12. Test and apply Gripsweat detail enrichment"
echo "=============================================="

detail_help="$(
    python scripts/enrich_gripsweat_details.py \
        --help \
        2>&1 ||
        true
)"

detail_common=(
    --wait-seconds
    6
    --delay
    2
)

if option_supported "$detail_help" "--refresh"; then
    detail_common+=("--refresh")
fi

run_logged \
    python scripts/enrich_gripsweat_details.py \
    "${detail_common[@]}" \
    --limit 10

run_logged \
    python scripts/enrich_gripsweat_details.py \
    "${detail_common[@]}" \
    --apply

echo
echo "13. Rebuild collector-derived values"
echo "===================================="

if [[ -f scripts/collector_features.py ]]; then
    run_logged \
        python scripts/collector_features.py
fi

if [[ -f scripts/reclassify_collector.py ]]; then
    reclassify_help="$(
        python scripts/reclassify_collector.py \
            --help \
            2>&1 ||
            true
    )"

    if option_supported "$reclassify_help" "--apply"; then
        run_logged \
            python scripts/reclassify_collector.py \
            --apply
    else
        run_logged \
            python scripts/reclassify_collector.py
    fi
fi

if [[ -f scripts/update_auction_fx.py ]]; then
    run_logged \
        python scripts/update_auction_fx.py
fi

echo
echo "14. Verify all refreshed data"
echo "============================="

run_logged \
    psql \
    "$DATABASE_URL" \
    -v ON_ERROR_STOP=1 <<'SQL'
SELECT
    marketplace,
    COUNT(*) AS rows,
    COUNT(DISTINCT listing_id) AS unique_listings,
    COUNT(final_price) AS final_prices,
    COUNT(gross_price) AS gross_prices,
    COUNT(ended_at) AS ended_dates
FROM warehouse.auction
GROUP BY marketplace
ORDER BY marketplace;

SELECT
    COUNT(*) AS duplicate_groups
FROM (
    SELECT
        marketplace,
        listing_id
    FROM warehouse.auction
    GROUP BY marketplace, listing_id
    HAVING COUNT(*) > 1
) AS duplicates;

SELECT
    COUNT(*) AS gripsweat_sources
FROM warehouse.gripsweat_source;

SELECT
    COUNT(*) AS gripsweat_sales
FROM warehouse.gripsweat_sale;

SELECT
    source_name,
    configured_artist,
    search_query,
    sort_by,
    enabled
FROM warehouse.gripsweat_source
ORDER BY source_name;
SQL

duplicate_groups="$(
    psql \
        "$DATABASE_URL" \
        -v ON_ERROR_STOP=1 \
        -Atc "
            SELECT COUNT(*)
            FROM (
                SELECT
                    marketplace,
                    listing_id
                FROM warehouse.auction
                GROUP BY marketplace, listing_id
                HAVING COUNT(*) > 1
            ) AS duplicates;
        "
)"

[[ "$duplicate_groups" == "0" ]] || {
    echo "ERROR: Duplicate auction keys were created."
    exit 1
}

run_logged \
    python -m auction_etl.cli.main doctor run

echo
echo "All in-container refreshes completed"
echo "===================================="
echo "✓ Buyee refresh completed."
echo "✓ eBay refresh completed."
echo "✓ Gripsweat refresh completed."
echo "✓ Collector-derived values were rebuilt."
echo "✓ Duplicate auction groups: 0"
echo "Run log: ${RUN_LOG}"
