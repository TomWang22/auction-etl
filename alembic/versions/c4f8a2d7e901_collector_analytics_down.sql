DROP VIEW IF EXISTS analytics.auction_alerts;
DROP VIEW IF EXISTS analytics.emotional_damage;
DROP VIEW IF EXISTS analytics.obi_variant_price_summary;
DROP VIEW IF EXISTS analytics.obi_premium;
DROP VIEW IF EXISTS analytics.completeness_premium;
DROP VIEW IF EXISTS analytics.midfication_detection;
DROP VIEW IF EXISTS analytics.auction_scores;
DROP FUNCTION IF EXISTS analytics.comparable_confidence(
    text,
    text,
    text,
    text
);
DROP VIEW IF EXISTS analytics.pressing_assignment_queue;
DROP VIEW IF EXISTS analytics.auction_collector_base;
DROP VIEW IF EXISTS warehouse.auction_completeness;

DROP TABLE IF EXISTS warehouse.auction_analysis_input;
DROP TABLE IF EXISTS warehouse.auction_event_context;
DROP TABLE IF EXISTS warehouse.listing_lineage_member;
DROP TABLE IF EXISTS warehouse.listing_lineage;
DROP TABLE IF EXISTS warehouse.auction_price_snapshot;
DROP TABLE IF EXISTS warehouse.auction_behavior_observation;
DROP TABLE IF EXISTS warehouse.auction_condition_normalization;
DROP TABLE IF EXISTS warehouse.auction_component_observation;
DROP TABLE IF EXISTS warehouse.pressing_component_expectation;
DROP TABLE IF EXISTS warehouse.auction_pressing_assignment;
DROP TABLE IF EXISTS warehouse.pressing_identity;
DROP TABLE IF EXISTS warehouse.release_family;
DROP TABLE IF EXISTS system.condition_grade;
DROP TABLE IF EXISTS system.component_type;
