CREATE TABLE system.media_profile_component (
    media_type varchar(40) NOT NULL,
    component_code varchar(50) NOT NULL
        REFERENCES system.component_type (code)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,
    field_group varchar(120) NOT NULL,
    sort_order integer NOT NULL,
    active boolean NOT NULL DEFAULT true,
    notes text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (
        media_type,
        component_code
    ),
    CONSTRAINT media_profile_component_media_check
        CHECK (
            media_type ~ '^[A-Z0-9][A-Z0-9_]{0,39}$'
        ),
    CONSTRAINT media_profile_component_group_check
        CHECK (
            length(trim(field_group)) > 0
        ),
    CONSTRAINT media_profile_component_order_check
        CHECK (
            sort_order > 0
        )
);

CREATE INDEX media_profile_component_lookup_idx
    ON system.media_profile_component (
        media_type,
        active,
        sort_order,
        component_code
    );

COMMENT ON TABLE system.media_profile_component IS
    'Authoritative media-specific component applicability, grouping, and display order.';

CREATE TABLE system.media_profile_audit_event (
    id bigserial PRIMARY KEY,
    media_type varchar(40) NOT NULL,
    component_code varchar(50) NOT NULL,
    action varchar(30) NOT NULL,
    before_state jsonb,
    after_state jsonb,
    actor varchar(120) NOT NULL DEFAULT 'UNKNOWN',
    reason text,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT media_profile_audit_action_check
        CHECK (
            action IN (
                'INSERT',
                'UPDATE',
                'DELETE'
            )
        ),
    CONSTRAINT media_profile_audit_state_check
        CHECK (
            before_state IS NOT NULL
            OR after_state IS NOT NULL
        )
);

CREATE INDEX media_profile_audit_lookup_idx
    ON system.media_profile_audit_event (
        media_type,
        component_code,
        created_at DESC
    );

CREATE OR REPLACE FUNCTION system.reject_media_profile_audit_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $audit$
BEGIN
    RAISE EXCEPTION
        'system.media_profile_audit_event is immutable';
END
$audit$;

CREATE TRIGGER media_profile_audit_immutable
BEFORE UPDATE OR DELETE
ON system.media_profile_audit_event
FOR EACH ROW
EXECUTE FUNCTION system.reject_media_profile_audit_mutation();

CREATE OR REPLACE FUNCTION system.capture_media_profile_audit()
RETURNS trigger
LANGUAGE plpgsql
AS $audit$
DECLARE
    actor_value text;
    reason_value text;
BEGIN
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

    INSERT INTO system.media_profile_audit_event (
        media_type,
        component_code,
        action,
        before_state,
        after_state,
        actor,
        reason
    )
    VALUES (
        CASE
            WHEN TG_OP = 'DELETE'
            THEN OLD.media_type
            ELSE NEW.media_type
        END,
        CASE
            WHEN TG_OP = 'DELETE'
            THEN OLD.component_code
            ELSE NEW.component_code
        END,
        TG_OP,
        CASE
            WHEN TG_OP IN ('UPDATE', 'DELETE')
            THEN to_jsonb(OLD)
            ELSE NULL
        END,
        CASE
            WHEN TG_OP IN ('INSERT', 'UPDATE')
            THEN to_jsonb(NEW)
            ELSE NULL
        END,
        actor_value,
        reason_value
    );

    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;

    RETURN NEW;
END
$audit$;

CREATE TRIGGER media_profile_component_audit
AFTER INSERT OR UPDATE OR DELETE
ON system.media_profile_component
FOR EACH ROW
EXECUTE FUNCTION system.capture_media_profile_audit();

WITH expanded AS (
    SELECT
        component.code AS component_code,
        unnest(
            component.applicable_media
        ) AS media_type
    FROM system.component_type AS component
    WHERE component.active
),
classified AS (
    SELECT
        media_type,
        component_code,
        CASE
            WHEN media_type = 'LP'
             AND component_code IN (
                'OBI',
                'BOX',
                'SHRINK_WRAP',
                'STICKER'
             )
                THEN 'Identity and packaging'
            WHEN media_type = 'LP'
             AND component_code IN (
                'INSERT',
                'LYRIC_SHEET',
                'POSTER',
                'PINUP'
             )
                THEN 'Printed matter'
            WHEN media_type = 'LP'
                THEN 'Sleeves and additional media'
            WHEN media_type = 'CASSETTE'
             AND component_code IN (
                'J_CARD',
                'BOX',
                'SHRINK_WRAP',
                'STICKER'
             )
                THEN 'Primary packaging'
            WHEN media_type = 'CASSETTE'
                THEN 'Printed matter'
            WHEN media_type = 'CD'
             AND component_code IN (
                'OBI',
                'SHRINK_WRAP',
                'STICKER'
             )
                THEN 'Identity and packaging'
            WHEN media_type = 'CD'
             AND component_code = 'BONUS_MEDIA'
                THEN 'Additional media'
            WHEN media_type = 'CD'
                THEN 'Printed matter'
            WHEN media_type = 'CD_BOX_SET'
             AND component_code IN (
                'BOX',
                'OBI'
             )
                THEN 'Box-set packaging'
            WHEN media_type = 'CD_BOX_SET'
             AND component_code = 'BONUS_MEDIA'
                THEN 'Additional media'
            WHEN media_type = 'CD_BOX_SET'
                THEN 'Printed matter'
            WHEN media_type IN (
                'EP_7_INCH',
                'SINGLE_12_INCH'
             )
             AND component_code IN (
                'OBI',
                'INNER_SLEEVE'
             )
                THEN 'Identity and sleeves'
            WHEN media_type = 'EP_7_INCH'
                THEN 'Printed matter'
            WHEN media_type = 'LD'
             AND component_code IN (
                'BOX',
                'SHRINK_WRAP',
                'STICKER'
             )
                THEN 'Packaging'
            WHEN media_type = 'LD'
                THEN 'Printed matter'
            WHEN media_type = 'DVD'
             AND component_code = 'SHRINK_WRAP'
                THEN 'Packaging'
            WHEN media_type = 'DVD'
                THEN 'Printed matter and media'
            ELSE 'Applicable components'
        END AS field_group
    FROM expanded
),
ranked AS (
    SELECT
        media_type,
        component_code,
        field_group,
        row_number() OVER (
            PARTITION BY media_type
            ORDER BY
                field_group,
                component_code
        ) * 10 AS sort_order
    FROM classified
)
INSERT INTO system.media_profile_component (
    media_type,
    component_code,
    field_group,
    sort_order,
    active,
    notes
)
SELECT
    media_type,
    component_code,
    field_group,
    sort_order,
    true,
    (
        'Seeded from system.component_type.applicable_media. '
        'This is interface configuration, not collector evidence.'
    )
FROM ranked
ON CONFLICT (
    media_type,
    component_code
)
DO NOTHING;
