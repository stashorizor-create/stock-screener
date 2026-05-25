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

import streamlit as st

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
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Password gate — must pass before anything renders
# ---------------------------------------------------------------------------

def _check_password() -> bool:
    if st.session_state.get("_auth_ok"):
        return True

    # Resolve the password from secrets — try [auth].password then flat password key.
    # FileNotFoundError means no secrets.toml at all (local dev) → open access.
    # Secrets present but key missing → block with config error so the mistake is visible.
    correct = None
    dev_mode = False
    try:
        auth_section = st.secrets.get("auth") or {}
        correct = auth_section.get("password") or st.secrets.get("password")
    except FileNotFoundError:
        dev_mode = True

    if dev_mode:
        return True  # local dev, no secrets file

    if not correct:
        st.error("Auth not configured: add `[auth]\\npassword = \"...\"` to Streamlit Cloud secrets.")
        st.stop()

    def _submit():
        if st.session_state.get("_pw_input") == correct:
            st.session_state["_auth_ok"] = True
        else:
            st.session_state["_auth_bad"] = True

    st.markdown("## AI Stock Screener")
    st.text_input("Password", type="password", key="_pw_input", on_change=_submit)
    if st.button("Login"):
        _submit()
    if st.session_state.get("_auth_bad"):
        st.error("Incorrect password.")
        st.session_state["_auth_bad"] = False
    return False

if not _check_password():
    st.stop()

# ---------------------------------------------------------------------------
# CSS — desktop + mobile responsive
# ---------------------------------------------------------------------------

st.markdown("""
<style>
/* Remove top padding — main and sidebar */
.block-container { padding-top: 0 !important; margin-top: -2rem !important; }
section[data-testid="stSidebar"] > div:first-child { padding-top: 0 !important; margin-top: -2rem !important; }

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

/* Hide Streamlit top header, hamburger menu, footer */
header[data-testid="stHeader"] { display: none !important; }
#MainMenu { visibility: hidden !important; }
footer { visibility: hidden !important; }

/* Hide Streamlit's built-in image fullscreen button */
button[title="View fullscreen"] { display: none !important; }


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

    # Reddit mentions (requires credentials in .env)
    try:
        from enrichment.reddit import get_mention_counts
        counts = get_mention_counts(symbol)
        wsb = counts.get("wallstreetbets")
        dtr = counts.get("Daytrading")
        if wsb is not None:
            result["wsb_mentions"] = wsb if wsb > 0 else None
        if dtr is not None:
            result["daytrading_mentions"] = dtr if dtr > 0 else None
    except Exception:
        pass

    # StockTwits — API now requires paid plan, disabled

    # News activity (yfinance, no credentials)
    try:
        from enrichment.news import get_news_enrichment
        news = get_news_enrichment(symbol)
        if news.get("news_sentiment") is not None:
            result["news_sentiment"] = news["news_sentiment"]
        if news.get("news_count_7d") is not None:
            result["news_count_7d"] = news["news_count_7d"]
    except Exception:
        pass

    return result


# ---------------------------------------------------------------------------
# HTML helpers
# ---------------------------------------------------------------------------

BADGE_COLORS = {
    "vcp":          "#388bfd",
    "qullamaggie":  "#a371f7",
    "ema_pullback": "#e3b341",
    "gap_up":       "#3fb950",
    "pocket_pivot": "#f0883e",
}
BADGE_LABELS = {
    "vcp": "VCP", "qullamaggie": "Q", "ema_pullback": "EMA5",
    "gap_up": "BGU", "pocket_pivot": "PP",
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
    sym = {"USD": "$", "DKK": "kr", "SEK": "kr", "NOK": "kr"}.get(sig["currency"], "")
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
# Load signals
# ---------------------------------------------------------------------------

ALL_SIGNALS, _data_source = get_signals()
ALL_ROWS = ALL_SIGNALS

STRAT_MAP = {
    "VCP": "vcp", "Qullamaggie": "qullamaggie",
    "5 EMA Pullback": "ema_pullback", "Buyable Gap Up": "gap_up",
    "Pocket Pivot": "pocket_pivot",
}

# ---------------------------------------------------------------------------
# Sidebar — filters + ranked list
# ---------------------------------------------------------------------------

with st.sidebar:
    _run_date = ALL_SIGNALS[0].get("date", "—") if ALL_SIGNALS else "—"
    _source_label = "live" if _data_source == "live" else "mock data"
    st.caption(f"Last updated: {_run_date}  ·  {_source_label}")
    if _data_source == "mock":
        _err = get_last_load_error()
        st.warning(_err if _err else "Showing mock data")
        st.info(_debug_db())

    # Filters — compact layout, no divider needed before them
    _fc1, _fc2 = st.columns(2)
    with _fc1:
        strat_filter = st.selectbox(
            "Strategy",
            ["All", "VCP", "Qullamaggie", "5 EMA Pullback", "Buyable Gap Up", "Pocket Pivot"],
            label_visibility="collapsed",
        )
    with _fc2:
        exch_filter = st.selectbox(
            "Exchange", ["All", "STO", "OSL", "CPH", "HEL", "NASDAQ", "NYSE"],
            label_visibility="collapsed",
        )
    min_score = st.slider("Min score", 0, 100, 60, format="≥ %d")

    filtered = [
        s for s in ALL_ROWS
        if s["composite_score"] >= min_score
        and (strat_filter == "All" or STRAT_MAP.get(strat_filter) in s["strategies_fired"])
        and (exch_filter == "All" or s["exchange"] == exch_filter)
    ]

    unique_stocks = len({s["symbol"] for s in filtered})
    st.markdown(
        f"**{len(filtered)} signal{'s' if len(filtered) != 1 else ''}** "
        f"<span style='color:#7d8590;font-size:12px'>({unique_stocks} stock{'s' if unique_stocks != 1 else ''})</span>",
        unsafe_allow_html=True,
    )

    if not filtered:
        st.warning("No signals match filters.")
        st.stop()

    score_color_char = lambda s: ("🟢" if s >= 75 else ("🟡" if s >= 60 else "🔴"))
    labels = [
        f"#{i+1} {score_color_char(s['composite_score'])} **{s['symbol']}**"
        f" `{'|'.join(BADGE_LABELS.get(st, '?') for st in s.get('strategies_fired', [])[:3]) or '?'}`"
        f" {s['composite_score']:.0f}"
        for i, s in enumerate(filtered)
    ]

    chosen = st.radio("Signals", labels, label_visibility="collapsed")
    sig = filtered[labels.index(chosen)]

    st.divider()
    if st.button("🌡️  Market Overview", key="market_toggle", use_container_width=True):
        st.session_state["market_open"] = not st.session_state.get("market_open", False)
    if st.button("📒  My Trades", key="trades_toggle", use_container_width=True):
        st.session_state["trades_open"] = not st.session_state.get("trades_open", False)


# ---------------------------------------------------------------------------
# Main content
# ---------------------------------------------------------------------------

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

# Chart — use stored path from pipeline run, fall back to None
chart_path = sig.get("chart_image_path") or None

# Chart-switching buttons for multi-strategy stocks
_strats = sig.get("strategies_fired", [])
_chart_strat_key = f"chart_strat_{sig['symbol']}_{sig.get('date', '')}"
if _chart_strat_key not in st.session_state:
    st.session_state[_chart_strat_key] = None
_per_strat_charts = [s for s in _strats if sig.get(f"chart_{s}")]
if len(_per_strat_charts) >= 1 and chart_path:
    _scols = st.columns(len(_per_strat_charts) + 1)
    _cur_sel = st.session_state.get(_chart_strat_key)
    with _scols[0]:
        if st.button("Combined", key=f"cbtn_main_{sig['symbol']}", use_container_width=True,
                     type="primary" if _cur_sel is None else "secondary"):
            st.session_state[_chart_strat_key] = None
            st.rerun()
    for _bi, _strat in enumerate(_per_strat_charts):
        with _scols[_bi + 1]:
            if st.button(BADGE_LABELS.get(_strat, _strat), key=f"cbtn_{_strat}_{sig['symbol']}",
                         use_container_width=True,
                         type="primary" if _cur_sel == _strat else "secondary"):
                st.session_state[_chart_strat_key] = _strat
                st.rerun()
    _sel = st.session_state.get(_chart_strat_key)
    if _sel and sig.get(f"chart_{_sel}"):
        chart_path = sig.get(f"chart_{_sel}")

_ck = f"chart_big_{sig['symbol']}"
_chart_big = st.session_state.get(_ck, False)

_c1, _c2 = st.columns([9, 2])
with _c1:
    _chart_label = "Pipeline chart" if _data_source == "live" else "Synthetic chart — run pipeline to generate real charts"
    st.caption(_chart_label)
with _c2:
    _btn_label = "✕ Collapse" if _chart_big else "⤢ Full chart"
    if st.button(_btn_label, key=f"chbtn_{sig['symbol']}", use_container_width=True,
                 help="Expand chart to full width / collapse back to preview"):
        st.session_state[_ck] = not _chart_big
        st.rerun()

_chart_is_url = chart_path and chart_path.startswith("http")
_chart_is_local = chart_path and not _chart_is_url and Path(chart_path).exists()

if _chart_is_url or _chart_is_local:
    if _chart_big:
        st.image(chart_path, use_container_width=True)
    else:
        st.image(chart_path, width=650)
else:
    st.info("Chart not available.")

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
# AI Assessment
# -------------------------------------------------------------------------

st.markdown('<div class="strip-label" style="margin-top:14px">AI Assessment</div>', unsafe_allow_html=True)

_AI_KEY = f"ai_result_{sig['symbol']}"
if _AI_KEY not in st.session_state:
    st.session_state[_AI_KEY] = None

col_btn, col_status = st.columns([1, 3])
with col_btn:
    run_ai = st.button("Run AI assessment", key=f"ai_btn_{sig['symbol']}", use_container_width=True)

if run_ai:
    if not chart_path or not Path(chart_path).exists():
        with col_status:
            st.warning("Chart file missing — cannot run assessment.")
    else:
        try:
            from ai.agent import assess_signal as _assess
            with st.spinner("Asking Claude to review the chart…"):
                result = _assess(display, chart_path)
            if result is None:
                with col_status:
                    st.warning("Assessment unavailable — check ANTHROPIC_API_KEY in .env")
            else:
                st.session_state[_AI_KEY] = result
        except Exception as _exc:
            with col_status:
                st.error(f"AI assessment failed: {_exc}")

ai = st.session_state[_AI_KEY]

if ai is None:
    st.markdown(
        '<div style="color:#484f58;font-size:12px;padding:8px 0">'
        'Click the button above to run a visual chart assessment via Claude.</div>',
        unsafe_allow_html=True,
    )
else:
    pq = ai["pattern_quality"]
    pq_color = "#3fb950" if pq >= 7 else ("#e3b341" if pq >= 5 else "#f85149")
    conf = ai["confidence_score"]
    conf_color = "#3fb950" if conf >= 75 else ("#e3b341" if conf >= 60 else "#f85149")

    st.markdown(strip_html([
        ("Pattern quality",
         f'<span style="color:{pq_color};font-weight:700">{pq}/10</span>'),
        ("AI confidence",
         f'<span style="color:{conf_color};font-weight:700">{conf:.0f}</span>'
         f'<span style="color:#484f58;font-size:10px">/100</span>'),
        ("Tokens used",
         f'<span class="grey" style="font-size:12px">'
         f'{ai["input_tokens"]+ai["output_tokens"]:,}</span>'),
    ]), unsafe_allow_html=True)

    st.markdown(
        f'<div style="margin-top:8px;padding:10px 14px;background:#161b22;'
        f'border-radius:6px;border:1px solid #21262d;font-size:13px;line-height:1.6">'
        f'{ai["chart_assessment"]} {ai["trade_narrative"]}'
        f'</div>',
        unsafe_allow_html=True,
    )

    if ai.get("red_flags"):
        flags_html = "".join(
            f'<div style="color:#f85149;font-size:12px;margin-top:4px">⚠ {f}</div>'
            for f in ai["red_flags"]
        )
        st.markdown(
            f'<div style="margin-top:6px;padding:8px 14px;background:#1a1215;'
            f'border-radius:6px;border:1px solid #3d1f20">{flags_html}</div>',
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
    system = (
        f"You are a stock trading assistant reviewing {sig['symbol']} "
        f"({sig.get('exchange', '?')}). Signal data:\n"
        f"- Strategies detected: {', '.join(strats)}\n"
        f"- Composite score: {sig.get('composite_score', '?')}/100\n"
        f"- Entry: {sig.get('entry_price', '?')}, Stop: {sig.get('stop_price', '?')}, "
        f"Target: {sig.get('target_price', '?')}\n"
        f"- RS Rank: {sig.get('rs_rank', '?')}th percentile\n"
        f"- Signal date: {sig.get('date', '?')}\n"
        f"The chart image is attached to the first message in the conversation. "
        f"Be concise, specific, and actionable for a swing trader."
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
                _reply = _call_claude_chat(sig, chart_path, _chat_history[:-1], _user_input)
            except Exception as _exc:
                _reply = f"Error contacting Claude: {_exc}"
        st.markdown(_reply)

    _chat_history.append({"role": "assistant", "content": _reply})
    st.session_state[_chat_key] = _chat_history
