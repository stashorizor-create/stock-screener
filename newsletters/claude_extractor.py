"""Use Claude Haiku (text + vision) to extract structured data from newsletter content."""
from __future__ import annotations

import base64
import io
import json
import re

# Anthropic downscales any image whose long edge exceeds this before the model
# sees it. A raw phone/desktop screenshot (often 2000-4000 px wide) therefore
# arrives shrunk to the point where small table digits turn to mush and the
# model reads nothing → []. We downscale ourselves with a good resampler so the
# table text stays as legible as possible, and keep the payload under the API
# size limit.
_VISION_MAX_EDGE = 1568
_MAX_IMAGE_BYTES = 4_500_000  # Anthropic rejects images above ~5 MB; stay clear.


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_TEXT_PROMPT = """\
You are analyzing a daily trading newsletter called PrimeTrading by Alex.

Extract structured data and return ONLY valid JSON — no markdown fences, no explanation.

Schema:
{
  "market_stance": "bullish|bearish|neutral|cautious",
  "market_notes": "1-2 sentence summary of market commentary",
  "risk_environment": "risk_on|risk_off|neutral",
  "risk_rationale": "1-2 sentences: the specific fundamental/breadth/macro reasons Alex gives for this risk conclusion (e.g. breadth improving, internals weakening, macro headwinds, etc.)",
  "portfolio_table": [
    {
      "ticker": "NVDA",
      "action": "LONG",
      "entry": 211.66,
      "stop": 195.0,
      "size_pct": 8.5,
      "trim_1": 240.0,
      "trim_2": 270.0,
      "trim_3": null,
      "notes": null
    }
  ],
  "focus_list": [
    {"ticker": "NVDA", "price_level": 950.0, "notes": "optional note"}
  ],
  "portfolio_moves": [
    {"ticker": "ARM", "action": "TRIM|OUT|ADDED|NEW|HOLD", "notes": "optional"}
  ],
  "scan_21dma": ["TICKER1", "TICKER2"],
  "ep_list": ["TICKER1", "TICKER2"],
  "stalk_list": ["TICKER1", "TICKER2"]
}

Rules:
- risk_environment: "risk_on" if Alex's commentary is broadly constructive (breadth improving,
  internals healthy, macro supportive, he is adding exposure); "risk_off" if he is cautious,
  reducing exposure, or cites deteriorating internals/macro headwinds; "neutral" if mixed or
  he gives no clear directional lean on market conditions.
- Strip $ prefix from tickers (e.g. $NVDA → NVDA)
- portfolio_table: the current open positions table (entry price, stop, size %, trim targets).
  Include every row you can find. Use null for any field not visible in the text.
  Only include rows that have at least an entry price. Return [] if no portfolio table found.
- focus_list: the tickers in Alex's "FocusList" / "Focus List" (his top ideas, often
  with a price level in parentheses).
- price_level in focus_list: actual stock price in parentheses (e.g. "$LITE (22)" → 22.0).
  If the number is clearly a conviction/rating score (70-100 scale), set to null and put in notes.
- scan_21dma: the tickers listed under the heading
  "Liquid Leaders 21dma-structure Pullback scan (LONG)". This is Alex's actionable
  pullback watchlist. Include ONLY that LONG pullback scan. Do NOT include the SHORT
  scan, and do NOT include the broad "Liquid Leaders Universe (top RS)" list here.
  Return [] if the LONG scan is absent or shows "None".
- IMPORTANT: do NOT extract the broad "Liquid Leaders Universe (top RS)" list into
  scan_21dma, stalk_list, or any other field — leave it out entirely.
- stalk_list / ep_list: only populate these from sections explicitly labelled as a
  stalk list or an Episodic Pivot (EP) list of individual tickers. Leave them [] if
  no such dedicated section exists.
- Use null for any section not present in the newsletter
- If a ticker appears in multiple sections, include it in all relevant sections

NEWSLETTER TEXT:
"""

_VISION_PROMPT = """\
This image is from a swing trading newsletter and may contain a portfolio positions table.

If the image contains a table with rows of stock positions (each row has a ticker symbol \
and numeric price/metric columns), extract every row.

For each row read these fields:
- ticker: the stock symbol (e.g. NVDA, TSLA)
- action: LONG or SHORT (default LONG if column not present)
- entry: entry price as an absolute dollar number
- stop: stop loss as an absolute dollar price (not a percentage, not a distance)
- size_pct: position size as a percentage of portfolio equity (e.g. 8.5 means 8.5%)
- trim_1: first partial exit target price (absolute dollar amount)
- trim_2: second partial exit target price
- trim_3: third partial exit target price
- notes: any brief note visible in the row

Only include values you can actually read — use null for anything not visible or unclear.
Return [] for pure chart images (candlestick charts, breadth indicators) with no position rows.

Return ONLY valid JSON, no markdown:
[{"ticker": "NVDA", "action": "LONG", "entry": 211.66, "stop": 195.0, "size_pct": 8.5, "trim_1": 240.0, "trim_2": 270.0, "trim_3": null, "notes": null}]
"""


# ---------------------------------------------------------------------------
# Extraction functions
# ---------------------------------------------------------------------------

def extract_from_text(text: str, client) -> dict:
    """Extract structured newsletter data from plain text using Claude Haiku."""
    # Send the whole newsletter (capped generously). The Liquid Leaders / 21dma
    # pullback scan sections sit ~9-11k chars in, so an 8k cap silently dropped
    # them — the actionable watchlist lists never reached the model.
    resp = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=1500,
        messages=[{"role": "user", "content": _TEXT_PROMPT + text[:30000]}],
    )
    return _parse_json(resp.content[0].text, fallback={})


def extract_from_images(images: list[tuple[str, str]], client) -> list[dict]:
    """
    Extract trade tables from images using Claude Haiku vision.
    images: list of (base64_data, media_type) tuples.
    Returns flat list of trade row dicts. Per-image failures are logged and
    skipped (used in the bulk newsletter run where some images are charts).
    """
    results = []
    for b64_data, media_type in images:
        rows, err = extract_one_image(b64_data, media_type, client)
        if err:
            # Don't kill the whole run for one bad image, but make it visible.
            print(f"[vision] image skipped: {err}")
        results.extend(rows)
    return results


def extract_one_image(
    b64_data: str, media_type: str, client
) -> tuple[list[dict], str | None]:
    """
    Run vision extraction on a single image.

    Returns (rows, error). On success error is None. On failure rows is [] and
    error is a human-readable reason (oversized image, API error, model returned
    no JSON, …) so the caller can show the user *why* nothing came back instead
    of a blanket "no trades found".
    """
    try:
        b64_data, media_type = _prepare_image(b64_data, media_type)
    except Exception as exc:  # decode / re-encode problem
        return [], f"could not read image ({exc})"

    if len(b64_data) > _MAX_IMAGE_BYTES * 4 // 3:
        return [], "image is too large even after downscaling — crop to just the positions table and retry"

    try:
        resp = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=4096,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": b64_data,
                        },
                    },
                    {"type": "text", "text": _VISION_PROMPT},
                ],
            }],
        )
    except Exception as exc:
        return [], f"vision API error: {exc}"

    raw = resp.content[0].text if resp.content else ""
    rows = _parse_json(raw, fallback=None)
    if rows is None:
        snippet = (raw or "").strip().replace("\n", " ")[:160]
        return [], f"model did not return valid JSON (got: {snippet!r})"
    if not isinstance(rows, list):
        return [], "model returned JSON but not a list of positions"
    # Keep only rows that actually carry a ticker.
    rows = [r for r in rows if isinstance(r, dict) and r.get("ticker")]
    if not rows:
        return [], "no positions table detected in the image (looks like a chart or has no ticker rows)"
    return rows, None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sniff_media_type(raw: bytes, fallback: str = "image/png") -> str:
    """Identify image type from magic bytes; declared type can be wrong/empty."""
    if raw[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if raw[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if raw[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "image/webp"
    return fallback


def _prepare_image(b64_data: str, media_type: str) -> tuple[str, str]:
    """
    Downscale oversized screenshots and correct the media type from the bytes.

    Returns (base64, media_type). If Pillow is unavailable we still fix the
    media type so a mislabelled upload doesn't get rejected by the API.
    """
    raw = base64.b64decode(b64_data)
    media_type = _sniff_media_type(raw, fallback=media_type or "image/png")

    try:
        from PIL import Image
    except Exception:
        return b64_data, media_type

    img = Image.open(io.BytesIO(raw))
    long_edge = max(img.size)
    needs_resize = long_edge > _VISION_MAX_EDGE
    too_big = len(raw) > _MAX_IMAGE_BYTES
    if not needs_resize and not too_big:
        return b64_data, media_type

    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    if needs_resize:
        scale = _VISION_MAX_EDGE / long_edge
        img = img.resize(
            (max(1, int(img.width * scale)), max(1, int(img.height * scale))),
            Image.LANCZOS,
        )
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return base64.b64encode(buf.getvalue()).decode(), "image/png"


def _parse_json(text: str, fallback):
    text = (text or "").strip()
    # Strip markdown code fences if model adds them
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Model sometimes wraps the JSON in prose ("Here is the table: [...]").
    # Grab the outermost array or object and try again.
    candidate = _extract_json_blob(text)
    if candidate is not None:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass
    # Last resort: the array was truncated mid-row (hit the token cap). Recover
    # whatever complete {...} objects we can so the user still gets those rows.
    salvaged = _salvage_objects(text)
    if salvaged:
        return salvaged
    return fallback


def _salvage_objects(text: str) -> list:
    """Pull every complete top-level {...} object out of a (possibly truncated) array."""
    objs = []
    depth = 0
    in_str = False
    esc = False
    start = -1
    for i, ch in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start != -1:
                    try:
                        objs.append(json.loads(text[start:i + 1]))
                    except json.JSONDecodeError:
                        pass
                    start = -1
    return objs


def _extract_json_blob(text: str) -> str | None:
    """Return the first balanced [...] or {...} block found in text, else None."""
    starts = [i for i in (text.find("["), text.find("{")) if i != -1]
    if not starts:
        return None
    start = min(starts)
    open_ch = text[start]
    close_ch = "]" if open_ch == "[" else "}"
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None
