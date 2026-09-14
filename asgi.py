"""Compatibility ASGI entrypoint for the database-free cloud shell."""

from api.index import app


__all__ = [
    "app",
]
