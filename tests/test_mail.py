"""Email summaries: one plain email per scheduled run, sent with the person's own mail
account. The password lives in Windows Credential Manager, never in bookings.yaml."""
from wacbooker import config, mail


class FakeVault:
    def __init__(self):
        self.d = {}

    def set_password(self, svc, user, pw):
        self.d[(svc, user)] = pw

    def get_password(self, svc, user):
        return self.d.get((svc, user))

    def delete_password(self, svc, user):
        self.d.pop((svc, user), None)


class FakeSMTP:
    sent = []
    logins = []
    fail = None

    def __init__(self, host, port, context=None, timeout=None):
        self.host, self.port = host, port

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def login(self, user, pw):
        if FakeSMTP.fail:
            raise FakeSMTP.fail
        FakeSMTP.logins.append((self.host, self.port, user, pw))

    def send_message(self, msg):
        FakeSMTP.sent.append(msg)


def setup(monkeypatch):
    v = FakeVault()
    monkeypatch.setattr(mail, "keyring", v)
    FakeSMTP.sent, FakeSMTP.logins, FakeSMTP.fail = [], [], None
    return v


def cfg(**kw):
    c = config.Config()
    for k, v in kw.items():
        setattr(c, k, v)
    return c


def test_config_reads_the_email_settings():
    doc = {"email_to": "me@example.com", "email_from": "sender@example.com",
           "smtp_host": "smtp.example.com", "smtp_port": 587}
    c = config.from_doc(doc)
    assert c.ok, c.errors
    assert (c.email_to, c.email_from, c.smtp_host, c.smtp_port) == \
        ("me@example.com", "sender@example.com", "smtp.example.com", 587)
    d = config.from_doc({})
    assert (d.email_to, d.email_from, d.smtp_host, d.smtp_port) == ("", "", "smtp.gmail.com", 465)
    assert not config.from_doc({"email_to": "not an address"}).ok


def test_template_documents_email():
    assert "email_to:" in config.TEMPLATE


def test_password_goes_to_the_vault_not_the_config(monkeypatch):
    v = setup(monkeypatch)
    mail.set_password("Me@Example.com", "app-password-123")
    assert v.d == {(mail.SERVICE, "me@example.com"): "app-password-123"}
    assert mail.has_password("me@example.com")
    mail.delete_password("me@example.com")
    assert not mail.has_password("me@example.com")


def test_send_uses_the_sender_account_over_ssl(monkeypatch):
    setup(monkeypatch)
    mail.set_password("me@example.com", "app-password-123")
    ok, why = mail.send(cfg(email_to="me@example.com"), "Booked", "Booked: Ct 5, Fri 12/18 6:00 PM, 60 min",
                        ["W+44.9s press -> CONFIRMED"], smtp=FakeSMTP)
    assert ok, why
    assert FakeSMTP.logins == [("smtp.gmail.com", 465, "me@example.com", "app-password-123")]
    m = FakeSMTP.sent[0]
    assert m["To"] == "me@example.com" and m["From"] == "me@example.com"
    assert m["Subject"] == "Tennis: Booked"
    body = m.get_content()
    assert body.startswith("Booked: Ct 5")
    assert "details for troubleshooting" in body and "W+44.9s" in body
    assert "app-password-123" not in body and "app-password-123" not in why


def test_send_keeps_member_numbers_out(monkeypatch):
    setup(monkeypatch)
    mail.set_password("me@example.com", "app-password-123")
    mail.send(cfg(email_to="me@example.com"), "Booked", "Member 1234567 booked Ct 5 at 6:00 PM on 12/18/2026",
              smtp=FakeSMTP)
    body = FakeSMTP.sent[0].get_content()
    assert "1234567" not in body and "6:00 PM" in body and "12/18/2026" in body


def test_send_without_setup_says_why(monkeypatch):
    setup(monkeypatch)
    ok, why = mail.send(cfg(), "Booked", "x", smtp=FakeSMTP)
    assert not ok and "address" in why
    ok, why = mail.send(cfg(email_to="me@example.com"), "Booked", "x", smtp=FakeSMTP)
    assert not ok and "password" in why
    assert FakeSMTP.sent == []
    assert not mail.configured(cfg(email_to="me@example.com"))


def test_send_failure_is_reported_not_raised(monkeypatch):
    import smtplib
    setup(monkeypatch)
    mail.set_password("me@example.com", "app-password-123")
    FakeSMTP.fail = smtplib.SMTPAuthenticationError(535, b"Username and Password not accepted")
    ok, why = mail.send(cfg(email_to="me@example.com"), "Booked", "x", smtp=FakeSMTP)
    assert not ok and "SMTPAuthenticationError" in why and "app-password-123" not in why


def test_sender_defaults_to_the_address():
    assert mail.sender(cfg(email_to="me@example.com")) == "me@example.com"
    assert mail.sender(cfg(email_to="me@example.com", email_from="s@example.com")) == "s@example.com"
