"""Regression tests for managed Collector Review views."""

from __future__ import annotations

import os
import unittest

from sqlalchemy import create_engine, text

from auction_etl.database.collector_views import (
    COLLECTOR_VIEW_DDL,
    EFFECTIVE_VIEW_COLUMNS,
    EFFECTIVE_VIEW_SELECT_SQL,
    REVIEW_VIEW_COLUMNS,
    REVIEW_VIEW_SELECT_SQL,
    install_collector_views,
    verify_collector_views,
)


class CollectorViewDefinitionTests(unittest.TestCase):
    """Validate static view ownership and ordering."""

    def test_dependency_order_is_explicit(self) -> None:
        self.assertEqual(
            COLLECTOR_VIEW_DDL[0],
            (
                "DROP VIEW IF EXISTS "
                "warehouse.auction_collector_review"
            ),
        )
        self.assertEqual(
            COLLECTOR_VIEW_DDL[1],
            (
                "DROP VIEW IF EXISTS "
                "warehouse.auction_collector_effective"
            ),
        )
        self.assertTrue(
            COLLECTOR_VIEW_DDL[2].startswith(
                "CREATE VIEW "
                "warehouse.auction_collector_effective"
            )
        )
        self.assertTrue(
            COLLECTOR_VIEW_DDL[3].startswith(
                "CREATE VIEW "
                "warehouse.auction_collector_review"
            )
        )

    def test_selects_are_explicit(self) -> None:
        self.assertNotIn("a.*", EFFECTIVE_VIEW_SELECT_SQL)
        self.assertNotIn(
            "effective.*",
            REVIEW_VIEW_SELECT_SQL,
        )

    def test_auction_format_is_owned_by_both_views(self) -> None:
        self.assertIn(
            "auction_format",
            EFFECTIVE_VIEW_COLUMNS,
        )
        self.assertIn(
            "auction_format",
            REVIEW_VIEW_COLUMNS,
        )
        self.assertEqual(
            EFFECTIVE_VIEW_COLUMNS.index("auction_format"),
            REVIEW_VIEW_COLUMNS.index("auction_format"),
        )

    def test_column_names_are_unique(self) -> None:
        self.assertEqual(
            len(EFFECTIVE_VIEW_COLUMNS),
            len(set(EFFECTIVE_VIEW_COLUMNS)),
        )
        self.assertEqual(
            len(REVIEW_VIEW_COLUMNS),
            len(set(REVIEW_VIEW_COLUMNS)),
        )

    def test_review_extends_effective_shape(self) -> None:
        self.assertEqual(
            REVIEW_VIEW_COLUMNS[
                : len(EFFECTIVE_VIEW_COLUMNS)
            ],
            EFFECTIVE_VIEW_COLUMNS,
        )
        self.assertEqual(
            REVIEW_VIEW_COLUMNS[
                len(EFFECTIVE_VIEW_COLUMNS) :
            ],
            (
                "effective_pressing_type",
                "detail_auction_status",
                "detail_condition_text",
                "live_detail_status",
                "live_detail_error_message",
                "live_detail_fetched_at",
            ),
        )


@unittest.skipUnless(
    os.environ.get("AUCTION_ETL_TEST_DATABASE_URL"),
    "AUCTION_ETL_TEST_DATABASE_URL is not set.",
)
class CollectorViewIntegrationTests(unittest.TestCase):
    """Exercise DDL repeatedly against a disposable PostgreSQL database."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.engine = create_engine(
            os.environ["AUCTION_ETL_TEST_DATABASE_URL"]
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.engine.dispose()

    def view_definition(self, relation: str) -> str:
        with self.engine.connect() as connection:
            return str(
                connection.execute(
                    text(
                        """
                        SELECT pg_get_viewdef(
                            CAST(:relation AS regclass),
                            TRUE
                        )
                        """
                    ),
                    {"relation": relation},
                ).scalar_one()
            )

    def test_repeated_install_is_idempotent(self) -> None:
        for _ in range(5):
            with self.engine.begin() as connection:
                state = install_collector_views(
                    connection,
                    require_collector_parity=True,
                )

            self.assertEqual(
                state.warehouse_rows,
                state.review_rows,
            )
            self.assertEqual(
                state.warehouse_unique_rows,
                state.review_unique_rows,
            )

    def test_exact_columns_and_cardinality(self) -> None:
        with self.engine.begin() as connection:
            state = install_collector_views(
                connection,
                require_collector_parity=True,
            )

        self.assertEqual(
            state.effective_columns,
            EFFECTIVE_VIEW_COLUMNS,
        )
        self.assertEqual(
            state.review_columns,
            REVIEW_VIEW_COLUMNS,
        )
        self.assertEqual(
            state.warehouse_rows,
            state.warehouse_unique_rows,
        )
        self.assertEqual(
            state.warehouse_rows,
            state.collector_rows,
        )
        self.assertEqual(
            state.warehouse_rows,
            state.effective_rows,
        )
        self.assertEqual(
            state.warehouse_rows,
            state.review_rows,
        )

    def test_unmanaged_dependent_blocks_replacement(self) -> None:
        probe = (
            "warehouse."
            "_auction_collector_review_dependency_probe"
        )

        with self.engine.begin() as connection:
            connection.execute(
                text(f"DROP VIEW IF EXISTS {probe}")
            )
            connection.execute(
                text(
                    f"""
                    CREATE VIEW {probe} AS
                    SELECT marketplace, listing_id
                    FROM warehouse.auction_collector_review
                    """
                )
            )

        try:
            with self.assertRaisesRegex(
                RuntimeError,
                "unmanaged dependents",
            ):
                with self.engine.begin() as connection:
                    install_collector_views(connection)
        finally:
            with self.engine.begin() as connection:
                connection.execute(
                    text(f"DROP VIEW IF EXISTS {probe}")
                )

        with self.engine.begin() as connection:
            verify_collector_views(
                connection,
                require_collector_parity=True,
            )

    def test_mid_migration_failure_rolls_back(self) -> None:
        effective_before = self.view_definition(
            "warehouse.auction_collector_effective"
        )
        review_before = self.view_definition(
            "warehouse.auction_collector_review"
        )

        with self.assertRaises(Exception):
            with self.engine.begin() as connection:
                for statement in COLLECTOR_VIEW_DDL[:3]:
                    connection.execute(text(statement))

                connection.execute(
                    text(
                        "SELECT 1 / 0 AS injected_failure"
                    )
                )

        self.assertEqual(
            self.view_definition(
                "warehouse.auction_collector_effective"
            ),
            effective_before,
        )
        self.assertEqual(
            self.view_definition(
                "warehouse.auction_collector_review"
            ),
            review_before,
        )

        with self.engine.begin() as connection:
            verify_collector_views(
                connection,
                require_collector_parity=True,
            )


if __name__ == "__main__":
    unittest.main()

