"""AICTE college search, the AICTE accept/reject decision and the bank officer case list."""

from sqlalchemy import select

from app.models import AuditLog, ReviewDecision
from tests.test_verification import NOTES, assign, review, submit


def search(client, actors, who="aicte", **params):
    return client.get("/api/institutions/search", params=params, headers=actors.headers[who])


def test_college_search_is_aicte_only(client, actors):
    for who in ("inst_a", "bank"):
        assert search(client, actors, who).status_code == 403, who
        assert client.get(f"/api/institutions/{actors.institution_a.id}", headers=actors.headers[who]).status_code == 403
    assert client.get("/api/institutions/search").status_code == 401
    assert search(client, actors).status_code == 200


def test_college_search_by_name_with_counts(client, actors, create_fdr, make_institution):
    make_institution(name="Gamma Empty Polytechnic")
    a = actors.headers["inst_a"]
    create_fdr(a, fdr_number="COL-1")
    rejected = create_fdr(a, fdr_number="COL-2")
    create_fdr(actors.headers["inst_b"], fdr_number="COL-3")
    assert review(client, actors, rejected["id"], "REJECTED", remarks="Receipt is illegible").status_code == 200

    everyone = search(client, actors).json()
    assert everyone["total"] == 3
    assert [item["name"] for item in everyone["items"]] == ["Alpha Test Institute", "Beta Test College", "Gamma Empty Polytechnic"]

    alpha = search(client, actors, q="alpha").json()
    assert alpha["total"] == 1
    item = alpha["items"][0]
    assert item["id"] == actors.institution_a.id
    assert (item["fdr_total"], item["fdrs_open_review"], item["fdrs_rejected"], item["fdrs_accepted"]) == (2, 1, 1, 0)
    assert item["latest_submission_at"] is not None

    gamma = search(client, actors, q="POLYTECH").json()["items"][0]
    assert gamma["fdr_total"] == 0 and gamma["latest_submission_at"] is None

    # Code search, LIKE wildcards treated literally, no match, and paging.
    assert search(client, actors, q=actors.institution_b.code).json()["total"] == 1
    assert search(client, actors, q="%").json()["total"] == 0
    assert search(client, actors, q="no such college").json() == {"items": [], "total": 0, "page": 1, "page_size": 20, "pages": 0}
    paged = search(client, actors, page_size=2, page=2).json()
    assert paged["pages"] == 2 and len(paged["items"]) == 1


def test_get_college(client, actors, create_fdr):
    create_fdr(actors.headers["inst_b"])
    response = client.get(f"/api/institutions/{actors.institution_b.id}", headers=actors.headers["aicte"])
    assert response.status_code == 200
    assert response.json()["fdr_total"] == 1 and response.json()["name"] == "Beta Test College"
    assert client.get("/api/institutions/99999", headers=actors.headers["aicte"]).status_code == 404


def test_college_fdr_listing_is_scoped_for_institutions(client, actors, create_fdr):
    create_fdr(actors.headers["inst_a"], fdr_number="SCOPE-A")
    create_fdr(actors.headers["inst_b"], fdr_number="SCOPE-B")
    aicte = client.get("/api/fdrs", params={"institution_id": actors.institution_b.id}, headers=actors.headers["aicte"]).json()
    assert [item["fdr_number"] for item in aicte["items"]] == ["SCOPE-B"]
    # An institution asking for another college's records still sees only its own.
    own = client.get("/api/fdrs", params={"institution_id": actors.institution_b.id}, headers=actors.headers["inst_a"]).json()
    assert [item["fdr_number"] for item in own["items"]] == ["SCOPE-A"]


def test_rejection_is_recorded_with_reviewer_reason_and_time(client, actors, create_fdr, db):
    fdr = create_fdr(actors.headers["inst_a"])
    blank = client.post(f"/api/fdrs/{fdr['id']}/review", json={"version": 1, "status": "REJECTED", "review_remarks": "   "},
                        headers=actors.headers["aicte"])
    assert blank.status_code == 422

    response = review(client, actors, fdr["id"], "REJECTED", remarks="FDR copy does not match the entered amount")
    assert response.status_code == 200 and response.json()["status"] == "REJECTED"
    assert client.get(f"/api/fdrs/{fdr['id']}", headers=actors.headers["aicte"]).json()["status"] == "REJECTED"

    decision = db.scalar(select(ReviewDecision).where(ReviewDecision.fdr_id == fdr["id"]))
    assert decision.decided_by_id == actors.user["aicte"].id and decision.decided_at is not None
    assert decision.message_to_institution == "FDR copy does not match the entered amount"
    entry = db.scalar(select(AuditLog).where(AuditLog.action == "FDR_STATUS_CHANGED", AuditLog.entity_id == fdr["id"]))
    assert entry.actor_user_id == actors.user["aicte"].id and entry.actor_role == "AICTE_OFFICIAL" and entry.created_at is not None
    assert entry.changes["status"] == {"old": "SUBMITTED", "new": "REJECTED"}
    assert entry.changes["review_remarks"] == "FDR copy does not match the entered amount"

    # Repeating the same decision (same version) is refused, and a rejected record is final.
    again = client.post(f"/api/fdrs/{fdr['id']}/review",
                        json={"version": 1, "status": "REJECTED", "review_remarks": "Again"}, headers=actors.headers["aicte"])
    assert again.status_code == 409
    latest = review(client, actors, fdr["id"], "REJECTED", remarks="Again")
    assert latest.status_code == 409
    assert db.query(ReviewDecision).filter_by(fdr_id=fdr["id"]).count() == 1


def test_duplicate_flag_does_not_decide_and_bank_outcome_does_not_accept(client, actors, create_fdr, db):
    create_fdr(actors.headers["inst_b"], fdr_number="DUP-777")
    fdr = create_fdr(actors.headers["inst_a"], fdr_number="dup 777")
    detail = client.get(f"/api/fdrs/{fdr['id']}", headers=actors.headers["aicte"]).json()
    assert detail["possible_duplicate"] is True and detail["status"] == "SUBMITTED"

    assignment = assign(client, actors, fdr["id"], actors.user["bank"].id).json()
    submit(client, actors.headers["bank"], assignment["id"], assignment["version"], notes=NOTES)
    # The confirmed outcome leaves the decision to AICTE.
    after = client.get(f"/api/fdrs/{fdr['id']}", headers=actors.headers["aicte"]).json()
    assert after["status"] == "UNDER_REVIEW"
    assert db.query(ReviewDecision).filter_by(fdr_id=fdr["id"]).count() == 0
    # AICTE can still accept a flagged record once it has reviewed the evidence.
    accepted = review(client, actors, fdr["id"], "ACCEPTED", remarks="Different FDR; references only look alike")
    assert accepted.status_code == 200 and accepted.json()["status"] == "ACCEPTED"


def test_bank_officer_cannot_decide(client, actors, create_fdr):
    fdr = create_fdr(actors.headers["inst_a"])
    assignment = assign(client, actors, fdr["id"], actors.user["bank"].id).json()
    submit(client, actors.headers["bank"], assignment["id"], assignment["version"])
    version = client.get(f"/api/fdrs/{fdr['id']}", headers=actors.headers["aicte"]).json()["version"]
    for status in ("ACCEPTED", "REJECTED"):
        body = {"version": version, "status": status, "review_remarks": "Bank says fine"}
        assert client.post(f"/api/fdrs/{fdr['id']}/review", json=body, headers=actors.headers["bank"]).status_code == 403


def test_case_list_shows_amount_only_while_open(client, actors, create_fdr):
    fdr = create_fdr(actors.headers["inst_a"], amount="345000.00")
    assignment = assign(client, actors, fdr["id"], actors.user["bank"].id).json()
    bank = actors.headers["bank"]
    open_case = client.get("/api/verification/cases", headers=bank).json()["items"][0]
    assert open_case["amount"] == "345000.00" and open_case["maturity_date"] == fdr["maturity_date"]

    submit(client, bank, assignment["id"], assignment["version"])
    closed = client.get("/api/verification/cases", params={"state": "closed"}, headers=bank).json()["items"][0]
    assert closed["status"] == "COMPLETED" and closed["amount"] is None and closed["maturity_date"] is None
