#!/usr/bin/env python3
"""Audit auction-related Docker resources without disrupting shared workloads."""

from __future__ import annotations

import argparse
import copy
import csv
import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Sequence


COLIMA_CONTEXT = "colima"

PROTECTED_CONTAINER = "auction-etl-db-1"
PROTECTED_PROJECT = "auction-etl"
PROTECTED_SERVICE = "db"
PROTECTED_VOLUME = "auction-etl_postgres_data"
PROTECTED_HOST = "127.0.0.1"
PROTECTED_PORT = "5544"
PROTECTED_DATABASE = "auction_warehouse"
PROTECTED_USER = "auction"

EXPECTED_REVISION = os.environ.get(
    "AUCTION_EXPECTED_REVISION",
    "c8b4d7e2a619",
)

EXPECTED_AUCTION_ROWS = os.environ.get(
    "AUCTION_EXPECTED_ROWS",
    "848",
)

ACTIVE_STATES = {
    "created",
    "running",
    "restarting",
    "paused",
}

BLOCKING_CLASSIFICATIONS = {
    "FOREIGN_ENGINE",
    "STALE_PROTECTED_LINEAGE",
    "SUSPICIOUS_ACTIVE",
    "SUSPICIOUS_STOPPED",
}


class AuditError(RuntimeError):
    """Raised when a Docker safety contract fails."""


@dataclass
class CommandResult:
    """Completed subprocess details."""

    returncode: int
    stdout: str
    stderr: str


@dataclass
class ContextRecord:
    """One configured Docker context."""

    context: str
    reachable: bool
    endpoint: str
    engine_key: str
    canonical_context: str
    classification: str


@dataclass
class ContainerRecord:
    """One auction-related Docker container."""

    classification: str
    context: str
    engine_key: str
    container_id: str
    name: str
    image: str
    state: str
    health: str
    restart_policy: str
    compose_project: str
    compose_service: str
    postgres_binding: str
    mounts: str
    reason: str


@dataclass
class VolumeRecord:
    """One auction-related Docker volume."""

    classification: str
    context: str
    engine_key: str
    volume: str
    compose_project: str
    references: str
    mountpoint: str
    reason: str


@dataclass
class Inventory:
    """Collected Docker resources."""

    contexts: list[ContextRecord]
    containers: list[ContainerRecord]
    volumes: list[VolumeRecord]
    disappeared_containers: int
    inspection_warnings: list[str]


def command_environment() -> dict[str, str]:
    """Return an environment that cannot silently target Docker Desktop."""
    environment = os.environ.copy()
    environment.pop("DOCKER_HOST", None)
    environment["DOCKER_CONTEXT"] = COLIMA_CONTEXT

    return environment


def run(
    command: Sequence[str],
    *,
    check: bool = False,
    input_text: str | None = None,
    environment: dict[str, str] | None = None,
) -> CommandResult:
    """Run one command and return captured output."""
    completed = subprocess.run(
        list(command),
        input=input_text,
        text=True,
        capture_output=True,
        env=environment or command_environment(),
        check=False,
    )

    result = CommandResult(
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )

    if check and result.returncode != 0:
        rendered_command = " ".join(command)

        raise AuditError(
            f"Command failed ({result.returncode}): {rendered_command}\n"
            f"{result.stderr.strip()}"
        )

    return result


def docker(
    context: str,
    *arguments: str,
    check: bool = False,
) -> CommandResult:
    """Run Docker against one explicit context."""
    return run(
        [
            "docker",
            "--context",
            context,
            *arguments,
        ],
        check=check,
    )


def require_commands(names: Iterable[str]) -> None:
    """Require local command-line dependencies."""
    missing = [
        name
        for name in names
        if shutil.which(name) is None
    ]

    if missing:
        raise AuditError(
            "Missing required commands: "
            + ", ".join(missing)
        )


def ensure_colima() -> None:
    """Start the existing Colima VM and select its Docker context."""
    require_commands(
        (
            "colima",
            "docker",
            "psql",
            "pg_isready",
        )
    )

    status = run(
        [
            "colima",
            "status",
        ]
    )

    if status.returncode != 0:
        print("Starting the existing Colima VM...")

        run(
            [
                "colima",
                "start",
            ],
            check=True,
        )

    context_check = run(
        [
            "docker",
            "context",
            "inspect",
            COLIMA_CONTEXT,
        ]
    )

    if context_check.returncode != 0:
        raise AuditError(
            "Docker context 'colima' does not exist."
        )

    run(
        [
            "docker",
            "context",
            "use",
            COLIMA_CONTEXT,
        ],
        check=True,
    )

    docker(
        COLIMA_CONTEXT,
        "info",
        check=True,
    )

    print("✓ Colima is running.")
    print("✓ Docker context is colima.")
    print("✓ DOCKER_HOST is unset.")
    print("✓ Docker Desktop was not started.")


def context_names() -> list[str]:
    """Return every configured Docker context."""
    result = run(
        [
            "docker",
            "context",
            "ls",
            "--format",
            "{{.Name}}",
        ],
        check=True,
    )

    return sorted(
        {
            line.strip()
            for line in result.stdout.splitlines()
            if line.strip()
        }
    )


def context_endpoint(context: str) -> str:
    """Return one context's Docker endpoint."""
    result = run(
        [
            "docker",
            "context",
            "inspect",
            context,
        ]
    )

    if result.returncode != 0:
        return ""

    try:
        payload = json.loads(
            result.stdout
        )

        endpoint = (
            payload[0]
            .get("Endpoints", {})
            .get("docker", {})
            .get("Host")
        )

        return str(
            endpoint
            or ""
        )
    except (
        IndexError,
        json.JSONDecodeError,
        TypeError,
    ):
        return ""


def docker_info(context: str) -> dict[str, Any] | None:
    """Return structured Docker engine information."""
    result = docker(
        context,
        "info",
        "--format",
        "{{json .}}",
    )

    if result.returncode != 0:
        return None

    try:
        return json.loads(
            result.stdout.strip()
        )
    except json.JSONDecodeError:
        return None


def engine_key(
    context: str,
    info: dict[str, Any],
    endpoint: str,
) -> str:
    """Return a stable identifier for one reachable Docker daemon."""
    engine_id = str(
        info.get("ID")
        or ""
    ).strip()

    if engine_id:
        return f"id:{engine_id}"

    docker_root = str(
        info.get("DockerRootDir")
        or ""
    ).strip()

    engine_name = str(
        info.get("Name")
        or ""
    ).strip()

    return "|".join(
        (
            "fallback",
            endpoint,
            docker_root,
            engine_name,
            context,
        )
    )


def discover_contexts() -> tuple[list[ContextRecord], str]:
    """Discover contexts and deduplicate aliases to the same daemon."""
    preliminary: list[
        tuple[str, bool, str, str]
    ] = []

    for context in context_names():
        endpoint = context_endpoint(
            context
        )

        info = docker_info(
            context
        )

        reachable = info is not None

        key = ""

        if info is not None:
            key = engine_key(
                context,
                info,
                endpoint,
            )

        preliminary.append(
            (
                context,
                reachable,
                endpoint,
                key,
            )
        )

    colima_entry = next(
        (
            entry
            for entry in preliminary
            if entry[0] == COLIMA_CONTEXT
        ),
        None,
    )

    if (
        colima_entry is None
        or not colima_entry[1]
        or not colima_entry[3]
    ):
        raise AuditError(
            "The Colima Docker engine is not reachable."
        )

    colima_engine_key = colima_entry[3]

    grouped_contexts: dict[
        str,
        list[str],
    ] = defaultdict(
        list
    )

    for context, reachable, _, key in preliminary:
        if reachable and key:
            grouped_contexts[
                key
            ].append(
                context
            )

    canonical_by_engine: dict[
        str,
        str,
    ] = {}

    for key, contexts in grouped_contexts.items():
        if (
            key == colima_engine_key
            and COLIMA_CONTEXT in contexts
        ):
            canonical_by_engine[
                key
            ] = COLIMA_CONTEXT
        else:
            canonical_by_engine[
                key
            ] = sorted(
                contexts
            )[0]

    records: list[
        ContextRecord
    ] = []

    for context, reachable, endpoint, key in preliminary:
        if not reachable:
            records.append(
                ContextRecord(
                    context=context,
                    reachable=False,
                    endpoint=endpoint,
                    engine_key="",
                    canonical_context="",
                    classification="UNREACHABLE",
                )
            )

            continue

        canonical = canonical_by_engine[
            key
        ]

        classification = (
            "CANONICAL"
            if context == canonical
            else "ENGINE_ALIAS"
        )

        records.append(
            ContextRecord(
                context=context,
                reachable=True,
                endpoint=endpoint,
                engine_key=key,
                canonical_context=canonical,
                classification=classification,
            )
        )

    return records, colima_engine_key


def stable_container_inspections(
    context: str,
) -> tuple[
    list[dict[str, Any]],
    int,
    list[str],
]:
    """Inspect containers individually while Kubernetes may replace pods."""
    inspected: dict[
        str,
        dict[str, Any],
    ] = {}

    disappeared: set[
        str
    ] = set()

    warnings: list[
        str
    ] = []

    for pass_number in range(
        2
    ):
        listing = docker(
            context,
            "ps",
            "-aq",
        )

        if listing.returncode != 0:
            warnings.append(
                f"{context}: docker ps failed: "
                f"{listing.stderr.strip()}"
            )

            break

        identifiers = [
            line.strip()
            for line in listing.stdout.splitlines()
            if line.strip()
        ]

        for identifier in identifiers:
            if identifier in inspected:
                continue

            inspection = docker(
                context,
                "inspect",
                "--format",
                "{{json .}}",
                identifier,
            )

            if inspection.returncode != 0:
                diagnostic = (
                    inspection.stderr
                    or inspection.stdout
                ).strip()

                if (
                    "No such object" in diagnostic
                    or "No such container" in diagnostic
                ):
                    disappeared.add(
                        identifier
                    )

                    continue

                warnings.append(
                    f"{context}: could not inspect "
                    f"{identifier}: {diagnostic}"
                )

                continue

            try:
                payload = json.loads(
                    inspection.stdout.strip()
                )
            except json.JSONDecodeError as error:
                warnings.append(
                    f"{context}: invalid inspect JSON for "
                    f"{identifier}: {error}"
                )

                continue

            container_id = str(
                payload.get("Id")
                or identifier
            )

            inspected[
                container_id
            ] = payload

        if pass_number == 0:
            time.sleep(
                0.15
            )

    return (
        list(
            inspected.values()
        ),
        len(
            disappeared
        ),
        warnings,
    )


def stable_volume_inspections(
    context: str,
) -> tuple[
    list[dict[str, Any]],
    list[str],
]:
    """Inspect Docker volumes without failing on concurrent deletion."""
    listing = docker(
        context,
        "volume",
        "ls",
        "-q",
    )

    if listing.returncode != 0:
        return (
            [],
            [
                f"{context}: docker volume ls failed: "
                f"{listing.stderr.strip()}"
            ],
        )

    volumes: list[
        dict[str, Any]
    ] = []

    warnings: list[
        str
    ] = []

    for name in listing.stdout.splitlines():
        volume_name = name.strip()

        if not volume_name:
            continue

        inspection = docker(
            context,
            "volume",
            "inspect",
            "--format",
            "{{json .}}",
            volume_name,
        )

        if inspection.returncode != 0:
            diagnostic = (
                inspection.stderr
                or inspection.stdout
            ).strip()

            if "No such volume" in diagnostic:
                continue

            warnings.append(
                f"{context}: could not inspect volume "
                f"{volume_name}: {diagnostic}"
            )

            continue

        try:
            volumes.append(
                json.loads(
                    inspection.stdout.strip()
                )
            )
        except json.JSONDecodeError as error:
            warnings.append(
                f"{context}: invalid volume JSON for "
                f"{volume_name}: {error}"
            )

    return volumes, warnings


def clean(value: Any) -> str:
    """Return one report-safe string."""
    return (
        str(
            value
            or ""
        )
        .replace(
            "\t",
            " ",
        )
        .replace(
            "\r",
            " ",
        )
        .replace(
            "\n",
            " ",
        )
        .strip()
    )


def container_labels(
    container: dict[str, Any],
) -> dict[str, str]:
    """Return normalized Docker labels."""
    labels = (
        container
        .get("Config", {})
        .get("Labels")
        or {}
    )

    return {
        str(key): clean(
            value
        )
        for key, value in labels.items()
    }


def container_mounts(
    container: dict[str, Any],
) -> list[str]:
    """Return normalized container mounts."""
    return [
        ":".join(
            (
                clean(
                    mount.get("Type")
                ),
                clean(
                    mount.get("Name")
                ),
                clean(
                    mount.get("Destination")
                ),
            )
        )
        for mount in container.get(
            "Mounts",
            [],
        )
    ]


def container_bindings(
    container: dict[str, Any],
) -> list[str]:
    """Return effective PostgreSQL bindings."""
    bindings = (
        container
        .get("NetworkSettings", {})
        .get("Ports", {})
        .get("5432/tcp")
        or []
    )

    return [
        "{}|{}".format(
            clean(
                binding.get("HostIp")
            ),
            clean(
                binding.get("HostPort")
            ),
        )
        for binding in bindings
    ]


def container_environment(
    container: dict[str, Any],
) -> list[str]:
    """Return normalized environment entries."""
    return [
        clean(
            value
        )
        for value in (
            container
            .get("Config", {})
            .get("Env")
            or []
        )
    ]


def has_protected_lineage(
    *,
    name: str,
    project: str,
    mounts: Sequence[str],
    environment: Sequence[str],
) -> bool:
    """Return whether a resource could be another auction-etl database."""
    normalized_name = name.casefold()

    name_match = bool(
        re.search(
            r"(^|[-_])auction[-_]?(etl|postgres)([-_]|$)",
            normalized_name,
        )
    )

    environment_text = " ".join(
        environment
    ).casefold()

    mount_text = " ".join(
        mounts
    ).casefold()

    return any(
        (
            name == PROTECTED_CONTAINER,
            project == PROTECTED_PROJECT,
            name_match,
            "auction_warehouse" in environment_text,
            "auction-etl_postgres_data" in mount_text,
        )
    )


def classify_container(
    *,
    context: str,
    current_engine_key: str,
    colima_engine_key: str,
    container: dict[str, Any],
) -> ContainerRecord | None:
    """Classify one auction-related container."""
    name = clean(
        container.get("Name")
    ).lstrip(
        "/"
    )

    container_id = clean(
        container.get("Id")
    )[:12]

    image = clean(
        container
        .get("Config", {})
        .get("Image")
    )

    state = clean(
        container
        .get("State", {})
        .get("Status")
    ) or "unknown"

    health = clean(
        container
        .get("State", {})
        .get("Health", {})
        .get("Status")
    ) or "none"

    restart_policy = clean(
        container
        .get("HostConfig", {})
        .get("RestartPolicy", {})
        .get("Name")
    ) or "none"

    labels = container_labels(
        container
    )

    project = labels.get(
        "com.docker.compose.project",
        "",
    )

    service = labels.get(
        "com.docker.compose.service",
        "",
    )

    mounts = container_mounts(
        container
    )

    bindings = container_bindings(
        container
    )

    environment = container_environment(
        container
    )

    searchable = " ".join(
        (
            name,
            image,
            project,
            service,
            " ".join(
                mounts
            ),
            " ".join(
                environment
            ),
        )
    ).casefold()

    if "auction" not in searchable:
        return None

    protected_lineage = has_protected_lineage(
        name=name,
        project=project,
        mounts=mounts,
        environment=environment,
    )

    protected_mount = (
        f"volume:{PROTECTED_VOLUME}:"
        "/var/lib/postgresql/data"
    )

    protected_binding = (
        f"{PROTECTED_HOST}|"
        f"{PROTECTED_PORT}"
    )

    is_protected = all(
        (
            current_engine_key == colima_engine_key,
            context == COLIMA_CONTEXT,
            name == PROTECTED_CONTAINER,
            project == PROTECTED_PROJECT,
            service == PROTECTED_SERVICE,
            protected_mount in mounts,
            protected_binding in bindings,
            state == "running",
            health == "healthy",
        )
    )

    if is_protected:
        classification = "PROTECTED"
        reason = (
            "Exact protected Colima database identity."
        )
    elif name.startswith(
        "quarantined-"
    ):
        classification = "QUARANTINED"
        reason = (
            "Previously isolated container; restart is disabled."
        )
    elif name.startswith(
        "k8s_"
    ):
        classification = "EXTERNAL_KUBERNETES"
        reason = (
            "Kubernetes-managed workload sharing the Docker daemon."
        )
    elif (
        project == "record-platform"
        or name.startswith(
            "record-platform-"
        )
    ):
        classification = "EXTERNAL_COMPOSE"
        reason = (
            "record-platform workload unrelated to auction-etl storage."
        )
    elif (
        protected_lineage
        and current_engine_key
        != colima_engine_key
    ):
        classification = "FOREIGN_ENGINE"
        reason = (
            "Possible auction-etl database exists on another "
            "reachable Docker daemon."
        )
    elif not protected_lineage:
        classification = "AUCTION_RELATED_EXTERNAL"
        reason = (
            "Auction-named workload without auction-etl database lineage."
        )
    elif (
        project == PROTECTED_PROJECT
        and protected_lineage
    ):
        classification = "STALE_PROTECTED_LINEAGE"
        reason = (
            "Stopped or noncanonical auction-etl database container "
            "still references protected database lineage."
        )
    elif project == PROTECTED_PROJECT:
        classification = "EXPECTED_PROJECT_OTHER"
        reason = (
            "Additional non-database container in the protected "
            "Compose project."
        )
    elif state in ACTIVE_STATES:
        classification = "SUSPICIOUS_ACTIVE"
        reason = (
            "Active auction database candidate outside the protected "
            "Compose identity."
        )
    else:
        classification = "SUSPICIOUS_STOPPED"
        reason = (
            "Stopped auction database candidate outside the protected "
            "Compose identity."
        )

    return ContainerRecord(
        classification=classification,
        context=context,
        engine_key=current_engine_key,
        container_id=container_id,
        name=name,
        image=image,
        state=state,
        health=health,
        restart_policy=restart_policy,
        compose_project=project,
        compose_service=service,
        postgres_binding=",".join(
            bindings
        ),
        mounts=";".join(
            mounts
        ),
        reason=reason,
    )


def classify_volume(
    *,
    context: str,
    current_engine_key: str,
    colima_engine_key: str,
    volume: dict[str, Any],
    references: Sequence[str],
) -> VolumeRecord | None:
    """Classify one auction-related Docker volume."""
    name = clean(
        volume.get("Name")
    )

    labels = (
        volume.get("Labels")
        or {}
    )

    project = clean(
        labels.get(
            "com.docker.compose.project"
        )
    )

    reference_text = " ".join(
        references
    )

    searchable = " ".join(
        (
            name,
            project,
            reference_text,
        )
    ).casefold()

    if "auction" not in searchable:
        return None

    normalized_name = name.casefold()

    protected_lineage = any(
        (
            normalized_name
            == PROTECTED_VOLUME.casefold(),
            normalized_name.startswith(
                "auction-etl"
            ),
            normalized_name.startswith(
                "auction_postgres"
            ),
            normalized_name.startswith(
                "auction-postgres"
            ),
        )
    )

    if (
        current_engine_key
        == colima_engine_key
        and name
        == PROTECTED_VOLUME
    ):
        classification = "PROTECTED"
        reason = (
            "Protected PostgreSQL named volume."
        )
    elif (
        project == "record-platform"
        or normalized_name.startswith(
            "record-platform"
        )
    ):
        classification = "EXTERNAL_COMPOSE"
        reason = (
            "record-platform volume unrelated to auction-etl."
        )
    elif (
        protected_lineage
        and current_engine_key
        != colima_engine_key
    ):
        classification = "FOREIGN_ENGINE"
        reason = (
            "Possible auction-etl volume exists on another daemon."
        )
    elif protected_lineage:
        classification = "SUSPICIOUS"
        reason = (
            "Auction database volume outside the protected identity."
        )
    else:
        classification = "AUCTION_RELATED_EXTERNAL"
        reason = (
            "Auction-related volume without protected database lineage."
        )

    return VolumeRecord(
        classification=classification,
        context=context,
        engine_key=current_engine_key,
        volume=name,
        compose_project=project,
        references=",".join(
            sorted(
                set(
                    references
                )
            )
        ),
        mountpoint=clean(
            volume.get("Mountpoint")
        ),
        reason=reason,
    )


def collect_inventory() -> Inventory:
    """Collect stable resources from each unique reachable Docker daemon."""
    contexts, colima_engine_key = discover_contexts()

    containers: list[
        ContainerRecord
    ] = []

    volumes: list[
        VolumeRecord
    ] = []

    disappeared_total = 0

    warnings: list[
        str
    ] = []

    canonical_contexts = [
        record
        for record in contexts
        if (
            record.reachable
            and record.classification
            == "CANONICAL"
        )
    ]

    for context_record in canonical_contexts:
        raw_containers, disappeared, container_warnings = (
            stable_container_inspections(
                context_record.context
            )
        )

        disappeared_total += disappeared
        warnings.extend(
            container_warnings
        )

        references_by_volume: dict[
            str,
            list[str],
        ] = defaultdict(
            list
        )

        for raw_container in raw_containers:
            name = clean(
                raw_container.get("Name")
            ).lstrip(
                "/"
            )

            for mount in raw_container.get(
                "Mounts",
                [],
            ):
                if mount.get(
                    "Type"
                ) != "volume":
                    continue

                volume_name = clean(
                    mount.get("Name")
                )

                if volume_name:
                    references_by_volume[
                        volume_name
                    ].append(
                        name
                    )

            record = classify_container(
                context=context_record.context,
                current_engine_key=context_record.engine_key,
                colima_engine_key=colima_engine_key,
                container=raw_container,
            )

            if record is not None:
                containers.append(
                    record
                )

        raw_volumes, volume_warnings = (
            stable_volume_inspections(
                context_record.context
            )
        )

        warnings.extend(
            volume_warnings
        )

        for raw_volume in raw_volumes:
            volume_name = clean(
                raw_volume.get("Name")
            )

            record = classify_volume(
                context=context_record.context,
                current_engine_key=context_record.engine_key,
                colima_engine_key=colima_engine_key,
                volume=raw_volume,
                references=references_by_volume.get(
                    volume_name,
                    [],
                ),
            )

            if record is not None:
                volumes.append(
                    record
                )

    return Inventory(
        contexts=contexts,
        containers=sorted(
            containers,
            key=lambda row: (
                row.classification,
                row.context,
                row.name,
            ),
        ),
        volumes=sorted(
            volumes,
            key=lambda row: (
                row.classification,
                row.context,
                row.volume,
            ),
        ),
        disappeared_containers=disappeared_total,
        inspection_warnings=warnings,
    )


def write_tsv(
    path: Path,
    rows: Sequence[Any],
) -> None:
    """Write dataclass rows as TSV."""
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    if not rows:
        path.write_text(
            "",
            encoding="utf-8",
        )

        return

    dictionaries = [
        asdict(
            row
        )
        for row in rows
    ]

    with path.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as output:
        writer = csv.DictWriter(
            output,
            fieldnames=list(
                dictionaries[0].keys()
            ),
            delimiter="\t",
            lineterminator="\n",
        )

        writer.writeheader()
        writer.writerows(
            dictionaries
        )


def write_inventory(
    inventory: Inventory,
    evidence_dir: Path,
    prefix: str,
) -> None:
    """Persist one audit inventory."""
    write_tsv(
        evidence_dir
        / f"contexts-{prefix}.tsv",
        inventory.contexts,
    )

    write_tsv(
        evidence_dir
        / f"containers-{prefix}.tsv",
        inventory.containers,
    )

    write_tsv(
        evidence_dir
        / f"volumes-{prefix}.tsv",
        inventory.volumes,
    )

    metadata = {
        "generated_at":
            datetime.now()
            .astimezone()
            .isoformat(),
        "disappeared_containers":
            inventory.disappeared_containers,
        "inspection_warnings":
            inventory.inspection_warnings,
    }

    (
        evidence_dir
        / f"metadata-{prefix}.json"
    ).write_text(
        json.dumps(
            metadata,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def print_table(
    headers: Sequence[str],
    rows: Sequence[Sequence[str]],
) -> None:
    """Print a compact aligned table."""
    if not rows:
        print("  None")

        return

    widths = [
        len(
            header
        )
        for header in headers
    ]

    for row in rows:
        for index, value in enumerate(
            row
        ):
            widths[index] = max(
                widths[index],
                len(
                    value
                ),
            )

    print(
        "  ".join(
            header.ljust(
                widths[index]
            )
            for index, header in enumerate(
                headers
            )
        )
    )

    print(
        "  ".join(
            "-" * width
            for width in widths
        )
    )

    for row in rows:
        print(
            "  ".join(
                value.ljust(
                    widths[index]
                )
                for index, value in enumerate(
                    row
                )
            )
        )


def print_inventory(
    inventory: Inventory,
) -> None:
    """Display the relevant audit results."""
    print()
    print("================ DOCKER CONTEXTS ================")

    print_table(
        (
            "CONTEXT",
            "STATE",
            "CLASS",
            "CANONICAL",
        ),
        [
            (
                row.context,
                (
                    "reachable"
                    if row.reachable
                    else "unreachable"
                ),
                row.classification,
                row.canonical_context or "-",
            )
            for row in inventory.contexts
        ],
    )

    print()
    print("================ AUCTION CONTAINERS ================")

    print_table(
        (
            "CLASS",
            "CONTEXT",
            "NAME",
            "STATE",
            "PORT",
        ),
        [
            (
                row.classification,
                row.context,
                row.name,
                row.state,
                row.postgres_binding or "-",
            )
            for row in inventory.containers
        ],
    )

    print()
    print("================ AUCTION VOLUMES ================")

    print_table(
        (
            "CLASS",
            "CONTEXT",
            "VOLUME",
            "REFERENCES",
        ),
        [
            (
                row.classification,
                row.context,
                row.volume,
                row.references or "-",
            )
            for row in inventory.volumes
        ],
    )

    counts = Counter(
        row.classification
        for row in inventory.containers
    )

    print()
    print("================ INVENTORY SUMMARY ================")
    print(
        "Protected containers:       "
        f"{counts['PROTECTED']}"
    )
    print(
        "External Kubernetes:        "
        f"{counts['EXTERNAL_KUBERNETES']}"
    )
    print(
        "External Compose:           "
        f"{counts['EXTERNAL_COMPOSE']}"
    )
    print(
        "Foreign-engine candidates:  "
        f"{counts['FOREIGN_ENGINE']}"
    )
    print(
        "Suspicious active:          "
        f"{counts['SUSPICIOUS_ACTIVE']}"
    )
    print(
        "Suspicious stopped:         "
        f"{counts['SUSPICIOUS_STOPPED']}"
    )
    print(
        "Quarantined containers:     "
        f"{counts['QUARANTINED']}"
    )
    print(
        "Containers removed during "
        f"inspection: {inventory.disappeared_containers}"
    )

    if inventory.inspection_warnings:
        print()
        print("Inspection warnings:")

        for warning in inventory.inspection_warnings:
            print(
                f"  {warning}"
            )


def blocking_containers(
    inventory: Inventory,
) -> list[ContainerRecord]:
    """Return containers that violate the auction-etl guard."""
    return [
        row
        for row in inventory.containers
        if row.classification
        in BLOCKING_CLASSIFICATIONS
    ]


def evaluate_inventory(
    inventory: Inventory,
    *,
    strict: bool,
) -> None:
    """Validate protected and suspicious resource counts."""
    protected = [
        row
        for row in inventory.containers
        if row.classification
        == "PROTECTED"
    ]

    blockers = blocking_containers(
        inventory
    )

    if blockers:
        print()
        print("Blocking auction resources:")

        for blocker in blockers:
            print(
                "  "
                f"{blocker.classification} · "
                f"{blocker.context} · "
                f"{blocker.name} · "
                f"{blocker.state}"
            )

    if not strict:
        return

    if len(
        protected
    ) != 1:
        raise AuditError(
            "Expected exactly one protected auction-etl "
            f"database; found {len(protected)}."
        )

    if blockers:
        names = ", ".join(
            sorted(
                row.name
                for row in blockers
            )
        )

        raise AuditError(
            "Rogue or foreign-engine auction resources remain: "
            f"{names}"
        )

    print()
    print("✓ Strict Docker auction-resource guard passed.")


def redacted_inspection(
    container: dict[str, Any],
) -> dict[str, Any]:
    """Return inspect data without environment values."""
    redacted = copy.deepcopy(
        container
    )

    environment = (
        redacted
        .get("Config", {})
        .get("Env")
    )

    if isinstance(
        environment,
        list,
    ):
        redacted[
            "Config"
        ][
            "Env"
        ] = [
            (
                entry.split(
                    "=",
                    1,
                )[0]
                + "=***"
                if "=" in str(
                    entry
                )
                else str(
                    entry
                )
            )
            for entry in environment
        ]

    return redacted


def inspect_named_container(
    context: str,
    name: str,
) -> dict[str, Any] | None:
    """Return one exact-name container from a Docker context."""
    listing = docker(
        context,
        "ps",
        "-aq",
        "--filter",
        f"name=^/{name}$",
    )

    if listing.returncode != 0:
        raise AuditError(
            listing.stderr.strip()
            or "Could not list containers."
        )

    identifiers = [
        line.strip()
        for line in listing.stdout.splitlines()
        if line.strip()
    ]

    if not identifiers:
        return None

    if len(
        identifiers
    ) != 1:
        raise AuditError(
            f"Expected one container named {name!r}; "
            f"found {len(identifiers)}."
        )

    inspection = docker(
        context,
        "inspect",
        "--format",
        "{{json .}}",
        identifiers[0],
    )

    if inspection.returncode != 0:
        raise AuditError(
            inspection.stderr.strip()
            or f"Could not inspect {name}."
        )

    return json.loads(
        inspection.stdout.strip()
    )


def quarantine_container(
    name: str,
    evidence_dir: Path,
) -> str:
    """Disable, stop, and rename one verified rogue container."""
    if name == PROTECTED_CONTAINER:
        raise AuditError(
            "The protected database cannot be quarantined."
        )

    container = inspect_named_container(
        COLIMA_CONTEXT,
        name,
    )

    if container is None:
        print(
            f"✓ {name} does not exist in Colima."
        )

        return ""

    labels = container_labels(
        container
    )

    project = labels.get(
        "com.docker.compose.project",
        "",
    )

    service = labels.get(
        "com.docker.compose.service",
        "",
    )

    mounts = container_mounts(
        container
    )

    container_id = clean(
        container.get("Id")
    )

    print()
    print("================ QUARANTINE CANDIDATE ================")
    print(
        f"Context:   {COLIMA_CONTEXT}"
    )
    print(
        f"Container: {name}"
    )
    print(
        f"ID:        {container_id[:12]}"
    )
    print(
        f"Project:   {project or 'NONE'}"
    )
    print(
        f"Service:   {service or 'NONE'}"
    )
    print(
        "Mounts:    "
        + (
            ";".join(
                mounts
            )
            or "NONE"
        )
    )

    if project == PROTECTED_PROJECT:
        raise AuditError(
            f"{name} belongs to protected Compose project "
            f"{PROTECTED_PROJECT}."
        )

    protected_mount = (
        f"volume:{PROTECTED_VOLUME}:"
        "/var/lib/postgresql/data"
    )

    if protected_mount in mounts:
        raise AuditError(
            f"{name} uses protected volume "
            f"{PROTECTED_VOLUME}."
        )

    inspection_path = (
        evidence_dir
        / f"{name}.inspect.redacted.json"
    )

    inspection_path.write_text(
        json.dumps(
            redacted_inspection(
                container
            ),
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    logs = docker(
        COLIMA_CONTEXT,
        "logs",
        "--timestamps",
        "--tail",
        "1000",
        container_id,
    )

    (
        evidence_dir
        / f"{name}.logs.txt"
    ).write_text(
        logs.stdout
        + logs.stderr,
        encoding="utf-8",
    )

    docker(
        COLIMA_CONTEXT,
        "update",
        "--restart=no",
        container_id,
        check=True,
    )

    docker(
        COLIMA_CONTEXT,
        "stop",
        "--time",
        "30",
        container_id,
    )

    timestamp = datetime.now().strftime(
        "%Y%m%d-%H%M%S"
    )

    quarantined_name = (
        f"quarantined-{name}-{timestamp}"
    )

    docker(
        COLIMA_CONTEXT,
        "rename",
        container_id,
        quarantined_name,
        check=True,
    )

    print()
    print("✓ Restart policy disabled.")
    print("✓ Container stopped.")
    print(
        "✓ Container renamed to "
        f"{quarantined_name}."
    )
    print("✓ No container was deleted.")
    print("✓ No volume was deleted.")

    return quarantined_name


def database_query(
    statement: str,
) -> str:
    """Run one scalar query against the protected warehouse."""
    password = os.environ.get(
        "AUCTION_DB_PASSWORD",
        "auction",
    )

    environment = command_environment()
    environment[
        "PGPASSWORD"
    ] = password

    result = run(
        [
            "psql",
            (
                "postgresql://"
                f"{PROTECTED_USER}:{password}"
                f"@{PROTECTED_HOST}:{PROTECTED_PORT}"
                f"/{PROTECTED_DATABASE}"
            ),
            "--no-password",
            "-v",
            "ON_ERROR_STOP=1",
            "-Atc",
            statement,
        ],
        environment=environment,
    )

    if result.returncode != 0:
        raise AuditError(
            "Protected PostgreSQL query failed:\n"
            + result.stderr.strip()
        )

    return result.stdout.strip()


def verify_protected_database() -> None:
    """Verify the protected database identity after strict checks."""
    password = os.environ.get(
        "AUCTION_DB_PASSWORD",
        "auction",
    )

    environment = command_environment()
    environment[
        "PGPASSWORD"
    ] = password

    readiness = run(
        [
            "pg_isready",
            "-h",
            PROTECTED_HOST,
            "-p",
            PROTECTED_PORT,
            "-U",
            PROTECTED_USER,
            "-d",
            PROTECTED_DATABASE,
        ],
        environment=environment,
    )

    if readiness.returncode != 0:
        raise AuditError(
            "Protected PostgreSQL is not accepting connections "
            f"on {PROTECTED_HOST}:{PROTECTED_PORT}."
        )

    revision = database_query(
        "SELECT version_num "
        "FROM alembic_version "
        "LIMIT 1;"
    )

    auction_rows = database_query(
        "SELECT COUNT(*) "
        "FROM warehouse.auction;"
    )

    if (
        EXPECTED_REVISION
        and revision
        != EXPECTED_REVISION
    ):
        raise AuditError(
            "Expected Alembic revision "
            f"{EXPECTED_REVISION}; found {revision or 'EMPTY'}."
        )

    if (
        EXPECTED_AUCTION_ROWS
        and auction_rows
        != EXPECTED_AUCTION_ROWS
    ):
        raise AuditError(
            "Expected auction row count "
            f"{EXPECTED_AUCTION_ROWS}; found {auction_rows}."
        )

    print()
    print("================ DATABASE VERIFICATION ================")
    print(
        f"PostgreSQL:       {PROTECTED_HOST}:{PROTECTED_PORT}"
    )
    print(
        f"Alembic revision: {revision}"
    )
    print(
        f"Auction rows:     {auction_rows}"
    )
    print("✓ The protected warehouse is intact.")


def write_listener_report(
    evidence_dir: Path,
    prefix: str,
) -> None:
    """Record relevant host TCP listeners."""
    if shutil.which(
        "lsof"
    ) is None:
        return

    result = run(
        [
            "lsof",
            "-nP",
            "-iTCP",
            "-sTCP:LISTEN",
        ]
    )

    selected_lines = []

    for index, line in enumerate(
        result.stdout.splitlines()
    ):
        if (
            index == 0
            or re.search(
                r":(?:5432|5444|5544)(?:\s|$)",
                line,
            )
        ):
            selected_lines.append(
                line
            )

    (
        evidence_dir
        / f"listeners-{prefix}.txt"
    ).write_text(
        "\n".join(
            selected_lines
        )
        + (
            "\n"
            if selected_lines
            else ""
        ),
        encoding="utf-8",
    )


def collect_and_report(
    evidence_dir: Path,
    prefix: str,
) -> Inventory:
    """Collect, persist, and print one inventory."""
    inventory = collect_inventory()

    write_inventory(
        inventory,
        evidence_dir,
        prefix,
    )

    write_listener_report(
        evidence_dir,
        prefix,
    )

    print_inventory(
        inventory
    )

    return inventory


def parse_arguments() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Audit auction-related Docker resources across contexts "
            "without deleting containers or volumes."
        )
    )

    parser.add_argument(
        "action",
        choices=(
            "audit",
            "assert-clean",
            "quarantine",
        ),
        nargs="?",
        default="audit",
    )

    parser.add_argument(
        "container",
        nargs="?",
        default="auction-postgres",
        help=(
            "Exact Colima container name used by the quarantine action."
        ),
    )

    return parser.parse_args()


def main() -> int:
    """Run the requested Docker audit operation."""
    arguments = parse_arguments()

    repository_root = Path(
        subprocess.check_output(
            [
                "git",
                "rev-parse",
                "--show-toplevel",
            ],
            text=True,
        ).strip()
    )

    os.chdir(
        repository_root
    )

    timestamp = datetime.now().strftime(
        "%Y%m%d-%H%M%S"
    )

    evidence_dir = (
        repository_root
        / "logs"
        / f"docker-context-audit-{timestamp}"
    )

    evidence_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    try:
        print("================ DOCKER CONTEXT AUDIT ================")

        ensure_colima()

        if arguments.action == "audit":
            inventory = collect_and_report(
                evidence_dir,
                "audit",
            )

            evaluate_inventory(
                inventory,
                strict=False,
            )

        elif arguments.action == "assert-clean":
            inventory = collect_and_report(
                evidence_dir,
                "assert-clean",
            )

            evaluate_inventory(
                inventory,
                strict=True,
            )

            verify_protected_database()

        else:
            before = collect_and_report(
                evidence_dir,
                "before-quarantine",
            )

            evaluate_inventory(
                before,
                strict=False,
            )

            quarantine_container(
                arguments.container,
                evidence_dir,
            )

            print()
            print("================ POST-QUARANTINE AUDIT ================")

            after = collect_and_report(
                evidence_dir,
                "after-quarantine",
            )

            evaluate_inventory(
                after,
                strict=True,
            )

            verify_protected_database()

        run(
            [
                "docker",
                "context",
                "use",
                COLIMA_CONTEXT,
            ],
            check=True,
        )

        print()
        print("================ RESULT ================")
        print(
            f"Docker context: {COLIMA_CONTEXT}"
        )
        print(
            f"Evidence:       {evidence_dir}"
        )
        print()
        print("✅ Kubernetes workloads were not modified.")
        print("✅ record-platform workloads were not modified.")
        print("✅ The protected auction-etl database was not modified.")
        print("✅ No container or volume was deleted.")

        return 0
    except (
        AuditError,
        json.JSONDecodeError,
    ) as error:
        print()
        print(
            f"ERROR: {error}",
            file=sys.stderr,
        )
        print(
            f"Evidence: {evidence_dir}",
            file=sys.stderr,
        )

        return 1


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
