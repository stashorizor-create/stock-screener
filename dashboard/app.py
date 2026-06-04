"""
AI Stock Screener — dashboard.
Run with:  streamlit run dashboard/app.py

Layout:
  Sidebar  — filters + ranked signal list (collapses to hamburger on mobile)
  Main     — chart + trade levels + fundamentals + sentiment strips
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

# Streamlit hot-reload reruns app.py but keeps sys.modules cached, so stale
# newsletter module bytecode survives deploys. Clear both the __pycache__ dirs
# and any loaded newsletters.* modules on every run to guarantee fresh imports.
import shutil as _shutil
for _pkg in ["newsletters", "config", "data"]:
    _cache = ROOT / _pkg / "__pycache__"
    if _cache.exists():
        _shutil.rmtree(_cache, ignore_errors=True)
for _mod_name in list(sys.modules.keys()):
    if _mod_name.startswith("newsletters"):
        del sys.modules[_mod_name]

import hashlib
from datetime import datetime, timedelta, timezone

import streamlit as st
import extra_streamlit_components as stx

from dashboard.data_loader import (
    load_signals, top_overall, top_by_region,
    get_last_load_error,
    EXCHANGE_FLAGS, EXCHANGE_NAMES,
)
from dashboard.market import fetch_sector_returns
from dashboard import trades_db
from themes.refresher import load_hot_themes

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="AI Stock Screener",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="auto",
)

# Cookie manager — instantiated at module level so it persists across reruns
_cookie_mgr = stx.CookieManager(key="screener_cookies")

# ---------------------------------------------------------------------------
# Password gate with 30-day cookie remember-me
# ---------------------------------------------------------------------------

_COOKIE_NAME = "screener_auth"
_COOKIE_DAYS = 30


def _auth_token(pw: str) -> str:
    return hashlib.sha256(f"screener_v1_{pw}".encode()).hexdigest()[:32]


def _check_password() -> bool:
    if st.session_state.get("_auth_ok"):
        return True

    correct = None
    dev_mode = False
    try:
        auth_section = st.secrets.get("auth") or {}
        correct = auth_section.get("password") or st.secrets.get("password")
    except FileNotFoundError:
        dev_mode = True

    if dev_mode:
        return True

    if not correct:
        st.error("Auth not configured: add `[auth]\\npassword = \"...\"` to Streamlit Cloud secrets.")
        st.stop()

    # Check cookie — skip password form if already authenticated
    try:
        stored = _cookie_mgr.get(_COOKIE_NAME)
        if stored and stored == _auth_token(correct):
            st.session_state["_auth_ok"] = True
            return True
    except Exception:
        pass

    def _submit():
        if st.session_state.get("_pw_input") == correct:
            st.session_state["_auth_ok"] = True
            st.session_state["_set_cookie"] = True
        else:
            st.session_state["_auth_bad"] = True

    st.markdown("## AI Stock Screener")
    st.text_input("Password", type="password", key="_pw_input", on_change=_submit)
    if st.button("Login"):
        _submit()
    if st.session_state.get("_auth_bad"):
        st.error("Incorrect password.")
        st.session_state["_auth_bad"] = False

    if st.session_state.get("_auth_ok"):
        if st.session_state.pop("_set_cookie", False):
            try:
                _cookie_mgr.set(
                    _COOKIE_NAME,
                    _auth_token(correct),
                    expires_at=datetime.now(timezone.utc) + timedelta(days=_COOKIE_DAYS),
                )
            except Exception:
                pass
        st.rerun()

    return False


if not _check_password():
    st.stop()

# ---------------------------------------------------------------------------
# CSS — desktop + mobile responsive
# ---------------------------------------------------------------------------

st.markdown("""
<style>
/* Remove top padding — main and sidebar */
.block-container { padding-top: 0.5rem !important; }
section[data-testid="stSidebar"] > div:first-child { padding-top: 0.5rem !important; }

/* Make sidebar toggle button visible on mobile */
[data-testid="collapsedControl"] {
    background-color: #238636 !important;
    border-radius: 0 6px 6px 0 !important;
    opacity: 1 !important;
    width: 1.8rem !important;
    min-height: 3rem !important;
}
[data-testid="collapsedControl"] svg { fill: white !important; }

/* Metric strip */
.strip {
    display: flex;
    flex-wrap: wrap;
    background: #161b22;
    border-radius: 8px;
    margin: 5px 0;
    border: 1px solid #21262d;
}
.cell {
    flex: 1 1 0;
    min-width: 0;
    text-align: center;
    padding: 10px 6px;
    border-right: 1px solid #21262d;
    box-sizing: border-box;
}
.cell:last-child { border-right: none; }
.cell-label {
    color: #7d8590;
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.6px;
    margin-bottom: 5px;
    white-space: nowrap;
}
.cell-value { font-size: 16px; font-weight: 700; }

/* Colours */
.green  { color: #3fb950; }
.red    { color: #f85149; }
.yellow { color: #d29922; }
.grey   { color: #484f58; }
.white  { color: #e6edf3; }

/* Score bar */
.score-bar-bg {
    background: #21262d;
    border-radius: 4px;
    height: 6px;
    margin: 4px 0 12px 0;
}
.score-bar-fill { height: 6px; border-radius: 4px; }

/* Badge */
.badge {
    display: inline-block;
    border-radius: 4px;
    padding: 2px 7px;
    font-size: 11px;
    font-weight: 700;
    margin-right: 4px;
    color: #0e1117;
}

/* Strip section label */
.strip-label {
    color: #7d8590;
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.8px;
    margin: 10px 0 2px 2px;
}

/* Sidebar radio — style as list */
div[data-testid="stRadio"] > div { gap: 6px; }
div[data-testid="stRadio"] label {
    background: #161b22;
    border-radius: 6px;
    padding: 9px 12px !important;
    cursor: pointer;
    border: 1px solid transparent;
    font-size: 13px;
    line-height: 1.5;
}
div[data-testid="stRadio"] label:has(input:checked) {
    border-color: #4488FF;
    background: #1a2a4a;
}
div[data-testid="stRadio"] label > div:first-child { display: none; }
/* Rank number — muted */
div[data-testid="stRadio"] label span.rank { color: #484f58; font-size: 11px; }
/* Strategy badge inside radio label */
div[data-testid="stRadio"] label code {
    background: #21262d !important;
    border: 1px solid #30363d !important;
    border-radius: 4px !important;
    color: #8b949e !important;
    font-size: 10px !important;
    padding: 1px 5px !important;
    font-family: inherit !important;
}

/* Hide Streamlit top header, hamburger menu, and "Made with Streamlit" footer badge */
header[data-testid="stHeader"] { display: none !important; }
#MainMenu { visibility: hidden !important; }
/* Target only the branding badge — NOT the chat input container */
footer .css-164nlkn, footer .viewerBadge_container__1QSob,
footer .viewerBadge_link__1S137 { visibility: hidden !important; }
section[data-testid="stBottom"] { visibility: visible !important; }



/* Market overview button — centered glow */
div[data-testid="stButton"]:has(button p:contains("🌡️")) button {
    background: linear-gradient(135deg, #0d1b35 0%, #1a2d4a 100%) !important;
    border: 1px solid #388bfd55 !important;
    border-radius: 12px !important;
    font-size: 15px !important;
    font-weight: 700 !important;
    letter-spacing: 0.5px !important;
    box-shadow: 0 0 18px #388bfd55, 0 0 40px #388bfd22 !important;
    color: #79c0ff !important;
    padding: 14px 0 !important;
    transition: box-shadow 0.3s ease, border-color 0.3s ease !important;
}
div[data-testid="stButton"]:has(button p:contains("🌡️")) button:hover {
    box-shadow: 0 0 32px #388bfd99, 0 0 64px #388bfd44 !important;
    border-color: #388bfdaa !important;
    color: #a5d6ff !important;
}


/* Mobile: wrap strip cells to 3-per-row */
@media (max-width: 640px) {
    .cell { flex-basis: 33.33% !important; min-width: 33.33% !important; }
    .cell-value { font-size: 14px; }
    .cell-label { font-size: 9px; }
    .block-container { padding: 0.5rem 0.8rem; }
}
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Signal data (cached 5 min — refreshes automatically on rerun)
# ---------------------------------------------------------------------------

@st.cache_data(ttl=300, show_spinner=False)
def get_signals() -> tuple[list[dict], str]:
    return load_signals()


def _debug_db():
    """Call without cache to diagnose connection issues."""
    from config.settings import settings
    db_url = settings.DATABASE_URL
    if not db_url:
        return "❌ DATABASE_URL is empty — .env not loading"
    masked = db_url[:30] + "..."
    try:
        from database.models import Alert, SessionLocal
        from datetime import date
        with SessionLocal() as s:
            count = s.query(Alert).filter(Alert.date == date.today()).count()
        return f"✅ Connected ({masked}) — {count} alerts today"
    except Exception as e:
        return f"❌ DB error: {e}"


# ---------------------------------------------------------------------------
# Market overview data (cached 1 hour — daily data, no need to refresh faster)
# ---------------------------------------------------------------------------

@st.cache_data(ttl=3600, show_spinner=False)
def get_sector_returns():
    return fetch_sector_returns()


@st.cache_data(ttl=3600, show_spinner=False)
def get_hot_themes() -> dict:
    return load_hot_themes()


# ---------------------------------------------------------------------------
# Live enrichment — Google Trends + Reddit (cached 1 hour)
# ---------------------------------------------------------------------------

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_live_enrichment(symbol: str, trends_keyword: str) -> dict:
    """Fetch Google Trends and Reddit mentions. Returns partial dict of real values."""
    result: dict = {}

    # Google Trends (no credentials required)
    try:
        from enrichment.google_trends import get_trends_acceleration
        val = get_trends_acceleration(trends_keyword)
        if val is not None:
            result["google_trends_chg"] = val
    except Exception:
        pass

    # Reddit and StockTwits removed (no free API access)


    # News activity (yfinance, no credentials)
    try:
        from enrichment.news import get_news_enrichment
        news = get_news_enrichment(symbol)
        if news.get("news_sentiment") is not None:
            result["news_sentiment"] = news["news_sentiment"]
        if news.get("news_count_7d") is not None:
            result["news_count_7d"] = news["news_count_7d"]
        if news.get("news_headlines"):
            result["news_headlines"] = news["news_headlines"]
    except Exception:
        pass

    return result


# ---------------------------------------------------------------------------
# HTML helpers
# ---------------------------------------------------------------------------

BADGE_COLORS = {
    "vcp":            "#388bfd",
    "qullamaggie":    "#a371f7",
    "ema_pullback":   "#e3b341",
    "gap_up":         "#3fb950",
    "pocket_pivot":   "#f0883e",
    "sma_inside_day": "#58a6ff",
    "alex_21ema":     "#79c0ff",
}
BADGE_LABELS = {
    "vcp": "VCP", "qullamaggie": "Q", "ema_pullback": "EMA5",
    "gap_up": "BGU", "pocket_pivot": "PP", "sma_inside_day": "SMA-ID",
    "alex_21ema": "21D",
}


def badges_html(strategies: list[str]) -> str:
    return "".join(
        f'<span class="badge" style="background:{BADGE_COLORS.get(s, "#555")}">'
        f'{BADGE_LABELS.get(s, s[:3].upper())}</span>'
        for s in strategies
    )


def score_bar_html(score: float) -> str:
    color = "#3fb950" if score >= 75 else ("#e3b341" if score >= 60 else "#f85149")
    return (
        f'<div class="score-bar-bg">'
        f'<div class="score-bar-fill" style="width:{score:.0f}%;background:{color}"></div>'
        f'</div>'
    )


def _pct(v) -> str:
    if v is None:
        return '<span class="grey">—</span>'
    cls = "green" if v > 0 else ("red" if v < 0 else "grey")
    return f'<span class="{cls}">{v:+.0%}</span>'


def _sent(v) -> str:
    if v is None:
        return '<span class="grey">—</span>'
    cls = "green" if v > 0.1 else ("red" if v < -0.1 else "grey")
    return f'<span class="{cls}">{v:+.2f}</span>'


def _trend(v) -> str:
    if v is None:
        return '<span class="grey">—</span>'
    if v > 0.1:
        return f'<span class="green">↑ {v:+.0%}</span>'
    if v < -0.1:
        return f'<span class="red">↓ {v:+.0%}</span>'
    return f'<span class="grey">→ flat</span>'


def _days(v) -> str:
    if v is None:
        return '<span class="grey">—</span>'
    cls = "yellow" if v <= 14 else "white"
    return f'<span class="{cls}">{v:.0f}d</span>'


def _mentions(v) -> str:
    if v is None:
        return '<span class="grey">—</span>'
    return f'<span class="white">↑ {v:,}</span>'


def _insider(days_ago) -> str:
    if days_ago is None:
        return '<span class="grey">—</span>'
    return f'<span class="green">✓ {days_ago}d ago</span>'


def _price_fmt(sig: dict, price: float | None) -> str:
    if price is None:
        return "—"
    sym = {"USD": "$", "EUR": "€", "GBP": "£", "CHF": "CHF ", "DKK": "kr", "SEK": "kr", "NOK": "kr"}.get(sig["currency"], "")
    return f"{sym}{price:,.2f}"


def strip_html(cells: list[tuple[str, str]]) -> str:
    inner = "".join(
        f'<div class="cell">'
        f'<div class="cell-label">{lbl}</div>'
        f'<div class="cell-value">{val}</div>'
        f'</div>'
        for lbl, val in cells
    )
    return f'<div class="strip">{inner}</div>'


def expand_to_rows(signals: list[dict]) -> list[dict]:
    """One row per (stock, strategy) — multi-strategy stocks get a separate row each."""
    rows = []
    for sig in signals:
        strats = sig.get("strategies_fired", [])
        if len(strats) <= 1:
            rows.append(sig)
            continue
        for strat in strats:
            detail = sig.get("signals", {}).get(strat, {})
            row = {**sig, "strategies_fired": [strat]}
            if detail.get("pivot_price"):
                row["entry_price"] = detail["pivot_price"]
            elif detail.get("entry_trigger"):
                row["entry_price"] = detail["entry_trigger"]
            # Use the focused per-strategy chart if the pipeline generated one
            per_chart = sig.get(f"chart_{strat}")
            if per_chart:
                row["chart_image_path"] = per_chart
            rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Strategy reference material — injected into chat system prompt
# ---------------------------------------------------------------------------

_STRATEGY_REFS: dict[str, str] = {
    "alex_21ema": (
        "--- PrimeTrading Wiki Reference (traderslab.gitbook.io/primetrading) ---\n"
        "ZONE: 21EMA cloud = EMA21(lows) + EMA21(highs) + EMA21(close). "
        "Cloud low = structural stop; cloud high = upper validity boundary. "
        "Only trade within 1×ATR of the zone.\n\n"
        "PATTERNS:\n"
        "- P1 — Pullback Into Rising Structure: Confirmed uptrend, price pulls back into rising cloud. "
        "Clean bounce or retest forming higher low. Highest historical win rate. Most aggressive positioning.\n"
        "- P2 — Reclaim & Backtest: Price reclaims cloud after a correction, retests forming a 'structure higher low.' "
        "Downtrend losing control. Early positioning, well-defined risk. Alex's favourite (trapped shorts).\n"
        "- P3 — Reject & Higher Low: Price fails to reclaim cloud but forms higher low underneath. "
        "Cautious pilot positions only if leadership confirms.\n"
        "- P4 — Reject & Lower Low: Downtrend in full control. Avoid.\n\n"
        "ENTRY TYPES:\n"
        "- Weakness into structure (R2G): Buy weakness directly against cloud. Best R/R. "
        "Risk 0.25% per trade. Powerful on red-to-green opens in strong markets.\n"
        "- Strength confirmation: Daily reversal / prior day high reclaim, cloud-high reclaim, "
        "DTL or base breakout. Higher conviction, reduced R/R. Risk 0.5% per trade.\n"
        "- Constraint: Do NOT engage if price is more than 1×ATR above cloud high.\n\n"
        "STOP: 21EMA low band (cloud bottom). Daily close below = exit. "
        "Soft stops preferred over hard orders.\n\n"
        "POSITION MANAGEMENT: After 2R trim (sell ⅓), trail remaining ⅔ with "
        "daily close below cloud as stop — allows multi-week trend capture.\n"
        "---"
    ),
    "vcp": (
        "--- Reference: Mark Minervini — 'Trade Like a Stock Market Wizard' ---\n"
        "VCP (Volatility Contraction Pattern): Series of price contractions getting tighter in range "
        "and lower in volume, coiling into a pivot buy point. Entry at pivot breakout on volume surge "
        "≥40-50% above average. Stop below the lowest low of the tightest contraction.\n"
        "---"
    ),
    "qullamaggie": (
        "--- Reference: Kristjan Kullamaggie momentum strategy ---\n"
        "Episodic pivot: stock surges 30%+ on a catalyst, bases 10-30 days on low volume drying up, "
        "then breaks out above base high. Entry at base breakout. Stop below base low. "
        "Highest win rate when base is tight and volume disappears completely near the pivot.\n"
        "---"
    ),
    "ema_pullback": (
        "--- Reference: 5 EMA Pullback (momentum continuation) ---\n"
        "After a strong surge (≥7%, 3+ days, volume ≥1.4× average), stock consolidates with an inside day "
        "at or near the 5 EMA. Entry above inside day high. Stop below inside day low. "
        "Ideally within 20 days of the surge.\n"
        "---"
    ),
    "sma_inside_day": (
        "--- Reference: SMA Inside Day (deeper momentum continuation) ---\n"
        "Same surge prerequisite as 5 EMA Pullback but price has pulled back deeper to the 20 or 50 SMA. "
        "Inside day forms within 3 sessions of the SMA touch. Entry above inside day high. "
        "Stop below inside day low or the SMA.\n"
        "---"
    ),
    "gap_up": (
        "--- Reference: IBD Buyable Gap Up ---\n"
        "Strong gap open above prior resistance on heavy volume (≥150% of 10-day average), "
        "closing in upper 50% of the day's range. Entry anywhere in the gap range on the gap day. "
        "Stop at gap day low.\n"
        "---"
    ),
    "pocket_pivot": (
        "--- Reference: Chris Kacher & Gil Morales — 'Trade Like an O'Neil Disciple' ---\n"
        "Pocket Pivot: volume on an up day exceeds the maximum volume on any down day in the prior "
        "10 sessions, while price is near a key moving average (10 or 21 SMA/EMA). "
        "Signals institutional accumulation before a visible breakout.\n"
        "---"
    ),
}


# Claude chat helper — defined here so it's available throughout the script
# ---------------------------------------------------------------------------

def _call_claude_chat(
    sig: dict,
    chart_path: str | None,
    history: list[dict],
    user_message: str,
) -> str:
    """Call Claude with chart image + signal context + conversation history."""
    import base64

    try:
        import anthropic
    except ImportError:
        return "anthropic package not installed."

    api_key = None
    try:
        api_key = st.secrets.get("ANTHROPIC_API_KEY")
    except Exception:
        pass
    if not api_key:
        try:
            from config.settings import settings
            api_key = settings.ANTHROPIC_API_KEY
        except Exception:
            pass
    if not api_key:
        return "ANTHROPIC_API_KEY not configured — add it to Streamlit Cloud secrets."

    # Build chart content block once (attached to first user message only)
    chart_block = None
    _is_url   = chart_path and chart_path.startswith("http")
    _is_local = chart_path and not _is_url and Path(chart_path).exists()
    if _is_url:
        chart_block = {"type": "image", "source": {"type": "url", "url": chart_path}}
    elif _is_local:
        with open(chart_path, "rb") as _f:
            _b64 = base64.standard_b64encode(_f.read()).decode()
        chart_block = {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": _b64}}

    strats = sig.get("strategies_fired", [])
    _sys_theme    = sig.get("theme_name") or ""
    _sys_theme_nr = sig.get("theme_narrative") or ""
    _sys_news     = sig.get("news_headlines") or []
    _sys_eps      = sig.get("eps_yoy")
    _sys_rev      = sig.get("revenue_yoy")
    _sys_earn     = sig.get("earnings_days_out")

    _theme_line = (
        f"- Theme: {_sys_theme}" + (f" — {_sys_theme_nr}" if _sys_theme_nr else "") + "\n"
    ) if _sys_theme else ""
    _fund_line = (
        f"- Fundamentals: EPS YoY {_sys_eps:+.0%}" if _sys_eps is not None else "- Fundamentals: EPS YoY n/a"
    ) + (f", Rev YoY {_sys_rev:+.0%}" if _sys_rev is not None else ", Rev YoY n/a") + (
        f", earnings in {_sys_earn}d" if _sys_earn else ""
    ) + "\n"
    _news_line = (
        "- Recent news:\n" + "\n".join(f"  • {h}" for h in _sys_news[:5]) + "\n"
    ) if _sys_news else ""

    _refs = "\n\n".join(_STRATEGY_REFS[s] for s in strats if s in _STRATEGY_REFS)
    _refs_block = f"\nStrategy reference material:\n{_refs}\n" if _refs else ""

    system = (
        f"You are a swing trading analyst helping review {sig['symbol']} "
        f"({sig.get('company_name', sig['symbol'])}, {sig.get('exchange', '?')}).\n"
        f"Signal data:\n"
        f"- Strategies: {', '.join(strats) or 'n/a'}\n"
        f"- Composite score: {sig.get('composite_score', '?')}/100\n"
        f"- Entry: {sig.get('entry_price', '?')}, Stop: {sig.get('stop_price', '?')}, "
        f"Target: {sig.get('target_price', '?')}\n"
        f"- RS Rank: {sig.get('rs_rank', '?')}th percentile\n"
        + _theme_line + _fund_line + _news_line
        + _refs_block
        + "The chart image may be attached. When discussing entries, stops, or pattern behaviour, "
        "cite the relevant strategy reference above (including the wiki URL for alex_21ema). "
        "Discuss macro context, news, and fundamentals alongside technicals. "
        "Be concise and actionable for a swing trader."
    )

    # Reconstruct message list — chart block attaches to the very first user message
    messages: list[dict] = []
    if history:
        first = history[0]
        first_content = (
            [chart_block, {"type": "text", "text": first["content"]}]
            if chart_block else first["content"]
        )
        messages.append({"role": "user", "content": first_content})
        for _m in history[1:]:
            messages.append({"role": _m["role"], "content": _m["content"]})
        messages.append({"role": "user", "content": user_message})
    else:
        # First turn in this conversation — attach chart here
        content = (
            [chart_block, {"type": "text", "text": user_message}]
            if chart_block else user_message
        )
        messages.append({"role": "user", "content": content})

    client = anthropic.Anthropic(api_key=api_key)
    resp = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        system=system,
        messages=messages,
    )
    return resp.content[0].text


# ---------------------------------------------------------------------------
# Load signals
# ---------------------------------------------------------------------------

ALL_SIGNALS, _data_source = get_signals()
ALL_ROWS = ALL_SIGNALS
sig = None  # defined in sidebar when signals exist; checked in main content

STRAT_MAP = {
    "VCP": "vcp", "Qullamaggie": "qullamaggie",
    "5 EMA Pullback": "ema_pullback", "Buyable Gap Up": "gap_up",
    "Pocket Pivot": "pocket_pivot", "SMA Inside Day": "sma_inside_day",
}

_selected_newsletter_date: str | None = None

# ---------------------------------------------------------------------------
# Newsletter data loaders (defined before sidebar so sidebar can call them)
# ---------------------------------------------------------------------------

def _supa_client():
    """Return (client, err_str | None)."""
    try:
        from supabase import create_client
        supa_url = ""
        supa_key = ""
        try:
            supa_url = st.secrets.get("SUPABASE_URL", "")
            supa_key = (st.secrets.get("SUPABASE_KEY") or
                        st.secrets.get("SUPABASE_SERVICE_KEY") or "")
        except Exception:
            pass
        if not supa_url or not supa_key:
            from config.settings import settings
            supa_url = supa_url or settings.SUPABASE_URL
            supa_key = supa_key or settings.SUPABASE_SERVICE_KEY
        if not supa_url or not supa_key:
            return None, "SUPABASE_URL / SUPABASE_KEY not configured"
        return create_client(supa_url, supa_key), None
    except Exception as _e:
        return None, str(_e)


@st.cache_data(ttl=600, show_spinner=False)
def get_newsletter_dates() -> list[str]:
    """Return list of newsletter dates (ISO strings), newest first."""
    client, err = _supa_client()
    if err or client is None:
        return []
    try:
        r = (client.table("newsletter_market")
             .select("email_date")
             .order("email_date", desc=True)
             .limit(60)
             .execute())
        return [row["email_date"] for row in (r.data or [])]
    except Exception:
        return []


@st.cache_data(ttl=300, show_spinner=False)
def get_newsletter(date: str | None = None) -> tuple[dict | None, list[dict]]:
    """Load newsletter for a specific date (or latest if None)."""
    try:
        client, err = _supa_client()
        if err or client is None:
            return None, [{"_error": err or "Supabase unavailable"}]

        if date:
            r = (client.table("newsletter_market")
                 .select("id,email_date,subject,market_stance,market_notes,risk_environment,risk_rationale")
                 .eq("email_date", date)
                 .limit(1)
                 .execute())
        else:
            r = (client.table("newsletter_market")
                 .select("id,email_date,subject,market_stance,market_notes,risk_environment,risk_rationale")
                 .order("email_date", desc=True)
                 .limit(1)
                 .execute())
        if not r.data:
            return None, []

        market = r.data[0]
        email_date = market["email_date"]

        r2 = (client.table("newsletter_picks")
              .select("id,email_date,ticker,action,entry_date,entry_price,stop_price,"
                      "target_price,trim_2,trim_3,position_size_pct,notes,source_section")
              .eq("email_date", email_date)
              .order("source_section")
              .order("ticker")
              .execute())
        picks = r2.data or []
        return market, picks
    except Exception as _e:
        return None, [{"_error": str(_e)}]


@st.cache_data(ttl=300, show_spinner=False)
def get_forward_tests(email_date: str) -> list[dict]:
    """Load forward test metrics for a newsletter date."""
    client, err = _supa_client()
    if err or client is None:
        return []
    try:
        r = (client.table("newsletter_forward_tests")
             .select("ticker,action,entry_price,stop_price,trim_1,trim_2,trim_3,"
                     "current_price,current_return_pct,r_multiple,"
                     "stop_hit,stop_hit_date,max_mfe_pct,days_held,status")
             .eq("email_date", email_date)
             .order("ticker")
             .execute())
        return r.data or []
    except Exception:
        return []


@st.cache_data(ttl=300, show_spinner=False)
def get_ohlcv_for_chart(ticker: str, from_date: str) -> list[dict]:
    """Load OHLCV rows for a ticker from from_date onwards (for charting)."""
    client, err = _supa_client()
    if err or client is None:
        return []
    try:
        r = (client.table("ohlcv")
             .select("date,open,high,low,close")
             .eq("symbol", ticker)
             .gte("date", from_date)
             .order("date")
             .limit(300)
             .execute())
        return r.data or []
    except Exception:
        return []


@st.cache_data(ttl=3600, show_spinner=False)
def get_track_record() -> dict:
    """Compute cumulative performance stats from all forward tests."""
    client, err = _supa_client()
    if err or client is None:
        return {"error": err or "Supabase unavailable"}
    try:
        r = (client.table("newsletter_forward_tests")
             .select("ticker,email_date,entry_price,current_return_pct,r_multiple,"
                     "stop_hit,max_mfe_pct,days_held")
             .limit(2000)
             .execute())
        rows = r.data or []
        if not rows:
            return {}

        import statistics
        valid = [
            row for row in rows
            if (row.get("entry_price") or 0) >= 5
            and row.get("current_return_pct") is not None
            and -100 <= row["current_return_pct"] <= 500
        ]
        if not valid:
            return {}

        returns   = [v["current_return_pct"] for v in valid]
        r_mults   = [v["r_multiple"] for v in valid if v.get("r_multiple") is not None]
        max_gains = [v["max_mfe_pct"] for v in valid if v.get("max_mfe_pct") is not None]
        winners   = sum(1 for r in returns if r > 0)
        stopped   = sum(1 for v in valid if v.get("stop_hit"))

        by_ret = sorted(valid, key=lambda v: v["current_return_pct"], reverse=True)
        return {
            "total":        len(valid),
            "win_rate":     winners / len(valid),
            "avg_ret":      sum(returns) / len(returns),
            "median_ret":   statistics.median(returns),
            "avg_r":        sum(r_mults) / len(r_mults) if r_mults else None,
            "stop_rate":    stopped / len(valid),
            "avg_max_gain": sum(max_gains) / len(max_gains) if max_gains else None,
            "returns":      returns,
            "best_5":       by_ret[:5],
            "worst_5":      list(reversed(by_ret[-5:])),
        }
    except Exception as exc:
        return {"error": str(exc)}


@st.cache_data(ttl=600, show_spinner=False)
def get_watchlist_tickers(email_date: str) -> list[dict]:
    """Get watchlist tickers (scan_21dma, focus_list, stalklist) for a newsletter date."""
    client, err = _supa_client()
    if err or client is None:
        return []
    try:
        r = (client.table("newsletter_picks")
             .select("ticker,source_section,action")
             .eq("email_date", email_date)
             .in_("source_section", ["scan_21dma", "focus_list", "stalklist"])
             .execute())
        picks = r.data or []
        # Deduplicate by ticker, keeping highest-priority section
        priority = {"scan_21dma": 0, "focus_list": 1, "stalklist": 2}
        seen: dict[str, dict] = {}
        for p in picks:
            t = p["ticker"]
            if t not in seen or priority.get(p["source_section"], 9) < priority.get(seen[t]["source_section"], 9):
                seen[t] = p
        return list(seen.values())
    except Exception:
        return []


@st.cache_data(ttl=3600, show_spinner=False)
def get_pick_entry_date(ticker: str) -> str | None:
    """Return the earliest newsletter date this ticker appeared in portfolio_table with an entry price."""
    client, err = _supa_client()
    if err or client is None:
        return None
    try:
        r = (client.table("newsletter_picks")
             .select("email_date")
             .eq("ticker", ticker)
             .eq("source_section", "portfolio_table")
             .not_.is_("entry_price", "null")
             .order("email_date")
             .limit(1)
             .execute())
        rows = r.data or []
        return str(rows[0]["email_date"]) if rows else None
    except Exception:
        return None


@st.cache_data(ttl=600, show_spinner=False)
def get_trim_history(ticker: str) -> list[dict]:
    """Return all TRIM/OUT/ADDED actions for a ticker across all newsletters, oldest first."""
    client, err = _supa_client()
    if err or client is None:
        return []
    try:
        r = (client.table("newsletter_picks")
             .select("email_date,action,notes")
             .eq("ticker", ticker)
             .in_("action", ["TRIM", "OUT", "ADDED"])
             .order("email_date")
             .execute())
        return r.data or []
    except Exception:
        return []


@st.cache_data(ttl=3600, show_spinner=False)
def compute_watchlist_ohlcv(tickers: tuple[str, ...]) -> dict[str, dict]:
    """
    Fetch OHLCV via Borsdata API for each ticker and compute EMA21 cloud scores.
    Returns {ticker: {df_records, score_dict, error}}.
    """
    import pandas as pd
    from datetime import date, timedelta
    from data.ingestor import BorsdataClient

    # ── Build ticker → Borsdata insId map (US markets only) ─────────────────
    _US_MARKET_IDS = {29, 32, 33, 34}
    sym_to_id: dict[str, int] = {}
    try:
        client = BorsdataClient()
        df_global = client.get_instruments_global()
        if not df_global.empty:
            df_us = df_global[df_global["marketId"].isin(_US_MARKET_IDS)]
            for _, row in df_us.iterrows():
                sym = str(row.get("ticker") or "").upper().strip()
                if sym:
                    sym_to_id[sym] = int(row["insId"])
    except Exception as exc:
        return {"_error": str(exc)}

    from_date = date.today() - timedelta(days=200)

    def _score(df: pd.DataFrame) -> dict:
        if len(df) < 30:
            return {"total": 0}
        df = df.copy()
        df["ema_21"]      = df["close"].ewm(span=21, adjust=False).mean()
        df["ema_21_high"] = df["high"].ewm(span=21,  adjust=False).mean()
        df["ema_21_low"]  = df["low"].ewm(span=21,   adjust=False).mean()
        prev_close        = df["close"].shift(1)
        tr = pd.concat([
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"]  - prev_close).abs(),
        ], axis=1).max(axis=1)
        df["atr_14"]     = tr.rolling(14).mean()
        df["vol_sma_20"] = df["volume"].rolling(20).mean()
        df["sma_50"]     = df["close"].rolling(50).mean()

        last    = df.iloc[-1]
        close   = float(last["close"])
        ema_mid = float(last["ema_21"])
        ema_hi  = float(last["ema_21_high"])
        ema_lo  = float(last["ema_21_low"])
        atr     = float(last["atr_14"])
        vol_s20 = float(last["vol_sma_20"])
        sma_50  = float(last["sma_50"])

        # 1. Rising cloud
        prev_mid  = float(df["ema_21"].iloc[-6]) if len(df) >= 6 else ema_mid
        rising    = ema_mid > prev_mid
        slope_pct = (ema_mid - prev_mid) / prev_mid * 100 if prev_mid > 0 else 0.0
        s_rising  = min(25.0, slope_pct * 5) if rising else 0.0

        # 2. Price in zone
        in_zone = ema_lo <= close <= ema_hi + atr
        below   = close < ema_lo
        if below:
            s_prox = 0.0
        elif close <= ema_hi:
            span   = max(ema_hi - ema_lo, 0.001) + atr
            s_prox = max(0.0, min(25.0, (1.0 - (close - ema_lo) / span) * 25))
        else:
            s_prox = max(0.0, 25.0 * (1.0 - (close - ema_hi) / atr))

        # 3. Higher lows
        lows   = df["low"].iloc[-20:].values
        swings = [lows[i] for i in range(1, len(lows) - 1)
                  if lows[i] <= lows[i - 1] and lows[i] <= lows[i + 1]]
        if len(swings) >= 2:
            hl1         = swings[-1] > swings[-2]
            hl2         = len(swings) >= 3 and swings[-2] > swings[-3]
            s_hl        = 20.0 if (hl1 and hl2) else (15.0 if hl1 else 0.0)
            higher_lows = hl1
        else:
            s_hl        = 10.0
            higher_lows = None

        # 4. Pullback volume
        w  = df.iloc[-15:]
        dn = w[w["close"] < w["close"].shift(1)]
        if len(dn) > 0 and vol_s20 > 0:
            ratio = float(dn["volume"].mean()) / vol_s20
            s_vol = 20.0 if ratio < 0.6 else (15.0 if ratio < 0.75 else (10.0 if ratio < 1.0 else 0.0))
        else:
            ratio = None
            s_vol = 10.0

        # 5. Compression
        rng   = float((df["high"].iloc[-5:] - df["low"].iloc[-5:]).mean())
        comp  = rng / atr if atr > 0 else 1.0
        s_cmp = 20.0 if comp < 0.7 else (15.0 if comp < 0.85 else (10.0 if comp < 1.0 else 0.0))

        return {
            "total":       round(s_rising + s_prox + s_hl + s_vol + s_cmp, 1),
            "rising":      rising,
            "slope_pct":   round(slope_pct, 2),
            "in_zone":     in_zone,
            "below_cloud": below,
            "higher_lows": higher_lows,
            "vol_ratio":   round(ratio, 2) if ratio is not None else None,
            "comp_ratio":  round(comp, 2),
            "close":       round(close, 2),
            "ema_hi":      round(ema_hi, 2),
            "ema_mid":     round(ema_mid, 2),
            "ema_lo":      round(ema_lo, 2),
            "atr":         round(atr, 2),
            "sma_50":      round(sma_50, 2),
            "entry":       round(ema_hi, 2),
            "stop":        round(ema_lo, 2),
            "scores":      {"rising": s_rising, "proximity": s_prox,
                            "higher_lows": s_hl, "volume": s_vol, "compression": s_cmp},
        }

    results: dict[str, dict] = {}
    for ticker in tickers:
        bid = sym_to_id.get(ticker.upper())
        if not bid:
            results[ticker] = {"df": None, "score": {"total": 0}, "error": f"No Borsdata ID for {ticker}"}
            continue
        try:
            df = client.get_ohlcv(bid, from_date=from_date, max_count=200)
            if df.empty or len(df) < 30:
                results[ticker] = {"df": None, "score": {"total": 0}, "error": "insufficient data"}
                continue
            df = df.reset_index(drop=True)
            if hasattr(df["date"].iloc[0], "strftime"):
                df["date"] = df["date"].apply(lambda d: d.strftime("%Y-%m-%d"))
            else:
                df["date"] = df["date"].astype(str)
            score = _score(df)
            results[ticker] = {
                "df":    df.tail(80).to_dict("records"),
                "score": score,
                "error": None,
            }
        except Exception as exc:
            results[ticker] = {"df": None, "score": {"total": 0}, "error": str(exc)}

    return results


# ---------------------------------------------------------------------------
# Sidebar — filters + ranked list
# ---------------------------------------------------------------------------

with st.sidebar:
    _run_date = ALL_SIGNALS[0].get("date", "—") if ALL_SIGNALS else "—"
    _source_label = "live" if _data_source == "live" else "mock data"
    st.caption(f"Last updated: {_run_date}  ·  {_source_label}")

    # Top-level page selector
    _page = st.radio(
        "page", ["📊 Screener", "📧 Alex's Picks"],
        horizontal=True, label_visibility="collapsed",
        key="page_selector",
    )

    if _page == "📧 Alex's Picks":
        st.divider()
        st.caption("PrimeTrading newsletter by Alex")
        _nl_dates = get_newsletter_dates()
        if len(_nl_dates) > 1:
            _selected_newsletter_date = st.selectbox(
                "Edition", _nl_dates, index=0, format_func=str, key="nl_date_sel",
                label_visibility="collapsed",
            )
        elif _nl_dates:
            _selected_newsletter_date = _nl_dates[0]
    else:
        if _data_source == "mock":
            _err = get_last_load_error()
            st.warning(_err if _err else "Showing mock data")
            st.info(_debug_db())

        # Region selector — Nordic is primary
    _REGION_EXCHANGES = {
        "Nordic":  {"STO", "OSL", "CPH", "HEL"},
        "Europe":  {"PAR", "AMS", "MIL", "MAD", "BRU", "LON", "CHE"},
        "US":      {"NYSE", "NASDAQ"},
        "All":     None,
    }
    _REGION_EXCH_OPTIONS = {
        "Nordic":  ["All", "STO", "OSL", "CPH", "HEL"],
        "Europe":  ["All", "PAR", "AMS", "MIL", "MAD", "BRU", "LON", "CHE"],
        "US":      ["All", "NYSE", "NASDAQ"],
        "All":     ["All", "STO", "OSL", "CPH", "HEL", "PAR", "AMS", "MIL", "MAD", "BRU", "LON", "CHE", "NYSE", "NASDAQ"],
    }
    region_filter = st.radio(
        "Region", ["Nordic", "Europe", "US", "All"],
        horizontal=True, index=0, label_visibility="collapsed",
    )

    # Filters — compact layout, no divider needed before them
    _fc1, _fc2 = st.columns(2)
    with _fc1:
        strat_filter = st.selectbox(
            "Strategy",
            ["All", "VCP", "Qullamaggie", "5 EMA Pullback", "Buyable Gap Up", "Pocket Pivot", "SMA Inside Day"],
            label_visibility="collapsed",
        )
    with _fc2:
        exch_filter = st.selectbox(
            "Exchange", _REGION_EXCH_OPTIONS[region_filter],
            label_visibility="collapsed",
            key=f"exch_sel_{region_filter}",
        )
    min_score = st.slider("Min score", 0, 100, 60, format="≥ %d")

    _region_set = _REGION_EXCHANGES[region_filter]
    filtered = [
        s for s in ALL_ROWS
        if s["composite_score"] >= min_score
        and (strat_filter == "All" or STRAT_MAP.get(strat_filter) in s["strategies_fired"])
        and (exch_filter == "All" or s["exchange"] == exch_filter)
        and (_region_set is None or s["exchange"] in _region_set)
    ]

    unique_stocks = len({s["symbol"] for s in filtered})
    st.markdown(
        f"**{len(filtered)} signal{'s' if len(filtered) != 1 else ''}** "
        f"<span style='color:#7d8590;font-size:12px'>({unique_stocks} stock{'s' if unique_stocks != 1 else ''})</span>",
        unsafe_allow_html=True,
    )

    if not filtered:
        st.warning("No signals match filters.")
        if _page != "📧 Alex's Picks":
            st.stop()

    # TradingView watchlist download
    _TV_EXCH = {
        "STO": "OMX", "OSL": "OSL", "CPH": "OMXCOP", "HEL": "OMXHEX",
        "NYSE": "NYSE", "NASDAQ": "NASDAQ",
        "LON": "LSE", "PAR": "EURONEXT", "AMS": "EURONEXT",
        "MIL": "MIL", "MAD": "BME", "BRU": "EURONEXT", "CHE": "SIX",
    }
    _seen_syms: set[str] = set()
    _tv_lines: list[str] = []
    for _s in filtered:
        if _s["symbol"] not in _seen_syms:
            _tv_exch = _TV_EXCH.get(_s.get("exchange", ""), _s.get("exchange", ""))
            _tv_lines.append(f"{_tv_exch}:{_s['symbol']}" if _tv_exch else _s["symbol"])
            _seen_syms.add(_s["symbol"])
    _tv_suffix = "_US" if region_filter == "US" else ""
    st.download_button(
        "📥 TradingView watchlist",
        data="\n".join(_tv_lines),
        file_name=f"watchlist_{_run_date}{_tv_suffix}.txt",
        mime="text/plain",
        use_container_width=True,
        help="Import in TradingView: Watchlists → ··· → Import list",
    )

    score_color_char = lambda s: ("🟢" if s >= 75 else ("🟡" if s >= 60 else "🔴"))
    labels = [
        f"#{i+1} {score_color_char(s['composite_score'])} **{s['symbol']}**"
        f" `{'|'.join(BADGE_LABELS.get(st, '?') for st in s.get('strategies_fired', [])[:3]) or '?'}`"
        f" {s['composite_score']:.0f}"
        for i, s in enumerate(filtered)
    ]

    if filtered:
        chosen = st.radio("Signals", labels, label_visibility="collapsed")
        sig = filtered[labels.index(chosen)]

        st.divider()
        if st.button("🌡️  Market Overview", key="market_toggle", use_container_width=True):
            st.session_state["market_open"] = not st.session_state.get("market_open", False)
        if st.button("📒  My Trades", key="trades_toggle", use_container_width=True):
            st.session_state["trades_open"] = not st.session_state.get("trades_open", False)


def _render_newsletter_page(sel_date: str | None = None):
    import plotly.graph_objects as go

    st.markdown("## Alex's Picks — PrimeTrading")

    # ── .eml upload ────────────────────────────────────────────────────────────
    with st.expander("📥 Add new newsletter (.eml)", expanded=False):
        st.caption("In Gmail: open the email → ⋮ menu → Download message → drag the .eml file here.")
        _uploaded = st.file_uploader("Drop .eml file", type=["eml"], key="eml_uploader",
                                     label_visibility="collapsed")
        if _uploaded is not None:
            _file_id = f"{_uploaded.name}_{_uploaded.size}"
            if st.session_state.get("_last_eml") != _file_id:
                with st.spinner("Ingesting newsletter… (~10 sec)"):
                    try:
                        from newsletters.runner import run_eml_bytes
                        _ok, _msg = run_eml_bytes(_uploaded.read(), dry_run=False)
                        if _ok:
                            st.success(f"Done — {_msg}")
                            st.session_state["_last_eml"] = _file_id
                            st.cache_data.clear()
                            st.rerun()
                        else:
                            st.error(f"Ingestion failed: {_msg}")
                    except Exception as _exc:
                        import traceback
                        st.error(f"Error: {_exc}")
                        st.code(traceback.format_exc(), language="text")

    # ── Portfolio screenshot upload ─────────────────────────────────────────────
    _mkt_for_upload, _ = get_newsletter(sel_date)
    _upload_date = (_mkt_for_upload or {}).get("email_date")
    if _upload_date:
        with st.expander("📊 Upload portfolio table screenshot", expanded=False):
            st.caption(
                f"Substack image URLs expire — if the Portfolio tab shows no data, "
                f"screenshot the positions table from Gmail and drop it here. "
                f"Will be saved to newsletter **{_upload_date}**."
            )
            _img_upload = st.file_uploader(
                "Portfolio screenshot", type=["png", "jpg", "jpeg", "webp"],
                key="portfolio_img_uploader", label_visibility="collapsed",
            )
            if _img_upload is not None:
                _img_id = f"{_img_upload.name}_{_img_upload.size}"
                if st.session_state.get("_last_portfolio_img") != _img_id:
                    with st.spinner("Extracting portfolio table from image… (~5 sec)"):
                        try:
                            from newsletters.runner import run_portfolio_image
                            _mt = _img_upload.type or "image/png"
                            _ok2, _msg2 = run_portfolio_image(
                                _img_upload.read(), _mt, _upload_date
                            )
                            if _ok2:
                                st.success(f"Done — {_msg2}")
                                st.session_state["_last_portfolio_img"] = _img_id
                                st.cache_data.clear()
                                st.rerun()
                            else:
                                st.error(f"Extraction failed: {_msg2}")
                        except Exception as _exc2:
                            import traceback
                            st.error(f"Error: {_exc2}")
                            st.code(traceback.format_exc(), language="text")

    _market, _picks = get_newsletter(sel_date)

    if _picks and _picks[0].get("_error"):
        st.error(f"DB error: {_picks[0]['_error']}")
        return

    if _market is None:
        st.info(
            "No newsletter data yet.\n\n"
            "**To populate:**\n"
            "1. Export from Google Takeout → download zip → extract the `.mbox` file\n"
            "2. Copy it to `data/newsletters/primetrading.mbox`\n"
            "3. Run: `python ingest_newsletter.py`\n\n"
            "The Takeout export is usually ready within a few hours of requesting it."
        )
        return

    # ── Risk On / Risk Off banner ─────────────────────────────────────────────
    _risk_raw = (_market.get("risk_environment") or "").lower()
    # Fall back: derive from market_stance for newsletters ingested before this field existed
    if not _risk_raw or _risk_raw == "neutral":
        _stance_raw = (_market.get("market_stance") or "").lower()
        if _stance_raw == "bullish":
            _risk_raw = "risk_on"
        elif _stance_raw in ("bearish", "cautious"):
            _risk_raw = "risk_off"
        else:
            _risk_raw = "neutral"

    _risk_cfg = {
        "risk_on":  ("RISK ON",  "#3fb950", "🟢"),
        "risk_off": ("RISK OFF", "#f85149", "🔴"),
        "neutral":  ("NEUTRAL",  "#e3b341", "🟡"),
    }.get(_risk_raw, ("NEUTRAL", "#e3b341", "🟡"))
    _risk_label, _risk_color, _risk_icon = _risk_cfg
    _risk_rationale = _market.get("risk_rationale") or _market.get("market_notes") or ""

    st.markdown(
        f'<div style="display:flex;align-items:flex-start;gap:12px;padding:10px 14px;'
        f'background:{_risk_color}11;border:1px solid {_risk_color}44;'
        f'border-radius:8px;margin-bottom:12px">'
        f'<span style="font-size:22px;line-height:1.2">{_risk_icon}</span>'
        f'<div>'
        f'<span style="font-size:15px;font-weight:700;color:{_risk_color};'
        f'letter-spacing:0.5px">{_risk_label}</span>'
        f'<span style="color:#7d8590;font-size:11px;margin-left:10px">{_market.get("email_date","")}</span>'
        + (f'<div style="color:#8b949e;font-size:12px;margin-top:3px">{_risk_rationale}</div>'
           if _risk_rationale else "")
        + f'</div></div>',
        unsafe_allow_html=True,
    )

    _tab_track, _tab_watch, _tab_port = st.tabs(["📊 Track Record", "📋 Watchlist", "💼 Portfolio"])

    # ── Track Record tab ──────────────────────────────────────────────────────
    with _tab_track:
        _tr = get_track_record()
        if _tr.get("error"):
            st.error(f"Track record error: {_tr['error']}")
        elif not _tr:
            st.info("No forward test data yet. Run `python forward_test.py` to compute metrics.")
        else:
            _wr   = _tr["win_rate"]
            _ar   = _tr["avg_ret"]
            _mr   = _tr["median_ret"]
            _avgr = _tr.get("avg_r")
            _sr   = _tr["stop_rate"]
            _amg  = _tr.get("avg_max_gain")

            _wr_color = "#3fb950" if _wr >= 0.6 else ("#e3b341" if _wr >= 0.5 else "#f85149")
            _ar_color = "#3fb950" if _ar > 0 else "#f85149"

            st.markdown(strip_html([
                ("Picks",      f'<span class="white">{_tr["total"]}</span>'),
                ("Win Rate",   f'<span style="color:{_wr_color};font-weight:700">{_wr:.0%}</span>'),
                ("Avg Return", f'<span style="color:{_ar_color};font-weight:700">{_ar:+.1f}%</span>'),
                ("Median Ret", f'<span style="color:{_ar_color}">{_mr:+.1f}%</span>'),
                ("Avg R",      f'<span class="green">{_avgr:+.2f}R</span>' if _avgr is not None else '<span class="grey">—</span>'),
                ("Stopped",    f'<span class="yellow">{_sr:.0%}</span>'),
                ("Max Gain",   f'<span class="green">{_amg:+.1f}%</span>' if _amg is not None else '<span class="grey">—</span>'),
            ]), unsafe_allow_html=True)

            # Return distribution histogram
            _neg_ret = [r for r in _tr["returns"] if r < 0]
            _pos_ret = [r for r in _tr["returns"] if r >= 0]
            fig_dist = go.Figure()
            if _neg_ret:
                fig_dist.add_trace(go.Histogram(
                    x=_neg_ret, xbins=dict(start=-100, end=0, size=25),
                    marker_color="#f85149", name="Loss", opacity=0.85,
                ))
            if _pos_ret:
                fig_dist.add_trace(go.Histogram(
                    x=_pos_ret, xbins=dict(start=0, end=510, size=25),
                    marker_color="#3fb950", name="Win", opacity=0.85,
                ))
            fig_dist.update_layout(
                height=260, margin=dict(l=0, r=0, t=10, b=30),
                paper_bgcolor="#0d1117", plot_bgcolor="#0d1117",
                xaxis=dict(title="Return %", color="#7d8590", showgrid=False),
                yaxis=dict(color="#7d8590", gridcolor="#21262d"),
                showlegend=False, bargap=0.05,
            )
            st.plotly_chart(fig_dist, use_container_width=True)

            # Best / Worst trades
            _bc1, _bc2 = st.columns(2)
            with _bc1:
                st.markdown("**Best Trades**")
                for _v in _tr.get("best_5", []):
                    _r_str = f"{_v['r_multiple']:+.1f}R" if _v.get("r_multiple") is not None else ""
                    st.markdown(
                        f'<div style="display:flex;justify-content:space-between;align-items:center;'
                        f'padding:5px 8px;background:#0d1117;border-radius:6px;'
                        f'border:1px solid #21262d;margin-bottom:3px">'
                        f'<span style="font-weight:700;color:#e6edf3">{_v["ticker"]}</span>'
                        f'<span style="color:#7d8590;font-size:11px">{_v["email_date"]}</span>'
                        f'<span style="color:#3fb950;font-weight:700">{_v["current_return_pct"]:+.1f}%</span>'
                        + (f'<span style="color:#3fb950;font-size:10px;margin-left:4px">{_r_str}</span>' if _r_str else "")
                        + '</div>',
                        unsafe_allow_html=True,
                    )
            with _bc2:
                st.markdown("**Worst Trades**")
                for _v in _tr.get("worst_5", []):
                    _r_str = f"{_v['r_multiple']:+.1f}R" if _v.get("r_multiple") is not None else ""
                    _stop_icon = "⛔ " if _v.get("stop_hit") else ""
                    st.markdown(
                        f'<div style="display:flex;justify-content:space-between;align-items:center;'
                        f'padding:5px 8px;background:#0d1117;border-radius:6px;'
                        f'border:1px solid #21262d;margin-bottom:3px">'
                        f'<span style="font-weight:700;color:#e6edf3">{_v["ticker"]}</span>'
                        f'<span style="color:#7d8590;font-size:11px">{_v["email_date"]}</span>'
                        f'<span style="color:#f85149;font-weight:700">{_stop_icon}{_v["current_return_pct"]:+.1f}%</span>'
                        + (f'<span style="color:#f85149;font-size:10px;margin-left:4px">{_r_str}</span>' if _r_str else "")
                        + '</div>',
                        unsafe_allow_html=True,
                    )

    # ── Watchlist tab ──────────────────────────────────────────────────────────
    with _tab_watch:
        _date_for_watch = _market.get("email_date", "") if _market else ""
        _wl_picks = get_watchlist_tickers(_date_for_watch) if _date_for_watch else []

        if not _wl_picks:
            st.info("No watchlist entries for this newsletter — upload the latest newsletter to populate.")
        else:
            _wl_tickers = tuple(sorted(p["ticker"] for p in _wl_picks))
            _wl_section = {p["ticker"]: p["source_section"] for p in _wl_picks}

            with st.spinner(f"Loading OHLCV for {len(_wl_tickers)} tickers…"):
                _wl_data = compute_watchlist_ohlcv(_wl_tickers)

            # Screener lookup: {symbol → composite_score}
            _screener_map = {s["symbol"].upper(): s["composite_score"] for s in ALL_SIGNALS}

            _SECTION_ORDER = ["scan_21dma", "focus_list", "stalklist"]
            _SECTION_TITLE = {
                "scan_21dma": "21EMA Zone — Top Setups",
                "focus_list": "Focus List — Top Ideas",
                "stalklist":  "Stalk List — Liquid Leaders",
            }
            _SECTION_COLOR = {
                "scan_21dma": "#e3b341",
                "focus_list": "#388bfd",
                "stalklist":  "#58a6ff",
            }

            # Build scored rows grouped by section
            _grouped: dict[str, list] = {s: [] for s in _SECTION_ORDER}
            for tk in _wl_tickers:
                d   = _wl_data.get(tk, {})
                sc  = d.get("score", {})
                sec = _wl_section.get(tk, "")
                if sec in _grouped:
                    _grouped[sec].append({
                        "ticker":      tk,
                        "section":     sec,
                        "alex_score":  sc.get("total", 0),
                        "score_data":  sc,
                        "in_screener": tk in _screener_map,
                        "comp_score":  _screener_map.get(tk),
                        "has_data":    d.get("df") is not None,
                    })
            for sec in _SECTION_ORDER:
                _grouped[sec].sort(key=lambda r: r["alex_score"], reverse=True)

            _all_rows = [r for sec in _SECTION_ORDER for r in _grouped[sec]]
            _total = len(_all_rows)

            # Header + TradingView export (current newsletter, section order)
            _scrn_exch_map = {s["symbol"].upper(): s.get("exchange", "") for s in ALL_SIGNALS}
            _nl_tv_lines: list[str] = []
            for sec in _SECTION_ORDER:
                for row in _grouped[sec]:
                    _t = row["ticker"].upper()
                    _exch = _scrn_exch_map.get(_t, "")
                    _tv_exch = _TV_EXCH.get(_exch, "")
                    _nl_tv_lines.append(f"{_tv_exch}:{_t}" if _tv_exch else _t)

            _hdr_col, _btn_col = st.columns([3, 1])
            with _hdr_col:
                st.markdown(
                    f'<div style="color:#7d8590;font-size:11px;text-transform:uppercase;'
                    f'letter-spacing:0.6px;margin-bottom:6px">'
                    f'{_total} stocks · {_date_for_watch} &nbsp;·&nbsp; '
                    f'<span style="text-transform:none">21D score = cloud rising · in zone · higher lows · low vol · compression</span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
            with _btn_col:
                if _nl_tv_lines:
                    st.download_button(
                        f"📥 TradingView ({len(_nl_tv_lines)})",
                        data="\n".join(_nl_tv_lines),
                        file_name=f"alex_watchlist_{_date_for_watch}.txt",
                        mime="text/plain",
                        use_container_width=True,
                        help="Current newsletter watchlist in section order · Import in TradingView: Watchlists → ··· → Import list",
                    )

            # Stock list — grouped by section
            def _dot(sc, val, key=None):
                if key and sc.get("scores"):
                    s = sc["scores"].get(key, 0)
                    c = "#3fb950" if s >= 15 else ("#e3b341" if s >= 8 else "#484f58")
                elif val is True:
                    c = "#3fb950"
                elif val is False:
                    c = "#f85149"
                else:
                    c = "#e3b341"
                return f'<span style="color:{c};font-size:14px">●</span>'

            for sec in _SECTION_ORDER:
                sec_rows = _grouped[sec]
                if not sec_rows:
                    continue
                sec_color = _SECTION_COLOR[sec]
                sec_title = _SECTION_TITLE[sec]
                st.markdown(
                    f'<div style="margin:12px 0 4px;border-left:3px solid {sec_color};padding-left:8px">'
                    f'<span style="color:{sec_color};font-size:11px;font-weight:700;'
                    f'text-transform:uppercase;letter-spacing:0.6px">'
                    f'{sec_title} &nbsp;·&nbsp; {len(sec_rows)}</span></div>',
                    unsafe_allow_html=True,
                )
                for row in sec_rows:
                    tk  = row["ticker"]
                    sc  = row["score_data"]
                    alx = row["alex_score"]
                    alx_color = "#3fb950" if alx >= 70 else ("#e3b341" if alx >= 45 else "#f85149")

                    _criteria = (
                        _dot(sc, sc.get("rising"), "rising")
                        + _dot(sc, sc.get("in_zone"), "proximity")
                        + _dot(sc, sc.get("higher_lows"), "higher_lows")
                        + _dot(sc, (sc.get("vol_ratio") or 1.0) < 0.75, "volume")
                        + _dot(sc, (sc.get("comp_ratio") or 1.0) < 0.85, "compression")
                    )

                    _comp_badge = ""
                    if row["in_screener"] and row["comp_score"] is not None:
                        _cc = "#3fb950" if row["comp_score"] >= 75 else ("#e3b341" if row["comp_score"] >= 60 else "#f85149")
                        _comp_badge = (f'<span style="font-size:10px;font-weight:700;color:{_cc};'
                                       f'background:{_cc}22;border-radius:4px;padding:2px 6px;margin-left:4px">'
                                       f'screener {row["comp_score"]:.0f}</span>')
                    else:
                        _comp_badge = ('<span style="font-size:10px;font-weight:700;color:#a371f7;'
                                       'background:#a371f722;border-radius:4px;padding:2px 6px;margin-left:4px">'
                                       '⚡ Alex only</span>')

                    _lvls = ""
                    if sc.get("entry"):
                        _lvls = (f'<span style="color:#8b949e;font-size:11px;margin-left:8px">'
                                 f'entry ${sc["entry"]:.2f} · stop ${sc["stop"]:.2f}</span>')

                    st.markdown(
                        f'<div style="display:flex;align-items:center;gap:6px;'
                        f'padding:6px 8px;background:#0d1117;border-radius:6px;'
                        f'border:1px solid #21262d;margin-bottom:3px">'
                        f'<span style="font-weight:700;color:#e6edf3;min-width:52px">{tk}</span>'
                        + _comp_badge
                        + f'<span style="flex:1"></span>'
                        + _criteria
                        + f'<span style="color:{alx_color};font-weight:700;font-size:13px;'
                        f'min-width:28px;text-align:right">{alx:.0f}</span>'
                        + _lvls
                        + f'</div>',
                        unsafe_allow_html=True,
                    )

            # Cloud chart for selected ticker
            st.markdown("---")
            _chart_options = [tk for tk in [r["ticker"] for r in _all_rows] if _wl_data.get(tk, {}).get("df")]
            _failed = [r["ticker"] for r in _all_rows if not _wl_data.get(r["ticker"], {}).get("df")]
            if _chart_options:
                if _failed:
                    st.caption(f"Charts loaded for {len(_chart_options)}/{len(_all_rows)} tickers · no Borsdata data for: {', '.join(_failed)}")
                _sel = st.selectbox(
                    "Select ticker to view cloud chart",
                    _chart_options, key="wl_chart_sel",
                    format_func=lambda t: f"{t}  (score {next(r['alex_score'] for r in _all_rows if r['ticker']==t):.0f})",
                )
                if _sel:
                    _ohlcv_records = _wl_data[_sel]["df"]
                    _sc = _wl_data[_sel]["score"]
                    if _ohlcv_records:
                        from plotly.subplots import make_subplots
                        _dates  = [r["date"]   for r in _ohlcv_records]
                        _opens  = [r["open"]   for r in _ohlcv_records]
                        _highs  = [r["high"]   for r in _ohlcv_records]
                        _lows   = [r["low"]    for r in _ohlcv_records]
                        _closes = [r["close"]  for r in _ohlcv_records]
                        _vols   = [r["volume"] for r in _ohlcv_records]

                        # Recompute cloud on the slice for chart (last 80 rows already in df)
                        import pandas as _pd
                        _cdf = _pd.DataFrame(_ohlcv_records)
                        _cdf["ema_21"]      = _cdf["close"].ewm(span=21, adjust=False).mean()
                        _cdf["ema_21_high"] = _cdf["high"].ewm(span=21,  adjust=False).mean()
                        _cdf["ema_21_low"]  = _cdf["low"].ewm(span=21,   adjust=False).mean()
                        _cdf["vol_sma_20"]  = _cdf["volume"].rolling(20).mean()

                        _ema_mid = _cdf["ema_21"].tolist()
                        _ema_hi  = _cdf["ema_21_high"].tolist()
                        _ema_lo  = _cdf["ema_21_low"].tolist()
                        _vol_avg = _cdf["vol_sma_20"].tolist()

                        _fig = make_subplots(
                            rows=2, cols=1, shared_xaxes=True,
                            row_heights=[0.72, 0.28], vertical_spacing=0.02,
                        )
                        # Cloud: filled polygon (toself is reliable in subplots; tonexty is not)
                        _fig.add_trace(go.Scatter(
                            x=_dates + _dates[::-1],
                            y=_ema_hi + _ema_lo[::-1],
                            fill="toself", fillcolor="rgba(56,139,253,0.12)",
                            line=dict(color="rgba(0,0,0,0)"),
                            showlegend=False, name="EMA Cloud",
                        ), row=1, col=1)
                        _fig.add_trace(go.Scatter(
                            x=_dates, y=_ema_lo,
                            line=dict(color="rgba(56,139,253,0.35)", width=1),
                            showlegend=False, name="Cloud low",
                        ), row=1, col=1)
                        _fig.add_trace(go.Scatter(
                            x=_dates, y=_ema_hi,
                            line=dict(color="rgba(56,139,253,0.35)", width=1),
                            showlegend=False, name="Cloud high",
                        ), row=1, col=1)
                        # EMA21 midline
                        _fig.add_trace(go.Scatter(
                            x=_dates, y=_ema_mid,
                            line=dict(color="#388bfd", width=1.5),
                            showlegend=False, name="EMA21",
                        ), row=1, col=1)
                        # Candlestick
                        _fig.add_trace(go.Candlestick(
                            x=_dates, open=_opens, high=_highs, low=_lows, close=_closes,
                            name=_sel,
                            increasing_line_color="#3fb950", decreasing_line_color="#f85149",
                        ), row=1, col=1)
                        # Volume bars
                        _vol_colors = ["#3fb950" if c >= o else "#f85149"
                                       for c, o in zip(_closes, _opens)]
                        _fig.add_trace(go.Bar(
                            x=_dates, y=_vols, marker_color=_vol_colors,
                            showlegend=False, name="Volume",
                        ), row=2, col=1)
                        # Volume SMA line
                        _fig.add_trace(go.Scatter(
                            x=_dates, y=_vol_avg,
                            line=dict(color="#e3b341", width=1),
                            showlegend=False, name="Vol SMA20",
                        ), row=2, col=1)
                        _fig.update_layout(
                            height=400, margin=dict(l=0, r=0, t=16, b=0),
                            paper_bgcolor="#0d1117", plot_bgcolor="#0d1117",
                            xaxis=dict(showgrid=False, color="#7d8590", rangeslider_visible=False),
                            yaxis=dict(showgrid=True, gridcolor="#21262d", color="#7d8590"),
                            xaxis2=dict(showgrid=False, color="#7d8590"),
                            yaxis2=dict(showgrid=True, gridcolor="#21262d", color="#7d8590"),
                            showlegend=False,
                        )
                        st.plotly_chart(_fig, use_container_width=True)

                        # Score breakdown
                        if _sc.get("scores"):
                            _s = _sc["scores"]
                            st.markdown(strip_html([
                                ("Rising",      f'<span style="color:{"#3fb950" if _s["rising"]>=15 else "#e3b341"}">{_s["rising"]:.0f}/25</span>'),
                                ("In Zone",     f'<span style="color:{"#3fb950" if _s["proximity"]>=15 else "#e3b341"}">{_s["proximity"]:.0f}/25</span>'),
                                ("Higher Lows", f'<span style="color:{"#3fb950" if _s["higher_lows"]>=15 else "#e3b341"}">{_s["higher_lows"]:.0f}/20</span>'),
                                ("Low Vol",     f'<span style="color:{"#3fb950" if _s["volume"]>=15 else "#e3b341"}">{_s["volume"]:.0f}/20</span>'),
                                ("Compress",    f'<span style="color:{"#3fb950" if _s["compression"]>=15 else "#e3b341"}">{_s["compression"]:.0f}/20</span>'),
                                ("Total",       f'<span style="font-weight:700;color:{"#3fb950" if _sc["total"]>=70 else "#e3b341"}">{_sc["total"]:.0f}/110</span>'),
                            ]), unsafe_allow_html=True)
            else:
                st.warning(f"No chart data loaded. Borsdata could not find OHLCV for: {', '.join(_failed) if _failed else 'any tickers'}")

    # ── Portfolio tab ──────────────────────────────────────────────────────────
    with _tab_port:
        _port_date = _market.get("email_date", "")
        _stance = (_market.get("market_stance") or "unknown").upper()
        _stance_color = {
            "BULLISH": "#3fb950", "NEUTRAL": "#e3b341",
            "CAUTIOUS": "#e3b341", "BEARISH": "#f85149",
        }.get(_stance, "#7d8590")

        st.markdown(
            f'<div style="display:flex;align-items:center;gap:12px;margin-bottom:8px">'
            f'<span style="color:#8b949e;font-size:13px">{_port_date}</span>'
            f'<span style="font-size:12px;font-weight:700;color:{_stance_color};'
            f'background:{_stance_color}22;border-radius:4px;padding:3px 8px">{_stance}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )
        if _market.get("market_notes"):
            st.markdown(
                f'<div style="padding:8px 12px;background:#161b22;border-radius:6px;'
                f'border:1px solid #21262d;color:#8b949e;font-size:12px;margin-bottom:12px">'
                f'{_market["market_notes"]}</div>',
                unsafe_allow_html=True,
            )

        _signal_tickers = {s["symbol"].upper() for s in ALL_SIGNALS}

        def _in_screener_badge(ticker: str) -> str:
            if ticker.upper() in _signal_tickers:
                return '<span style="font-size:10px;color:#3fb950;background:#3fb95022;border-radius:4px;padding:2px 6px">✓ screener</span>'
            return ""

        def _action_badge(action: str) -> str:
            colors = {
                "FOCUS": "#388bfd", "LONG": "#3fb950", "ADDED": "#3fb950",
                "NEW": "#3fb950", "TRIM": "#e3b341", "OUT": "#f85149",
                "WATCH": "#7d8590", "EP": "#a371f7", "STALK": "#58a6ff",
            }
            c = colors.get((action or "").upper(), "#7d8590")
            return f'<span style="font-size:10px;font-weight:700;color:{c};background:{c}22;border-radius:4px;padding:2px 6px">{(action or "").upper()}</span>'

        _sections: dict[str, list[dict]] = {}
        for p in _picks:
            _sections.setdefault(p["source_section"], []).append(p)

        if "portfolio_table" not in _sections:
            st.info("No portfolio data in this newsletter.")
        else:
            _pt_picks = _sections["portfolio_table"]
            _fwd = {r["ticker"]: r for r in get_forward_tests(_port_date)} if _port_date else {}

            # ── Portfolio table ──────────────────────────────────────────────────
            st.markdown(
                '<div style="display:flex;gap:4px;padding:0 6px;margin-bottom:2px">'
                '<div style="flex:2;font-size:10px;color:#7d8590;text-transform:uppercase">Ticker</div>'
                '<div style="flex:1.4;text-align:right;font-size:10px;color:#7d8590;text-transform:uppercase">Entered</div>'
                '<div style="flex:1;text-align:right;font-size:10px;color:#7d8590;text-transform:uppercase">Entry</div>'
                '<div style="flex:1;text-align:right;font-size:10px;color:#7d8590;text-transform:uppercase">Stop</div>'
                '<div style="flex:1;text-align:right;font-size:10px;color:#7d8590;text-transform:uppercase">Size</div>'
                '<div style="flex:1;text-align:right;font-size:10px;color:#7d8590;text-transform:uppercase">T1</div>'
                '<div style="flex:1;text-align:right;font-size:10px;color:#7d8590;text-transform:uppercase">T2</div>'
                '<div style="flex:1;text-align:right;font-size:10px;color:#7d8590;text-transform:uppercase">T3</div>'
                '<div style="flex:1;text-align:right;font-size:10px;color:#7d8590;text-transform:uppercase">Perf</div>'
                '</div>',
                unsafe_allow_html=True,
            )
            rows_html = ""
            for p in _pt_picks:
                tk  = p["ticker"]
                _ed = p.get("entry_date") or "—"
                _e  = f"${p['entry_price']:.2f}"      if p.get("entry_price")       else "—"
                _s  = f"${p['stop_price']:.2f}"        if p.get("stop_price")        else "—"
                _sz = f"{p['position_size_pct']:.1f}%" if p.get("position_size_pct") else "—"
                _t1 = f"${p['target_price']:.0f}"      if p.get("target_price")      else "—"
                _t2 = f"${p['trim_2']:.0f}"             if p.get("trim_2")             else "—"
                _t3 = f"${p['trim_3']:.0f}"             if p.get("trim_3")             else "—"
                fwd  = _fwd.get(tk, {})
                _ret = fwd.get("current_return_pct")
                if _ret is not None:
                    _rc = "#3fb950" if _ret >= 0 else "#f85149"
                    _stopped = fwd.get("stop_hit") or fwd.get("status") == "stopped"
                    _perf = f'<span style="color:{_rc};font-size:12px;font-weight:700">{"⛔ " if _stopped else ""}{_ret:+.1f}%</span>'
                    _rm = fwd.get("r_multiple")
                    if _rm is not None:
                        _rmc = "#3fb950" if _rm >= 0 else "#f85149"
                        _perf += f'<span style="color:{_rmc};font-size:10px;margin-left:4px">{_rm:+.1f}R</span>'
                else:
                    _perf = '<span style="color:#7d8590;font-size:11px">—</span>'
                rows_html += (
                    f'<div style="display:flex;gap:4px;align-items:center;padding:5px 6px;'
                    f'background:#0d1117;border-radius:6px;border:1px solid #21262d;margin-bottom:3px">'
                    f'<div style="flex:2;display:flex;align-items:center;gap:5px">'
                    f'<span style="font-weight:700;color:#e6edf3;font-size:13px">{tk}</span>'
                    + _action_badge(p.get("action") or "") + " " + _in_screener_badge(tk)
                    + f'</div>'
                    f'<div style="flex:1.4;text-align:right;font-size:11px;color:#8b949e">{_ed}</div>'
                    f'<div style="flex:1;text-align:right;font-size:12px;color:#e6edf3">{_e}</div>'
                    f'<div style="flex:1;text-align:right;font-size:12px;color:#f85149">{_s}</div>'
                    f'<div style="flex:1;text-align:right;font-size:12px;color:#8b949e">{_sz}</div>'
                    f'<div style="flex:1;text-align:right;font-size:12px;color:#3fb950">{_t1}</div>'
                    f'<div style="flex:1;text-align:right;font-size:12px;color:#3fb950">{_t2}</div>'
                    f'<div style="flex:1;text-align:right;font-size:12px;color:#3fb950">{_t3}</div>'
                    f'<div style="flex:1;text-align:right">{_perf}</div>'
                    f'</div>'
                )
            if rows_html:
                st.markdown(rows_html, unsafe_allow_html=True)

            # ── EMA21 cloud chart with trade levels ──────────────────────────────
            st.markdown("---")
            _positions_with_entry = [p for p in _pt_picks if p.get("entry_price")]
            _entry_tickers = sorted({p["ticker"] for p in _positions_with_entry})
            if _positions_with_entry:
                with st.spinner("Loading chart data…"):
                    _port_ohlcv = compute_watchlist_ohlcv(tuple(_entry_tickers))

                # Each scaled-in position is charted on its own. A ticker Alex
                # added to appears once per entry (distinct entry date/price),
                # never merged into a single combined position.
                _chartable = [p for p in _positions_with_entry
                              if _port_ohlcv.get(p["ticker"], {}).get("df")]
                if not _chartable:
                    _pt_failed = sorted({p["ticker"] for p in _positions_with_entry
                                         if not _port_ohlcv.get(p["ticker"], {}).get("df")})
                    st.caption(f"No chart data — Borsdata could not find: {', '.join(_pt_failed)}")
                else:
                    def _pos_label(i):
                        _p  = _chartable[i]
                        _sc = _port_ohlcv[_p["ticker"]]["score"]["total"]
                        _dt = _p.get("entry_date") or "?"
                        return f"{_p['ticker']}  {_dt}  @ ${_p['entry_price']:.2f}  (21D {_sc:.0f})"
                    _pos_idx = st.selectbox(
                        "Select position to chart",
                        range(len(_chartable)),
                        key="port_chart_sel",
                        format_func=_pos_label,
                    )
                    _pick     = _chartable[_pos_idx]
                    _port_sel = _pick["ticker"]
                    if _port_sel:
                        _ohlcv_recs = _port_ohlcv[_port_sel]["df"]

                        from plotly.subplots import make_subplots as _msp2
                        import pandas as _pd3
                        _cdf2 = _pd3.DataFrame(_ohlcv_recs)
                        _cdf2["ema_21"]      = _cdf2["close"].ewm(span=21, adjust=False).mean()
                        _cdf2["ema_21_high"] = _cdf2["high"].ewm(span=21,  adjust=False).mean()
                        _cdf2["ema_21_low"]  = _cdf2["low"].ewm(span=21,   adjust=False).mean()
                        _cdf2["vol_sma_20"]  = _cdf2["volume"].rolling(20).mean()

                        _pdates   = [r["date"]   for r in _ohlcv_recs]
                        _popens   = [r["open"]   for r in _ohlcv_recs]
                        _phighs   = [r["high"]   for r in _ohlcv_recs]
                        _plows    = [r["low"]    for r in _ohlcv_recs]
                        _pcloses  = [r["close"]  for r in _ohlcv_recs]
                        _pvols    = [r["volume"] for r in _ohlcv_recs]
                        _pema_mid = _cdf2["ema_21"].tolist()
                        _pema_hi  = _cdf2["ema_21_high"].tolist()
                        _pema_lo  = _cdf2["ema_21_low"].tolist()
                        _pvol_avg = _cdf2["vol_sma_20"].tolist()

                        _pfig2 = _msp2(
                            rows=2, cols=1, shared_xaxes=True,
                            row_heights=[0.72, 0.28], vertical_spacing=0.02,
                        )
                        # EMA21 cloud (toself polygon — reliable in subplots)
                        _pfig2.add_trace(go.Scatter(
                            x=_pdates + _pdates[::-1],
                            y=_pema_hi + _pema_lo[::-1],
                            fill="toself", fillcolor="rgba(56,139,253,0.12)",
                            line=dict(color="rgba(0,0,0,0)"),
                            showlegend=False, name="EMA Cloud",
                        ), row=1, col=1)
                        _pfig2.add_trace(go.Scatter(
                            x=_pdates, y=_pema_lo,
                            line=dict(color="rgba(56,139,253,0.35)", width=1),
                            showlegend=False, name="Cloud low",
                        ), row=1, col=1)
                        _pfig2.add_trace(go.Scatter(
                            x=_pdates, y=_pema_hi,
                            line=dict(color="rgba(56,139,253,0.35)", width=1),
                            showlegend=False, name="Cloud high",
                        ), row=1, col=1)
                        _pfig2.add_trace(go.Scatter(
                            x=_pdates, y=_pema_mid,
                            line=dict(color="#388bfd", width=1.5),
                            showlegend=False, name="EMA21",
                        ), row=1, col=1)
                        _pfig2.add_trace(go.Candlestick(
                            x=_pdates, open=_popens, high=_phighs,
                            low=_plows, close=_pcloses,
                            name=_port_sel,
                            increasing_line_color="#3fb950",
                            decreasing_line_color="#f85149",
                        ), row=1, col=1)
                        _pvol_colors = ["#3fb950" if c >= o else "#f85149"
                                        for c, o in zip(_pcloses, _popens)]
                        _pfig2.add_trace(go.Bar(
                            x=_pdates, y=_pvols, marker_color=_pvol_colors,
                            showlegend=False, name="Volume",
                        ), row=2, col=1)
                        _pfig2.add_trace(go.Scatter(
                            x=_pdates, y=_pvol_avg,
                            line=dict(color="#e3b341", width=1),
                            showlegend=False, name="Vol SMA20",
                        ), row=2, col=1)

                        # Trade level hlines
                        def _port_hline(price, color, label):
                            if price is None:
                                return
                            _pfig2.add_hline(
                                y=price, row=1, col=1,
                                line_color=color, line_dash="dot", line_width=1.2,
                                annotation_text=f" {label} ${price:.2f}",
                                annotation_font_color=color, annotation_font_size=10,
                            )
                        _port_hline(_pick.get("entry_price"), "#388bfd", "Entry")
                        # Stop line intentionally omitted — Alex trails it up over the
                        # following days, so a static stop line is misleading on the chart.
                        _port_hline(_pick.get("target_price"), "#3fb950", "T1")
                        _port_hline(_pick.get("trim_2"),       "#58a6ff", "T2")
                        _port_hline(_pick.get("trim_3"),       "#a371f7", "T3")

                        # Entry date vline — prefer the position's real entry date,
                        # fall back to the newsletter-date proxy only if unavailable.
                        _entry_dt2 = _pick.get("entry_date") or get_pick_entry_date(_port_sel)
                        if _entry_dt2 and _entry_dt2 in _pdates:
                            _pfig2.add_shape(
                                type="line",
                                x0=_entry_dt2, x1=_entry_dt2, y0=0, y1=1,
                                xref="x", yref="paper",
                                line=dict(color="#388bfd", dash="dash", width=1.5),
                            )
                            _pfig2.add_annotation(
                                x=_entry_dt2, y=0.98, xref="x", yref="paper",
                                text="Entry", showarrow=False,
                                font=dict(color="#388bfd", size=10), xanchor="left",
                            )

                        # TRIM / OUT history markers
                        for _tr in get_trim_history(_port_sel):
                            _tr_date = str(_tr.get("email_date", ""))
                            if _tr_date and _tr_date in _pdates:
                                _tr_action = (_tr.get("action") or "TRIM").upper()
                                _tr_color  = "#f85149" if _tr_action == "OUT" else "#e3b341"
                                _pfig2.add_shape(
                                    type="line",
                                    x0=_tr_date, x1=_tr_date, y0=0, y1=1,
                                    xref="x", yref="paper",
                                    line=dict(color=_tr_color, dash="dash", width=1.2),
                                )
                                _pfig2.add_annotation(
                                    x=_tr_date, y=0.88, xref="x", yref="paper",
                                    text=_tr_action, showarrow=False,
                                    font=dict(color=_tr_color, size=9), xanchor="left",
                                )

                        _pfig2.update_layout(
                            height=440, margin=dict(l=0, r=0, t=20, b=0),
                            paper_bgcolor="#0d1117", plot_bgcolor="#0d1117",
                            xaxis=dict(showgrid=False, color="#7d8590", rangeslider_visible=False),
                            yaxis=dict(showgrid=True, gridcolor="#21262d", color="#7d8590"),
                            xaxis2=dict(showgrid=False, color="#7d8590"),
                            yaxis2=dict(showgrid=True, gridcolor="#21262d", color="#7d8590"),
                            showlegend=False,
                        )
                        st.plotly_chart(_pfig2, use_container_width=True)

                        # EMA21 score strip
                        _psc = _port_ohlcv[_port_sel]["score"]
                        if _psc.get("scores"):
                            _ps = _psc["scores"]
                            st.markdown(strip_html([
                                ("Rising",      f'<span style="color:{"#3fb950" if _ps["rising"]>=15 else "#e3b341"}">{_ps["rising"]:.0f}/25</span>'),
                                ("In Zone",     f'<span style="color:{"#3fb950" if _ps["proximity"]>=15 else "#e3b341"}">{_ps["proximity"]:.0f}/25</span>'),
                                ("Higher Lows", f'<span style="color:{"#3fb950" if _ps["higher_lows"]>=15 else "#e3b341"}">{_ps["higher_lows"]:.0f}/20</span>'),
                                ("Low Vol",     f'<span style="color:{"#3fb950" if _ps["volume"]>=15 else "#e3b341"}">{_ps["volume"]:.0f}/20</span>'),
                                ("Compress",    f'<span style="color:{"#3fb950" if _ps["compression"]>=15 else "#e3b341"}">{_ps["compression"]:.0f}/20</span>'),
                                ("21D Score",   f'<span style="font-weight:700;color:{"#3fb950" if _psc["total"]>=70 else "#e3b341"}">{_psc["total"]:.0f}/110</span>'),
                            ]), unsafe_allow_html=True)

        _nl_count = len(get_newsletter_dates())
        if _nl_count > 1:
            st.divider()
            st.caption(f"{_nl_count} newsletters in database")


# ---------------------------------------------------------------------------
# Main content
# ---------------------------------------------------------------------------

# Newsletter page — render and stop before screener code
if _page == "📧 Alex's Picks":
    _render_newsletter_page(_selected_newsletter_date)
    st.stop()

if st.session_state.get("market_open", False):
    _sector_df = get_sector_returns()
    _themes    = get_hot_themes()

    col_sec, col_theme = st.columns([3, 2])

    with col_sec:
        st.markdown("**Sector Strength**")
        st.caption("US sector ETFs · Yahoo Finance · sorted by 1M")

        if _sector_df.empty:
            st.info("Sector data unavailable — yfinance may be rate-limited.")
        else:
            def _ret_color(v):
                if v is None:
                    return "—"
                color = "#3fb950" if v > 0 else "#f85149"
                sign  = "+" if v > 0 else ""
                return f'<span style="color:{color};font-weight:600">{sign}{v:.1%}</span>'

            header = (
                '<div class="strip" style="margin-bottom:4px">'
                '<div class="cell" style="flex:2;text-align:left;padding-left:10px">'
                '<span class="cell-label">Sector</span></div>'
                + "".join(
                    f'<div class="cell"><span class="cell-label">{p}</span></div>'
                    for p in ["1W", "1M", "6M", "1Y", "ETF"]
                )
                + "</div>"
            )
            st.markdown(header, unsafe_allow_html=True)

            sorted_df = _sector_df.sort_values("1M", ascending=False, na_position="last")
            for _, row in sorted_df.iterrows():
                cells = [
                    (row["Sector"], "white", 2),
                    (_ret_color(row.get("1W")),  "", 1),
                    (_ret_color(row.get("1M")),  "", 1),
                    (_ret_color(row.get("6M")),  "", 1),
                    (_ret_color(row.get("1Y")),  "", 1),
                    (f'<span class="grey" style="font-size:11px">{row["ETF"]}</span>', "", 1),
                ]
                inner = "".join(
                    f'<div class="cell" style="flex:{flex};{"text-align:left;padding-left:10px" if i==0 else ""}">'
                    f'<div class="cell-value" style="font-size:13px">{val}</div></div>'
                    for i, (val, _, flex) in enumerate(cells)
                )
                st.markdown(f'<div class="strip">{inner}</div>', unsafe_allow_html=True)

    with col_theme:
        st.markdown("**Hot Market Themes**")

        if not _themes.get("themes"):
            st.info("No themes yet.")
            if st.button("Generate themes now", key="refresh_themes_btn"):
                with st.spinner("Asking Claude…"):
                    try:
                        from themes.refresher import refresh_hot_themes
                        _themes = refresh_hot_themes()
                        get_hot_themes.clear()
                        st.rerun()
                    except Exception as _e:
                        st.error(f"Failed: {_e}")
        else:
            st.caption(f"Generated: {_themes.get('generated_at', 'unknown')}")
            if st.button("🔄 Refresh themes", key="refresh_themes_btn2", use_container_width=True):
                with st.spinner("Refreshing…"):
                    try:
                        from themes.refresher import refresh_hot_themes
                        _themes = refresh_hot_themes()
                        get_hot_themes.clear()
                        st.rerun()
                    except Exception as _e:
                        st.error(f"Failed: {_e}")

            MOMENTUM_COLOR = {"high": "#3fb950", "medium": "#e3b341", "emerging": "#388bfd"}
            for _key, theme in _themes.get("themes", {}).items():
                momentum = theme.get("momentum", "medium")
                m_color  = MOMENTUM_COLOR.get(momentum, "#7d8590")
                tickers  = ", ".join(theme.get("example_tickers", []))
                st.markdown(
                    f'<div style="padding:10px 14px;background:#161b22;border-radius:8px;'
                    f'border:1px solid #21262d;margin-bottom:6px">'
                    f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:4px">'
                    f'<span style="font-size:13px;font-weight:700;color:#e6edf3">{theme["name"]}</span>'
                    f'<span style="font-size:10px;font-weight:600;color:{m_color};'
                    f'background:{m_color}22;border-radius:4px;padding:2px 6px">{momentum.upper()}</span>'
                    f'</div>'
                    f'<div style="color:#7d8590;font-size:11px;line-height:1.5;margin-bottom:6px">'
                    f'{theme["description"]}</div>'
                    f'<div style="color:#484f58;font-size:10px;margin-bottom:2px">🇺🇸 '
                    f'<span style="color:#388bfd">{tickers}</span></div>'
                    + (
                        f'<div style="color:#484f58;font-size:10px;margin-bottom:2px">🇪🇺 '
                        f'<span style="color:#58a6ff">{", ".join(theme.get("european_tickers", []))}</span></div>'
                        if theme.get("european_tickers") else ""
                    )
                    + (
                        f'<div style="color:#484f58;font-size:10px">🇸🇪 '
                        f'<span style="color:#79c0ff">{", ".join(theme.get("scandinavian_tickers", []))}</span></div>'
                        if theme.get("scandinavian_tickers") else ""
                    )
                    + f'</div>',
                    unsafe_allow_html=True,
                )

st.divider()

# ===== MY TRADES =====

if st.session_state.get("trades_open", False):
    _open_trades  = trades_db.get_open_trades()
    _closed_trades = trades_db.get_closed_trades()
    _strat_stats  = trades_db.get_strategy_stats()

    st.markdown("**My Trades**")

    # Open positions
    st.markdown('<div class="strip-label">Open Positions</div>', unsafe_allow_html=True)
    if not _open_trades:
        st.caption("No open positions. Log an entry from a signal below.")
    else:
        for _t in _open_trades:
            _ep  = _t.get("entry_price") or 0.0
            _sp  = _t.get("stop_price")  or 0.0
            _tp  = _t.get("target_price")
            _rr  = round((_tp - _ep) / (_ep - _sp), 1) if (_tp and _ep and _sp and _ep > _sp) else None
            _tc1, _tc2 = st.columns([4, 1])
            with _tc1:
                st.markdown(strip_html([
                    ("Symbol",   f'<span style="font-weight:700;color:#e6edf3">{_t["symbol"]}</span>'),
                    ("Strategy", f'<span style="color:#8b949e">{BADGE_LABELS.get(_t.get("strategy",""), _t.get("strategy","—"))}</span>'),
                    ("Entry",    f'<span class="white">{_ep:.2f}</span>'),
                    ("Stop",     f'<span class="red">{_sp:.2f}</span>'),
                    ("Target",   f'<span class="green">{_tp:.2f}</span>' if _tp else '<span class="grey">—</span>'),
                    ("Planned R:R", f'<span class="white">{_rr:.1f}×</span>' if _rr else '<span class="grey">—</span>'),
                    ("Since",    f'<span class="grey" style="font-size:11px">{_t.get("entry_date","")}</span>'),
                ]), unsafe_allow_html=True)
            with _tc2:
                with st.expander("Record exit"):
                    with st.form(f"exit_{_t['id']}"):
                        _xp = st.number_input("Exit price", min_value=0.01, step=0.01,
                                              format="%.2f", key=f"xprice_{_t['id']}")
                        _xn = st.text_input("Notes", key=f"xnote_{_t['id']}")
                        if st.form_submit_button("Confirm exit", use_container_width=True):
                            if _xp > 0 and trades_db.record_exit(_t["id"], _xp, _xn):
                                st.success("Saved")
                                st.rerun()
                            else:
                                st.error("Failed — check connection")

    # Strategy performance stats
    if _strat_stats:
        st.markdown('<div class="strip-label" style="margin-top:10px">Performance by Strategy</div>', unsafe_allow_html=True)
        for _s in _strat_stats:
            _wr = _s["win_rate"]
            _wc = "#3fb950" if _wr >= 0.5 else ("#e3b341" if _wr >= 0.35 else "#f85149")
            _rr_str = f'{_s["avg_rr"]:.2f}×' if _s["avg_rr"] is not None else "—"
            _rr_col = "#3fb950" if (_s["avg_rr"] or 0) >= 1.0 else ("#e3b341" if (_s["avg_rr"] or 0) >= 0 else "#f85149")
            st.markdown(strip_html([
                ("Strategy", f'<span class="white">{BADGE_LABELS.get(_s["strategy"], _s["strategy"])}</span>'),
                ("Trades",   f'<span class="white">{_s["trades"]}</span>'),
                ("Wins",     f'<span class="white">{_s["wins"]}</span>'),
                ("Win %",    f'<span style="color:{_wc};font-weight:700">{_wr:.0%}</span>'),
                ("Avg R:R",  f'<span style="color:{_rr_col};font-weight:700">{_rr_str}</span>'),
            ]), unsafe_allow_html=True)

    # Closed trades log
    if _closed_trades:
        st.markdown('<div class="strip-label" style="margin-top:10px">Closed Trades</div>', unsafe_allow_html=True)
        for _t in _closed_trades[:20]:
            _rr  = _t.get("realized_rr")
            _oc  = _t.get("outcome", "")
            _oc_color = "#3fb950" if _oc == "win" else ("#f85149" if _oc == "loss" else "#7d8590")
            st.markdown(strip_html([
                ("Symbol",   f'<span class="white">{_t["symbol"]}</span>'),
                ("Strategy", f'<span style="color:#8b949e">{BADGE_LABELS.get(_t.get("strategy",""), _t.get("strategy","—"))}</span>'),
                ("Entry",    f'<span class="grey">{(_t.get("entry_price") or 0):.2f}</span>'),
                ("Exit",     f'<span class="white">{(_t.get("exit_price") or 0):.2f}</span>'),
                ("R:R",      f'<span style="color:{_oc_color};font-weight:700">{_rr:+.2f}R</span>' if _rr is not None else '<span class="grey">—</span>'),
                ("Result",   f'<span style="color:{_oc_color}">{_oc.upper()}</span>'),
                ("Date",     f'<span class="grey" style="font-size:11px">{_t.get("exit_date","")}</span>'),
            ]), unsafe_allow_html=True)

    st.divider()

# ===== REGIONAL TOP 5 =====

_regional = top_by_region(ALL_SIGNALS)
if _regional and len(_regional) > 1:
    st.markdown("**Top 5 by Region**")
    _reg_cols = st.columns(len(_regional))
    for _col, (_ex, _sigs) in zip(_reg_cols, _regional.items()):
        _flag = EXCHANGE_FLAGS.get(_ex, "")
        _name = EXCHANGE_NAMES.get(_ex, _ex)
        with _col:
            st.markdown(
                f'<div style="font-size:12px;font-weight:700;color:#7d8590;'
                f'margin-bottom:6px">{_flag} {_name}</div>',
                unsafe_allow_html=True,
            )
            for _rank, _s in enumerate(_sigs, 1):
                _score = _s.get("composite_score", 0)
                _sc = "#3fb950" if _score >= 75 else ("#e3b341" if _score >= 60 else "#f85149")
                _strats = _s.get("strategies_fired", [])
                _b = badges_html(_strats[:1]) if _strats else ""
                st.markdown(
                    f'<div style="display:flex;align-items:center;gap:6px;'
                    f'padding:5px 8px;background:#161b22;border-radius:6px;'
                    f'border:1px solid #21262d;margin-bottom:4px;cursor:pointer">'
                    f'<span style="color:#484f58;font-size:10px;min-width:14px">#{_rank}</span>'
                    f'<span style="font-weight:700;font-size:13px;color:#e6edf3;flex:1">{_s["symbol"]}</span>'
                    f'{_b}'
                    f'<span style="color:{_sc};font-size:12px;font-weight:700">{_score:.0f}</span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
    st.divider()

# ===== SIGNAL DETAIL =====
# Fetch real sentiment, overlay on mock values
live = fetch_live_enrichment(sig["symbol"], sig.get("company_name") or sig["symbol"])
display = {**sig, **{k: v for k, v in live.items() if v is not None}}

# Header
st.markdown(
    f"### {sig['symbol']} &nbsp; {badges_html(sig['strategies_fired'])} "
    f"&nbsp;<span style='color:#7d8590;font-size:14px'>{sig['exchange']}</span>",
    unsafe_allow_html=True,
)

score_color = "#3fb950" if sig["composite_score"] >= 75 else ("#e3b341" if sig["composite_score"] >= 60 else "#f85149")
st.markdown(
    f'{score_bar_html(sig["composite_score"])}'
    f'<span style="color:{score_color};font-weight:700;font-size:14px">'
    f'Composite score {sig["composite_score"]:.0f} / 100</span>',
    unsafe_allow_html=True,
)

# Breakout freshness — warn if signal is stale
from datetime import date as _date_cls
_sig_date_str = sig.get("date", "")
if _sig_date_str:
    try:
        _days_old = (_date_cls.today() - _date_cls.fromisoformat(_sig_date_str)).days
        if _days_old == 0:
            st.success("✓ Fresh signal — detected today")
        elif _days_old == 1:
            st.warning("⚠ Signal is 1 day old — verify entry is still at pivot before acting")
        elif _days_old > 1:
            st.error(f"⚠ Signal is {_days_old} days old — price may have moved significantly past the pivot")
    except Exception:
        pass

# Chart display — full width always; side-by-side for 2; arrows for 3+
chart_path = sig.get("chart_image_path") or None   # kept as default for AI assessment
_strats = sig.get("strategies_fired", [])
_chart_label = "Pipeline chart" if _data_source == "live" else "Synthetic chart — run pipeline to generate real charts"
st.caption(_chart_label)

_all_charts: list[tuple[str, str]] = []
if chart_path:
    _all_charts.append(("Combined", chart_path))
for _cs in _strats:
    _cp = sig.get(f"chart_{_cs}")
    if _cp and _cp != chart_path:
        _all_charts.append((BADGE_LABELS.get(_cs, _cs), _cp))

if not _all_charts:
    st.info("Chart not available — run the pipeline first.")
elif len(_all_charts) == 1:
    st.image(_all_charts[0][1], use_container_width=True)
elif len(_all_charts) == 2:
    _cc1, _cc2 = st.columns(2)
    for _col, (_lbl, _pth) in zip([_cc1, _cc2], _all_charts):
        with _col:
            st.caption(_lbl)
            st.image(_pth, use_container_width=True)
else:
    _nav_key = f"chart_nav_{sig['symbol']}_{sig.get('date', '')}"
    if _nav_key not in st.session_state:
        st.session_state[_nav_key] = 0
    _nav_idx = st.session_state[_nav_key] % len(_all_charts)
    _nav_lbl, _nav_pth = _all_charts[_nav_idx]
    chart_path = _nav_pth
    _na, _nb, _nc = st.columns([1, 8, 1])
    with _na:
        if st.button("◄", key=f"cprev_{sig['symbol']}", use_container_width=True):
            st.session_state[_nav_key] = (_nav_idx - 1) % len(_all_charts)
            st.rerun()
    with _nb:
        st.caption(f"{_nav_lbl}  ·  {_nav_idx + 1} / {len(_all_charts)}")
    with _nc:
        if st.button("►", key=f"cnext_{sig['symbol']}", use_container_width=True):
            st.session_state[_nav_key] = (_nav_idx + 1) % len(_all_charts)
            st.rerun()
    st.image(_nav_pth, use_container_width=True)
# Info strips below chart
rr = display.get("risk_reward")
rs = display.get("rs_rank")
st.markdown('<div class="strip-label">Trade levels</div>', unsafe_allow_html=True)
st.markdown(strip_html([
    ("Entry",   _price_fmt(sig, display.get("entry_price"))),
    ("Stop",    _price_fmt(sig, display.get("stop_price"))),
    ("Target",  _price_fmt(sig, display.get("target_price"))),
    ("R / R",   f'<span class="white">{rr:.1f}×</span>' if rr else '<span class="grey">—</span>'),
    ("RS Rank", f'<span class="white">{rs:.0f}</span><span class="grey" style="font-size:10px">th</span>'
                if rs else '<span class="grey">—</span>'),
]), unsafe_allow_html=True)

_info_l, _info_r = st.columns(2)
with _info_l:
    st.markdown('<div class="strip-label">Fundamentals</div>', unsafe_allow_html=True)
    st.markdown(strip_html([
        ("EPS QoQ",  _pct(display.get("eps_qoq"))),
        ("EPS YoY",  _pct(display.get("eps_yoy"))),
        ("Rev QoQ",  _pct(display.get("revenue_qoq"))),
        ("Rev YoY",  _pct(display.get("revenue_yoy"))),
        ("Earnings", _days(display.get("earnings_days_out"))),
    ]), unsafe_allow_html=True)

with _info_r:
    live_indicator = " 🔴" if not live else " 🟢"
    st.markdown(f'<div class="strip-label">Sentiment{live_indicator}</div>', unsafe_allow_html=True)
    _nc = display.get("news_count_7d")
    st.markdown(strip_html([
        ("Insider buy",  _insider(display.get("insider_buy_days_ago"))),
        ("News sent.",   _sent(display.get("news_sentiment"))),
        ("News 7d",      f'<span class="white">{_nc}</span>' if _nc else '<span class="grey">—</span>'),
        ("Google trend", _trend(display.get("google_trends_chg"))),
    ]), unsafe_allow_html=True)
    _headlines = display.get("news_headlines") or []
    if _headlines:
        _hl_html = "".join(
            f'<div style="color:#8b949e;font-size:11px;padding:3px 0;border-bottom:'
            f'1px solid #21262d20;line-height:1.4">{h}</div>'
            for h in _headlines
        )
        st.markdown(
            f'<div style="margin-top:6px;padding:6px 10px;background:#161b22;'
            f'border-radius:6px;border:1px solid #21262d">{_hl_html}</div>',
            unsafe_allow_html=True,
        )

notes = display.get("pattern_notes", "")
if notes:
    st.markdown(
        f'<div style="color:#7d8590;font-size:12px;margin-top:6px;padding:8px 12px;'
        f'background:#161b22;border-radius:6px;border:1px solid #21262d">{notes}</div>',
        unsafe_allow_html=True,
    )


# -------------------------------------------------------------------------
# Theme Classification
# -------------------------------------------------------------------------

if sig.get("theme_name"):
    _t_m = (sig.get("theme_momentum") or "").lower()
    _t_color = {"strong": "#3fb950", "moderate": "#e3b341", "emerging": "#388bfd"}.get(_t_m, "#7d8590")
    _t_fit = (sig.get("fit_strength") or "").lower()
    _t_fit_color = {"high": "#3fb950", "medium": "#e3b341", "low": "#f85149"}.get(_t_fit, "#7d8590")
    st.markdown('<div class="strip-label" style="margin-top:10px">Theme</div>', unsafe_allow_html=True)
    st.markdown(
        f'<div style="padding:10px 14px;background:#161b22;border-radius:8px;'
        f'border:1px solid #21262d;margin-bottom:6px">'
        f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:6px">'
        f'<span style="font-size:13px;font-weight:700;color:#e6edf3">{sig["theme_name"]}</span>'
        + (f'<span style="font-size:10px;font-weight:600;color:{_t_color};'
           f'background:{_t_color}22;border-radius:4px;padding:2px 6px">{_t_m.upper()}</span>'
           if _t_m else "")
        + (f'<span style="font-size:10px;font-weight:600;color:{_t_fit_color};'
           f'background:{_t_fit_color}22;border-radius:4px;padding:2px 6px">FIT: {_t_fit.upper()}</span>'
           if _t_fit else "")
        + f'</div>'
        + (f'<div style="color:#8b949e;font-size:12px;line-height:1.5">{sig["theme_narrative"]}</div>'
           if sig.get("theme_narrative") else "")
        + f'</div>',
        unsafe_allow_html=True,
    )

# -------------------------------------------------------------------------
# Company & Market Context
# -------------------------------------------------------------------------

st.markdown('<div class="strip-label" style="margin-top:14px">Company &amp; Market Context</div>', unsafe_allow_html=True)

_CONTEXT_KEY = f"context_{sig['symbol']}_{sig.get('date', '')}"
if _CONTEXT_KEY not in st.session_state:
    st.session_state[_CONTEXT_KEY] = None

_run_context = st.button(
    "📰  Analyse company + news", key=f"ctx_btn_{sig['symbol']}", use_container_width=False
)

if _run_context:
    _headlines = display.get("news_headlines") or []
    _theme_nm  = sig.get("theme_name") or "no specific theme identified"
    _theme_nar = sig.get("theme_narrative") or ""
    _eps_yoy   = display.get("eps_yoy")
    _rev_yoy   = display.get("revenue_yoy")
    _earn_out  = display.get("earnings_days_out")

    def _fmt_plain(v):
        return f"{v:+.0%}" if v is not None else "n/a"

    _macro_prompt = (
        f"I'm considering a swing trade in {sig['symbol']} "
        f"({sig.get('company_name', sig['symbol'])}, {sig.get('exchange', '?')}, "
        f"RS rank {sig.get('rs_rank', '?')}th percentile).\n\n"
        f"Theme: {_theme_nm}" + (f" — {_theme_nar}" if _theme_nar else "") + "\n"
        f"Fundamentals: EPS YoY {_fmt_plain(_eps_yoy)}, Revenue YoY {_fmt_plain(_rev_yoy)}"
        + (f", earnings in {_earn_out}d" if _earn_out else "") + "\n"
    )
    if _headlines:
        _macro_prompt += "Recent news:\n" + "\n".join(f"  • {h}" for h in _headlines) + "\n"
    _macro_prompt += (
        "\nAs a swing trading analyst, discuss this stock:\n"
        "1. What macro or sector forces are acting on this stock right now — tailwinds or headwinds?\n"
        "2. What does the news tell us about near-term catalysts or risks?\n"
        "3. Does the fundamental picture support a breakout, or are there concerns?\n"
        "4. Anything in the macro environment I should know before entering?\n"
        "Be specific and direct. Don’t describe chart patterns — I can see the chart. "
        "Focus on the story behind the stock and whether now is the right time."
    )

    try:
        with st.spinner("Asking Claude…"):
            _context_reply = _call_claude_chat(display, None, [], _macro_prompt)
        st.session_state[_CONTEXT_KEY] = _context_reply
        _ck = f"chat_{sig['symbol']}_{sig.get('date', '')}"
        if _ck not in st.session_state:
            st.session_state[_ck] = []
        if not st.session_state[_ck]:
            st.session_state[_ck] = [
                {"role": "user", "content": "Give me a macro and fundamental analysis of this stock."},
                {"role": "assistant", "content": _context_reply},
            ]
        st.rerun()
    except Exception as _exc:
        st.error(f"Analysis failed: {_exc}")

_context_result = st.session_state[_CONTEXT_KEY]
if _context_result is None:
    st.markdown(
        '<div style="color:#484f58;font-size:12px;padding:8px 0">'
        'Click to get a macro &amp; news analysis from Claude — then continue the discussion in the chat below.</div>',
        unsafe_allow_html=True,
    )
else:
    st.markdown(
        f'<div style="margin-top:8px;padding:10px 14px;background:#161b22;'
        f'border-radius:6px;border:1px solid #21262d;font-size:13px;line-height:1.6">'
        f'{_context_result}'
        f'</div>',
        unsafe_allow_html=True,
    )

# -------------------------------------------------------------------------
# Log Entry
# -------------------------------------------------------------------------

st.markdown('<div class="strip-label" style="margin-top:18px">Log Trade</div>', unsafe_allow_html=True)
_strat_key = sig.get("strategies_fired", [""])[0] if sig.get("strategies_fired") else ""
with st.expander(f"📥  Log entry — {sig['symbol']} / {BADGE_LABELS.get(_strat_key, _strat_key)}"):
    with st.form(f"log_entry_{sig['symbol']}_{_strat_key}_{sig.get('date','')}"):
        _lc1, _lc2, _lc3 = st.columns(3)
        with _lc1:
            _l_entry = st.number_input("Entry price",
                value=float(sig.get("entry_price") or 0), min_value=0.0, step=0.01, format="%.2f")
        with _lc2:
            _l_stop = st.number_input("Stop price",
                value=float(sig.get("stop_price") or 0), min_value=0.0, step=0.01, format="%.2f")
        with _lc3:
            _l_target = st.number_input("Target price",
                value=float(sig.get("target_price") or 0), min_value=0.0, step=0.01, format="%.2f")
        _l_notes = st.text_input("Notes (optional)")
        if st.form_submit_button("✓  Confirm entry", use_container_width=True):
            if _l_entry > 0 and _l_stop > 0:
                _saved = trades_db.log_entry(
                    symbol=sig["symbol"],
                    strategy=_strat_key,
                    entry_price=_l_entry,
                    stop_price=_l_stop,
                    target_price=_l_target if _l_target > 0 else None,
                    alert_date=sig.get("date", ""),
                    notes=_l_notes,
                )
                if _saved:
                    st.success(f"✓ Entry logged for {sig['symbol']} — open My Trades to track it")
                else:
                    st.error("Save failed — check Supabase connection")
            else:
                st.warning("Entry price and stop price are required")


# Position size — equity persists across signals via session_state key
st.markdown('<div class="strip-label">Position Size</div>', unsafe_allow_html=True)
if "equity" not in st.session_state:
    st.session_state["equity"] = 100_000
if "risk_pct" not in st.session_state:
    st.session_state["risk_pct"] = 1.0
_pc1, _pc2 = st.columns(2)
with _pc1:
    _equity = st.number_input(
        "Account equity", min_value=1_000, step=5_000,
        key="equity", help="Total trading account size",
    )
with _pc2:
    _risk_pct = st.number_input(
        "Risk per trade (%)", min_value=0.1, max_value=10.0, step=0.5,
        key="risk_pct", help="Max % of equity to lose if stopped out",
    )
_entry = display.get("entry_price")
_stop  = display.get("stop_price")
if _entry and _stop and _entry > _stop and _equity > 0:
    _dollar_risk    = _equity * _risk_pct / 100
    _risk_per_share = _entry - _stop
    _shares         = _dollar_risk / _risk_per_share
    _pos_value      = _shares * _entry
    st.markdown(strip_html([
        ("At risk",        f'<span class="red">{_price_fmt(sig, _dollar_risk)}</span>'),
        ("Shares",         f'<span class="white">{_shares:,.0f}</span>'),
        ("Position value", f'<span class="white">{_price_fmt(sig, _pos_value)}</span>'),
        ("% of equity",    f'<span class="white">{_pos_value / _equity:.1%}</span>'),
    ]), unsafe_allow_html=True)
else:
    st.caption("Enter equity above to calculate position size.")


# -------------------------------------------------------------------------
# Signal Chatbox
# -------------------------------------------------------------------------

st.markdown('<div class="strip-label" style="margin-top:18px">Ask Claude about this signal</div>', unsafe_allow_html=True)

_chat_key = f"chat_{sig['symbol']}_{sig.get('date', '')}"
if _chat_key not in st.session_state:
    st.session_state[_chat_key] = []

_chat_history: list[dict] = st.session_state[_chat_key]

if _chat_history:
    if st.button("🗑  Clear chat", key=f"clearchat_{sig['symbol']}"):
        st.session_state[_chat_key] = []
        st.rerun()

for _msg in _chat_history:
    with st.chat_message(_msg["role"]):
        st.markdown(_msg["content"])

_user_input = st.chat_input(
    f"Ask about {sig['symbol']} — chart context included",
    key=f"chat_input_{sig['symbol']}_{sig.get('date', '')}",
)

if _user_input:
    _chat_history.append({"role": "user", "content": _user_input})
    with st.chat_message("user"):
        st.markdown(_user_input)

    with st.chat_message("assistant"):
        with st.spinner("Thinking…"):
            try:
                _reply = _call_claude_chat(display, chart_path, _chat_history[:-1], _user_input)
            except Exception as _exc:
                _reply = f"Error contacting Claude: {_exc}"
        st.markdown(_reply)

    _chat_history.append({"role": "assistant", "content": _reply})
    st.session_state[_chat_key] = _chat_history
