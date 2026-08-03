CREATE TABLE system.evidence_source_registry (
    source_key varchar(80) PRIMARY KEY,
    display_name varchar(160) NOT NULL,
    source_type varchar(60) NOT NULL DEFAULT 'OTHER',
    base_url text,
    default_confidence numeric(5, 4),
    active boolean NOT NULL DEFAULT true,
    notes text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT evidence_source_registry_key_format_check
        CHECK (
            source_key ~ '^[A-Z0-9][A-Z0-9_:-]*$'
        ),
    CONSTRAINT evidence_source_registry_confidence_check
        CHECK (
            default_confidence IS NULL
            OR (
                default_confidence >= 0
                AND default_confidence <= 1
            )
        )
);

CREATE INDEX evidence_source_registry_active_idx
    ON system.evidence_source_registry (
        active,
        display_name
    );

COMMENT ON TABLE system.evidence_source_registry IS
    'Reusable registry of reviewed evidence-source identifiers.';

COMMENT ON COLUMN system.evidence_source_registry.source_key IS
    'Stable identifier stored in evidence_source fields.';

COMMENT ON COLUMN system.evidence_source_registry.default_confidence IS
    'Optional UI default only; never overwrites reviewed row confidence.';

WITH existing_sources AS (
    SELECT evidence_source
    FROM warehouse.auction_component_observation

    UNION

    SELECT evidence_source
    FROM warehouse.pressing_component_expectation
),
normalized_sources AS (
    SELECT
        UPPER(
            REGEXP_REPLACE(
                BTRIM(evidence_source),
                '[^A-Za-z0-9]+',
                '_',
                'g'
            )
        ) AS source_key,
        MIN(BTRIM(evidence_source)) AS display_name
    FROM existing_sources
    WHERE NULLIF(
        BTRIM(evidence_source),
        ''
    ) IS NOT NULL
    GROUP BY
        UPPER(
            REGEXP_REPLACE(
                BTRIM(evidence_source),
                '[^A-Za-z0-9]+',
                '_',
                'g'
            )
        )
)
INSERT INTO system.evidence_source_registry (
    source_key,
    display_name,
    source_type,
    active,
    notes
)
SELECT
    source_key,
    display_name,
    'EXISTING_DATA',
    true,
    'Bootstrapped from evidence_source values already stored before this migration.'
FROM normalized_sources
WHERE source_key <> ''
ON CONFLICT (source_key) DO NOTHING;
