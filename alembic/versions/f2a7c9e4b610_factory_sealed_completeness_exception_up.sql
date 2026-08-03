CREATE OR REPLACE VIEW warehouse.auction_completeness AS
WITH active_component_count AS (
    SELECT
        COUNT(*) AS component_count
    FROM system.component_type
    WHERE active
),
reference_summary AS (
    SELECT
        pressing.id AS pressing_id,
        COUNT(
            DISTINCT expectation.component_code
        ) AS configured_component_count,
        COUNT(*) FILTER (
            WHERE expectation.expectation_state = 'REQUIRED'
        ) AS required_reference_count,
        COUNT(*) FILTER (
            WHERE expectation.expectation_state = 'UNKNOWN'
        ) AS unknown_reference_count
    FROM warehouse.pressing_identity AS pressing
    LEFT JOIN warehouse.pressing_component_expectation
        AS expectation
      ON expectation.pressing_id = pressing.id
    GROUP BY pressing.id
),
reference_coverage AS (
    SELECT
        summary.pressing_id,
        summary.configured_component_count,
        active.component_count
            AS active_component_count,
        summary.required_reference_count,
        summary.unknown_reference_count,
        (
            active.component_count > 0
            AND summary.configured_component_count =
                active.component_count
            AND summary.required_reference_count > 0
            AND summary.unknown_reference_count = 0
        ) AS verified_reference
    FROM reference_summary AS summary
    CROSS JOIN active_component_count AS active
),
factory_seal_flags AS (
    SELECT
        assignment.marketplace,
        assignment.listing_id,
        BOOL_OR(
            observation.component_code = 'SHRINK_WRAP'
            AND observation.variant_key = 'FACTORY_SEALED'
            AND observation.observation_state = 'PRESENT'
            AND COALESCE(
                observation.observed_quantity,
                1
            ) >= 1
            AND observation.confidence >= 0.9000
            AND NULLIF(
                BTRIM(
                    observation.evidence_source
                ),
                ''
            ) IS NOT NULL
            AND NULLIF(
                BTRIM(
                    observation.evidence_url
                ),
                ''
            ) IS NOT NULL
        ) AS factory_sealed_evidence,
        BOOL_OR(
            observation.component_code = 'SHRINK_WRAP'
            AND observation.observation_state = 'ABSENT'
        ) AS seal_contradiction
    FROM warehouse.auction_pressing_assignment
        AS assignment
    LEFT JOIN warehouse.auction_component_observation
        AS observation
      ON observation.marketplace =
            assignment.marketplace
     AND observation.listing_id =
            assignment.listing_id
    GROUP BY
        assignment.marketplace,
        assignment.listing_id
),
expectation_rollup AS (
    SELECT
        assignment.marketplace,
        assignment.listing_id,
        assignment.pressing_id,
        pressing.release_family_id,
        COALESCE(
            coverage.verified_reference,
            false
        ) AS verified_reference,
        COUNT(*) FILTER (
            WHERE expectation.expectation_state = 'REQUIRED'
        ) AS required_component_count,
        COUNT(*) FILTER (
            WHERE expectation.expectation_state = 'REQUIRED'
              AND observation.observation_state = 'PRESENT'
        ) AS present_required_component_count,
        COALESCE(
            ARRAY_AGG(
                DISTINCT expectation.component_code
                ORDER BY expectation.component_code
            ) FILTER (
                WHERE expectation.expectation_state = 'REQUIRED'
                  AND observation.observation_state = 'ABSENT'
            ),
            ARRAY[]::varchar[]
        ) AS missing_components,
        COALESCE(
            ARRAY_AGG(
                DISTINCT expectation.component_code
                ORDER BY expectation.component_code
            ) FILTER (
                WHERE expectation.expectation_state = 'REQUIRED'
                  AND (
                      observation.id IS NULL
                      OR observation.observation_state IN (
                          'UNKNOWN',
                          'NOT_VISIBLE',
                          'NOT_APPLICABLE'
                      )
                  )
            ),
            ARRAY[]::varchar[]
        ) AS unverified_components
    FROM warehouse.auction_pressing_assignment
        AS assignment
    JOIN warehouse.pressing_identity AS pressing
      ON pressing.id = assignment.pressing_id
    LEFT JOIN reference_coverage AS coverage
      ON coverage.pressing_id = assignment.pressing_id
    LEFT JOIN warehouse.pressing_component_expectation
        AS expectation
      ON expectation.pressing_id = assignment.pressing_id
    LEFT JOIN warehouse.auction_component_observation
        AS observation
      ON observation.marketplace = assignment.marketplace
     AND observation.listing_id = assignment.listing_id
     AND observation.component_code =
            expectation.component_code
     AND observation.variant_key =
            expectation.variant_key
    GROUP BY
        assignment.marketplace,
        assignment.listing_id,
        assignment.pressing_id,
        pressing.release_family_id,
        coverage.verified_reference
),
unexpected_rollup AS (
    SELECT
        assignment.marketplace,
        assignment.listing_id,
        COALESCE(
            ARRAY_AGG(
                DISTINCT observation.component_code
                ORDER BY observation.component_code
            ) FILTER (
                WHERE observation.observation_state = 'PRESENT'
                  AND (
                      expectation.id IS NULL
                      OR expectation.expectation_state =
                            'NOT_INCLUDED'
                  )
            ),
            ARRAY[]::varchar[]
        ) AS unexpected_components
    FROM warehouse.auction_pressing_assignment
        AS assignment
    LEFT JOIN warehouse.auction_component_observation
        AS observation
      ON observation.marketplace = assignment.marketplace
     AND observation.listing_id = assignment.listing_id
    LEFT JOIN warehouse.pressing_component_expectation
        AS expectation
      ON expectation.pressing_id = assignment.pressing_id
     AND expectation.component_code =
            observation.component_code
     AND expectation.variant_key =
            observation.variant_key
    GROUP BY
        assignment.marketplace,
        assignment.listing_id
)
SELECT
    expectation.marketplace,
    expectation.listing_id,
    expectation.release_family_id,
    expectation.pressing_id,
    expectation.required_component_count,
    expectation.present_required_component_count,
    expectation.missing_components,
    expectation.unverified_components,
    COALESCE(
        unexpected.unexpected_components,
        ARRAY[]::varchar[]
    ) AS unexpected_components,
    CASE
        WHEN expectation.required_component_count = 0
            THEN NULL::numeric
        ELSE ROUND(
            expectation.present_required_component_count::numeric
            / expectation.required_component_count::numeric,
            4
        )
    END AS completeness_ratio,
    CASE
        WHEN expectation.required_component_count = 0
            THEN 'NO_EXPECTATION'
        WHEN CARDINALITY(
            expectation.missing_components
        ) > 0
            THEN 'INCOMPLETE'
        WHEN CARDINALITY(
            expectation.unverified_components
        ) > 0
         AND expectation.verified_reference
         AND COALESCE(
             seal.factory_sealed_evidence,
             false
         )
         AND NOT COALESCE(
             seal.seal_contradiction,
             false
         )
            THEN 'FACTORY_SEALED_EXCEPTION'
        WHEN CARDINALITY(
            expectation.unverified_components
        ) > 0
            THEN 'UNVERIFIED'
        ELSE 'COMPLETE'
    END AS completeness_status,
    (
        expectation.required_component_count > 0
        AND expectation.present_required_component_count =
            expectation.required_component_count
        AND CARDINALITY(
            expectation.missing_components
        ) = 0
        AND CARDINALITY(
            expectation.unverified_components
        ) = 0
    ) AS complete
FROM expectation_rollup AS expectation
LEFT JOIN unexpected_rollup AS unexpected
  ON unexpected.marketplace = expectation.marketplace
 AND unexpected.listing_id = expectation.listing_id
LEFT JOIN factory_seal_flags AS seal
  ON seal.marketplace = expectation.marketplace
 AND seal.listing_id = expectation.listing_id;
