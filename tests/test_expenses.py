"""Expense form uploads: several files (form + receipts), one Expense_Forms row, one email to Aba."""
from types import SimpleNamespace

from utils import expenses as exp

FILES = [{"filename": "Expense Form.xlsx", "data": b"x" * 10, "mime_type": "application/vnd.ms-excel"},
         {"filename": "uber receipt.jpg", "data": b"y" * 10, "mime_type": "image/jpeg"}]


class Fake:
    def __init__(self, fail_files=(), append_ok=True, send_ok=True):
        self.rows, self.sent, self.fail, self.append_ok, self.send_ok = [], [], set(fail_files), append_ok, send_ok

    def upload(self, eid, files):
        ok = [f for f in files if f["filename"] not in self.fail]
        return "https://drive.google.com/drive/folders/F1", [f"https://drive/{f['filename']}" for f in ok], \
            [f["filename"] for f in files if f["filename"] in self.fail]

    def append(self, row):
        self.rows.append(row)
        return self.append_ok

    def send(self, to, subject, body):
        self.sent.append((to, subject, body))
        return SimpleNamespace(__bool__=lambda s: True) if self.send_ok else SimpleNamespace(reason="SERVICE_DISABLED", __bool__=lambda s: False)

    def go(self, **kw):
        args = dict(name="Stéphane Burwash", email="Stephane@Infostrux.com", event="ODSC Montreal",
                    notes="Receipt <b>attached</b>", files=FILES)
        args.update(kw)
        return exp.submit(**args, upload=self.upload, append=self.append,
                          send=lambda *a: self.sent.append(a) or (True if self.send_ok else False))


def test_form_and_receipts_upload_together_and_aba_is_emailed():
    f = Fake()
    r = f.go()
    assert r.saved and r.folder_link.endswith("F1") and r.failed_files == () and r.email_reason == ""
    [row] = f.rows
    assert row[0] == r.expense_id and row[3] == "stephane@infostrux.com"
    assert row[5] == "Expense Form.xlsx; uber receipt.jpg" and row[8] == "Uploaded to Drive"
    [(to, subject, body)] = f.sent
    assert to == ["aba.micah@snowflake.com"] and subject == "Expense form submitted · Stéphane Burwash · ODSC Montreal"
    assert "uber receipt.jpg" in body and "drive/folders/F1" in body
    assert "&lt;b&gt;attached&lt;/b&gt;" in body and "<b>attached</b>" not in body     # speaker text escaped


def test_partial_upload_is_recorded_and_flagged_in_the_email():
    f = Fake(fail_files={"uber receipt.jpg"})
    r = f.go()
    assert r.saved and r.failed_files == ("uber receipt.jpg",)
    assert f.rows[0][8].startswith("Partly uploaded") and "upload failed" in f.sent[0][2]


def test_sheet_failure_sends_nothing():
    f = Fake(append_ok=False)
    assert not f.go().saved and f.sent == []


def test_email_failure_still_saves():
    f = Fake(send_ok=False)
    r = f.go()
    assert r.saved and r.email_reason == "send_failed"


def test_check_rejects_empty_too_many_and_huge():
    assert exp.check([]) and exp.check(FILES * 6)
    assert "over" in exp.check([{"filename": "big.pdf", "data": b"0" * (21 * 1024 * 1024), "mime_type": "x"}])
    assert exp.check(FILES) == ""


def test_receipt_images_are_accepted_file_types():
    assert {"jpg", "jpeg", "png", "heic", "pdf", "xlsx"} <= set(exp.FILE_TYPES)


def test_portal_uploader_takes_multiple_files_after_sign_in():
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file("pages/1_Speaker_Portal.py", default_timeout=30)
    at.query_params["section"] = "travel"
    at.session_state["spk_email"] = "stephane@infostrux.com"
    at.run()
    assert not at.exception, at.exception
    up = next(e.proto for e in at.get("file_uploader") if e.proto.label.startswith("Upload your expense form"))
    assert up.multiple_files and "jpg" in [t.lstrip(".") for t in up.type]
    assert next(b for b in at.button if b.key == "exp_submit").disabled        # nothing attached yet
