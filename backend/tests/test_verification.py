"""Bank verification workflow: assignments, officer access, outcomes, AICTE review, history and audit."""

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DatabaseError, IntegrityError

from app.models import AuditLog, ReviewDecision, UserRole, VerificationAssignment
from app.services import document_storage
from tests.conftest import login
from tests.test_documents import PDF_BYTES, make_png, upload

OUTCOMES = ["CONFIRMED_AGAINST_BANK_RECORDS", "DETAILS_MISMATCH", "ADDITIONAL_INFO_REQUIRED", "UNABLE_TO_VERIFY"]
NOTES = "Checked the deposit ledger for this branch against the submitted details."


# ---------- helpers ----------


@pytest.fixture
def officer2(make_user, client):
    user = make_user(UserRole.BANK_OFFICER)
    return user, login(client, user)


@pytest.fixture
def fdr(actors, create_fdr):
    return create_fdr(actors.headers["inst_a"], fdr_number="VER-A-1")


def get_fdr(client, actors, fdr_id, who="aicte"):
    return client.get(f"/api/fdrs/{fdr_id}", headers=actors.headers[who]).json()


def assign(client, actors, fdr_id, officer_id, version=None, who="aicte", note="Please check the deposit ledger"):
    if version is None:
        version = get_fdr(client, actors, fdr_id)["version"]
    return client.post(
        f"/api/fdrs/{fdr_id}/verification/assignments",
        json={"bank_officer_id": officer_id, "fdr_version": version, "note": note},
        headers=actors.headers[who],
    )


def submit(client, headers, assignment_id, version, outcome="CONFIRMED_AGAINST_BANK_RECORDS", notes=NOTES, **extra):
    return client.post(
        f"/api/verification/cases/{assignment_id}/outcome",
        json={"version": version, "outcome": outcome, "notes": notes, **extra},
        headers=headers,
    )


def review(client, actors, fdr_id, status, remarks=None, internal=None):
    version = get_fdr(client, actors, fdr_id)["version"]
    body = {"version": version, "status": status, "review_remarks": remarks, "internal_notes": internal}
    return client.post(f"/api/fdrs/{fdr_id}/review", json=body, headers=actors.headers["aicte"])


def history(client, actors, fdr_id):
    return client.get(f"/api/fdrs/{fdr_id}/verification", headers=actors.headers["aicte"]).json()


def actions(db, fdr_id=None):
    query = select(AuditLog.action).order_by(AuditLog.id)
    if fdr_id is not None:
        query = query.where(AuditLog.entity_type == "fdr", AuditLog.entity_id == fdr_id)
    return list(db.scalars(query).all())


@pytest.fixture
def assigned(client, actors, fdr):
    response = assign(client, actors, fdr["id"], actors.user["bank"].id)
    assert response.status_code == 201, response.text
    return response.json()


# ---------- assignment creation and validation ----------


def test_assignment_created_and_record_moves_under_review(client, actors, fdr, db):
    response = assign(client, actors, fdr["id"], actors.user["bank"].id)
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "ACTIVE"
    assert body["bank_officer"]["id"] == actors.user["bank"].id
    assert body["assigned_by"]["id"] == actors.user["aicte"].id
    assert body["assignment_note"] == "Please check the deposit ledger"

    record = get_fdr(client, actors, fdr["id"])
    assert record["status"] == "UNDER_REVIEW"
    assert record["verification_state"] == "IN_PROGRESS"
    assert record["can_edit"] is False  # details are frozen while the bank checks them
    assert "VERIFICATION_ASSIGNED" in actions(db, fdr["id"])

    data = history(client, actors, fdr["id"])
    assert data["active_assignment"]["id"] == body["id"]
    assert data["can_assign"] is False


def test_assignment_validation(client, actors, fdr, make_user, db):
    inactive = make_user(UserRole.BANK_OFFICER, is_active=False)
    for officer_id in (999_999, actors.user["inst_a"].id, actors.user["aicte"].id, inactive.id):
        response = assign(client, actors, fdr["id"], officer_id)
        assert response.status_code == 422, officer_id
        assert response.json()["detail"][0]["loc"] == ["body", "bank_officer_id"]

    assert assign(client, actors, fdr["id"], actors.user["bank"].id, version=fdr["version"] + 5).status_code == 409
    assert assign(client, actors, 999_999, actors.user["bank"].id, version=1).status_code == 404
    for who in ("inst_a", "bank"):
        assert assign(client, actors, fdr["id"], actors.user["bank"].id, version=1, who=who).status_code == 403
    assert db.scalar(select(VerificationAssignment.id)) is None


@pytest.mark.parametrize("status", ["REJECTED", "CLARIFICATION_REQUESTED"])
def test_records_with_institution_or_closed_cannot_be_assigned(client, actors, fdr, status):
    assert review(client, actors, fdr["id"], status, remarks="Returned for test").status_code == 200
    response = assign(client, actors, fdr["id"], actors.user["bank"].id)
    assert response.status_code == 409


def test_duplicate_active_assignment_prevented(client, actors, fdr, assigned, officer2):
    second = assign(client, actors, fdr["id"], officer2[0].id)
    assert second.status_code == 409
    assert "reassign" in second.json()["detail"].lower()


def test_database_rejects_two_active_assignments(actors, fdr, assigned, db):
    with pytest.raises(IntegrityError):
        db.execute(
            text(
                "INSERT INTO verification_assignments (fdr_id, bank_officer_id, assigned_by_id, assigned_at, status, version)"
                " VALUES (:fdr, :officer, :aicte, '2026-01-01 00:00:00', 'ACTIVE', 1)"
            ),
            {"fdr": fdr["id"], "officer": actors.user["bank"].id, "aicte": actors.user["aicte"].id},
        )
    db.rollback()


def test_concurrent_assignment_with_same_version(client, actors, fdr, officer2):
    version = fdr["version"]
    first = assign(client, actors, fdr["id"], actors.user["bank"].id, version=version)
    second = assign(client, actors, fdr["id"], officer2[0].id, version=version)
    assert first.status_code == 201
    assert second.status_code == 409
    assert len(history(client, actors, fdr["id"])["assignments"]) == 1


# ---------- reassignment ----------


def test_reassignment_preserves_history(client, actors, fdr, assigned, officer2, db):
    officer2_user, officer2_headers = officer2
    response = client.post(
        f"/api/verification/assignments/{assigned['id']}/reassign",
        json={"bank_officer_id": officer2_user.id, "version": assigned["version"], "reason": "Original officer on leave"},
        headers=actors.headers["aicte"],
    )
    assert response.status_code == 201
    new = response.json()
    assert new["status"] == "ACTIVE" and new["previous_assignment_id"] == assigned["id"]
    assert new["assignment_note"] == assigned["assignment_note"]

    data = history(client, actors, fdr["id"])
    assert [a["status"] for a in data["assignments"]] == ["ACTIVE", "SUPERSEDED"]
    old = data["assignments"][1]
    assert old["end_reason"] == "Original officer on leave"
    assert old["ended_by"]["id"] == actors.user["aicte"].id
    assert old["ended_at"] is not None
    assert "VERIFICATION_REASSIGNED" in actions(db, fdr["id"])

    # The previous officer loses access immediately; the new one gains it.
    old_case = client.get(f"/api/verification/cases/{assigned['id']}", headers=actors.headers["bank"]).json()
    assert old_case["status"] == "SUPERSEDED" and old_case["fdr"] is None and old_case["documents"] == []
    assert client.get(f"/api/fdrs/{fdr['id']}/documents", headers=actors.headers["bank"]).status_code == 403
    assert submit(client, actors.headers["bank"], assigned["id"], assigned["version"]).status_code == 409
    assert client.get(f"/api/verification/cases/{new['id']}", headers=officer2_headers).json()["fdr"]["id"] == fdr["id"]


def test_reassignment_validation(client, actors, fdr, assigned, officer2):
    url = f"/api/verification/assignments/{assigned['id']}/reassign"
    body = {"bank_officer_id": officer2[0].id, "version": assigned["version"], "reason": "Moving to another officer"}
    aicte = actors.headers["aicte"]
    assert client.post(url, json={**body, "reason": "short"}, headers=aicte).status_code == 422
    assert client.post(url, json={**body, "bank_officer_id": actors.user["bank"].id}, headers=aicte).status_code == 422
    assert client.post(url, json={**body, "version": 99}, headers=aicte).status_code == 409
    assert client.post(url, json=body, headers=actors.headers["inst_a"]).status_code == 403
    assert client.post(url, json=body, headers=actors.headers["bank"]).status_code == 403
    assert client.post(url, json=body, headers=aicte).status_code == 201
    # The superseded assignment cannot be reassigned again.
    assert client.post(url, json=body, headers=aicte).status_code == 409


# ---------- bank officer access ----------


def test_assigned_officer_sees_case_and_documents(client, actors, fdr, db):
    doc = upload(client, actors.headers["inst_a"], fdr["id"], PDF_BYTES).json()
    assignment = assign(client, actors, fdr["id"], actors.user["bank"].id).json()
    bank = actors.headers["bank"]

    cases = client.get("/api/verification/cases", headers=bank).json()
    assert [c["id"] for c in cases["items"]] == [assignment["id"]]

    case = client.get(f"/api/verification/cases/{assignment['id']}", headers=bank).json()
    assert case["can_submit_outcome"] is True
    assert case["fdr"]["fdr_number"] == "VER-A-1"
    assert [d["id"] for d in case["documents"]] == [doc["id"]]
    # Restricted view: no duplicate details, AICTE remarks, institution remarks or history.
    for hidden in ("duplicate_review", "review_remarks", "remarks", "status", "can_edit"):
        assert hidden not in case["fdr"]

    listing = client.get(f"/api/fdrs/{fdr['id']}/documents", headers=bank).json()
    assert listing["can_upload"] is False and listing["can_withdraw"] is False and listing["can_check_integrity"] is False
    download = client.get(f"/api/fdrs/{fdr['id']}/documents/{doc['id']}/download", headers=bank)
    assert download.status_code == 200 and download.content == PDF_BYTES
    assert upload(client, bank, fdr["id"], make_png(), filename="x.png").status_code == 403
    assert db.scalar(
        select(AuditLog).where(AuditLog.action == "DOCUMENT_DOWNLOADED", AuditLog.actor_user_id == actors.user["bank"].id)
    ) is not None


def test_bank_officer_still_blocked_from_general_fdr_api(client, actors, fdr, assigned, db):
    bank = actors.headers["bank"]
    assert client.get("/api/fdrs", headers=bank).status_code == 403
    assert client.get("/api/fdrs/summary", headers=bank).status_code == 403
    assert client.get(f"/api/fdrs/{fdr['id']}", headers=bank).status_code == 403
    assert client.get(f"/api/fdrs/{fdr['id']}/history", headers=bank).status_code == 403
    assert client.get(f"/api/fdrs/{fdr['id']}/verification", headers=bank).status_code == 403
    assert "VERIFICATION_ACCESS_DENIED" in actions(db)


def test_unassigned_case_is_inaccessible_and_audited(client, actors, create_fdr, db):
    other = create_fdr(actors.headers["inst_b"], fdr_number="VER-B-1")
    doc = upload(client, actors.headers["inst_b"], other["id"], PDF_BYTES).json()
    bank = actors.headers["bank"]

    assert client.get(f"/api/fdrs/{other['id']}/documents", headers=bank).status_code == 403
    response = client.get(f"/api/fdrs/{other['id']}/documents/{doc['id']}/download", headers=bank)
    assert response.status_code == 403
    assert "VER-B-1" not in response.text and "Beta" not in response.text
    # A non-existent FDR gets exactly the same answer.
    missing = client.get("/api/fdrs/999999/documents", headers=bank)
    assert missing.status_code == 403 and missing.json() == response.json()

    denied = db.scalars(select(AuditLog).where(AuditLog.action == "VERIFICATION_ACCESS_DENIED")).all()
    assert len(denied) == 3
    assert denied[0].actor_user_id == actors.user["bank"].id
    assert denied[0].changes["attempted"] == "fdr_documents"


def test_cross_officer_isolation(client, actors, fdr, assigned, officer2, db):
    _, officer2_headers = officer2
    case_url = f"/api/verification/cases/{assigned['id']}"
    assert client.get(case_url, headers=officer2_headers).status_code == 404
    assert client.get("/api/verification/cases/999999", headers=officer2_headers).status_code == 404
    assert submit(client, officer2_headers, assigned["id"], assigned["version"]).status_code == 404
    assert client.get(f"/api/fdrs/{fdr['id']}/documents", headers=officer2_headers).status_code == 403
    assert client.get("/api/verification/cases?state=all", headers=officer2_headers).json()["total"] == 0
    # The real officer's case is untouched.
    assert client.get(case_url, headers=actors.headers["bank"]).json()["status"] == "ACTIVE"
    assert actions(db).count("VERIFICATION_ACCESS_DENIED") == 4


def test_case_endpoints_are_bank_officer_only(client, actors, assigned):
    for who in ("inst_a", "aicte"):
        assert client.get("/api/verification/cases", headers=actors.headers[who]).status_code == 403
        assert client.get(f"/api/verification/cases/{assigned['id']}", headers=actors.headers[who]).status_code == 403
    assert client.get("/api/verification/officers", headers=actors.headers["bank"]).status_code == 403
    assert client.get("/api/verification/assignments", headers=actors.headers["inst_a"]).status_code == 403
    assert client.get("/api/verification/cases").status_code == 401


def test_cross_institution_isolation(client, actors, fdr, create_fdr, assigned):
    other = create_fdr(actors.headers["inst_b"], fdr_number="VER-B-2")
    # Institution B cannot see A's verification state or history; A cannot use AICTE views.
    assert client.get(f"/api/fdrs/{fdr['id']}", headers=actors.headers["inst_b"]).status_code == 404
    assert client.get(f"/api/fdrs/{fdr['id']}/verification", headers=actors.headers["inst_a"]).status_code == 403
    # The officer's queue contains only the assigned FDR, nothing from institution B.
    cases = client.get("/api/verification/cases?state=all", headers=actors.headers["bank"]).json()["items"]
    assert [c["fdr_number"] for c in cases] == ["VER-A-1"]
    assert other["fdr_number"] not in str(cases)


# ---------- outcomes ----------


@pytest.mark.parametrize("outcome", OUTCOMES)
def test_each_outcome_is_recorded(client, actors, fdr, assigned, outcome, db):
    response = submit(client, actors.headers["bank"], assigned["id"], assigned["version"], outcome=outcome,
                      bank_reference="LEDGER/2026/0042")
    assert response.status_code == 201, response.text
    case = response.json()
    assert case["status"] == "COMPLETED" and case["can_submit_outcome"] is False
    assert case["outcome"]["outcome"] == outcome
    assert case["outcome"]["notes"] == NOTES
    assert case["outcome"]["method"] == "OFFICER_ATTESTATION"
    assert case["outcome"]["submitted_by"]["id"] == actors.user["bank"].id
    assert case["fdr"] is None  # access ends with the assignment

    data = history(client, actors, fdr["id"])
    assert data["assignments"][0]["outcome"]["outcome"] == outcome
    assert data["state"] == "OUTCOME_RECORDED"
    assert "VERIFICATION_OUTCOME_SUBMITTED" in actions(db, fdr["id"])
    assert client.get(f"/api/fdrs/{fdr['id']}/documents", headers=actors.headers["bank"]).status_code == 403


@pytest.mark.parametrize("notes", ["", "too short", " " * 30])
def test_outcome_requires_notes(client, actors, assigned, notes):
    assert submit(client, actors.headers["bank"], assigned["id"], assigned["version"], notes=notes).status_code == 422


def test_outcome_rejects_unknown_type_and_extra_fields(client, actors, assigned):
    bank = actors.headers["bank"]
    assert submit(client, bank, assigned["id"], assigned["version"], outcome="VERIFIED").status_code == 422
    assert submit(client, bank, assigned["id"], assigned["version"], status="ACCEPTED").status_code == 422


def test_only_one_outcome_per_assignment(client, actors, assigned):
    bank = actors.headers["bank"]
    assert submit(client, bank, assigned["id"], assigned["version"]).status_code == 201
    assert submit(client, bank, assigned["id"], assigned["version"]).status_code == 409
    assert submit(client, bank, assigned["id"], assigned["version"] + 1, outcome="DETAILS_MISMATCH").status_code == 409


def test_stale_outcome_version_rejected(client, actors, assigned):
    assert submit(client, actors.headers["bank"], assigned["id"], assigned["version"] + 3).status_code == 409


def test_evidence_references_are_validated(client, actors, fdr, create_fdr):
    inst = actors.headers["inst_a"]
    good = upload(client, inst, fdr["id"], PDF_BYTES).json()
    withdrawn = upload(client, inst, fdr["id"], make_png(), filename="wrong.png").json()
    client.post(f"/api/fdrs/{fdr['id']}/documents/{withdrawn['id']}/withdraw", json={"reason": "Wrong file"}, headers=inst)
    other_fdr = create_fdr(inst, fdr_number="VER-A-2")
    foreign = upload(client, inst, other_fdr["id"], make_png(2, 2), filename="other.png").json()
    assignment = assign(client, actors, fdr["id"], actors.user["bank"].id).json()
    bank = actors.headers["bank"]

    for bad in ([foreign["id"]], [withdrawn["id"]], [999_999]):
        response = submit(client, bank, assignment["id"], assignment["version"], evidence_document_ids=bad)
        assert response.status_code == 422, bad
    response = submit(client, bank, assignment["id"], assignment["version"], evidence_document_ids=[good["id"], good["id"]])
    assert response.status_code == 201
    evidence = response.json()["outcome"]["evidence_documents"]
    assert [d["id"] for d in evidence] == [good["id"]]
    assert evidence[0]["sha256"] == good["sha256"]


# ---------- AICTE review ----------


def test_accept_requires_confirmed_outcome(client, actors, fdr, officer2):
    bank = actors.headers["bank"]
    assignment = assign(client, actors, fdr["id"], actors.user["bank"].id).json()
    # Not while the bank is still checking.
    assert review(client, actors, fdr["id"], "ACCEPTED").status_code == 409

    submit(client, bank, assignment["id"], assignment["version"], outcome="DETAILS_MISMATCH")
    assert review(client, actors, fdr["id"], "ACCEPTED").status_code == 409
    assert history(client, actors, fdr["id"])["can_accept"] is False

    second = assign(client, actors, fdr["id"], officer2[0].id).json()
    submit(client, officer2[1], second["id"], second["version"], outcome="CONFIRMED_AGAINST_BANK_RECORDS")
    assert history(client, actors, fdr["id"])["can_accept"] is True

    response = review(client, actors, fdr["id"], "ACCEPTED", remarks="Accepted after bank confirmation",
                      internal="Second officer confirmed against branch ledger")
    assert response.status_code == 200
    assert response.json()["status"] == "ACCEPTED"

    # Accepted is final for now: no further review or assignment.
    assert review(client, actors, fdr["id"], "REJECTED", remarks="Changing my mind").status_code == 409
    assert assign(client, actors, fdr["id"], actors.user["bank"].id).status_code == 409


def test_review_decisions_are_separate_and_preserved(client, actors, fdr, assigned, db):
    submit(client, actors.headers["bank"], assigned["id"], assigned["version"])
    review(client, actors, fdr["id"], "ACCEPTED", remarks="Accepted", internal="Internal: ledger ref matched")

    data = history(client, actors, fdr["id"])
    decision = data["decisions"][0]
    assert decision["previous_status"] == "UNDER_REVIEW" and decision["new_status"] == "ACCEPTED"
    assert decision["internal_notes"] == "Internal: ledger ref matched"
    assert decision["reviewed_outcome_id"] == data["assignments"][0]["outcome"]["id"]
    assert decision["decided_by"]["id"] == actors.user["aicte"].id
    # The bank outcome is untouched by the AICTE decision.
    assert data["assignments"][0]["outcome"]["outcome"] == "CONFIRMED_AGAINST_BANK_RECORDS"
    # Internal notes never reach the shared audit trail.
    status_entry = db.scalar(select(AuditLog).where(AuditLog.action == "FDR_STATUS_CHANGED"))
    assert "Internal" not in str(status_entry.changes)


def test_review_permissions(client, actors, fdr, assigned):
    version = get_fdr(client, actors, fdr["id"])["version"]
    body = {"version": version, "status": "REJECTED", "review_remarks": "Not allowed"}
    assert client.post(f"/api/fdrs/{fdr['id']}/review", json=body, headers=actors.headers["bank"]).status_code == 403
    assert client.post(f"/api/fdrs/{fdr['id']}/review", json=body, headers=actors.headers["inst_a"]).status_code == 403
    assert client.get(f"/api/fdrs/{fdr['id']}/verification", headers=actors.headers["inst_a"]).status_code == 403


def test_clarification_cancels_assignment_and_allows_new_round(client, actors, fdr, assigned, db):
    assert review(client, actors, fdr["id"], "CLARIFICATION_REQUESTED", remarks="Please re-upload the FDR copy").status_code == 200
    data = history(client, actors, fdr["id"])
    assert data["assignments"][0]["status"] == "CANCELLED"
    assert "returned to the institution" in data["assignments"][0]["end_reason"]
    assert data["active_assignment"] is None
    # The officer can no longer act on it.
    assert submit(client, actors.headers["bank"], assigned["id"], assigned["version"]).status_code == 409
    assert client.get(f"/api/fdrs/{fdr['id']}/documents", headers=actors.headers["bank"]).status_code == 403

    # Institution corrects, AICTE assigns again; both rounds remain in the history.
    current = get_fdr(client, actors, fdr["id"], who="inst_a")
    client.patch(f"/api/fdrs/{fdr['id']}", json={"version": current["version"], "branch_name": "Corrected"}, headers=actors.headers["inst_a"])
    assert assign(client, actors, fdr["id"], actors.user["bank"].id).status_code == 201
    assert [a["status"] for a in history(client, actors, fdr["id"])["assignments"]] == ["ACTIVE", "CANCELLED"]
    assert "VERIFICATION_CANCELLED" in actions(db, fdr["id"])


def test_rejection_cancels_active_assignment(client, actors, fdr, assigned):
    assert review(client, actors, fdr["id"], "REJECTED", remarks="Rejected for test").status_code == 200
    assert history(client, actors, fdr["id"])["assignments"][0]["status"] == "CANCELLED"


# ---------- institution view ----------


def test_institution_sees_status_but_not_internal_details(client, actors, fdr, db):
    inst = actors.headers["inst_a"]
    assert get_fdr(client, actors, fdr["id"], who="inst_a")["verification_state"] == "NOT_ASSIGNED"
    assignment = assign(client, actors, fdr["id"], actors.user["bank"].id, note="Secret instruction to the bank").json()
    doc = upload(client, inst, fdr["id"], PDF_BYTES).json()
    client.get(f"/api/fdrs/{fdr['id']}/documents/{doc['id']}/download", headers=actors.headers["bank"])
    assert get_fdr(client, actors, fdr["id"], who="inst_a")["verification_state"] == "IN_PROGRESS"
    submit(client, actors.headers["bank"], assignment["id"], assignment["version"], outcome="DETAILS_MISMATCH",
           notes="Amount in the ledger differs from the submitted amount.")
    review(client, actors, fdr["id"], "CLARIFICATION_REQUESTED", remarks="Please confirm the deposit amount",
           internal="Bank reported an amount mismatch")

    detail = client.get(f"/api/fdrs/{fdr['id']}", headers=inst).json()
    assert detail["status"] == "CLARIFICATION_REQUESTED"
    assert detail["review_remarks"] == "Please confirm the deposit amount"
    text_of = client.get(f"/api/fdrs/{fdr['id']}/history", headers=inst).text + str(detail)
    for secret in ("Secret instruction", "amount mismatch", "DETAILS_MISMATCH", "Amount in the ledger",
                   actors.user["bank"].full_name, "VERIFICATION_"):
        assert secret not in text_of, secret

    # AICTE sees everything.
    aicte_history = client.get(f"/api/fdrs/{fdr['id']}/history", headers=actors.headers["aicte"]).json()
    assert {"VERIFICATION_ASSIGNED", "VERIFICATION_OUTCOME_SUBMITTED", "FDR_STATUS_CHANGED"} <= {h["action"] for h in aicte_history}


# ---------- queue, audit and evidence protection ----------


def test_aicte_queue_and_officer_list(client, actors, fdr, create_fdr, assigned, officer2):
    other = create_fdr(actors.headers["inst_b"], fdr_number="VER-B-3")
    second = assign(client, actors, other["id"], officer2[0].id).json()
    submit(client, officer2[1], second["id"], second["version"])
    aicte = actors.headers["aicte"]

    officers = client.get("/api/verification/officers", headers=aicte).json()
    assert {o["id"] for o in officers} == {actors.user["bank"].id, officer2[0].id}
    everything = client.get("/api/verification/assignments", headers=aicte).json()
    assert everything["total"] == 2
    active = client.get("/api/verification/assignments", params={"status": "ACTIVE"}, headers=aicte).json()
    assert [a["id"] for a in active["items"]] == [assigned["id"]]
    completed = client.get("/api/verification/assignments", params={"status": "COMPLETED"}, headers=aicte).json()
    assert completed["items"][0]["outcome"] == "CONFIRMED_AGAINST_BANK_RECORDS"


def test_full_audit_trail(client, actors, fdr, assigned, officer2, db):
    moved = client.post(
        f"/api/verification/assignments/{assigned['id']}/reassign",
        json={"bank_officer_id": officer2[0].id, "version": assigned["version"], "reason": "Workload balancing"},
        headers=actors.headers["aicte"],
    ).json()
    submit(client, officer2[1], moved["id"], moved["version"])
    review(client, actors, fdr["id"], "ACCEPTED", remarks="Accepted")
    trail = [a for a in actions(db, fdr["id"]) if a != "FDR_CREATED"]
    assert trail == ["VERIFICATION_ASSIGNED", "VERIFICATION_REASSIGNED", "VERIFICATION_OUTCOME_SUBMITTED", "FDR_STATUS_CHANGED"]
    reassigned = db.scalar(select(AuditLog).where(AuditLog.action == "VERIFICATION_REASSIGNED"))
    assert reassigned.changes["reason"] == "Workload balancing"
    assert reassigned.changes["previous_assignment_id"] == assigned["id"]
    assert db.scalar(select(ReviewDecision.id)) is not None


def test_history_tables_cannot_be_rewritten(client, actors, fdr, assigned, db):
    submit(client, actors.headers["bank"], assigned["id"], assigned["version"])
    review(client, actors, fdr["id"], "ACCEPTED", remarks="Accepted")
    for statement in (
        "UPDATE verification_outcomes SET outcome = 'DETAILS_MISMATCH'",
        "DELETE FROM verification_outcomes",
        "UPDATE review_decisions SET internal_notes = 'edited'",
        "DELETE FROM review_decisions",
        "UPDATE verification_assignments SET status = 'ACTIVE'",
        "UPDATE verification_assignments SET bank_officer_id = 1",
        "DELETE FROM verification_assignments",
    ):
        with pytest.raises(DatabaseError):
            db.execute(text(statement))
        db.rollback()


def test_active_assignment_officer_cannot_be_swapped_in_database(actors, assigned, db):
    with pytest.raises(DatabaseError, match="immutable"):
        db.execute(text("UPDATE verification_assignments SET bank_officer_id = :id"), {"id": actors.user["aicte"].id})
    db.rollback()


# ---------- documents still protected after assignments exist ----------


def test_document_download_and_integrity_after_assignment(client, actors, fdr, db):
    doc = upload(client, actors.headers["inst_a"], fdr["id"], PDF_BYTES).json()
    assignment = assign(client, actors, fdr["id"], actors.user["bank"].id).json()
    base = f"/api/fdrs/{fdr['id']}/documents/{doc['id']}"

    assert client.get(f"{base}/download", headers=actors.headers["inst_a"]).content == PDF_BYTES
    assert client.get(f"{base}/download", headers=actors.headers["aicte"]).content == PDF_BYTES
    report = client.post(f"{base}/integrity-check", headers=actors.headers["aicte"]).json()
    assert report["status"] == "intact"
    assert client.post(f"{base}/integrity-check", headers=actors.headers["bank"]).status_code == 403
    assert client.get(f"{base}/download", headers=actors.headers["inst_b"]).status_code == 404

    # Tampering still blocks the assigned officer's download.
    key = db.scalar(select(text("storage_key")).select_from(text("fdr_documents")))
    document_storage._path_for(key).write_bytes(PDF_BYTES.replace(b"Catalog", b"Katalog"))
    assert client.get(f"{base}/download", headers=actors.headers["bank"]).status_code == 409
    assert submit(client, actors.headers["bank"], assignment["id"], assignment["version"],
                  evidence_document_ids=[doc["id"]]).status_code == 201
