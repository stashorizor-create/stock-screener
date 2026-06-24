"""
Prompt templates for the chart assessment agent.

System prompt is designed for prompt caching — it is large and static,
so Anthropic caches it across the nightly run to minimise cost.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# System prompt — cached across all calls in a nightly run
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are an expert swing trader trained in the Minervini Stage 2 \
and Qullamaggie momentum methodologies. You assess stock chart setups for a nightly \
screener that has already passed algorithmic filters. Your job is to add the judgment \
layer that an algorithm cannot — you look at the chart as a human trader would.

ASSESSMENT FRAMEWORK
====================
1. CHART FIRST — examine the image before reading any numbers.
   Ask yourself: does this look like a textbook setup, or is something off?

2. PATTERN QUALITY (1–10 scale):
   9–10 = Textbook. Tight, clean, volume perfectly confirming. Rare.
   7–8  = Strong. Minor imperfections. Worth serious attention.
   5–6  = Adequate. Passes filters but not ideal. Proceed with caution.
   3–4  = Weak. Technically passes but sloppy or extended. Flag it.
   1–2  = False positive. Should not have passed. Call it out.

3. WHAT DOWNGRADES A PATTERN:
   - MAs tangled or not in correct Stage 2 order
   - Base that looks choppy or wide rather than tight
   - Volume not confirming (up days on low vol, down days on high vol)
   - Stock extended far from pivot — risk/reward unfavourable
   - Wedging down into support rather than coiling tightly
   - Prior move too weak to justify a base breakout

4. WHAT UPGRADES A PATTERN:
   - Progressively tighter price range (true VCP compression)
   - Volume clearly drying up to multi-week lows
   - Price hugging key MAs without breaking them
   - Near all-time or 52-week highs — leadership stock
   - Strong EPS and revenue growth backing the technical setup
   - Recent insider buying or positive sentiment momentum

5. NARRATIVE — write 2–3 concise sentences a trader can act on:
   - What the chart shows (pattern quality, key level)
   - What the fundamental/sentiment context adds
   - The specific risk: what would invalidate this trade

Be direct. Do not hedge excessively. If a setup is weak, say so clearly.
Never invent data that was not provided."""

# ---------------------------------------------------------------------------
# Strategy-specific visual guidance (injected per call)
# ---------------------------------------------------------------------------

STRATEGY_GUIDANCE: dict[str, str] = {
    "vcp": """STRATEGY: Volatility Contraction Pattern (Minervini VCP)
Look for:
- 2+ successive contractions where each swing is smaller than the last (tightening coil)
- MAs stacked: price > SMA50 > SMA150 > SMA200 (Stage 2 uptrend intact)
- Volume declining through each contraction — ideally at multi-week lows near the pivot
- Current price within 5% of the pivot (consolidation high) — not extended
Red flags: contractions not genuinely tightening; price well below pivot; MAs crossed down.""",

    "qullamaggie": """STRATEGY: Qullamaggie Breakout Setup
Look for:
- A strong prior explosive move (30–70%+) before the base
- Tight, short consolidation (2–6 weeks) hugging the 10 and 20 SMA
- Volume clearly lower in the base than during the prior move
- Price coiling near the top of the base, not drifting down
Red flags: base too deep (>20% from top to bottom); price falling away from MAs; \
prior move too weak to generate real momentum.""",

    "ema_pullback": """STRATEGY: 5 EMA Pullback + Inside Day
Look for:
- A clear surge (3–5 day thrust, strong volume) shaded in the chart
- A clean, orderly pullback back to the 5 EMA — not a crash, a drift
- Today's bar is an inside day: range fully contained within yesterday's range
- Volume on the pullback lower than the surge — healthy digestion
Red flags: pullback too deep (broke 20 SMA); volume higher on down days; \
inside day range too wide (not really compressed).""",

    "gap_up": """STRATEGY: Buyable Gap Up (BGU)
Look for:
- A genuine gap: today's open above yesterday's HIGH (not just a big open)
- Close in the upper half of the day's range — buyers absorbed the gap
- Volume at least 1.5–2× the 10-day average — institutional sponsorship
- The gap itself is the entry; gap day low is the stop
Red flags: close in lower half of the range (buyers gave back gains); \
gap too large — stock already extended and may retrace the whole gap; \
low volume gap — no institutional follow-through.""",
}

# ---------------------------------------------------------------------------
# Enrichment context formatter
# ---------------------------------------------------------------------------

def _pct(v: float | None) -> str:
    if v is None:
        return "n/a"
    return f"{v:+.0%}"


def format_enrichment(sig: dict) -> str:
    """Build a compact text block summarising enrichment data for the prompt."""
    headlines = sig.get("news_headlines") or []
    lines = [
        "FUNDAMENTALS",
        f"  EPS growth   QoQ: {_pct(sig.get('eps_qoq'))}   YoY: {_pct(sig.get('eps_yoy'))}",
        f"  Revenue      QoQ: {_pct(sig.get('revenue_qoq'))}   YoY: {_pct(sig.get('revenue_yoy'))}",
        f"  Sales QoQ:   {_pct(sig.get('sales_qoq'))}",
        f"  Earnings in: {sig['earnings_days_out']}d" if sig.get("earnings_days_out") else "  Earnings:    n/a",
        "",
        "RECENT NEWS HEADLINES",
    ]
    if headlines:
        lines += [f"  - {h}" for h in headlines]
    else:
        lines.append("  n/a")
    lines += [
        "",
        "SENTIMENT",
        f"  Insider buy:        {str(sig['insider_buy_days_ago']) + 'd ago' if sig.get('insider_buy_days_ago') else 'none recent'}",
        f"  News sentiment:     {sig['news_sentiment']:+.2f}" if sig.get("news_sentiment") is not None else "  News sentiment:     n/a",
        f"  Google Trends WoW:  {sig['google_trends_chg']:+.0%}" if sig.get("google_trends_chg") is not None else "  Google Trends WoW:  n/a",
    ]
    return "\n".join(lines)


def format_signal_summary(sig: dict) -> str:
    """Build the numerical signal summary for the prompt."""
    strategy = sig.get("strategies_fired", ["unknown"])[0]
    sub = sig.get("signals", {}).get(strategy, {})

    lines = [
        f"SIGNAL SUMMARY",
        f"  Symbol:          {sig['symbol']} ({sig.get('exchange', '?')})",
        f"  Strategy:        {sig.get('alert_type', strategy)}",
        f"  Composite score: {sig.get('composite_score', 0):.0f} / 100",
        f"  Pivot price:     {sig.get('pivot_price', 'n/a')}",
        f"  Entry:           {sig.get('entry_price', 'n/a')}",
        f"  Stop:            {sig.get('stop_price', 'n/a')}",
        f"  Target:          {sig.get('target_price', 'n/a')}",
        f"  R/R:             {sig.get('risk_reward', 'n/a')}×",
        f"  RS rank:         {sig.get('rs_rank', 'n/a')}th percentile",
    ]

    # Strategy-specific details
    if strategy == "vcp":
        lines += [
            f"  Contractions:    {sub.get('n_contractions', 'n/a')}",
            f"  Vol declining:   {sub.get('volume_declining', 'n/a')}",
        ]
    elif strategy == "qullamaggie":
        lines += [
            f"  Base length:     {sub.get('base_days', 'n/a')} trading days",
            f"  Base depth:      {sub.get('base_depth_pct', 0):.0%}" if sub.get("base_depth_pct") else "",
            f"  Prior move:      {sub.get('prior_move_pct', 0):+.0%}" if sub.get("prior_move_pct") else "",
            f"  Volume drying:   {sub.get('volume_drying', 'n/a')}",
        ]
    elif strategy == "ema_pullback":
        lines += [
            f"  Surge move:      {sub.get('surge_move_pct', 0):+.0%}" if sub.get("surge_move_pct") else "",
            f"  Surge days:      {sub.get('surge_days', 'n/a')}",
            f"  Vol ratio:       {sub.get('surge_volume_ratio', 'n/a')}×",
            f"  Days since surge:{sub.get('days_since_surge', 'n/a')}",
        ]
    elif strategy == "gap_up":
        lines += [
            f"  Gap size:        {sub.get('gap_pct', 0):+.1%}" if sub.get("gap_pct") else "",
            f"  Volume ratio:    {sub.get('volume_ratio', 'n/a')}×",
        ]

    return "\n".join(l for l in lines if l)


# ---------------------------------------------------------------------------
# Full user message builder
# ---------------------------------------------------------------------------

def build_user_message(sig: dict, chart_b64: str) -> list[dict]:
    """
    Build the messages list for the Claude API call.
    Puts the chart image FIRST so the model sees it before any text.
    """
    strategy = (sig.get("strategies_fired") or ["vcp"])[0]
    guidance = STRATEGY_GUIDANCE.get(strategy, "")
    signal_text = format_signal_summary(sig)
    enrichment_text = format_enrichment(sig)

    return [
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": chart_b64,
            },
        },
        {
            "type": "text",
            "text": (
                f"{guidance}\n\n"
                f"{signal_text}\n\n"
                f"{enrichment_text}\n\n"
                "Assess this chart using the framework above. "
                "Use the submit_assessment tool to return your rating and narrative."
            ),
        },
    ]
