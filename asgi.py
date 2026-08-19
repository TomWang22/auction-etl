"""Vercel ASGI entrypoint for the Auction ETL control plane."""

from auction_etl.cloud_api import app


__all__ = [
    "app",
]
