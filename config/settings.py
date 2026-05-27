import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")


def _load_streamlit_secrets() -> None:
    """On Streamlit Cloud .env doesn't exist; pull top-level string secrets into os.environ."""
    try:
        import streamlit as st
        for key, val in st.secrets.items():
            if isinstance(val, str) and not os.environ.get(key):
                os.environ[key] = val
    except Exception:
        pass


_load_streamlit_secrets()


class Settings:
    # Database
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")

    # Borsdata
    BORSDATA_API_KEY: str = os.getenv("BORSDATA_API_KEY", "")
    BORSDATA_BASE_URL: str = "https://apiservice.borsdata.se/v1"

    # Anthropic
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")

    # Supabase REST + Storage
    SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
    SUPABASE_SERVICE_KEY: str = os.getenv("SUPABASE_SERVICE_KEY") or os.getenv("supabase_key", "")

    # Finnhub (Phase 3)
    FINNHUB_API_KEY: str = os.getenv("FINNHUB_API_KEY", "")

    # Quiver (Phase 3)
    QUIVER_API_KEY: str = os.getenv("QUIVER_API_KEY", "")

    # Telegram (Phase 2)
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")

    # Reddit (Phase 4)
    REDDIT_CLIENT_ID: str = os.getenv("REDDIT_CLIENT_ID", "")
    REDDIT_CLIENT_SECRET: str = os.getenv("REDDIT_CLIENT_SECRET", "")
    REDDIT_USER_AGENT: str = os.getenv("REDDIT_USER_AGENT", "trading-intelligence/1.0")

    # Email (Phase 2)
    SMTP_HOST: str = os.getenv("SMTP_HOST", "")
    SMTP_PORT: int = int(os.getenv("SMTP_PORT") or "587")
    SMTP_USER: str = os.getenv("SMTP_USER", "")
    SMTP_PASSWORD: str = os.getenv("SMTP_PASSWORD", "")
    ALERT_EMAIL: str = os.getenv("ALERT_EMAIL", "")

    # Pipeline
    CHART_OUTPUT_DIR: str = os.getenv("CHART_OUTPUT_DIR", "charts")
    OHLCV_HISTORY_DAYS: int = 400  # ~16 months, covers 200-day SMA + base lookback
    NIGHTLY_SCHEDULE_HOUR: int = 22  # 10pm local time

    def validate(self) -> list[str]:
        """Return list of missing required config keys."""
        missing = []
        if not self.DATABASE_URL:
            missing.append("DATABASE_URL")
        if not self.BORSDATA_API_KEY:
            missing.append("BORSDATA_API_KEY")
        return missing


settings = Settings()
