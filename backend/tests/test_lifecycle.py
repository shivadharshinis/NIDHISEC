"""Lifecycle: maturity alerts, notifications, renewal/replacement/release workflows and dashboards."""

from datetime import date, timedelta

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DatabaseError, IntegrityError

from app.models import FDR, AuditLog, FDRStatus, LifecycleStatus, UserRole
from app.models.lifecycle import LifecycleRequest, Notification
from app.services import lifecycle as lifecycle_service
from app.services import notifications as notification_service
from tests.conftest import fdr_payload, login
from tests.test_documents import PDF_BYTES, upload

TODAY = date.today()
REASON = "The deposit must remain in place for the next academic cycle."


def iso(days: int) -> str:
    return (TODAY + timedelta(days=days)).isoformat()


def accept(client, actors, fdr_id):
    """Take an FDR through the real workflow to ACCEPTED: assign, confirmed outcome, AICTE decision."""
    aicte = actors.headers["aicte"]
    version = client.get(f"/api/fdrs/{fdr_id}", headers=aicte).json()["version"]
    assignment = client.post(f"/api/fdrs/{fdr_id}/verification/assignments",
                             json={"bank_officer_id": actors.user["bank"].id, "fdr_version": version}, headers=aicte).json()
    client.post(f"/api/verification/cases/{assignment['id']}/outcome",
                json={"version": assignment["version"], "outcome": "CONFIRMED_AGAINST_BANK_RECORDS",
                      "notes": "Matches the branch deposit ledger exactly."}, headers=actors.headers["bank"])
    version = client.get(f"/api/fdrs/{fdr_id}", headers=aicte).json()["version"]
    response = client.post(f"/api/fdrs/{fdr_id}/review", json={"version": version, "status": "ACCEPTED"}, headers=aicte)
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture
def accepted(client, actors, create_fdr):
    """An accepted FDR of institution A maturing in 30 days (inside the renewal window)."""
    fdr = create_fdr(actors.headers["inst_a"], fdr_number="LC-1001", issue_date=iso(-335), maturity_date=iso(30))
    return accept(client, actors, fdr["id"])


@pytest.fixture
def matured(client, actors, create_fdr):
    fdr = create_fdr(actors.headers["inst_a"], fdr_number="LC-2002", issue_date=iso(-400), maturity_date=iso(-1))
    return accept(client, actors, fdr["id"])


def successor(**overrides):
    payload = fdr_payload(fdr_number="LC-NEW-1", issue_date=iso(0), maturity_date=iso(400))
    payload.update(overrides)
    return payload


def submit(client, actors, fdr, request_type="RENEWAL", who="inst_a", **extra):
    body = {"request_type": request_type, "fdr_version": fdr["version"], "reason": REASON}
    if request_type != "RELEASE":
        body["successor"] = successor()
    body.update(extra)
    return client.post(f"/api/fdrs/{fdr['id']}/lifecycle-requests", json=body, headers=actors.headers[who])


def act(client, actors, req, action, who="aicte", **extra):
    current = client.get(f"/api/lifecycle-requests/{req['id']}", headers=actors.headers[who]).json()
    body = {"action": action, "version": current["version"], **extra}
    return client.post(f"/api/lifecycle-requests/{req['id']}/transitions", json=body, headers=actors.headers[who])


def notifications_for(db, user):
    return db.scalars(select(Notification).where(Notification.recipient_id == user.id).order_by(Notification.id)).all()


# ---------- maturity windows ----------


@pytest.mark.parametrize(("days", "state", "window"), [
    (31, "NOT_DUE", None), (30, "DUE", 30), (16, "DUE", 30), (15, "DUE", 15), (8, "DUE", 15),
    (7, "DUE", 7), (1, "DUE", 7), (0, "DUE", 7), (-1, "MATURED", None), (-400, "MATURED", None),
])
def test_maturity_window_boundaries(days, state, window):
    result = lifecycle_service.maturity_state(TODAY + timedelta(days=days), TODAY, [7, 15, 30])
    assert (result.state, result.window, result.days_remaining) == (state, window, days)


def test_alert_window_configuration_is_parsed_safely(monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "maturity_alert_days", "30, 15,abc,7,7,-3")
    assert get_settings().maturity_alert_windows == [7, 15, 30]


def test_lifecycle_check_is_idempotent_and_follows_windows(client, actors, create_fdr, db):
    due = create_fdr(actors.headers["inst_a"], fdr_number="MAT-10", issue_date=iso(-300), maturity_date=iso(10))
    past = create_fdr(actors.headers["inst_a"], fdr_number="MAT-PAST", issue_date=iso(-300), maturity_date=iso(-3))
    create_fdr(actors.headers["inst_a"], fdr_number="MAT-FAR", issue_date=iso(-10), maturity_date=iso(200))
    other = create_fdr(actors.headers["inst_b"], fdr_number="MAT-B", issue_date=iso(-300), maturity_date=iso(12))
    before = {f.id: (f.status, f.version, f.lifecycle_status) for f in db.scalars(select(FDR)).all()}

    first = lifecycle_service.run_lifecycle_check(db, actors.user["aicte"], today=TODAY)
    assert (first["due"], first["matured"]) == (2, 1)
    second = lifecycle_service.run_lifecycle_check(db, actors.user["aicte"], today=TODAY)
    assert second["notifications_created"] == 0  # nothing duplicated

    inst_a = [(n.event_type, n.fdr_id) for n in notifications_for(db, actors.user["inst_a"])]
    assert sorted(inst_a) == sorted([("MATURITY_DUE", due["id"]), ("MATURITY_PASSED", past["id"])])
    assert [n.fdr_id for n in notifications_for(db, actors.user["inst_b"])] == [other["id"]]
    # AICTE is only alerted for the 7-day window and for matured instruments.
    assert [(n.event_type, n.fdr_id) for n in notifications_for(db, actors.user["aicte"])] == [("MATURITY_PASSED", past["id"])]

    # Moving into the 7-day window is a new event: one new alert per recipient, no repeats of old ones.
    # Four days later MAT-10 is 6 days out (7-day window): new alerts for institution A and AICTE.
    # MAT-B is 8 days out, still in its 15-day window, so institution B gets nothing new.
    later = lifecycle_service.run_lifecycle_check(db, actors.user["aicte"], today=TODAY + timedelta(days=4))
    assert later["notifications_created"] == 2
    assert len(notifications_for(db, actors.user["inst_a"])) == 3
    assert len(notifications_for(db, actors.user["inst_b"])) == 1
    assert [n.dedup_key.rsplit(":", 1)[1] for n in notifications_for(db, actors.user["aicte"])] == ["matured", "7"]
    # The check never changes any FDR.
    db.expire_all()
    assert {f.id: (f.status, f.version, f.lifecycle_status) for f in db.scalars(select(FDR)).all()} == before


def test_new_maturity_date_produces_new_alert(client, actors, create_fdr, db):
    fdr = create_fdr(actors.headers["inst_a"], fdr_number="MAT-EDIT", issue_date=iso(-300), maturity_date=iso(10))
    lifecycle_service.run_lifecycle_check(db, None, today=TODAY)
    client.patch(f"/api/fdrs/{fdr['id']}", json={"version": 1, "maturity_date": iso(5)}, headers=actors.headers["inst_a"])
    assert lifecycle_service.run_lifecycle_check(db, None, today=TODAY)["notifications_created"] >= 1
    keys = [n.dedup_key for n in notifications_for(db, actors.user["inst_a"])]
    assert len(keys) == 2 and len(set(keys)) == 2
    assert db.scalar(select(AuditLog).where(AuditLog.action == "LIFECYCLE_CHECK_RUN")).actor_email == "system:lifecycle-check"


def test_released_and_rejected_instruments_are_not_monitored(client, actors, create_fdr, db):
    fdr = create_fdr(actors.headers["inst_a"], fdr_number="MAT-REJ", issue_date=iso(-300), maturity_date=iso(5))
    client.post(f"/api/fdrs/{fdr['id']}/review", json={"version": 1, "status": "REJECTED", "review_remarks": "Rejected test"},
                headers=actors.headers["aicte"])
    assert lifecycle_service.run_lifecycle_check(db, None, today=TODAY)["checked"] == 0


def test_maturity_endpoint_scoping(client, actors, create_fdr, db):
    create_fdr(actors.headers["inst_a"], fdr_number="MAT-A", issue_date=iso(-300), maturity_date=iso(10))
    create_fdr(actors.headers["inst_b"], fdr_number="MAT-B", issue_date=iso(-300), maturity_date=iso(-2))
    own = client.get("/api/lifecycle/maturity", headers=actors.headers["inst_a"]).json()
    assert [(i["fdr_number"], i["days_remaining"], i["state"], i["alert_window"]) for i in own["items"]] == [("MAT-A", 10, "DUE", 15)]
    everything = client.get("/api/lifecycle/maturity", headers=actors.headers["aicte"]).json()
    assert [i["fdr_number"] for i in everything["items"]] == ["MAT-B", "MAT-A"]
    assert client.get("/api/lifecycle/maturity", params={"include_overdue": False},
                      headers=actors.headers["aicte"]).json()["total"] == 1
    assert client.post("/api/lifecycle/check", headers=actors.headers["inst_a"]).status_code == 403
    assert client.post("/api/lifecycle/check", headers=actors.headers["aicte"]).json()["due"] == 1


# ---------- notifications ----------


def test_notification_dedup_and_link_safety(actors, db):
    users = [actors.user["inst_a"], actors.user["inst_a"]]
    assert notification_service.notify(db, users, event_type="X", title="t", body="b", dedup_key="k1", link="/x") == 1
    assert notification_service.notify(db, users, event_type="X", title="t", body="b", dedup_key="k1", link="/x") == 0
    db.commit()
    assert db.scalar(select(func.count()).select_from(Notification)) == 1
    for bad in ("https://evil.example", "//evil.example", "javascript:alert(1)"):
        with pytest.raises(ValueError):
            notification_service.notify(db, users, event_type="X", title="t", body="b", dedup_key="k2", link=bad)
    with pytest.raises(IntegrityError):
        db.add(Notification(recipient_id=actors.user["inst_a"].id, event_type="X", title="t", body="b", dedup_key="k1"))
        db.flush()
    db.rollback()


def test_notification_read_state_and_isolation(client, actors, db):
    for key in ("a", "b", "c"):
        notification_service.notify(db, [actors.user["inst_a"]], event_type="X", title=key, body="b", dedup_key=key)
    notification_service.notify(db, [actors.user["inst_b"]], event_type="X", title="theirs", body="b", dedup_key="z")
    db.commit()
    mine = client.get("/api/notifications", headers=actors.headers["inst_a"]).json()
    assert [n["title"] for n in mine["items"]] == ["c", "b", "a"]
    theirs = db.scalar(select(Notification).where(Notification.recipient_id == actors.user["inst_b"].id))

    assert client.post(f"/api/notifications/{theirs.id}/read", headers=actors.headers["inst_a"]).status_code == 404
    first = mine["items"][0]["id"]
    assert client.post(f"/api/notifications/{first}/read", headers=actors.headers["inst_a"]).json()["read_at"]
    assert client.get("/api/notifications/unread-count", headers=actors.headers["inst_a"]).json() == {"unread": 2}
    assert client.post("/api/notifications/read-all", headers=actors.headers["inst_a"]).json() == {"marked": 2}
    assert client.get("/api/notifications/unread-count", headers=actors.headers["inst_b"]).json() == {"unread": 1}
    assert client.get("/api/notifications", params={"unread_only": True}, headers=actors.headers["inst_a"]).json()["total"] == 0
    assert client.get("/api/notifications").status_code == 401
    with pytest.raises(DatabaseError, match="immutable"):
        db.execute(text("UPDATE notifications SET title = 'changed'"))
    db.rollback()
    with pytest.raises(DatabaseError):
        db.execute(text("DELETE FROM notifications"))
    db.rollback()


def test_workflow_events_notify_the_right_people(client, actors, create_fdr, make_user, db):
    officer2 = make_user(UserRole.BANK_OFFICER)
    fdr = create_fdr(actors.headers["inst_a"], fdr_number="NOTE-1")
    aicte = actors.headers["aicte"]
    assignment = client.post(f"/api/fdrs/{fdr['id']}/verification/assignments",
                             json={"bank_officer_id": actors.user["bank"].id, "fdr_version": 1}, headers=aicte).json()
    assert [n.event_type for n in notifications_for(db, actors.user["bank"])] == ["VERIFICATION_ASSIGNED"]
    moved = client.post(f"/api/verification/assignments/{assignment['id']}/reassign",
                        json={"bank_officer_id": officer2.id, "version": assignment["version"], "reason": "Balancing workload"},
                        headers=aicte).json()
    assert [n.event_type for n in notifications_for(db, actors.user["bank"])] == ["VERIFICATION_ASSIGNED", "VERIFICATION_REASSIGNED"]
    assert [n.link for n in notifications_for(db, officer2)] == [f"/verification/cases/{moved['id']}"]
    client.post(f"/api/verification/cases/{moved['id']}/outcome",
                json={"version": moved["version"], "outcome": "DETAILS_MISMATCH", "notes": "Amount differs in the ledger."},
                headers=login(client, officer2))
    assert [n.event_type for n in notifications_for(db, actors.user["aicte"])] == ["VERIFICATION_OUTCOME"]
    version = client.get(f"/api/fdrs/{fdr['id']}", headers=aicte).json()["version"]
    client.post(f"/api/fdrs/{fdr['id']}/review", json={"version": version, "status": "CLARIFICATION_REQUESTED",
                "review_remarks": "Please confirm the amount", "internal_notes": "SECRET-INTERNAL-NOTE"}, headers=aicte)
    inst = notifications_for(db, actors.user["inst_a"])
    assert [n.event_type for n in inst] == ["FDR_CLARIFICATION_REQUESTED"]
    everything = " ".join(n.title + n.body for n in db.scalars(select(Notification)).all())
    assert "SECRET-INTERNAL-NOTE" not in everything and "DETAILS_MISMATCH" not in everything
    assert not notifications_for(db, actors.user["inst_b"])


# ---------- renewal / replacement ----------


def test_eligibility_rules(client, actors, create_fdr, accepted):
    pending = create_fdr(actors.headers["inst_a"], fdr_number="LC-PENDING", issue_date=iso(-300), maturity_date=iso(30))
    response = submit(client, actors, pending, "RENEWAL")
    assert response.status_code == 409 and "accepted by AICTE" in response.json()["detail"]

    far = accept(client, actors, create_fdr(actors.headers["inst_a"], fdr_number="LC-FAR",
                                             issue_date=iso(-10), maturity_date=iso(200))["id"])
    assert "Renewal can be requested from" in submit(client, actors, far, "RENEWAL").json()["detail"]
    assert "matured" in submit(client, actors, far, "RELEASE").json()["detail"]
    assert submit(client, actors, far, "REPLACEMENT").status_code == 201  # replacement is not time-bound

    overview = client.get(f"/api/fdrs/{accepted['id']}/lifecycle", headers=actors.headers["inst_a"]).json()
    assert overview["eligibility"]["RENEWAL"]["allowed"] is True
    assert overview["eligibility"]["RELEASE"]["allowed"] is False
    assert overview["days_to_maturity"] == 30


def test_renewal_creates_linked_proposed_successor_without_touching_original(client, actors, accepted, db):
    original_before = client.get(f"/api/fdrs/{accepted['id']}", headers=actors.headers["aicte"]).json()
    response = submit(client, actors, accepted, "RENEWAL")
    assert response.status_code == 201, response.text
    req = response.json()
    assert req["status"] == "SUBMITTED" and req["fdr"]["id"] == accepted["id"]
    assert req["successor"]["lifecycle_status"] == "PROPOSED" and req["successor"]["status"] == "SUBMITTED"
    assert [e["action"] for e in req["events"]] == ["SUBMIT"]

    original_after = client.get(f"/api/fdrs/{accepted['id']}", headers=actors.headers["aicte"]).json()
    for key in ("fdr_number", "amount", "issue_date", "maturity_date", "status", "version", "lifecycle_status"):
        assert original_after[key] == original_before[key], key
    lifecycle = client.get(f"/api/fdrs/{req['successor']['id']}/lifecycle", headers=actors.headers["inst_a"]).json()
    assert lifecycle["proposed_by_request"]["id"] == req["id"]
    assert [n.event_type for n in notifications_for(db, actors.user["aicte"])][-1] == "LIFECYCLE_SUBMITTED"
    assert "LIFECYCLE_REQUEST_SUBMITTED" in {a.action for a in db.scalars(select(AuditLog)).all()}


def test_successor_validation(client, actors, accepted):
    bad_dates = submit(client, actors, accepted, "RENEWAL", successor=successor(maturity_date=iso(20)))
    assert bad_dates.status_code == 422
    assert bad_dates.json()["detail"][0]["loc"] == ["body", "successor", "maturity_date"]
    assert submit(client, actors, accepted, "RENEWAL", successor=successor(amount="-5")).status_code == 422
    assert submit(client, actors, accepted, "RENEWAL", successor=None).status_code == 422
    assert submit(client, actors, accepted, "RELEASE", successor=successor()).status_code == 422
    assert submit(client, actors, accepted, "RENEWAL", reason="too short").status_code == 422
    assert submit(client, actors, accepted, "RENEWAL", fdr_version=accepted["version"] + 3).status_code == 409


def test_only_one_open_request_per_fdr(client, actors, accepted, db):
    assert submit(client, actors, accepted, "RENEWAL").status_code == 201
    second = submit(client, actors, accepted, "REPLACEMENT", successor=successor(fdr_number="LC-NEW-2"))
    assert second.status_code == 409 and "already open" in second.json()["detail"]
    with pytest.raises(IntegrityError):
        db.execute(text(
            "INSERT INTO lifecycle_requests (request_type, fdr_id, institution_id, status, reason, created_by_id, "
            "version, created_at, updated_at) VALUES ('RELEASE', :f, :i, 'SUBMITTED', 'x', :u, 1, '2026-01-01', '2026-01-01')"),
            {"f": accepted["id"], "i": actors.institution_a.id, "u": actors.user["inst_a"].id})
    db.rollback()


def test_renewal_full_workflow_and_history(client, actors, accepted, db):
    req = submit(client, actors, accepted, "RENEWAL").json()
    assert act(client, actors, req, "APPROVE", who="inst_a").status_code == 403
    assert act(client, actors, req, "COMPLETE").status_code == 409
    assert act(client, actors, req, "START_REVIEW").status_code == 200
    assert act(client, actors, req, "REQUEST_CLARIFICATION").status_code == 422  # message required
    act(client, actors, req, "REQUEST_CLARIFICATION", message="Please attach the new receipt copy.",
        internal_note="Check bank letterhead carefully")
    inst_view = client.get(f"/api/lifecycle-requests/{req['id']}", headers=actors.headers["inst_a"]).json()
    assert inst_view["status"] == "CLARIFICATION_REQUESTED" and inst_view["allowed_actions"] == ["RESPOND", "WITHDRAW"]
    assert all(e["internal_note"] is None for e in inst_view["events"])
    assert act(client, actors, req, "RESPOND", who="inst_a", internal_note="sneaky", message="Attached now.").status_code == 422
    assert act(client, actors, req, "RESPOND", who="inst_a", message="New receipt uploaded to the new record.").status_code == 200
    approved = act(client, actors, req, "APPROVE", message="Renewal approved in principle.").json()
    assert approved["status"] == "APPROVED" and approved["completion_blockers"]

    # Completion waits for the new instrument to be verified and accepted through the normal workflow.
    blocked = act(client, actors, req, "COMPLETE", message="Renewal recorded as complete.")
    assert blocked.status_code == 409 and "accepted by AICTE" in blocked.json()["detail"]
    accept(client, actors, req["successor"]["id"])
    done = act(client, actors, req, "COMPLETE", message="Renewal recorded as complete.", completion_reference="ORD/2026/17")
    assert done.status_code == 200
    body = done.json()
    assert body["status"] == "COMPLETED" and body["completion_reference"] == "ORD/2026/17"
    assert body["fdr"]["lifecycle_status"] == "RENEWED" and body["successor"]["lifecycle_status"] == "ACTIVE"
    assert body["fdr"]["status"] == "ACCEPTED"  # review status untouched
    assert [e["action"] for e in body["events"]] == ["SUBMIT", "START_REVIEW", "REQUEST_CLARIFICATION", "RESPOND", "APPROVE", "COMPLETE"]
    aicte_view = client.get(f"/api/lifecycle-requests/{req['id']}", headers=actors.headers["aicte"]).json()
    assert aicte_view["events"][2]["internal_note"] == "Check bank letterhead carefully"
    # Institution was told about each AICTE step; closed requests cannot be changed.
    titles = [n.title for n in notifications_for(db, actors.user["inst_a"]) if n.event_type.startswith("LIFECYCLE_")]
    assert titles == ["Clarification requested on your renewal request", "Your renewal request was approved",
                      "Your renewal request was completed"]
    assert act(client, actors, req, "REJECT", message="Too late to reject").status_code == 409
    with pytest.raises(DatabaseError):
        db.execute(text("UPDATE lifecycle_requests SET status = 'SUBMITTED'"))
    db.rollback()
    with pytest.raises(DatabaseError):
        db.execute(text("UPDATE lifecycle_request_events SET message = 'x'"))
    db.rollback()
    # The renewed original is history: no more edits, uploads or requests.
    assert upload(client, actors.headers["inst_a"], accepted["id"], PDF_BYTES).status_code == 409
    assert submit(client, actors, client.get(f"/api/fdrs/{accepted['id']}", headers=actors.headers["inst_a"]).json(),
                  "RELEASE").status_code == 409


def test_rejection_cancels_the_proposed_successor(client, actors, accepted, db):
    req = submit(client, actors, accepted, "REPLACEMENT").json()
    succ_id = req["successor"]["id"]
    aicte = actors.headers["aicte"]
    client.post(f"/api/fdrs/{succ_id}/verification/assignments",
                json={"bank_officer_id": actors.user["bank"].id, "fdr_version": 1}, headers=aicte)
    assert act(client, actors, req, "REJECT", message="Replacement is not justified.").json()["status"] == "REJECTED"

    succ = client.get(f"/api/fdrs/{succ_id}", headers=actors.headers["inst_a"]).json()
    assert succ["lifecycle_status"] == "CANCELLED" and succ["can_edit"] is False and succ["can_upload_documents"] is False
    history = client.get(f"/api/fdrs/{succ_id}/verification", headers=aicte).json()
    assert history["assignments"][0]["status"] == "CANCELLED" and history["can_assign"] is False
    assert client.patch(f"/api/fdrs/{succ_id}", json={"version": succ["version"], "amount": "1.00"},
                        headers=actors.headers["inst_a"]).status_code == 409
    assert client.get(f"/api/fdrs/{accepted['id']}", headers=aicte).json()["lifecycle_status"] == "ACTIVE"
    # A new request can now be filed for the original.
    fresh = client.get(f"/api/fdrs/{accepted['id']}", headers=actors.headers["inst_a"]).json()
    assert submit(client, actors, fresh, "RENEWAL", successor=successor(fdr_number="LC-NEW-9")).status_code == 201


def test_institution_can_withdraw(client, actors, accepted):
    req = submit(client, actors, accepted, "RENEWAL").json()
    assert act(client, actors, req, "WITHDRAW", who="inst_a").status_code == 422  # reason required
    body = act(client, actors, req, "WITHDRAW", who="inst_a", message="Submitted by mistake, sorry.").json()
    assert body["status"] == "WITHDRAWN" and body["successor"]["lifecycle_status"] == "CANCELLED"
    assert act(client, actors, req, "WITHDRAW", who="inst_a", message="Submitted by mistake, sorry.").status_code == 409


# ---------- release ----------


def test_release_workflow_preserves_history(client, actors, matured, db):
    inst = actors.headers["inst_a"]
    doc = upload(client, inst, matured["id"], PDF_BYTES).json()
    client.post(f"/api/fdrs/{matured['id']}/screening/runs", headers=actors.headers["aicte"])
    verification_before = client.get(f"/api/fdrs/{matured['id']}/verification", headers=actors.headers["aicte"]).json()

    req = submit(client, actors, matured, "RELEASE", supporting_note="Institution closure order attached.").json()
    assert req["successor"] is None
    act(client, actors, req, "APPROVE", message="Release approved.")
    assert client.get(f"/api/fdrs/{matured['id']}", headers=inst).json()["lifecycle_status"] == "ACTIVE"  # approval alone changes nothing
    assert act(client, actors, req, "COMPLETE").status_code == 422  # completion note required
    done = act(client, actors, req, "COMPLETE", message="Release recorded administratively.", completion_reference="REL-0042").json()
    assert done["fdr"]["lifecycle_status"] == "RELEASED" and done["fdr"]["status"] == "ACCEPTED"

    # Documents, integrity, verification and screening history are all intact.
    base = f"/api/fdrs/{matured['id']}/documents/{doc['id']}"
    assert client.get(f"{base}/download", headers=inst).content == PDF_BYTES
    assert client.post(f"{base}/integrity-check", headers=actors.headers["aicte"]).json()["status"] == "intact"
    assert client.get(f"/api/fdrs/{matured['id']}/verification", headers=actors.headers["aicte"]).json()["assignments"] == \
        verification_before["assignments"]
    assert len(client.get(f"/api/fdrs/{matured['id']}/screening", headers=actors.headers["aicte"]).json()["runs"]) == 1
    # Released instruments are no longer monitored for maturity.
    assert lifecycle_service.run_lifecycle_check(db, None, today=TODAY)["checked"] == 0
    assert client.get("/api/fdrs/summary", headers=inst).json()["matured"] == 0


# ---------- access control and integrity ----------


def test_tenant_isolation_and_bank_restrictions(client, actors, accepted, db):
    req = submit(client, actors, accepted, "RENEWAL").json()
    other = actors.headers["inst_b"]
    assert client.get(f"/api/lifecycle-requests/{req['id']}", headers=other).status_code == 404
    assert client.post(f"/api/lifecycle-requests/{req['id']}/transitions",
                       json={"action": "WITHDRAW", "version": 1, "message": "Not my request"}, headers=other).status_code == 404
    assert client.get(f"/api/fdrs/{accepted['id']}/lifecycle", headers=other).status_code == 404
    assert client.post(f"/api/fdrs/{accepted['id']}/lifecycle-requests", json={"request_type": "RELEASE",
                       "fdr_version": 1, "reason": REASON}, headers=other).status_code == 404
    assert client.get("/api/lifecycle-requests", headers=other).json()["total"] == 0
    assert client.get("/api/lifecycle-requests", headers=actors.headers["aicte"]).json()["total"] == 1
    assert client.post(f"/api/fdrs/{accepted['id']}/lifecycle-requests", json={"request_type": "RELEASE",
                       "fdr_version": 1, "reason": REASON}, headers=actors.headers["aicte"]).status_code == 403

    bank = actors.headers["bank"]
    for method, url in (("get", "/api/lifecycle-requests"), ("get", f"/api/lifecycle-requests/{req['id']}"),
                        ("get", f"/api/fdrs/{accepted['id']}/lifecycle"), ("get", "/api/lifecycle/maturity"),
                        ("post", "/api/lifecycle/check")):
        assert getattr(client, method)(url, headers=bank).status_code == 403, url
    denied = db.scalars(select(AuditLog).where(AuditLog.action == "LIFECYCLE_ACCESS_DENIED")).all()
    assert len(denied) == 5 and all(d.actor_role == "BANK_OFFICER" for d in denied)


def test_concurrent_transitions_are_rejected(client, actors, accepted):
    req = submit(client, actors, accepted, "RENEWAL").json()
    url = f"/api/lifecycle-requests/{req['id']}/transitions"
    body = {"action": "START_REVIEW", "version": req["version"]}
    assert client.post(url, json=body, headers=actors.headers["aicte"]).status_code == 200
    stale = client.post(url, json={**body, "action": "APPROVE"}, headers=actors.headers["aicte"])
    assert stale.status_code == 409


def test_failed_submission_leaves_nothing_behind(client, actors, accepted, db, monkeypatch):
    from fastapi.testclient import TestClient

    from app.api.routes import lifecycle as lifecycle_routes
    from app.main import app

    fdr_count = db.scalar(select(func.count()).select_from(FDR))

    def broken(*args, **kwargs):
        raise RuntimeError("simulated failure")

    monkeypatch.setattr(lifecycle_routes.notifications, "notify", broken)
    with TestClient(app, raise_server_exceptions=False) as failing:
        response = failing.post(f"/api/fdrs/{accepted['id']}/lifecycle-requests",
                                json={"request_type": "RENEWAL", "fdr_version": accepted["version"], "reason": REASON,
                                      "successor": successor()}, headers=actors.headers["inst_a"])
    assert response.status_code == 500
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(LifecycleRequest)) == 0
    assert db.scalar(select(func.count()).select_from(FDR)) == fdr_count  # no orphan successor
    assert db.scalar(select(AuditLog).where(AuditLog.action == "LIFECYCLE_REQUEST_SUBMITTED")) is None


# ---------- dashboards ----------


def test_dashboard_counts_match_records(client, actors, create_fdr, accepted, matured, db):
    create_fdr(actors.headers["inst_a"], fdr_number="DASH-SOON", issue_date=iso(-300), maturity_date=iso(5))
    create_fdr(actors.headers["inst_b"], fdr_number="DASH-B", issue_date=iso(-300), maturity_date=iso(-10))
    clar = create_fdr(actors.headers["inst_a"], fdr_number="DASH-CLAR")
    client.post(f"/api/fdrs/{clar['id']}/review", json={"version": 1, "status": "CLARIFICATION_REQUESTED",
                "review_remarks": "Please clarify the amount"}, headers=actors.headers["aicte"])
    submit(client, actors, accepted, "RENEWAL")
    submit(client, actors, matured, "RELEASE")
    lifecycle_service.run_lifecycle_check(db, None, today=TODAY)

    inst = client.get("/api/dashboard/summary", headers=actors.headers["inst_a"]).json()
    by_status = dict(db.execute(select(FDR.status, func.count()).where(FDR.institution_id == actors.institution_a.id)
                                .group_by(FDR.status)).all())
    assert inst["fdr_by_status"] == {k.value: v for k, v in by_status.items()}
    assert inst["fdr_by_lifecycle"] == {"ACTIVE": 4, "PROPOSED": 1}
    assert inst["maturing_within_30_days"] == 2  # LC-1001 (30 days) and DASH-SOON (5 days)
    assert inst["overdue_active"] == 1           # LC-2002
    assert inst["lifecycle_requests_open"] == {"RENEWAL": 1, "RELEASE": 1}
    assert inst["clarifications_requiring_action"] == 1
    assert inst["unread_notifications"] == db.scalar(select(func.count()).select_from(Notification).where(
        Notification.recipient_id == actors.user["inst_a"].id, Notification.read_at.is_(None)))
    assert inst["verification_active"] is None and inst["screening_unreviewed_high"] is None

    aicte = client.get("/api/dashboard/summary", headers=actors.headers["aicte"]).json()
    assert aicte["overdue_active"] == 2  # LC-2002 and DASH-B
    assert aicte["lifecycle_requests_awaiting_decision"] == {"RENEWAL": 1, "RELEASE": 1}
    assert aicte["lifecycle_requests_awaiting_completion"] == 0
    assert aicte["verification_outcomes_awaiting_decision"] == 0  # both outcomes were followed by decisions

    bank = client.get("/api/dashboard/summary", headers=actors.headers["bank"]).json()
    assert (bank["cases_awaiting_action"], bank["cases_completed"]) == (0, 2)
    assert bank["fdr_by_status"] is None and bank["overdue_active"] is None

    other = client.get("/api/dashboard/summary", headers=actors.headers["inst_b"]).json()
    assert other["fdr_by_status"] == {"SUBMITTED": 1} and other["lifecycle_requests_open"] == {}
