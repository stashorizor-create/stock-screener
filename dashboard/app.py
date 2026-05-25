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

from dashboard.mock_data import MOCK_SIGNALS, make_df_for, _scale
from dashboard.market import fetch_sector_returns
from charts.generator import generate_chart
from screening.indicators import compute_all
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
# CSS — desktop + mobile responsive
# ---------------------------------------------------------------------------

st.markdown("""
<style>
/* Push content below Streamlit toolbar */
.block-container { padding-top: 3.5rem; }

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
div[data-testid="stRadio"] > div { gap: 2px; }
div[data-testid="stRadio"] label {
    background: #161b22;
    border-radius: 6px;
    padding: 7px 10px !important;
    cursor: pointer;
    border: 1px solid transparent;
    font-size: 13px;
}
div[data-testid="stRadio"] label:has(input:checked) {
    border-color: #4488FF;
    background: #1a2a4a;
}
div[data-testid="stRadio"] label > div:first-child { display: none; }

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
# Chart cache
# ---------------------------------------------------------------------------

@st.cache_resource
def build_all_charts() -> dict[str, str]:
    paths = {}
    for s in MOCK_SIGNALS:
        df = _scale(make_df_for(s["_seed"]), s["_price"])
        df = compute_all(df)
        path = generate_chart(df, s, s["symbol"])
        paths[s["symbol"]] = str(path)
    return paths


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
            # Use per-strategy entry price when available
            if detail.get("pivot_price"):
                row["entry_price"] = detail["pivot_price"]
            elif detail.get("entry_trigger"):
                row["entry_price"] = detail["entry_trigger"]
            rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# Sidebar — filters + ranked list
# ---------------------------------------------------------------------------

ALL_ROWS = expand_to_rows(MOCK_SIGNALS)
charts = build_all_charts()

STRAT_MAP = {
    "VCP": "vcp", "Qullamaggie": "qullamaggie",
    "5 EMA Pullback": "ema_pullback", "Buyable Gap Up": "gap_up",
    "Pocket Pivot": "pocket_pivot",
}

with st.sidebar:
    st.markdown("## 📈 Screener")
    st.caption("2026-05-25  ·  mock data")
    st.divider()

    strat_filter = st.selectbox(
        "Strategy", ["All", "VCP", "Qullamaggie", "5 EMA Pullback", "Buyable Gap Up", "Pocket Pivot"]
    )
    min_score = st.slider("Min score", 0, 100, 60, format="≥ %d")
    exch_filter = st.selectbox(
        "Exchange", ["All", "STO", "CPH", "OSL", "NASDAQ", "NYSE"]
    )

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
        f"{score_color_char(s['composite_score'])}  #{i+1}  {s['symbol']:<8}  "
        f"{s['composite_score']:.0f}  "
        f"{BADGE_LABELS.get(s['strategies_fired'][0], '?') if s.get('strategies_fired') else '?'}"
        for i, s in enumerate(filtered)
    ]
    chosen = st.radio("Signals", labels, label_visibility="collapsed")
    sig = filtered[labels.index(chosen)]

    st.divider()
    if st.button("🌡️  Market Overview", key="market_toggle", use_container_width=True):
        st.session_state["market_open"] = not st.session_state.get("market_open", False)


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
            _t_left, _t_right = st.columns([3, 1])
            with _t_left:
                st.caption(f"Generated: {_themes.get('generated_at', 'unknown')}")
            with _t_right:
                if st.button("Refresh", key="refresh_themes_btn2"):
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
                    f'<div style="color:#7d8590;font-size:11px;line-height:1.5;margin-bottom:4px">'
                    f'{theme["description"]}</div>'
                    f'<div style="color:#484f58;font-size:10px">Examples: '
                    f'<span style="color:#388bfd">{tickers}</span></div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

st.divider()

# ===== SIGNAL DETAIL =====
# Fetch real sentiment, overlay on mock values
live = fetch_live_enrichment(sig["symbol"], sig.get("_trends_keyword", sig["symbol"]))
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

# Chart
chart_path = charts.get(sig["symbol"])
if chart_path and Path(chart_path).exists():
    st.caption("Synthetic chart — real OHLCV loads after first pipeline run")
    st.image(chart_path, use_container_width=True)
else:
    st.info("Chart not available.")

# Two-column layout — all info fits without scrolling
col_left, col_right = st.columns(2)

with col_left:
    st.markdown('<div class="strip-label">Trade levels</div>', unsafe_allow_html=True)
    rr = display.get("risk_reward")
    rs = display.get("rs_rank")
    st.markdown(strip_html([
        ("Entry",   _price_fmt(sig, display.get("entry_price"))),
        ("Stop",    _price_fmt(sig, display.get("stop_price"))),
        ("Target",  _price_fmt(sig, display.get("target_price"))),
        ("R / R",   f'<span class="white">{rr:.1f}×</span>' if rr else '<span class="grey">—</span>'),
        ("RS Rank", f'<span class="white">{rs:.0f}</span><span class="grey" style="font-size:10px">th</span>'
                    if rs else '<span class="grey">—</span>'),
    ]), unsafe_allow_html=True)

    st.markdown('<div class="strip-label">Position Size</div>', unsafe_allow_html=True)
    _pc1, _pc2 = st.columns(2)
    with _pc1:
        _equity = st.number_input(
            "Account equity", value=100_000, step=5_000, min_value=1_000,
            key="equity", help="Total trading account size",
        )
    with _pc2:
        _risk_pct = st.number_input(
            "Risk per trade (%)", value=1.0, step=0.5, min_value=0.1, max_value=10.0,
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

with col_right:
    st.markdown('<div class="strip-label">Fundamentals</div>', unsafe_allow_html=True)
    st.markdown(strip_html([
        ("EPS QoQ",  _pct(display.get("eps_qoq"))),
        ("EPS YoY",  _pct(display.get("eps_yoy"))),
        ("Rev QoQ",  _pct(display.get("revenue_qoq"))),
        ("Rev YoY",  _pct(display.get("revenue_yoy"))),
        ("Earnings", _days(display.get("earnings_days_out"))),
    ]), unsafe_allow_html=True)

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
