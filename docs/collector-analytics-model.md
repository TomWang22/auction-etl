# Collector Analytics Model

## Identity hierarchy

A release family represents the canonical album or title.

A pressing identity represents an exact issue within that family:

- catalog and matrix number;
- country and region;
- media format and disc count;
- first press, early press, promo, reissue, or modern repress;
- issue-specific variant.

Listings remain unassigned until the collector or a high-confidence rule
connects them to an exact pressing.

## Completeness layers

Expected components are stored per pressing.

Observed components are stored per marketplace listing.

The derived completeness view returns:

- required component count;
- confirmed required component count;
- missing components;
- unverified components;
- unexpected components;
- completeness ratio;
- completeness status;
- complete boolean.

Unknown and not-visible components are never treated as absent.

## Bidder semantics

Distinct bidder count is nullable.

For Buyee or Yahoo! Auctions listings where distinct bidders are not
exposed:

    distinct_bidder_count = NULL
    distinct_bidder_state = NOT_EXPOSED

Unknown bidder count is never converted to zero.

## Price normalization

Each listing can select hammer, gross, or landed price.

Condition-adjusted prices require a condition market factor.

Fully normalized prices require both:

- condition market factor;
- completeness market factor.

Incomplete listings do not silently receive a factor of one.

## Comparable Confidence Score

Pairwise comparability is scored from zero to one hundred using:

- release-family match;
- exact pressing match;
- pressing generation;
- region;
- media type;
- disc count;
- completeness status;
- normalized condition;
- bulk-lot status;
- sealed status.

## Quantitative Midfication Detection

    ratio =
        modern or repress adjusted median
        / first-press adjusted median

Thresholds:

| Ratio | Status |
|---:|---|
| below 0.60 | Normal |
| 0.60–0.79 | Mid gaining visibility |
| 0.80–0.99 | Yellow alert |
| 1.00–1.19 | First-press defense breach |
| 1.20+ | Midfication incident |
| 1.20+ with at least three modern sales | Structural midfication |

The view requires fully normalized prices and excludes bulk lots.

## Completeness and obi premiums

Completeness premium:

    complete median / incomplete median

Obi premium:

    with-obi median / without-obi median

Obi variant summaries preserve issue-specific keys such as pink, alternate,
damaged, taped, or partial obi.

## Plushie Index

The five pillars are:

- title strength;
- completeness;
- condition;
- auction behavior;
- market context.

The full index appears only when all five scores exist.

A partial score and coverage ratio remain available while curation is
incomplete.

## Emotional Damage Framework

Available components are normalized to one hundred:

- expectation deviation;
- late spike;
- historical-anchor deviation;
- completeness contradiction;
- first-press distortion;
- bidder-war intensity.

Coverage is stored separately so a partial score cannot masquerade as a
fully observed incident.

## Manual-first rollout

1. Assign exact pressing identities.
2. Define pressing component expectations.
3. Record listing component observations.
4. Normalize condition.
5. Add behavior measurements and price snapshots.
6. Supply completeness market factors for incomplete copies.
7. Review comparable confidence.
8. Use Midfication, premium, Plushie, Emotional Damage, and alert views.
