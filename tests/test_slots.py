"""Speaker slots: CFP vs slot split, claim once, waitlist, accept/decline emails, slot status, program sheet sync.

Nothing reaches Google: Events is a MemoryEvents, Slot_Claims a MemorySheets, the program sheet a MemoryProgram, and
Gmail is the fake HTTP layer from test_conference so To/Cc headers are checked as sent.
"""
from datetime import date

import pandas as pd
import pytest

from test_conference import FakeGmail
from utils import ops_store as ops
from utils import public_events as pe
from utils import sheets
from utils import slots as sl
from utils.gmail_diag import GmailClient

TODAY = date(2026, 11, 21)
ABA = sl.ADMIN_EMAIL


def ev_row(eid, name, start, city, kind, slot="", deadline="", org="AI Camp", status="Approved"):
    d = dict.fromkeys(sl.EVENT_COLS, "")
    d.update({"event_id": eid, "status": status, "organizer_org": org, "event_name": name, "event_start": start,
              "event_end": start, "event_city": city, "event_country": "United States", "opportunity_type": kind,
              "slot_status": slot, "cfp_deadline": deadline})
    return d


@pytest.fixture
def env(monkeypatch):
    rows = [ev_row("AUS", "AI Camp Austin", "2026-12-02", "Austin", pe.SPEAKER_SLOT, pe.OPEN),
            ev_row("NYC", "AI Camp New York", "2026-12-09", "New York", pe.SPEAKER_SLOT, pe.OPEN),
            ev_row("OLD", "AI Camp Dallas", "2026-11-18", "Dallas", pe.SPEAKER_SLOT, pe.CANCELED),
            ev_row("FULL", "AI Camp Miami", "2026-12-08", "Miami", pe.SPEAKER_SLOT, pe.FILLED),
            ev_row("ZRH", "DevOps Days Zurich", "2027-04-14", "Zurich", pe.CFP, deadline="2026-12-31", org=""),
            ev_row("LON", "Tech Show London", "2027-03-10", "London", pe.CFP, deadline="Rolling", org=""),
            ev_row("FOS", "FOSDEM", "2027-01-30", "Brussels", pe.CFP, deadline="2026-11-16", org=""),
            ev_row("VND", "Vendor meetup", "2027-01-05", "Berlin", "", org="")]
    events = sl.MemoryEvents(pd.DataFrame(rows, columns=sl.EVENT_COLS))
    sl.OVERRIDE["events"] = events
    pe.OVERRIDE["events"] = events.df                      # same frame: status changes show in the portal lists
    program = sl.MemoryProgram({
        "Speakers": pd.DataFrame([["SPK-001", "Keith Belanger", "keith@x.com"]], columns=["Speaker ID", "Full Name", "Email"]),
        "Event List": pd.DataFrame([["EVT-001", "AI Camp Austin", "AI Camp", "2026-12-02", "", "Austin"]],
                                   columns=["Event ID", "Event Name", "Partner", "Date", "Day", "City"]),
        "Speaker-Events": pd.DataFrame([["SE-007", "SPK-001", "EVT-001"]], columns=["SE ID", "Speaker ID", "Event ID"])})
    sl.OVERRIDE["program"] = program
    ops.OVERRIDE["sheets"] = ops.MemorySheets({})
    gm = FakeGmail()
    creds = {"GOOGLE_CLIENT_ID": "c", "GOOGLE_CLIENT_SECRET": "s", "GOOGLE_REFRESH_TOKEN": "r"}
    monkeypatch.setattr(sheets, "_gmail_client", GmailClient(lambda: creds, gm.post, gm.get))
    monkeypatch.setattr(sheets, "_gmail_token", lambda: "tok")
    yield events, program, gm
    sl.OVERRIDE.clear()
    pe.OVERRIDE.clear()
    ops.OVERRIDE.clear()


def status(events, eid):
    return events.df.loc[events.df["event_id"] == eid, "slot_status"].iloc[0]


# ── Two lists ────────────────────────────────────────────────────────────────────────────────────────────────────

def test_slots_and_cfps_are_separate_and_hide_past_items(env):
    slots = pe.speaker_slots(today=TODAY)
    assert list(slots["event_id"]) == ["AUS", "NYC"]          # filled, canceled and past slots hidden
    cfps = pe.cfp_invitations(today=TODAY)
    assert set(cfps["event_id"]) == {"ZRH", "LON", "VND"}     # closed FOSDEM CFP hidden; untyped counts as CFP


# ── Claim ───────────────────────────────────────────────────────────────────────────────────────────────────────

def test_claim_records_once_moves_slot_to_review_and_emails_only_aba(env):
    events, _, gm = env
    ok, msg = sl.claim("AUS", "Mandeep Singh", "Mandeep@x.com", "Agents in practice", "Short abstract", ["Hotel"])
    assert ok and "2 business days" in msg
    assert status(events, "AUS") == pe.PENDING_REVIEW
    assert [m["to"] for m in gm.sent] == [ABA]
    assert "Agents in practice" in gm.sent[0]["body"] and "Hotel" in gm.sent[0]["body"]
    ok, msg = sl.claim("AUS", "Mandeep Singh", "mandeep@x.com", "Agents in practice", "", [])
    assert ok and "already claimed" in msg
    assert len(sl.claims()) == 1 and len(gm.sent) == 1


def test_second_claim_joins_waitlist(env):
    events, _, gm = env
    sl.claim("AUS", "Mandeep Singh", "mandeep@x.com", "Talk A", "", [])
    ok, msg = sl.claim("AUS", "Joyce Avila", "joyce@x.com", "Talk B", "", [])
    assert ok and "waitlist" in msg
    assert {c["email"]: c["status"] for c in sl.claims()} == {"mandeep@x.com": sl.PENDING, "joyce@x.com": sl.WAITLIST}
    assert "waitlist" in gm.sent[-1]["body"].lower()


def test_filled_slot_and_bad_input_are_refused(env):
    assert sl.claim("FULL", "A B", "a@x.com", "T", "", [])[0] is False
    assert sl.claim("AUS", "", "a@x.com", "T", "", [])[0] is False
    assert sl.claim("AUS", "A B", "not-an-email", "T", "", [])[0] is False
    assert sl.claims() == []


# ── Accept / decline ────────────────────────────────────────────────────────────────────────────────────────────

def test_accept_fills_slot_emails_speaker_cc_aba_and_syncs_program(env):
    events, program, gm = env
    sl.claim("AUS", "Keith Belanger", "keith@x.com", "Stop Prompting", "", ["Flight"])
    k = sl.key_of("AUS", "keith@x.com")
    ok, msg = sl.decide(k, sl.ACCEPTED, ABA, "See you there")
    assert ok, msg
    assert status(events, "AUS") == pe.FILLED
    m = gm.to("keith@x.com")[-1]
    assert ABA in m["cc"] and m["subject"].startswith("You're confirmed: AI Camp Austin")
    assert "conference support form" in m["body"] and "See you there" in m["body"] and "Nov 18" in m["body"]
    se = program.tabs["Speaker-Events"]
    assert list(se.iloc[-1][:3]) == ["SE-008", "SPK-001", "EVT-001"]     # existing speaker + event reused
    assert len(program.tabs["Speakers"]) == 1 and len(program.tabs["Event List"]) == 1
    assert sl.decide(k, sl.ACCEPTED, ABA)[0] is False                    # never re-sent
    assert len(gm.to("keith@x.com")) == 1


def test_accept_new_speaker_and_event_adds_program_rows(env):
    _, program, _ = env
    sl.claim("NYC", "Veronika Durgin", "veronika@x.com", "Data modeling", "", [])
    sl.decide(sl.key_of("NYC", "veronika@x.com"), sl.ACCEPTED, ABA)
    assert program.tabs["Speakers"].iloc[-1]["Speaker ID"] == "SPK-002"
    assert program.tabs["Event List"].iloc[-1]["Event ID"] == "EVT-002"


def test_decline_promotes_waitlist_then_reopens_slot(env):
    events, _, gm = env
    sl.claim("AUS", "Mandeep Singh", "mandeep@x.com", "Talk A", "", [])
    sl.claim("AUS", "Joyce Avila", "joyce@x.com", "Talk B", "", [])
    ok, msg = sl.decide(sl.key_of("AUS", "mandeep@x.com"), sl.DECLINED, ABA)
    assert ok and "Joyce Avila" in msg
    assert status(events, "AUS") == pe.PENDING_REVIEW
    assert "other open slots" in gm.to("mandeep@x.com")[-1]["body"]
    sl.decide(sl.key_of("AUS", "joyce@x.com"), sl.DECLINED, ABA)
    assert status(events, "AUS") == pe.OPEN


def test_declining_waitlist_never_reopens_a_filled_slot(env):
    events, _, _ = env
    sl.claim("AUS", "Mandeep Singh", "mandeep@x.com", "Talk A", "", [])
    sl.claim("AUS", "Joyce Avila", "joyce@x.com", "Talk B", "", [])
    sl.decide(sl.key_of("AUS", "mandeep@x.com"), sl.ACCEPTED, ABA)
    sl.decide(sl.key_of("AUS", "joyce@x.com"), sl.DECLINED, ABA)
    assert status(events, "AUS") == pe.FILLED


# ── Admin: add a slot ───────────────────────────────────────────────────────────────────────────────────────────

def test_add_slot_lists_it_as_open(env):
    ok, _ = sl.add_slot("AI Camp", "AI Camp Seattle", date(2027, 1, 12), "Seattle", "United States")
    assert ok
    assert "AI Camp Seattle" in set(pe.speaker_slots(today=TODAY)["event_name"])
    assert sl.add_slot("AI Camp", "", None, "", "")[0] is False


# ── Speaker Portal page ─────────────────────────────────────────────────────────────────────────────────────────

def test_portal_shows_two_lists_and_claim_form_submits(env):
    from streamlit.testing.v1 import AppTest
    events, _, gm = env
    at = AppTest.from_file("pages/1_Speaker_Portal.py", default_timeout=30)
    at.query_params["section"] = "speak"
    at.run()
    assert not at.exception, at.exception
    heads = " ".join(m.value for m in at.markdown)
    assert "Open speaker slots" in heads and "CFP invitations" in heads
    assert "AI Camp Austin" in heads and "AI Camp Miami" not in heads          # filled slot not listed
    assert set(at.dataframe[0].value["Event"]) >= {"DevOps Days Zurich", "Tech Show London"}
    at.button(key="slot_btn_AUS").click().run()
    form = [t for t in at.text_input if t.label in ("Your name", "Your email", "Talk title")]
    for t, v in zip(form, ["Gilberto Hernandez", "gilberto@x.com", "From Iceberg to Intelligence"]):
        t.input(v)
    next(b for b in at.button if b.proto.form_id == "slot_form_AUS").click().run()
    assert not at.exception, at.exception
    assert any("2 business days" in s.value for s in at.success)
    assert status(events, "AUS") == pe.PENDING_REVIEW and gm.sent[-1]["to"] == ABA
