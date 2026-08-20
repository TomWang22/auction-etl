"""Vercel control-plane dependency packaging contracts."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_vercel_uses_minimal_control_plane_requirements() -> None:
    """Vercel must not install the complete ETL dependency graph."""
    requirements = [
        line.strip()
        for line in (
            ROOT
            / "requirements.txt"
        ).read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip()
        and not line.lstrip().startswith("#")
    ]

    assert requirements == [
        "sqlalchemy==2.0.51",
        "psycopg[binary]==3.3.4",
    ]


def test_vercel_excludes_full_project_dependency_manifests() -> None:
    """Vercel must not discover the heavy worker dependency manifests."""
    ignored = {
        line.strip()
        for line in (
            ROOT
            / ".vercelignore"
        ).read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip()
        and not line.lstrip().startswith("#")
    }

    assert "pyproject.toml" in ignored
    assert "uv.lock" in ignored


def test_vercel_python_version_is_explicit() -> None:
    """The Vercel Python runtime must remain deterministic."""
    assert (
        ROOT
        / ".python-version"
    ).read_text(
        encoding="utf-8"
    ).strip() == "3.12"
