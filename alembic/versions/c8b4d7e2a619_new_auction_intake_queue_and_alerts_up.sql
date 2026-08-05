CREATE TABLE system.auction_pressing_assignment_audit_event (
    id bigserial PRIMARY KEY,
    marketplace character varying NOT NULL,
    listing_id character varying NOT NULL,
    pressing_id bigint,
    action character varying(16) NOT NULL,
    before_state jsonb,
    after_state jsonb,
    actor character varying NOT NULL DEFAULT 'UNKNOWN',
    reason text,
    occurred_at timestamp with time zone NOT NULL DEFAULT now(),
    CONSTRAINT auction_assignment_audit_action_valid
        CHECK (
            action IN (
                'BASELINE',
                'INSERT',
                'UPDATE',
                'DELETE'
            )
        )
);

CREATE INDEX auction_assignment_audit_identity_idx
    ON system.auction_pressing_assignment_audit_event (
        marketplace,
        listing_id,
        occurred_at DESC,
        id DESC
    );

CREATE FUNCTION system.reject_assignment_audit_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
BEGIN
    RAISE EXCEPTION
        'Auction pressing assignment audit history is immutable.';
END;
$function$;

CREATE TRIGGER auction_assignment_audit_immutable
BEFORE UPDATE OR DELETE
ON system.auction_pressing_assignment_audit_event
FOR EACH ROW
EXECUTE FUNCTION system.reject_assignment_audit_mutation();

CREATE FUNCTION system.capture_auction_pressing_assignment_audit()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
DECLARE
    resolved_actor text;
    resolved_reason text;
BEGIN
    resolved_actor := COALESCE(
        NULLIF(
            current_setting(
                'app.actor',
                true
            ),
            ''
        ),
        'UNKNOWN'
    );

    resolved_reason := NULLIF(
        current_setting(
            'app.reason',
            true
        ),
        ''
    );

    INSERT INTO system.auction_pressing_assignment_audit_event (
        marketplace,
        listing_id,
        pressing_id,
        action,
        before_state,
        after_state,
        actor,
        reason
    )
    VALUES (
        CASE
            WHEN TG_OP = 'DELETE'
            THEN OLD.marketplace
            ELSE NEW.marketplace
        END,
        CASE
            WHEN TG_OP = 'DELETE'
            THEN OLD.listing_id
            ELSE NEW.listing_id
        END,
        CASE
            WHEN TG_OP = 'DELETE'
            THEN OLD.pressing_id
            ELSE NEW.pressing_id
        END,
        TG_OP,
        CASE
            WHEN TG_OP IN (
                'UPDATE',
                'DELETE'
            )
            THEN to_jsonb(
                OLD
            )
            ELSE NULL
        END,
        CASE
            WHEN TG_OP IN (
                'INSERT',
                'UPDATE'
            )
            THEN to_jsonb(
                NEW
            )
            ELSE NULL
        END,
        resolved_actor,
        resolved_reason
    );

    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;

    RETURN NEW;
END;
$function$;

CREATE TRIGGER auction_pressing_assignment_audit
AFTER INSERT OR UPDATE OR DELETE
ON warehouse.auction_pressing_assignment
FOR EACH ROW
EXECUTE FUNCTION system.capture_auction_pressing_assignment_audit();

INSERT INTO system.auction_pressing_assignment_audit_event (
    marketplace,
    listing_id,
    pressing_id,
    action,
    before_state,
    after_state,
    actor,
    reason,
    occurred_at
)
SELECT
    assignment.marketplace,
    assignment.listing_id,
    assignment.pressing_id,
    'BASELINE',
    NULL,
    to_jsonb(
        assignment
    ),
    'MIGRATION',
    'Backfill the reviewed assignment baseline.',
    COALESCE(
        assignment.assigned_at,
        assignment.updated_at,
        now()
    )
FROM warehouse.auction_pressing_assignment
    AS assignment;

CREATE VIEW system.new_auction_assignment_queue AS
WITH auction_rows AS (
    SELECT
        auction_record.marketplace,
        auction_record.listing_id,
        to_jsonb(
            auction_record
        ) AS auction_payload
    FROM warehouse.auction AS auction_record
)
SELECT
    auction_rows.marketplace,
    auction_rows.listing_id,
    COALESCE(
        NULLIF(
            auction_rows.auction_payload
                ->> 'title',
            ''
        ),
        NULLIF(
            auction_rows.auction_payload
                ->> 'auction_title',
            ''
        ),
        NULLIF(
            auction_rows.auction_payload
                ->> 'listing_title',
            ''
        ),
        NULLIF(
            auction_rows.auction_payload
                ->> 'item_title',
            ''
        ),
        'Untitled auction'
    ) AS display_title,
    COALESCE(
        NULLIF(
            auction_rows.auction_payload
                ->> 'catalog_number',
            ''
        ),
        NULLIF(
            auction_rows.auction_payload
                ->> 'catalog',
            ''
        ),
        NULLIF(
            auction_rows.auction_payload
                ->> 'catalog_hint',
            ''
        )
    ) AS catalog_hint,
    COALESCE(
        NULLIF(
            auction_rows.auction_payload
                ->> 'url',
            ''
        ),
        NULLIF(
            auction_rows.auction_payload
                ->> 'auction_url',
            ''
        ),
        NULLIF(
            auction_rows.auction_payload
                ->> 'listing_url',
            ''
        ),
        NULLIF(
            auction_rows.auction_payload
                ->> 'source_url',
            ''
        )
    ) AS source_url,
    COALESCE(
        NULLIF(
            auction_rows.auction_payload
                ->> 'updated_at',
            ''
        ),
        NULLIF(
            auction_rows.auction_payload
                ->> 'ingested_at',
            ''
        ),
        NULLIF(
            auction_rows.auction_payload
                ->> 'fetched_at',
            ''
        ),
        NULLIF(
            auction_rows.auction_payload
                ->> 'created_at',
            ''
        )
    ) AS source_changed_at,
    'UNASSIGNED'::text AS queue_status,
    md5(
        auction_rows.marketplace
        || '|'
        || auction_rows.listing_id
    ) AS identity_fingerprint,
    auction_rows.auction_payload
FROM auction_rows
WHERE NOT EXISTS (
    SELECT 1
    FROM warehouse.auction_pressing_assignment
        AS assignment
    WHERE assignment.marketplace =
            auction_rows.marketplace
      AND assignment.listing_id =
            auction_rows.listing_id
);

CREATE VIEW system.listing_completeness_alert AS
WITH ordered_snapshots AS (
    SELECT
        snapshot_record.*,
        lag(
            snapshot_record.status
        ) OVER snapshot_window
            AS previous_status,
        lag(
            snapshot_record.pressing_id
        ) OVER snapshot_window
            AS previous_pressing_id,
        lag(
            snapshot_record.missing_components
        ) OVER snapshot_window
            AS previous_missing_components,
        row_number() OVER snapshot_window
            AS chronological_sequence
    FROM system.listing_completeness_snapshot
        AS snapshot_record
    WINDOW snapshot_window AS (
        PARTITION BY
            snapshot_record.marketplace,
            snapshot_record.listing_id
        ORDER BY
            snapshot_record.created_at,
            snapshot_record.id
    )
)
SELECT
    ordered_snapshots.id AS snapshot_id,
    ordered_snapshots.marketplace,
    ordered_snapshots.listing_id,
    ordered_snapshots.pressing_id,
    ordered_snapshots.media_type,
    ordered_snapshots.status,
    ordered_snapshots.previous_status,
    ordered_snapshots.required_component_count,
    ordered_snapshots.required_unit_count,
    ordered_snapshots.verified_present_unit_count,
    ordered_snapshots.missing_required_unit_count,
    ordered_snapshots.unknown_observation_count,
    ordered_snapshots.missing_components,
    ordered_snapshots.blocking_reasons,
    ordered_snapshots.trigger_event,
    ordered_snapshots.actor,
    ordered_snapshots.reason,
    ordered_snapshots.created_at,
    CASE
        WHEN ordered_snapshots.chronological_sequence = 1
        THEN 'INITIAL_BASELINE'
        WHEN ordered_snapshots.previous_pressing_id
            IS DISTINCT FROM ordered_snapshots.pressing_id
        THEN 'ASSIGNMENT_CHANGED'
        WHEN ordered_snapshots.status = 'COMPLETE'
         AND ordered_snapshots.previous_status
            IS DISTINCT FROM 'COMPLETE'
        THEN 'BECAME_COMPLETE'
        WHEN ordered_snapshots.previous_status = 'COMPLETE'
         AND ordered_snapshots.status
            IS DISTINCT FROM 'COMPLETE'
        THEN 'BECAME_INCOMPLETE'
        WHEN ordered_snapshots.status =
                'NO_VERIFIED_REFERENCE'
          OR ordered_snapshots.blocking_reasons
                ? 'NO_VERIFIED_REFERENCE'
        THEN 'REFERENCE_UNRESOLVED'
        WHEN ordered_snapshots.previous_missing_components
            IS DISTINCT FROM
                ordered_snapshots.missing_components
        THEN 'MISSING_COMPONENTS_CHANGED'
        ELSE 'SNAPSHOT_CHANGED'
    END AS alert_type,
    CASE
        WHEN ordered_snapshots.previous_status = 'COMPLETE'
         AND ordered_snapshots.status
            IS DISTINCT FROM 'COMPLETE'
        THEN 'CRITICAL'
        WHEN ordered_snapshots.status =
                'NO_VERIFIED_REFERENCE'
          OR ordered_snapshots.blocking_reasons
                ? 'NO_VERIFIED_REFERENCE'
        THEN 'WARNING'
        WHEN ordered_snapshots.previous_missing_components
            IS DISTINCT FROM
                ordered_snapshots.missing_components
         AND ordered_snapshots.chronological_sequence > 1
        THEN 'WARNING'
        ELSE 'INFO'
    END AS severity,
    jsonb_build_object(
        'previous_status',
            ordered_snapshots.previous_status,
        'current_status',
            ordered_snapshots.status,
        'previous_pressing_id',
            ordered_snapshots.previous_pressing_id,
        'current_pressing_id',
            ordered_snapshots.pressing_id,
        'previous_missing_components',
            ordered_snapshots.previous_missing_components,
        'current_missing_components',
            ordered_snapshots.missing_components,
        'trigger_event',
            ordered_snapshots.trigger_event
    ) AS alert_details
FROM ordered_snapshots;

CREATE VIEW system.current_listing_completeness_alert AS
SELECT DISTINCT ON (
    alert_record.marketplace,
    alert_record.listing_id
)
    alert_record.*
FROM system.listing_completeness_alert
    AS alert_record
ORDER BY
    alert_record.marketplace,
    alert_record.listing_id,
    alert_record.created_at DESC,
    alert_record.snapshot_id DESC;

CREATE VIEW system.completeness_cohort_summary AS
WITH latest_snapshots AS (
    SELECT DISTINCT ON (
        snapshot_record.marketplace,
        snapshot_record.listing_id
    )
        snapshot_record.*
    FROM system.listing_completeness_snapshot
        AS snapshot_record
    ORDER BY
        snapshot_record.marketplace,
        snapshot_record.listing_id,
        snapshot_record.created_at DESC,
        snapshot_record.id DESC
)
SELECT
    latest_snapshots.pressing_id,
    family.display_artist,
    family.display_title,
    pressing.catalog_number,
    latest_snapshots.media_type,
    latest_snapshots.status,
    COUNT(*)::integer AS listing_count,
    SUM(
        latest_snapshots.required_unit_count
    )::integer AS required_unit_count,
    SUM(
        latest_snapshots.verified_present_unit_count
    )::integer AS verified_present_unit_count,
    SUM(
        latest_snapshots.missing_required_unit_count
    )::integer AS missing_required_unit_count,
    SUM(
        latest_snapshots.unknown_observation_count
    )::integer AS unknown_observation_count
FROM latest_snapshots
LEFT JOIN warehouse.pressing_identity AS pressing
  ON pressing.id =
        latest_snapshots.pressing_id
LEFT JOIN warehouse.release_family AS family
  ON family.id =
        pressing.release_family_id
GROUP BY
    latest_snapshots.pressing_id,
    family.display_artist,
    family.display_title,
    pressing.catalog_number,
    latest_snapshots.media_type,
    latest_snapshots.status;
