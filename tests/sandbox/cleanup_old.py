"""Inside Windows Sandbox: remove what earlier versions of the sandbox test put in the
person's own bookings.yaml (a test login and test bookings). Run with the app's venv Python."""
from wacbooker import config

TEST_LOGINS = ("sandbox", "test-no-password")
TEST_BOOKINGS = ("Sandbox check", "Sandbox dry run")

doc, _ = config.load()
logins = list(doc.get("logins") or [])
books = list(doc.get("bookings") or [])
keep_logins = [x for x in logins if x.get("nickname") not in TEST_LOGINS]
keep_books = [x for x in books if x.get("name") not in TEST_BOOKINGS and x.get("login") not in TEST_LOGINS]
if len(keep_logins) != len(logins) or len(keep_books) != len(books):
    doc["logins"], doc["bookings"] = keep_logins, keep_books
    config.save(doc)
    print("removed old test entries")
