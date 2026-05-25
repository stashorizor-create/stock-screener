"""
Nightly hot-theme refresher.

Fetches sector ETF performance (yfinance), StockTwits trending symbols,
and recent market headlines, then asks Claude to identify the 5-8 currently
hot investment themes. Writes the result to themes/hot_themes.json.

Run standalone:
    python -m themes.refresher
"""
from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

THEMES_FILE = Path(__file__).parent / "hot_themes.json"

SECTOR_ETFS: dict[str, str] = {
    "Technology":       "XLK",
    "Energy":           "XLE",
    "Financials":       "XLF",
    "Healthcare":       "XLV",
    "Industrials":      "XLI",
    "Consumer Disc.":   "XLY",
    "Consumer Staples": "XLP",
    "Utilities":        "XLU",
    "Real Estate":      "XLRE",
    "Materials":        "XLB",
    "Communication":    "XLC",
    "Semiconductors":   "SOXX",
    "Biotech":          "XBI",
    "Clean Energy":     "ICLN",
    "Cyber Security":   "HACK",
    "AI & Robotics":    "BOTZ",
}

NEWS_TICKERS = ["SPY", "QQQ", "XLK", "XLE", "XLF", "XLV"]


# ---------------------------------------------------------------------------
# Data fetchers
# ---------------------------------------------------------------------------

def _fetch_sector_returns() -> str:
    try:
        import yfinance as yf
    except ImportError:
        logger.warning("yfinance not installed — sector returns unavailable")
        return "Sector data unavailable."

    tickers = list(SECTOR_ETFS.values())
    try:
        raw = yf.download(tickers, period="1y", auto_adjust=True, progress=False)
        data = raw["Close"] if "Close" in raw.columns else raw
    except Exception as exc:
        logger.warning("yfinance download failed: %s", exc)
        return "Sector data unavailable."

    periods = {"1W": 5, "1M": 21, "6M": 126, "1Y": 252}
    lines = [f"{'Sector':<22} {'1W':>7} {'1M':>7} {'6M':>7} {'1Y':>7}"]
    lines.append("-" * 54)

    for sector, ticker in SECTOR_ETFS.items():
        col = data.get(ticker)
        if col is None:
            continue
        col = col.dropna()
        if len(col) < 10:
            continue
        row = f"{sector:<22}"
        for label, days in periods.items():
            if len(col) >= days + 1:
                ret = col.iloc[-1] / col.iloc[-days - 1] - 1
                sign = "+" if ret >= 0 else ""
                row += f" {sign}{ret:.1%}".rjust(8)
            else:
                row += f"{'n/a':>8}"
        lines.append(row)

    return "\n".join(lines)


def _fetch_stocktwits_trending() -> str:
    # StockTwits API now requires a paid plan — returns unavailable
    return "unavailable"


def _fetch_news_headlines() -> str:
    try:
        import yfinance as yf
    except ImportError:
        return "News unavailable."

    headlines: list[str] = []
    seen: set[str] = set()
    for ticker in NEWS_TICKERS:
        try:
            news = yf.Ticker(ticker).news or []
            for item in news[:6]:
                title = item.get("title", "")
                if title and title not in seen:
                    seen.add(title)
                    headlines.append(f"- {title}")
        except Exception:
            pass

    return "\n".join(headlines[:30]) if headlines else "No headlines available."


# ---------------------------------------------------------------------------
# Claude call
# ---------------------------------------------------------------------------

def _call_claude(sector_table: str, trending: str, headlines: str) -> dict:
    from ai.agent import _get_client
    client = _get_client()
    if client is None:
        raise RuntimeError("Anthropic client unavailable — check ANTHROPIC_API_KEY")

    today = date.today().isoformat()
    prompt = f"""You are a market analyst identifying currently hot stock market themes.

SECTOR ETF PERFORMANCE ({today}):
{sector_table}

TRENDING ON STOCKTWITS TODAY:
{trending}

RECENT MARKET HEADLINES:
{headlines}

Based on this real market data, identify 5-8 currently hot investment themes.
Prioritise themes with clear momentum: outperforming sectors, strong social chatter, and headline-driven narratives.
Include both established high-momentum themes AND emerging ones.

For each theme provide:
- A snake_case key (e.g. "ai_infrastructure")
- A display name (e.g. "AI Infrastructure")
- 2 sentences: what companies/sub-industries make up this theme, and what macro catalyst is driving it right now
- 3-5 example US-listed ticker symbols that best represent this theme
- 2-4 example European ticker symbols (LSE, Euronext, Xetra) that fit this theme — use the local exchange ticker (e.g. ASML, SAP, SHELL, SIE)
- 2-4 example Scandinavian ticker symbols (Stockholm, Oslo, Copenhagen, Helsinki) that fit this theme — use local tickers (e.g. ERIC B, VOLV B, NOVO B, EQNR)
- Momentum level: "high", "medium", or "emerging"

If a theme has no relevant European or Scandinavian stocks, return an empty list for those fields.

Return ONLY valid JSON, no commentary, no markdown fences:
{{
  "generated_at": "{today}",
  "themes": {{
    "theme_key": {{
      "name": "Display Name",
      "description": "Two sentences on the theme and its catalyst.",
      "example_tickers": ["TICK1", "TICK2", "TICK3"],
      "european_tickers": ["TICK1", "TICK2"],
      "scandinavian_tickers": ["TICK1", "TICK2"],
      "momentum": "high"
    }}
  }}
}}"""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}],
    )

    text = response.content[0].text.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("json\n"):
            text = text[5:]
    return json.loads(text)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def refresh_hot_themes() -> dict:
    """
    Full refresh: fetch market inputs → call Claude → write hot_themes.json.
    Returns the full themes dict.
    """
    logger.info("Refreshing hot themes…")

    sector_table = _fetch_sector_returns()
    logger.info("Sector ETF data fetched")

    trending = _fetch_stocktwits_trending()
    logger.info("StockTwits trending: %s", trending[:80])

    headlines = _fetch_news_headlines()
    logger.info("Headlines fetched (%d chars)", len(headlines))

    themes = _call_claude(sector_table, trending, headlines)
    THEMES_FILE.write_text(json.dumps(themes, indent=2), encoding="utf-8")

    n = len(themes.get("themes", {}))
    logger.info("Wrote %d themes to %s", n, THEMES_FILE)
    return themes


def load_hot_themes() -> dict:
    """Load themes from disk. Returns empty dict if file is missing or empty."""
    if not THEMES_FILE.exists():
        return {}
    try:
        data = json.loads(THEMES_FILE.read_text(encoding="utf-8"))
        return data if data.get("themes") else {}
    except Exception as exc:
        logger.warning("Failed to load hot_themes.json: %s", exc)
        return {}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    result = refresh_hot_themes()
    print(json.dumps(result, indent=2))
