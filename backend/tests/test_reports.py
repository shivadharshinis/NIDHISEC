"""AICTE reports snapshot and audit-log filters used by the Audit Log page."""

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select

from app.models import FDR, AuditLog
from app.models.lifecycle import LifecycleRequest
from tests.test_lifecycle import REASON, accept, iso, successor


def report(client, actors, who="aicte"):
    return client.get("/api/reports/summary", headers=actors.headers[who])


def test_reports_are_aicte_only(client, actors):
    for who in ("inst_a", "inst_b", "bank"):
        response = report(client, actors, who)
        assert response.status_code == 403, who
    assert client.get("/api/reports/summary").status_code == 401
    assert report(client, actors).status_code == 200


def test_report_counts_match_records(client, actors, create_fdr, make_institution, db):
    empty_institution = make_institution(name="Gamma Test Polytechnic")
    a, b = actors.headers["inst_a"], actors.headers["inst_b"]
    overdue = create_fdr(a, fdr_number="REP-OVERDUE", amount="1000.00", issue_date=iso(-400), maturity_date=iso(-5))
    create_fdr(a, fdr_number="REP-DUE-10", amount="2000.00", issue_date=iso(-300), maturity_date=iso(10))
    create_fdr(a, fdr_number="REP-DUE-60", amount="3000.00", issue_date=iso(-300), maturity_date=iso(60))
    create_fdr(b, fdr_number="REP-DUE-200", amount="4000.00", issue_date=iso(-100), maturity_date=iso(200))
    create_fdr(b, fdr_number="REP-LATER", amount="5000.00", issue_date=iso(-10), maturity_date=iso(900))
    rejected = create_fdr(b, fdr_number="REP-REJ", amount="99999.00", issue_date=iso(-300), maturity_date=iso(5))
    client.post(f"/api/fdrs/{rejected['id']}/review", json={"version": 1, "status": "REJECTED", "review_remarks": "SECRET-REJECTION-NOTE"},
                headers=actors.headers["aicte"])
    # One accepted instrument with a release request (matured) and its decision.
    matured = accept(client, actors, overdue["id"])
    release = client.post(f"/api/fdrs/{matured['id']}/lifecycle-requests",
                          json={"request_type": "RELEASE", "fdr_version": matured["version"], "reason": REASON}, headers=a).json()
    renew_target = accept(client, actors, create_fdr(a, fdr_number="REP-RENEW", amount="6000.00",
                                                       issue_date=iso(-335), maturity_date=iso(20))["id"])
    client.post(f"/api/fdrs/{renew_target['id']}/lifecycle-requests",
                json={"request_type": "RENEWAL", "fdr_version": renew_target["version"], "reason": REASON,
                      "successor": successor(fdr_number="REP-RENEW-NEW")}, headers=a)
    current = client.get(f"/api/lifecycle-requests/{release['id']}", headers=actors.headers["aicte"]).json()
    client.post(f"/api/lifecycle-requests/{release['id']}/transitions",
                json={"action": "REJECT", "version": current["version"], "message": "Not eligible yet in this test",
                      "internal_note": "SECRET-INTERNAL-NOTE"}, headers=actors.headers["aicte"])

    body = report(client, actors).json()
    today = date.today()

    # FDR totals match the database.
    assert body["fdr_total"] == db.scalar(select(func.count()).select_from(FDR))
    by_status = dict(db.execute(select(FDR.status, func.count()).group_by(FDR.status)).all())
    assert body["fdr_by_status"] == {k.value: v for k, v in by_status.items()}
    assert body["fdr_by_lifecycle"] == {"ACTIVE": 7, "PROPOSED": 1}
    assert body["as_of"] == today.isoformat()

    # Lifecycle requests by type and current status.
    pairs = {(r["request_type"], r["status"]): r["count"] for r in body["lifecycle_requests"]}
    assert pairs == {("RELEASE", "REJECTED"): 1, ("RENEWAL", "SUBMITTED"): 1}
    assert sum(pairs.values()) == db.scalar(select(func.count()).select_from(LifecycleRequest))

    # Maturity buckets: active, non-rejected instruments only; rejected REP-REJ and the proposed successor excluded.
    buckets = {m["bucket"]: (m["count"], m["total_amount"]) for m in body["maturity"]}
    assert buckets == {
        "OVERDUE": (1, "1000.00"),
        "DUE_0_30": (2, "8000.00"),     # REP-DUE-10 + REP-RENEW
        "DUE_31_90": (1, "3000.00"),
        "DUE_91_365": (1, "4000.00"),
        "LATER": (1, "5000.00"),
    }
    assert body["monitored_total"] == 6

    # Institution-wise rows, including an institution with no FDRs.
    rows = {r["institution"]["code"]: r for r in body["institutions"]}
    assert set(rows) == {actors.institution_a.code, actors.institution_b.code, empty_institution.code}
    inst_a = rows[actors.institution_a.code]
    assert inst_a["total_fdrs"] == 4 + 1  # four submitted directly plus the proposed renewal successor
    assert inst_a["by_status"]["ACCEPTED"] == 2
    assert (inst_a["active_instruments"], Decimal(inst_a["active_amount"])) == (4, Decimal("12000.00"))
    assert (inst_a["maturing_within_30_days"], inst_a["overdue_active"], inst_a["open_lifecycle_requests"]) == (2, 1, 1)
    inst_b = rows[actors.institution_b.code]
    assert (inst_b["total_fdrs"], inst_b["by_status"]["REJECTED"], inst_b["active_instruments"]) == (3, 1, 2)
    assert rows[empty_institution.code]["total_fdrs"] == 0 and rows[empty_institution.code]["active_amount"] == "0.00"

    # Only counts and amounts: no remarks, internal notes or record content.
    text = report(client, actors).text
    for secret in ("SECRET-INTERNAL-NOTE", "SECRET-REJECTION-NOTE", "REP-OVERDUE", REASON):
        assert secret not in text


def test_report_reads_nothing_into_records(client, actors, create_fdr, db):
    create_fdr(actors.headers["inst_a"], fdr_number="REP-RO")
    audit_before = db.scalar(select(func.count()).select_from(AuditLog))
    report(client, actors)
    report(client, actors)
    assert db.scalar(select(func.count()).select_from(AuditLog)) == audit_before


# ---------- audit-log filters exposed on the Audit Log page ----------


def test_audit_log_filters(client, actors, create_fdr, db):
    first = create_fdr(actors.headers["inst_a"], fdr_number="AUD-1")
    create_fdr(actors.headers["inst_b"], fdr_number="AUD-2")
    aicte = actors.headers["aicte"]

    def query(**params):
        response = client.get("/api/audit-logs", params=params, headers=aicte)
        assert response.status_code == 200, response.text
        return response.json()

    by_record = query(entity_type="fdr", entity_id=first["id"])
    assert by_record["total"] == 1 and by_record["items"][0]["entity_id"] == first["id"]

    email = actors.user["inst_a"].email
    by_actor = query(actor_email=email.upper())  # exact match, case-insensitive
    assert by_actor["total"] >= 2 and {i["actor_email"] for i in by_actor["items"]} == {email}
    assert query(actor_email=email[:5])["total"] == 0  # not a substring search

    today = date.today()
    assert query(date_from=today.isoformat(), date_to=today.isoformat())["total"] == db.scalar(select(func.count()).select_from(AuditLog))
    assert query(date_to=(today - timedelta(days=2)).isoformat())["total"] == 0
    assert query(date_from=(today + timedelta(days=2)).isoformat())["total"] == 0
    assert query(entity_type="user", action="LOGIN_SUCCEEDED")["total"] == 4

    combined = query(entity_type="fdr", actor_email=actors.user["inst_b"].email, date_from=today.isoformat())
    assert [i["summary"] for i in combined["items"]] == ["FDR AUD-2 (Test Demo Bank) submitted"]
    paged = query(page_size=2, page=1)
    assert len(paged["items"]) == 2 and paged["items"][0]["id"] > paged["items"][1]["id"]  # newest first
    assert client.get("/api/audit-logs", params={"entity_id": "abc"}, headers=aicte).status_code == 422
    assert client.get("/api/audit-logs", params={"date_from": "2026-13-40"}, headers=aicte).status_code == 422
