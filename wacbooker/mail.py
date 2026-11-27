"""Email summaries: one plain email per scheduled run, sent with the person's own mail
account (Gmail by default: an app password, kept in Windows Credential Manager under
its own name). The password is never written to bookings.yaml, a log or an email."""
from __future__ import annotations

import re
import smtplib
import ssl
from email.message import EmailMessage

import keyring

from . import APP_NAME

SERVICE = APP_NAME + " email"
DEFAULT_HOST, DEFAULT_PORT = "smtp.gmail.com", 465
# Member numbers (and any other long number) never go in an email.
_LONG_NUMBER = re.compile(r"\b\d{5,}\b")


def _key(address: str) -> str:
    return address.strip().lower()


def set_password(address: str, password: str) -> None:
    keyring.set_password(SERVICE, _key(address), password)


def has_password(address: str) -> bool:
    try:
        return bool(address) and bool(keyring.get_password(SERVICE, _key(address)))
    except Exception:  # noqa: BLE001 -- vault unreachable
        return False


def delete_password(address: str) -> None:
    try:
        keyring.delete_password(SERVICE, _key(address))
    except Exception:  # noqa: BLE001 -- nothing saved
        pass


def sender(cfg) -> str:
    """The account the email is sent from: email_from, or the address itself."""
    return (cfg.email_from or cfg.email_to or "").strip()


def configured(cfg) -> bool:
    return bool(cfg.email_to) and has_password(sender(cfg))


def compose(cfg, subject: str, summary: str, details=()) -> EmailMessage:
    body = summary.strip() + "\n"
    if details:
        body += "\n---- details for troubleshooting ----\n" + "\n".join(details) + "\n"
    msg = EmailMessage()
    msg["Subject"] = f"Tennis: {subject}"[:120]
    msg["From"] = sender(cfg)
    msg["To"] = cfg.email_to
    msg.set_content(_LONG_NUMBER.sub("#####", body))
    return msg


def send(cfg, subject: str, summary: str, details=(), smtp=smtplib.SMTP_SSL,
         starttls_smtp=smtplib.SMTP) -> tuple[bool, str]:
    """(sent?, what happened). Never raises; never includes the password.
    Port 465 is TLS from the first byte; any other port (587) connects in plain text
    and upgrades with STARTTLS before logging in."""
    if not cfg.email_to:
        return False, "no email address is set"
    who = sender(cfg)
    try:
        pw = keyring.get_password(SERVICE, _key(who))
    except Exception:  # noqa: BLE001
        return False, "Windows Credential Manager wasn't reachable"
    if not pw:
        return False, f"no saved email password for {who}"
    try:
        host, port = cfg.smtp_host or DEFAULT_HOST, int(cfg.smtp_port or DEFAULT_PORT)
        if port == 465:
            conn = smtp(host, port, context=ssl.create_default_context(), timeout=30)
        else:
            conn = starttls_smtp(host, port, timeout=30)
        with conn as s:
            if port != 465:
                s.starttls(context=ssl.create_default_context())
            s.login(who, pw)
            s.send_message(compose(cfg, subject, summary, details))
    except (smtplib.SMTPException, OSError) as e:
        return False, f"{type(e).__name__}: {str(e).replace(pw, '***')[:160]}"
    finally:
        pw = None
    return True, f"sent to {cfg.email_to}"
