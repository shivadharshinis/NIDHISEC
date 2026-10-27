"""Role-based access and institution-level data isolation, enforced by the API."""

from tests.conftest import fdr_payload


def test_institution_sees_only_its_own_records(client, actors, create_fdr):
    own = create_fdr(actors.headers["inst_a"], fdr_number="A-100")
    create_fdr(actors.headers["inst_b"], fdr_number="B-200")

    response = client.get("/api/fdrs", headers=actors.headers["inst_a"])

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert [item["id"] for item in body["items"]] == [own["id"]]


def test_institution_filter_cannot_widen_scope(client, actors, create_fdr):
    create_fdr(actors.headers["inst_b"], fdr_number="B-200")
    response = client.get(
        "/api/fdrs", params={"institution_id": actors.institution_b.id}, headers=actors.headers["inst_a"]
    )
    assert response.json()["total"] == 0


def test_other_institutions_record_is_not_found(client, actors, create_fdr):
    other = create_fdr(actors.headers["inst_b"], fdr_number="B-200")
    headers = actors.headers["inst_a"]

    assert client.get(f"/api/fdrs/{other['id']}", headers=headers).status_code == 404
    assert client.get(f"/api/fdrs/{other['id']}/history", headers=headers).status_code == 404
    patch = client.patch(f"/api/fdrs/{other['id']}", json={"version": 1, "amount": "1.00"}, headers=headers)
    assert patch.status_code == 404


def test_record_is_always_created_for_own_institution(client, actors):
    payload = fdr_payload(institution_id=actors.institution_b.id)
    response = client.post("/api/fdrs", json=payload, headers=actors.headers["inst_a"])
    assert response.status_code == 422  # unknown fields are rejected, not silently honoured

    response = client.post("/api/fdrs", json=fdr_payload(), headers=actors.headers["inst_a"])
    assert response.json()["institution"]["id"] == actors.institution_a.id


def test_status_cannot_be_set_by_institution(client, actors, create_fdr):
    fdr = create_fdr(actors.headers["inst_a"])
    response = client.patch(
        f"/api/fdrs/{fdr['id']}", json={"version": fdr["version"], "status": "UNDER_REVIEW"}, headers=actors.headers["inst_a"]
    )
    assert response.status_code == 422
    review = client.post(
        f"/api/fdrs/{fdr['id']}/review",
        json={"version": fdr["version"], "status": "UNDER_REVIEW"},
        headers=actors.headers["inst_a"],
    )
    assert review.status_code == 403


def test_bank_officer_has_no_broad_access(client, actors, create_fdr):
    fdr = create_fdr(actors.headers["inst_a"])
    headers = actors.headers["bank"]

    for response in (
        client.get("/api/fdrs", headers=headers),
        client.get("/api/fdrs/summary", headers=headers),
        client.get(f"/api/fdrs/{fdr['id']}", headers=headers),
        client.post("/api/fdrs", json=fdr_payload(), headers=headers),
        client.get("/api/institutions", headers=headers),
        client.get("/api/audit-logs", headers=headers),
    ):
        assert response.status_code == 403, response.request.url
    assert "assign" in client.get("/api/fdrs", headers=headers).json()["detail"]


def test_aicte_can_view_all_but_not_create(client, actors, create_fdr):
    create_fdr(actors.headers["inst_a"], fdr_number="A-100")
    create_fdr(actors.headers["inst_b"], fdr_number="B-200")
    headers = actors.headers["aicte"]

    assert client.get("/api/fdrs", headers=headers).json()["total"] == 2
    filtered = client.get("/api/fdrs", params={"institution_id": actors.institution_b.id}, headers=headers)
    assert filtered.json()["total"] == 1
    assert client.post("/api/fdrs", json=fdr_payload(), headers=headers).status_code == 403


def test_aicte_cannot_edit_institution_fields(client, actors, create_fdr):
    fdr = create_fdr(actors.headers["inst_a"])
    response = client.patch(
        f"/api/fdrs/{fdr['id']}", json={"version": fdr["version"], "amount": "1.00"}, headers=actors.headers["aicte"]
    )
    assert response.status_code == 403


def test_audit_log_endpoint_is_aicte_only(client, actors):
    assert client.get("/api/audit-logs", headers=actors.headers["inst_a"]).status_code == 403
    assert client.get("/api/audit-logs", headers=actors.headers["aicte"]).status_code == 200
    assert client.get("/api/audit-logs").status_code == 401


def test_institutions_list_is_scoped(client, actors):
    own = client.get("/api/institutions", headers=actors.headers["inst_a"]).json()
    assert [inst["id"] for inst in own] == [actors.institution_a.id]
    assert len(client.get("/api/institutions", headers=actors.headers["aicte"]).json()) == 2


def test_summary_is_scoped(client, actors, create_fdr):
    create_fdr(actors.headers["inst_a"], fdr_number="A-100")
    create_fdr(actors.headers["inst_b"], fdr_number="B-200")
    create_fdr(actors.headers["inst_b"], fdr_number="B-201")
    assert client.get("/api/fdrs/summary", headers=actors.headers["inst_a"]).json()["total"] == 1
    assert client.get("/api/fdrs/summary", headers=actors.headers["aicte"]).json()["total"] == 3
