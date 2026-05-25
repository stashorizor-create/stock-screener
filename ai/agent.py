"""
AI chart assessment agent.

For each screener candidate:
  1. Loads the chart PNG and encodes it for Claude's vision API
  2. Sends chart image + signal data + enrichment to Claude
  3. Receives pattern_quality (1-10) + trade narrative
  4. Computes final confidence_score
  5. Returns a structured result ready to insert into the alerts table

Uses prompt caching on the system prompt to minimise cost across a nightly run
where many signals are assessed in sequence.
"""
from __future__ import annotations

import base64
import logging
from pathlib import Path

from ai.prompt import SYSTEM_PROMPT, build_user_message

logger = logging.getLogger(__name__)

# Tool definition — Claude uses this to return structured output
_ASSESSMENT_TOOL = {
    "name": "submit_assessment",
    "description": (
        "Submit your pattern quality rating and trade narrative "
        "after assessing the chart and enrichment data."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "pattern_quality": {
                "type": "integer",
                "description": "Pattern quality score 1 (worst) to 10 (textbook setup)",
                "minimum": 1,
                "maximum": 10,
            },
            "chart_assessment": {
                "type": "string",
                "description": (
                    "1-2 sentences on what you see in the chart: "
                    "pattern clarity, MA alignment, volume behaviour."
                ),
            },
            "trade_narrative": {
                "type": "string",
                "description": (
                    "2-3 sentences combining technical + fundamental context "
                    "into a concise trade thesis a trader can act on."
                ),
            },
            "red_flags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of concerns or conditions that would invalidate the trade.",
            },
        },
        "required": ["pattern_quality", "chart_assessment", "trade_narrative", "red_flags"],
    },
}


def _load_chart_b64(chart_path: str | Path) -> str | None:
    """Read a PNG (local file or URL) and return it as a base64 string."""
    path_str = str(chart_path)
    if path_str.startswith("http"):
        try:
            import urllib.request
            with urllib.request.urlopen(path_str, timeout=15) as resp:
                return base64.standard_b64encode(resp.read()).decode("utf-8")
        except Exception as exc:
            logger.warning("Chart download failed from %s: %s", path_str, exc)
            return None
    path = Path(chart_path)
    if not path.exists():
        logger.warning("Chart not found: %s", path)
        return None
    return base64.standard_b64encode(path.read_bytes()).decode("utf-8")


def _compute_confidence(
    composite_score: float,
    pattern_quality: int,
    sig: dict,
) -> float:
    """
    Weighted confidence score combining algorithmic + AI assessment.

      60% — composite score from the screener (0-100)
      40% — AI pattern quality (1-10 scaled to 0-100)

    Enrichment boosts are reserved for Phase 3 when real data flows in.
    """
    tech_component = composite_score * 0.60
    ai_component   = (pattern_quality / 10) * 100 * 0.40
    return round(min(100.0, tech_component + ai_component), 1)


def _get_client():
    """Lazy-initialise the Anthropic client."""
    try:
        import anthropic
        from config.settings import settings
        if not settings.ANTHROPIC_API_KEY:
            logger.warning("ANTHROPIC_API_KEY not set — AI assessment unavailable")
            return None
        return anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    except Exception as exc:
        logger.warning("Anthropic client init failed: %s", exc)
        return None


def assess_signal(
    sig: dict,
    chart_path: str | Path,
    model: str = "claude-sonnet-4-6",
) -> dict | None:
    """
    Run the AI assessment for a single screener signal.

    Args:
        sig:        Full signal dict from run_all_strategies() merged with enrichment.
        chart_path: Path to the strategy chart PNG.
        model:      Claude model ID. Defaults to claude-sonnet-4-6.

    Returns:
        Dict with keys: pattern_quality, chart_assessment, trade_narrative,
        red_flags, confidence_score, ai_narrative.
        Returns None if the API key is missing or the call fails.
    """
    client = _get_client()
    if client is None:
        return None

    chart_b64 = _load_chart_b64(chart_path)
    if chart_b64 is None:
        logger.warning("Skipping AI assessment — chart file missing for %s", sig.get("symbol"))
        return None

    user_content = build_user_message(sig, chart_b64)

    try:
        response = client.messages.create(
            model=model,
            max_tokens=1024,
            system=[
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},  # cached across nightly run
                }
            ],
            tools=[_ASSESSMENT_TOOL],
            tool_choice={"type": "tool", "name": "submit_assessment"},
            messages=[{"role": "user", "content": user_content}],
        )
    except Exception as exc:
        logger.error("Claude API call failed for %s: %s", sig.get("symbol"), exc)
        return None

    # Extract the tool call result
    tool_result = next(
        (block.input for block in response.content if block.type == "tool_use"),
        None,
    )
    if tool_result is None:
        logger.warning("No tool call in response for %s", sig.get("symbol"))
        return None

    pattern_quality = int(tool_result.get("pattern_quality", 5))
    chart_assessment = tool_result.get("chart_assessment", "")
    trade_narrative  = tool_result.get("trade_narrative", "")
    red_flags        = tool_result.get("red_flags", [])

    # Combine chart assessment + narrative into a single ai_narrative field
    # (matches the alerts table column)
    ai_narrative = f"{chart_assessment} {trade_narrative}".strip()
    if red_flags:
        ai_narrative += " ⚠ " + " · ".join(red_flags)

    confidence_score = _compute_confidence(
        sig.get("composite_score", 0), pattern_quality, sig
    )

    return {
        "symbol":           sig.get("symbol"),
        "pattern_quality":  pattern_quality,
        "chart_assessment": chart_assessment,
        "trade_narrative":  trade_narrative,
        "red_flags":        red_flags,
        "ai_narrative":     ai_narrative,
        "confidence_score": confidence_score,
        "input_tokens":     response.usage.input_tokens,
        "output_tokens":    response.usage.output_tokens,
    }


def assess_batch(
    signals: list[dict],
    chart_paths: dict[str, str | Path],
    model: str = "claude-sonnet-4-6",
    min_composite_score: float = 60.0,
) -> list[dict]:
    """
    Run AI assessment on a batch of signals (e.g. full nightly run).

    Args:
        signals:            List of signal dicts.
        chart_paths:        {symbol: chart_path} mapping.
        model:              Claude model ID.
        min_composite_score: Skip signals below this threshold.

    Returns:
        List of assessment result dicts (None results are filtered out).
    """
    results = []
    for sig in signals:
        score = sig.get("composite_score", 0)
        if score < min_composite_score:
            continue
        symbol = sig.get("symbol", "?")
        chart_path = chart_paths.get(symbol)
        if not chart_path:
            logger.warning("No chart path for %s — skipping", symbol)
            continue

        logger.info("Assessing %s (composite score %.0f)…", symbol, score)
        result = assess_signal(sig, chart_path, model=model)
        if result:
            results.append(result)
            logger.info(
                "  %s → quality %d/10, confidence %.0f, tokens %d+%d",
                symbol,
                result["pattern_quality"],
                result["confidence_score"],
                result["input_tokens"],
                result["output_tokens"],
            )

    return results
