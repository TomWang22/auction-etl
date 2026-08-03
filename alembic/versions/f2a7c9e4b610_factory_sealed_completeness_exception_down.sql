CREATE OR REPLACE VIEW warehouse.auction_completeness AS
 WITH expectation_rollup AS (
         SELECT assignment.marketplace,
            assignment.listing_id,
            assignment.pressing_id,
            pressing.release_family_id,
            count(*) FILTER (WHERE expectation_1.expectation_state = 'REQUIRED'::text) AS required_component_count,
            count(*) FILTER (WHERE expectation_1.expectation_state = 'REQUIRED'::text AND observation.observation_state = 'PRESENT'::text) AS present_required_component_count,
            COALESCE(array_agg(DISTINCT expectation_1.component_code ORDER BY expectation_1.component_code) FILTER (WHERE expectation_1.expectation_state = 'REQUIRED'::text AND observation.observation_state = 'ABSENT'::text), ARRAY[]::text[]::character varying[]) AS missing_components,
            COALESCE(array_agg(DISTINCT expectation_1.component_code ORDER BY expectation_1.component_code) FILTER (WHERE expectation_1.expectation_state = 'REQUIRED'::text AND (observation.id IS NULL OR (observation.observation_state = ANY (ARRAY['UNKNOWN'::text, 'NOT_VISIBLE'::text, 'NOT_APPLICABLE'::text])))), ARRAY[]::text[]::character varying[]) AS unverified_components
           FROM warehouse.auction_pressing_assignment assignment
             JOIN warehouse.pressing_identity pressing ON pressing.id = assignment.pressing_id
             LEFT JOIN warehouse.pressing_component_expectation expectation_1 ON expectation_1.pressing_id = assignment.pressing_id
             LEFT JOIN warehouse.auction_component_observation observation ON observation.marketplace::text = assignment.marketplace::text AND observation.listing_id::text = assignment.listing_id::text AND observation.component_code::text = expectation_1.component_code::text AND observation.variant_key = expectation_1.variant_key
          GROUP BY assignment.marketplace, assignment.listing_id, assignment.pressing_id, pressing.release_family_id
        ), unexpected_rollup AS (
         SELECT assignment.marketplace,
            assignment.listing_id,
            COALESCE(array_agg(DISTINCT observation.component_code ORDER BY observation.component_code) FILTER (WHERE observation.observation_state = 'PRESENT'::text AND (expectation_1.id IS NULL OR expectation_1.expectation_state = 'NOT_INCLUDED'::text)), ARRAY[]::text[]::character varying[]) AS unexpected_components
           FROM warehouse.auction_pressing_assignment assignment
             LEFT JOIN warehouse.auction_component_observation observation ON observation.marketplace::text = assignment.marketplace::text AND observation.listing_id::text = assignment.listing_id::text
             LEFT JOIN warehouse.pressing_component_expectation expectation_1 ON expectation_1.pressing_id = assignment.pressing_id AND expectation_1.component_code::text = observation.component_code::text AND expectation_1.variant_key = observation.variant_key
          GROUP BY assignment.marketplace, assignment.listing_id
        )
 SELECT expectation.marketplace,
    expectation.listing_id,
    expectation.release_family_id,
    expectation.pressing_id,
    expectation.required_component_count,
    expectation.present_required_component_count,
    expectation.missing_components,
    expectation.unverified_components,
    COALESCE(unexpected.unexpected_components, ARRAY[]::text[]::character varying[]) AS unexpected_components,
        CASE
            WHEN expectation.required_component_count = 0 THEN NULL::numeric
            ELSE round(expectation.present_required_component_count::numeric / expectation.required_component_count::numeric, 4)
        END AS completeness_ratio,
        CASE
            WHEN expectation.required_component_count = 0 THEN 'NO_EXPECTATION'::text
            WHEN cardinality(expectation.missing_components) > 0 THEN 'INCOMPLETE'::text
            WHEN cardinality(expectation.unverified_components) > 0 THEN 'UNVERIFIED'::text
            ELSE 'COMPLETE'::text
        END AS completeness_status,
    expectation.required_component_count > 0 AND expectation.present_required_component_count = expectation.required_component_count AND cardinality(expectation.missing_components) = 0 AND cardinality(expectation.unverified_components) = 0 AS complete
   FROM expectation_rollup expectation
     LEFT JOIN unexpected_rollup unexpected ON unexpected.marketplace::text = expectation.marketplace::text AND unexpected.listing_id::text = expectation.listing_id::text;
;
