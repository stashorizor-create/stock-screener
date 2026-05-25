# Trading Intelligence System — Project Brief for Claude Code

## Project Overview

Build a fully automated, nightly swing-trade screening and alert system covering **Scandinavian and US equity markets** (with Nordic markets as primary focus). The system identifies high-quality technical setups using Minervini/Qullamaggie-style criteria, enriches candidates with contextual signals (insider activity, financial news, Google Trends, social sentiment), and delivers a prioritised shortlist with entry, stop, and target levels via Telegram/email alert each evening.

The system is built for **personal use initially**, with architecture designed to support future multi-user SaaS expansion.

---

## Core Design Principles

1. **Deterministic before probabilistic** — rule-based technical screening runs first across the full universe; AI is used only on the narrow surviving candidate set
2. **Hard filters before soft evidence** — chart structure, stage, base quality, and liquidity are binary gates; insider data, news, trends, and social signals influence ranking only
3. **End-of-day only in v1** — no intraday data; swing trading timeframe makes EOD sufficient and avoids significant cost/complexity increase
4. **Single user, personal licensing** — all data provider choices reflect personal/non-commercial use terms
5. **TradingView retained for intraday execution** — this system replaces nightly screening, not live charting

---

## Architecture Overview

### Five-Stage Nightly Pipeline

```
Universe Manager
    → Nightly OHLCV Ingestion (Borsdata Pro+ API)
        → Rule-Based Technical Screener (Python / TA-Lib)
            → AI Chart Review (Claude Haiku 4.5 vision, Batch API)
                → Contextual Enrichment (top candidates only)
                    → Confluence Scoring & Ranking
                        → Alert Delivery (Telegram + email)
```

### Six Modules

| Module | Responsibility |
|---|---|
| **Universe Manager** | Maintains stock universe, liquidity filters, exchange calendars |
| **Data Ingestor** | Nightly EOD OHLCV pull, corporate actions, 52-week history retention |
| **Technical Screener** | Computes indicators, applies hard filter rules, generates candidates |
| **Enrichment Layer** | Insider buys, financial news, Google Trends, Reddit/StockTwits — top candidates only |
| **Synthesis Engine** | Confluence scoring, AI chart review, narrative summary generation |
| **Alert / UI Layer** | Telegram bot, email delivery, simple web dashboard for alert review |

---

## Stock Universe

### Coverage
- **Norway (Oslo Børs):** All liquid equities, minimum avg daily volume 500k NOK
- **Sweden (Nasdaq Stockholm):** All liquid equities, minimum avg daily volume 2M SEK
- **Denmark (Nasdaq Copenhagen):** Liquid large/mid cap
- **Finland (Nasdaq Helsinki):** Liquid large/mid cap
- **US:** Russell 3000 equivalent, minimum avg daily volume 500k shares, price > $10
- **Broader Europe (v2):** Frankfurt, Euronext Paris/Amsterdam — deferred to after v1 stable

### Estimated Universe Size
- Nordic: ~600-800 liquid names
- US: ~2,000-2,500 liquid names
- Total v1: ~3,000-3,500 names

### Liquidity Filters (applied nightly)
- Minimum 50-day average volume threshold (exchange-specific)
- Minimum price threshold
- Exclude ETFs, REITs, preferred shares, warrants

---

## Data Providers

### Primary Market Data
**Borsdata Pro+** (borsdata.se)
- EOD OHLCV for all Nordic exchanges
- Global instruments including US stocks
- Fundamentals, KPIs, ownership data
- REST JSON API, 100 calls/10 seconds rate limit
- Personal use license

### Financial News
**Finnhub** (finnhub.io)
- Company news, earnings calendar, market news
- Paid tier (~$40/month) for adequate coverage
- Covers US + European markets

### Insider Activity
**Quiver Quantitative** (quiverquant.com)
- SEC Form 4 filings (US insider buys/sells)
- Personal plan (~$25/month)
- Nordic insider data: supplement with direct Oslo Børs/Finansinspektionen scraping

### Social & Sentiment (secondary signals only)
- **Google Trends:** pytrends Python library (free, unofficial)
- **StockTwits:** free public API
- **Reddit:** PRAW library, free personal tier (r/stocks, r/investing, r/wallstreetbets)
- **Twitter/X:** pay-per-use API (~$15/month at low personal volume)

### Corporate Actions / Calendars
- Borsdata API for Nordic
- Finnhub for US earnings calendar

---

## Technical Stack

### Language
Python 3.11+

### Key Libraries
```
pandas              # Data manipulation
pandas-ta           # Technical indicators (preferred over TA-Lib for ease)
ta-lib              # Fallback for specific indicators
mplfinance          # Chart image generation
plotly              # Interactive charts (dashboard)
sqlalchemy          # Database ORM
psycopg2            # PostgreSQL driver
anthropic           # Claude API (chart review + synthesis)
python-telegram-bot # Alert delivery
apscheduler         # Nightly job scheduling
requests / httpx    # API calls
pytrends            # Google Trends
praw                # Reddit API
```

### Database
**PostgreSQL**

Schema tables (minimum):
- `universe` — tracked symbols, exchange, liquidity flags, last updated
- `ohlcv` — daily OHLCV per symbol, adjusted for splits
- `indicators` — computed technical indicators per symbol per date
- `candidates` — symbols passing technical screen each night, with scores
- `enrichment` — insider, news, trends, social data per candidate per date
- `alerts` — final alert records with entry/stop/target, confidence score, narrative
- `strategy_params` — user strategy parameter profile (hard filter thresholds)
- `alert_feedback` — user accept/reject feedback per alert for future refinement

### Infrastructure
- Small cloud VM (DigitalOcean, Hetzner, or AWS EC2 t3.small)
- PostgreSQL on same VM or managed instance
- Scheduled via APScheduler or cron
- Runs nightly after market close (target: complete before midnight local time)

---

## Technical Screening Rules (Hard Filters)

These are Minervini Stage 2 / Qullamaggie momentum breakout criteria. All must pass for a stock to proceed to AI review.

### Trend / Stage Filters
- Price > 50-day SMA
- Price > 150-day SMA
- Price > 200-day SMA
- 50-day SMA > 150-day SMA
- 150-day SMA > 200-day SMA
- 200-day SMA trending upward for minimum 4 weeks
- Price within 25% of 52-week high

### Relative Strength
- RS rank in top 30% of universe (price performance vs universe over 63 days)
- RS line trending upward — making new highs preferred

### Base Detection
- Prior uptrend: minimum 30% gain before base formation
- Base length: minimum 4 weeks, maximum 52 weeks
- Base depth: maximum 35% correction from high to low within base
- Price range within base: closes within 15% range for base period
- ATR declining during base (volatility contraction)
- Volume declining during base (drying up toward lows)

### Pivot & Entry Zone
- Stock within 5% of base high (pivot point)
- Or breaking above pivot with volume confirmation

### Liquidity
- 50-day average volume above exchange threshold
- Sufficient float for institutional participation

---

## Soft Evidence (Ranking Signals)

These do not disqualify a stock but adjust its confidence score and rank:

| Signal | Weight (indicative) | Source |
|---|---|---|
| CEO / insider buy within 90 days | High | Quiver Quant / Finansinspektionen |
| Positive news sentiment last 7 days | Medium | Finnhub |
| Google Trends acceleration for company/sector | Medium | pytrends |
| Hot sector/theme alignment | Medium | News tagging via LLM |
| StockTwits / Reddit mention velocity increase | Low | Public APIs |
| RS line making new highs | High | Computed internally |
| Earnings not within 2 weeks (avoid binary risk) | Modifier | Finnhub calendar |

---

## AI Components

### Chart Review (Claude Haiku 4.5, Batch API)
**Input:** mplfinance-generated chart image (1000×600px) showing:
- 1 year of daily OHLCV candlesticks
- 50, 150, 200-day SMAs
- Volume bars with 50-day volume average line
- Base period highlighted
- Pivot level annotated

**Prompt instructs model to assess:**
- Is this a genuine Stage 2 base? (yes/no + reasoning)
- Base quality: tight/acceptable/sloppy
- Pivot point validation
- Suggested entry price (just above pivot)
- Stop loss (below base low or ATR-based)
- Initial target (measured move from base depth)
- Overall pattern quality score (1-10)

**Output:** Structured JSON

### Synthesis / Narrative (Claude Sonnet 4.6, Batch API)
For top 10-15 candidates post chart review, synthesise all signals into a plain-language summary:

**Input:** Technical score, chart assessment, insider data, news headlines, Google Trends data, sector/theme tags

**Output:** 3-5 sentence narrative explaining why this stock is alerting tonight, plus final confidence score

### Conversational Strategy Refinement (Claude Sonnet 4.6)
User-facing chat interface (v2) where natural language input updates structured strategy parameters. Example:

- User: "I want tighter bases, maximum 12% depth"
- System: Updates `strategy_params.base_max_depth = 0.12`
- Confirmed back to user in plain language

---

## Alert Format

### Telegram Message (per candidate)
```
🟢 TICKER — Exchange
Setup: Minervini Stage 2 Breakout
Pattern quality: 8/10

Entry: $XX.XX (above pivot)
Stop: $XX.XX (below base low)
Target: $XX.XX (measured move)
Risk/Reward: 1:3.2

Signals:
✅ Stage 2 trend structure
✅ 6-week tight base, ATR compression
✅ CEO bought 15,000 shares (12 days ago)
✅ Sector: AI Infrastructure — strong theme momentum
⚠️ Earnings in 18 days — size accordingly

Summary: [3-sentence AI narrative]
```

### Daily Summary Alert
End-of-night summary: total screened, candidates reviewed, alerts generated, market regime note.

---

## MVP Build Order (Prioritised Backlog)

### Phase 1 — Core Engine (build first)
1. Database schema setup (PostgreSQL)
2. Borsdata API integration — Nordic OHLCV ingestion
3. US data ingestion via Borsdata global or supplementary provider
4. Universe manager with liquidity filters and exchange calendars
5. Technical indicator computation (pandas-ta)
6. Hard filter screener — Minervini/Qullamaggie rules
7. Corporate actions handling (splits, dividends)

### Phase 2 — AI Layer
8. mplfinance chart generation for candidates
9. Claude Haiku 4.5 chart review via Batch API
10. Structured JSON output parsing and validation
11. Telegram alert delivery

### Phase 3 — Enrichment
12. Quiver Quantitative insider data integration (US)
13. Finansinspektionen / Oslo Børs insider scraping (Nordic)
14. Finnhub news integration + LLM theme tagging
15. Claude Sonnet synthesis narrative generation
16. Confluence scoring and final ranking

### Phase 4 — Secondary Signals
17. Google Trends (pytrends) integration
18. StockTwits mention velocity
19. Reddit monitoring (PRAW, focused subreddits)
20. Twitter/X selective monitoring

### Phase 5 — UI & Refinement
21. Simple web dashboard (Flask or FastAPI + minimal frontend)
22. Alert history and feedback tracking
23. Strategy parameter management interface
24. Conversational parameter refinement (chat UI → structured params)

---

## File Structure

```
trading-intelligence/
├── config/
│   ├── settings.py          # API keys, DB connection, thresholds
│   └── universe_config.py   # Exchange definitions, liquidity thresholds
├── data/
│   ├── ingestor.py          # Borsdata API client, nightly EOD pull
│   ├── universe.py          # Universe management, liquidity filtering
│   └── corporate_actions.py # Splits, dividends handling
├── screening/
│   ├── indicators.py        # pandas-ta indicator computation
│   ├── filters.py           # Hard filter rules (Minervini criteria)
│   ├── base_detection.py    # Base identification logic
│   └── relative_strength.py # RS rank computation across universe
├── enrichment/
│   ├── insider.py           # Quiver Quant + Nordic insider scraping
│   ├── news.py              # Finnhub news ingestion
│   ├── trends.py            # Google Trends via pytrends
│   └── social.py            # StockTwits, Reddit, Twitter/X
├── ai/
│   ├── chart_generator.py   # mplfinance chart image creation
│   ├── chart_reviewer.py    # Claude Haiku vision assessment
│   ├── synthesiser.py       # Claude Sonnet narrative + scoring
│   └── prompts.py           # All prompt templates
├── scoring/
│   └── confluence.py        # Weighted scoring, final ranking
├── alerts/
│   ├── telegram_bot.py      # Telegram delivery
│   └── email_sender.py      # Email delivery
├── database/
│   ├── models.py            # SQLAlchemy models
│   └── migrations/          # Alembic migrations
├── scheduler/
│   └── nightly_job.py       # APScheduler pipeline orchestration
├── dashboard/               # Phase 5 — simple Flask UI
├── tests/
└── requirements.txt
```

---

## Environment Variables Required

```
# Borsdata
BORSDATA_API_KEY=

# Anthropic
ANTHROPIC_API_KEY=

# Finnhub
FINNHUB_API_KEY=

# Quiver Quantitative
QUIVER_API_KEY=

# Twitter/X
X_API_KEY=
X_API_SECRET=

# Reddit (PRAW)
REDDIT_CLIENT_ID=
REDDIT_CLIENT_SECRET=
REDDIT_USER_AGENT=

# Telegram
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=

# Database
DATABASE_URL=postgresql://user:password@localhost:5432/trading_intel

# Email
SMTP_HOST=
SMTP_USER=
SMTP_PASSWORD=
ALERT_EMAIL=
```

---

## Cost Summary (Personal Use, Monthly)

| Component | Monthly (USD) |
|---|---|
| Borsdata Pro+ | ~$60 |
| Finnhub (paid tier) | ~$40 |
| Quiver Quantitative | ~$25 |
| Twitter/X API (pay-per-use) | ~$15 |
| Claude API (Haiku + Sonnet, Batch) | ~$15 |
| Cloud VM + PostgreSQL | ~$20 |
| Google Trends / Reddit / StockTwits | $0 |
| **Total** | **~$175/month** |

---

## Key Constraints & Decisions

- **No browser automation** — all data via direct APIs only
- **No intraday data in v1** — EOD only, reduces cost and complexity significantly
- **TradingView retained** for live intraday monitoring during execution
- **Batch API mandatory** for all nightly Claude calls — 50% cost reduction
- **Prompt caching** for system prompts used repeatedly across chart assessments
- **Personal use licensing** — do not exceed Borsdata/Finnhub/Quiver personal plan terms
- **Commercial expansion** requires renegotiating data licenses before charging users
- **Nordic insider data** requires direct scraping of Finansinspektionen (Sweden) and Oslo Børs insider register (Norway) — no clean API exists

---

## Notes for Future Commercial Expansion

- Borsdata Enterprise tier required for commercial/professional use
- Data licensing for all providers must be renegotiated
- MiFID II compliance review recommended before charging EU users
- Standard "not financial advice" disclaimer required throughout UI
- Multi-user architecture: each user needs isolated strategy_params and alert preferences
- Conversational refinement UI: store intent as structured parameters, not freeform prompts
- Template presets (Minervini, Qullamaggie, CANSLIM) recommended for onboarding
