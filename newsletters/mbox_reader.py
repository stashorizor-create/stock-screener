"""Read emails from an .mbox file or a single .eml file."""
from __future__ import annotations

import email as _email_lib
import mailbox
from datetime import datetime
from email.header import decode_header as _decode_header_raw
from email.utils import parsedate_to_datetime
from pathlib import Path


def read_eml_bytes(data: bytes) -> tuple:
    """
    Parse a single .eml file from raw bytes.
    Returns (email_date, subject, html_body, text_body).
    """
    msg = _email_lib.message_from_bytes(data)
    return (
        _parse_date(msg.get("Date", "")),
        _decode_str(msg.get("Subject", "")),
        *_extract_bodies(msg),
    )


def iter_emails(mbox_path: str | Path):
    """
    Yield (email_date, subject, html_body, text_body) for each message.
    email_date is a datetime or None. html_body / text_body may be None.
    """
    box = mailbox.mbox(str(mbox_path))
    try:
        for msg in box:
            yield (
                _parse_date(msg.get("Date", "")),
                _decode_str(msg.get("Subject", "")),
                *_extract_bodies(msg),
            )
    finally:
        box.close()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _decode_str(value: str) -> str:
    parts = _decode_header_raw(value)
    out = []
    for chunk, charset in parts:
        if isinstance(chunk, bytes):
            out.append(chunk.decode(charset or "utf-8", errors="replace"))
        else:
            out.append(chunk)
    return " ".join(out)


def _parse_date(date_str: str) -> datetime | None:
    try:
        return parsedate_to_datetime(date_str)
    except Exception:
        return None


def _extract_bodies(msg) -> tuple[str | None, str | None]:
    html_body = None
    text_body = None

    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            if ct == "text/html" and html_body is None:
                html_body = _decode_payload(part)
            elif ct == "text/plain" and text_body is None:
                text_body = _decode_payload(part)
    else:
        ct = msg.get_content_type()
        body = _decode_payload(msg)
        if ct == "text/html":
            html_body = body
        else:
            text_body = body

    return html_body, text_body


def _decode_payload(part) -> str | None:
    payload = part.get_payload(decode=True)
    if not payload:
        return None
    charset = part.get_content_charset() or "utf-8"
    return payload.decode(charset, errors="replace")
