"""
Nightly signal digest email via Gmail SMTP.

Gmail setup (one-time):
  1. Enable 2-Step Verification on your Google account
  2. Google Account → Security → App passwords → "Mail" → generate
  3. Add to .env:
       SMTP_HOST=smtp.gmail.com
       SMTP_PORT=465
       SMTP_USER=stashorizor@gmail.com
       SMTP_PASSWORD=<16-char app password, no spaces>
       ALERT_EMAIL=stashorizor@gmail.com
"""
from __future__ import annotations

import logging
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)

BADGE_LABELS = {
    "vcp": "VCP", "qullamaggie": "Q", "ema_pullback": "EMA5",
    "gap_up": "BGU", "pocket_pivot": "PP",
}
BADGE_COLORS = {
    "vcp": "#388bfd", "qullamaggie": "#a371f7", "ema_pullback": "#e3b341",
    "gap_up": "#3fb950", "pocket_pivot": "#f0883e",
}


def _strats_html(strategies: list[str]) -> str:
    return "".join(
        f'<span style="background:{BADGE_COLORS.get(s,"#555")};color:#000;border-radius:3px;'
        f'padding:1px 6px;font-size:11px;font-weight:700;margin-right:3px">'
        f'{BADGE_LABELS.get(s, s[:3].upper())}</span>'
        for s in strategies
    )


def _score_color(score: float) -> str:
    return "#3fb950" if score >= 75 else ("#e3b341" if score >= 60 else "#f85149")


def build_email_html(signals: list[dict], run_date: str) -> str:
    top20 = signals[:20]

    rows = ""
    for i, sig in enumerate(top20, 1):
        score  = sig.get("composite_score", 0)
        rs     = sig.get("rs_rank")
        entry  = sig.get("entry_price")
        stop   = sig.get("stop_price")
        rr     = sig.get("risk_reward")
        theme  = sig.get("theme_name") or ""
        strats = sig.get("strategies_fired") or []

        rows += (
            f'<tr style="border-top:1px solid #21262d">'
            f'<td style="padding:7px 10px;color:#7d8590;font-size:12px">#{i}</td>'
            f'<td style="padding:7px 10px;font-weight:700;color:#e6edf3;white-space:nowrap">{sig["symbol"]}</td>'
            f'<td style="padding:7px 10px;color:#484f58;font-size:11px">{sig.get("exchange","")}</td>'
            f'<td style="padding:7px 10px;font-weight:700;font-size:15px;color:{_score_color(score)}">{score:.0f}</td>'
            f'<td style="padding:7px 10px;color:#8b949e;font-size:12px">{f"{rs:.0f}th" if rs else "—"}</td>'
            f'<td style="padding:7px 10px">{_strats_html(strats)}</td>'
            f'<td style="padding:7px 10px;color:#7d8590;font-size:11px;max-width:140px">{theme}</td>'
            f'<td style="padding:7px 10px;color:#8b949e;font-size:12px;white-space:nowrap">{f"{entry:.2f}" if entry else "—"}</td>'
            f'<td style="padding:7px 10px;color:#f85149;font-size:12px;white-space:nowrap">{f"{stop:.2f}" if stop else "—"}</td>'
            f'<td style="padding:7px 10px;color:#7d8590;font-size:12px">{f"{rr:.1f}×" if rr else "—"}</td>'
            f'</tr>'
        )

    extra_html = ""
    if len(signals) > 20:
        rest = signals[20:]
        rest_text = "  ·  ".join(
            f'<span style="color:#e6edf3;font-weight:600">{s["symbol"]}</span>'
            f' <span style="color:{_score_color(s.get("composite_score",0))}">'
            f'{s.get("composite_score",0):.0f}</span>'
            for s in rest
        )
        extra_html = (
            f'<p style="color:#7d8590;font-size:12px;margin-top:16px;line-height:2">'
            f'<strong style="color:#8b949e">+{len(rest)} more:</strong>&nbsp;&nbsp;{rest_text}</p>'
        )

    return f"""<!DOCTYPE html>
<html>
<head><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="background:#0d1117;color:#e6edf3;font-family:-apple-system,BlinkMacSystemFont,Helvetica,sans-serif;margin:0;padding:20px">
<div style="max-width:700px;margin:0 auto">

  <h2 style="color:#e6edf3;margin-bottom:2px;font-size:20px">&#128200; AI Stock Screener</h2>
  <p style="color:#7d8590;margin-top:4px;margin-bottom:18px;font-size:13px">
    {run_date}&nbsp;&nbsp;&#183;&nbsp;&nbsp;<strong style="color:#e6edf3">{len(signals)}</strong> signals found
  </p>

  <table style="width:100%;border-collapse:collapse;background:#161b22;border-radius:8px;border:1px solid #21262d">
    <thead>
      <tr style="background:#21262d">
        <th style="padding:8px 10px;text-align:left;color:#7d8590;font-size:10px;font-weight:600;text-transform:uppercase">#</th>
        <th style="padding:8px 10px;text-align:left;color:#7d8590;font-size:10px;font-weight:600;text-transform:uppercase">Symbol</th>
        <th style="padding:8px 10px;text-align:left;color:#7d8590;font-size:10px;font-weight:600;text-transform:uppercase">Exch</th>
        <th style="padding:8px 10px;text-align:left;color:#7d8590;font-size:10px;font-weight:600;text-transform:uppercase">Score</th>
        <th style="padding:8px 10px;text-align:left;color:#7d8590;font-size:10px;font-weight:600;text-transform:uppercase">RS</th>
        <th style="padding:8px 10px;text-align:left;color:#7d8590;font-size:10px;font-weight:600;text-transform:uppercase">Strategy</th>
        <th style="padding:8px 10px;text-align:left;color:#7d8590;font-size:10px;font-weight:600;text-transform:uppercase">Theme</th>
        <th style="padding:8px 10px;text-align:left;color:#7d8590;font-size:10px;font-weight:600;text-transform:uppercase">Entry</th>
        <th style="padding:8px 10px;text-align:left;color:#7d8590;font-size:10px;font-weight:600;text-transform:uppercase">Stop</th>
        <th style="padding:8px 10px;text-align:left;color:#7d8590;font-size:10px;font-weight:600;text-transform:uppercase">R:R</th>
      </tr>
    </thead>
    <tbody>{rows}</tbody>
  </table>

  {extra_html}

  <p style="color:#30363d;font-size:10px;margin-top:24px">AI Stock Screener &#183; Nordic markets &#183; {run_date}</p>
</div>
</body>
</html>"""


def send_nightly_email(signals: list[dict], run_date: str) -> bool:
    """Send signal digest. Returns True on success, False if unconfigured or failed."""
    from config.settings import settings

    host = settings.SMTP_HOST
    port = settings.SMTP_PORT
    user = settings.SMTP_USER
    pw   = settings.SMTP_PASSWORD
    to   = settings.ALERT_EMAIL

    if not all([host, user, pw, to]):
        logger.info("Email skipped — SMTP not fully configured in .env")
        return False

    top_sym = signals[0]["symbol"] if signals else "—"
    subject = f"\U0001f4c8 Screener {run_date}  ·  {len(signals)} signals  ·  #{1} {top_sym}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = user
    msg["To"]      = to
    msg.attach(MIMEText(build_email_html(signals, run_date), "html"))

    try:
        ctx = ssl.create_default_context()
        if port == 465:
            with smtplib.SMTP_SSL(host, port, context=ctx) as srv:
                srv.login(user, pw)
                srv.sendmail(user, to, msg.as_string())
        else:
            with smtplib.SMTP(host, port) as srv:
                srv.ehlo()
                srv.starttls(context=ctx)
                srv.login(user, pw)
                srv.sendmail(user, to, msg.as_string())
        logger.info("Email digest sent to %s (%d signals)", to, len(signals))
        return True
    except Exception as exc:
        logger.warning("Email send failed: %s", exc)
        return False
