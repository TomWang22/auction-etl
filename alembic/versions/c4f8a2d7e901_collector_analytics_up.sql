CREATE SCHEMA IF NOT EXISTS analytics;

CREATE TABLE system.component_type (
    code varchar(50) PRIMARY KEY,
    display_name varchar(100) NOT NULL,
    description text,
    applicable_media text[] NOT NULL DEFAULT ARRAY[]::text[],
    sort_order integer NOT NULL DEFAULT 100,
    active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now()
);

INSERT INTO system.component_type (
    code,
    display_name,
    description,
    applicable_media,
    sort_order
)
VALUES
    (
        'OBI',
        'Obi',
        'Issue-specific paper sash, including alternate-color variants.',
        ARRAY['LP', 'EP_7_INCH', 'SINGLE_12_INCH', 'CD', 'CD_BOX_SET'],
        10
    ),
    (
        'INSERT',
        'Insert',
        'General printed insert supplied with the pressing.',
        ARRAY['LP', 'EP_7_INCH', 'CD', 'CASSETTE', 'LD'],
        20
    ),
    (
        'LYRIC_SHEET',
        'Lyric sheet',
        'Separate lyric sheet.',
        ARRAY['LP', 'EP_7_INCH', 'CD', 'CASSETTE'],
        30
    ),
    (
        'POSTER',
        'Poster',
        'Folded or separate poster.',
        ARRAY['LP', 'CD_BOX_SET', 'LD'],
        40
    ),
    (
        'PINUP',
        'Pin-up',
        'Portrait or pin-up insert.',
        ARRAY['LP', 'EP_7_INCH'],
        50
    ),
    (
        'BOOKLET',
        'Booklet',
        'Bound or stapled booklet.',
        ARRAY['CD', 'CD_BOX_SET', 'CASSETTE', 'LD', 'DVD'],
        60
    ),
    (
        'J_CARD',
        'J-card',
        'Original cassette case insert.',
        ARRAY['CASSETTE'],
        70
    ),
    (
        'INNER_SLEEVE',
        'Inner sleeve',
        'Original company or printed inner sleeve.',
        ARRAY['LP', 'EP_7_INCH', 'SINGLE_12_INCH'],
        80
    ),
    (
        'BOX',
        'Box',
        'Original outer box or slipcase.',
        ARRAY['CD_BOX_SET', 'LP', 'CASSETTE', 'LD'],
        90
    ),
    (
        'STICKER',
        'Sticker',
        'Original hype, issue, promotional, or price sticker.',
        ARRAY['LP', 'CD', 'CASSETTE', 'LD'],
        100
    ),
    (
        'SHRINK_WRAP',
        'Shrink wrap',
        'Original shrink wrap or factory seal.',
        ARRAY['LP', 'CD', 'CASSETTE', 'LD', 'DVD'],
        110
    ),
    (
        'BONUS_MEDIA',
        'Bonus media',
        'Expected bonus disc, record, CD, DVD, or cassette.',
        ARRAY['LP', 'CD', 'CD_BOX_SET', 'DVD'],
        120
    ),
    (
        'OTHER',
        'Other component',
        'Collector-defined component.',
        ARRAY[]::text[],
        999
    );

CREATE TABLE system.condition_grade (
    code varchar(20) PRIMARY KEY,
    display_name varchar(50) NOT NULL,
    sort_rank smallint NOT NULL,
    score_20 numeric(5, 2),
    market_value_factor numeric(8, 4),
    description text,
    CONSTRAINT condition_grade_score_range
        CHECK (
            score_20 IS NULL
            OR score_20 BETWEEN 0 AND 20
        ),
    CONSTRAINT condition_grade_factor_positive
        CHECK (
            market_value_factor IS NULL
            OR market_value_factor > 0
        )
);

INSERT INTO system.condition_grade (
    code,
    display_name,
    sort_rank,
    score_20,
    market_value_factor,
    description
)
VALUES
    ('M', 'Mint', 1, 20, 1.0500, 'Mint'),
    ('NM', 'Near Mint', 2, 19, 1.0000, 'Near Mint'),
    ('EX', 'Excellent', 3, 17, 0.9000, 'Excellent'),
    ('E', 'E', 4, 16, 0.8500, 'Collector E grade'),
    ('E-', 'E minus', 5, 14, 0.7500, 'Collector E minus grade'),
    ('VG+', 'Very Good Plus', 6, 13, 0.7000, 'Very Good Plus'),
    ('VG', 'Very Good', 7, 11, 0.6000, 'Very Good'),
    ('G+', 'Good Plus', 8, 8, 0.4500, 'Good Plus'),
    ('G', 'Good', 9, 6, 0.3500, 'Good'),
    ('F', 'Fair', 10, 3, 0.2000, 'Fair'),
    ('P', 'Poor', 11, 1, 0.1000, 'Poor'),
    ('UNKNOWN', 'Unknown', 99, NULL, NULL, 'Unknown or unverified');

CREATE TABLE warehouse.release_family (
    id bigserial PRIMARY KEY,
    artist_key text NOT NULL,
    title_key text NOT NULL,
    display_artist text NOT NULL,
    display_title text NOT NULL,
    original_release_year smallint,
    notes text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT release_family_artist_key_not_blank
        CHECK (btrim(artist_key) <> ''),
    CONSTRAINT release_family_title_key_not_blank
        CHECK (btrim(title_key) <> ''),
    CONSTRAINT release_family_year_range
        CHECK (
            original_release_year IS NULL
            OR original_release_year BETWEEN 1800 AND 2200
        ),
    CONSTRAINT release_family_identity_unique
        UNIQUE (artist_key, title_key)
);

CREATE TABLE warehouse.pressing_identity (
    id bigserial PRIMARY KEY,
    release_family_id bigint NOT NULL
        REFERENCES warehouse.release_family(id)
        ON DELETE RESTRICT,
    catalog_number text NOT NULL DEFAULT '',
    matrix_number text NOT NULL DEFAULT '',
    label_name text NOT NULL DEFAULT '',
    region text NOT NULL DEFAULT '',
    country text NOT NULL DEFAULT '',
    media_type text NOT NULL,
    format_detail text NOT NULL DEFAULT '',
    disc_count smallint,
    release_year smallint,
    generation text NOT NULL DEFAULT 'UNKNOWN',
    pressing_variant_key text NOT NULL DEFAULT '',
    pressing_variant_label text,
    is_first_press boolean NOT NULL DEFAULT false,
    is_modern_repress boolean NOT NULL DEFAULT false,
    parent_first_press_id bigint
        REFERENCES warehouse.pressing_identity(id)
        ON DELETE SET NULL,
    notes text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pressing_identity_generation_valid
        CHECK (
            generation IN (
                'FIRST_PRESS',
                'EARLY_PRESS',
                'STANDARD',
                'PROMO',
                'REISSUE',
                'MODERN_REPRESS',
                'UNKNOWN'
            )
        ),
    CONSTRAINT pressing_identity_media_not_blank
        CHECK (btrim(media_type) <> ''),
    CONSTRAINT pressing_identity_disc_count_positive
        CHECK (disc_count IS NULL OR disc_count > 0),
    CONSTRAINT pressing_identity_year_range
        CHECK (
            release_year IS NULL
            OR release_year BETWEEN 1800 AND 2200
        ),
    CONSTRAINT pressing_identity_generation_consistency
        CHECK (
            NOT is_first_press
            OR generation = 'FIRST_PRESS'
        ),
    CONSTRAINT pressing_identity_modern_consistency
        CHECK (
            NOT is_modern_repress
            OR generation IN (
                'REISSUE',
                'MODERN_REPRESS'
            )
        ),
    CONSTRAINT pressing_identity_natural_unique
        UNIQUE (
            release_family_id,
            catalog_number,
            matrix_number,
            region,
            media_type,
            pressing_variant_key
        )
);

CREATE INDEX pressing_identity_release_family_idx
    ON warehouse.pressing_identity (
        release_family_id
    );

CREATE INDEX pressing_identity_catalog_idx
    ON warehouse.pressing_identity (
        catalog_number
    )
    WHERE catalog_number <> '';

CREATE TABLE warehouse.auction_pressing_assignment (
    id bigserial PRIMARY KEY,
    marketplace varchar(40) NOT NULL,
    listing_id varchar(255) NOT NULL,
    pressing_id bigint NOT NULL
        REFERENCES warehouse.pressing_identity(id)
        ON DELETE RESTRICT,
    match_basis text NOT NULL DEFAULT 'UNKNOWN',
    match_confidence numeric(5, 4),
    is_manual_override boolean NOT NULL DEFAULT false,
    notes text,
    assigned_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT auction_pressing_match_basis_valid
        CHECK (
            match_basis IN (
                'MANUAL',
                'CATALOG_EXACT',
                'MATRIX_EXACT',
                'TITLE_RULE',
                'MODEL',
                'IMPORT',
                'UNKNOWN'
            )
        ),
    CONSTRAINT auction_pressing_confidence_range
        CHECK (
            match_confidence IS NULL
            OR match_confidence BETWEEN 0 AND 1
        ),
    CONSTRAINT auction_pressing_listing_unique
        UNIQUE (marketplace, listing_id)
);

CREATE INDEX auction_pressing_pressing_idx
    ON warehouse.auction_pressing_assignment (
        pressing_id
    );

CREATE TABLE warehouse.pressing_component_expectation (
    id bigserial PRIMARY KEY,
    pressing_id bigint NOT NULL
        REFERENCES warehouse.pressing_identity(id)
        ON DELETE CASCADE,
    component_code varchar(50) NOT NULL
        REFERENCES system.component_type(code)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,
    variant_key text NOT NULL DEFAULT '',
    variant_label text,
    expectation_state text NOT NULL DEFAULT 'UNKNOWN',
    expected_quantity smallint NOT NULL DEFAULT 1,
    evidence_source text,
    confidence numeric(5, 4),
    notes text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pressing_component_expectation_valid
        CHECK (
            expectation_state IN (
                'REQUIRED',
                'OPTIONAL',
                'NOT_INCLUDED',
                'UNKNOWN'
            )
        ),
    CONSTRAINT pressing_component_quantity_positive
        CHECK (expected_quantity > 0),
    CONSTRAINT pressing_component_confidence_range
        CHECK (
            confidence IS NULL
            OR confidence BETWEEN 0 AND 1
        ),
    CONSTRAINT pressing_component_unique
        UNIQUE (
            pressing_id,
            component_code,
            variant_key
        )
);

CREATE TABLE warehouse.auction_component_observation (
    id bigserial PRIMARY KEY,
    marketplace varchar(40) NOT NULL,
    listing_id varchar(255) NOT NULL,
    component_code varchar(50) NOT NULL
        REFERENCES system.component_type(code)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,
    variant_key text NOT NULL DEFAULT '',
    variant_label text,
    observation_state text NOT NULL DEFAULT 'UNKNOWN',
    observed_quantity smallint,
    normalized_condition varchar(20)
        REFERENCES system.condition_grade(code),
    source_condition_text text,
    evidence_source text,
    confidence numeric(5, 4),
    evidence_url text,
    notes text,
    observed_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT auction_component_observation_valid
        CHECK (
            observation_state IN (
                'PRESENT',
                'ABSENT',
                'UNKNOWN',
                'NOT_VISIBLE',
                'NOT_APPLICABLE'
            )
        ),
    CONSTRAINT auction_component_quantity_nonnegative
        CHECK (
            observed_quantity IS NULL
            OR observed_quantity >= 0
        ),
    CONSTRAINT auction_component_confidence_range
        CHECK (
            confidence IS NULL
            OR confidence BETWEEN 0 AND 1
        ),
    CONSTRAINT auction_component_observation_unique
        UNIQUE (
            marketplace,
            listing_id,
            component_code,
            variant_key
        )
);

CREATE INDEX auction_component_listing_idx
    ON warehouse.auction_component_observation (
        marketplace,
        listing_id
    );

CREATE TABLE warehouse.auction_condition_normalization (
    id bigserial PRIMARY KEY,
    marketplace varchar(40) NOT NULL,
    listing_id varchar(255) NOT NULL,
    media_grade_code varchar(20)
        REFERENCES system.condition_grade(code),
    cover_grade_code varchar(20)
        REFERENCES system.condition_grade(code),
    source_media_condition text,
    source_cover_condition text,
    condition_factor_override numeric(8, 4),
    confidence numeric(5, 4),
    is_manual_override boolean NOT NULL DEFAULT false,
    notes text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT auction_condition_factor_positive
        CHECK (
            condition_factor_override IS NULL
            OR condition_factor_override > 0
        ),
    CONSTRAINT auction_condition_confidence_range
        CHECK (
            confidence IS NULL
            OR confidence BETWEEN 0 AND 1
        ),
    CONSTRAINT auction_condition_listing_unique
        UNIQUE (marketplace, listing_id)
);

CREATE TABLE warehouse.auction_behavior_observation (
    id bigserial PRIMARY KEY,
    marketplace varchar(40) NOT NULL,
    listing_id varchar(255) NOT NULL,
    distinct_bidder_count integer,
    distinct_bidder_state text NOT NULL DEFAULT 'UNAVAILABLE',
    distinct_bidder_source text,
    closing_window_minutes integer,
    closing_window_start_price numeric(16, 4),
    closing_window_final_price numeric(16, 4),
    closing_window_currency varchar(8),
    closing_window_escalation_ratio numeric(16, 8)
        GENERATED ALWAYS AS (
            CASE
                WHEN closing_window_start_price > 0
                 AND closing_window_final_price IS NOT NULL
                THEN (
                    closing_window_final_price
                    / closing_window_start_price
                ) - 1
                ELSE NULL
            END
        ) STORED,
    reserve_status text,
    notes text,
    observed_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT auction_behavior_bidder_state_valid
        CHECK (
            distinct_bidder_state IN (
                'OBSERVED',
                'MANUAL',
                'NOT_EXPOSED',
                'UNAVAILABLE',
                'ESTIMATED'
            )
        ),
    CONSTRAINT auction_behavior_bidder_count_nonnegative
        CHECK (
            distinct_bidder_count IS NULL
            OR distinct_bidder_count >= 0
        ),
    CONSTRAINT auction_behavior_minutes_nonnegative
        CHECK (
            closing_window_minutes IS NULL
            OR closing_window_minutes >= 0
        ),
    CONSTRAINT auction_behavior_bidder_semantics
        CHECK (
            (
                distinct_bidder_state IN (
                    'OBSERVED',
                    'MANUAL',
                    'ESTIMATED'
                )
                AND distinct_bidder_count IS NOT NULL
            )
            OR (
                distinct_bidder_state IN (
                    'NOT_EXPOSED',
                    'UNAVAILABLE'
                )
                AND distinct_bidder_count IS NULL
            )
        ),
    CONSTRAINT auction_behavior_listing_unique
        UNIQUE (marketplace, listing_id)
);

CREATE TABLE warehouse.auction_price_snapshot (
    id bigserial PRIMARY KEY,
    marketplace varchar(40) NOT NULL,
    listing_id varchar(255) NOT NULL,
    captured_at timestamptz NOT NULL,
    price_local numeric(16, 4),
    currency varchar(8),
    bid_count integer,
    watch_count integer,
    source text NOT NULL DEFAULT 'UNKNOWN',
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT auction_snapshot_bid_count_nonnegative
        CHECK (
            bid_count IS NULL
            OR bid_count >= 0
        ),
    CONSTRAINT auction_snapshot_watch_count_nonnegative
        CHECK (
            watch_count IS NULL
            OR watch_count >= 0
        ),
    CONSTRAINT auction_snapshot_unique
        UNIQUE (
            marketplace,
            listing_id,
            captured_at,
            source
        )
);

CREATE INDEX auction_snapshot_listing_time_idx
    ON warehouse.auction_price_snapshot (
        marketplace,
        listing_id,
        captured_at DESC
    );

CREATE TABLE warehouse.listing_lineage (
    id bigserial PRIMARY KEY,
    lineage_key text NOT NULL UNIQUE,
    description text,
    physical_copy_confidence numeric(5, 4),
    notes text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT listing_lineage_key_not_blank
        CHECK (btrim(lineage_key) <> ''),
    CONSTRAINT listing_lineage_confidence_range
        CHECK (
            physical_copy_confidence IS NULL
            OR physical_copy_confidence BETWEEN 0 AND 1
        )
);

CREATE TABLE warehouse.listing_lineage_member (
    id bigserial PRIMARY KEY,
    lineage_id bigint NOT NULL
        REFERENCES warehouse.listing_lineage(id)
        ON DELETE CASCADE,
    marketplace varchar(40) NOT NULL,
    listing_id varchar(255) NOT NULL,
    sequence_number integer,
    relationship_type text NOT NULL DEFAULT 'RELISTING',
    notes text,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT listing_lineage_relationship_valid
        CHECK (
            relationship_type IN (
                'RELISTING',
                'WITHDRAWN_RUN',
                'INTERRUPTED_RUN',
                'SAME_COPY',
                'POSSIBLE_SAME_COPY',
                'OTHER'
            )
        ),
    CONSTRAINT listing_lineage_listing_unique
        UNIQUE (marketplace, listing_id)
);

CREATE TABLE warehouse.auction_event_context (
    id bigserial PRIMARY KEY,
    marketplace varchar(40) NOT NULL,
    listing_id varchar(255) NOT NULL,
    seller_group text,
    seller_kind text,
    event_type text NOT NULL DEFAULT 'UNKNOWN',
    private_collection boolean,
    record_shop_inventory boolean,
    rolling_auction boolean,
    relisted boolean,
    interrupted boolean,
    withdrawn boolean,
    notes text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT auction_event_type_valid
        CHECK (
            event_type IN (
                'STANDARD_AUCTION',
                'FIXED_PRICE',
                'BEST_OFFER',
                'PRIVATE_COLLECTION_DISPERSAL',
                'SHOP_INVENTORY',
                'ROLLING_AUCTION',
                'RELISTING',
                'UNKNOWN'
            )
        ),
    CONSTRAINT auction_event_listing_unique
        UNIQUE (marketplace, listing_id)
);

CREATE TABLE warehouse.auction_analysis_input (
    id bigserial PRIMARY KEY,
    marketplace varchar(40) NOT NULL,
    listing_id varchar(255) NOT NULL,
    price_basis text NOT NULL DEFAULT 'GROSS',
    completeness_market_factor numeric(8, 4),
    condition_factor_override numeric(8, 4),
    title_strength_score numeric(5, 2),
    market_context_score numeric(5, 2),
    manual_auction_behavior_score numeric(5, 2),
    expectation_price_usd numeric(16, 4),
    historical_anchor_usd numeric(16, 4),
    notes text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT auction_analysis_price_basis_valid
        CHECK (
            price_basis IN (
                'HAMMER',
                'GROSS',
                'LANDED'
            )
        ),
    CONSTRAINT auction_analysis_completeness_factor_positive
        CHECK (
            completeness_market_factor IS NULL
            OR completeness_market_factor > 0
        ),
    CONSTRAINT auction_analysis_condition_factor_positive
        CHECK (
            condition_factor_override IS NULL
            OR condition_factor_override > 0
        ),
    CONSTRAINT auction_analysis_title_score_range
        CHECK (
            title_strength_score IS NULL
            OR title_strength_score BETWEEN 0 AND 20
        ),
    CONSTRAINT auction_analysis_market_score_range
        CHECK (
            market_context_score IS NULL
            OR market_context_score BETWEEN 0 AND 20
        ),
    CONSTRAINT auction_analysis_behavior_score_range
        CHECK (
            manual_auction_behavior_score IS NULL
            OR manual_auction_behavior_score BETWEEN 0 AND 20
        ),
    CONSTRAINT auction_analysis_listing_unique
        UNIQUE (marketplace, listing_id)
);

CREATE OR REPLACE VIEW warehouse.auction_completeness AS
WITH expectation_rollup AS (
    SELECT
        assignment.marketplace,
        assignment.listing_id,
        assignment.pressing_id,
        pressing.release_family_id,
        COUNT(*) FILTER (
            WHERE expectation.expectation_state = 'REQUIRED'
        ) AS required_component_count,
        COUNT(*) FILTER (
            WHERE expectation.expectation_state = 'REQUIRED'
              AND observation.observation_state = 'PRESENT'
        ) AS present_required_component_count,
        COALESCE(
            ARRAY_AGG(
                DISTINCT expectation.component_code
                ORDER BY expectation.component_code
            ) FILTER (
                WHERE expectation.expectation_state = 'REQUIRED'
                  AND observation.observation_state = 'ABSENT'
            ),
            ARRAY[]::text[]
        ) AS missing_components,
        COALESCE(
            ARRAY_AGG(
                DISTINCT expectation.component_code
                ORDER BY expectation.component_code
            ) FILTER (
                WHERE expectation.expectation_state = 'REQUIRED'
                  AND (
                      observation.id IS NULL
                      OR observation.observation_state IN (
                          'UNKNOWN',
                          'NOT_VISIBLE',
                          'NOT_APPLICABLE'
                      )
                  )
            ),
            ARRAY[]::text[]
        ) AS unverified_components
    FROM warehouse.auction_pressing_assignment AS assignment
    JOIN warehouse.pressing_identity AS pressing
      ON pressing.id = assignment.pressing_id
    LEFT JOIN warehouse.pressing_component_expectation AS expectation
      ON expectation.pressing_id = assignment.pressing_id
    LEFT JOIN warehouse.auction_component_observation AS observation
      ON observation.marketplace = assignment.marketplace
     AND observation.listing_id = assignment.listing_id
     AND observation.component_code = expectation.component_code
     AND observation.variant_key = expectation.variant_key
    GROUP BY
        assignment.marketplace,
        assignment.listing_id,
        assignment.pressing_id,
        pressing.release_family_id
),
unexpected_rollup AS (
    SELECT
        assignment.marketplace,
        assignment.listing_id,
        COALESCE(
            ARRAY_AGG(
                DISTINCT observation.component_code
                ORDER BY observation.component_code
            ) FILTER (
                WHERE observation.observation_state = 'PRESENT'
                  AND (
                      expectation.id IS NULL
                      OR expectation.expectation_state = 'NOT_INCLUDED'
                  )
            ),
            ARRAY[]::text[]
        ) AS unexpected_components
    FROM warehouse.auction_pressing_assignment AS assignment
    LEFT JOIN warehouse.auction_component_observation AS observation
      ON observation.marketplace = assignment.marketplace
     AND observation.listing_id = assignment.listing_id
    LEFT JOIN warehouse.pressing_component_expectation AS expectation
      ON expectation.pressing_id = assignment.pressing_id
     AND expectation.component_code = observation.component_code
     AND expectation.variant_key = observation.variant_key
    GROUP BY
        assignment.marketplace,
        assignment.listing_id
)
SELECT
    expectation.marketplace,
    expectation.listing_id,
    expectation.release_family_id,
    expectation.pressing_id,
    expectation.required_component_count,
    expectation.present_required_component_count,
    expectation.missing_components,
    expectation.unverified_components,
    COALESCE(
        unexpected.unexpected_components,
        ARRAY[]::text[]
    ) AS unexpected_components,
    CASE
        WHEN expectation.required_component_count = 0
        THEN NULL
        ELSE ROUND(
            expectation.present_required_component_count::numeric
            / expectation.required_component_count::numeric,
            4
        )
    END AS completeness_ratio,
    CASE
        WHEN expectation.required_component_count = 0
        THEN 'NO_EXPECTATION'
        WHEN CARDINALITY(
            expectation.missing_components
        ) > 0
        THEN 'INCOMPLETE'
        WHEN CARDINALITY(
            expectation.unverified_components
        ) > 0
        THEN 'UNVERIFIED'
        ELSE 'COMPLETE'
    END AS completeness_status,
    (
        expectation.required_component_count > 0
        AND expectation.present_required_component_count
            = expectation.required_component_count
        AND CARDINALITY(
            expectation.missing_components
        ) = 0
        AND CARDINALITY(
            expectation.unverified_components
        ) = 0
    ) AS complete
FROM expectation_rollup AS expectation
LEFT JOIN unexpected_rollup AS unexpected
  ON unexpected.marketplace = expectation.marketplace
 AND unexpected.listing_id = expectation.listing_id;

CREATE OR REPLACE VIEW analytics.auction_collector_base AS
WITH component_flags AS (
    SELECT
        marketplace,
        listing_id,
        CASE
            WHEN BOOL_OR(
                component_code = 'OBI'
                AND observation_state = 'PRESENT'
            )
            THEN 'PRESENT'
            WHEN BOOL_OR(
                component_code = 'OBI'
                AND observation_state = 'ABSENT'
            )
            THEN 'ABSENT'
            ELSE 'UNKNOWN'
        END AS obi_state,
        MAX(variant_key) FILTER (
            WHERE component_code = 'OBI'
              AND observation_state = 'PRESENT'
        ) AS obi_variant_key,
        CASE
            WHEN BOOL_OR(
                component_code = 'SHRINK_WRAP'
                AND observation_state = 'PRESENT'
            )
            THEN 'PRESENT'
            WHEN BOOL_OR(
                component_code = 'SHRINK_WRAP'
                AND observation_state = 'ABSENT'
            )
            THEN 'ABSENT'
            ELSE 'UNKNOWN'
        END AS sealed_state
    FROM warehouse.auction_component_observation
    GROUP BY marketplace, listing_id
),
joined AS (
    SELECT
        auction.*,
        assignment.pressing_id,
        pressing.release_family_id,
        family.display_artist AS canonical_artist,
        family.display_title AS canonical_release_title,
        pressing.catalog_number AS canonical_catalog_number,
        pressing.matrix_number AS canonical_matrix_number,
        pressing.region AS pressing_region,
        pressing.country AS pressing_country,
        pressing.generation AS pressing_generation,
        pressing.pressing_variant_key,
        pressing.pressing_variant_label,
        pressing.is_first_press,
        pressing.is_modern_repress,
        pressing.disc_count AS canonical_disc_count,
        assignment.match_basis AS pressing_match_basis,
        assignment.match_confidence AS pressing_match_confidence,
        completeness.required_component_count,
        completeness.present_required_component_count,
        completeness.missing_components,
        completeness.unverified_components,
        completeness.unexpected_components,
        completeness.completeness_ratio,
        completeness.completeness_status,
        completeness.complete,
        component_flags.obi_state,
        component_flags.obi_variant_key,
        component_flags.sealed_state,
        condition.media_grade_code,
        condition.cover_grade_code,
        media_grade.sort_rank AS media_condition_rank,
        cover_grade.sort_rank AS cover_condition_rank,
        media_grade.score_20 AS media_condition_score,
        cover_grade.score_20 AS cover_condition_score,
        behavior.distinct_bidder_count,
        behavior.distinct_bidder_state,
        behavior.distinct_bidder_source,
        behavior.closing_window_minutes,
        behavior.closing_window_start_price,
        behavior.closing_window_final_price,
        behavior.closing_window_currency,
        behavior.closing_window_escalation_ratio,
        event_context.seller_group,
        event_context.seller_kind,
        event_context.event_type,
        event_context.private_collection,
        event_context.record_shop_inventory,
        event_context.rolling_auction,
        event_context.relisted,
        event_context.interrupted,
        event_context.withdrawn,
        lineage_member.lineage_id,
        analysis.price_basis,
        analysis.title_strength_score,
        analysis.market_context_score,
        analysis.manual_auction_behavior_score,
        analysis.expectation_price_usd,
        analysis.historical_anchor_usd,
        COALESCE(
            analysis.condition_factor_override,
            condition.condition_factor_override,
            CASE
                WHEN media_grade.market_value_factor IS NOT NULL
                 AND cover_grade.market_value_factor IS NOT NULL
                THEN (
                    media_grade.market_value_factor
                    + cover_grade.market_value_factor
                ) / 2
                ELSE COALESCE(
                    media_grade.market_value_factor,
                    cover_grade.market_value_factor
                )
            END
        ) AS condition_market_factor,
        COALESCE(
            analysis.completeness_market_factor,
            CASE
                WHEN completeness.complete
                THEN 1.0000
                ELSE NULL
            END
        ) AS completeness_market_factor,
        auction.final_price AS price_hammer_local,
        COALESCE(
            auction.gross_price,
            auction.final_price
                + COALESCE(auction.tax_amount, 0)
        ) AS price_gross_local,
        COALESCE(
            auction.gross_price,
            auction.final_price
                + COALESCE(auction.tax_amount, 0)
        ) + COALESCE(
            auction.shipping_price,
            0
        ) AS price_landed_local,
        auction.final_price_usd AS price_hammer_usd,
        COALESCE(
            auction.gross_price_usd,
            auction.final_price_usd
                + COALESCE(auction.tax_usd, 0)
        ) AS price_gross_usd,
        COALESCE(
            auction.landed_price_usd,
            COALESCE(
                auction.gross_price_usd,
                auction.final_price_usd
                    + COALESCE(auction.tax_usd, 0)
            ) + COALESCE(
                auction.shipping_price_usd,
                0
            )
        ) AS price_landed_usd
    FROM warehouse.auction AS auction
    LEFT JOIN warehouse.auction_pressing_assignment AS assignment
      ON assignment.marketplace = auction.marketplace
     AND assignment.listing_id = auction.listing_id
    LEFT JOIN warehouse.pressing_identity AS pressing
      ON pressing.id = assignment.pressing_id
    LEFT JOIN warehouse.release_family AS family
      ON family.id = pressing.release_family_id
    LEFT JOIN warehouse.auction_completeness AS completeness
      ON completeness.marketplace = auction.marketplace
     AND completeness.listing_id = auction.listing_id
    LEFT JOIN component_flags
      ON component_flags.marketplace = auction.marketplace
     AND component_flags.listing_id = auction.listing_id
    LEFT JOIN warehouse.auction_condition_normalization AS condition
      ON condition.marketplace = auction.marketplace
     AND condition.listing_id = auction.listing_id
    LEFT JOIN system.condition_grade AS media_grade
      ON media_grade.code = condition.media_grade_code
    LEFT JOIN system.condition_grade AS cover_grade
      ON cover_grade.code = condition.cover_grade_code
    LEFT JOIN warehouse.auction_behavior_observation AS behavior
      ON behavior.marketplace = auction.marketplace
     AND behavior.listing_id = auction.listing_id
    LEFT JOIN warehouse.auction_event_context AS event_context
      ON event_context.marketplace = auction.marketplace
     AND event_context.listing_id = auction.listing_id
    LEFT JOIN warehouse.listing_lineage_member AS lineage_member
      ON lineage_member.marketplace = auction.marketplace
     AND lineage_member.listing_id = auction.listing_id
    LEFT JOIN warehouse.auction_analysis_input AS analysis
      ON analysis.marketplace = auction.marketplace
     AND analysis.listing_id = auction.listing_id
),
priced AS (
    SELECT
        joined.*,
        CASE COALESCE(price_basis, 'GROSS')
            WHEN 'HAMMER' THEN price_hammer_local
            WHEN 'LANDED' THEN price_landed_local
            ELSE price_gross_local
        END AS selected_price_local,
        CASE COALESCE(price_basis, 'GROSS')
            WHEN 'HAMMER' THEN price_hammer_usd
            WHEN 'LANDED' THEN price_landed_usd
            ELSE price_gross_usd
        END AS selected_price_usd
    FROM joined
)
SELECT
    priced.*,
    CASE
        WHEN selected_price_usd IS NOT NULL
         AND condition_market_factor > 0
        THEN selected_price_usd
            / condition_market_factor
        ELSE NULL
    END AS condition_adjusted_price_usd,
    CASE
        WHEN selected_price_usd IS NOT NULL
         AND condition_market_factor > 0
         AND completeness_market_factor > 0
        THEN selected_price_usd
            / condition_market_factor
            / completeness_market_factor
        ELSE NULL
    END AS fully_normalized_price_usd,
    (
        selected_price_usd IS NOT NULL
        AND condition_market_factor > 0
        AND completeness_market_factor > 0
    ) AS normalization_ready
FROM priced;

CREATE OR REPLACE VIEW analytics.pressing_assignment_queue AS
SELECT
    auction.artist,
    auction.catalog_number,
    auction.media_type,
    COUNT(*) AS listing_count,
    COUNT(*) FILTER (
        WHERE auction.bulk_lot IS TRUE
    ) AS bulk_lot_count,
    (ARRAY_AGG(
        auction.title
        ORDER BY auction.id DESC
    ))[1:3] AS sample_titles
FROM warehouse.auction AS auction
LEFT JOIN warehouse.auction_pressing_assignment AS assignment
  ON assignment.marketplace = auction.marketplace
 AND assignment.listing_id = auction.listing_id
WHERE assignment.id IS NULL
GROUP BY
    auction.artist,
    auction.catalog_number,
    auction.media_type
ORDER BY
    COUNT(*) DESC,
    auction.catalog_number NULLS LAST;

CREATE OR REPLACE FUNCTION analytics.comparable_confidence(
    target_marketplace text,
    target_listing_id text,
    candidate_marketplace text,
    candidate_listing_id text
)
RETURNS numeric
LANGUAGE sql
STABLE
AS $function$
WITH target AS (
    SELECT *
    FROM analytics.auction_collector_base
    WHERE marketplace = target_marketplace
      AND listing_id = target_listing_id
),
candidate AS (
    SELECT *
    FROM analytics.auction_collector_base
    WHERE marketplace = candidate_marketplace
      AND listing_id = candidate_listing_id
)
SELECT
    CASE
        WHEN target.release_family_id IS NULL
          OR candidate.release_family_id IS NULL
          OR target.release_family_id
                <> candidate.release_family_id
        THEN 0
        ELSE ROUND(
            (
                30
                + CASE
                    WHEN target.pressing_id
                        = candidate.pressing_id
                    THEN 25 ELSE 0
                  END
                + CASE
                    WHEN target.pressing_generation
                        = candidate.pressing_generation
                    THEN 10 ELSE 0
                  END
                + CASE
                    WHEN target.pressing_region
                        = candidate.pressing_region
                    THEN 8 ELSE 0
                  END
                + CASE
                    WHEN target.media_type
                        = candidate.media_type
                    THEN 8 ELSE 0
                  END
                + CASE
                    WHEN target.canonical_disc_count
                        = candidate.canonical_disc_count
                    THEN 5 ELSE 0
                  END
                + CASE
                    WHEN target.completeness_status
                        = candidate.completeness_status
                    THEN 5 ELSE 0
                  END
                + CASE
                    WHEN target.media_condition_rank IS NOT NULL
                     AND candidate.media_condition_rank IS NOT NULL
                     AND ABS(
                         target.media_condition_rank
                         - candidate.media_condition_rank
                     ) <= 1
                    THEN 5 ELSE 0
                  END
                + CASE
                    WHEN COALESCE(target.bulk_lot, false)
                        = COALESCE(candidate.bulk_lot, false)
                    THEN 2 ELSE 0
                  END
                + CASE
                    WHEN target.sealed_state
                        = candidate.sealed_state
                    THEN 2 ELSE 0
                  END
            )::numeric,
            2
        )
    END
FROM target
CROSS JOIN candidate;
$function$;

CREATE OR REPLACE VIEW analytics.auction_scores AS
WITH feature_scores AS (
    SELECT
        base.*,
        CASE
            WHEN bid_count IS NULL
            THEN NULL
            ELSE LEAST(
                5,
                LN(1 + bid_count)::numeric
                / LN(51)::numeric
                * 5
            )
        END AS bid_component,
        CASE
            WHEN bid_count IS NULL
              OR watch_count IS NULL
            THEN NULL
            ELSE LEAST(
                3,
                bid_count::numeric
                / (watch_count + 1)::numeric
                * 3
            )
        END AS watcher_component,
        CASE
            WHEN distinct_bidder_state IN (
                'OBSERVED',
                'MANUAL',
                'ESTIMATED'
            )
            THEN LEAST(
                5,
                LN(1 + distinct_bidder_count)::numeric
                / LN(11)::numeric
                * 5
            )
            ELSE NULL
        END AS bidder_component,
        CASE
            WHEN closing_window_escalation_ratio IS NULL
            THEN NULL
            ELSE LEAST(
                7,
                GREATEST(
                    closing_window_escalation_ratio,
                    0
                ) / 2 * 7
            )
        END AS escalation_component
    FROM analytics.auction_collector_base AS base
),
behavior AS (
    SELECT
        feature_scores.*,
        (
            COALESCE(bid_component, 0)
            + COALESCE(watcher_component, 0)
            + COALESCE(bidder_component, 0)
            + COALESCE(escalation_component, 0)
        ) AS behavior_points,
        (
            CASE WHEN bid_component IS NOT NULL THEN 5 ELSE 0 END
            + CASE WHEN watcher_component IS NOT NULL THEN 3 ELSE 0 END
            + CASE WHEN bidder_component IS NOT NULL THEN 5 ELSE 0 END
            + CASE WHEN escalation_component IS NOT NULL THEN 7 ELSE 0 END
        ) AS behavior_available_points
    FROM feature_scores
),
scored AS (
    SELECT
        behavior.*,
        CASE
            WHEN completeness_ratio IS NULL
            THEN NULL
            ELSE ROUND(
                completeness_ratio * 20,
                2
            )
        END AS completeness_score,
        CASE
            WHEN media_condition_score IS NULL
             AND cover_condition_score IS NULL
            THEN NULL
            ELSE ROUND(
                (
                    COALESCE(media_condition_score, 0)
                    + COALESCE(cover_condition_score, 0)
                ) / (
                    CASE
                        WHEN media_condition_score IS NOT NULL
                        THEN 1 ELSE 0
                    END
                    + CASE
                        WHEN cover_condition_score IS NOT NULL
                        THEN 1 ELSE 0
                    END
                ),
                2
            )
        END AS condition_score,
        COALESCE(
            manual_auction_behavior_score,
            CASE
                WHEN behavior_available_points = 0
                THEN NULL
                ELSE ROUND(
                    behavior_points
                    / behavior_available_points
                    * 20,
                    2
                )
            END
        ) AS auction_behavior_score,
        CASE
            WHEN behavior_available_points = 0
            THEN 0
            ELSE ROUND(
                behavior_available_points::numeric
                / 20,
                4
            )
        END AS auction_behavior_coverage
    FROM behavior
)
SELECT
    scored.*,
    CASE
        WHEN title_strength_score IS NOT NULL
         AND completeness_score IS NOT NULL
         AND condition_score IS NOT NULL
         AND auction_behavior_score IS NOT NULL
         AND market_context_score IS NOT NULL
        THEN ROUND(
            title_strength_score
            + completeness_score
            + condition_score
            + auction_behavior_score
            + market_context_score,
            2
        )
        ELSE NULL
    END AS plushie_index,
    ROUND(
        COALESCE(title_strength_score, 0)
        + COALESCE(completeness_score, 0)
        + COALESCE(condition_score, 0)
        + COALESCE(auction_behavior_score, 0)
        + COALESCE(market_context_score, 0),
        2
    ) AS plushie_partial_score,
    ROUND(
        (
            CASE WHEN title_strength_score IS NOT NULL THEN 1 ELSE 0 END
            + CASE WHEN completeness_score IS NOT NULL THEN 1 ELSE 0 END
            + CASE WHEN condition_score IS NOT NULL THEN 1 ELSE 0 END
            + CASE WHEN auction_behavior_score IS NOT NULL THEN 1 ELSE 0 END
            + CASE WHEN market_context_score IS NOT NULL THEN 1 ELSE 0 END
        )::numeric / 5,
        4
    ) AS plushie_coverage
FROM scored;

CREATE OR REPLACE VIEW analytics.midfication_detection AS
WITH grouped AS (
    SELECT
        release_family_id,
        canonical_artist,
        canonical_release_title,
        media_type,
        COUNT(*) FILTER (
            WHERE pressing_generation = 'FIRST_PRESS'
        ) AS first_press_sales,
        COUNT(*) FILTER (
            WHERE pressing_generation IN (
                'REISSUE',
                'MODERN_REPRESS'
            )
        ) AS modern_sales,
        PERCENTILE_CONT(0.5) WITHIN GROUP (
            ORDER BY fully_normalized_price_usd
        ) FILTER (
            WHERE pressing_generation = 'FIRST_PRESS'
        ) AS first_press_adjusted_median,
        PERCENTILE_CONT(0.5) WITHIN GROUP (
            ORDER BY fully_normalized_price_usd
        ) FILTER (
            WHERE pressing_generation IN (
                'REISSUE',
                'MODERN_REPRESS'
            )
        ) AS modern_adjusted_median
    FROM analytics.auction_collector_base
    WHERE normalization_ready
      AND bulk_lot IS NOT TRUE
      AND release_family_id IS NOT NULL
    GROUP BY
        release_family_id,
        canonical_artist,
        canonical_release_title,
        media_type
)
SELECT
    grouped.*,
    modern_adjusted_median
        / NULLIF(
            first_press_adjusted_median,
            0
        ) AS midfication_ratio,
    CASE
        WHEN first_press_sales = 0
          OR modern_sales = 0
        THEN 'INSUFFICIENT_DATA'
        WHEN modern_adjusted_median
            / NULLIF(first_press_adjusted_median, 0) < 0.60
        THEN 'NORMAL'
        WHEN modern_adjusted_median
            / NULLIF(first_press_adjusted_median, 0) < 0.80
        THEN 'MID_GAINING_VISIBILITY'
        WHEN modern_adjusted_median
            / NULLIF(first_press_adjusted_median, 0) < 1.00
        THEN 'YELLOW_ALERT'
        WHEN modern_adjusted_median
            / NULLIF(first_press_adjusted_median, 0) < 1.20
        THEN 'FIRST_PRESS_DEFENSE_BREACH'
        WHEN modern_sales >= 3
        THEN 'STRUCTURAL_MIDFICATION'
        ELSE 'MIDFICATION_INCIDENT'
    END AS midfication_status
FROM grouped;

CREATE OR REPLACE VIEW analytics.completeness_premium AS
WITH grouped AS (
    SELECT
        pressing_id,
        canonical_artist,
        canonical_release_title,
        canonical_catalog_number,
        COUNT(*) FILTER (
            WHERE completeness_status = 'COMPLETE'
        ) AS complete_sales,
        COUNT(*) FILTER (
            WHERE completeness_status = 'INCOMPLETE'
        ) AS incomplete_sales,
        PERCENTILE_CONT(0.5) WITHIN GROUP (
            ORDER BY condition_adjusted_price_usd
        ) FILTER (
            WHERE completeness_status = 'COMPLETE'
        ) AS complete_median_usd,
        PERCENTILE_CONT(0.5) WITHIN GROUP (
            ORDER BY condition_adjusted_price_usd
        ) FILTER (
            WHERE completeness_status = 'INCOMPLETE'
        ) AS incomplete_median_usd
    FROM analytics.auction_collector_base
    WHERE condition_adjusted_price_usd IS NOT NULL
      AND bulk_lot IS NOT TRUE
      AND pressing_id IS NOT NULL
    GROUP BY
        pressing_id,
        canonical_artist,
        canonical_release_title,
        canonical_catalog_number
)
SELECT
    grouped.*,
    complete_median_usd
        / NULLIF(
            incomplete_median_usd,
            0
        ) AS completeness_premium
FROM grouped;

CREATE OR REPLACE VIEW analytics.obi_premium AS
WITH grouped AS (
    SELECT
        pressing_id,
        canonical_artist,
        canonical_release_title,
        canonical_catalog_number,
        COUNT(*) FILTER (
            WHERE obi_state = 'PRESENT'
        ) AS with_obi_sales,
        COUNT(*) FILTER (
            WHERE obi_state = 'ABSENT'
        ) AS without_obi_sales,
        PERCENTILE_CONT(0.5) WITHIN GROUP (
            ORDER BY condition_adjusted_price_usd
        ) FILTER (
            WHERE obi_state = 'PRESENT'
        ) AS with_obi_median_usd,
        PERCENTILE_CONT(0.5) WITHIN GROUP (
            ORDER BY condition_adjusted_price_usd
        ) FILTER (
            WHERE obi_state = 'ABSENT'
        ) AS without_obi_median_usd
    FROM analytics.auction_collector_base
    WHERE condition_adjusted_price_usd IS NOT NULL
      AND bulk_lot IS NOT TRUE
      AND pressing_id IS NOT NULL
    GROUP BY
        pressing_id,
        canonical_artist,
        canonical_release_title,
        canonical_catalog_number
)
SELECT
    grouped.*,
    with_obi_median_usd
        / NULLIF(
            without_obi_median_usd,
            0
        ) AS obi_premium
FROM grouped;

CREATE OR REPLACE VIEW analytics.obi_variant_price_summary AS
SELECT
    pressing_id,
    canonical_artist,
    canonical_release_title,
    canonical_catalog_number,
    COALESCE(
        NULLIF(obi_variant_key, ''),
        'REGULAR_OR_UNSPECIFIED'
    ) AS obi_variant,
    COUNT(*) AS sales,
    PERCENTILE_CONT(0.5) WITHIN GROUP (
        ORDER BY condition_adjusted_price_usd
    ) AS median_price_usd
FROM analytics.auction_collector_base
WHERE obi_state = 'PRESENT'
  AND condition_adjusted_price_usd IS NOT NULL
  AND bulk_lot IS NOT TRUE
  AND pressing_id IS NOT NULL
GROUP BY
    pressing_id,
    canonical_artist,
    canonical_release_title,
    canonical_catalog_number,
    COALESCE(
        NULLIF(obi_variant_key, ''),
        'REGULAR_OR_UNSPECIFIED'
    );

CREATE OR REPLACE VIEW analytics.emotional_damage AS
WITH first_press AS (
    SELECT
        release_family_id,
        media_type,
        PERCENTILE_CONT(0.5) WITHIN GROUP (
            ORDER BY fully_normalized_price_usd
        ) AS first_press_median
    FROM analytics.auction_collector_base
    WHERE is_first_press
      AND fully_normalized_price_usd IS NOT NULL
    GROUP BY release_family_id, media_type
),
complete_price AS (
    SELECT
        pressing_id,
        PERCENTILE_CONT(0.5) WITHIN GROUP (
            ORDER BY condition_adjusted_price_usd
        ) AS complete_median
    FROM analytics.auction_collector_base
    WHERE completeness_status = 'COMPLETE'
      AND condition_adjusted_price_usd IS NOT NULL
    GROUP BY pressing_id
),
components AS (
    SELECT
        score.*,
        CASE
            WHEN expectation_price_usd > 0
             AND selected_price_usd IS NOT NULL
            THEN LEAST(
                20,
                ABS(
                    selected_price_usd
                    / expectation_price_usd
                    - 1
                ) * 20
            )
            ELSE NULL
        END AS expectation_deviation,
        CASE
            WHEN closing_window_escalation_ratio IS NOT NULL
            THEN LEAST(
                20,
                GREATEST(
                    closing_window_escalation_ratio,
                    0
                ) * 10
            )
            ELSE NULL
        END AS late_spike,
        CASE
            WHEN historical_anchor_usd > 0
             AND selected_price_usd IS NOT NULL
            THEN LEAST(
                20,
                ABS(
                    selected_price_usd
                    / historical_anchor_usd
                    - 1
                ) * 10
            )
            ELSE NULL
        END AS historical_anchor_deviation,
        CASE
            WHEN completeness_status = 'INCOMPLETE'
             AND complete_price.complete_median > 0
             AND condition_adjusted_price_usd
                    > complete_price.complete_median
            THEN LEAST(
                20,
                (
                    condition_adjusted_price_usd
                    / complete_price.complete_median
                    - 1
                ) * 20
            )
            ELSE NULL
        END AS completeness_contradiction,
        CASE
            WHEN is_modern_repress
             AND first_press.first_press_median > 0
             AND fully_normalized_price_usd
                    > first_press.first_press_median
            THEN LEAST(
                20,
                (
                    fully_normalized_price_usd
                    / first_press.first_press_median
                    - 1
                ) * 20
            )
            ELSE NULL
        END AS first_press_distortion,
        auction_behavior_score AS bidder_war_intensity
    FROM analytics.auction_scores AS score
    LEFT JOIN first_press
      ON first_press.release_family_id = score.release_family_id
     AND first_press.media_type = score.media_type
    LEFT JOIN complete_price
      ON complete_price.pressing_id = score.pressing_id
),
summed AS (
    SELECT
        components.*,
        (
            COALESCE(expectation_deviation, 0)
            + COALESCE(late_spike, 0)
            + COALESCE(historical_anchor_deviation, 0)
            + COALESCE(completeness_contradiction, 0)
            + COALESCE(first_press_distortion, 0)
            + COALESCE(bidder_war_intensity, 0)
        ) AS damage_points,
        (
            CASE WHEN expectation_deviation IS NOT NULL THEN 1 ELSE 0 END
            + CASE WHEN late_spike IS NOT NULL THEN 1 ELSE 0 END
            + CASE WHEN historical_anchor_deviation IS NOT NULL THEN 1 ELSE 0 END
            + CASE WHEN completeness_contradiction IS NOT NULL THEN 1 ELSE 0 END
            + CASE WHEN first_press_distortion IS NOT NULL THEN 1 ELSE 0 END
            + CASE WHEN bidder_war_intensity IS NOT NULL THEN 1 ELSE 0 END
        ) AS damage_components
    FROM components
),
scored AS (
    SELECT
        summed.*,
        CASE
            WHEN damage_components = 0
            THEN NULL
            ELSE ROUND(
                (
                    damage_points
                    / (damage_components * 20)
                    * 100
                )::numeric,
                2
            )
        END AS emotional_damage_score,
        ROUND(
            damage_components::numeric / 6,
            4
        ) AS emotional_damage_coverage
    FROM summed
)
SELECT
    scored.*,
    CASE
        WHEN emotional_damage_score IS NULL
        THEN 'INSUFFICIENT_DATA'
        WHEN emotional_damage_score >= 90
        THEN 'SKINWALKER_RANCH'
        WHEN emotional_damage_score >= 75
        THEN 'SEV_0'
        WHEN emotional_damage_score >= 60
        THEN 'BIDDER_IDENTITY_WAR'
        WHEN emotional_damage_score >= 40
        THEN 'MAJOR_INCIDENT'
        WHEN emotional_damage_score >= 20
        THEN 'ELEVATED'
        ELSE 'NORMAL'
    END AS incident_class
FROM scored;

CREATE OR REPLACE VIEW analytics.auction_alerts AS
SELECT
    marketplace,
    listing_id,
    'LATE_SPIKE_OVER_75_PERCENT' AS alert_code,
    'HIGH' AS severity,
    closing_window_escalation_ratio AS metric_value
FROM analytics.auction_collector_base
WHERE closing_window_escalation_ratio > 0.75

UNION ALL

SELECT
    marketplace,
    listing_id,
    'PRICE_OVER_2X_HISTORICAL_ANCHOR',
    'CRITICAL',
    selected_price_usd
        / NULLIF(historical_anchor_usd, 0)
FROM analytics.auction_collector_base
WHERE historical_anchor_usd > 0
  AND selected_price_usd
        > historical_anchor_usd * 2

UNION ALL

SELECT
    base.marketplace,
    base.listing_id,
    'INCOMPLETE_EXCEEDS_COMPLETE_MEDIAN',
    'HIGH',
    base.condition_adjusted_price_usd
        / NULLIF(premium.complete_median_usd, 0)
FROM analytics.auction_collector_base AS base
JOIN analytics.completeness_premium AS premium
  ON premium.pressing_id = base.pressing_id
WHERE base.completeness_status = 'INCOMPLETE'
  AND base.condition_adjusted_price_usd
        > premium.complete_median_usd

UNION ALL

SELECT
    marketplace,
    listing_id,
    'HIGH_BID_COUNT_LOW_BIDDER_COUNT',
    'MEDIUM',
    bid_count
FROM analytics.auction_collector_base
WHERE bid_count >= 30
  AND distinct_bidder_count <= 2
  AND distinct_bidder_state IN (
      'OBSERVED',
      'MANUAL'
  );
