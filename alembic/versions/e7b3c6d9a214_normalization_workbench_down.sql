DROP VIEW IF EXISTS
    analytics.normalization_work_queue;

DROP TRIGGER IF EXISTS
    auction_comparable_review_audit
ON warehouse.auction_comparable_review;

DROP TRIGGER IF EXISTS
    auction_analysis_input_audit
ON warehouse.auction_analysis_input;

DROP TRIGGER IF EXISTS
    auction_condition_normalization_audit
ON warehouse.auction_condition_normalization;

DROP TRIGGER IF EXISTS
    normalization_work_audit_immutable
ON system.normalization_work_audit_event;

DROP FUNCTION IF EXISTS
    system.capture_normalization_work_audit();

DROP FUNCTION IF EXISTS
    system.reject_normalization_audit_mutation();

DROP TABLE IF EXISTS
    warehouse.auction_comparable_review;

DROP TABLE IF EXISTS
    system.normalization_work_audit_event;

DROP TABLE IF EXISTS
    system.normalization_work_batch_row;

DROP TABLE IF EXISTS
    system.normalization_work_batch;
