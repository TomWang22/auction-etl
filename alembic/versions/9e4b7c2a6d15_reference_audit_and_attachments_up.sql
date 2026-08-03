-- evidence-source-key-repair:start
INSERT INTO system.evidence_source_registry (
    source_key,
    display_name,
    source_type,
    base_url,
    default_confidence,
    notes,
    active
)
SELECT
    'AUCTION_TITLE_STATES',
    display_name,
    source_type,
    base_url,
    default_confidence,
    notes,
    active
FROM system.evidence_source_registry
WHERE source_key = 'AUCTION_TITLE_STATES_'
ON CONFLICT (source_key) DO NOTHING;

UPDATE warehouse.pressing_component_expectation
SET evidence_source = 'AUCTION_TITLE_STATES'
WHERE evidence_source = 'AUCTION_TITLE_STATES_';

UPDATE warehouse.auction_component_observation
SET evidence_source = 'AUCTION_TITLE_STATES'
WHERE evidence_source = 'AUCTION_TITLE_STATES_';

DELETE FROM system.evidence_source_registry
WHERE source_key = 'AUCTION_TITLE_STATES_';
-- evidence-source-key-repair:end

CREATE TABLE system.reference_audit_event (
    id bigserial PRIMARY KEY,
    entity_type varchar(80) NOT NULL,
    entity_key jsonb NOT NULL,
    action varchar(30) NOT NULL,
    before_state jsonb,
    after_state jsonb,
    reason text,
    actor varchar(120) NOT NULL DEFAULT 'UNKNOWN',
    batch_id uuid,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT reference_audit_event_action_check
        CHECK (
            action IN (
                'INSERT',
                'UPDATE',
                'DELETE',
                'RESTORE'
            )
        ),
    CONSTRAINT reference_audit_event_state_check
        CHECK (
            before_state IS NOT NULL
            OR after_state IS NOT NULL
        )
);

CREATE INDEX reference_audit_event_entity_idx
    ON system.reference_audit_event (
        entity_type,
        created_at DESC
    );

CREATE INDEX reference_audit_event_batch_idx
    ON system.reference_audit_event (
        batch_id,
        created_at
    )
    WHERE batch_id IS NOT NULL;

CREATE INDEX reference_audit_event_key_gin_idx
    ON system.reference_audit_event
    USING gin (entity_key);

COMMENT ON TABLE system.reference_audit_event IS
    'Immutable change history for collector reference and evidence entities.';

CREATE TABLE system.evidence_attachment (
    id bigserial PRIMARY KEY,
    entity_type varchar(80) NOT NULL,
    entity_key jsonb NOT NULL,
    source_key varchar(80)
        REFERENCES system.evidence_source_registry (
            source_key
        )
        ON UPDATE CASCADE
        ON DELETE RESTRICT,
    attachment_kind varchar(50) NOT NULL,
    uri text NOT NULL,
    sha256 varchar(64) NOT NULL,
    mime_type varchar(120),
    captured_at timestamptz,
    page_reference varchar(120),
    notes text,
    active boolean NOT NULL DEFAULT true,
    created_by varchar(120) NOT NULL DEFAULT 'UNKNOWN',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT evidence_attachment_sha256_check
        CHECK (
            sha256 ~ '^[0-9a-fA-F]{64}$'
        ),
    CONSTRAINT evidence_attachment_kind_check
        CHECK (
            attachment_kind IN (
                'URL',
                'IMAGE',
                'PDF',
                'CATALOG_SCAN',
                'LISTING_CAPTURE',
                'PHYSICAL_COPY',
                'ARCHIVE_FILE',
                'OTHER'
            )
        )
);

CREATE INDEX evidence_attachment_entity_idx
    ON system.evidence_attachment (
        entity_type,
        active,
        created_at DESC
    );

CREATE INDEX evidence_attachment_key_gin_idx
    ON system.evidence_attachment
    USING gin (entity_key);

CREATE UNIQUE INDEX evidence_attachment_active_identity_idx
    ON system.evidence_attachment (
        entity_type,
        md5(entity_key::text),
        sha256,
        uri
    )
    WHERE active;

COMMENT ON TABLE system.evidence_attachment IS
    'Attachment metadata only; files are referenced by URI and checksum.';

CREATE TABLE system.bulk_observation_batch (
    id uuid PRIMARY KEY,
    filename text,
    uploaded_sha256 varchar(64) NOT NULL,
    overwrite_existing boolean NOT NULL DEFAULT false,
    actor varchar(120) NOT NULL,
    reason text NOT NULL,
    status varchar(30) NOT NULL,
    requested_row_count integer NOT NULL DEFAULT 0,
    inserted_row_count integer NOT NULL DEFAULT 0,
    overwritten_row_count integer NOT NULL DEFAULT 0,
    rejected_row_count integer NOT NULL DEFAULT 0,
    touched_listing_count integer NOT NULL DEFAULT 0,
    validation_summary jsonb NOT NULL DEFAULT '{}'::jsonb,
    error_message text,
    created_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz,
    CONSTRAINT bulk_observation_batch_sha256_check
        CHECK (
            uploaded_sha256 ~ '^[0-9a-fA-F]{64}$'
        ),
    CONSTRAINT bulk_observation_batch_status_check
        CHECK (
            status IN (
                'RUNNING',
                'COMPLETED',
                'FAILED'
            )
        )
);

CREATE INDEX bulk_observation_batch_created_idx
    ON system.bulk_observation_batch (
        created_at DESC
    );

CREATE TABLE system.bulk_observation_batch_row (
    id bigserial PRIMARY KEY,
    batch_id uuid NOT NULL
        REFERENCES system.bulk_observation_batch (id)
        ON DELETE CASCADE,
    row_number integer NOT NULL,
    marketplace varchar(80) NOT NULL,
    listing_id varchar(255) NOT NULL,
    component_code varchar(50) NOT NULL,
    variant_key varchar(120) NOT NULL DEFAULT '',
    outcome varchar(30) NOT NULL,
    before_state jsonb,
    after_state jsonb,
    error_message text,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT bulk_observation_batch_row_outcome_check
        CHECK (
            outcome IN (
                'INSERTED',
                'OVERWRITTEN',
                'REJECTED',
                'SKIPPED'
            )
        )
);

CREATE INDEX bulk_observation_batch_row_batch_idx
    ON system.bulk_observation_batch_row (
        batch_id,
        row_number
    );

CREATE OR REPLACE FUNCTION system.reject_reference_audit_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $audit$
BEGIN
    RAISE EXCEPTION
        'system.reference_audit_event is immutable';
END
$audit$;

CREATE TRIGGER reference_audit_event_immutable
BEFORE UPDATE OR DELETE
ON system.reference_audit_event
FOR EACH ROW
EXECUTE FUNCTION system.reject_reference_audit_mutation();

CREATE OR REPLACE FUNCTION system.capture_reference_audit()
RETURNS trigger
LANGUAGE plpgsql
AS $audit$
DECLARE
    before_payload jsonb;
    after_payload jsonb;
    key_payload jsonb;
    entity_type_value text;
    action_value text;
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

    IF (
        TG_TABLE_SCHEMA = 'warehouse'
        AND TG_TABLE_NAME =
            'pressing_component_expectation'
    ) THEN
        entity_type_value :=
            'PRESSING_COMPONENT_EXPECTATION';

        key_payload := jsonb_build_object(
            'id',
            COALESCE(
                after_payload -> 'id',
                before_payload -> 'id'
            ),
            'pressing_id',
            COALESCE(
                after_payload -> 'pressing_id',
                before_payload -> 'pressing_id'
            ),
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
        );
    ELSIF (
        TG_TABLE_SCHEMA = 'warehouse'
        AND TG_TABLE_NAME =
            'auction_component_observation'
    ) THEN
        entity_type_value :=
            'AUCTION_COMPONENT_OBSERVATION';

        key_payload := jsonb_build_object(
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
        );
    ELSIF (
        TG_TABLE_SCHEMA = 'system'
        AND TG_TABLE_NAME =
            'evidence_source_registry'
    ) THEN
        entity_type_value := 'EVIDENCE_SOURCE';

        key_payload := jsonb_build_object(
            'source_key',
            COALESCE(
                after_payload -> 'source_key',
                before_payload -> 'source_key'
            )
        );
    ELSIF (
        TG_TABLE_SCHEMA = 'system'
        AND TG_TABLE_NAME = 'evidence_attachment'
    ) THEN
        entity_type_value := 'EVIDENCE_ATTACHMENT';

        key_payload := jsonb_build_object(
            'id',
            COALESCE(
                after_payload -> 'id',
                before_payload -> 'id'
            ),
            'entity_type',
            COALESCE(
                after_payload -> 'entity_type',
                before_payload -> 'entity_type'
            ),
            'entity_key',
            COALESCE(
                after_payload -> 'entity_key',
                before_payload -> 'entity_key'
            )
        );
    ELSE
        RAISE EXCEPTION
            'Unsupported audited table %%.%%',
            TG_TABLE_SCHEMA,
            TG_TABLE_NAME;
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

    action_value := COALESCE(
        NULLIF(
            current_setting(
                'auction_etl.audit_action',
                true
            ),
            ''
        ),
        TG_OP
    );

    batch_text := NULLIF(
        current_setting(
            'auction_etl.batch_id',
            true
        ),
        ''
    );

    IF batch_text IS NOT NULL THEN
        batch_value := batch_text::uuid;
    ELSE
        batch_value := NULL;
    END IF;

    INSERT INTO system.reference_audit_event (
        entity_type,
        entity_key,
        action,
        before_state,
        after_state,
        reason,
        actor,
        batch_id
    )
    VALUES (
        entity_type_value,
        key_payload,
        action_value,
        before_payload,
        after_payload,
        reason_value,
        actor_value,
        batch_value
    );

    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;

    RETURN NEW;
END
$audit$;

CREATE TRIGGER pressing_component_expectation_audit
AFTER INSERT OR UPDATE OR DELETE
ON warehouse.pressing_component_expectation
FOR EACH ROW
EXECUTE FUNCTION system.capture_reference_audit();

CREATE TRIGGER auction_component_observation_audit
AFTER INSERT OR UPDATE OR DELETE
ON warehouse.auction_component_observation
FOR EACH ROW
EXECUTE FUNCTION system.capture_reference_audit();

CREATE TRIGGER evidence_source_registry_audit
AFTER INSERT OR UPDATE OR DELETE
ON system.evidence_source_registry
FOR EACH ROW
EXECUTE FUNCTION system.capture_reference_audit();

CREATE TRIGGER evidence_attachment_audit
AFTER INSERT OR UPDATE OR DELETE
ON system.evidence_attachment
FOR EACH ROW
EXECUTE FUNCTION system.capture_reference_audit();
