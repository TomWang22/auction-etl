"""Tests for physical pressing identity semantics."""

from auction_etl.domain.pressing_reference import (
    MatrixRunout,
    PressingReference,
    ReleaseFormat,
    ReleaseType,
    can_auto_assign_pressing,
    has_strong_pressing_identity_match,
    pressing_match_score,
)


def test_matrix_normalizes_side_and_value() -> None:
    matrix = MatrixRunout(
        side=" a ",
        value="  1A 1234  ",
    )

    assert matrix.side == "A"
    assert matrix.value == "1A 1234"


def test_reference_deduplicates_identical_matrices() -> None:
    reference = PressingReference(
        artist="Teresa Teng",
        canonical_title="Example",
        matrices=[
            MatrixRunout(
                side="A",
                value="ABC 123",
            ),
            MatrixRunout(
                side="A",
                value="abc 123",
            ),
        ],
    )

    assert len(
        reference.matrices
    ) == 1


def test_catalog_and_matrix_dominate_match_score() -> None:
    left = PressingReference(
        artist="Teresa Teng",
        canonical_title="Example",
        catalog_number="28TR-2018",
        release_country="Japan",
        release_year=1983,
        release_format=ReleaseFormat.LP,
        release_type=ReleaseType.STUDIO,
        matrices=[
            MatrixRunout(
                side="A",
                value="28TR-2018-A",
            ),
        ],
    )

    right = PressingReference(
        artist="Teresa Teng",
        canonical_title="Example",
        catalog_number="28TR-2018",
        release_country="Japan",
        release_year=1983,
        release_format=ReleaseFormat.LP,
        release_type=ReleaseType.STUDIO,
        matrices=[
            MatrixRunout(
                side="A",
                value="28TR-2018-A",
            ),
        ],
    )

    assert pressing_match_score(
        left,
        right,
    ) == 135

    assert has_strong_pressing_identity_match(
        left,
        right,
    )

    assert can_auto_assign_pressing(
        left,
        right,
    )


def test_title_only_match_cannot_auto_assign() -> None:
    left = PressingReference(
        artist="Teresa Teng",
        canonical_title="Example",
        release_format=ReleaseFormat.LP,
        release_country="Japan",
        release_year=1983,
    )

    right = PressingReference(
        artist="Teresa Teng",
        canonical_title="Example",
        release_format=ReleaseFormat.LP,
        release_country="Japan",
        release_year=1983,
    )

    assert pressing_match_score(
        left,
        right,
    ) == 45

    assert not has_strong_pressing_identity_match(
        left,
        right,
    )

    assert not can_auto_assign_pressing(
        left,
        right,
    )
