from __future__ import annotations

import os
import socket
import smtplib
import ssl
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from pathlib import Path

from .config import REPORTS_DIR, mail_settings
from .news_digest import build_html, kst_today, kst_today_ko, load_subscribers

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


def _send_mail_enabled() -> bool:
    return os.getenv("TED_SEND_MAIL", "").strip().lower() in {"1", "true", "yes", "on"}


def _mail_only() -> str:
    return os.getenv("TED_MAIL_ONLY", "").strip().lower()


def _is_test_send() -> bool:
    if _mail_only():
        return True
    return os.getenv("TED_MAIL_TEST", "").strip().lower() in {"1", "true", "yes", "on"}


def _ipv4_socket(host: str, port: int, timeout: int) -> socket.socket:
    last: Exception | None = None
    for info in socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM):
        family, socktype, proto, _canon, sockaddr = info
        sock = socket.socket(family, socktype, proto)
        sock.settimeout(timeout)
        try:
            sock.connect(sockaddr)
            return sock
        except OSError as exc:
            last = exc
            sock.close()
    raise last or OSError(f"{host}:{port} IPv4 연결 실패")


class _SMTP(smtplib.SMTP):
    def _get_socket(self, host: str, port: int, timeout: float):
        return _ipv4_socket(host, port, int(timeout or 60))


class _SMTP_SSL(smtplib.SMTP_SSL):
    def _get_socket(self, host: str, port: int, timeout: float):
        sock = _ipv4_socket(host, port, int(timeout or 60))
        context = self.context if getattr(self, "context", None) else ssl.create_default_context()
        return context.wrap_socket(sock, server_hostname=host)


def _connect(cfg: dict[str, str]) -> smtplib.SMTP:
    user = (cfg.get("user") or "").strip()
    host = (cfg.get("host") or "").strip()
    if user.lower().endswith("@gmail.com") or user.lower().endswith("@googlemail.com"):
        host = "smtp.gmail.com"
    elif user.lower().endswith("@naver.com"):
        host = "smtp.naver.com"
    port_raw = int(cfg.get("port") or "0")
    if user.lower().endswith("@gmail.com") or user.lower().endswith("@googlemail.com"):
        attempts: list[tuple[int, bool]] = [(587, False), (465, True)]
        if port_raw in {587, 465}:
            attempts.sort(key=lambda item: 0 if item[0] == port_raw else 1)
    elif port_raw == 465:
        attempts = [(465, True), (587, False)]
    else:
        attempts = [(port_raw or 587, False), (465, True)]

    last: Exception | None = None
    for port, use_ssl in attempts:
        smtp: smtplib.SMTP | None = None
        try:
            context = ssl.create_default_context()
            if use_ssl:
                smtp = _SMTP_SSL(host, port, timeout=60, context=context)
            else:
                smtp = _SMTP(host, port, timeout=60)
                smtp.ehlo()
                smtp.starttls(context=context)
                smtp.ehlo()
            if cfg["user"] and cfg["password"]:
                smtp.login(cfg["user"], cfg["password"])
            return smtp
        except Exception as exc:  # noqa: BLE001
            last = exc
            if smtp is not None:
                try:
                    smtp.close()
                except Exception:  # noqa: BLE001
                    pass
    assert last is not None
    raise last


def send_brief_if_configured(report: dict | None = None, html_path: Path | None = None, xlsx_path: Path | None = None) -> str:
    del report, html_path, xlsx_path
    cfg = mail_settings()
    asof = kst_today()
    asof_ko = kst_today_ko()
    if not cfg["host"] or not cfg["user"] or not cfg["password"]:
        return _write_status(
            False,
            "메일 설정이 없어 발송하지 못했습니다. GitHub Secrets 에 "
            "SMTP_HOST / SMTP_USER / SMTP_PASSWORD 를 넣으세요. 수신자는 뉴스레터 신청자입니다.",
        )
    if not _send_mail_enabled():
        return _write_status(True, "뉴스레터 발송을 건너뛰었습니다. 예약 발송이 아니거나 발송 허락이 없습니다.")
    test_send = _is_test_send()
    if not test_send and _already_sent(asof):
        return _write_status(True, f"이미 {asof} 뉴스레터를 보냈습니다.")

    sender = cfg["mail_from"] or cfg["user"]
    from_name = cfg.get("mail_from_name") or "Claudio Marchisio"
    subscribers = load_subscribers()
    only = _mail_only()
    if only:
        subscribers = [s for s in subscribers if s["email"] == only]
    if not sender or not subscribers:
        if only:
            return _write_status(False, f"{only} 뉴스레터 신청 내역이 없어 메일을 보내지 않았습니다.")
        return _write_status(False, "발신 계정 또는 뉴스레터 신청자가 없어 메일을 보내지 않았습니다.")

    payloads: list[tuple[str, bytes]] = []
    for sub in subscribers:
        msg = MIMEMultipart()
        msg["Subject"] = f"관심 키워드 핫 뉴스 · {asof_ko}"
        msg["From"] = formataddr((from_name, sender))
        msg["To"] = sub["email"]
        msg.attach(MIMEText(build_html(sub, asof_ko), "html", "utf-8"))
        payloads.append((sub["email"], msg.as_bytes()))

    sent_ok: list[str] = []
    errors: list[str] = []
    last: Exception | None = None
    for attempt in range(3):
        try:
            with _connect(cfg) as smtp:
                for to_addr, raw in payloads:
                    if to_addr in sent_ok:
                        continue
                    smtp.sendmail(sender, [to_addr], raw)
                    sent_ok.append(to_addr)
            last = None
            break
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(2 * (attempt + 1))
    if last is not None and len(sent_ok) < len(subscribers):
        missing = [s["email"] for s in subscribers if s["email"] not in sent_ok]
        print(f"::error::뉴스레터 발송 실패 ({cfg['host']}:{cfg['port']} → {len(missing)}명 미발송)")
        errors.append(f"{type(last).__name__}: {last}")
        return _write_status(
            False,
            f"메일 발송 실패: {len(sent_ok)}/{len(subscribers)}명 성공. {'; '.join(errors)}",
        )

    if not test_send:
        _mark_sent(asof)
    sent = f"키워드 뉴스 메일을 신청자 {len(sent_ok)}명에게 보냈습니다."
    if test_send:
        sent = f"테스트로 {', '.join(sent_ok)} 에게 키워드 뉴스 메일을 보냈습니다."
    print(sent)
    return _write_status(True, sent)


def send_brief_from_latest() -> str:
    return send_brief_if_configured()


def main() -> None:
    msg = send_brief_from_latest()
    print(msg)
    if msg.startswith("메일 발송 실패") or "발송하지 못했습니다" in msg or "보내지 않았습니다" in msg:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
