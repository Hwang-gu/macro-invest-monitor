from __future__ import annotations

import json
import smtplib
import ssl
import time
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from pathlib import Path

from .config import BRIEF_HTML, REPORTS_DIR, ROOT, WORKBOOK_PATH, mail_settings

MAIL_SENT_PATH = REPORTS_DIR / "mail_sent.txt"
MAIL_STATUS_PATH = REPORTS_DIR / "mail_status.txt"


def _write_status(ok: bool, message: str) -> str:
    MAIL_STATUS_PATH.write_text(("OK\n" if ok else "FAIL\n") + message, encoding="utf-8")
    return message


def _already_sent(asof: str) -> bool:
    if not asof or not MAIL_SENT_PATH.exists():
        return False
    return MAIL_SENT_PATH.read_text(encoding="utf-8").strip() == asof


def _mark_sent(asof: str) -> None:
    if asof:
        MAIL_SENT_PATH.write_text(asof + "\n", encoding="utf-8")


def _newsletter_recipients() -> list[str]:
    path = ROOT / "data" / "ted_newsletters.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, dict):
        return []
    addrs: list[str] = []
    for key, row in data.items():
        email = str(key or "").strip().lower()
        if not email or "@" not in email:
            continue
        if isinstance(row, dict) and row.get("active") is False:
            continue
        if email not in addrs:
            addrs.append(email)
    return addrs


def _recipients(cfg: dict[str, str]) -> list[str]:
    addrs: list[str] = []
    for raw in (cfg.get("mail_to") or "").split(","):
        addr = raw.strip()
        if addr and addr not in addrs:
            addrs.append(addr)
    for email in _newsletter_recipients():
        if email not in addrs:
            addrs.append(email)
    return addrs


def _connect(cfg: dict[str, str]) -> smtplib.SMTP:
    port = int(cfg["port"] or "587")
    host = cfg["host"]
    context = ssl.create_default_context()
    if port == 465:
        smtp = smtplib.SMTP_SSL(host, port, timeout=60, context=context)
    else:
        smtp = smtplib.SMTP(host, port, timeout=60)
        smtp.ehlo()
        smtp.starttls(context=context)
        smtp.ehlo()
    if cfg["user"] and cfg["password"]:
        smtp.login(cfg["user"], cfg["password"])
    return smtp


def send_brief_if_configured(report: dict, html_path: Path | None = None, xlsx_path: Path | None = None) -> str:
    cfg = mail_settings()
    asof = str(report.get("asof") or "")
    if not cfg["host"] or not cfg["user"] or not cfg["password"]:
        return _write_status(
            False,
            "메일 설정이 없어 발송하지 못했습니다. GitHub Secrets 또는 .env 에 "
            "SMTP_HOST / SMTP_USER / SMTP_PASSWORD 를 넣으세요. 수신자는 뉴스레터 신청자입니다.",
        )
    if _already_sent(asof):
        return _write_status(True, f"이미 {asof} 브리핑 메일을 보냈습니다.")

    html_path = html_path or BRIEF_HTML
    xlsx_path = xlsx_path or WORKBOOK_PATH
    pick = report.get("asset_label", "")
    market = report.get("market_label") or report.get("if_stocks_market_label") or "—"
    sector = report.get("sector_label") or report.get("if_stocks_sector_label") or "—"
    body = (report.get("commentary") or {}).get("display") or ""
    sender = cfg["mail_from"] or cfg["user"]
    recipients = _recipients(cfg)
    if not sender or not recipients:
        return _write_status(False, "발신 계정 또는 뉴스레터 신청자가 없어 메일을 보내지 않았습니다.")

    attachments: list[tuple[str, bytes]] = []
    for path in (html_path, xlsx_path):
        if path is None or not path.exists():
            continue
        attachments.append((path.name, path.read_bytes()))

    intro = (
        f"<p>기준일 {asof}. 1순위 <b>{pick}</b>."
        f" 주식이라면 {market} / {sector}.</p>"
        f"<pre style='white-space:pre-wrap;font-family:sans-serif'>{body}</pre>"
        "<p>엑셀 장부와 HTML 브리핑을 첨부했습니다. 연구용이며 투자 권유가 아닙니다.</p>"
        "<p>Ted Investment 뉴스레터 신청자에게 보내는 메일입니다.</p>"
    )

    def _message_for(to_addr: str) -> bytes:
        msg = MIMEMultipart()
        msg["Subject"] = f"[매크로 브리핑] {asof} · {pick}"
        msg["From"] = formataddr(("Ted Investment", sender))
        msg["To"] = to_addr
        msg.attach(MIMEText(intro, "html", "utf-8"))
        for name, blob in attachments:
            part = MIMEApplication(blob)
            part.add_header("Content-Disposition", "attachment", filename=name)
            msg.attach(part)
        return msg.as_bytes()

    sent_ok: list[str] = []
    errors: list[str] = []
    last: Exception | None = None
    for attempt in range(3):
        try:
            with _connect(cfg) as smtp:
                for to_addr in recipients:
                    if to_addr in sent_ok:
                        continue
                    smtp.sendmail(sender, [to_addr], _message_for(to_addr))
                    sent_ok.append(to_addr)
            last = None
            break
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(2 * (attempt + 1))
    if last is not None and len(sent_ok) < len(recipients):
        missing = [a for a in recipients if a not in sent_ok]
        print(f"::error::브리핑 메일 발송 실패 ({cfg['host']}:{cfg['port']} → {len(missing)}명 미발송)")
        errors.append(f"{type(last).__name__}: {last}")
        return _write_status(
            False,
            f"메일 발송 실패: {len(sent_ok)}/{len(recipients)}명 성공. {'; '.join(errors)}",
        )

    _mark_sent(asof)
    sent = f"메일을 뉴스레터 신청자 {len(sent_ok)}명에게 보냈습니다."
    print(sent)
    return _write_status(True, sent)


def send_brief_from_latest() -> str:
    path = REPORTS_DIR / "latest.json"
    if not path.exists():
        return _write_status(False, "latest.json 이 없어 메일을 보내지 않았습니다.")
    report = json.loads(path.read_text(encoding="utf-8"))
    return send_brief_if_configured(report)


def main() -> None:
    msg = send_brief_from_latest()
    print(msg)
    if msg.startswith("메일 발송 실패") or "발송하지 못했습니다" in msg or "보내지 않았습니다" in msg:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
