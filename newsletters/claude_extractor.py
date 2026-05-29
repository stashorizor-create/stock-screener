"""Use Claude Haiku (text + vision) to extract structured data from newsletter content."""
from __future__ import annotations

import json
import re


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
- Strip $ prefix from tickers (e.g. $NVDA → NVDA)
- price_level: actual stock price in parentheses (e.g. "$LITE (22)" → 22.0). \
  If the number is clearly a conviction/rating score (typically 70-100 on a 0-100 scale, \
  labelled as score/rating/rank), set price_level to null and put it in notes instead.
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
    resp = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=1500,
        messages=[{"role": "user", "content": _TEXT_PROMPT + text[:8000]}],
    )
    return _parse_json(resp.content[0].text, fallback={})


def extract_from_images(images: list[tuple[str, str]], client) -> list[dict]:
    """
    Extract trade tables from images using Claude Haiku vision.
    images: list of (base64_data, media_type) tuples.
    Returns flat list of trade row dicts.
    """
    results = []
    for b64_data, media_type in images:
        try:
            resp = client.messages.create(
                model="claude-haiku-4-5",
                max_tokens=800,
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
            rows = _parse_json(resp.content[0].text, fallback=[])
            if isinstance(rows, list):
                results.extend(rows)
        except Exception:
            continue
    return results


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_json(text: str, fallback):
    text = text.strip()
    # Strip markdown code fences if model adds them
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return fallback
