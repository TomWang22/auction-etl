DROP TRIGGER IF EXISTS
    media_profile_component_completeness_snapshot
ON system.media_profile_component;

DROP TRIGGER IF EXISTS
    auction_component_observation_completeness_snapshot
ON warehouse.auction_component_observation;

DROP TRIGGER IF EXISTS
    pressing_component_expectation_completeness_snapshot
ON warehouse.pressing_component_expectation;

DROP TRIGGER IF EXISTS
    auction_pressing_assignment_completeness_snapshot
ON warehouse.auction_pressing_assignment;

DROP VIEW IF EXISTS
    system.listing_completeness_timeline;

DROP FUNCTION IF EXISTS
    system.capture_automatic_completeness_snapshot();

DROP TRIGGER IF EXISTS
    listing_completeness_snapshot_immutable
ON system.listing_completeness_snapshot;

DROP FUNCTION IF EXISTS
    system.reject_completeness_snapshot_mutation();

DROP FUNCTION IF EXISTS
    system.capture_listing_completeness_snapshot(
        text,
        text,
        text,
        text,
        jsonb,
        jsonb,
        jsonb,
        text,
        text,
        bigint
    );

DROP FUNCTION IF EXISTS
    system.listing_completeness_payload(
        text,
        text,
        bigint
    );

DROP FUNCTION IF EXISTS
    system.completeness_changed_fields(
        jsonb,
        jsonb
    );

DROP TABLE IF EXISTS
    system.listing_completeness_snapshot;
