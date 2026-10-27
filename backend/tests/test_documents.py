"""FDR document management: validation, storage, access control, integrity and audit."""

import hashlib
import struct
import zlib

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import DatabaseError

from app.core.config import get_settings
from app.main import app
from app.models import AuditLog, FDRDocument
from app.services import document_storage

# ---------- sample files (synthetic, structurally valid) ----------

PDF_BYTES = (
    b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
    b"2 0 obj\n<< /Type /Pages /Kids [] /Count 0 >>\nendobj\n"
    b"trailer\n<< /Root 1 0 R >>\n%%EOF\n"
)


def make_png(width: int = 1, height: int = 1) -> bytes:
    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)

    raw = b"".join(b"\x00" + b"\xff\xff\xff" * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def make_jpeg(width: int = 2, height: int = 2) -> bytes:
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    sof0 = b"\xff\xc0" + struct.pack(">HBHHB", 11, 8, height, width, 1) + b"\x01\x11\x00"
    sos = b"\xff\xda" + struct.pack(">HB", 8, 1) + b"\x01\x00\x00\x3f\x00"
    return b"\xff\xd8" + app0 + sof0 + sos + b"\x12\x34\x56" + b"\xff\xd9"


PNG_BYTES = make_png()
JPEG_BYTES = make_jpeg()


# ---------- helpers ----------


def upload(client, headers, fdr_id, content, filename="fdr-scan.pdf", document_type="FDR_COPY", mime="application/pdf"):
    return client.post(
        f"/api/fdrs/{fdr_id}/documents",
        files={"file": (filename, content, mime)},
        data={"document_type": document_type},
        headers=headers,
    )


def stored_files():
    return document_storage.list_stored_files()


@pytest.fixture
def fdr_a(actors, create_fdr):
    return create_fdr(actors.headers["inst_a"], fdr_number="DOC-A-1")


@pytest.fixture
def uploaded(client, actors, fdr_a):
    response = upload(client, actors.headers["inst_a"], fdr_a["id"], PDF_BYTES)
    assert response.status_code == 201, response.text
    return response.json()


# ---------- upload and download ----------


def test_upload_and_download_pdf(client, actors, fdr_a, db):
    response = upload(client, actors.headers["inst_a"], fdr_a["id"], PDF_BYTES, filename="../../FDR scan (1).PDF")
    assert response.status_code == 201
    doc = response.json()
    assert doc["content_type"] == "application/pdf"
    assert doc["original_filename"] == "FDR scan (1).pdf"
    assert doc["size_bytes"] == len(PDF_BYTES)
    assert doc["sha256"] == hashlib.sha256(PDF_BYTES).hexdigest()
    assert doc["is_withdrawn"] is False
    assert "storage_key" not in response.text and "storage" not in response.text.lower()

    download = client.get(f"/api/fdrs/{fdr_a['id']}/documents/{doc['id']}/download", headers=actors.headers["inst_a"])
    assert download.status_code == 200
    assert download.content == PDF_BYTES
    assert download.headers["content-type"] == "application/pdf"
    assert download.headers["content-disposition"].startswith("attachment;")
    assert "sandbox" in download.headers["content-security-policy"]
    assert download.headers["x-content-type-options"] == "nosniff"
    assert download.headers["x-content-sha256"] == doc["sha256"]

    # Stored under a random key, outside anything the frontend serves.
    files = stored_files()
    assert len(files) == 1
    stored_key = db.scalar(select(FDRDocument.storage_key))
    assert files[0].name == stored_key and "scan" not in files[0].name
    assert files[0].read_bytes() == PDF_BYTES


@pytest.mark.parametrize(
    ("content", "filename", "expected_type"),
    [(PNG_BYTES, "photo.png", "image/png"), (JPEG_BYTES, "photo.JPEG", "image/jpeg"), (JPEG_BYTES, "x.jpg", "image/jpeg")],
)
def test_upload_images(client, actors, fdr_a, content, filename, expected_type):
    response = upload(client, actors.headers["inst_a"], fdr_a["id"], content, filename=filename, mime="text/plain")
    assert response.status_code == 201, response.text
    assert response.json()["content_type"] == expected_type  # detected, not the client's "text/plain"


def test_list_and_metadata(client, actors, fdr_a, uploaded):
    listing = client.get(f"/api/fdrs/{fdr_a['id']}/documents", headers=actors.headers["inst_a"]).json()
    assert [item["id"] for item in listing["items"]] == [uploaded["id"]]
    assert listing["can_upload"] is True and listing["can_withdraw"] is True
    assert listing["can_check_integrity"] is False
    assert listing["max_upload_bytes"] == get_settings().max_upload_bytes
    assert ".pdf" in listing["allowed_extensions"]

    meta = client.get(f"/api/fdrs/{fdr_a['id']}/documents/{uploaded['id']}", headers=actors.headers["inst_a"])
    assert meta.json()["sha256"] == uploaded["sha256"]

    detail = client.get(f"/api/fdrs/{fdr_a['id']}", headers=actors.headers["inst_a"]).json()
    assert [d["id"] for d in detail["documents"]] == [uploaded["id"]]
    assert detail["can_upload_documents"] is True


# ---------- validation ----------


@pytest.mark.parametrize("filename", ["fdr.exe", "fdr.txt", "fdr.pdf.exe", "fdr", "fdr.svg", "fdr.html"])
def test_unsupported_extension_rejected(client, actors, fdr_a, filename):
    response = upload(client, actors.headers["inst_a"], fdr_a["id"], PDF_BYTES, filename=filename)
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "file"]
    assert stored_files() == []


@pytest.mark.parametrize(
    ("content", "filename"),
    [
        (PNG_BYTES, "renamed.pdf"),
        (PDF_BYTES, "renamed.png"),
        (PDF_BYTES, "renamed.jpg"),
        (b"MZ\x90\x00 this is an executable", "fdr.pdf"),
        (b"<html><body>not a pdf</body></html>", "fdr.pdf"),
        (b"plain text pretending to be an image", "fdr.png"),
    ],
)
def test_mismatched_or_unknown_signature_rejected(client, actors, fdr_a, content, filename):
    response = upload(client, actors.headers["inst_a"], fdr_a["id"], content, filename=filename)
    assert response.status_code == 422, response.text
    assert stored_files() == []


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (b"%PDF-1.4\n1 0 obj\n<< >>\nendobj\n", "truncated"),
        (PDF_BYTES.replace(b"/Type /Catalog", b"/Type /Catalog /OpenAction << /S /JavaScript /JS (app.alert(1)) >>"), "active content"),
        (PDF_BYTES.replace(b"/Type /Catalog", b"/Type /Catalog /Names << /EmbeddedFiles 3 0 R >> /EmbeddedFile"), "active content"),
        (PDF_BYTES.replace(b"trailer\n<<", b"trailer\n<< /Encrypt 5 0 R"), "encrypted"),
        (PDF_BYTES.replace(b"endobj\n", b"endobj\n<script>alert(1)</script>\n", 1), "markup"),
    ],
)
def test_malformed_or_suspicious_pdf_rejected(client, actors, fdr_a, content, message):
    response = upload(client, actors.headers["inst_a"], fdr_a["id"], content)
    assert response.status_code == 422
    assert message in response.json()["detail"][0]["msg"]


def test_malformed_images_rejected(client, actors, fdr_a):
    headers = actors.headers["inst_a"]
    corrupted_png = bytearray(PNG_BYTES)
    corrupted_png[20] ^= 0xFF  # inside IHDR -> CRC mismatch
    cases = [
        (bytes(corrupted_png), "x.png"),
        (PNG_BYTES[:-12], "x.png"),  # IEND missing
        (make_png(width=0), "x.png"),
        (make_png(width=30_000, height=1), "x.png"),
        (JPEG_BYTES[:-2], "x.jpg"),  # no end-of-image marker
        (b"\xff\xd8\xff\xd9", "x.jpg"),  # no frame header
    ]
    for content, filename in cases:
        assert upload(client, headers, fdr_a["id"], content, filename=filename).status_code == 422, filename
    assert stored_files() == []


def test_empty_file_rejected(client, actors, fdr_a):
    response = upload(client, actors.headers["inst_a"], fdr_a["id"], b"")
    assert response.status_code == 422
    assert "empty" in response.json()["detail"][0]["msg"]


def test_oversized_file_rejected_by_endpoint(client, actors, fdr_a):
    limit = get_settings().max_upload_bytes
    content = PDF_BYTES[:-6] + b" " * (limit - len(PDF_BYTES) + 1) + b"%%EOF\n"
    assert len(content) > limit
    response = upload(client, actors.headers["inst_a"], fdr_a["id"], content)
    assert response.status_code == 413
    assert stored_files() == []


def test_oversized_request_rejected_before_parsing(client, actors, fdr_a):
    content = b"%PDF-1.4\n" + b"0" * (get_settings().max_upload_bytes + 200_000)
    response = upload(client, actors.headers["inst_a"], fdr_a["id"], content)
    assert response.status_code == 413
    assert "limit" in response.json()["detail"][0]["msg"]


def test_same_file_twice_on_one_record_is_rejected(client, actors, fdr_a, create_fdr, uploaded):
    again = upload(client, actors.headers["inst_a"], fdr_a["id"], PDF_BYTES, filename="copy.pdf")
    assert again.status_code == 409
    other_fdr = create_fdr(actors.headers["inst_a"], fdr_number="DOC-A-2")
    assert upload(client, actors.headers["inst_a"], other_fdr["id"], PDF_BYTES).status_code == 201


def test_cannot_upload_to_rejected_record(client, actors, fdr_a):
    client.post(
        f"/api/fdrs/{fdr_a['id']}/review",
        json={"version": 1, "status": "REJECTED", "review_remarks": "Test rejection"},
        headers=actors.headers["aicte"],
    )
    assert upload(client, actors.headers["inst_a"], fdr_a["id"], PDF_BYTES).status_code == 409


# ---------- access control ----------


def test_other_institution_cannot_reach_documents(client, actors, fdr_a, uploaded, create_fdr):
    headers = actors.headers["inst_b"]
    base = f"/api/fdrs/{fdr_a['id']}/documents"
    assert client.get(base, headers=headers).status_code == 404
    assert client.get(f"{base}/{uploaded['id']}", headers=headers).status_code == 404
    assert client.get(f"{base}/{uploaded['id']}/download", headers=headers).status_code == 404
    assert upload(client, headers, fdr_a["id"], PNG_BYTES, filename="x.png").status_code == 404

    # Using their own FDR id with someone else's document id does not work either.
    own = create_fdr(headers, fdr_number="DOC-B-1")
    assert client.get(f"/api/fdrs/{own['id']}/documents/{uploaded['id']}/download", headers=headers).status_code == 404


def test_bank_officer_has_no_document_access(client, actors, fdr_a, uploaded):
    headers = actors.headers["bank"]
    base = f"/api/fdrs/{fdr_a['id']}/documents"
    assert client.get(base, headers=headers).status_code == 403
    assert client.get(f"{base}/{uploaded['id']}", headers=headers).status_code == 403
    assert client.get(f"{base}/{uploaded['id']}/download", headers=headers).status_code == 403
    assert upload(client, headers, fdr_a["id"], PNG_BYTES, filename="x.png").status_code == 403


def test_unauthenticated_requests_rejected(client, fdr_a, uploaded):
    assert client.get(f"/api/fdrs/{fdr_a['id']}/documents/{uploaded['id']}/download").status_code == 401


def test_aicte_can_read_but_not_upload_or_withdraw(client, actors, fdr_a, uploaded):
    headers = actors.headers["aicte"]
    base = f"/api/fdrs/{fdr_a['id']}/documents"
    listing = client.get(base, headers=headers).json()
    assert len(listing["items"]) == 1
    assert listing["can_upload"] is False and listing["can_check_integrity"] is True
    assert client.get(f"{base}/{uploaded['id']}/download", headers=headers).content == PDF_BYTES
    assert upload(client, headers, fdr_a["id"], PNG_BYTES, filename="x.png").status_code == 403
    withdraw = client.post(f"{base}/{uploaded['id']}/withdraw", json={"reason": "Not allowed"}, headers=headers)
    assert withdraw.status_code == 403


# ---------- integrity ----------


def _stored_path(db):
    return document_storage._path_for(db.scalar(select(FDRDocument.storage_key)))


def test_integrity_check_intact(client, actors, fdr_a, uploaded, db):
    report = client.post(
        f"/api/fdrs/{fdr_a['id']}/documents/{uploaded['id']}/integrity-check", headers=actors.headers["aicte"]
    ).json()
    assert report["status"] == "intact"
    assert report["actual_sha256"] == report["expected_sha256"] == hashlib.sha256(_stored_path(db).read_bytes()).hexdigest()
    institution = client.post(
        f"/api/fdrs/{fdr_a['id']}/documents/{uploaded['id']}/integrity-check", headers=actors.headers["inst_a"]
    )
    assert institution.status_code == 403


def test_tampered_file_blocks_download_and_is_audited(client, actors, fdr_a, uploaded, db):
    _stored_path(db).write_bytes(PDF_BYTES.replace(b"Catalog", b"Katalog"))
    base = f"/api/fdrs/{fdr_a['id']}/documents/{uploaded['id']}"

    download = client.get(f"{base}/download", headers=actors.headers["aicte"])
    assert download.status_code == 409
    assert b"Katalog" not in download.content

    report = client.post(f"{base}/integrity-check", headers=actors.headers["aicte"]).json()
    assert report["status"] == "mismatch"
    assert report["actual_sha256"] != report["expected_sha256"]

    failures = db.scalars(select(AuditLog).where(AuditLog.action == "DOCUMENT_INTEGRITY_FAILED")).all()
    assert len(failures) == 2
    assert failures[0].changes["document_id"] == uploaded["id"]


def test_missing_file_is_reported(client, actors, fdr_a, uploaded, db):
    _stored_path(db).unlink()
    base = f"/api/fdrs/{fdr_a['id']}/documents/{uploaded['id']}"
    assert client.get(f"{base}/download", headers=actors.headers["inst_a"]).status_code == 409
    assert client.post(f"{base}/integrity-check", headers=actors.headers["aicte"]).json()["status"] == "missing"


def test_tampered_storage_key_cannot_escape_storage(db):
    with pytest.raises(document_storage.StorageKeyError):
        document_storage.read("../../../.env")


# ---------- audit ----------


def test_upload_download_and_rejection_are_audited(client, actors, fdr_a, uploaded, db):
    client.get(f"/api/fdrs/{fdr_a['id']}/documents/{uploaded['id']}/download", headers=actors.headers["aicte"])
    upload(client, actors.headers["inst_a"], fdr_a["id"], b"not a pdf", filename="bad.pdf")

    entries = db.scalars(
        select(AuditLog).where(AuditLog.action.like("DOCUMENT_%")).order_by(AuditLog.id)
    ).all()
    assert [e.action for e in entries] == ["DOCUMENT_UPLOADED", "DOCUMENT_DOWNLOADED", "DOCUMENT_UPLOAD_REJECTED"]
    uploaded_entry, downloaded_entry, rejected_entry = entries
    for entry in (uploaded_entry, downloaded_entry):
        assert entry.entity_type == "fdr" and entry.entity_id == fdr_a["id"]
        assert entry.changes["document_id"] == uploaded["id"]
        assert entry.changes["sha256"] == uploaded["sha256"]
        assert entry.created_at is not None
    assert uploaded_entry.actor_user_id == actors.user["inst_a"].id
    assert downloaded_entry.actor_user_id == actors.user["aicte"].id
    assert rejected_entry.changes["reason"]

    history = client.get(f"/api/fdrs/{fdr_a['id']}/history", headers=actors.headers["inst_a"]).json()
    assert {"DOCUMENT_UPLOADED", "DOCUMENT_DOWNLOADED"} <= {h["action"] for h in history}


# ---------- withdrawal and evidence protection ----------


def test_withdrawal_keeps_document_and_history(client, actors, fdr_a, uploaded, db):
    base = f"/api/fdrs/{fdr_a['id']}/documents/{uploaded['id']}"
    headers = actors.headers["inst_a"]
    assert client.post(f"{base}/withdraw", json={"reason": "no"}, headers=headers).status_code == 422

    response = client.post(f"{base}/withdraw", json={"reason": "Wrong file attached"}, headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["is_withdrawn"] is True and body["withdrawal_reason"] == "Wrong file attached"
    assert body["withdrawn_by_name"] == actors.user["inst_a"].full_name

    assert client.post(f"{base}/withdraw", json={"reason": "Again please"}, headers=headers).status_code == 409
    # Still on record and still retrievable as evidence.
    assert client.get(f"{base}/download", headers=actors.headers["aicte"]).content == PDF_BYTES
    assert db.scalar(select(AuditLog).where(AuditLog.action == "DOCUMENT_WITHDRAWN")) is not None


def test_withdrawal_blocked_once_under_review(client, actors, fdr_a, uploaded):
    client.post(f"/api/fdrs/{fdr_a['id']}/review", json={"version": 1, "status": "UNDER_REVIEW"}, headers=actors.headers["aicte"])
    response = client.post(
        f"/api/fdrs/{fdr_a['id']}/documents/{uploaded['id']}/withdraw",
        json={"reason": "Trying to remove it"},
        headers=actors.headers["inst_a"],
    )
    assert response.status_code == 409


def test_database_blocks_evidence_changes_and_deletion(uploaded, db):
    for statement in (
        "UPDATE fdr_documents SET sha256 = 'x'",
        "UPDATE fdr_documents SET storage_key = 'abc'",
        "UPDATE fdr_documents SET original_filename = 'renamed.pdf'",
        "DELETE FROM fdr_documents",
    ):
        with pytest.raises(DatabaseError):
            db.execute(text(statement))
        db.rollback()


def test_withdrawal_cannot_be_reversed_in_database(client, actors, fdr_a, uploaded, db):
    client.post(
        f"/api/fdrs/{fdr_a['id']}/documents/{uploaded['id']}/withdraw",
        json={"reason": "Wrong file attached"},
        headers=actors.headers["inst_a"],
    )
    with pytest.raises(DatabaseError, match="withdrawal cannot be changed"):
        db.execute(text("UPDATE fdr_documents SET withdrawn_at = NULL, withdrawn_by_id = NULL, withdrawal_reason = NULL"))
    db.rollback()


# ---------- failure cleanup ----------


def test_database_failure_removes_written_file(actors, fdr_a, db, monkeypatch):
    def broken_audit(*args, **kwargs):
        raise RuntimeError("simulated database failure")

    monkeypatch.setattr("app.api.routes.documents._audit_document", broken_audit)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = upload(client, actors.headers["inst_a"], fdr_a["id"], PDF_BYTES)
    assert response.status_code == 500
    assert stored_files() == []
    assert db.scalar(select(FDRDocument.id)) is None


def test_failed_write_leaves_no_partial_file(actors, fdr_a, db, monkeypatch):
    def broken_replace(*args, **kwargs):
        raise OSError("simulated disk failure")

    monkeypatch.setattr(document_storage.os, "replace", broken_replace)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = upload(client, actors.headers["inst_a"], fdr_a["id"], PDF_BYTES)
    assert response.status_code == 500
    assert stored_files() == []  # no .part leftovers either
    assert db.scalar(select(FDRDocument.id)) is None


def test_missing_fdr_copy_filter(client, actors, create_fdr):
    inst_a = actors.headers["inst_a"]
    with_copy = create_fdr(inst_a, fdr_number="COPY-1")
    only_letter = create_fdr(inst_a, fdr_number="COPY-2")
    withdrawn = create_fdr(inst_a, fdr_number="COPY-3")
    nothing = create_fdr(inst_a, fdr_number="COPY-4")
    create_fdr(actors.headers["inst_b"], fdr_number="COPY-B")  # other institution, no documents

    upload(client, inst_a, with_copy["id"], PDF_BYTES)
    upload(client, inst_a, only_letter["id"], PNG_BYTES, filename="letter.png", document_type="BANK_LETTER")
    doc = upload(client, inst_a, withdrawn["id"], JPEG_BYTES, filename="copy.jpg").json()
    client.post(f"/api/fdrs/{withdrawn['id']}/documents/{doc['id']}/withdraw", json={"reason": "Wrong file"}, headers=inst_a)

    def missing(headers):
        response = client.get("/api/fdrs", params={"missing_fdr_copy": True, "sort": "oldest"}, headers=headers)
        assert response.status_code == 200
        return [item["fdr_number"] for item in response.json()["items"]]

    assert missing(inst_a) == ["COPY-2", "COPY-3", "COPY-4"]  # institution-scoped, as before
    assert missing(actors.headers["aicte"]) == ["COPY-2", "COPY-3", "COPY-4", "COPY-B"]
    assert missing(actors.headers["inst_b"]) == ["COPY-B"]
    assert nothing["fdr_number"] in missing(inst_a)
    assert client.get("/api/fdrs", params={"missing_fdr_copy": True}, headers=actors.headers["bank"]).status_code == 403
