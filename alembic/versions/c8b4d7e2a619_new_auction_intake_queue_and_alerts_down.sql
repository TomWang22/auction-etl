DROP VIEW IF EXISTS
    system.completeness_cohort_summary;

DROP VIEW IF EXISTS
    system.current_listing_completeness_alert;

DROP VIEW IF EXISTS
    system.listing_completeness_alert;

DROP VIEW IF EXISTS
    system.new_auction_assignment_queue;

DROP TRIGGER IF EXISTS
    auction_pressing_assignment_audit
ON warehouse.auction_pressing_assignment;

DROP FUNCTION IF EXISTS
    system.capture_auction_pressing_assignment_audit();

DROP TRIGGER IF EXISTS
    auction_assignment_audit_immutable
ON system.auction_pressing_assignment_audit_event;

DROP FUNCTION IF EXISTS
    system.reject_assignment_audit_mutation();

DROP TABLE IF EXISTS
    system.auction_pressing_assignment_audit_event;
