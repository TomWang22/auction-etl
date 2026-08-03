DROP TRIGGER IF EXISTS
    evidence_attachment_audit
ON system.evidence_attachment;

DROP TRIGGER IF EXISTS
    evidence_source_registry_audit
ON system.evidence_source_registry;

DROP TRIGGER IF EXISTS
    auction_component_observation_audit
ON warehouse.auction_component_observation;

DROP TRIGGER IF EXISTS
    pressing_component_expectation_audit
ON warehouse.pressing_component_expectation;

DROP TRIGGER IF EXISTS
    reference_audit_event_immutable
ON system.reference_audit_event;

DROP FUNCTION IF EXISTS
    system.capture_reference_audit();

DROP FUNCTION IF EXISTS
    system.reject_reference_audit_mutation();

DROP TABLE IF EXISTS
    system.bulk_observation_batch_row;

DROP TABLE IF EXISTS
    system.bulk_observation_batch;

DROP TABLE IF EXISTS
    system.evidence_attachment;

DROP TABLE IF EXISTS
    system.reference_audit_event;
