"""Public pages: Homepage CTAs, sidebar visibility, Speaker Portal sections, audience feedback link, Help."""
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from utils import public_events
from workflow import runtime

TEAM_PAGES = {"Workflow admin", "Admin Portal", "Navan Travel Portal"}


@pytest.fixture(autouse=True)
def clean():
    runtime.OVERRIDE.clear()
    public_events.OVERRIDE["events"] = pd.DataFrame([
        {"event_name": "Data Summit <script>x</script> [link](https://evil.example)", "event_city": "Lagos",
         "event_country": "Nigeria", "event_start": "2099-01-15", "event_end": "", "event_format": "In-person",
         "status": "Approved", "organizer_email": "private@org.example"},
        {"event_name": "Pending Meetup", "event_start": "2099-02-01", "status": "Pending"},
        {"event_name": "Old Conf", "event_start": "2001-02-01", "status": "Approved"},
    ])
    yield
    public_events.OVERRIDE.clear()
    runtime.OVERRIDE.clear()


def run(path, query=None, session=None):
    at = AppTest.from_file(path, default_timeout=30)
    if query:
        at.query_params.update(query)
    for k, v in (session or {}).items():
        at.session_state[k] = v
    at.run()
    assert not at.exception, at.exception
    return at


def links(at, where=None):
    return {p.proto.label: p.proto.page for p in (where or at).get("page_link")}


def text(at):
    return " ".join(m.value for m in at.markdown)


# ── Homepage ──────────────────────────────────────────────────────────────────────────────────────

def test_homepage_ctas_link_to_the_right_portals():
    at = run("streamlit_app.py")
    ls = links(at)
    assert ls["Go to the Speaker Portal"] == "Speaker_Portal"
    assert ls["Go to the Vendor Portal"] == "Vendor_Portal"
    assert "I'm a speaker" in text(at) and "I'm organizing an event" in text(at)


def test_homepage_highlights_only_upcoming_approved_events_escaped():
    at = run("streamlit_app.py")
    body = text(at)
    assert "Pending Meetup" not in body and "Old Conf" not in body and "private@org" not in body
    hit = next(m.value for m in at.markdown if "Data Summit" in m.value)
    assert "\\[link\\]" in hit and "](https" not in hit.replace("\\](", "")


def test_homepage_handles_sheet_outage():
    public_events.OVERRIDE.clear()
    public_events.OVERRIDE["events"] = None
    at = run("streamlit_app.py")
    assert any("New events are on the way" in i.value or "couldn't load" in i.value for i in at.info)


# ── Sidebar visibility ──────────────────────────────────────────────────────────────────────────

def test_public_sidebar_hides_program_team_pages():
    at = run("streamlit_app.py")
    side = links(at, at.sidebar)
    assert {"Homepage", "Speaker Portal", "Vendor Portal", "Help & instructions"} <= set(side)
    assert not TEAM_PAGES & set(side)
    assert side["Program team sign-in"] == "Admin"           # entry point to the password form


def test_password_unlock_shows_program_team_pages():
    at = run("streamlit_app.py", session={"_pw_unlocked": {"admin"}})
    side = links(at, at.sidebar)
    assert TEAM_PAGES <= set(side) and "Program team sign-in" not in side
    assert any(b.label == "Lock program team pages" for b in at.sidebar.button)


def test_program_team_url_still_gated():
    at = run("pages/3_Admin.py")                              # no password configured in tests
    assert any("locked" in e.value for e in at.error)
    assert not at.dataframe and not at.metric


# ── Speaker Portal ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("section", ["start", "speak", "resources", "travel", "after"])
def test_speaker_portal_renders_signed_out_in_every_section(section):
    at = run("pages/1_Speaker_Portal.py", query={"section": section})
    assert at.radio(key="spk_section").value == section
    assert not any("paused" in w.value.lower() for w in at.warning)      # one friendly card instead
    if section == "travel":
        assert not at.exception, at.exception                           # one sign-in box for all travel forms
        assert any("Expense reimbursement" in m.value for m in at.markdown)
        assert at.text_input(key="spk_email_input") is not None      # reimbursement needs sign-in
    if section == "after":
        assert at.text_input(key="qr_name") is not None                  # QR generator is public
        assert at.text_input(key="spk_email_input") is not None      # headcount needs sign-in
    if section == "speak":
        shown = at.dataframe[0].value
        assert list(shown["Event"].str.startswith("Data Summit")) == [True]   # approved + upcoming only


def test_speaker_portal_section_switch_updates_url():
    at = run("pages/1_Speaker_Portal.py")
    at.radio(key="spk_section").set_value("resources").run()
    assert at.query_params.get("section") in ("resources", ["resources"])
    assert any("Brand Kit" in t.label for t in at.tabs)


def test_feedback_qr_link_works_without_sign_in(monkeypatch):
    saved = []
    monkeypatch.setattr("utils.sheets.append_row", lambda tab, row: saved.append((tab, row)) or True)
    at = run("pages/1_Speaker_Portal.py", query={"speaker": "Ada <b>", "event": "Data Summit", "talk": "Streams 101"})
    hero = next(m.value for m in at.markdown if "Rate this Talk" in m.value)
    assert "&lt;b&gt;" in hero and "<b>" not in hero
    assert all(r.key != "spk_section" for r in at.radio)                 # rating form only, no portal nav
    assert not any(t.key and t.key == "spk_email_input" for t in at.text_input)   # no sign-in prompt
    at.button(key="fb_submit").click().run()
    assert not at.exception, at.exception
    assert any("Thank you" in s.value for s in at.success)


# ── Help ────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("topic", ["speakers", "organizers", "signin", "bulk", "travel", "contact"])
def test_help_page_renders_every_topic(topic):
    at = run("pages/7_Help.py", query={"topic": topic})
    assert at.radio(key="help_topic").value == topic
    assert at.header


def test_help_is_public_in_navigation():
    at = run("streamlit_app.py")
    assert links(at, at.sidebar)["Help & instructions"] == "help"


def test_speaker_email_entry_unlocks_forms_without_sending_a_code(monkeypatch):
    from utils import email_otp
    monkeypatch.setattr(email_otp, "request_code", lambda *a, **k: pytest.fail("no code should be sent"),
                        raising=False)
    at = run("pages/1_Speaker_Portal.py", query={"section": "travel"})
    at.text_input(key="spk_email_input").input("not-an-email")
    next(b for b in at.button if b.label == "Continue").click().run()
    assert any("valid email" in e.value for e in at.error)
    at.text_input(key="spk_email_input").input("Ada@Example.com")
    next(b for b in at.button if b.label == "Continue").click().run()
    assert not at.exception, at.exception
    assert at.session_state["spk_email"] == "ada@example.com"
    keys = [t.key for t in at.text_input]
    assert "exp_name" in keys and "spk_email_input" not in keys
