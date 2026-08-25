from __future__ import annotations

import smtplib
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from .config import BRIEF_HTML, WORKBOOK_PATH, mail_settings


def send_brief_if_configured(report: dict, html_path: Path | None = None, xlsx_path: Path | None = None) -> str:
    cfg = mail_settings()
    if not cfg["host"] or not cfg["mail_to"]:
        return "메일 설정이 없어 파일만 저장했습니다. .env 의 SMTP_* / MAIL_TO 를 채우면 발송됩니다."

    html_path = html_path or BRIEF_HTML
    xlsx_path = xlsx_path or WORKBOOK_PATH
    asof = report.get("asof", "")
    pick = report.get("asset_label", "")
    market = report.get("market_label") or report.get("if_stocks_market_label") or "—"
    sector = report.get("sector_label") or report.get("if_stocks_sector_label") or "—"
    body = (report.get("commentary") or {}).get("display") or ""
    sender = cfg["mail_from"] or cfg["user"]
    if not sender:
        return "MAIL_FROM 또는 SMTP_USER 가 없어 메일을 보내지 않았습니다."

    msg = MIMEMultipart()
    msg["Subject"] = f"[매크로 브리핑] {asof} · {pick}"
    msg["From"] = sender
    msg["To"] = cfg["mail_to"]
    intro = (
        f"<p>기준일 {asof}. 1순위 <b>{pick}</b>."
        f" 주식이라면 {market} / {sector}.</p>"
        f"<pre style='white-space:pre-wrap;font-family:sans-serif'>{body}</pre>"
        "<p>엑셀 장부와 HTML 브리핑을 첨부했습니다. 연구용이며 투자 권유가 아닙니다.</p>"
    )
    msg.attach(MIMEText(intro, "html", "utf-8"))
    for path in (html_path, xlsx_path):
        if path is None or not path.exists():
            continue
        part = MIMEApplication(path.read_bytes())
        part.add_header("Content-Disposition", "attachment", filename=path.name)
        msg.attach(part)

    port = int(cfg["port"] or "587")
    with smtplib.SMTP(cfg["host"], port, timeout=30) as smtp:
        smtp.starttls()
        if cfg["user"] and cfg["password"]:
            smtp.login(cfg["user"], cfg["password"])
        smtp.sendmail(sender, [addr.strip() for addr in cfg["mail_to"].split(",")], msg.as_bytes())
    return f"메일을 {cfg['mail_to']} 로 보냈습니다."
