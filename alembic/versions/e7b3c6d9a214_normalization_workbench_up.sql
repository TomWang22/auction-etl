CREATE TABLE system.normalization_work_batch (
    id uuid PRIMARY KEY,
    work_type varchar(40) NOT NULL,
    filename text,
    payload_sha256 varchar(64) NOT NULL,
    actor varchar(120) NOT NULL,
    reason text NOT NULL,
    status varchar(30) NOT NULL,
    requested_row_count integer NOT NULL DEFAULT 0,
    applied_row_count integer NOT NULL DEFAULT 0,
    rejected_row_count integer NOT NULL DEFAULT 0,
    validation_summary jsonb NOT NULL DEFAULT '{}'::jsonb,
    error_message text,
    created_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz,
    CONSTRAINT normalization_work_batch_type_check
        CHECK (
            work_type IN (
                'CONDITION',
                'ANALYSIS_FACTOR',
                'COMPARABLE_REVIEW'
            )
        ),
    CONSTRAINT normalization_work_batch_status_check
        CHECK (
            status IN (
                'RUNNING',
                'COMPLETED',
                'FAILED'
            )
        ),
    CONSTRAINT normalization_work_batch_sha256_check
        CHECK (
            payload_sha256 ~ '^[0-9a-fA-F]{64}$'
        )
);

CREATE INDEX normalization_work_batch_created_idx
    ON system.normalization_work_batch (
        created_at DESC
    );

CREATE TABLE system.normalization_work_batch_row (
    id bigserial PRIMARY KEY,
    batch_id uuid NOT NULL
        REFERENCES system.normalization_work_batch (id)
        ON DELETE CASCADE,
    row_number integer NOT NULL,
    entity_key jsonb NOT NULL,
    outcome varchar(30) NOT NULL,
    before_state jsonb,
    after_state jsonb,
    error_message text,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT normalization_work_batch_row_outcome_check
        CHECK (
            outcome IN (
                'INSERTED',
                'UPDATED',
                'SKIPPED',
                'REJECTED'
            )
        )
);

CREATE INDEX normalization_work_batch_row_batch_idx
    ON system.normalization_work_batch_row (
        batch_id,
        row_number
    );

CREATE TABLE warehouse.auction_comparable_review (
    id bigserial PRIMARY KEY,
    marketplace varchar(80) NOT NULL,
    listing_id varchar(255) NOT NULL,
    comparable_marketplace varchar(80) NOT NULL,
    comparable_listing_id varchar(255) NOT NULL,
    decision varchar(30) NOT NULL,
    reason text NOT NULL,
    actor varchar(120) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT auction_comparable_review_decision_check
        CHECK (
            decision IN (
                'INCLUDE',
                'EXCLUDE',
                'NEEDS_REVIEW'
            )
        ),
    CONSTRAINT auction_comparable_review_distinct_check
        CHECK (
            marketplace <> comparable_marketplace
            OR listing_id <> comparable_listing_id
        ),
    CONSTRAINT auction_comparable_review_identity_unique
        UNIQUE (
            marketplace,
            listing_id,
            comparable_marketplace,
            comparable_listing_id
        )
);

CREATE INDEX auction_comparable_review_target_idx
    ON warehouse.auction_comparable_review (
        marketplace,
        listing_id,
        decision
    );

CREATE TABLE system.normalization_work_audit_event (
    id bigserial PRIMARY KEY,
    entity_type varchar(80) NOT NULL,
    entity_key jsonb NOT NULL,
    action varchar(20) NOT NULL,
    before_state jsonb,
    after_state jsonb,
    actor varchar(120) NOT NULL DEFAULT 'UNKNOWN',
    reason text,
    batch_id uuid,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT normalization_work_audit_action_check
        CHECK (
            action IN (
                'INSERT',
                'UPDATE',
                'DELETE'
            )
        ),
    CONSTRAINT normalization_work_audit_state_check
        CHECK (
            before_state IS NOT NULL
            OR after_state IS NOT NULL
        )
);

CREATE INDEX normalization_work_audit_entity_idx
    ON system.normalization_work_audit_event (
        entity_type,
        created_at DESC
    );

CREATE INDEX normalization_work_audit_key_idx
    ON system.normalization_work_audit_event
    USING gin (entity_key);

CREATE INDEX normalization_work_audit_batch_idx
    ON system.normalization_work_audit_event (
        batch_id,
        created_at
    )
    WHERE batch_id IS NOT NULL;

CREATE OR REPLACE FUNCTION system.reject_normalization_audit_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $audit$
BEGIN
    RAISE EXCEPTION
        'system.normalization_work_audit_event is immutable';
END
$audit$;

CREATE TRIGGER normalization_work_audit_immutable
BEFORE UPDATE OR DELETE
ON system.normalization_work_audit_event
FOR EACH ROW
EXECUTE FUNCTION system.reject_normalization_audit_mutation();

CREATE OR REPLACE FUNCTION system.capture_normalization_work_audit()
RETURNS trigger
LANGUAGE plpgsql
AS $audit$
DECLARE
    before_payload jsonb;
    after_payload jsonb;
    entity_type_value text;
    entity_key_value jsonb;
    actor_value text;
    reason_value text;
    batch_text text;
    batch_value uuid;
BEGIN
    before_payload :=
        CASE
            WHEN TG_OP IN ('UPDATE', 'DELETE')
            THEN to_jsonb(OLD)
            ELSE NULL
        END;

    after_payload :=
        CASE
            WHEN TG_OP IN ('INSERT', 'UPDATE')
            THEN to_jsonb(NEW)
            ELSE NULL
        END;

    IF TG_TABLE_SCHEMA = 'warehouse'
       AND TG_TABLE_NAME =
            'auction_condition_normalization'
    THEN
        entity_type_value :=
            'AUCTION_CONDITION_NORMALIZATION';

        entity_key_value := jsonb_build_object(
            'marketplace',
            COALESCE(
                after_payload -> 'marketplace',
                before_payload -> 'marketplace'
            ),
            'listing_id',
            COALESCE(
                after_payload -> 'listing_id',
                before_payload -> 'listing_id'
            )
        );
    ELSIF TG_TABLE_SCHEMA = 'warehouse'
       AND TG_TABLE_NAME =
            'auction_analysis_input'
    THEN
        entity_type_value :=
            'AUCTION_ANALYSIS_INPUT';

        entity_key_value := jsonb_build_object(
            'marketplace',
            COALESCE(
                after_payload -> 'marketplace',
                before_payload -> 'marketplace'
            ),
            'listing_id',
            COALESCE(
                after_payload -> 'listing_id',
                before_payload -> 'listing_id'
            )
        );
    ELSIF TG_TABLE_SCHEMA = 'warehouse'
       AND TG_TABLE_NAME =
            'auction_comparable_review'
    THEN
        entity_type_value :=
            'AUCTION_COMPARABLE_REVIEW';

        entity_key_value := jsonb_build_object(
            'marketplace',
            COALESCE(
                after_payload -> 'marketplace',
                before_payload -> 'marketplace'
            ),
            'listing_id',
            COALESCE(
                after_payload -> 'listing_id',
                before_payload -> 'listing_id'
            ),
            'comparable_marketplace',
            COALESCE(
                after_payload -> 'comparable_marketplace',
                before_payload -> 'comparable_marketplace'
            ),
            'comparable_listing_id',
            COALESCE(
                after_payload -> 'comparable_listing_id',
                before_payload -> 'comparable_listing_id'
            )
        );
    ELSE
        RAISE EXCEPTION
            'Unsupported normalization audit table';
    END IF;

    actor_value := COALESCE(
        NULLIF(
            current_setting(
                'auction_etl.actor',
                true
            ),
            ''
        ),
        'UNKNOWN'
    );

    reason_value := NULLIF(
        current_setting(
            'auction_etl.reason',
            true
        ),
        ''
    );

    batch_text := NULLIF(
        current_setting(
            'auction_etl.batch_id',
            true
        ),
        ''
    );

    IF batch_text IS NULL THEN
        batch_value := NULL;
    ELSE
        batch_value := batch_text::uuid;
    END IF;

    INSERT INTO system.normalization_work_audit_event (
        entity_type,
        entity_key,
        action,
        before_state,
        after_state,
        actor,
        reason,
        batch_id
    )
    VALUES (
        entity_type_value,
        entity_key_value,
        TG_OP,
        before_payload,
        after_payload,
        actor_value,
        reason_value,
        batch_value
    );

    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;

    RETURN NEW;
END
$audit$;

CREATE TRIGGER auction_condition_normalization_audit
AFTER INSERT OR UPDATE OR DELETE
ON warehouse.auction_condition_normalization
FOR EACH ROW
EXECUTE FUNCTION system.capture_normalization_work_audit();

CREATE TRIGGER auction_analysis_input_audit
AFTER INSERT OR UPDATE OR DELETE
ON warehouse.auction_analysis_input
FOR EACH ROW
EXECUTE FUNCTION system.capture_normalization_work_audit();

CREATE TRIGGER auction_comparable_review_audit
AFTER INSERT OR UPDATE OR DELETE
ON warehouse.auction_comparable_review
FOR EACH ROW
EXECUTE FUNCTION system.capture_normalization_work_audit();

CREATE OR REPLACE VIEW analytics.normalization_work_queue AS
WITH reference_summary AS (
    SELECT
        pressing_id,
        COUNT(*) AS expectation_count,
        COUNT(*) FILTER (
            WHERE expectation_state = 'REQUIRED'
        ) AS required_count,
        COUNT(*) FILTER (
            WHERE expectation_state = 'NOT_INCLUDED'
        ) AS not_included_count,
        COUNT(*) FILTER (
            WHERE expectation_state = 'UNKNOWN'
        ) AS unknown_count
    FROM warehouse.pressing_component_expectation
    GROUP BY pressing_id
),
comparable_summary AS (
    SELECT
        target.marketplace,
        target.listing_id,
        COUNT(*) FILTER (
            WHERE candidate.selected_price_usd IS NOT NULL
        ) AS raw_comparable_count,
        COUNT(*) FILTER (
            WHERE candidate.normalization_ready IS TRUE
              AND candidate.selected_price_usd IS NOT NULL
        ) AS eligible_comparable_count
    FROM analytics.auction_collector_base AS target
    LEFT JOIN analytics.auction_collector_base AS candidate
      ON candidate.pressing_id = target.pressing_id
     AND (
            candidate.marketplace <> target.marketplace
            OR candidate.listing_id <> target.listing_id
         )
    GROUP BY
        target.marketplace,
        target.listing_id
),
review_summary AS (
    SELECT
        marketplace,
        listing_id,
        COUNT(*) FILTER (
            WHERE decision = 'INCLUDE'
        ) AS included_review_count,
        COUNT(*) FILTER (
            WHERE decision = 'EXCLUDE'
        ) AS excluded_review_count,
        COUNT(*) FILTER (
            WHERE decision = 'NEEDS_REVIEW'
        ) AS pending_review_count
    FROM warehouse.auction_comparable_review
    GROUP BY
        marketplace,
        listing_id
)
SELECT
    base.marketplace,
    base.listing_id,
    auction.title,
    auction.artist,
    auction.catalog_number,
    auction.media_type,
    auction.seller,
    auction.ended_at,
    base.pressing_id,
    assignment.match_basis,
    assignment.match_confidence,
    family.display_artist,
    family.display_title,
    pressing.pressing_variant_label,
    COALESCE(
        reference.expectation_count,
        0
    ) AS expectation_count,
    COALESCE(
        reference.required_count,
        0
    ) AS required_reference_count,
    COALESCE(
        reference.not_included_count,
        0
    ) AS not_included_reference_count,
    COALESCE(
        reference.unknown_count,
        0
    ) AS unknown_reference_count,
    completeness.required_component_count,
    completeness.present_required_component_count,
    completeness.missing_components,
    completeness.unverified_components,
    completeness.unexpected_components,
    completeness.completeness_ratio,
    completeness.completeness_status,
    completeness.complete,
    base.selected_price_usd,
    base.condition_market_factor,
    base.completeness_market_factor,
    base.normalization_ready,
    COALESCE(
        comparable.raw_comparable_count,
        0
    ) AS raw_comparable_count,
    COALESCE(
        comparable.eligible_comparable_count,
        0
    ) AS eligible_comparable_count,
    COALESCE(
        review.included_review_count,
        0
    ) AS included_review_count,
    COALESCE(
        review.excluded_review_count,
        0
    ) AS excluded_review_count,
    COALESCE(
        review.pending_review_count,
        0
    ) AS pending_review_count,
    array_remove(
        ARRAY[
            CASE
                WHEN base.pressing_id IS NULL
                THEN 'PRESSING_ASSIGNMENT'
            END,
            CASE
                WHEN base.pressing_id IS NOT NULL
                 AND COALESCE(
                        reference.expectation_count,
                        0
                     ) = 0
                THEN 'COMPLETENESS_REFERENCE'
            END,
            CASE
                WHEN COALESCE(
                        reference.unknown_count,
                        0
                     ) > 0
                THEN 'REFERENCE_VERIFICATION'
            END,
            CASE
                WHEN base.condition_market_factor IS NULL
                THEN 'CONDITION_NORMALIZATION'
            END,
            CASE
                WHEN base.completeness_market_factor IS NULL
                THEN 'COMPLETENESS_FACTOR'
            END,
            CASE
                WHEN base.selected_price_usd IS NULL
                THEN 'PRICE_BASIS'
            END,
            CASE
                WHEN COALESCE(
                        comparable.eligible_comparable_count,
                        0
                     ) < 3
                THEN 'ELIGIBLE_COMPARABLES'
            END
        ]::text[],
        NULL
    ) AS blocker_codes,
    (
        CASE
            WHEN base.pressing_id IS NULL
            THEN 100
            ELSE 0
        END
        +
        CASE
            WHEN base.pressing_id IS NOT NULL
             AND COALESCE(
                    reference.expectation_count,
                    0
                 ) = 0
            THEN 80
            ELSE 0
        END
        +
        CASE
            WHEN COALESCE(
                    reference.unknown_count,
                    0
                 ) > 0
            THEN 60
            ELSE 0
        END
        +
        CASE
            WHEN base.condition_market_factor IS NULL
            THEN 50
            ELSE 0
        END
        +
        CASE
            WHEN base.completeness_market_factor IS NULL
            THEN 40
            ELSE 0
        END
        +
        CASE
            WHEN base.selected_price_usd IS NULL
            THEN 30
            ELSE 0
        END
        +
        CASE
            WHEN COALESCE(
                    comparable.eligible_comparable_count,
                    0
                 ) < 3
            THEN 20
            ELSE 0
        END
        +
        CASE
            WHEN COALESCE(
                    review.pending_review_count,
                    0
                 ) > 0
            THEN 10
            ELSE 0
        END
    ) AS priority_score,
    CASE
        WHEN base.normalization_ready IS TRUE
        THEN 'READY'
        WHEN base.pressing_id IS NULL
        THEN 'NEEDS_PRESSING'
        WHEN COALESCE(
                reference.expectation_count,
                0
             ) = 0
        THEN 'NEEDS_REFERENCE'
        WHEN COALESCE(
                reference.unknown_count,
                0
             ) > 0
        THEN 'NEEDS_REFERENCE_VERIFICATION'
        WHEN base.condition_market_factor IS NULL
        THEN 'NEEDS_CONDITION'
        WHEN base.completeness_market_factor IS NULL
        THEN 'NEEDS_COMPLETENESS_FACTOR'
        WHEN base.selected_price_usd IS NULL
        THEN 'NEEDS_PRICE_BASIS'
        WHEN COALESCE(
                comparable.eligible_comparable_count,
                0
             ) < 3
        THEN 'NEEDS_COMPARABLES'
        ELSE 'BLOCKED_OTHER'
    END AS work_status
FROM analytics.auction_collector_base AS base
JOIN warehouse.auction AS auction
  ON auction.marketplace = base.marketplace
 AND auction.listing_id = base.listing_id
LEFT JOIN warehouse.auction_pressing_assignment AS assignment
  ON assignment.marketplace = base.marketplace
 AND assignment.listing_id = base.listing_id
LEFT JOIN warehouse.pressing_identity AS pressing
  ON pressing.id = base.pressing_id
LEFT JOIN warehouse.release_family AS family
  ON family.id = pressing.release_family_id
LEFT JOIN warehouse.auction_completeness AS completeness
  ON completeness.marketplace = base.marketplace
 AND completeness.listing_id = base.listing_id
LEFT JOIN reference_summary AS reference
  ON reference.pressing_id = base.pressing_id
LEFT JOIN comparable_summary AS comparable
  ON comparable.marketplace = base.marketplace
 AND comparable.listing_id = base.listing_id
LEFT JOIN review_summary AS review
  ON review.marketplace = base.marketplace
 AND review.listing_id = base.listing_id;

ALTER VIEW analytics.normalization_work_queue
OWNER TO auction;

COMMENT ON VIEW analytics.normalization_work_queue IS
    'Prioritized deterministic queue for pressing, reference, condition, factor, price, and comparable normalization work.';
