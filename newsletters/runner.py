"""Orchestrate: read mbox → extract text + images → write to DB."""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def run(mbox_path: str | Path, dry_run: bool = False, limit: int | None = None, skip: int = 0) -> int:
    """
    Process emails in an .mbox file.
    skip: skip the first N emails (by file order).
    Returns number of emails successfully processed.
    """
    from config.settings import settings
    import anthropic

    from newsletters.mbox_reader import iter_emails
    from newsletters.html_extractor import html_to_text, extract_image_urls, fetch_image_as_b64
    from newsletters.claude_extractor import extract_from_text, extract_from_images
    from newsletters.db_writer import write_newsletter

    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

    mbox_path = Path(mbox_path)
    if not mbox_path.exists():
        raise FileNotFoundError(f"mbox file not found: {mbox_path}")

    processed = 0
    skipped = 0
    file_idx = 0

    for email_dt, subject, html_body, text_body in iter_emails(mbox_path):
        if file_idx < skip:
            file_idx += 1
            continue
        file_idx += 1
        if limit and processed >= limit:
            break

        if email_dt is None:
            logger.warning("Skipping email with unparseable date: %s", subject[:60])
            skipped += 1
            continue

        email_date = email_dt.date()
        logger.info("[%s] %s", email_date, subject[:70])

        body = html_body or text_body or ""
        if not body.strip():
            logger.warning("Empty body — skipping")
            skipped += 1
            continue

        plain_text = html_to_text(html_body) if html_body else (text_body or "")

        # Text extraction
        extracted: dict = {}
        try:
            extracted = extract_from_text(plain_text, client)
            logger.info("  Text: stance=%s focus=%d portfolio=%d",
                        extracted.get("market_stance", "?"),
                        len(extracted.get("focus_list") or []),
                        len(extracted.get("portfolio_moves") or []))
        except Exception as exc:
            logger.warning("  Text extraction failed: %s", exc)

        # Vision extraction from embedded images
        # Fetch all candidate URLs, sort by file size descending, send largest first
        # (portfolio/table screenshots are typically the biggest images in the email)
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
                    vision_trades = extract_from_images(images, client)
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
        processed += 1

    logger.info("Done. Processed=%d skipped=%d", processed, skipped)
    return processed
