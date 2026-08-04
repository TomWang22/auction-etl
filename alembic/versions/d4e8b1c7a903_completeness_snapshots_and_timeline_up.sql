CREATE TABLE system.listing_completeness_snapshot (
    id bigserial PRIMARY KEY,
    marketplace varchar(80) NOT NULL,
    listing_id varchar(255) NOT NULL,
    pressing_id bigint,
    media_type varchar(50),
    status varchar(50) NOT NULL,
    required_component_count integer NOT NULL DEFAULT 0,
    required_unit_count integer NOT NULL DEFAULT 0,
    verified_present_unit_count integer NOT NULL DEFAULT 0,
    missing_required_unit_count integer NOT NULL DEFAULT 0,
    unknown_observation_count integer NOT NULL DEFAULT 0,
    missing_components jsonb NOT NULL DEFAULT '[]'::jsonb,
    blocking_reasons jsonb NOT NULL DEFAULT '[]'::jsonb,
    reference_fingerprint varchar(64) NOT NULL,
    observation_fingerprint varchar(64) NOT NULL,
    profile_fingerprint varchar(64) NOT NULL,
    snapshot_fingerprint varchar(64) NOT NULL,
    trigger_event varchar(60) NOT NULL,
    trigger_entity_type varchar(80) NOT NULL,
    trigger_entity_key jsonb NOT NULL DEFAULT '{}'::jsonb,
    source_before_state jsonb,
    source_after_state jsonb,
    source_changed_fields jsonb NOT NULL DEFAULT '{}'::jsonb,
    completeness_changed_fields jsonb NOT NULL DEFAULT '{}'::jsonb,
    actor varchar(120) NOT NULL DEFAULT 'UNKNOWN',
    reason text,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT listing_completeness_snapshot_status_check
        CHECK (
            status IN (
                'UNASSIGNED',
                'NO_VERIFIED_REFERENCE',
                'COMPLETE',
                'INCOMPLETE'
            )
        ),
    CONSTRAINT listing_completeness_snapshot_trigger_check
        CHECK (
            trigger_event IN (
                'BASELINE',
                'PRESSING_ASSIGNMENT_CHANGED',
                'MASTER_REFERENCE_CHANGED',
                'LISTING_OBSERVATION_CHANGED',
                'MEDIA_PROFILE_CHANGED',
                'MANUAL_REVIEW'
            )
        ),
    CONSTRAINT listing_completeness_snapshot_counts_check
        CHECK (
            required_component_count >= 0
            AND required_unit_count >= 0
            AND verified_present_unit_count >= 0
            AND missing_required_unit_count >= 0
            AND unknown_observation_count >= 0
        )
);

CREATE INDEX listing_completeness_snapshot_identity_idx
    ON system.listing_completeness_snapshot (
        marketplace,
        listing_id,
        created_at DESC,
        id DESC
    );

CREATE INDEX listing_completeness_snapshot_pressing_idx
    ON system.listing_completeness_snapshot (
        pressing_id,
        created_at DESC
    );

CREATE INDEX listing_completeness_snapshot_trigger_idx
    ON system.listing_completeness_snapshot (
        trigger_event,
        created_at DESC
    );

CREATE INDEX listing_completeness_snapshot_fingerprint_idx
    ON system.listing_completeness_snapshot (
        marketplace,
        listing_id,
        snapshot_fingerprint
    );

COMMENT ON TABLE system.listing_completeness_snapshot IS
    'Immutable derived history comparing auction listings with exact-pressing master references.';

CREATE OR REPLACE FUNCTION system.completeness_changed_fields(
    before_payload jsonb,
    after_payload jsonb
)
RETURNS jsonb
LANGUAGE sql
IMMUTABLE
AS $function$
    SELECT COALESCE(
        jsonb_object_agg(
            key_value.key,
            jsonb_build_object(
                'before',
                before_payload -> key_value.key,
                'after',
                after_payload -> key_value.key
            )
        ),
        '{}'::jsonb
    )
    FROM (
        SELECT key
        FROM jsonb_object_keys(
            COALESCE(
                before_payload,
                '{}'::jsonb
            )
        ) AS before_keys(key)

        UNION

        SELECT key
        FROM jsonb_object_keys(
            COALESCE(
                after_payload,
                '{}'::jsonb
            )
        ) AS after_keys(key)
    ) AS key_value
    WHERE (
        before_payload -> key_value.key
    ) IS DISTINCT FROM (
        after_payload -> key_value.key
    );
$function$;

CREATE OR REPLACE FUNCTION system.listing_completeness_payload(
    target_marketplace text,
    target_listing_id text,
    forced_pressing_id bigint DEFAULT NULL
)
RETURNS jsonb
LANGUAGE sql
STABLE
AS $function$
WITH target AS (
    SELECT
        assignment.pressing_id,
        pressing.media_type,
        false AS unassigned
    FROM warehouse.auction_pressing_assignment AS assignment
    JOIN warehouse.pressing_identity AS pressing
      ON pressing.id = assignment.pressing_id
    WHERE assignment.marketplace = target_marketplace
      AND assignment.listing_id = target_listing_id

    UNION ALL

    SELECT
        pressing.id AS pressing_id,
        pressing.media_type,
        true AS unassigned
    FROM warehouse.pressing_identity AS pressing
    WHERE pressing.id = forced_pressing_id
      AND NOT EXISTS (
          SELECT 1
          FROM warehouse.auction_pressing_assignment AS assignment
          WHERE assignment.marketplace = target_marketplace
            AND assignment.listing_id = target_listing_id
      )

    LIMIT 1
),
profile_rows AS (
    SELECT
        profile.component_code,
        jsonb_build_object(
            'component_code',
            profile.component_code,
            'active',
            COALESCE(
                CASE
                    WHEN lower(
                        COALESCE(
                            to_jsonb(profile) ->> 'active',
                            ''
                        )
                    ) IN ('true', 't', '1', 'yes')
                    THEN true
                    WHEN lower(
                        COALESCE(
                            to_jsonb(profile) ->> 'active',
                            ''
                        )
                    ) IN ('false', 'f', '0', 'no')
                    THEN false
                    ELSE NULL
                END,
                CASE
                    WHEN lower(
                        COALESCE(
                            to_jsonb(profile) ->> 'enabled',
                            ''
                        )
                    ) IN ('true', 't', '1', 'yes')
                    THEN true
                    WHEN lower(
                        COALESCE(
                            to_jsonb(profile) ->> 'enabled',
                            ''
                        )
                    ) IN ('false', 'f', '0', 'no')
                    THEN false
                    ELSE NULL
                END,
                true
            )
        ) AS fingerprint_payload
    FROM system.media_profile_component AS profile
    JOIN target
      ON target.media_type = profile.media_type
    WHERE COALESCE(
        CASE
            WHEN lower(
                COALESCE(
                    to_jsonb(profile) ->> 'active',
                    ''
                )
            ) IN ('true', 't', '1', 'yes')
            THEN true
            WHEN lower(
                COALESCE(
                    to_jsonb(profile) ->> 'active',
                    ''
                )
            ) IN ('false', 'f', '0', 'no')
            THEN false
            ELSE NULL
        END,
        CASE
            WHEN lower(
                COALESCE(
                    to_jsonb(profile) ->> 'enabled',
                    ''
                )
            ) IN ('true', 't', '1', 'yes')
            THEN true
            WHEN lower(
                COALESCE(
                    to_jsonb(profile) ->> 'enabled',
                    ''
                )
            ) IN ('false', 'f', '0', 'no')
            THEN false
            ELSE NULL
        END,
        true
    )
),
required_references AS (
    SELECT
        reference.id,
        reference.component_code,
        COALESCE(
            reference.variant_key,
            ''
        ) AS variant_key,
        reference.expected_quantity,
        jsonb_build_object(
            'component_code',
            reference.component_code,
            'variant_key',
            COALESCE(
                reference.variant_key,
                ''
            ),
            'expected_quantity',
            reference.expected_quantity,
            'expectation_state',
            reference.expectation_state
        ) AS fingerprint_payload
    FROM warehouse.pressing_component_expectation AS reference
    JOIN target
      ON target.pressing_id = reference.pressing_id
    JOIN profile_rows AS profile
      ON profile.component_code = reference.component_code
    WHERE reference.expectation_state = 'REQUIRED'
),
observation_source AS (
    SELECT
        to_jsonb(observation) AS payload
    FROM warehouse.auction_component_observation AS observation
    WHERE observation.marketplace = target_marketplace
      AND observation.listing_id = target_listing_id
),
observation_normalized AS (
    SELECT
        payload,
        COALESCE(
            payload ->> 'component_code',
            ''
        ) AS component_code,
        COALESCE(
            payload ->> 'variant_key',
            ''
        ) AS variant_key,
        upper(
            COALESCE(
                payload ->> 'observation_state',
                payload ->> 'presence_state',
                payload ->> 'component_state',
                payload ->> 'observed_state',
                payload ->> 'state',
                payload ->> 'status',
                ''
            )
        ) AS state_value,
        CASE
            WHEN COALESCE(
                payload ->> 'observed_quantity',
                payload ->> 'present_quantity',
                payload ->> 'quantity',
                ''
            ) ~ '^[0-9]+$'
            THEN (
                COALESCE(
                    payload ->> 'observed_quantity',
                    payload ->> 'present_quantity',
                    payload ->> 'quantity'
                )
            )::integer
            ELSE 1
        END AS observed_quantity,
        (
            lower(
                COALESCE(
                    payload ->> 'is_present',
                    payload ->> 'present',
                    ''
                )
            ) IN ('true', 't', '1', 'yes')
            OR upper(
                COALESCE(
                    payload ->> 'observation_state',
                    payload ->> 'presence_state',
                    payload ->> 'component_state',
                    payload ->> 'observed_state',
                    payload ->> 'state',
                    payload ->> 'status',
                    ''
                )
            ) IN (
                'PRESENT',
                'VERIFIED_PRESENT',
                'INCLUDED',
                'OBSERVED',
                'FOUND',
                'YES',
                'TRUE'
            )
        ) AS is_present,
        (
            lower(
                COALESCE(
                    payload ->> 'is_present',
                    payload ->> 'present',
                    ''
                )
            ) IN ('false', 'f', '0', 'no')
            OR upper(
                COALESCE(
                    payload ->> 'observation_state',
                    payload ->> 'presence_state',
                    payload ->> 'component_state',
                    payload ->> 'observed_state',
                    payload ->> 'state',
                    payload ->> 'status',
                    ''
                )
            ) IN (
                'ABSENT',
                'MISSING',
                'NOT_PRESENT',
                'NOT INCLUDED',
                'NO',
                'FALSE'
            )
        ) AS is_absent,
        jsonb_build_object(
            'component_code',
            COALESCE(
                payload ->> 'component_code',
                ''
            ),
            'variant_key',
            COALESCE(
                payload ->> 'variant_key',
                ''
            ),
            'state',
            upper(
                COALESCE(
                    payload ->> 'observation_state',
                    payload ->> 'presence_state',
                    payload ->> 'component_state',
                    payload ->> 'observed_state',
                    payload ->> 'state',
                    payload ->> 'status',
                    ''
                )
            ),
            'quantity',
            CASE
                WHEN COALESCE(
                    payload ->> 'observed_quantity',
                    payload ->> 'present_quantity',
                    payload ->> 'quantity',
                    ''
                ) ~ '^[0-9]+$'
                THEN (
                    COALESCE(
                        payload ->> 'observed_quantity',
                        payload ->> 'present_quantity',
                        payload ->> 'quantity'
                    )
                )::integer
                ELSE 1
            END
        ) AS fingerprint_payload
    FROM observation_source
),
reference_evaluation AS (
    SELECT
        reference.component_code,
        reference.variant_key,
        reference.expected_quantity,
        COALESCE(
            SUM(
                CASE
                    WHEN observation.is_present
                    THEN observation.observed_quantity
                    ELSE 0
                END
            ),
            0
        )::integer AS observed_quantity
    FROM required_references AS reference
    LEFT JOIN observation_normalized AS observation
      ON observation.component_code = reference.component_code
     AND observation.variant_key = reference.variant_key
    GROUP BY
        reference.id,
        reference.component_code,
        reference.variant_key,
        reference.expected_quantity
),
reference_statistics AS (
    SELECT
        COUNT(*)::integer AS required_component_count,
        COALESCE(
            SUM(
                expected_quantity
            ),
            0
        )::integer AS required_unit_count,
        COALESCE(
            SUM(
                LEAST(
                    expected_quantity,
                    observed_quantity
                )
            ),
            0
        )::integer AS verified_present_unit_count,
        COALESCE(
            SUM(
                GREATEST(
                    expected_quantity - observed_quantity,
                    0
                )
            ),
            0
        )::integer AS missing_required_unit_count,
        COALESCE(
            jsonb_agg(
                jsonb_build_object(
                    'component_code',
                    component_code,
                    'variant_key',
                    variant_key,
                    'expected_quantity',
                    expected_quantity,
                    'observed_quantity',
                    observed_quantity,
                    'missing_quantity',
                    GREATEST(
                        expected_quantity - observed_quantity,
                        0
                    )
                )
                ORDER BY
                    component_code,
                    variant_key
            ) FILTER (
                WHERE observed_quantity < expected_quantity
            ),
            '[]'::jsonb
        ) AS missing_components
    FROM reference_evaluation
),
unknown_statistics AS (
    SELECT
        COUNT(*)::integer AS unknown_observation_count
    FROM observation_normalized AS observation
    WHERE NOT observation.is_present
      AND NOT observation.is_absent
      AND EXISTS (
          SELECT 1
          FROM required_references AS reference
          WHERE reference.component_code =
                    observation.component_code
            AND reference.variant_key =
                    observation.variant_key
      )
),
fingerprints AS (
    SELECT
        md5(
            COALESCE(
                (
                    SELECT jsonb_agg(
                        fingerprint_payload
                        ORDER BY
                            component_code,
                            variant_key
                    )::text
                    FROM required_references
                ),
                '[]'
            )
        ) AS reference_fingerprint,
        md5(
            COALESCE(
                (
                    SELECT jsonb_agg(
                        fingerprint_payload
                        ORDER BY
                            component_code,
                            variant_key
                    )::text
                    FROM observation_normalized
                ),
                '[]'
            )
        ) AS observation_fingerprint,
        md5(
            COALESCE(
                (
                    SELECT jsonb_agg(
                        fingerprint_payload
                        ORDER BY component_code
                    )::text
                    FROM profile_rows
                ),
                '[]'
            )
        ) AS profile_fingerprint
),
semantic_payload AS (
    SELECT jsonb_build_object(
        'pressing_id',
        (
            SELECT pressing_id
            FROM target
        ),
        'media_type',
        (
            SELECT media_type
            FROM target
        ),
        'status',
        CASE
            WHEN NOT EXISTS (
                SELECT 1
                FROM target
            )
            OR COALESCE(
                (
                    SELECT unassigned
                    FROM target
                ),
                true
            )
            THEN 'UNASSIGNED'
            WHEN statistics.required_component_count = 0
            THEN 'NO_VERIFIED_REFERENCE'
            WHEN statistics.missing_required_unit_count = 0
            THEN 'COMPLETE'
            ELSE 'INCOMPLETE'
        END,
        'required_component_count',
        statistics.required_component_count,
        'required_unit_count',
        statistics.required_unit_count,
        'verified_present_unit_count',
        statistics.verified_present_unit_count,
        'missing_required_unit_count',
        statistics.missing_required_unit_count,
        'unknown_observation_count',
        unknowns.unknown_observation_count,
        'missing_components',
        statistics.missing_components,
        'blocking_reasons',
        (
            SELECT COALESCE(
                jsonb_agg(
                    reason
                ),
                '[]'::jsonb
            )
            FROM (
                VALUES
                    (
                        CASE
                            WHEN NOT EXISTS (
                                SELECT 1
                                FROM target
                            )
                            OR COALESCE(
                                (
                                    SELECT unassigned
                                    FROM target
                                ),
                                true
                            )
                            THEN 'UNASSIGNED'
                            ELSE NULL
                        END
                    ),
                    (
                        CASE
                            WHEN EXISTS (
                                SELECT 1
                                FROM target
                            )
                            AND NOT COALESCE(
                                (
                                    SELECT unassigned
                                    FROM target
                                ),
                                false
                            )
                            AND statistics.required_component_count = 0
                            THEN 'NO_VERIFIED_REFERENCE'
                            ELSE NULL
                        END
                    ),
                    (
                        CASE
                            WHEN statistics.missing_required_unit_count > 0
                            THEN 'MISSING_REQUIRED_COMPONENTS'
                            ELSE NULL
                        END
                    ),
                    (
                        CASE
                            WHEN unknowns.unknown_observation_count > 0
                            THEN 'UNKNOWN_OBSERVATIONS'
                            ELSE NULL
                        END
                    )
            ) AS reasons(reason)
            WHERE reason IS NOT NULL
        ),
        'reference_fingerprint',
        fingerprints.reference_fingerprint,
        'observation_fingerprint',
        fingerprints.observation_fingerprint,
        'profile_fingerprint',
        fingerprints.profile_fingerprint
    ) AS payload
    FROM reference_statistics AS statistics
    CROSS JOIN unknown_statistics AS unknowns
    CROSS JOIN fingerprints
)
SELECT
    payload
    || jsonb_build_object(
        'snapshot_fingerprint',
        md5(
            payload::text
        )
    )
FROM semantic_payload;
$function$;

CREATE OR REPLACE FUNCTION system.capture_listing_completeness_snapshot(
    target_marketplace text,
    target_listing_id text,
    trigger_event_value text,
    trigger_entity_type_value text,
    trigger_entity_key_value jsonb DEFAULT '{}'::jsonb,
    source_before_value jsonb DEFAULT NULL,
    source_after_value jsonb DEFAULT NULL,
    actor_value text DEFAULT NULL,
    reason_value text DEFAULT NULL,
    forced_pressing_id bigint DEFAULT NULL
)
RETURNS bigint
LANGUAGE plpgsql
AS $function$
DECLARE
    payload jsonb;
    latest_snapshot record;
    inserted_id bigint;
    resolved_actor text;
    resolved_reason text;
    source_diff jsonb;
    completeness_diff jsonb;
BEGIN
    payload := system.listing_completeness_payload(
        target_marketplace,
        target_listing_id,
        forced_pressing_id
    );

    resolved_actor := COALESCE(
        NULLIF(
            actor_value,
            ''
        ),
        NULLIF(
            current_setting(
                'auction_etl.actor',
                true
            ),
            ''
        ),
        'UNKNOWN'
    );

    resolved_reason := COALESCE(
        NULLIF(
            reason_value,
            ''
        ),
        NULLIF(
            current_setting(
                'auction_etl.reason',
                true
            ),
            ''
        )
    );

    SELECT *
    INTO latest_snapshot
    FROM system.listing_completeness_snapshot
    WHERE marketplace = target_marketplace
      AND listing_id = target_listing_id
    ORDER BY
        created_at DESC,
        id DESC
    LIMIT 1;

    IF latest_snapshot.id IS NOT NULL
       AND latest_snapshot.snapshot_fingerprint =
            payload ->> 'snapshot_fingerprint'
    THEN
        RETURN NULL;
    END IF;

    source_diff := system.completeness_changed_fields(
        source_before_value,
        source_after_value
    );

    completeness_diff :=
        system.completeness_changed_fields(
            CASE
                WHEN latest_snapshot.id IS NULL
                THEN NULL
                ELSE jsonb_build_object(
                    'pressing_id',
                    latest_snapshot.pressing_id,
                    'media_type',
                    latest_snapshot.media_type,
                    'status',
                    latest_snapshot.status,
                    'required_component_count',
                    latest_snapshot.required_component_count,
                    'required_unit_count',
                    latest_snapshot.required_unit_count,
                    'verified_present_unit_count',
                    latest_snapshot.verified_present_unit_count,
                    'missing_required_unit_count',
                    latest_snapshot.missing_required_unit_count,
                    'unknown_observation_count',
                    latest_snapshot.unknown_observation_count,
                    'missing_components',
                    latest_snapshot.missing_components,
                    'blocking_reasons',
                    latest_snapshot.blocking_reasons
                )
            END,
            jsonb_build_object(
                'pressing_id',
                payload -> 'pressing_id',
                'media_type',
                payload -> 'media_type',
                'status',
                payload -> 'status',
                'required_component_count',
                payload -> 'required_component_count',
                'required_unit_count',
                payload -> 'required_unit_count',
                'verified_present_unit_count',
                payload -> 'verified_present_unit_count',
                'missing_required_unit_count',
                payload -> 'missing_required_unit_count',
                'unknown_observation_count',
                payload -> 'unknown_observation_count',
                'missing_components',
                payload -> 'missing_components',
                'blocking_reasons',
                payload -> 'blocking_reasons'
            )
        );

    INSERT INTO system.listing_completeness_snapshot (
        marketplace,
        listing_id,
        pressing_id,
        media_type,
        status,
        required_component_count,
        required_unit_count,
        verified_present_unit_count,
        missing_required_unit_count,
        unknown_observation_count,
        missing_components,
        blocking_reasons,
        reference_fingerprint,
        observation_fingerprint,
        profile_fingerprint,
        snapshot_fingerprint,
        trigger_event,
        trigger_entity_type,
        trigger_entity_key,
        source_before_state,
        source_after_state,
        source_changed_fields,
        completeness_changed_fields,
        actor,
        reason
    )
    VALUES (
        target_marketplace,
        target_listing_id,
        NULLIF(
            payload ->> 'pressing_id',
            ''
        )::bigint,
        payload ->> 'media_type',
        payload ->> 'status',
        (
            payload ->> 'required_component_count'
        )::integer,
        (
            payload ->> 'required_unit_count'
        )::integer,
        (
            payload ->> 'verified_present_unit_count'
        )::integer,
        (
            payload ->> 'missing_required_unit_count'
        )::integer,
        (
            payload ->> 'unknown_observation_count'
        )::integer,
        payload -> 'missing_components',
        payload -> 'blocking_reasons',
        payload ->> 'reference_fingerprint',
        payload ->> 'observation_fingerprint',
        payload ->> 'profile_fingerprint',
        payload ->> 'snapshot_fingerprint',
        trigger_event_value,
        trigger_entity_type_value,
        COALESCE(
            trigger_entity_key_value,
            '{}'::jsonb
        ),
        source_before_value,
        source_after_value,
        COALESCE(
            source_diff,
            '{}'::jsonb
        ),
        COALESCE(
            completeness_diff,
            '{}'::jsonb
        ),
        resolved_actor,
        resolved_reason
    )
    RETURNING id
    INTO inserted_id;

    RETURN inserted_id;
END
$function$;

CREATE OR REPLACE FUNCTION system.reject_completeness_snapshot_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
BEGIN
    RAISE EXCEPTION
        'system.listing_completeness_snapshot is immutable';
END
$function$;

CREATE TRIGGER listing_completeness_snapshot_immutable
BEFORE UPDATE OR DELETE
ON system.listing_completeness_snapshot
FOR EACH ROW
EXECUTE FUNCTION system.reject_completeness_snapshot_mutation();

CREATE OR REPLACE FUNCTION system.capture_automatic_completeness_snapshot()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
DECLARE
    before_payload jsonb;
    after_payload jsonb;
    selected_pressing_id bigint;
    selected_media_type text;
    selected_marketplace text;
    selected_listing_id text;
    listing_record record;
    actor_value text;
    reason_value text;
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

    IF (
        TG_TABLE_SCHEMA = 'warehouse'
        AND TG_TABLE_NAME = 'auction_pressing_assignment'
    ) THEN
        IF TG_OP IN ('UPDATE', 'DELETE') THEN
            PERFORM system.capture_listing_completeness_snapshot(
                OLD.marketplace,
                OLD.listing_id,
                'PRESSING_ASSIGNMENT_CHANGED',
                'AUCTION_PRESSING_ASSIGNMENT',
                jsonb_build_object(
                    'marketplace',
                    OLD.marketplace,
                    'listing_id',
                    OLD.listing_id,
                    'pressing_id',
                    OLD.pressing_id
                ),
                before_payload,
                after_payload,
                actor_value,
                reason_value,
                OLD.pressing_id
            );
        END IF;

        IF TG_OP IN ('INSERT', 'UPDATE') THEN
            PERFORM system.capture_listing_completeness_snapshot(
                NEW.marketplace,
                NEW.listing_id,
                'PRESSING_ASSIGNMENT_CHANGED',
                'AUCTION_PRESSING_ASSIGNMENT',
                jsonb_build_object(
                    'marketplace',
                    NEW.marketplace,
                    'listing_id',
                    NEW.listing_id,
                    'pressing_id',
                    NEW.pressing_id
                ),
                before_payload,
                after_payload,
                actor_value,
                reason_value,
                NEW.pressing_id
            );
        END IF;

    ELSIF (
        TG_TABLE_SCHEMA = 'warehouse'
        AND TG_TABLE_NAME = 'pressing_component_expectation'
    ) THEN
        selected_pressing_id :=
            CASE
                WHEN TG_OP = 'DELETE'
                THEN OLD.pressing_id
                ELSE NEW.pressing_id
            END;

        FOR listing_record IN
            SELECT
                assignment.marketplace,
                assignment.listing_id
            FROM warehouse.auction_pressing_assignment AS assignment
            WHERE assignment.pressing_id = selected_pressing_id
        LOOP
            PERFORM system.capture_listing_completeness_snapshot(
                listing_record.marketplace,
                listing_record.listing_id,
                'MASTER_REFERENCE_CHANGED',
                'PRESSING_COMPONENT_EXPECTATION',
                jsonb_build_object(
                    'pressing_id',
                    selected_pressing_id,
                    'component_code',
                    COALESCE(
                        after_payload -> 'component_code',
                        before_payload -> 'component_code'
                    ),
                    'variant_key',
                    COALESCE(
                        after_payload -> 'variant_key',
                        before_payload -> 'variant_key'
                    )
                ),
                before_payload,
                after_payload,
                actor_value,
                reason_value,
                selected_pressing_id
            );
        END LOOP;

    ELSIF (
        TG_TABLE_SCHEMA = 'warehouse'
        AND TG_TABLE_NAME = 'auction_component_observation'
    ) THEN
        IF TG_OP IN ('UPDATE', 'DELETE') THEN
            PERFORM system.capture_listing_completeness_snapshot(
                OLD.marketplace,
                OLD.listing_id,
                'LISTING_OBSERVATION_CHANGED',
                'AUCTION_COMPONENT_OBSERVATION',
                jsonb_build_object(
                    'marketplace',
                    OLD.marketplace,
                    'listing_id',
                    OLD.listing_id,
                    'component_code',
                    OLD.component_code,
                    'variant_key',
                    OLD.variant_key
                ),
                before_payload,
                after_payload,
                actor_value,
                reason_value,
                NULL
            );
        END IF;

        IF TG_OP IN ('INSERT', 'UPDATE')
           AND (
               TG_OP = 'INSERT'
               OR NEW.marketplace IS DISTINCT FROM OLD.marketplace
               OR NEW.listing_id IS DISTINCT FROM OLD.listing_id
           )
        THEN
            PERFORM system.capture_listing_completeness_snapshot(
                NEW.marketplace,
                NEW.listing_id,
                'LISTING_OBSERVATION_CHANGED',
                'AUCTION_COMPONENT_OBSERVATION',
                jsonb_build_object(
                    'marketplace',
                    NEW.marketplace,
                    'listing_id',
                    NEW.listing_id,
                    'component_code',
                    NEW.component_code,
                    'variant_key',
                    NEW.variant_key
                ),
                before_payload,
                after_payload,
                actor_value,
                reason_value,
                NULL
            );
        END IF;

    ELSIF (
        TG_TABLE_SCHEMA = 'system'
        AND TG_TABLE_NAME = 'media_profile_component'
    ) THEN
        selected_media_type :=
            CASE
                WHEN TG_OP = 'DELETE'
                THEN OLD.media_type
                ELSE NEW.media_type
            END;

        FOR listing_record IN
            SELECT
                assignment.marketplace,
                assignment.listing_id,
                assignment.pressing_id
            FROM warehouse.auction_pressing_assignment AS assignment
            JOIN warehouse.pressing_identity AS pressing
              ON pressing.id = assignment.pressing_id
            WHERE pressing.media_type = selected_media_type
        LOOP
            PERFORM system.capture_listing_completeness_snapshot(
                listing_record.marketplace,
                listing_record.listing_id,
                'MEDIA_PROFILE_CHANGED',
                'MEDIA_PROFILE_COMPONENT',
                jsonb_build_object(
                    'media_type',
                    selected_media_type,
                    'component_code',
                    COALESCE(
                        after_payload -> 'component_code',
                        before_payload -> 'component_code'
                    )
                ),
                before_payload,
                after_payload,
                actor_value,
                reason_value,
                listing_record.pressing_id
            );
        END LOOP;

    ELSE
        RAISE EXCEPTION USING MESSAGE =
            'Unsupported completeness snapshot source '
            || TG_TABLE_SCHEMA
            || '.'
            || TG_TABLE_NAME;
    END IF;

    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;

    RETURN NEW;
END
$function$;

CREATE TRIGGER auction_pressing_assignment_completeness_snapshot
AFTER INSERT OR UPDATE OR DELETE
ON warehouse.auction_pressing_assignment
FOR EACH ROW
EXECUTE FUNCTION system.capture_automatic_completeness_snapshot();

CREATE TRIGGER pressing_component_expectation_completeness_snapshot
AFTER INSERT OR UPDATE OR DELETE
ON warehouse.pressing_component_expectation
FOR EACH ROW
EXECUTE FUNCTION system.capture_automatic_completeness_snapshot();

CREATE TRIGGER auction_component_observation_completeness_snapshot
AFTER INSERT OR UPDATE OR DELETE
ON warehouse.auction_component_observation
FOR EACH ROW
EXECUTE FUNCTION system.capture_automatic_completeness_snapshot();

CREATE TRIGGER media_profile_component_completeness_snapshot
AFTER INSERT OR UPDATE OR DELETE
ON system.media_profile_component
FOR EACH ROW
EXECUTE FUNCTION system.capture_automatic_completeness_snapshot();

CREATE OR REPLACE VIEW system.listing_completeness_timeline AS
WITH ordered AS (
    SELECT
        snapshot.*,
        lag(snapshot.id) OVER identity_window
            AS previous_snapshot_id,
        lag(snapshot.status) OVER identity_window
            AS previous_status,
        lag(snapshot.required_component_count) OVER identity_window
            AS previous_required_component_count,
        lag(snapshot.required_unit_count) OVER identity_window
            AS previous_required_unit_count,
        lag(snapshot.verified_present_unit_count) OVER identity_window
            AS previous_verified_present_unit_count,
        lag(snapshot.missing_required_unit_count) OVER identity_window
            AS previous_missing_required_unit_count,
        lag(snapshot.unknown_observation_count) OVER identity_window
            AS previous_unknown_observation_count,
        lag(snapshot.missing_components) OVER identity_window
            AS previous_missing_components,
        lag(snapshot.blocking_reasons) OVER identity_window
            AS previous_blocking_reasons
    FROM system.listing_completeness_snapshot AS snapshot
    WINDOW identity_window AS (
        PARTITION BY
            snapshot.marketplace,
            snapshot.listing_id
        ORDER BY
            snapshot.created_at,
            snapshot.id
    )
)
SELECT
    id AS event_id,
    previous_snapshot_id,
    marketplace,
    listing_id,
    pressing_id,
    media_type,
    created_at AS occurred_at,
    trigger_event AS event_type,
    trigger_entity_type AS source_entity_type,
    trigger_entity_key AS source_entity_key,
    actor,
    reason,
    source_before_state,
    source_after_state,
    source_changed_fields,
    previous_status AS status_before,
    status AS status_after,
    previous_required_component_count,
    required_component_count,
    previous_required_unit_count,
    required_unit_count,
    previous_verified_present_unit_count,
    verified_present_unit_count,
    previous_missing_required_unit_count,
    missing_required_unit_count,
    previous_unknown_observation_count,
    unknown_observation_count,
    previous_missing_components,
    missing_components,
    previous_blocking_reasons,
    blocking_reasons,
    completeness_changed_fields,
    snapshot_fingerprint
FROM ordered;

COMMENT ON VIEW system.listing_completeness_timeline IS
    'Chronological source and completeness differences for each assigned auction listing.';

SELECT system.capture_listing_completeness_snapshot(
    assignment.marketplace,
    assignment.listing_id,
    'BASELINE',
    'MIGRATION_BASELINE',
    jsonb_build_object(
        'marketplace',
        assignment.marketplace,
        'listing_id',
        assignment.listing_id,
        'pressing_id',
        assignment.pressing_id
    ),
    NULL,
    to_jsonb(assignment),
    'MIGRATION',
    'Create the initial derived completeness snapshot.',
    assignment.pressing_id
)
FROM warehouse.auction_pressing_assignment AS assignment;
