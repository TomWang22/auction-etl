DROP TRIGGER IF EXISTS
    deterministic_verdict_rule_audit_capture
ON system.deterministic_verdict_rule;

DROP TRIGGER IF EXISTS
    deterministic_verdict_rule_audit_immutable
ON system.deterministic_verdict_rule_audit;

DROP FUNCTION IF EXISTS
    system.capture_verdict_rule_audit();

DROP FUNCTION IF EXISTS
    system.reject_verdict_rule_audit_mutation();

DROP TABLE IF EXISTS
    system.deterministic_verdict_rule_audit;

DROP TABLE IF EXISTS
    system.deterministic_verdict_rule;
