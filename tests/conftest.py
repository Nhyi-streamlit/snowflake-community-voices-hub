import os
import sys
from datetime import date, datetime, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from workflow.channels import FakeChannel  # noqa: E402
from workflow.files import MemoryFileStore  # noqa: E402
from workflow.models import EMAIL, SLACK  # noqa: E402
from workflow.service import Actor, Config, WorkflowService  # noqa: E402
from workflow.store import MemoryStore  # noqa: E402


class Clock:
    def __init__(self):
        self.now = datetime(2026, 10, 1, 12, 0, 0)

    def __call__(self):
        return self.now

    def advance(self, **kw):
        self.now += timedelta(**kw)


ABA = Actor("sub-aba", "aba.micah@snowflake.com", is_admin=True)
DELEG = Actor("sub-deleg", "delegate@snowflake.com")
SPK_A = Actor("sub-spk-a", "speaker.a@example.com")
SPK_B = Actor("sub-spk-b", "speaker.b@example.com")
VND = Actor("sub-vnd", "vendor@eventco.example")
VND2 = Actor("sub-vnd2", "other@eventco2.example")
STRANGER = Actor("sub-stranger", "stranger@example.com")


def make_service(store=None, files=None, delivery=True, channels=None, clock=None):
    clock = clock or Clock()
    email = FakeChannel()
    slack = FakeChannel()
    svc = WorkflowService(store or MemoryStore(), files or MemoryFileStore(),
                          Config(app_base_url="https://cv.example", enabled_channels=frozenset({EMAIL, SLACK}),
                                 delivery_enabled=delivery),
                          channels=channels if channels is not None else {EMAIL: email, SLACK: slack},
                          clock=clock)
    return svc, email, slack, clock


def tok(prefix="t"):
    tok.n += 1
    return f"{prefix}-{tok.n}"


tok.n = 0


def setup_event(svc, *, with_owner=True, with_delegate=False, vendor=True, speakers=(SPK_A,)):
    eid = svc.create_event(ABA, name="Data Summit Lagos", start_date=date(2026, 11, 20), city="Lagos",
                           token=tok()).ref
    if with_owner:
        svc.invite(ABA, eid, role="OWNER", email=ABA.email, slack_user_id="U_ABA", token=tok())
    if with_delegate:
        svc.invite(ABA, eid, role="DELEGATE", email=DELEG.email, token=tok())
        svc.bind_invites(DELEG)
    for s in speakers:
        svc.invite(ABA, eid, role="SPEAKER", email=s.email, due_date=date(2026, 11, 1), token=tok())
        svc.bind_invites(s)
    if vendor:
        svc.invite(ABA, eid, role="VENDOR", email=VND.email, token=tok())
        svc.bind_invites(VND)
    svc.bind_invites(ABA)
    return eid


def item_of(svc, actor, eid, item_type, party=None):
    view = svc.event_view(actor, eid)
    return next(i for i in view.items if i.item_type == item_type and (party is None or i.party == party))


@pytest.fixture
def env():
    svc, email, slack, clock = make_service()
    eid = setup_event(svc)
    svc.dispatch()          # flush assignment notifications so tests start clean
    email.sent.clear()
    slack.sent.clear()
    return svc, email, slack, clock, eid
