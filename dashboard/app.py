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
}
BADGE_LABELS = {
    "vcp": "VCP", "qullamaggie": "Q", "ema_pullback": "EMA5",
    "gap_up": "BGU", "pocket_pivot": "PP", "sma_inside_day": "SMA-ID",
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
        + f"The chart image may be attached. Discuss macro context, news, and fundamentals alongside technicals. "
        f"Be concise and actionable for a swing trader."
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
        # Newsletter sidebar is minimal — date selector rendered in main area
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
    st.download_button(
        "📥 TradingView watchlist",
        data="\n".join(_tv_lines),
        file_name=f"watchlist_{_run_date}.txt",
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


# ---------------------------------------------------------------------------
# Newsletter data loader
# ---------------------------------------------------------------------------

@st.cache_data(ttl=300, show_spinner=False)
def get_newsletter() -> tuple[dict | None, list[dict]]:
    """Load latest newsletter from DB. Returns (market_record, picks_list)."""
    try:
        from database.models import NewsletterMarket, NewsletterPick, SessionLocal
        with SessionLocal() as session:
            market = (
                session.query(NewsletterMarket)
                .order_by(NewsletterMarket.email_date.desc())
                .first()
            )
            if not market:
                return None, []
            picks = (
                session.query(NewsletterPick)
                .filter(NewsletterPick.email_date == market.email_date)
                .order_by(NewsletterPick.source_section, NewsletterPick.ticker)
                .all()
            )
            m = {c.name: getattr(market, c.name) for c in market.__table__.columns}
            ps = [{c.name: getattr(p, c.name) for c in p.__table__.columns} for p in picks]
            return m, ps
    except Exception as _e:
        return None, [{"_error": str(_e)}]


def _render_newsletter_page():
    _market, _picks = get_newsletter()

    st.markdown("## Alex's Picks — PrimeTrading")

    # Surface DB errors instead of silently showing empty state
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

    _date = _market.get("email_date", "")
    _stance = (_market.get("market_stance") or "unknown").upper()
    _stance_color = {
        "BULLISH": "#3fb950", "NEUTRAL": "#e3b341",
        "CAUTIOUS": "#e3b341", "BEARISH": "#f85149",
    }.get(_stance, "#7d8590")

    st.markdown(
        f'<div style="display:flex;align-items:center;gap:12px;margin-bottom:12px">'
        f'<span style="color:#8b949e;font-size:13px">{_date}</span>'
        f'<span style="font-size:12px;font-weight:700;color:{_stance_color};'
        f'background:{_stance_color}22;border-radius:4px;padding:3px 8px">{_stance}</span>'
        f'</div>',
        unsafe_allow_html=True,
    )
    if _market.get("market_notes"):
        st.markdown(
            f'<div style="padding:10px 14px;background:#161b22;border-radius:8px;'
            f'border:1px solid #21262d;color:#8b949e;font-size:13px;margin-bottom:16px">'
            f'{_market["market_notes"]}</div>',
            unsafe_allow_html=True,
        )

    # Cross-reference with screener signals
    _signal_tickers = {s["symbol"].upper() for s in ALL_SIGNALS}

    def _in_screener_badge(ticker: str) -> str:
        if ticker.upper() in _signal_tickers:
            return '<span style="font-size:10px;color:#3fb950;background:#3fb95022;border-radius:4px;padding:2px 6px">✓ In screener</span>'
        return ""

    def _action_badge(action: str) -> str:
        colors = {
            "FOCUS": "#388bfd", "LONG": "#3fb950", "ADDED": "#3fb950",
            "NEW": "#3fb950", "TRIM": "#e3b341", "OUT": "#f85149",
            "WATCH": "#7d8590", "EP": "#a371f7", "STALK": "#58a6ff",
        }
        c = colors.get(action.upper(), "#7d8590")
        return f'<span style="font-size:10px;font-weight:700;color:{c};background:{c}22;border-radius:4px;padding:2px 6px">{action.upper()}</span>'

    # Group picks by section
    _sections: dict[str, list[dict]] = {}
    for p in _picks:
        _sections.setdefault(p["source_section"], []).append(p)

    _SECTION_LABELS = {
        "portfolio_table": "Portfolio (from table)",
        "focus_list":      "Focus List",
        "portfolio":       "Portfolio Moves",
        "scan_21dma":      "21 DMA Scan",
        "ep_list":         "EP List",
        "stalklist":       "Stalk List",
    }
    _SECTION_ORDER = ["portfolio_table", "focus_list", "portfolio", "scan_21dma", "ep_list", "stalklist"]

    for _sec_key in _SECTION_ORDER:
        if _sec_key not in _sections:
            continue
        _sec_picks = _sections[_sec_key]
        st.markdown(f"**{_SECTION_LABELS.get(_sec_key, _sec_key)}**")

        if _sec_key == "portfolio_table":
            # Rich table: entry / stop / target / size
            rows_html = ""
            for p in _sec_picks:
                _e = f"${p['entry_price']:.2f}" if p.get("entry_price") else "—"
                _s = f"${p['stop_price']:.2f}"  if p.get("stop_price")  else "—"
                _t = f"${p['target_price']:.2f}" if p.get("target_price") else "—"
                _sz = f"{p['position_size_pct']:.1f}%" if p.get("position_size_pct") else "—"
                rows_html += (
                    f'<div class="strip" style="margin-bottom:4px">'
                    f'<div class="cell" style="flex:2;text-align:left;padding-left:10px">'
                    f'<span style="font-weight:700;color:#e6edf3">{p["ticker"]}</span> '
                    + _action_badge(p.get("action") or "") + " "
                    + _in_screener_badge(p["ticker"])
                    + f'</div>'
                    f'<div class="cell"><span class="cell-label">ENTRY</span>'
                    f'<div class="cell-value" style="font-size:13px">{_e}</div></div>'
                    f'<div class="cell"><span class="cell-label">STOP</span>'
                    f'<div class="cell-value" style="font-size:13px;color:#f85149">{_s}</div></div>'
                    f'<div class="cell"><span class="cell-label">TARGET</span>'
                    f'<div class="cell-value" style="font-size:13px;color:#3fb950">{_t}</div></div>'
                    f'<div class="cell"><span class="cell-label">SIZE</span>'
                    f'<div class="cell-value" style="font-size:13px">{_sz}</div></div>'
                    f'</div>'
                )
            if rows_html:
                st.markdown(rows_html, unsafe_allow_html=True)

        elif _sec_key in ("scan_21dma", "ep_list", "stalklist"):
            # Compact chip list
            chips = " ".join(
                f'<span style="display:inline-block;padding:3px 8px;margin:2px;'
                f'background:#161b22;border:1px solid #21262d;border-radius:6px;'
                f'font-size:13px;font-weight:700;color:#e6edf3">'
                f'{p["ticker"]}</span>'
                + _in_screener_badge(p["ticker"])
                for p in _sec_picks
            )
            st.markdown(f'<div style="margin-bottom:12px">{chips}</div>', unsafe_allow_html=True)

        else:
            # focus_list + portfolio: rows with action badge + optional price
            for p in _sec_picks:
                _price_str = ""
                if p.get("entry_price"):
                    _price_str = f' <span style="color:#8b949e;font-size:12px">@ ${p["entry_price"]:.2f}</span>'
                st.markdown(
                    f'<div style="display:flex;align-items:center;gap:8px;'
                    f'padding:6px 10px;background:#161b22;border-radius:6px;'
                    f'border:1px solid #21262d;margin-bottom:4px">'
                    f'<span style="font-weight:700;color:#e6edf3;min-width:60px">{p["ticker"]}</span>'
                    + _action_badge(p.get("action") or "")
                    + _price_str + " "
                    + _in_screener_badge(p["ticker"])
                    + (f'<span style="color:#7d8590;font-size:11px;margin-left:auto">{p["notes"]}</span>'
                       if p.get("notes") else "")
                    + "</div>",
                    unsafe_allow_html=True,
                )

    # Date navigation — load other available dates
    try:
        from database.models import NewsletterMarket, SessionLocal
        with SessionLocal() as _sess:
            _all_dates = [
                r[0] for r in _sess.query(NewsletterMarket.email_date)
                .order_by(NewsletterMarket.email_date.desc()).limit(20).all()
            ]
        if len(_all_dates) > 1:
            st.divider()
            st.caption(f"{len(_all_dates)} newsletters in database · showing latest")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Main content
# ---------------------------------------------------------------------------

# Newsletter page — render and stop before screener code
if _page == "📧 Alex's Picks":
    _render_newsletter_page()
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
