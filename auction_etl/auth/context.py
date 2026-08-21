"""Authenticated identity and account-authorization context."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class AuthenticatedPrincipal:
    """Normalized external OIDC identity."""

    provider: str
    subject: str
    email: str
    display_name: str


@dataclass(frozen=True, slots=True)
class AccountContext:
    """Authorized Collector Ledger account membership."""

    user_id: UUID
    account_id: UUID
    role: str
    email: str
    display_name: str
    is_system_admin: bool

    @property
    def can_manage_account(self) -> bool:
        """Return whether this member can administer the account."""
        return self.role in {"owner", "admin"}

    @property
    def can_write_shared_reference_data(self) -> bool:
        """Return whether global shared-data writes are authorized."""
        return self.is_system_admin
