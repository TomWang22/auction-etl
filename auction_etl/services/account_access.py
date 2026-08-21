"""Identity bootstrap and account membership authorization."""

from __future__ import annotations

import uuid

from sqlalchemy import text
from sqlalchemy.engine import Engine

from auction_etl.auth.context import (
    AccountContext,
    AuthenticatedPrincipal,
)


IDENTITY_NAMESPACE = uuid.UUID(
    "f340983d-6198-45b5-b611-b4150594361e"
)


def stable_user_id(principal: AuthenticatedPrincipal) -> uuid.UUID:
    """Return a deterministic application user ID."""
    return uuid.uuid5(
        IDENTITY_NAMESPACE,
        f"user:{principal.provider}:{principal.subject}",
    )


def stable_personal_account_id(user_id: uuid.UUID) -> uuid.UUID:
    """Return a deterministic personal-account ID."""
    return uuid.uuid5(
        IDENTITY_NAMESPACE,
        f"personal-account:{user_id}",
    )


def _account_name(principal: AuthenticatedPrincipal) -> str:
    """Return the default personal workspace name."""
    base = (
        principal.display_name
        or principal.email.split("@", 1)[0]
        or "Collector"
    )
    return f"{base}'s Collector Ledger"


def resolve_or_create_personal_account(
    engine: Engine,
    principal: AuthenticatedPrincipal,
) -> AccountContext:
    """Resolve an OIDC user and create an empty personal account if new."""
    user_id = stable_user_id(principal)
    account_id = stable_personal_account_id(user_id)

    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO identity.app_user (
                    id, provider, subject, email, display_name
                )
                VALUES (
                    :id, :provider, :subject, :email, :display_name
                )
                ON CONFLICT (provider, subject)
                DO UPDATE SET
                    email = EXCLUDED.email,
                    display_name = EXCLUDED.display_name,
                    updated_at = now()
                """
            ),
            {
                "id": user_id,
                "provider": principal.provider,
                "subject": principal.subject,
                "email": principal.email,
                "display_name": principal.display_name,
            },
        )

        actual_user_id = connection.execute(
            text(
                """
                SELECT id
                FROM identity.app_user
                WHERE provider = :provider
                  AND subject = :subject
                """
            ),
            {
                "provider": principal.provider,
                "subject": principal.subject,
            },
        ).scalar_one()

        account_id = stable_personal_account_id(actual_user_id)

        connection.execute(
            text(
                """
                INSERT INTO identity.account (
                    id, name, account_type
                )
                VALUES (
                    :id, :name, 'personal'
                )
                ON CONFLICT (id)
                DO NOTHING
                """
            ),
            {"id": account_id, "name": _account_name(principal)},
        )

        connection.execute(
            text(
                """
                INSERT INTO identity.account_member (
                    account_id, user_id, role
                )
                VALUES (
                    :account_id, :user_id, 'owner'
                )
                ON CONFLICT (account_id, user_id)
                DO NOTHING
                """
            ),
            {
                "account_id": account_id,
                "user_id": actual_user_id,
            },
        )

        row = connection.execute(
            text(
                """
                SELECT
                    u.id AS user_id,
                    m.account_id,
                    m.role,
                    u.email,
                    u.display_name,
                    u.is_system_admin
                FROM identity.app_user AS u
                JOIN identity.account_member AS m
                  ON m.user_id = u.id
                JOIN identity.account AS a
                  ON a.id = m.account_id
                WHERE u.provider = :provider
                  AND u.subject = :subject
                  AND a.account_type = 'personal'
                ORDER BY a.created_at
                LIMIT 1
                """
            ),
            {
                "provider": principal.provider,
                "subject": principal.subject,
            },
        ).mappings().one()

    return AccountContext(
        user_id=row["user_id"],
        account_id=row["account_id"],
        role=str(row["role"]),
        email=str(row["email"]),
        display_name=str(row["display_name"] or ""),
        is_system_admin=bool(row["is_system_admin"]),
    )
