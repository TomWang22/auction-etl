"""Domain models for stable physical pressing references."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class ReleaseFormat(StrEnum):
    """Physical carrier or release format."""

    LP = "LP"
    EP = "EP"
    SINGLE_7 = '7"'
    SINGLE_10 = '10"'
    SINGLE_12 = '12"'
    CD = "CD"
    CASSETTE = "CASSETTE"
    OTHER = "OTHER"


class ReleaseType(StrEnum):
    """Semantic release type independent of physical format."""

    STUDIO = "STUDIO"
    COMPILATION = "COMPILATION"
    LIVE = "LIVE"
    SOUNDTRACK = "SOUNDTRACK"
    SINGLE = "SINGLE"
    EP = "EP"
    PROMO = "PROMO"
    BOX_SET = "BOX_SET"
    OTHER = "OTHER"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class MatrixRunout:
    """Matrix or runout inscription for one side of a release."""

    side: str | None
    value: str

    def __post_init__(self) -> None:
        value = self.value.strip()

        if not value:
            raise ValueError(
                "matrix/runout value cannot be empty"
            )

        object.__setattr__(
            self,
            "value",
            value,
        )

        if self.side is not None:
            side = self.side.strip().upper()

            object.__setattr__(
                self,
                "side",
                side or None,
            )


@dataclass(slots=True)
class PressingReference:
    """Stable identity for one physical release or pressing.

    Auction prices, sellers, listing IDs, condition, completeness,
    and marketplace-specific observations intentionally do not
    belong to this object.
    """

    artist: str
    canonical_title: str

    catalog_number: str | None = None
    label: str | None = None

    release_country: str | None = None
    release_language: str | None = None
    release_year: int | None = None

    release_format: ReleaseFormat = ReleaseFormat.OTHER
    release_type: ReleaseType = ReleaseType.UNKNOWN

    matrices: list[MatrixRunout] = field(
        default_factory=list
    )

    edition_notes: str | None = None

    def __post_init__(self) -> None:
        self.artist = self.artist.strip()
        self.canonical_title = (
            self.canonical_title.strip()
        )

        if not self.artist:
            raise ValueError(
                "artist is required"
            )

        if not self.canonical_title:
            raise ValueError(
                "canonical_title is required"
            )

        self.catalog_number = self._clean_optional(
            self.catalog_number
        )
        self.label = self._clean_optional(
            self.label
        )
        self.release_country = self._clean_optional(
            self.release_country
        )
        self.release_language = self._clean_optional(
            self.release_language
        )
        self.edition_notes = self._clean_optional(
            self.edition_notes
        )

        if (
            self.release_year is not None
            and not 1900
            <= self.release_year
            <= 2100
        ):
            raise ValueError(
                "invalid release year: "
                f"{self.release_year}"
            )

        deduplicated: list[MatrixRunout] = []
        seen: set[tuple[str, str]] = set()

        for matrix in self.matrices:
            key = (
                matrix.side or "",
                matrix.value.casefold(),
            )

            if key in seen:
                continue

            seen.add(key)
            deduplicated.append(matrix)

        self.matrices = deduplicated

    @staticmethod
    def _clean_optional(
        value: str | None,
    ) -> str | None:
        if value is None:
            return None

        cleaned = value.strip()
        return cleaned or None


@dataclass(slots=True)
class AuctionObservation:
    """Marketplace-specific observation of a pressing."""

    marketplace: str
    listing_id: str
    listing_title: str

    pressing_reference_id: int | None = None

    seller: str | None = None
    listing_url: str | None = None

    starting_bid: str | None = None
    hammer_before_tax: str | None = None
    tax: str | None = None
    total_with_tax: str | None = None

    bids: int | None = None


@dataclass(slots=True)
class CompletenessObservation:
    """Copy-specific completeness and condition evidence."""

    obi: bool | None = None
    insert: bool | None = None
    poster: bool | None = None
    sticker: bool | None = None
    sealed: bool | None = None
    rental: bool | None = None

    media_condition: str | None = None
    cover_condition: str | None = None

    collector_notes: str | None = None
    manual_verdict: str | None = None


def _identity_text(value: str) -> str:
    """Normalize identity text without discarding punctuation."""

    return " ".join(
        value.casefold().split()
    )


def pressing_match_score(
    candidate: PressingReference,
    reference: PressingReference,
) -> int:
    """Return a conservative pressing identity-match score.

    Matrix and catalog identity dominate. Auction and completeness
    fields intentionally cannot participate.
    """

    score = 0

    if (
        candidate.catalog_number
        and reference.catalog_number
        and _identity_text(
            candidate.catalog_number
        )
        == _identity_text(
            reference.catalog_number
        )
    ):
        score += 40

    candidate_matrices = {
        _identity_text(matrix.value)
        for matrix in candidate.matrices
    }

    reference_matrices = {
        _identity_text(matrix.value)
        for matrix in reference.matrices
    }

    if candidate_matrices & reference_matrices:
        score += 50

    if (
        _identity_text(candidate.artist)
        == _identity_text(reference.artist)
    ):
        score += 10

    if (
        _identity_text(
            candidate.canonical_title
        )
        == _identity_text(
            reference.canonical_title
        )
    ):
        score += 10

    if (
        candidate.release_format
        == reference.release_format
    ):
        score += 10

    if (
        candidate.release_country
        and reference.release_country
        and _identity_text(
            candidate.release_country
        )
        == _identity_text(
            reference.release_country
        )
    ):
        score += 10

    if (
        candidate.release_year is not None
        and candidate.release_year
        == reference.release_year
    ):
        score += 5

    return score


def has_strong_pressing_identity_match(
    candidate: PressingReference,
    reference: PressingReference,
) -> bool:
    """Return whether catalog or matrix evidence matches exactly."""

    catalog_match = bool(
        candidate.catalog_number
        and reference.catalog_number
        and _identity_text(
            candidate.catalog_number
        )
        == _identity_text(
            reference.catalog_number
        )
    )

    candidate_matrices = {
        _identity_text(matrix.value)
        for matrix in candidate.matrices
    }
    reference_matrices = {
        _identity_text(matrix.value)
        for matrix in reference.matrices
    }

    matrix_match = bool(
        candidate_matrices
        & reference_matrices
    )

    return catalog_match or matrix_match


def can_auto_assign_pressing(
    candidate: PressingReference,
    reference: PressingReference,
    *,
    minimum_score: int = 70,
) -> bool:
    """Permit automatic assignment only with strong identity evidence."""

    return (
        has_strong_pressing_identity_match(
            candidate,
            reference,
        )
        and pressing_match_score(
            candidate,
            reference,
        )
        >= minimum_score
    )
