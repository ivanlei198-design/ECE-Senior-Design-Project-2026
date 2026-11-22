import os
import smtplib
from email.message import EmailMessage


def _cfg() -> dict:
    return {k: os.environ.get(f"SDP_{k}", "") for k in ("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "NOTIFY_TO")}


def email_enabled() -> bool:
    c = _cfg()
    return bool(c["SMTP_HOST"] and c["NOTIFY_TO"])


def email_target() -> str:
    return _cfg()["NOTIFY_TO"]


def send_email(subject: str, body: str):
    if not email_enabled():
        return False, "email not configured"
    c = _cfg()
    try:
        msg = EmailMessage()
        msg["Subject"], msg["From"], msg["To"] = subject, c["SMTP_USER"] or c["NOTIFY_TO"], c["NOTIFY_TO"]
        msg.set_content(body)
        port = int(c["SMTP_PORT"] or 587)
        if port == 465:
            server = smtplib.SMTP_SSL(c["SMTP_HOST"], port, timeout=15)
        else:
            server = smtplib.SMTP(c["SMTP_HOST"], port, timeout=15)
            server.ehlo()
            if server.has_extn("starttls"):
                server.starttls()
                server.ehlo()
        with server:
            if c["SMTP_USER"] and c["SMTP_PASSWORD"]:
                server.login(c["SMTP_USER"], c["SMTP_PASSWORD"])
            server.send_message(msg)
        return True, f"sent to {c['NOTIFY_TO']}"
    except Exception as e:
        return False, str(e)[:120]
