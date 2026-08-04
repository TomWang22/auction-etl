#!/usr/bin/env python3
"""Export a read-only review packet for one exact pressing cohort."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterable, Mapping

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from auction_etl.services.cohort_curation_wizard import (
    BASELINE_RULE_CODES,
    build_cohort_report,
    cohort_progress,
    export_cohort_workbook,
    list_attachments,
    list_cohort_audit,
    load_cohort,
    load_observation_rows,
    load_reference_rows,
)
from auction_etl.services.deterministic_verdicts import (
    evaluate_listing,
    list_rules,
)
from auction_etl.services.normalization_readiness import (
    get_readiness,
)
from auction_etl.services.normalization_workbench import (
    list_comparable_candidates,
)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Export the complete reviewed curation packet "
            "for one normalized catalog number."
        )
    )

    parser.add_argument(
        "--catalog",
        required=True,
        help="Catalog number, for example MR2276.",
    )

    parser.add_argument(
        "--output-dir",
        required=True,
        type=Path,
        help="Destination directory.",
    )

    parser.add_argument(
        "--database-url",
        default=os.environ.get(
            "DATABASE_URL"
        ),
        help="SQLAlchemy PostgreSQL URL.",
    )

    return parser.parse_args()


def normalized_catalog(
    value: str,
) -> str:
    """Normalize a catalog number for exact comparison."""
    return "".join(
        character
        for character in value.upper()
        if character.isalnum()
    )


def json_text(
    value: Any,
) -> str:
    """Serialize one value for CSV or TSV output."""
    if value is None:
        return ""

    if isinstance(
        value,
        (
            dict,
            list,
            tuple,
            set,
        ),
    ):
        return json.dumps(
            value,
            ensure_ascii=False,
            default=str,
            sort_keys=True,
        )

    return str(value)


def write_json(
    path: Path,
    value: Any,
) -> None:
    """Write formatted UTF-8 JSON."""
    path.write_text(
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            default=str,
        )
        + "\n",
        encoding="utf-8",
    )


def field_order(
    rows: Iterable[Mapping[str, Any]],
) -> list[str]:
    """Return stable first-seen field ordering."""
    ordered: list[str] = []
    seen: set[str] = set()

    for row in rows:
        for key in row:
            if key in seen:
                continue

            seen.add(key)
            ordered.append(key)

    return ordered


def write_delimited(
    path: Path,
    rows: list[Mapping[str, Any]],
    *,
    delimiter: str,
    fieldnames: list[str] | None = None,
) -> None:
    """Write CSV or TSV rows."""
    selected_fields = (
        fieldnames
        if fieldnames is not None
        else field_order(rows)
    )

    with path.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=
                selected_fields,
            delimiter=delimiter,
            lineterminator="\n",
            extrasaction="ignore",
        )

        writer.writeheader()

        for row in rows:
            writer.writerow(
                {
                    field:
                        json_text(
                            row.get(field)
                        )
                    for field in selected_fields
                }
            )


def resolve_pressing(
    engine: Engine,
    catalog: str,
) -> dict[str, Any]:
    """Resolve exactly one pressing by normalized catalog number."""
    target = normalized_catalog(
        catalog
    )

    if not target:
        raise ValueError(
            "Catalog number is empty after normalization."
        )

    with engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT
                    pressing.id AS pressing_id,
                    pressing.catalog_number,
                    family.display_artist,
                    family.display_title,
                    pressing.media_type,
                    pressing.generation
                FROM warehouse.pressing_identity AS pressing
                JOIN warehouse.release_family AS family
                  ON family.id =
                        pressing.release_family_id
                WHERE regexp_replace(
                    upper(
                        COALESCE(
                            pressing.catalog_number,
                            ''
                        )
                    ),
                    '[^A-Z0-9]',
                    '',
                    'g'
                ) = :catalog
                ORDER BY pressing.id
                """
            ),
            {
                "catalog":
                    target,
            },
        ).mappings().all()

    if len(rows) != 1:
        raise ValueError(
            "Expected exactly one pressing for normalized "
            f"catalog {target}; found {len(rows)}."
        )

    return dict(
        rows[0]
    )


def reference_review_rows(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build a disabled-by-default shared-reference worksheet."""
    output: list[dict[str, Any]] = []

    for row in rows:
        output.append(
            {
                "action":
                    "NO_CHANGE",
                "id":
                    row.get("id"),
                "component_code":
                    row.get(
                        "component_code"
                    ),
                "display_name":
                    row.get(
                        "display_name"
                    ),
                "variant_key":
                    row.get(
                        "variant_key"
                    )
                    or "",
                "variant_label":
                    row.get(
                        "variant_label"
                    )
                    or "",
                "expectation_state":
                    row.get(
                        "expectation_state"
                    )
                    or "UNKNOWN",
                "expected_quantity":
                    row.get(
                        "expected_quantity"
                    )
                    if row.get(
                        "expected_quantity"
                    )
                    is not None
                    else 1,
                "evidence_source":
                    row.get(
                        "evidence_source"
                    )
                    or "",
                "confidence":
                    row.get(
                        "confidence"
                    )
                    or "",
                "notes":
                    row.get("notes")
                    or "",
            }
        )

    return output


def observation_review_rows(
    cohort: dict[str, Any],
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build a disabled-by-default observation worksheet."""
    output: list[dict[str, Any]] = []

    for row in rows:
        output.append(
            {
                "action":
                    "NO_CHANGE",
                **row,
            }
        )

    for listing in cohort[
        "listings"
    ]:
        output.append(
            {
                "action":
                    "NO_CHANGE",
                "id":
                    "",
                "marketplace":
                    listing[
                        "marketplace"
                    ],
                "listing_id":
                    listing[
                        "listing_id"
                    ],
                "title":
                    listing.get(
                        "title"
                    )
                    or "",
                "component_code":
                    "",
                "variant_key":
                    "",
                "variant_label":
                    "",
                "observation_state":
                    "UNKNOWN",
                "observed_quantity":
                    0,
                "normalized_condition":
                    "",
                "source_condition_text":
                    "",
                "evidence_source":
                    "",
                "confidence":
                    "",
                "evidence_url":
                    "",
                "notes":
                    (
                        "Blank review row. Set action=UPSERT "
                        "only after listing-specific evidence is verified."
                    ),
            }
        )

    return output


def comparable_review_rows(
    engine: Engine,
    cohort: dict[str, Any],
) -> list[dict[str, Any]]:
    """Build disabled directed comparable-review rows."""
    rows: list[dict[str, Any]] = []

    for target in cohort[
        "listings"
    ]:
        candidates = (
            list_comparable_candidates(
                engine,
                str(
                    target[
                        "marketplace"
                    ]
                ),
                str(
                    target[
                        "listing_id"
                    ]
                ),
            )
        )

        for candidate in candidates:
            rows.append(
                {
                    "apply":
                        "FALSE",
                    "target_marketplace":
                        target[
                            "marketplace"
                        ],
                    "target_listing_id":
                        target[
                            "listing_id"
                        ],
                    "target_title":
                        target.get(
                            "title"
                        )
                        or "",
                    "comparable_marketplace":
                        candidate[
                            "marketplace"
                        ],
                    "comparable_listing_id":
                        candidate[
                            "listing_id"
                        ],
                    "comparable_title":
                        candidate.get(
                            "title"
                        )
                        or "",
                    "selected_price_usd":
                        candidate.get(
                            "selected_price_usd"
                        ),
                    "condition_market_factor":
                        candidate.get(
                            "condition_market_factor"
                        ),
                    "completeness_market_factor":
                        candidate.get(
                            "completeness_market_factor"
                        ),
                    "normalization_ready":
                        candidate.get(
                            "normalization_ready"
                        ),
                    "decision":
                        candidate.get(
                            "decision"
                        )
                        or "NEEDS_REVIEW",
                    "review_reason":
                        candidate.get(
                            "reason"
                        )
                        or "",
                    "actor":
                        "",
                }
            )

    return rows


def readiness_rows(
    engine: Engine,
    cohort: dict[str, Any],
) -> list[dict[str, Any]]:
    """Load deterministic readiness for every listing."""
    rows: list[dict[str, Any]] = []

    for listing in cohort[
        "listings"
    ]:
        result = get_readiness(
            engine,
            str(
                listing[
                    "marketplace"
                ]
            ),
            str(
                listing[
                    "listing_id"
                ]
            ),
        )

        rows.append(
            dict(result)
        )

    return rows


def verdict_rows(
    engine: Engine,
    cohort: dict[str, Any],
) -> list[dict[str, Any]]:
    """Flatten all eleven professional rule evaluations."""
    rules = list_rules(
        engine,
        include_inactive=True,
    )

    names = {
        str(rule["rule_code"]):
            rule.get(
                "display_name"
            )
        for rule in rules
    }

    output: list[dict[str, Any]] = []

    for listing in cohort[
        "listings"
    ]:
        evaluation = evaluate_listing(
            engine,
            str(
                listing[
                    "marketplace"
                ]
            ),
            str(
                listing[
                    "listing_id"
                ]
            ),
        )

        evaluations = {
            str(item["rule_code"]):
                item
            for item in evaluation[
                "evaluations"
            ]
        }

        for rule_code in (
            BASELINE_RULE_CODES
        ):
            item = evaluations.get(
                rule_code,
                {}
            )

            output.append(
                {
                    "marketplace":
                        listing[
                            "marketplace"
                        ],
                    "listing_id":
                        listing[
                            "listing_id"
                        ],
                    "title":
                        listing.get(
                            "title"
                        )
                        or "",
                    "rule_code":
                        rule_code,
                    "professional_name":
                        names.get(
                            rule_code
                        ),
                    "metric_code":
                        item.get(
                            "metric_code"
                        ),
                    "metric_value":
                        item.get(
                            "metric_value"
                        ),
                    "status":
                        item.get(
                            "status"
                        )
                        or "NOT_EVALUATED",
                    "triggered":
                        item.get(
                            "triggered"
                        ),
                    "severity":
                        item.get(
                            "severity"
                        ),
                    "verdict_label":
                        item.get(
                            "verdict_label"
                        ),
                    "suppression_reason":
                        item.get(
                            "suppression_reason"
                        ),
                }
            )

    return output


def attachment_template() -> list[dict[str, Any]]:
    """Build one inactive attachment metadata template."""
    return [
        {
            "apply":
                "FALSE",
            "source_key":
                "",
            "attachment_kind":
                "URL",
            "uri":
                "",
            "sha256":
                "",
            "mime_type":
                "",
            "captured_at":
                "",
            "page_reference":
                "",
            "notes":
                (
                    "Use a content checksum. Do not hash only "
                    "the URI text."
                ),
            "actor":
                "",
            "reason":
                "",
        }
    ]


def file_sha256(
    path: Path,
) -> str:
    """Calculate one file checksum."""
    digest = hashlib.sha256()

    with path.open(
        "rb"
    ) as handle:
        for block in iter(
            lambda: handle.read(
                1024 * 1024
            ),
            b"",
        ):
            digest.update(block)

    return digest.hexdigest()


def write_readme(
    path: Path,
    *,
    pressing: dict[str, Any],
    cohort: dict[str, Any],
    progress: dict[str, Any],
    attachments: list[dict[str, Any]],
    references: list[dict[str, Any]],
    observations: list[dict[str, Any]],
) -> None:
    """Write packet review instructions."""
    unresolved = [
        stage
        for stage in progress[
            "stages"
        ]
        if not stage[
            "complete"
        ]
    ]

    unresolved_lines = "\n".join(
        (
            f"- Stage {stage['stage']}: "
            f"{stage['name']} — "
            f"{stage['detail']}"
        )
        for stage in unresolved
    )

    content = f"""# Exact-Pressing Curation Review Packet

## Cohort

- Pressing ID: {pressing['pressing_id']}
- Catalog: {pressing.get('catalog_number') or ''}
- Artist: {pressing.get('display_artist') or ''}
- Title: {pressing.get('display_title') or ''}
- Assigned listings: {len(cohort['listings'])}
- Completed wizard stages: {progress['completed_stages']}/11

## Existing verified data

- Active attachment records: {len(attachments)}
- Persisted pressing-reference rows: {
    sum(row.get('id') is not None for row in references)
}
- Existing listing observations: {len(observations)}

The existing OBI and PINUP observations are listing-specific presence
evidence. They do not establish that those components were required for
every copy of the pressing.

## Unresolved stages

{unresolved_lines or '- None'}

## Stage 3 — Evidence and attachments

Edit `stage-03-attachment-review.csv`.

Set `apply=TRUE` only when the URI, evidence scope, and SHA-256 content
checksum have been reviewed. A listing title supporting an observation
must not be silently promoted into pressing-level reference evidence.

## Stage 4 — Shared completeness reference

Edit `stage-04-reference-review.csv`.

Change `action` from `NO_CHANGE` to `UPSERT` or `DELETE` only with
evidence supporting the exact pressing. Each component must be reviewed
as `REQUIRED`, `NOT_INCLUDED`, or `UNKNOWN`.

## Stage 5 — Listing observations

Edit `stage-05-observation-review.csv`.

The existing persisted rows are included with `action=NO_CHANGE`.
Additional rows must remain listing-specific and evidence-backed.

## Stage 6 — Condition normalization

Edit `stage-06-condition-review.csv`.

Set `apply=TRUE` only after completing every required field, including
the manual-override flag. A notes-only row is invalid by design.

## Stage 7 — Analysis and market factors

Edit `stage-07-analysis-review.csv`.

Set `apply=TRUE` only when the factors and supporting basis have been
reviewed. Do not derive a historical anchor from unnormalized prices.

## Stage 8 — Comparable review

Edit `stage-08-comparable-review.csv`.

Every row is disabled with `apply=FALSE`. Review directed comparisons
as `INCLUDE`, `EXCLUDE`, or `NEEDS_REVIEW`, with an explicit reason.

## Read-only evidence

- `current-cohort-report.json`
- `current-stage-progress.tsv`
- `current-readiness.tsv`
- `current-verdicts.tsv`
- `current-reference-audit.tsv`
- `current-normalization-audit.tsv`
- `current-attachments.tsv`
- `current-observations.tsv`

No file in this packet has been applied to PostgreSQL.
"""

    path.write_text(
        content,
        encoding="utf-8",
    )


def main() -> int:
    """Export the complete read-only review packet."""
    args = parse_args()

    if not args.database_url:
        raise RuntimeError(
            "DATABASE_URL is required."
        )

    args.output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    engine = create_engine(
        args.database_url,
        pool_pre_ping=True,
    )

    try:
        pressing = resolve_pressing(
            engine,
            args.catalog,
        )

        pressing_id = int(
            pressing[
                "pressing_id"
            ]
        )

        cohort = load_cohort(
            engine,
            pressing_id,
        )

        progress = cohort_progress(
            engine,
            pressing_id,
        )

        report = build_cohort_report(
            engine,
            pressing_id,
        )

        references = (
            load_reference_rows(
                engine,
                pressing_id,
            )
        )

        observations = (
            load_observation_rows(
                engine,
                pressing_id,
            )
        )

        attachments = list_attachments(
            engine,
            pressing_id,
        )

        audit = list_cohort_audit(
            engine,
            pressing_id,
        )

        readiness = readiness_rows(
            engine,
            cohort,
        )

        verdicts = verdict_rows(
            engine,
            cohort,
        )

        comparables = (
            comparable_review_rows(
                engine,
                cohort,
            )
        )

        write_json(
            args.output_dir
            / "current-cohort-report.json",
            report,
        )

        write_json(
            args.output_dir
            / "packet-summary.json",
            {
                "catalog":
                    args.catalog,
                "pressing":
                    pressing,
                "assigned_listing_count":
                    len(
                        cohort[
                            "listings"
                        ]
                    ),
                "completed_stages":
                    progress[
                        "completed_stages"
                    ],
                "stage_count":
                    len(
                        progress[
                            "stages"
                        ]
                    ),
                "persisted_reference_rows":
                    sum(
                        row.get("id")
                        is not None
                        for row
                        in references
                    ),
                "existing_observation_rows":
                    len(
                        observations
                    ),
                "active_attachment_rows":
                    len(
                        attachments
                    ),
                "comparable_review_rows":
                    len(
                        comparables
                    ),
                "database_writes":
                    0,
            },
        )

        write_delimited(
            args.output_dir
            / "current-stage-progress.tsv",
            progress[
                "stages"
            ],
            delimiter="\t",
        )

        write_delimited(
            args.output_dir
            / "current-listings.tsv",
            cohort[
                "listings"
            ],
            delimiter="\t",
        )

        write_delimited(
            args.output_dir
            / "current-attachments.tsv",
            attachments,
            delimiter="\t",
        )

        write_delimited(
            args.output_dir
            / "current-observations.tsv",
            observations,
            delimiter="\t",
        )

        write_delimited(
            args.output_dir
            / "current-readiness.tsv",
            readiness,
            delimiter="\t",
        )

        write_delimited(
            args.output_dir
            / "current-verdicts.tsv",
            verdicts,
            delimiter="\t",
        )

        write_delimited(
            args.output_dir
            / "current-reference-audit.tsv",
            audit[
                "reference_events"
            ],
            delimiter="\t",
        )

        write_delimited(
            args.output_dir
            / "current-normalization-audit.tsv",
            audit[
                "normalization_events"
            ],
            delimiter="\t",
        )

        write_delimited(
            args.output_dir
            / "stage-03-attachment-review.csv",
            attachment_template(),
            delimiter=",",
        )

        write_delimited(
            args.output_dir
            / "stage-04-reference-review.csv",
            reference_review_rows(
                references
            ),
            delimiter=",",
        )

        write_delimited(
            args.output_dir
            / "stage-05-observation-review.csv",
            observation_review_rows(
                cohort,
                observations,
            ),
            delimiter=",",
        )

        (
            args.output_dir
            / "stage-06-condition-review.csv"
        ).write_bytes(
            export_cohort_workbook(
                engine,
                pressing_id,
                "CONDITION",
            )
        )

        (
            args.output_dir
            / "stage-07-analysis-review.csv"
        ).write_bytes(
            export_cohort_workbook(
                engine,
                pressing_id,
                "ANALYSIS_FACTOR",
            )
        )

        write_delimited(
            args.output_dir
            / "stage-08-comparable-review.csv",
            comparables,
            delimiter=",",
        )

        write_readme(
            args.output_dir
            / "README.md",
            pressing=pressing,
            cohort=cohort,
            progress=progress,
            attachments=attachments,
            references=references,
            observations=observations,
        )

        packet_files = sorted(
            path
            for path
            in args.output_dir.iterdir()
            if path.is_file()
            and path.name
            != "manifest.json"
        )

        manifest = {
            "catalog":
                args.catalog,
            "pressing_id":
                pressing_id,
            "database_writes":
                0,
            "files":
                [
                    {
                        "name":
                            path.name,
                        "bytes":
                            path.stat().st_size,
                        "sha256":
                            file_sha256(
                                path
                            ),
                    }
                    for path
                    in packet_files
                ],
        }

        write_json(
            args.output_dir
            / "manifest.json",
            manifest,
        )

        print(
            json.dumps(
                {
                    "catalog":
                        args.catalog,
                    "pressing_id":
                        pressing_id,
                    "assigned_listings":
                        len(
                            cohort[
                                "listings"
                            ]
                        ),
                    "completed_stages":
                        progress[
                            "completed_stages"
                        ],
                    "stage_count":
                        len(
                            progress[
                                "stages"
                            ]
                        ),
                    "persisted_reference_rows":
                        sum(
                            row.get("id")
                            is not None
                            for row
                            in references
                        ),
                    "existing_observations":
                        len(
                            observations
                        ),
                    "active_attachments":
                        len(
                            attachments
                        ),
                    "comparable_review_rows":
                        len(
                            comparables
                        ),
                    "packet_files":
                        len(
                            manifest[
                                "files"
                            ]
                        )
                        + 1,
                    "output_dir":
                        str(
                            args.output_dir
                        ),
                    "database_writes":
                        0,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    finally:
        engine.dispose()

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
