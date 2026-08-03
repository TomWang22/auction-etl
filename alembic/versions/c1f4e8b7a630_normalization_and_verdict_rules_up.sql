CREATE TABLE system.deterministic_verdict_rule (
    id bigserial PRIMARY KEY,
    rule_code varchar(120) NOT NULL UNIQUE,
    display_name varchar(240) NOT NULL,
    category varchar(80) NOT NULL,
    metric_code varchar(160) NOT NULL,
    comparison_operator varchar(20) NOT NULL,
    threshold_low numeric,
    threshold_high numeric,
    minimum_sample_size integer NOT NULL DEFAULT 0,
    minimum_evidence_coverage numeric(6, 4)
        NOT NULL DEFAULT 0,
    severity varchar(30) NOT NULL,
    priority integer NOT NULL DEFAULT 100,
    verdict_label varchar(240) NOT NULL,
    verdict_message text NOT NULL,
    active boolean NOT NULL DEFAULT true,
    effective_from timestamptz,
    effective_to timestamptz,
    notes text,
    created_by varchar(120) NOT NULL DEFAULT 'SYSTEM',
    updated_by varchar(120) NOT NULL DEFAULT 'SYSTEM',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT deterministic_verdict_rule_operator_check
        CHECK (
            comparison_operator IN (
                'GT',
                'GTE',
                'LT',
                'LTE',
                'EQ',
                'NEQ',
                'BETWEEN'
            )
        ),
    CONSTRAINT deterministic_verdict_rule_severity_check
        CHECK (
            severity IN (
                'INFO',
                'LOW',
                'MODERATE',
                'HIGH',
                'CRITICAL'
            )
        ),
    CONSTRAINT deterministic_verdict_rule_sample_check
        CHECK (
            minimum_sample_size >= 0
        ),
    CONSTRAINT deterministic_verdict_rule_coverage_check
        CHECK (
            minimum_evidence_coverage >= 0
            AND minimum_evidence_coverage <= 1
        ),
    CONSTRAINT deterministic_verdict_rule_effective_check
        CHECK (
            effective_to IS NULL
            OR effective_from IS NULL
            OR effective_to > effective_from
        ),
    CONSTRAINT deterministic_verdict_rule_threshold_check
        CHECK (
            (
                comparison_operator = 'BETWEEN'
                AND threshold_low IS NOT NULL
                AND threshold_high IS NOT NULL
                AND threshold_high >= threshold_low
            )
            OR (
                comparison_operator <> 'BETWEEN'
                AND threshold_low IS NOT NULL
            )
        )
);

CREATE INDEX deterministic_verdict_rule_active_idx
    ON system.deterministic_verdict_rule (
        active,
        priority,
        rule_code
    );

CREATE INDEX deterministic_verdict_rule_metric_idx
    ON system.deterministic_verdict_rule (
        metric_code,
        active
    );

COMMENT ON TABLE system.deterministic_verdict_rule IS
    'Audited deterministic market, normalization, and collector verdict rules.';

CREATE TABLE system.deterministic_verdict_rule_audit (
    id bigserial PRIMARY KEY,
    rule_id bigint,
    rule_code varchar(120) NOT NULL,
    action varchar(20) NOT NULL,
    before_state jsonb,
    after_state jsonb,
    actor varchar(120) NOT NULL DEFAULT 'UNKNOWN',
    reason text,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT deterministic_verdict_rule_audit_action_check
        CHECK (
            action IN (
                'INSERT',
                'UPDATE',
                'DELETE'
            )
        ),
    CONSTRAINT deterministic_verdict_rule_audit_state_check
        CHECK (
            before_state IS NOT NULL
            OR after_state IS NOT NULL
        )
);

CREATE INDEX deterministic_verdict_rule_audit_rule_idx
    ON system.deterministic_verdict_rule_audit (
        rule_code,
        created_at DESC
    );

INSERT INTO system.deterministic_verdict_rule (
    rule_code,
    display_name,
    category,
    metric_code,
    comparison_operator,
    threshold_low,
    threshold_high,
    minimum_sample_size,
    minimum_evidence_coverage,
    severity,
    priority,
    verdict_label,
    verdict_message,
    active,
    notes
)
VALUES
    (
        'MARKET_EVIDENCE_INSUFFICIENT',
        'Market evidence insufficient',
        'DATA_QUALITY',
        'EVIDENCE_COVERAGE',
        'LT',
        0.5000,
        NULL,
        0,
        0,
        'INFO',
        5,
        'Insufficient evidence',
        'Evidence coverage is below the minimum required for a reliable market verdict.',
        true,
        'Suppresses stronger verdicts when evidence coverage is incomplete.'
    ),
    (
        'MARKET_NOISE_INSUFFICIENT_SAMPLE',
        'Market noise or insufficient sample',
        'DATA_QUALITY',
        'COMPARABLE_SAMPLE_SIZE',
        'LT',
        3,
        NULL,
        0,
        0,
        'INFO',
        10,
        'Market noise',
        'The comparable cohort is too small to distinguish a durable market pattern from ordinary pricing noise.',
        true,
        'A minimum of three comparable sales is required for structural interpretation.'
    ),
    (
        'REISSUE_MARKET_VISIBILITY',
        'Reissue market visibility',
        'REISSUE_MARKET',
        'REISSUE_TO_FIRST_PRESS_RATIO',
        'BETWEEN',
        0.6000,
        0.7999,
        3,
        0.5000,
        'LOW',
        30,
        'Reissue visibility',
        'The reissue is gaining measurable market visibility but remains below first-press price convergence.',
        true,
        'Professional replacement for informal low-level mid-price language.'
    ),
    (
        'REISSUE_PRICE_CONVERGENCE',
        'Reissue price convergence',
        'REISSUE_MARKET',
        'REISSUE_TO_FIRST_PRESS_RATIO',
        'BETWEEN',
        0.8000,
        0.9999,
        3,
        0.5000,
        'MODERATE',
        40,
        'Reissue price convergence',
        'The adjusted reissue price is approaching the adjusted first-press comparable level.',
        true,
        'Formal market term for a reissue approaching first-press pricing.'
    ),
    (
        'FIRST_PRESS_PRICE_PARITY',
        'First-press price parity',
        'REISSUE_MARKET',
        'REISSUE_TO_FIRST_PRESS_RATIO',
        'BETWEEN',
        1.0000,
        1.1999,
        3,
        0.5000,
        'HIGH',
        50,
        'First-press price parity',
        'The adjusted reissue result has reached or modestly exceeded the first-press comparable level.',
        true,
        'A parity condition rather than a colloquial breach label.'
    ),
    (
        'REISSUE_PRICE_CROSSOVER',
        'Reissue price crossover',
        'REISSUE_MARKET',
        'REISSUE_TO_FIRST_PRESS_RATIO',
        'GTE',
        1.2000,
        NULL,
        3,
        0.5000,
        'CRITICAL',
        60,
        'Reissue price crossover',
        'The adjusted reissue result materially exceeds the adjusted first-press comparable level.',
        true,
        'A professional replacement for an isolated midfication incident.'
    ),
    (
        'PERSISTENT_REISSUE_DISPLACEMENT',
        'Persistent reissue displacement',
        'REISSUE_MARKET',
        'REISSUE_CROSSOVER_COUNT',
        'GTE',
        3,
        NULL,
        3,
        0.5000,
        'CRITICAL',
        70,
        'Persistent reissue displacement',
        'Three or more qualified crossover results indicate a persistent pricing displacement rather than a single-sale anomaly.',
        true,
        'Structural condition requiring repeated qualified sales.'
    ),
    (
        'HISTORICAL_PRICE_OUTLIER',
        'Historical price outlier',
        'PRICE_ANOMALY',
        'FINAL_TO_HISTORICAL_MEDIAN_RATIO',
        'GTE',
        2.0000,
        NULL,
        3,
        0.5000,
        'HIGH',
        80,
        'Historical price outlier',
        'The final adjusted result is at least twice the qualified historical median.',
        true,
        'Requires normalized historical evidence.'
    ),
    (
        'CLOSING_WINDOW_ESCALATION',
        'Closing-window escalation',
        'AUCTION_DYNAMICS',
        'LATE_WINDOW_ESCALATION_RATIO',
        'GTE',
        0.7500,
        NULL,
        0,
        0.5000,
        'HIGH',
        90,
        'Closing-window escalation',
        'The final closing-window increase exceeded seventy-five percent.',
        true,
        'Requires timestamped closing-window evidence.'
    ),
    (
        'HIGH_AUCTION_IMPACT',
        'High auction impact',
        'AUCTION_DYNAMICS',
        'EMOTIONAL_DAMAGE_SCORE',
        'GTE',
        75,
        NULL,
        0,
        0.5000,
        'HIGH',
        100,
        'High auction impact',
        'The deterministic auction-impact score is elevated with sufficient evidence coverage.',
        true,
        'Professional display term for the legacy Emotional Damage score.'
    ),
    (
        'HIGH_COLLECTOR_SIGNIFICANCE',
        'High collector significance',
        'COLLECTOR_SIGNIFICANCE',
        'PLUSHIE_INDEX',
        'GTE',
        80,
        NULL,
        0,
        0,
        'HIGH',
        110,
        'High collector significance',
        'The combined title, completeness, condition, auction-behavior, and market-context score is eighty or higher.',
        true,
        'Professional display term for the legacy Plushie Index.'
    )
ON CONFLICT (rule_code) DO NOTHING;

CREATE OR REPLACE FUNCTION system.reject_verdict_rule_audit_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $audit$
BEGIN
    RAISE EXCEPTION
        'system.deterministic_verdict_rule_audit is immutable';
END
$audit$;

CREATE TRIGGER deterministic_verdict_rule_audit_immutable
BEFORE UPDATE OR DELETE
ON system.deterministic_verdict_rule_audit
FOR EACH ROW
EXECUTE FUNCTION system.reject_verdict_rule_audit_mutation();

CREATE OR REPLACE FUNCTION system.capture_verdict_rule_audit()
RETURNS trigger
LANGUAGE plpgsql
AS $audit$
DECLARE
    before_payload jsonb;
    after_payload jsonb;
    actor_value text;
    reason_value text;
    code_value text;
    id_value bigint;
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

    code_value := COALESCE(
        NEW.rule_code,
        OLD.rule_code
    );

    id_value := COALESCE(
        NEW.id,
        OLD.id
    );

    INSERT INTO system.deterministic_verdict_rule_audit (
        rule_id,
        rule_code,
        action,
        before_state,
        after_state,
        actor,
        reason
    )
    VALUES (
        id_value,
        code_value,
        TG_OP,
        before_payload,
        after_payload,
        actor_value,
        reason_value
    );

    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;

    RETURN NEW;
END
$audit$;

CREATE TRIGGER deterministic_verdict_rule_audit_capture
AFTER INSERT OR UPDATE OR DELETE
ON system.deterministic_verdict_rule
FOR EACH ROW
EXECUTE FUNCTION system.capture_verdict_rule_audit();
