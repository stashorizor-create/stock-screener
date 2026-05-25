"""
Uploads generated chart PNGs to Supabase Storage and returns the public URL.
Called from run.py after each chart is saved locally.
"""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_client = None


def _get_client():
    global _client
    if _client is not None:
        return _client
    try:
        from supabase import create_client
        from config.settings import settings
        if not settings.SUPABASE_URL or not settings.SUPABASE_SERVICE_KEY:
            return None
        _client = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)
        return _client
    except Exception as exc:
        logger.warning("Supabase client init failed: %s", exc)
        return None


def upload_chart(local_path: Path, symbol: str, run_date: str) -> str | None:
    """
    Upload chart PNG to Supabase Storage bucket 'charts'.
    Returns the public URL, or None if upload fails.
    """
    client = _get_client()
    if client is None:
        return None

    storage_path = f"{run_date}/{symbol}.png"
    try:
        with open(local_path, "rb") as f:
            data = f.read()
        client.storage.from_("charts").upload(
            path=storage_path,
            file=data,
            file_options={"content-type": "image/png", "upsert": "true"},
        )
        url = client.storage.from_("charts").get_public_url(storage_path)
        logger.info("Uploaded chart for %s → %s", symbol, url)
        return url
    except Exception as exc:
        logger.warning("Chart upload failed for %s: %s", symbol, exc)
        return None
