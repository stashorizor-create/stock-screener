"""
Uploads generated chart PNGs to Supabase Storage and returns the public URL.
Called from run.py after each chart is saved locally.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

_client = None
_init_failed = False   # sentinel — warn once, then stay silent


def _get_client():
    global _client, _init_failed
    if _client is not None:
        return _client
    if _init_failed:
        return None
    try:
        from supabase import create_client
        from config.settings import settings
        if not settings.SUPABASE_URL or not settings.SUPABASE_SERVICE_KEY:
            logger.warning("Supabase chart upload disabled: SUPABASE_URL or SUPABASE_SERVICE_KEY not set")
            _init_failed = True
            return None
        _client = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)
        return _client
    except Exception as exc:
        logger.warning("Supabase client init failed (charts will be local only): %s", exc)
        _init_failed = True
        return None


def cleanup_old_charts(keep_days: int = 7) -> None:
    """
    Delete chart folders from Supabase Storage older than keep_days.
    Folders are named YYYY-MM-DD — anything before the cutoff is removed.
    """
    client = _get_client()
    if client is None:
        return

    cutoff = date.today() - timedelta(days=keep_days)
    try:
        folders = client.storage.from_("charts").list()
        for item in folders:
            name = item.get("name", "")
            try:
                folder_date = date.fromisoformat(name)
            except ValueError:
                continue  # not a date folder, skip
            if folder_date >= cutoff:
                continue

            # List every file inside the old folder and delete them all
            files = client.storage.from_("charts").list(name)
            paths = [f"{name}/{f['name']}" for f in files if f.get("name")]
            if paths:
                client.storage.from_("charts").remove(paths)
                logger.info("Deleted %d old charts from folder %s", len(paths), name)
    except Exception as exc:
        logger.warning("Chart cleanup failed (non-fatal): %s", exc)


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
