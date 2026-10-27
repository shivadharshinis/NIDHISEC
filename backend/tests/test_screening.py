"""Advisory screening: rules, extraction, duplicates, permissions, history, review and audit."""

import os
from datetime import date, timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DatabaseError

from app.models import FDR, AuditLog, FDRDocument, ReviewDecision, VerificationAssignment
from app.models.screening import ScreeningRun
from app.services import document_storage
from app.services import screening as screening_service
from app.services.extraction import PdfTextExtractor, extract_document
from tests.conftest import fdr_payload
from tests.test_documents import PDF_BYTES, make_png, upload


def make_text_pdf(lines: list[str]) -> bytes:
    """A small, valid PDF whose text layer contains the given lines (no parentheses in text)."""
    stream = "BT /F1 11 Tf 72 760 Td 14 TL " + " ".join(f"({line}) Tj T*" for line in lines) + " ET"
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = b"%PDF-1.4\n"
    offsets = []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n{body}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets)
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out


def receipt_lines(fdr: dict, institution_name: str, **overrides) -> list[str]:
    def ddmmyyyy(iso: str) -> str:
        y, m, d = iso.split("-")
        return f"{d}/{m}/{y}"

    values = {
        "bank": fdr["bank_name"],
        "ifsc": fdr["ifsc_code"],
        "number": fdr["fdr_number"],
        "holder": f"{institution_name} jointly with Member Secretary AICTE",
        "amount": "Rs. " + fdr["amount"],
        "issue": ddmmyyyy(fdr["issue_date"]),
        "maturity": ddmmyyyy(fdr["maturity_date"]),
    }
    values.update(overrides)
    return [
        values["bank"],
        f"Branch IFSC: {values['ifsc']}",
        "FIXED DEPOSIT RECEIPT",
        f"FDR No: {values['number']}",
        f"Name of Depositor: {values['holder']}",
        f"Deposit Amount: {values['amount']}",
        f"Date of Issue: {values['issue']}",
        f"Maturity Date: {values['maturity']}",
    ]


def run(client, actors, fdr_id, who="aicte"):
    return client.post(f"/api/fdrs/{fdr_id}/screening/runs", headers=actors.headers[who])


def codes(result: dict) -> set[str]:
    return {f["code"] for f in result["findings"]}


def finding(result: dict, code: str) -> dict:
    return next(f for f in result["findings"] if f["code"] == code)


@pytest.fixture
def fdr(actors, create_fdr):
    return create_fdr(actors.headers["inst_a"], fdr_number="SCR-10001")


@pytest.fixture
def receipt(client, actors, fdr):
    pdf = make_text_pdf(receipt_lines(fdr, actors.institution_a.name))
    response = upload(client, actors.headers["inst_a"], fdr["id"], pdf, filename="receipt.pdf")
    assert response.status_code == 201, response.text
    return response.json(), pdf


# ---------- consistent record ----------


def test_consistent_record_and_receipt(client, actors, fdr, receipt):
    response = run(client, actors, fdr["id"])
    assert response.status_code == 201
    result = response.json()
    assert result["status"] == "COMPLETED"
    assert result["review_priority"] == "LOW"
    assert result["high_count"] == 0 and result["warning_count"] == 0
    assert result["engine_version"].startswith("screening/1.0")
    assert result["is_latest"] is True and result["is_stale"] is False

    extraction = result["extraction"][0]
    assert extraction["status"] == "EXTRACTED" and extraction["method"] == "pypdf-text-layer"
    fields = {f["field"]: f for f in extraction["fields"]}
    assert fields["fdr_number"]["value"] == "SCR-10001"
    assert fields["amount"]["value"] == fdr["amount"]
    assert fields["issue_date"]["value"] == fdr["issue_date"]
    assert fields["amount"]["page"] == 1 and "Deposit Amount" in fields["amount"]["raw"]
    # Only snippets are kept, never the whole document text.
    assert "FIXED DEPOSIT RECEIPT" not in str(extraction)


# ---------- document vs record ----------


def test_mismatched_receipt_is_flagged_with_explanations(client, actors, fdr):
    pdf = make_text_pdf(receipt_lines(
        fdr, actors.institution_a.name,
        bank="Other Sample Bank", ifsc="OTHR0000009", number="SCR-99999", amount="Rs. 2,75,000.00",
        issue="01/01/2020", maturity="01/01/2021",
    ))
    upload(client, actors.headers["inst_a"], fdr["id"], pdf, filename="receipt.pdf")
    result = run(client, actors, fdr["id"]).json()

    expected = {
        "DOC_FDR_NUMBER_MISMATCH": "HIGH",
        "DOC_AMOUNT_MISMATCH": "HIGH",
        "DOC_ISSUE_DATE_MISMATCH": "WARNING",
        "DOC_MATURITY_DATE_MISMATCH": "WARNING",
        "DOC_IFSC_MISMATCH": "WARNING",
        "DOC_BANK_NAME_MISMATCH": "WARNING",
    }
    for code, severity in expected.items():
        item = finding(result, code)
        assert item["severity"] == severity
        assert item["reason"] and item["description"] and item["rule_version"] == "1.0"
    amount = finding(result, "DOC_AMOUNT_MISMATCH")
    assert amount["field"] == "amount"
    assert amount["observed"]["record"] == fdr["amount"]
    assert amount["observed"]["document_values"][0]["value"] == "275000.00"
    assert amount["observed"]["document_values"][0]["page"] == 1
    assert result["review_priority"] == "HIGH"


def test_missing_fields_and_documents(client, actors, create_fdr, fdr):
    bare = create_fdr(actors.headers["inst_a"], fdr_number="SCR-20002", branch_name=None, ifsc_code=None)
    result = run(client, actors, bare["id"]).json()
    assert "DOC_NONE_ATTACHED" in codes(result)
    assert finding(result, "REC_OPTIONAL_FIELDS_MISSING")["field"] == "branch_name,ifsc_code"

    upload(client, actors.headers["inst_a"], fdr["id"], make_text_pdf(["Letter about a deposit", "Nothing labelled here"]))
    result = run(client, actors, fdr["id"]).json()
    assert result["extraction"][0]["status"] == "NO_FIELDS_FOUND"
    missing = finding(result, "DOC_KEY_FIELDS_NOT_FOUND")
    assert missing["severity"] == "INFO"
    assert set(missing["field"].split(",")) == {"fdr_number", "amount", "issue_date", "maturity_date"}


def test_inconsistent_dates_within_document(client, actors, fdr):
    pdf = make_text_pdf(receipt_lines(fdr, actors.institution_a.name, issue="01/06/2026", maturity="01/01/2026"))
    upload(client, actors.headers["inst_a"], fdr["id"], pdf)
    assert "DOC_DATE_ORDER_INVALID" in codes(run(client, actors, fdr["id"]).json())


def test_record_rules_for_invalid_dates_and_amounts(actors, fdr, db):
    record = db.get(FDR, fdr["id"])
    today = date.today()
    # Values the API would refuse, as could exist in legacy or imported data.
    record.issue_date, record.maturity_date, record.amount_paise = today + timedelta(days=10), today, 0
    found = {f.code: f for f in screening_service.record_rules(record)}
    assert found["REC_DATE_ORDER_INVALID"].severity.value == "HIGH"
    assert found["REC_ISSUE_DATE_FUTURE"].severity.value == "HIGH"
    assert found["REC_AMOUNT_OUT_OF_RANGE"].severity.value == "HIGH"
    db.rollback()

    record = db.get(FDR, fdr["id"])
    record.issue_date, record.maturity_date = date(2020, 1, 1), date(2031, 6, 1)
    assert "REC_TENURE_TOO_LONG" in {f.code for f in screening_service.record_rules(record)}
    db.rollback()


def test_holder_that_does_not_name_institution(client, actors, fdr):
    pdf = make_text_pdf(receipt_lines(fdr, actors.institution_a.name, holder="Some Unrelated Trading Company"))
    upload(client, actors.headers["inst_a"], fdr["id"], pdf)
    item = finding(run(client, actors, fdr["id"]).json(), "DOC_HOLDER_NOT_INSTITUTION")
    assert item["severity"] == "INFO"


def test_lifecycle_findings_are_separate_and_informational(client, actors, create_fdr):
    today = date.today()
    soon = create_fdr(actors.headers["inst_a"], fdr_number="SCR-30003",
                      issue_date=(today - timedelta(days=300)).isoformat(),
                      maturity_date=(today + timedelta(days=20)).isoformat())
    result = run(client, actors, soon["id"]).json()
    item = finding(result, "LIFE_MATURING_SOON")
    assert item["category"] == "LIFECYCLE" and item["severity"] == "INFO"
    assert "not an integrity concern" in item["reason"]


# ---------- extraction ----------


def test_extraction_limitations_are_reported(client, actors, fdr):
    inst = actors.headers["inst_a"]
    upload(client, inst, fdr["id"], make_text_pdf([]), filename="scan.pdf")  # a page with no text layer
    upload(client, inst, fdr["id"], PDF_BYTES, filename="broken.pdf", document_type="OTHER")  # no pages/xref
    upload(client, inst, fdr["id"], make_png(), filename="photo.png", document_type="OTHER")
    result = run(client, actors, fdr["id"]).json()
    statuses = {e["document_name"]: e["status"] for e in result["extraction"]}
    assert statuses == {"scan.pdf": "NO_TEXT_LAYER", "photo.png": "UNSUPPORTED_FORMAT", "broken.pdf": "FAILED"}
    assert finding(result, "DOC_EXTRACTION_FAILED")["severity"] == "WARNING"
    assert result["status"] == "COMPLETED"
    assert finding(result, "DOC_NO_TEXT_LAYER")["severity"] == "INFO"
    assert "OCR" in finding(result, "DOC_EXTRACTION_UNSUPPORTED")["description"]


def test_extractor_crash_becomes_a_finding_not_a_failed_run(client, actors, fdr, receipt, monkeypatch):
    def boom(self, data):
        raise RuntimeError("simulated parser crash")

    monkeypatch.setattr(PdfTextExtractor, "extract", boom)
    result = run(client, actors, fdr["id"]).json()
    assert result["status"] == "COMPLETED"
    assert finding(result, "DOC_EXTRACTION_FAILED")["severity"] == "WARNING"


def test_extraction_does_not_modify_the_document(client, actors, fdr, receipt, db):
    document, pdf = receipt
    stored = document_storage._path_for(db.scalar(select(FDRDocument.storage_key)))
    before = (stored.read_bytes(), os.stat(stored).st_mtime_ns)
    run(client, actors, fdr["id"])
    run(client, actors, fdr["id"])
    assert (stored.read_bytes(), os.stat(stored).st_mtime_ns) == before
    assert stored.read_bytes() == pdf
    report = client.post(f"/api/fdrs/{fdr['id']}/documents/{document['id']}/integrity-check", headers=actors.headers["aicte"])
    assert report.json()["status"] == "intact"
    assert len(document_storage.list_stored_files()) == 1  # no copies written


def test_tampered_document_is_not_read(client, actors, fdr, receipt, db):
    stored = document_storage._path_for(db.scalar(select(FDRDocument.storage_key)))
    stored.write_bytes(stored.read_bytes().replace(b"SCR-10001", b"SCR-10009"))
    result = run(client, actors, fdr["id"]).json()
    assert finding(result, "DOC_INTEGRITY_FAILED")["severity"] == "HIGH"
    assert result["extraction"][0]["status"] == "INTEGRITY_FAILED"
    assert "DOC_FDR_NUMBER_MISMATCH" not in codes(result)


def test_extract_document_direct():
    assert extract_document(b"\x89PNG", "image/png").status == "UNSUPPORTED_FORMAT"
    assert extract_document(b"%PDF-1.4 garbage", "application/pdf").status in ("FAILED", "NO_TEXT_LAYER")
    good = extract_document(make_text_pdf(["Maturity Amount: Rs. 9,99,999.00", "Deposit Amount: Rs. 1,000.00"]), "application/pdf")
    assert [f.value for f in good.values("amount")] == ["1000.00"]  # maturity value is not the deposit amount


# ---------- duplicates ----------


def test_exact_and_possible_cross_institution_matches(client, actors, create_fdr):
    original = create_fdr(actors.headers["inst_a"], fdr_number="DUP-55555")
    exact = create_fdr(actors.headers["inst_b"], fdr_number="dup 55555")
    possible = create_fdr(actors.headers["inst_b"], fdr_number="DUP/055555", amount="999.00")

    exact_result = run(client, actors, exact["id"]).json()
    item = next(f for f in exact_result["findings"] if f["related_fdr_id"] == original["id"])
    assert item["code"] == "DUP_EXACT_OTHER_INSTITUTION" and item["match_type"] == "EXACT"
    assert item["severity"] == "HIGH" and item["category"] == "DUPLICATE"
    assert item["observed"]["other"]["institution"]["id"] == actors.institution_a.id
    assert item["observed"]["differing_fields"] == []
    assert "not proof of fraud" in item["reason"]

    possible_result = run(client, actors, possible["id"]).json()
    item = next(f for f in possible_result["findings"] if f["related_fdr_id"] == original["id"])
    assert item["code"] == "DUP_POSSIBLE_OTHER_INSTITUTION" and item["match_type"] == "POSSIBLE"
    assert item["observed"]["differing_fields"] == ["amount"]
    # Same institution pair (exact vs possible, both inst B) is classified separately.
    same = next(f for f in possible_result["findings"] if f["related_fdr_id"] == exact["id"])
    assert same["code"] == "DUP_POSSIBLE_SAME_INSTITUTION" and same["severity"] == "WARNING"


def test_near_reference_and_amount_alone(client, actors, create_fdr):
    base = create_fdr(actors.headers["inst_a"], fdr_number="NEAR-12345", amount="5000.00")
    near = create_fdr(actors.headers["inst_b"], fdr_number="NEAR-12346", amount="5000.00")
    create_fdr(actors.headers["inst_b"], fdr_number="TOTALLY-OTHER", amount="5000.00")
    create_fdr(actors.headers["inst_b"], fdr_number="NEAR-12347", amount="5000.00",
               bank_name="Different Bank", ifsc_code="DIFF0000001")

    result = run(client, actors, base["id"]).json()
    duplicates = [f for f in result["findings"] if f["category"] == "DUPLICATE"]
    assert [(f["code"], f["related_fdr_id"]) for f in duplicates] == [("DUP_NEAR_REFERENCE", near["id"])]


def test_same_document_file_on_two_records(client, actors, create_fdr, fdr):
    other = create_fdr(actors.headers["inst_b"], fdr_number="SCR-OTHER-1")
    pdf = make_text_pdf(receipt_lines(fdr, actors.institution_a.name))
    upload(client, actors.headers["inst_a"], fdr["id"], pdf)
    upload(client, actors.headers["inst_b"], other["id"], pdf)
    item = finding(run(client, actors, other["id"]).json(), "DUP_SAME_DOCUMENT_FILE")
    assert item["severity"] == "HIGH" and item["related_fdr_id"] == fdr["id"] and item["match_type"] == "SAME_FILE"


# ---------- permissions ----------


def test_only_aicte_can_use_screening(client, actors, fdr, receipt, db):
    run(client, actors, fdr["id"])
    finding_id = client.get(f"/api/fdrs/{fdr['id']}/screening", headers=actors.headers["aicte"]).json()["latest"]["findings"]
    review_target = finding_id[0]["id"] if finding_id else 1
    for who in ("inst_a", "inst_b", "bank"):
        headers = actors.headers[who]
        assert client.get(f"/api/fdrs/{fdr['id']}/screening", headers=headers).status_code == 403
        assert client.post(f"/api/fdrs/{fdr['id']}/screening/runs", headers=headers).status_code == 403
        assert client.get("/api/screening/queue", headers=headers).status_code == 403
        response = client.post(f"/api/fdrs/{fdr['id']}/screening/findings/{review_target}/reviews",
                               json={"disposition": "DISMISSED_NOT_AN_ISSUE", "notes": "Clearing my own record"},
                               headers=headers)
        assert response.status_code == 403
    # Unknown FDR gives the same answer to non-AICTE users.
    assert client.get("/api/fdrs/999999/screening", headers=actors.headers["inst_a"]).status_code == 403
    assert client.get(f"/api/fdrs/{fdr['id']}/screening").status_code == 401
    denied = db.scalars(select(AuditLog).where(AuditLog.action == "SCREENING_ACCESS_DENIED")).all()
    assert len(denied) == 13
    assert {d.actor_role for d in denied} == {"INSTITUTION", "BANK_OFFICER"}


def test_assigned_bank_officer_gains_no_screening_access(client, actors, fdr, receipt):
    run(client, actors, fdr["id"])
    version = client.get(f"/api/fdrs/{fdr['id']}", headers=actors.headers["aicte"]).json()["version"]
    client.post(f"/api/fdrs/{fdr['id']}/verification/assignments",
                json={"bank_officer_id": actors.user["bank"].id, "fdr_version": version}, headers=actors.headers["aicte"])
    bank = actors.headers["bank"]
    assert client.get(f"/api/fdrs/{fdr['id']}/screening", headers=bank).status_code == 403
    case = client.get("/api/verification/cases", headers=bank).json()["items"][0]
    assert "screening" not in str(client.get(f"/api/verification/cases/{case['id']}", headers=bank).json()).lower()


def test_institutions_learn_nothing_from_screening(client, actors, create_fdr, fdr):
    other = create_fdr(actors.headers["inst_b"], fdr_number="SCR-10001")  # same reference, other institution
    run(client, actors, other["id"])
    run(client, actors, fdr["id"])
    for who, record in (("inst_a", fdr), ("inst_b", other)):
        detail = client.get(f"/api/fdrs/{record['id']}", headers=actors.headers[who]).text
        history = client.get(f"/api/fdrs/{record['id']}/history", headers=actors.headers[who]).text
        for secret in ("SCREENING", "DUP_EXACT", "priority", actors.institution_a.code if who == "inst_b" else actors.institution_b.code):
            assert secret not in detail + history, (who, secret)


# ---------- advisory only ----------


def test_screening_never_changes_the_record_or_workflow(client, actors, create_fdr, fdr, db):
    create_fdr(actors.headers["inst_b"], fdr_number="SCR-10001")  # cross-institution exact duplicate
    pdf = make_text_pdf(receipt_lines(fdr, actors.institution_a.name, amount="Rs. 1.00"))
    upload(client, actors.headers["inst_a"], fdr["id"], pdf)
    before = client.get(f"/api/fdrs/{fdr['id']}", headers=actors.headers["aicte"]).json()

    result = run(client, actors, fdr["id"]).json()
    assert result["review_priority"] == "HIGH"

    after = client.get(f"/api/fdrs/{fdr['id']}", headers=actors.headers["aicte"]).json()
    for key in ("status", "version", "verification_state", "updated_at", "can_edit"):
        assert after[key] == before[key], key
    assert db.scalar(select(ReviewDecision.id)) is None
    assert db.scalar(select(VerificationAssignment.id)) is None
    # Institutions can keep submitting, including duplicates.
    assert client.post("/api/fdrs", json=fdr_payload(fdr_number="SCR-10001"), headers=actors.headers["inst_a"]).status_code == 201


# ---------- reruns, staleness and reviews ----------


def test_reruns_preserve_history_and_show_changes(client, actors, fdr):
    pdf = make_text_pdf(receipt_lines(fdr, actors.institution_a.name, amount="Rs. 1,23,456.00"))
    upload(client, actors.headers["inst_a"], fdr["id"], pdf)
    first = run(client, actors, fdr["id"]).json()
    mismatch = finding(first, "DOC_AMOUNT_MISMATCH")
    aicte = actors.headers["aicte"]
    review = client.post(f"/api/fdrs/{fdr['id']}/screening/findings/{mismatch['id']}/reviews",
                         json={"disposition": "NEEDS_FOLLOW_UP", "notes": "Asked the institution to check the amount"},
                         headers=aicte)
    assert review.status_code == 201

    # Institution corrects the amount: the latest run becomes stale.
    client.patch(f"/api/fdrs/{fdr['id']}", json={"version": 1, "amount": "123456.00"}, headers=actors.headers["inst_a"])
    overview = client.get(f"/api/fdrs/{fdr['id']}/screening", headers=aicte).json()
    assert overview["latest"]["is_stale"] is True

    second = run(client, actors, fdr["id"]).json()
    assert second["run_number"] == 2 and second["is_stale"] is False
    assert "DOC_AMOUNT_MISMATCH" not in codes(second)
    gone = [g for g in second["no_longer_raised"] if g["code"] == "DOC_AMOUNT_MISMATCH"]
    assert gone and gone[0]["reviewed_by_human"] is True and gone[0]["previous_run_number"] == 1

    overview = client.get(f"/api/fdrs/{fdr['id']}/screening", headers=aicte).json()
    assert [r["run_number"] for r in overview["runs"]] == [2, 1]
    old = client.get(f"/api/fdrs/{fdr['id']}/screening/runs/{first['id']}", headers=aicte).json()
    assert old["is_latest"] is False
    assert finding(old, "DOC_AMOUNT_MISMATCH")["reviews"][0]["disposition"] == "NEEDS_FOLLOW_UP"


def test_reviews_are_append_only_and_carried_as_context(client, actors, create_fdr, fdr):
    create_fdr(actors.headers["inst_b"], fdr_number="SCR-10001")
    first = run(client, actors, fdr["id"]).json()
    dup = finding(first, "DUP_EXACT_OTHER_INSTITUTION")
    url = f"/api/fdrs/{fdr['id']}/screening/findings/{dup['id']}/reviews"
    aicte = actors.headers["aicte"]
    assert client.post(url, json={"disposition": "DISMISSED_NOT_AN_ISSUE", "notes": "short"}, headers=aicte).status_code == 422
    assert client.post(url, json={"disposition": "AUTO_CLEARED", "notes": "Not a real disposition"}, headers=aicte).status_code == 422
    client.post(url, json={"disposition": "NEEDS_FOLLOW_UP", "notes": "Checking with both institutions"}, headers=aicte)
    client.post(url, json={"disposition": "CONCERN_CONFIRMED", "notes": "Same receipt used twice; escalated"}, headers=aicte)

    current = client.get(f"/api/fdrs/{fdr['id']}/screening", headers=aicte).json()["latest"]
    assert [r["disposition"] for r in finding(current, "DUP_EXACT_OTHER_INSTITUTION")["reviews"]] == [
        "NEEDS_FOLLOW_UP", "CONCERN_CONFIRMED"]

    second = run(client, actors, fdr["id"]).json()
    again = finding(second, "DUP_EXACT_OTHER_INSTITUTION")
    assert again["reviews"] == []  # not auto-applied to the new run
    assert [r["run_number"] for r in again["earlier_reviews"]] == [1, 1]
    # Old-run findings can no longer be reviewed.
    assert client.post(url, json={"disposition": "NEEDS_FOLLOW_UP", "notes": "Late review attempt"}, headers=aicte).status_code == 409


def test_screening_history_cannot_be_rewritten(client, actors, create_fdr, fdr, db):
    create_fdr(actors.headers["inst_b"], fdr_number="SCR-10001")
    result = run(client, actors, fdr["id"]).json()
    client.post(f"/api/fdrs/{fdr['id']}/screening/findings/{result['findings'][0]['id']}/reviews",
                json={"disposition": "NEEDS_FOLLOW_UP", "notes": "Looking into it now"}, headers=actors.headers["aicte"])
    for statement in (
        "UPDATE screening_runs SET review_priority = 'LOW'",
        "DELETE FROM screening_runs",
        "UPDATE screening_findings SET severity = 'INFO'",
        "DELETE FROM screening_findings",
        "UPDATE screening_reviews SET disposition = 'DISMISSED_NOT_AN_ISSUE'",
        "DELETE FROM screening_reviews",
    ):
        with pytest.raises(DatabaseError, match="append-only"):
            db.execute(text(statement))
        db.rollback()


# ---------- audit and failure handling ----------


def test_runs_and_reviews_are_audited(client, actors, create_fdr, fdr, db):
    create_fdr(actors.headers["inst_b"], fdr_number="SCR-10001")
    result = run(client, actors, fdr["id"]).json()
    client.post(f"/api/fdrs/{fdr['id']}/screening/findings/{result['findings'][0]['id']}/reviews",
                json={"disposition": "NEEDS_FOLLOW_UP", "notes": "Looking into it now"}, headers=actors.headers["aicte"])
    completed = db.scalar(select(AuditLog).where(AuditLog.action == "SCREENING_RUN_COMPLETED"))
    assert completed.entity_id == fdr["id"] and completed.actor_role == "AICTE_OFFICIAL"
    assert completed.changes["run_id"] == result["id"]
    assert "DUP_EXACT_OTHER_INSTITUTION" in completed.changes["finding_codes"]
    reviewed = db.scalar(select(AuditLog).where(AuditLog.action == "SCREENING_FINDING_REVIEWED"))
    assert reviewed.changes["disposition"] == "NEEDS_FOLLOW_UP"
    # AICTE sees screening entries in the record history; institutions do not.
    aicte_history = client.get(f"/api/fdrs/{fdr['id']}/history", headers=actors.headers["aicte"]).json()
    assert {"SCREENING_RUN_COMPLETED", "SCREENING_FINDING_REVIEWED"} <= {h["action"] for h in aicte_history}


def test_engine_failure_is_recorded_without_side_effects(client, actors, fdr, receipt, db, monkeypatch):
    first = run(client, actors, fdr["id"]).json()
    before = client.get(f"/api/fdrs/{fdr['id']}", headers=actors.headers["aicte"]).json()

    def broken(*args, **kwargs):
        raise RuntimeError("simulated engine failure")

    monkeypatch.setattr(screening_service, "evaluate", broken)
    failed = run(client, actors, fdr["id"])
    assert failed.status_code == 201
    body = failed.json()
    assert body["status"] == "FAILED" and body["error_code"] == "ENGINE_ERROR"
    assert body["findings"] == [] and body["review_priority"] is None
    assert "simulated" not in failed.text  # no internal error details leak

    after = client.get(f"/api/fdrs/{fdr['id']}", headers=actors.headers["aicte"]).json()
    assert after["version"] == before["version"] and after["status"] == before["status"]
    assert db.scalar(select(AuditLog).where(AuditLog.action == "SCREENING_RUN_FAILED")) is not None
    assert client.get(f"/api/fdrs/{fdr['id']}/screening/runs/{first['id']}", headers=actors.headers["aicte"]).status_code == 200

    monkeypatch.undo()
    third = run(client, actors, fdr["id"]).json()
    assert third["status"] == "COMPLETED" and third["run_number"] == 3
    assert len(db.scalars(select(ScreeningRun)).all()) == 3


# ---------- queue ----------


def test_queue_orders_by_priority(client, actors, create_fdr, fdr, receipt):
    low = fdr
    high_a = create_fdr(actors.headers["inst_a"], fdr_number="Q-77777")
    create_fdr(actors.headers["inst_b"], fdr_number="Q-77777")
    run(client, actors, low["id"])
    run(client, actors, high_a["id"])
    queue = client.get("/api/screening/queue", headers=actors.headers["aicte"]).json()
    assert [(i["fdr_id"], i["review_priority"]) for i in queue["items"]] == [(high_a["id"], "HIGH"), (low["id"], "LOW")]
    assert queue["items"][0]["unreviewed_high"] >= 1
    only_high = client.get("/api/screening/queue", params={"priority": "HIGH"}, headers=actors.headers["aicte"]).json()
    assert only_high["total"] == 1
