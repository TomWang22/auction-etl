DROP TRIGGER IF EXISTS
    media_profile_component_audit
ON system.media_profile_component;

DROP FUNCTION IF EXISTS
    system.capture_media_profile_audit();

DROP TRIGGER IF EXISTS
    media_profile_audit_immutable
ON system.media_profile_audit_event;

DROP FUNCTION IF EXISTS
    system.reject_media_profile_audit_mutation();

DROP TABLE IF EXISTS
    system.media_profile_audit_event;

DROP TABLE IF EXISTS
    system.media_profile_component;
