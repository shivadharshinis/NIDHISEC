"""Possible-duplicate detection: flags for review, never blocks or overwrites."""

from sqlalchemy import select

from app.models import FDR, AuditLog
from app.services import fdrs as fdr_service


def test_cross_institution_duplicate_is_flagged_not_blocked(client, actors, create_fdr, db):
    first = create_fdr(actors.headers["inst_a"], bank_name="Test Demo Bank Ltd.", fdr_number="FD/000777", amount="1000.00")
    second = create_fdr(actors.headers["inst_b"], bank_name="THE TEST DEMO BANK", fdr_number="fd-777", amount="2000.00")

    # Both records exist; the original was not overwritten.
    assert db.scalar(select(FDR).where(FDR.id == first["id"])).amount_paise == 100000
    assert second["id"] != first["id"]
    assert second["duplicate_review"]["flagged"] is True
    assert second["duplicate_review"]["match_count"] == 1

    # The submitting institution is told about the flag but not about the other institution's record.
    assert second["duplicate_review"]["matches"] == []
    assert second["duplicate_review"]["hidden_match_count"] == 1

    # The original record is now flagged too.
    original_for_owner = client.get(f"/api/fdrs/{first['id']}", headers=actors.headers["inst_a"]).json()
    assert original_for_owner["possible_duplicate"] is True

    # AICTE sees full match details for review.
    for_aicte = client.get(f"/api/fdrs/{second['id']}", headers=actors.headers["aicte"]).json()
    match = for_aicte["duplicate_review"]["matches"][0]
    assert match["id"] == first["id"]
    assert match["institution"]["id"] == actors.institution_a.id
    assert match["same_institution"] is False

    flagged = db.scalars(select(AuditLog).where(AuditLog.action == "FDR_DUPLICATE_FLAGGED")).all()
    assert [entry.entity_id for entry in flagged] == [second["id"]]


def test_same_institution_duplicate_details_are_visible(client, actors, create_fdr):
    headers = actors.headers["inst_a"]
    first = create_fdr(headers, fdr_number="REPEAT-1")
    second = create_fdr(headers, fdr_number="repeat 1")
    review = second["duplicate_review"]
    assert review["hidden_match_count"] == 0
    assert review["matches"][0]["id"] == first["id"]
    assert review["matches"][0]["same_institution"] is True


def test_same_reference_at_different_bank_is_not_flagged(client, actors, create_fdr):
    create_fdr(actors.headers["inst_a"], bank_name="First Test Bank", ifsc_code="FRST0000001", fdr_number="12345")
    other = create_fdr(actors.headers["inst_b"], bank_name="Second Test Bank", ifsc_code="SCND0000001", fdr_number="12345")
    assert other["duplicate_review"]["flagged"] is False


def test_ifsc_bank_code_catches_differently_spelled_bank(client, actors, create_fdr):
    create_fdr(actors.headers["inst_a"], bank_name="Test Demo Bank", ifsc_code="TDBK0000001", fdr_number="XY-10")
    other = create_fdr(actors.headers["inst_b"], bank_name="TDB", ifsc_code="TDBK0000999", fdr_number="xy10")
    assert other["duplicate_review"]["flagged"] is True


def test_duplicates_only_filter_and_summary(client, actors, create_fdr):
    create_fdr(actors.headers["inst_a"], fdr_number="DUP-1")
    create_fdr(actors.headers["inst_b"], fdr_number="DUP-1")
    create_fdr(actors.headers["inst_b"], fdr_number="UNIQUE-1")

    aicte = actors.headers["aicte"]
    flagged = client.get("/api/fdrs", params={"duplicates_only": True}, headers=aicte).json()
    assert flagged["total"] == 2
    assert all(item["possible_duplicate"] for item in flagged["items"])
    assert client.get("/api/fdrs/summary", headers=aicte).json()["possible_duplicates"] == 2
    assert client.get("/api/fdrs/summary", headers=actors.headers["inst_b"]).json()["possible_duplicates"] == 1


def test_editing_reference_into_a_duplicate_flags_it(client, actors, create_fdr, db):
    create_fdr(actors.headers["inst_a"], fdr_number="ORIGINAL-9")
    mine = create_fdr(actors.headers["inst_b"], fdr_number="DIFFERENT-1")
    assert mine["duplicate_review"]["flagged"] is False

    updated = client.patch(
        f"/api/fdrs/{mine['id']}", json={"version": mine["version"], "fdr_number": "original/9"}, headers=actors.headers["inst_b"]
    ).json()
    assert updated["duplicate_review"]["flagged"] is True
    assert db.scalars(
        select(AuditLog).where(AuditLog.action == "FDR_DUPLICATE_FLAGGED", AuditLog.entity_id == mine["id"])
    ).first()


def test_sql_and_python_matching_agree(client, actors, create_fdr, db):
    specs = [
        ("Alpha Test Bank", "AAAA0000001", "MM-1"),
        ("Alpha Test Bank Limited", None, "mm1"),
        ("Beta Test Bank", "AAAA0000002", "MM 1"),
        ("Gamma Test Bank", None, "MM-1"),
        ("Gamma Test Bank", None, "MM-2"),
    ]
    for bank, ifsc, number in specs:
        create_fdr(actors.headers["inst_a"], bank_name=bank, ifsc_code=ifsc, fdr_number=number)

    rows = db.scalars(select(FDR)).all()
    via_python = fdr_service.duplicate_flags(db, rows)
    via_sql = set(db.scalars(select(FDR.id).where(fdr_service.has_duplicate_clause())).all())
    assert via_python == via_sql
    assert len(via_sql) == 3  # the three "MM-1" records at Alpha/Alpha Ltd/IFSC AAAA


def test_normalisation_rules():
    from app.services.normalization import normalize_bank_name, normalize_fdr_number

    assert normalize_fdr_number("fd/000777-a") == normalize_fdr_number("FD 777 A") == "FD777A"
    assert normalize_fdr_number("000") == "0"
    assert normalize_fdr_number("A10B") != normalize_fdr_number("A1B")
    assert normalize_bank_name("The Demo Co-operative Bank Ltd.") == normalize_bank_name("demo bank") == "DEMO BANK"
    assert normalize_bank_name("Demo Bank") != normalize_bank_name("Demo National Bank")
