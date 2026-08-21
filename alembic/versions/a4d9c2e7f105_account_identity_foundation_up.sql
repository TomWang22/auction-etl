CREATE SCHEMA IF NOT EXISTS identity;
CREATE SCHEMA IF NOT EXISTS account;

CREATE TABLE identity.app_user (
    id uuid PRIMARY KEY,
    provider text NOT NULL,
    subject text NOT NULL,
    email text NOT NULL,
    display_name text NOT NULL DEFAULT '',
    is_system_admin boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT app_user_provider_subject_key
        UNIQUE (provider, subject)
);

CREATE UNIQUE INDEX app_user_email_lower_idx
ON identity.app_user (lower(email));

CREATE TABLE identity.account (
    id uuid PRIMARY KEY,
    name text NOT NULL,
    account_type text NOT NULL DEFAULT 'personal',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT account_type_check
        CHECK (account_type IN ('personal', 'team'))
);

CREATE TABLE identity.account_member (
    account_id uuid NOT NULL
        REFERENCES identity.account(id)
        ON DELETE CASCADE,
    user_id uuid NOT NULL
        REFERENCES identity.app_user(id)
        ON DELETE CASCADE,
    role text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (account_id, user_id),
    CONSTRAINT account_member_role_check
        CHECK (role IN ('owner', 'admin', 'member'))
);

CREATE INDEX account_member_user_idx
ON identity.account_member (user_id, account_id);

CREATE TABLE account.auction_listing (
    account_id uuid NOT NULL
        REFERENCES identity.account(id)
        ON DELETE CASCADE,
    marketplace text NOT NULL,
    listing_id text NOT NULL,
    source_kind text NOT NULL DEFAULT 'review-surface',
    source_refresh_job_id uuid NULL,
    first_seen_at timestamptz NOT NULL DEFAULT now(),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (account_id, marketplace, listing_id),
    CONSTRAINT account_auction_listing_marketplace_check
        CHECK (marketplace IN ('buyee', 'ebay', 'gripsweat'))
);

CREATE INDEX account_auction_listing_identity_idx
ON account.auction_listing (
    marketplace,
    listing_id,
    account_id
);

CREATE TABLE account.tracked_artist (
    id uuid PRIMARY KEY,
    account_id uuid NOT NULL
        REFERENCES identity.account(id)
        ON DELETE CASCADE,
    name text NOT NULL,
    normalized_name text NOT NULL,
    enabled boolean NOT NULL DEFAULT true,
    legacy_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT tracked_artist_account_name_key
        UNIQUE (account_id, normalized_name)
);

CREATE TABLE account.artist_marketplace (
    tracked_artist_id uuid NOT NULL
        REFERENCES account.tracked_artist(id)
        ON DELETE CASCADE,
    marketplace text NOT NULL,
    enabled boolean NOT NULL DEFAULT true,
    search_query text NOT NULL DEFAULT '',
    search_url text NOT NULL DEFAULT '',
    config_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tracked_artist_id, marketplace),
    CONSTRAINT artist_marketplace_check
        CHECK (marketplace IN ('ebay', 'gripsweat'))
);

CREATE TABLE account.marketplace_connection (
    id uuid PRIMARY KEY,
    account_id uuid NOT NULL
        REFERENCES identity.account(id)
        ON DELETE CASCADE,
    marketplace text NOT NULL,
    status text NOT NULL DEFAULT 'not_configured',
    credential_reference text NOT NULL DEFAULT '',
    profile_reference text NOT NULL DEFAULT '',
    connected_at timestamptz NULL,
    last_verified_at timestamptz NULL,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT marketplace_connection_account_key
        UNIQUE (account_id, marketplace),
    CONSTRAINT marketplace_connection_marketplace_check
        CHECK (marketplace IN ('buyee', 'ebay', 'gripsweat')),
    CONSTRAINT marketplace_connection_status_check
        CHECK (
            status IN (
                'not_configured',
                'connected',
                'degraded',
                'disconnected'
            )
        )
);

ALTER TABLE ops.refresh_job
    ADD COLUMN IF NOT EXISTS account_id uuid NULL
        REFERENCES identity.account(id),
    ADD COLUMN IF NOT EXISTS requested_by_user_id uuid NULL
        REFERENCES identity.app_user(id);

CREATE INDEX IF NOT EXISTS refresh_job_account_created_idx
ON ops.refresh_job (account_id, created_at DESC);

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_class AS target_relation
        WHERE target_relation.oid = to_regclass('warehouse.auction_collector')
          AND target_relation.relkind IN ('r', 'p')
    ) THEN
        ALTER TABLE warehouse.auction_collector
            ADD COLUMN IF NOT EXISTS account_id uuid NULL
                REFERENCES identity.account(id);
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_class AS target_relation
        WHERE target_relation.oid = to_regclass('warehouse.auction_pressing_assignment')
          AND target_relation.relkind IN ('r', 'p')
    ) THEN
        ALTER TABLE warehouse.auction_pressing_assignment
            ADD COLUMN IF NOT EXISTS account_id uuid NULL
                REFERENCES identity.account(id);
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_class AS target_relation
        WHERE target_relation.oid = to_regclass('system.new_auction_assignment_queue')
          AND target_relation.relkind IN ('r', 'p')
    ) THEN
        ALTER TABLE system.new_auction_assignment_queue
            ADD COLUMN IF NOT EXISTS account_id uuid NULL
                REFERENCES identity.account(id);
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_class AS target_relation
        WHERE target_relation.oid = to_regclass('system.auction_pressing_assignment_audit_event')
          AND target_relation.relkind IN ('r', 'p')
    ) THEN
        ALTER TABLE system.auction_pressing_assignment_audit_event
            ADD COLUMN IF NOT EXISTS account_id uuid NULL
                REFERENCES identity.account(id);
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_class AS target_relation
        WHERE target_relation.oid = to_regclass('system.listing_completeness_snapshot')
          AND target_relation.relkind IN ('r', 'p')
    ) THEN
        ALTER TABLE system.listing_completeness_snapshot
            ADD COLUMN IF NOT EXISTS account_id uuid NULL
                REFERENCES identity.account(id);
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_class AS target_relation
        WHERE target_relation.oid = to_regclass('system.listing_completeness_timeline')
          AND target_relation.relkind IN ('r', 'p')
    ) THEN
        ALTER TABLE system.listing_completeness_timeline
            ADD COLUMN IF NOT EXISTS account_id uuid NULL
                REFERENCES identity.account(id);
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_class AS target_relation
        WHERE target_relation.oid = to_regclass('system.current_listing_completeness_alert')
          AND target_relation.relkind IN ('r', 'p')
    ) THEN
        ALTER TABLE system.current_listing_completeness_alert
            ADD COLUMN IF NOT EXISTS account_id uuid NULL
                REFERENCES identity.account(id);
    END IF;
END
$$;
