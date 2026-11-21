"""Speaker self-reports and the program sheet roll-up.

Hub tabs are a MemorySheets, the program sheet a MemoryProgram; nothing reaches Google.
"""
import pandas as pd
import pytest

from utils import activity as act
from utils import ops_store as ops
from utils import rollup
from utils import slots as sl

ME = "Joyce@Example.com"
SE_COLS = ["SE ID", "Speaker ID", "Event ID", "Speaker", "Event", "Partner", "Date", "City", "Region", "Fiscal Qtr",
           "Community", "Stage", "Confirmed", "Welcome Email", "Talk Title", "Format", "AI / CoCo Topic",
           "Content Reused", "Content Link", "Registered", "Attended"]          # real program-sheet order


@pytest.fixture
def env():
    program = sl.MemoryProgram({
        "Speakers": pd.DataFrame([["SPK-001", "Joyce Avila", "joyce@example.com"]],
                                 columns=["Speaker ID", "Full Name", "Email"]),
        "Event List": pd.DataFrame([["EVT-001", "ODSC AI New York", "ODSC", "2026-12-03", "", "New York"]],
                                   columns=["Event ID", "Event Name", "Partner", "Date", "Day", "City"]),
        "Speaker-Events": pd.DataFrame([["SE-001", "SPK-001", "EVT-001", "Joyce Avila", "ODSC AI New York", "ODSC",
                                         "2026-12-03", "New York", "US East", "Q4 FY27", "Data Superhero", "Planned",
                                         "", "", "", "Talk", "", "", "", "", ""]],
                                       columns=SE_COLS),
        "Talk Feedback": pd.DataFrame([["old-1"] + [""] * 12], columns=[f"c{i}" for i in range(13)]),
        "Partner Metrics": pd.DataFrame(columns=["Submission ID", "Partner", "Event Name", "City", "Event Date",
                                                 "Total Attendees", "Registered / RSVPs", "Speaker Name"])})
    sl.OVERRIDE["program"] = program
    hub = ops.MemorySheets({})
    ops.OVERRIDE["sheets"] = hub
    yield program, hub
    sl.OVERRIDE.clear()
    ops.OVERRIDE.clear()


def se(program):
    return program.tabs["Speaker-Events"]


# ── "I'm speaking at an event" ───────────────────────────────────────────────────────────────────────────────────

def test_new_talk_adds_event_and_speaker_events_row(env):
    program, _ = env
    ok, msg = act.report_talk(name="Joyce Avila", email=ME, event="AI Camp Austin", date="2026-12-02", city="Austin",
                              talk_title="CoWork in the Real World")
    assert ok and "on the program" in msg
    assert list(program.tabs["Event List"]["Event Name"]) == ["ODSC AI New York", "AI Camp Austin"]
    row = se(program).iloc[-1]
    assert (row["SE ID"], row["Speaker ID"], row["Event ID"], row["Stage"]) == ("SE-002", "SPK-001", "EVT-002", "Confirmed")
    rec = act.updates()[0]
    assert rec["email"] == "joyce@example.com" and rec["se_id"] == "SE-002" and rec["status"] == "Confirmed"


def test_same_talk_again_edits_not_duplicates(env):
    program, _ = env
    act.report_talk(name="Joyce", email=ME, event="AI Camp Austin", date="2026-12-02", city="Austin")
    ok, msg = act.report_talk(name="Joyce", email=ME.lower(), event="AI camp  austin", date="2026-12-02",
                              city="Austin", talk_title="New title")
    assert ok and msg.startswith("Updated")
    assert len(act.updates()) == 1 and act.updates()[0]["talk_title"] == "New title"
    assert len(se(program)) == 2 and len(program.tabs["Event List"]) == 2


def test_talk_on_existing_event_confirms_existing_row(env):
    program, _ = env
    act.report_talk(name="Joyce", email=ME, event="ODSC AI New York", date="2026-12-03", city="New York",
                    talk_title="CoWork")
    assert len(se(program)) == 1
    assert se(program).iloc[0]["Stage"] == "Confirmed" and se(program).iloc[0]["Talk Title"] == "CoWork"


def test_unknown_speaker_gets_a_confirm_row(env):
    program, _ = env
    act.report_talk(name="New Person", email="new@x.com", event="ODSC AI New York", date="2026-12-03")
    assert program.tabs["Speakers"].iloc[-1]["Speaker ID"] == "SPK-002"
    assert se(program).iloc[-1]["Speaker ID"] == "SPK-002"


def test_talk_needs_event_and_date(env):
    assert act.report_talk(name="J", email=ME, event="", date="2026-12-02", city="")[0] is False
    assert act.updates() == []


# ── CFPs ─────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_cfp_submitted_then_accepted_adds_talk(env):
    program, _ = env
    ok, _ = act.report_cfp(name="Joyce", email=ME, conference="DevFest Berlin", deadline="2026-12-15", talk_title="Agents")
    assert ok and act.my_cfps(ME)[0]["status"] == "Submitted"
    assert len(se(program)) == 1                                             # a CFP alone isn't a talk
    key = act.my_cfps(ME)[0]["key"]
    ok, msg = act.cfp_result(key, ME, "Accepted", event_date="2027-02-10", city="Berlin")
    assert ok and "Congratulations" in msg
    rec = act.my_cfps(ME)[0]
    assert rec["status"] == "Accepted" and rec["decided_at"] and rec["se_id"] == "SE-002"
    assert se(program).iloc[-1]["Stage"] == "Confirmed"


def test_cfp_declined_updates_row_only(env):
    program, _ = env
    act.report_cfp(name="Joyce", email=ME, conference="PyCon FR")
    key = act.my_cfps(ME)[0]["key"]
    assert act.cfp_result(key, ME, "Declined")[0]
    assert [r["status"] for r in act.my_cfps(ME)] == ["Declined"] and len(se(program)) == 1


def test_resubmitting_cfp_keeps_status_and_one_row(env):
    act.report_cfp(name="Joyce", email=ME, conference="PyCon FR")
    act.cfp_result(act.my_cfps(ME)[0]["key"], ME, "Declined")
    act.report_cfp(name="Joyce", email=ME, conference="PyCon FR", talk_title="Better title")
    assert len(act.my_cfps(ME)) == 1 and act.my_cfps(ME)[0]["status"] == "Declined"


def test_speaker_cannot_change_someone_elses_cfp(env):
    act.report_cfp(name="Joyce", email=ME, conference="PyCon FR")
    key = act.my_cfps(ME)[0]["key"]
    ok, msg = act.cfp_result(key, "someone@else.com", "Accepted")
    assert not ok and act.my_cfps(ME)[0]["status"] == "Submitted"


# ── Roll-up ──────────────────────────────────────────────────────────────────────────────────────────────────────

def test_rollup_copies_feedback_fills_blanks_and_flags_unmatched(env):
    program, hub = env
    fb_cols = ops.HEADERS.get("Talk_Feedback") or [f"f{i}" for i in range(17)]
    hub.tabs["Talk_Feedback"] = pd.DataFrame([["old-1"] + [""] * 16, ["new-1", "2026-12-03", "Joyce Avila", "ODSC",
                                               "CoWork", "2026-12-03", "5"] + [""] * 8 + ["Fan", "fan@x.com"]],
                                             columns=fb_cols)
    hub.tabs["Event_Headcount"] = pd.DataFrame([
        ["2026-12-04", "joyce@example.com", "ODSC AI NY", "2026-12-04", "New York", "", "", "", "", "88", ""],
        ["2026-12-04", "nobody@x.com", "Mystery Meetup", "2026-12-04", "Lima", "", "", "", "", "20", ""]],
        columns=["Submitted_At", "Speaker_Email", "Event_Name", "Event_Date", "City", "Photos", "Detected_Total",
                 "Peak_Count", "Sum_Count", "Reported_Attendance", "Photo_Details"])
    program.tabs["Partner Metrics"].loc[0] = ["PM-1", "ODSC", "ODSC AI New York", "New York", "2026-12-03", "99", "210",
                                             "Joyce Avila"]
    out = rollup.run()
    assert out["feedback_copied"] == 1
    copied = program.tabs["Talk Feedback"].iloc[-1].tolist()
    assert copied[0] == "new-1" and "fan@x.com" not in copied and len(copied) == 13
    row = se(program).iloc[0]
    assert row["Attended"] == "88" and row["Registered"] == "210"            # headcount first; partner fills Registered
    review = ops.records("Needs_Review")
    assert [r["source"] for r in review] == ["Event_Headcount"] and "Mystery Meetup" in review[0]["detail"]
    rollup.run()                                                             # idempotent
    assert len(program.tabs["Talk Feedback"]) == 2 and len(ops.records("Needs_Review")) == 1


def test_portal_share_an_update_form_saves_and_prefills_email(env):
    from streamlit.testing.v1 import AppTest
    program, _ = env
    at = AppTest.from_file("pages/1_Speaker_Portal.py", default_timeout=30)
    at.query_params["section"] = "after"
    at.session_state["spk_email"] = "joyce@example.com"
    at.run()
    assert not at.exception, at.exception
    assert any(h.value == "Share an update" for h in at.subheader)
    form_inputs = {t.label: t for t in at.text_input}
    form_inputs["Event *"].input("AI Camp Austin")
    form_inputs["City"].input("Austin")
    next(d for d in at.date_input if d.label == "Date *").set_value(__import__("datetime").date(2026, 12, 2))
    next(b for b in at.button if b.label == "Save").click().run()
    assert not at.exception, at.exception
    assert any("on the program" in s.value for s in at.success)
    assert act.updates()[0]["email"] == "joyce@example.com"
    assert se(program).iloc[-1]["Stage"] == "Confirmed"
