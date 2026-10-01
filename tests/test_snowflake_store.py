"""Integration tests: SnowflakeStore + StageFileStore against real hybrid tables and stage.

Opt-in. Runs only when CV_WF_TEST_CONNECTION and CV_WF_TEST_SCHEMA are set, and the schema
name must contain TEST (tables are truncated). Notification channels are fakes: no messages
are sent anywhere.

  CV_WF_TEST_CONNECTION=<conn> CV_WF_TEST_SCHEMA=TEMP.CV_WORKFLOW_TEST_AMICAH pytest tests/test_snowflake_store.py
"""
import os
from dataclasses import replace
from datetime import date, timedelta

import pytest

from conftest import ABA, SPK_A, VND, Clock, item_of, make_service, setup_event, tok
from workflow.models import ConcurrentModification, DuplicateAction, InvalidAction, NotAuthorized
from workflow.service import Actor

CONN = os.environ.get("CV_WF_TEST_CONNECTION")
SCHEMA = os.environ.get("CV_WF_TEST_SCHEMA", "")
pytestmark = pytest.mark.skipif(not CONN or "TEST" not in SCHEMA.upper(),
                                reason="Snowflake integration tests are opt-in")
TABLES = ["WF_EVENTS", "WF_MEMBERS", "WF_ITEMS", "WF_ITEM_VERSIONS", "WF_AUDIT", "WF_OUTBOX"]


@pytest.fixture(scope="module")
def connect():
    import snowflake.connector
    db, sch = SCHEMA.split(".")
    conn = snowflake.connector.connect(connection_name=CONN, database=db, schema=sch, paramstyle="qmark",
                                       client_store_temporary_credential=True)
    yield lambda: conn
    conn.close()


@pytest.fixture
def sf(connect):
    from workflow.files import StageFileStore
    from workflow.snowflake_store import SnowflakeStore
    conn = connect()
    for t in TABLES:
        conn.cursor().execute(f"DELETE FROM {t}")
    store = SnowflakeStore(connect)
    svc, email, slack, clock = make_service(store=store, files=StageFileStore(connect, lock=store._lock))
    return svc, email, slack, clock


def test_full_flow_on_snowflake(sf):
    svc, email, slack, clock = sf
    eid = setup_event(svc)
    svc.dispatch()
    email.sent.clear(); slack.sent.clear()
    slides = item_of(svc, SPK_A, eid, "slides")
    t = tok()
    r = svc.submit_item(SPK_A, slides.item_id, upload=("talk deck.pdf", b"%PDF-1 real bytes"), token=t)
    assert r.status == "recorded" and r.queued == 2
    # rerun with the same token: no new version, no new notifications
    assert svc.submit_item(SPK_A, slides.item_id, upload=("talk deck.pdf", b"%PDF-1 real bytes"),
                           token=t).status == "no_change"
    assert len(svc.store.list_versions(slides.item_id)) == 1
    assert svc.dispatch(action_key=r.action_key)["sent"] == 2
    assert svc.dispatch(action_key=r.action_key)["sent"] == 0
    assert [a for a, *_ in email.sent] == [ABA.email] and slack.sent[0][0] == "U_ABA"
    rows = svc.store.list_notifications(action_key=r.action_key)
    assert all(n.status == "SENT" and n.provider_message_id for n in rows)

    # private file round trip, revision keeps v1, vendor gated on approval
    assert svc.download(SPK_A, slides.item_id, 1) == ("talk deck.pdf", b"%PDF-1 real bytes")
    with pytest.raises(NotAuthorized):
        svc.download(VND, slides.item_id, 1)
    svc.review_item(ABA, slides.item_id, version=1, approve=True)
    assert svc.download(VND, slides.item_id, 1)[1] == b"%PDF-1 real bytes"
    svc.submit_item(SPK_A, slides.item_id, upload=("talk deck.pdf", b"%PDF-2"), token=tok())
    assert svc.download(SPK_A, slides.item_id, 1)[1] == b"%PDF-1 real bytes"
    assert svc.download(SPK_A, slides.item_id, 2)[1] == b"%PDF-2"
    with pytest.raises(NotAuthorized):
        svc.download(VND, slides.item_id, 2)


def test_unique_keys_enforced_by_database(sf):
    svc, *_ = sf
    eid = setup_event(svc)
    bio = item_of(svc, SPK_A, eid, "bio")
    r = svc.submit_item(SPK_A, bio.item_id, text={"bio": "Hi"}, token="same")
    store = svc.store
    store.action_exists = lambda k: False     # bypass the pre-check: rely on the constraint
    from workflow.models import ChangeSet, ItemUpdate
    audit = svc._audit(r.action_key, eid, "ITEM_SUBMITTED", SPK_A, "SPEAKER", bio.item_id)
    with pytest.raises(DuplicateAction):
        store.apply(ChangeSet(audit=[audit]))
    with pytest.raises(InvalidAction):       # (event, role, email) unique
        svc.invite(ABA, eid, role="SPEAKER", email=SPK_A.email, token=tok())


def test_optimistic_concurrency_and_atomic_rollback(sf):
    svc, *_ = sf
    eid = setup_event(svc)
    bio = item_of(svc, SPK_A, eid, "bio")
    from workflow.models import ChangeSet, ItemUpdate
    stale = svc.store.get_item(bio.item_id)
    svc.submit_item(SPK_A, bio.item_id, text={"bio": "first"}, token=tok())
    audit = svc._audit("k-stale", eid, "ITEM_SUBMITTED", SPK_A, "SPEAKER", bio.item_id)
    with pytest.raises(ConcurrentModification):
        svc.store.apply(ChangeSet(audit=[audit], item_updates=[ItemUpdate(replace(stale, current_version=1), 0)]))
    assert not svc.store.action_exists("k-stale")      # audit row rolled back with the failed update


def test_claims_and_stale_sends_on_snowflake(sf):
    svc, email, slack, clock = sf
    eid = setup_event(svc)
    svc.dispatch()
    bio = item_of(svc, SPK_A, eid, "bio")
    r = svc.submit_item(SPK_A, bio.item_id, text={"bio": "Hi"}, token=tok())
    a = svc.store.claim_notifications(now=clock.now, limit=10, token="A", action_key=r.action_key)
    b = svc.store.claim_notifications(now=clock.now, limit=10, token="B", action_key=r.action_key)
    assert len(a) == 2 and b == []
    clock.advance(minutes=11)
    svc.dispatch()
    assert {n.status for n in svc.store.list_notifications(action_key=r.action_key)} == {"UNCERTAIN"}


def test_missing_owner_on_snowflake(sf):
    svc, *_ = sf
    eid = setup_event(svc, with_owner=False)
    bio = item_of(svc, SPK_A, eid, "bio")
    r = svc.submit_item(SPK_A, bio.item_id, text={"bio": "Hi"}, token=tok())
    [n] = svc.store.list_notifications(action_key=r.action_key)
    assert n.status == "UNROUTABLE"
    svc.invite(ABA, eid, role="OWNER", email=ABA.email, token=tok())
    svc.reroute(ABA, n.notification_id, tok())
    assert sorted(x.status for x in svc.store.list_notifications(action_key=r.action_key)) == ["CANCELLED", "PENDING"]
