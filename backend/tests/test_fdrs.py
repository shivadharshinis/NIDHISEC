from datetime import date, timedelta

import pytest

from tests.conftest import fdr_payload


def test_create_and_retrieve_fdr(client, actors):
    headers = actors.headers["inst_a"]
    payload = fdr_payload(amount="500000.50", ifsc_code=" test0000001 ", branch_name="  ")

    created = client.post("/api/fdrs", json=payload, headers=headers)
    assert created.status_code == 201
    body = created.json()
    assert body["status"] == "SUBMITTED"
    assert body["amount"] == "500000.50"
    assert body["ifsc_code"] == "TEST0000001"
    assert body["branch_name"] is None
    assert body["version"] == 1
    assert body["duplicate_review"]["flagged"] is False
    assert body["documents"] == []
    assert body["can_edit"] is True

    fetched = client.get(f"/api/fdrs/{body['id']}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["fdr_number"] == payload["fdr_number"]
    assert fetched.json()["institution"]["id"] == actors.institution_a.id


@pytest.mark.parametrize("amount", ["0", "-100", "0.001", "12.345", "10000000000.01", "abc"])
def test_invalid_amount_rejected(client, actors, amount):
    response = client.post("/api/fdrs", json=fdr_payload(amount=amount), headers=actors.headers["inst_a"])
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"][-1] == "amount"


def test_invalid_dates_rejected(client, actors):
    headers = actors.headers["inst_a"]
    today = date.today()
    cases = {
        "maturity_date": dict(issue_date=today.isoformat(), maturity_date=(today - timedelta(days=1)).isoformat()),
        "issue_date": dict(issue_date=(today + timedelta(days=5)).isoformat(),
                           maturity_date=(today + timedelta(days=400)).isoformat()),
    }
    for field, overrides in cases.items():
        response = client.post("/api/fdrs", json=fdr_payload(**overrides), headers=headers)
        assert response.status_code == 422, overrides
        assert field in [error["loc"][-1] for error in response.json()["detail"]]

    same_day = client.post(
        "/api/fdrs", json=fdr_payload(issue_date=today.isoformat(), maturity_date=today.isoformat()), headers=headers
    )
    assert same_day.status_code == 422

    too_long = client.post(
        "/api/fdrs",
        json=fdr_payload(issue_date="2024-01-01", maturity_date="2034-01-02"),
        headers=headers,
    )
    assert too_long.status_code == 422


@pytest.mark.parametrize("field", ["bank_name", "fdr_number", "amount", "issue_date", "maturity_date"])
def test_required_fields(client, actors, field):
    payload = fdr_payload()
    del payload[field]
    assert client.post("/api/fdrs", json=payload, headers=actors.headers["inst_a"]).status_code == 422


def test_rejects_unsafe_characters(client, actors):
    response = client.post(
        "/api/fdrs", json=fdr_payload(fdr_number="<script>alert(1)</script>"), headers=actors.headers["inst_a"]
    )
    assert response.status_code == 422


def test_update_permitted_fields(client, actors, create_fdr):
    headers = actors.headers["inst_a"]
    fdr = create_fdr(headers)

    response = client.patch(
        f"/api/fdrs/{fdr['id']}", json={"version": fdr["version"], "amount": "300000.00"}, headers=headers
    )
    assert response.status_code == 200
    assert response.json()["amount"] == "300000.00"
    assert response.json()["version"] == fdr["version"] + 1


def test_update_with_stale_version_is_rejected(client, actors, create_fdr):
    headers = actors.headers["inst_a"]
    fdr = create_fdr(headers)
    client.patch(f"/api/fdrs/{fdr['id']}", json={"version": 1, "amount": "300000.00"}, headers=headers)

    stale = client.patch(f"/api/fdrs/{fdr['id']}", json={"version": 1, "amount": "999.00"}, headers=headers)
    assert stale.status_code == 409
    assert client.get(f"/api/fdrs/{fdr['id']}", headers=headers).json()["amount"] == "300000.00"


def test_update_validates_merged_dates(client, actors, create_fdr):
    headers = actors.headers["inst_a"]
    fdr = create_fdr(headers)
    before_issue = (date.fromisoformat(fdr["issue_date"]) - timedelta(days=1)).isoformat()

    response = client.patch(
        f"/api/fdrs/{fdr['id']}", json={"version": 1, "maturity_date": before_issue}, headers=headers
    )
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "maturity_date"]


def test_update_rejects_invalid_amount_and_clearing_required(client, actors, create_fdr):
    headers = actors.headers["inst_a"]
    fdr = create_fdr(headers)
    assert client.patch(f"/api/fdrs/{fdr['id']}", json={"version": 1, "amount": "-5"}, headers=headers).status_code == 422
    assert client.patch(f"/api/fdrs/{fdr['id']}", json={"version": 1, "bank_name": None}, headers=headers).status_code == 422


def test_review_flow_and_edit_lock(client, actors, create_fdr):
    inst, aicte = actors.headers["inst_a"], actors.headers["aicte"]
    fdr = create_fdr(inst)

    clarify = client.post(
        f"/api/fdrs/{fdr['id']}/review",
        json={"version": 1, "status": "CLARIFICATION_REQUESTED", "review_remarks": "Please correct the branch name"},
        headers=aicte,
    )
    assert clarify.status_code == 200
    assert clarify.json()["status"] == "CLARIFICATION_REQUESTED"

    # Institution corrects the record; it returns to SUBMITTED.
    fixed = client.patch(
        f"/api/fdrs/{fdr['id']}", json={"version": 2, "branch_name": "Corrected Branch"}, headers=inst
    )
    assert fixed.status_code == 200
    assert fixed.json()["status"] == "SUBMITTED"

    rejected = client.post(
        f"/api/fdrs/{fdr['id']}/review",
        json={"version": 3, "status": "REJECTED", "review_remarks": "Test rejection"},
        headers=aicte,
    )
    assert rejected.status_code == 200
    assert rejected.json()["can_edit"] is False

    locked = client.patch(f"/api/fdrs/{fdr['id']}", json={"version": 4, "amount": "1.00"}, headers=inst)
    assert locked.status_code == 409

    no_transition = client.post(
        f"/api/fdrs/{fdr['id']}/review", json={"version": 4, "status": "UNDER_REVIEW"}, headers=aicte
    )
    assert no_transition.status_code == 409


def test_reject_requires_remarks(client, actors, create_fdr):
    fdr = create_fdr(actors.headers["inst_a"])
    response = client.post(
        f"/api/fdrs/{fdr['id']}/review", json={"version": 1, "status": "REJECTED"}, headers=actors.headers["aicte"]
    )
    assert response.status_code == 422


def test_list_pagination_search_and_filters(client, actors, create_fdr):
    headers = actors.headers["inst_a"]
    for n in range(5):
        create_fdr(headers, fdr_number=f"PAGE-{n}", bank_name="Paging Test Bank" if n < 3 else "Other Test Bank")

    page1 = client.get("/api/fdrs", params={"page_size": 2}, headers=headers).json()
    page3 = client.get("/api/fdrs", params={"page_size": 2, "page": 3}, headers=headers).json()
    assert page1["total"] == 5 and page1["pages"] == 3 and len(page1["items"]) == 2
    assert len(page3["items"]) == 1
    assert {i["id"] for i in page1["items"]}.isdisjoint({i["id"] for i in page3["items"]})

    assert client.get("/api/fdrs", params={"q": "paging"}, headers=headers).json()["total"] == 3
    assert client.get("/api/fdrs", params={"q": "PAGE-4"}, headers=headers).json()["total"] == 1
    assert client.get("/api/fdrs", params={"q": "%"}, headers=headers).json()["total"] == 0
    assert client.get("/api/fdrs", params={"status": "REJECTED"}, headers=headers).json()["total"] == 0
    assert client.get("/api/fdrs", params={"status": "SUBMITTED"}, headers=headers).json()["total"] == 5
    assert client.get("/api/fdrs", params={"page_size": 500}, headers=headers).status_code == 422
    assert client.get("/api/fdrs", params={"sort": "drop table"}, headers=headers).status_code == 422


def test_maturity_filter_and_summary(client, actors, create_fdr):
    headers = actors.headers["inst_a"]
    today = date.today()
    create_fdr(headers, fdr_number="SOON-1", issue_date=(today - timedelta(days=300)).isoformat(),
               maturity_date=(today + timedelta(days=30)).isoformat())
    create_fdr(headers, fdr_number="LATER-1", issue_date=(today - timedelta(days=10)).isoformat(),
               maturity_date=(today + timedelta(days=700)).isoformat())
    create_fdr(headers, fdr_number="PAST-1", issue_date=(today - timedelta(days=500)).isoformat(),
               maturity_date=(today - timedelta(days=5)).isoformat())

    soon = client.get("/api/fdrs", params={"maturity_to": (today + timedelta(days=90)).isoformat(),
                                           "maturity_from": today.isoformat()}, headers=headers).json()
    assert [item["fdr_number"] for item in soon["items"]] == ["SOON-1"]

    summary = client.get("/api/fdrs/summary", headers=headers).json()
    assert summary["total"] == 3
    assert summary["by_status"]["SUBMITTED"] == 3
    assert summary["maturing_within_90_days"] == 1
    assert summary["matured"] == 1
    assert summary["possible_duplicates"] == 0


def test_missing_record_is_404(client, actors):
    assert client.get("/api/fdrs/99999", headers=actors.headers["aicte"]).status_code == 404
