"""
Classifies a single stock against the current hot themes.

Uses claude-haiku (cheap + fast) to tag each passing screener candidate
with a theme key, fit strength, and a 1-2 sentence narrative explaining
why the stock benefits from that theme.
"""
from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

# Theme score mapping
FIT_SCORES: dict[str, int] = {
    "strong":     25,
    "moderate":   15,
    "tangential":  8,
    "none":        0,
}

_NO_THEME = {
    "primary_theme":   "none",
    "theme_name":      "",
    "theme_momentum":  "",
    "fit_strength":    "none",
    "theme_score":     0,
    "theme_narrative": "No current theme alignment.",
}


def classify_stock_theme(
    symbol: str,
    company_name: str,
    sector: str,
    description: str,
    themes: dict,
) -> dict:
    """
    Classify a stock against the active hot themes list.

    Args:
        symbol:       Ticker symbol.
        company_name: Full company name.
        sector:       Broad sector (e.g. "Technology").
        description:  Short business description (1-3 sentences).
        themes:       Full themes dict loaded from hot_themes.json.

    Returns dict with keys:
        primary_theme, theme_name, theme_momentum,
        fit_strength, theme_score, theme_narrative
    """
    theme_list: dict = themes.get("themes", {})
    if not theme_list:
        return dict(_NO_THEME)

    from ai.agent import _get_client
    client = _get_client()
    if client is None:
        return dict(_NO_THEME)

    themes_text = "\n".join(
        f'  "{key}" ({v.get("momentum","?")} momentum): {v["name"]} — {v["description"]}'
        for key, v in theme_list.items()
    )

    prompt = f"""HOT MARKET THEMES:
{themes_text}

STOCK:
Symbol: {symbol}
Company: {company_name}
Sector: {sector}
Business: {description}

Classify this stock against the above themes.
- primary_theme: the single best-matching theme key, or "none"
- fit_strength: "strong" (core beneficiary), "moderate" (meaningful exposure), "tangential" (some overlap), or "none"
- narrative: 1-2 sentences on specifically why this stock benefits from the theme. If none, write "No current theme alignment."

Return ONLY valid JSON, no markdown:
{{"primary_theme": "...", "fit_strength": "...", "narrative": "..."}}"""

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("```", 2)[1]
            if text.startswith("json\n"):
                text = text[5:]
        result = json.loads(text)
    except Exception as exc:
        logger.warning("Theme classification failed for %s: %s", symbol, exc)
        return dict(_NO_THEME)

    theme_key = result.get("primary_theme", "none")
    fit = result.get("fit_strength", "none")
    theme_info = theme_list.get(theme_key, {})

    return {
        "primary_theme":   theme_key,
        "theme_name":      theme_info.get("name", ""),
        "theme_momentum":  theme_info.get("momentum", ""),
        "fit_strength":    fit,
        "theme_score":     FIT_SCORES.get(fit, 0),
        "theme_narrative": result.get("narrative", _NO_THEME["theme_narrative"]),
    }
