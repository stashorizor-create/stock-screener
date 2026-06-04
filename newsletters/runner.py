"""Orchestrate: read mbox / eml → extract text + images → write to DB."""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def _make_client():
    """Build Anthropic client. Reads st.secrets first (Streamlit Cloud), then settings."""
    api_key = ""
    try:
        import streamlit as st
        api_key = st.secrets.get("ANTHROPIC_API_KEY", "")
    except Exception:
        pass
    if not api_key:
        from config.settings import settings
        api_key = settings.ANTHROPIC_API_KEY
    import anthropic
    return anthropic.Anthropic(api_key=api_key)


def _process_one(email_dt, subject, html_body, text_body, client,
                 dry_run: bool = False, portfolio_only: bool = False) -> bool:
    """
    Extract structured data from one email and write to DB.
    Returns True if processed, False if skipped.
    """
    from newsletters.html_extractor import html_to_text, extract_image_urls, fetch_image_as_b64
    from newsletters.claude_extractor import extract_from_text, extract_from_images
    from newsletters.db_writer import write_newsletter

    if email_dt is None:
        logger.warning("Skipping email with unparseable date: %s", (subject or "")[:60])
        return False

    email_date = email_dt.date()
    body = html_body or text_body or ""
    if not body.strip():
        logger.warning("Empty body — skipping")
        return False

    logger.info("[%s] %s", email_date, (subject or "")[:70])
    plain_text = html_to_text(html_body) if html_body else (text_body or "")

    extracted: dict = {}
    if not portfolio_only:
        try:
            extracted = extract_from_text(plain_text, client)
            logger.info("  Text: stance=%s focus=%d portfolio=%d",
                        extracted.get("market_stance", "?"),
                        len(extracted.get("focus_list") or []),
                        len(extracted.get("portfolio_moves") or []))
        except Exception as exc:
            logger.warning("  Text extraction failed: %s", exc)

    vision_trades: list[dict] = []
    if html_body:
        img_urls = extract_image_urls(html_body, max_images=30)
        sized_images: list[tuple[int, tuple]] = []
        for url in img_urls:
            img = fetch_image_as_b64(url)
            if img:
                sized_images.append((len(img[0]), img))
        sized_images.sort(reverse=True)
        images = [img for _, img in sized_images[:10]]
        if images:
            try:
                vision_trades = extract_from_images(images, client, context_date=email_date)
                if vision_trades:
                    logger.info("  Vision: %d trade rows extracted", len(vision_trades))
            except Exception as exc:
                logger.warning("  Vision extraction failed: %s", exc)

    write_newsletter(
        email_date=email_date,
        subject=subject,
        extracted=extracted,
        vision_trades=vision_trades,
        raw_text=plain_text,
        dry_run=dry_run,
    )
    return True


def run_eml_bytes(data: bytes, dry_run: bool = False) -> tuple[bool, str]:
    """
    Process a single .eml file from raw bytes (e.g. from a Streamlit file uploader).
    Returns (success, message).
    """
    from newsletters.mbox_reader import read_eml_bytes
    email_dt, subject, html_body, text_body = read_eml_bytes(data)
    if email_dt is None:
        return False, "Could not parse date from email — is this a valid .eml file?"
    client = _make_client()
    ok = _process_one(email_dt, subject, html_body, text_body, client, dry_run=dry_run)
    if ok:
        return True, f"Ingested {email_dt.date()} — {subject[:60]}"
    return False, "Email had no readable content."


def run_portfolio_image(
    image_data: bytes,
    media_type: str,
    email_date,
    dry_run: bool = False,
) -> tuple[bool, str]:
    """
    Run vision extraction on a single screenshot and upsert portfolio_table picks
    for the given newsletter date. Used when Substack image URLs have expired.
    Returns (success, message).
    """
    import base64
    from datetime import date as _date, datetime as _datetime
    from newsletters.claude_extractor import extract_one_image, _VISION_MODEL_ACCURATE
    from newsletters.db_writer import write_newsletter

    if isinstance(email_date, str):
        email_date = _datetime.strptime(email_date[:10], "%Y-%m-%d").date()

    client = _make_client()
    b64 = base64.b64encode(image_data).decode()
    # Manual upload: rare, accuracy-critical (dense portfolio table). Use the
    # stronger model — Haiku misreads small digits here; Sonnet reads it cleanly.
    trades, err = extract_one_image(
        b64, media_type, client, context_date=email_date, model=_VISION_MODEL_ACCURATE
    )
    if not trades:
        return False, err or "No portfolio table found in this image — make sure it shows tickers, entry prices and stops."

    write_newsletter(
        email_date=email_date,
        subject="",
        extracted={},
        vision_trades=trades,
        raw_text="",
        dry_run=dry_run,
        replace_portfolio=True,  # new upload replaces the date's positions wholesale
    )
    tickers = ", ".join(t.get("ticker", "?") for t in trades if t.get("ticker"))
    return True, f"Extracted {len(trades)} position(s): {tickers}"


def run(
    mbox_path: str | Path,
    dry_run: bool = False,
    limit: int | None = None,
    skip: int = 0,
    portfolio_only: bool = False,
) -> int:
    """
    Process emails in an .mbox file.
    Returns number of emails successfully processed.
    """
    from newsletters.mbox_reader import iter_emails

    mbox_path = Path(mbox_path)
    if not mbox_path.exists():
        raise FileNotFoundError(f"mbox file not found: {mbox_path}")

    client = _make_client()
    processed = 0
    file_idx = 0

    for email_dt, subject, html_body, text_body in iter_emails(mbox_path):
        if file_idx < skip:
            file_idx += 1
            continue
        file_idx += 1
        if limit and processed >= limit:
            break
        if _process_one(email_dt, subject, html_body, text_body, client,
                        dry_run=dry_run, portfolio_only=portfolio_only):
            processed += 1

    logger.info("Done. Processed=%d", processed)
    return processed
