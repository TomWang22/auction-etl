#!/usr/bin/env bash
set -euo pipefail

BASE_REVISION="${BASE_REVISION:-be7b9855a5dc}"
ANALYTICS_REVISION="${ANALYTICS_REVISION:-c4f8a2d7e901}"
LIVE_PSQL_URL="${PSQL_URL:?PSQL_URL is required}"
BACKUP_DUMP="${1:?usage: test_collector_analytics_migration.sh BACKUP_DUMP}"

timestamp="$(date +%Y%m%d%H%M%S)"
temp_db="auction_analytics_test_${timestamp}"
temp_psql_url="postgresql://auction:auction@127.0.0.1:5544/${temp_db}"
temp_database_url="postgresql+psycopg://auction:auction@127.0.0.1:5544/${temp_db}"

cleanup() {
    psql \
        "${LIVE_PSQL_URL}" \
        --no-password \
        -v ON_ERROR_STOP=1 \
        -c "DROP DATABASE IF EXISTS \"${temp_db}\" WITH (FORCE);" \
        >/dev/null 2>&1 \
        || true
}

trap cleanup EXIT

can_create="$(
    psql \
        "${LIVE_PSQL_URL}" \
        --no-password \
        -Atc "
            SELECT rolsuper OR rolcreatedb
            FROM pg_roles
            WHERE rolname = current_user;
        "
)"

if [[ "${can_create}" != "t" ]]; then
    echo "ERROR: Current PostgreSQL role cannot create disposable databases."
    exit 1
fi

cleanup

psql \
    "${LIVE_PSQL_URL}" \
    --no-password \
    -v ON_ERROR_STOP=1 \
    -c "
        CREATE DATABASE \"${temp_db}\"
        OWNER auction
        TEMPLATE template0;
    "

pg_restore \
    --dbname="${temp_psql_url}" \
    --no-password \
    --no-owner \
    --no-privileges \
    "${BACKUP_DUMP}"

restored_rows="$(
    psql \
        "${temp_psql_url}" \
        --no-password \
        -Atc '
            SELECT COUNT(*)
            FROM warehouse.auction;
        '
)"

[[ "${restored_rows}" == "848" ]] || {
    echo "ERROR: Disposable restore has ${restored_rows} auctions."
    exit 1
}

restored_revision="$(
    DATABASE_URL="${temp_database_url}" \
        uv run alembic current 2>/dev/null |
    awk 'NF {print $1; exit}'
)"

[[ "${restored_revision}" == "${BASE_REVISION}" ]] || {
    echo "ERROR: Disposable database revision is ${restored_revision}."
    exit 1
}

DATABASE_URL="${temp_database_url}" \
    uv run alembic upgrade head

upgraded_revision="$(
    DATABASE_URL="${temp_database_url}" \
        uv run alembic current 2>/dev/null |
    awk 'NF {print $1; exit}'
)"

[[ "${upgraded_revision}" == "${ANALYTICS_REVISION}" ]] || {
    echo "ERROR: Disposable upgrade stopped at ${upgraded_revision}."
    exit 1
}

psql \
    "${temp_psql_url}" \
    --no-password \
    -v ON_ERROR_STOP=1 \
    -c "
        SELECT COUNT(*) AS auction_rows
        FROM analytics.auction_collector_base;
    " \
    -c "
        SELECT COUNT(*) AS component_types
        FROM system.component_type;
    " \
    -c "
        SELECT COUNT(*) AS condition_grades
        FROM system.condition_grade;
    "

psql \
    "${temp_psql_url}" \
    --no-password \
    -v ON_ERROR_STOP=1 <<'SQL'
WITH sample AS (
    SELECT
        marketplace,
        listing_id,
        COALESCE(NULLIF(artist, ''), 'Test Artist') AS artist,
        title,
        COALESCE(NULLIF(media_type, ''), 'OTHER') AS media_type
    FROM warehouse.auction
    ORDER BY id
    LIMIT 1
),
family AS (
    INSERT INTO warehouse.release_family (
        artist_key,
        title_key,
        display_artist,
        display_title
    )
    SELECT
        'migration-test-artist',
        'migration-test-title',
        artist,
        title
    FROM sample
    RETURNING id
),
pressing AS (
    INSERT INTO warehouse.pressing_identity (
        release_family_id,
        catalog_number,
        media_type,
        generation,
        is_first_press
    )
    SELECT
        family.id,
        'MIGRATION-TEST',
        sample.media_type,
        'FIRST_PRESS',
        true
    FROM family
    CROSS JOIN sample
    RETURNING id
),
assignment AS (
    INSERT INTO warehouse.auction_pressing_assignment (
        marketplace,
        listing_id,
        pressing_id,
        match_basis,
        match_confidence,
        is_manual_override
    )
    SELECT
        sample.marketplace,
        sample.listing_id,
        pressing.id,
        'MANUAL',
        1,
        true
    FROM sample
    CROSS JOIN pressing
    RETURNING marketplace, listing_id, pressing_id
)
INSERT INTO warehouse.pressing_component_expectation (
    pressing_id,
    component_code,
    expectation_state
)
SELECT pressing_id, 'OBI', 'REQUIRED'
FROM assignment
UNION ALL
SELECT pressing_id, 'INSERT', 'REQUIRED'
FROM assignment
UNION ALL
SELECT pressing_id, 'POSTER', 'REQUIRED'
FROM assignment;

WITH sample AS (
    SELECT marketplace, listing_id
    FROM warehouse.auction_pressing_assignment
    WHERE match_basis = 'MANUAL'
    ORDER BY id DESC
    LIMIT 1
)
INSERT INTO warehouse.auction_component_observation (
    marketplace,
    listing_id,
    component_code,
    observation_state
)
SELECT marketplace, listing_id, 'OBI', 'PRESENT'
FROM sample
UNION ALL
SELECT marketplace, listing_id, 'INSERT', 'NOT_VISIBLE'
FROM sample
UNION ALL
SELECT marketplace, listing_id, 'POSTER', 'ABSENT'
FROM sample;

DO $test$
DECLARE
    result record;
BEGIN
    SELECT *
    INTO result
    FROM warehouse.auction_completeness
    WHERE marketplace = (
        SELECT marketplace
        FROM warehouse.auction_pressing_assignment
        WHERE match_basis = 'MANUAL'
        ORDER BY id DESC
        LIMIT 1
    )
      AND listing_id = (
        SELECT listing_id
        FROM warehouse.auction_pressing_assignment
        WHERE match_basis = 'MANUAL'
        ORDER BY id DESC
        LIMIT 1
    );

    IF result.required_component_count <> 3 THEN
        RAISE EXCEPTION 'expected 3 required components';
    END IF;

    IF result.present_required_component_count <> 1 THEN
        RAISE EXCEPTION 'expected 1 present component';
    END IF;

    IF result.completeness_status <> 'INCOMPLETE' THEN
        RAISE EXCEPTION 'expected INCOMPLETE status';
    END IF;

    IF result.complete THEN
        RAISE EXCEPTION 'listing must not be complete';
    END IF;
END
$test$;

WITH sample AS (
    SELECT marketplace, listing_id
    FROM warehouse.auction
    WHERE marketplace = 'buyee'
    ORDER BY id
    LIMIT 1
)
INSERT INTO warehouse.auction_behavior_observation (
    marketplace,
    listing_id,
    distinct_bidder_count,
    distinct_bidder_state,
    distinct_bidder_source
)
SELECT
    marketplace,
    listing_id,
    NULL,
    'NOT_EXPOSED',
    'Yahoo/Buyee does not expose distinct bidders'
FROM sample;

SELECT
    COUNT(*) AS explicitly_not_exposed
FROM warehouse.auction_behavior_observation
WHERE distinct_bidder_state = 'NOT_EXPOSED'
  AND distinct_bidder_count IS NULL;
SQL

DATABASE_URL="${temp_database_url}" \
    uv run alembic downgrade -1

downgraded_revision="$(
    DATABASE_URL="${temp_database_url}" \
        uv run alembic current 2>/dev/null |
    awk 'NF {print $1; exit}'
)"

[[ "${downgraded_revision}" == "${BASE_REVISION}" ]] || {
    echo "ERROR: Disposable downgrade stopped at ${downgraded_revision}."
    exit 1
}

remaining_objects="$(
    psql \
        "${temp_psql_url}" \
        --no-password \
        -Atc "
            SELECT COUNT(*)
            FROM (
                VALUES
                    (to_regclass('warehouse.release_family')),
                    (to_regclass('warehouse.pressing_identity')),
                    (to_regclass('analytics.auction_collector_base'))
            ) AS objects(object_identity)
            WHERE object_identity IS NOT NULL;
        "
)"

[[ "${remaining_objects}" == "0" ]] || {
    echo "ERROR: Downgrade left ${remaining_objects} analytics objects."
    exit 1
}

post_downgrade_rows="$(
    psql \
        "${temp_psql_url}" \
        --no-password \
        -Atc '
            SELECT COUNT(*)
            FROM warehouse.auction;
        '
)"

[[ "${post_downgrade_rows}" == "848" ]] || {
    echo "ERROR: Downgrade changed auction rows."
    exit 1
}

DATABASE_URL="${temp_database_url}" \
    uv run alembic upgrade head

final_revision="$(
    DATABASE_URL="${temp_database_url}" \
        uv run alembic current 2>/dev/null |
    awk 'NF {print $1; exit}'
)"

[[ "${final_revision}" == "${ANALYTICS_REVISION}" ]] || {
    echo "ERROR: Re-upgrade stopped at ${final_revision}."
    exit 1
}

final_rows="$(
    psql \
        "${temp_psql_url}" \
        --no-password \
        -Atc '
            SELECT COUNT(*)
            FROM analytics.auction_collector_base;
        '
)"

[[ "${final_rows}" == "848" ]] || {
    echo "ERROR: Re-upgraded base view has ${final_rows} rows."
    exit 1
}

echo "✓ Disposable restore:          passed"
echo "✓ Upgrade:                     passed"
echo "✓ Completeness derivation:     passed"
echo "✓ NOT_EXPOSED bidder state:    passed"
echo "✓ Downgrade:                   passed"
echo "✓ Re-upgrade:                  passed"
echo "✓ Existing 848 auctions:       preserved"
