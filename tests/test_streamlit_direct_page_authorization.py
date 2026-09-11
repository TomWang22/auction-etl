"""Fail closed when a protected Streamlit page loses authorization."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest


AUTHENTICATED_PAGES = (
    Path(
        "app/pages/10_Listing_Completeness_Review.py"
    ),
    Path(
        "app/pages/12_Completeness_History.py"
    ),
    Path(
        "app/pages/13_New_Auction_Intake.py"
    ),
    Path(
        "app/pages/2_Pressing_Analytics.py"
    ),
    Path(
        "app/pages/5_Normalization_Readiness.py"
    ),
)

ADMIN_PAGES = (
    Path(
        "app/pages/11_Media_Profile_Admin.py"
    ),
    Path(
        "app/pages/14_Pressing_Reference_Catalog.py"
    ),
    Path(
        "app/pages/2_Completeness_Reference.py"
    ),
    Path(
        "app/pages/3_Evidence_and_Bulk_Observations.py"
    ),
    Path(
        "app/pages/4_Reference_Record_Admin.py"
    ),
    Path(
        "app/pages/6_Deterministic_Verdict_Rules.py"
    ),
    Path(
        "app/pages/7_Normalization_Workbench.py"
    ),
    Path(
        "app/pages/8_Cohort_Curation_Wizard.py"
    ),
    Path(
        "app/pages/9_Evidence_Intake.py"
    ),
)


def called_name(
    call: ast.Call,
) -> str | None:
    """Return the simple function name for one call expression."""
    function = call.func

    if isinstance(
        function,
        ast.Name,
    ):
        return function.id

    if isinstance(
        function,
        ast.Attribute,
    ):
        return function.attr

    return None


def called_names(
    node: ast.AST,
) -> list[str]:
    """Return function names in source order."""
    calls: list[
        tuple[int, int, str]
    ] = []

    for child in ast.walk(
        node
    ):
        if not isinstance(
            child,
            ast.Call,
        ):
            continue

        name = called_name(
            child
        )

        if name is None:
            continue

        calls.append(
            (
                child.lineno,
                child.col_offset,
                name,
            )
        )

    return [
        name
        for _, _, name in sorted(
            calls
        )
    ]


def page_tree(
    path: Path,
) -> ast.Module:
    """Parse one Streamlit page."""
    return ast.parse(
        path.read_text(
            encoding="utf-8"
        ),
        filename=str(
            path
        ),
    )


def page_main_from_tree(
    tree: ast.Module,
    path: Path,
) -> ast.FunctionDef:
    """Return the page's single main entrypoint."""
    matches = [
        statement
        for statement in tree.body
        if (
            isinstance(
                statement,
                ast.FunctionDef,
            )
            and statement.name
            == "main"
        )
    ]

    assert len(
        matches
    ) == 1, (
        f"{path}: expected exactly one main() function"
    )

    return matches[0]


def page_main(
    path: Path,
) -> ast.FunctionDef:
    """Load the page's main entrypoint."""
    return page_main_from_tree(
        page_tree(
            path
        ),
        path,
    )


def statement_calls(
    statement: ast.stmt,
    name: str,
) -> bool:
    """Return whether one top-level statement invokes a named function."""
    return any(
        (
            isinstance(
                node,
                ast.Call,
            )
            and called_name(
                node
            )
            == name
        )
        for node in ast.walk(
            statement
        )
    )


def assignment_targets_name(
    statement: ast.stmt,
    name: str,
) -> bool:
    """Return whether one statement assigns the requested variable."""
    targets: list[
        ast.expr
    ] = []

    if isinstance(
        statement,
        ast.Assign,
    ):
        targets.extend(
            statement.targets
        )

    elif isinstance(
        statement,
        ast.AnnAssign,
    ):
        targets.append(
            statement.target
        )

    else:
        return False

    return any(
        (
            isinstance(
                target,
                ast.Name,
            )
            and target.id
            == name
        )
        for target in targets
    )


def module_imports_name(
    tree: ast.Module,
    name: str,
) -> bool:
    """Return whether a module imports a symbol under the requested name."""
    for statement in tree.body:
        if isinstance(
            statement,
            ast.ImportFrom,
        ):
            for alias in statement.names:
                imported_name = (
                    alias.asname
                    or alias.name
                )

                if imported_name == name:
                    return True

        elif isinstance(
            statement,
            ast.Import,
        ):
            for alias in statement.names:
                imported_name = (
                    alias.asname
                    or alias.name.split(
                        "."
                    )[0]
                )

                if imported_name == name:
                    return True

    return False


def is_docstring_statement(
    statement: ast.stmt,
) -> bool:
    """Return whether a statement is a function docstring."""
    return (
        isinstance(
            statement,
            ast.Expr,
        )
        and isinstance(
            statement.value,
            ast.Constant,
        )
        and isinstance(
            statement.value.value,
            str,
        )
    )


def statement_index_calling(
    function: ast.FunctionDef,
    name: str,
) -> int | None:
    """Return the top-level statement index containing a named call."""
    for index, statement in enumerate(
        function.body
    ):
        if statement_calls(
            statement,
            name,
        ):
            return index

    return None


def engine_assignment_index(
    function: ast.FunctionDef,
) -> int | None:
    """Return the first top-level local engine assignment."""
    for index, statement in enumerate(
        function.body
    ):
        if assignment_targets_name(
            statement,
            "engine",
        ):
            return index

    return None


def expected_authentication_index(
    tree: ast.Module,
    main: ast.FunctionDef,
    path: Path,
) -> int:
    """Return where authentication must occur in main()."""
    engine_index = engine_assignment_index(
        main
    )

    if engine_index is not None:
        return (
            engine_index
            + 1
        )

    assert module_imports_name(
        tree,
        "engine",
    ), (
        f"{path}: no local engine assignment or imported engine"
    )

    if (
        main.body
        and is_docstring_statement(
            main.body[0]
        )
    ):
        return 1

    return 0


@pytest.mark.parametrize(
    "path",
    (
        *AUTHENTICATED_PAGES,
        *ADMIN_PAGES,
    ),
)
def test_protected_page_requires_authenticated_account(
    path: Path,
) -> None:
    """Every protected direct page authenticates at its entry boundary."""
    assert path.is_file()

    tree = page_tree(
        path
    )

    main = page_main_from_tree(
        tree,
        path,
    )

    auth_index = statement_index_calling(
        main,
        "require_authenticated_account",
    )

    assert auth_index is not None, (
        f"{path}: direct execution lacks authentication"
    )

    expected_index = expected_authentication_index(
        tree,
        main,
        path,
    )

    assert auth_index == expected_index, (
        f"{path}: authentication is not immediately after "
        "the page engine becomes available; "
        f"expected statement {expected_index}, "
        f"found {auth_index}"
    )


@pytest.mark.parametrize(
    "path",
    ADMIN_PAGES,
)
def test_shared_write_page_requires_system_admin(
    path: Path,
) -> None:
    """Shared reference/configuration writes require system-admin access."""
    main = page_main(
        path
    )

    auth_index = statement_index_calling(
        main,
        "require_authenticated_account",
    )

    admin_index = statement_index_calling(
        main,
        "require_system_admin",
    )

    assert auth_index is not None, (
        f"{path}: authentication is missing"
    )

    assert admin_index is not None, (
        f"{path}: shared/global write surface lacks "
        "system-admin authorization"
    )

    assert auth_index < admin_index, (
        f"{path}: admin authorization must follow authentication"
    )


def test_public_home_is_not_forced_through_private_page_guard() -> None:
    """The explicit public landing page remains independently public."""
    path = Path(
        "app/pages/1_Home.py"
    )

    source = path.read_text(
        encoding="utf-8"
    )

    assert (
        "require_system_admin("
        not in source
    )


def test_protected_page_inventory_has_no_duplicates() -> None:
    """A page cannot accidentally have conflicting authorization roles."""
    authenticated = set(
        AUTHENTICATED_PAGES
    )
    admin = set(
        ADMIN_PAGES
    )

    assert not (
        authenticated
        & admin
    )

    assert len(
        authenticated
    ) == len(
        AUTHENTICATED_PAGES
    )

    assert len(
        admin
    ) == len(
        ADMIN_PAGES
    )
