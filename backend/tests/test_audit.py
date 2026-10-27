import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DatabaseError

from app.models import AuditLog


def _entries(db, fdr_id):
    return db.scalars(
        select(AuditLog).where(AuditLog.entity_type == "fdr", AuditLog.entity_id == fdr_id).order_by(AuditLog.id)
    ).all()


def test_create_update_and_review_are_audited(client, actors, create_fdr, db):
    fdr = create_fdr(actors.headers["inst_a"], amount="1000.00")
    client.patch(f"/api/fdrs/{fdr['id']}", json={"version": 1, "amount": "1500.00"}, headers=actors.headers["inst_a"])
    client.post(
        f"/api/fdrs/{fdr['id']}/review", json={"version": 2, "status": "UNDER_REVIEW"}, headers=actors.headers["aicte"]
    )

    entries = _entries(db, fdr["id"])
    assert [entry.action for entry in entries] == ["FDR_CREATED", "FDR_UPDATED", "FDR_STATUS_CHANGED"]

    created, updated, reviewed = entries
    assert created.actor_user_id == actors.user["inst_a"].id
    assert created.institution_id == actors.institution_a.id
    assert updated.changes == {"amount": {"old": "1000.00", "new": "1500.00"}}
    assert reviewed.actor_role == "AICTE_OFFICIAL"
    assert reviewed.changes["status"] == {"old": "SUBMITTED", "new": "UNDER_REVIEW"}
    assert all(entry.ip_address for entry in entries)


def test_no_op_update_is_not_audited(client, actors, create_fdr, db):
    fdr = create_fdr(actors.headers["inst_a"], amount="1000.00")
    response = client.patch(
        f"/api/fdrs/{fdr['id']}", json={"version": 1, "amount": "1000.00"}, headers=actors.headers["inst_a"]
    )
    assert response.json()["version"] == 1
    assert [entry.action for entry in _entries(db, fdr["id"])] == ["FDR_CREATED"]


def test_rejected_request_leaves_no_audit_or_change(client, actors, create_fdr, db):
    fdr = create_fdr(actors.headers["inst_b"])
    client.patch(f"/api/fdrs/{fdr['id']}", json={"version": 1, "amount": "1.00"}, headers=actors.headers["inst_a"])
    assert [entry.action for entry in _entries(db, fdr["id"])] == ["FDR_CREATED"]


def test_history_endpoint_is_scoped_to_record_viewers(client, actors, create_fdr):
    fdr = create_fdr(actors.headers["inst_a"])
    own = client.get(f"/api/fdrs/{fdr['id']}/history", headers=actors.headers["inst_a"])
    assert own.status_code == 200
    assert own.json()[0]["action"] == "FDR_CREATED"
    assert "ip_address" not in own.json()[0]
    assert client.get(f"/api/fdrs/{fdr['id']}/history", headers=actors.headers["inst_b"]).status_code == 404


def test_audit_log_listing_for_aicte(client, actors, create_fdr):
    fdr = create_fdr(actors.headers["inst_a"])
    response = client.get(
        "/api/audit-logs", params={"entity_type": "fdr", "entity_id": fdr["id"]}, headers=actors.headers["aicte"]
    )
    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["action"] == "FDR_CREATED"

    logins = client.get("/api/audit-logs", params={"action": "LOGIN_SUCCEEDED"}, headers=actors.headers["aicte"])
    assert logins.json()["total"] == 4  # one per signed-in actor


def test_audit_log_is_append_only(client, actors, create_fdr, db):
    create_fdr(actors.headers["inst_a"])
    with pytest.raises(DatabaseError, match="append-only"):
        db.execute(text("UPDATE audit_logs SET summary = 'tampered'"))
    db.rollback()
    with pytest.raises(DatabaseError, match="append-only"):
        db.execute(text("DELETE FROM audit_logs"))
    db.rollback()
