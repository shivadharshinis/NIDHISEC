"""OCR fallback for scanned PDFs, using a fake engine so the suite does not need Tesseract."""

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.models import ReviewDecision
from app.services import extraction
from app.services.extraction import NO_TEXT_NOTE, OCR_MAX_PAGES, TesseractEngine, render_pdf_pages
from app.services.file_validation import MAX_IMAGE_PIXELS
from tests.test_documents import upload
from tests.test_screening import codes, fdr, finding, make_text_pdf, receipt, receipt_lines, run  # noqa: F401


def make_scanned_pdf(pages: int = 1, width: int = 612, height: int = 792) -> bytes:
    """A valid PDF whose pages have no text layer, like a scan without OCR text."""
    kids = " ".join(f"{3 + i} 0 R" for i in range(pages))
    objects = ["<< /Type /Catalog /Pages 2 0 R >>", f"<< /Type /Pages /Kids [{kids}] /Count {pages} >>"]
    objects += [f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {width} {height}] >>" for _ in range(pages)]
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


class FakeOcr:
    """Returns fixed text for every page, or raises the given error; records what it was asked to read."""

    def __init__(self, text: str = "", *, available: bool = True, error: Exception | None = None):
        self.text, self._available, self.error = text, available, error
        self.images: list = []
        self.timeouts: list[int] = []

    def available(self) -> bool:
        return self._available

    def image_to_text(self, image, timeout_seconds: int) -> str:
        self.images.append(image.size)
        self.timeouts.append(timeout_seconds)
        if self.error:
            raise self.error
        return self.text


@pytest.fixture
def ocr_on(monkeypatch):
    monkeypatch.setattr(get_settings(), "ocr_enabled", True)


def use_engine(monkeypatch, engine: FakeOcr) -> FakeOcr:
    monkeypatch.setattr(extraction, "OCR_ENGINE", engine)
    return engine


def scan(client, actors, fdr, pdf: bytes | None = None):  # noqa: F811
    response = upload(client, actors.headers["inst_a"], fdr["id"], pdf or make_scanned_pdf(), filename="scan.pdf")
    assert response.status_code == 201, response.text
    result = run(client, actors, fdr["id"]).json()
    assert result["status"] == "COMPLETED"
    return result


# ---------- 1. successful OCR ----------


def test_ocr_reads_scanned_receipt_and_compares(client, actors, fdr, ocr_on, monkeypatch):  # noqa: F811
    engine = use_engine(monkeypatch, FakeOcr("\n".join(receipt_lines(fdr, actors.institution_a.name))))
    result = scan(client, actors, fdr)

    doc = result["extraction"][0]
    assert doc["method"] == "tesseract-ocr" and doc["status"] == "EXTRACTED" and doc["pages_read"] == 1
    assert "Recognition errors are possible" in doc["note"]
    fields = {f["field"]: f["value"] for f in doc["fields"]}
    assert fields["amount"] == fdr["amount"] and fields["fdr_number"] == fdr["fdr_number"]

    ocr_finding = finding(result, "DOC_READ_BY_OCR")
    assert ocr_finding["severity"] == "INFO" and "check each value" in ocr_finding["reason"]
    assert not codes(result) & {"DOC_NO_TEXT_LAYER", "DOC_AMOUNT_MISMATCH", "DOC_FDR_NUMBER_MISMATCH", "DOC_KEY_FIELDS_NOT_FOUND"}
    assert result["review_priority"] == "LOW"
    assert engine.timeouts == [get_settings().ocr_page_timeout_seconds]
    assert result["engine_version"].endswith("pdf-text/1.1+ocr-fallback")


# ---------- 2. disabled or unavailable ----------


def test_ocr_disabled_keeps_no_text_layer(client, actors, fdr, monkeypatch):  # noqa: F811
    assert get_settings().ocr_enabled is False  # the default
    engine = use_engine(monkeypatch, FakeOcr("FDR No: SHOULD-NOT-BE-READ"))
    result = scan(client, actors, fdr)
    doc = result["extraction"][0]
    assert (doc["status"], doc["method"], doc["note"]) == ("NO_TEXT_LAYER", "pypdf-text-layer", NO_TEXT_NOTE)
    assert finding(result, "DOC_NO_TEXT_LAYER")["reason"].startswith("OCR is not available")
    assert "DOC_READ_BY_OCR" not in codes(result)
    assert engine.images == []


def test_ocr_engine_unavailable(client, actors, fdr, ocr_on, monkeypatch):  # noqa: F811
    engine = use_engine(monkeypatch, FakeOcr("FDR No: X", available=False))
    result = scan(client, actors, fdr)
    doc = result["extraction"][0]
    assert doc["status"] == "NO_TEXT_LAYER" and "Tesseract was not found" in doc["note"]
    assert "DOC_NO_TEXT_LAYER" in codes(result) and "DOC_READ_BY_OCR" not in codes(result)
    assert engine.images == []


def test_real_tesseract_engine_reports_missing_binary(monkeypatch):
    monkeypatch.setattr(get_settings(), "ocr_tesseract_cmd", "C:/no/such/folder/tesseract.exe")
    assert TesseractEngine().available() is False


# ---------- 3. failure and timeout ----------


@pytest.mark.parametrize(("error", "note"), [
    (RuntimeError("engine crashed"), "OCR could not read the pages"),
    (TimeoutError("too slow"), "OCR timed out (limit 15s per page)"),
])
def test_ocr_failure_and_timeout_fall_back(client, actors, fdr, ocr_on, monkeypatch, error, note):  # noqa: F811
    use_engine(monkeypatch, FakeOcr(error=error))
    result = scan(client, actors, fdr)
    doc = result["extraction"][0]
    assert doc["status"] == "NO_TEXT_LAYER" and note in doc["note"]
    assert finding(result, "DOC_NO_TEXT_LAYER")["reason"].startswith("OCR could not read it")
    assert "DOC_READ_BY_OCR" not in codes(result)


def test_ocr_finding_no_text_falls_back(client, actors, fdr, ocr_on, monkeypatch):  # noqa: F811
    use_engine(monkeypatch, FakeOcr("   \n "))
    doc = scan(client, actors, fdr)["extraction"][0]
    assert doc["status"] == "NO_TEXT_LAYER" and "OCR found no readable text" in doc["note"]


def test_tesseract_timeout_becomes_timeout_error(monkeypatch):
    import pytesseract

    def slow(*args, **kwargs):
        raise RuntimeError("Tesseract process timeout")

    monkeypatch.setattr(pytesseract, "image_to_string", slow)
    with pytest.raises(TimeoutError):
        TesseractEngine().image_to_text(object(), 1)


# ---------- 4. OCR mismatches capped at warning ----------


def test_ocr_mismatches_are_capped_at_warning(client, actors, fdr, ocr_on, monkeypatch):  # noqa: F811
    lines = receipt_lines(fdr, actors.institution_a.name, number="SCR-10007", amount="Rs. 2,80,000.00")
    use_engine(monkeypatch, FakeOcr("\n".join(lines)))
    result = scan(client, actors, fdr)
    for code in ("DOC_AMOUNT_MISMATCH", "DOC_FDR_NUMBER_MISMATCH"):
        item = finding(result, code)
        assert item["severity"] == "WARNING", code
        assert "read by OCR" in item["reason"] and "check it against the original document" in item["reason"]
    assert result["high_count"] == 0 and result["review_priority"] == "MEDIUM"


def test_same_mismatch_from_text_layer_stays_high(client, actors, fdr):  # noqa: F811
    lines = receipt_lines(fdr, actors.institution_a.name, amount="Rs. 2,80,000.00")
    result = scan(client, actors, fdr, make_text_pdf(lines))
    assert finding(result, "DOC_AMOUNT_MISMATCH")["severity"] == "HIGH"
    assert "OCR" not in finding(result, "DOC_AMOUNT_MISMATCH")["reason"]


# ---------- 5. text PDFs unchanged, limits ----------


def test_text_pdf_never_uses_ocr(client, actors, fdr, receipt, ocr_on, monkeypatch):  # noqa: F811
    engine = use_engine(monkeypatch, FakeOcr("FDR No: SHOULD-NOT-BE-READ"))
    result = run(client, actors, fdr["id"]).json()
    doc = result["extraction"][0]
    assert doc["method"] == "pypdf-text-layer" and doc["status"] == "EXTRACTED" and doc["note"] is None
    assert "DOC_READ_BY_OCR" not in codes(result) and engine.images == []


def test_ocr_reads_at_most_three_pages(client, actors, fdr, ocr_on, monkeypatch):  # noqa: F811
    engine = use_engine(monkeypatch, FakeOcr("\n".join(receipt_lines(fdr, actors.institution_a.name))))
    doc = scan(client, actors, fdr, make_scanned_pdf(pages=5))["extraction"][0]
    assert len(engine.images) == OCR_MAX_PAGES and doc["pages_read"] == OCR_MAX_PAGES
    assert f"Only the first {OCR_MAX_PAGES} page(s) were read by OCR." in doc["note"]


def test_rendering_respects_the_image_pixel_limit():
    images, total = render_pdf_pages(make_scanned_pdf(width=14_000, height=14_000), OCR_MAX_PAGES)
    assert total == 1
    width, height = images[0].size
    assert width * height <= MAX_IMAGE_PIXELS
    normal, _ = render_pdf_pages(make_scanned_pdf(), OCR_MAX_PAGES)
    assert normal[0].size == (1700, 2200)  # A4/Letter-sized page at 200 DPI


# ---------- 6. workflow untouched ----------


def test_ocr_screening_changes_no_record_or_permissions(client, actors, fdr, ocr_on, monkeypatch, db):  # noqa: F811
    lines = receipt_lines(fdr, actors.institution_a.name, amount="Rs. 1.00")
    use_engine(monkeypatch, FakeOcr("\n".join(lines)))
    before = client.get(f"/api/fdrs/{fdr['id']}", headers=actors.headers["aicte"]).json()
    scan(client, actors, fdr)
    after = client.get(f"/api/fdrs/{fdr['id']}", headers=actors.headers["aicte"]).json()
    assert (after["status"], after["version"]) == (before["status"], before["version"]) == ("SUBMITTED", 1)
    assert db.scalars(select(ReviewDecision)).all() == []
    for who in ("inst_a", "bank"):
        assert run(client, actors, fdr["id"], who).status_code == 403
