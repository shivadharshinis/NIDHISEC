"""Conservative field extraction from supporting documents.

What this does:
  * Reads the *text layer* of PDFs locally with pypdf. Nothing is sent to any
    external service.
  * Finds a small set of labelled fields (FDR number, amount, issue/maturity
    dates, IFSC, bank name, depositor/holder) with explicit patterns, keeping a
    short source snippet and page number for each value.

  * Optionally (NIDHISEC_OCR_ENABLED), when a PDF has no text layer at all,
    renders its first pages with pypdfium2 and reads them with a local
    Tesseract install. The same labelled-field patterns are applied, and the
    result is marked as OCR so screening treats its values with caution.

What it does not do:
  * No OCR for image uploads, and no OCR at all unless it is enabled and
    Tesseract is installed: such documents are reported as needing manual review.
  * No guessing: a field is reported only when a labelled pattern matches;
    missing values stay missing.
  * Extraction proves nothing about whether a document is genuine.

The original bytes are only read, never modified. Full document text is not
returned or stored, only the matched snippets.
"""

import io
import logging
import math
import re
from dataclasses import asdict, dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Protocol

from app.core.config import get_settings
from app.services.file_validation import MAX_IMAGE_PIXELS

logger = logging.getLogger(__name__)

EXTRACTOR_VERSION = "pdf-text/1.1+ocr-fallback"
MAX_PAGES = 20
MAX_TEXT_CHARS = 200_000
SNIPPET_CHARS = 120


@dataclass
class ExtractedField:
    field: str
    value: str  # normalised: dates ISO, amounts "1234.50", IFSC upper-case
    raw: str  # source snippet (truncated line)
    page: int


@dataclass
class ExtractionResult:
    status: str  # EXTRACTED | NO_FIELDS_FOUND | NO_TEXT_LAYER | UNSUPPORTED_FORMAT | FAILED
    method: str | None
    pages_read: int = 0
    fields: list[ExtractedField] = field(default_factory=list)
    note: str | None = None

    def values(self, name: str) -> list[ExtractedField]:
        return [f for f in self.fields if f.field == name]

    def to_dict(self) -> dict:
        return asdict(self)


class Extractor(Protocol):
    def supports(self, content_type: str) -> bool: ...
    def extract(self, data: bytes) -> ExtractionResult: ...


# ---------- value parsing ----------

_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
DATE_PATTERN = (
    r"(\d{1,2}[/.\-]\d{1,2}[/.\-]\d{4}"
    r"|\d{4}-\d{2}-\d{2}"
    r"|\d{1,2}[\s\-](?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?[\s\-,]+\d{4})"
)


def parse_date(text: str) -> date | None:
    """Day-first, as on Indian bank documents. Returns None when not a real date."""
    text = text.strip().lower()
    try:
        if m := re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", text):
            return date(int(m[1]), int(m[2]), int(m[3]))
        if m := re.fullmatch(r"(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4})", text):
            return date(int(m[3]), int(m[2]), int(m[1]))
        if m := re.fullmatch(r"(\d{1,2})[\s\-]([a-z]{3})[a-z]*\.?[\s\-,]+(\d{4})", text):
            month = _MONTHS.get(m[2])
            return date(int(m[3]), month, int(m[1])) if month else None
    except ValueError:
        return None
    return None


def parse_amount(text: str) -> Decimal | None:
    cleaned = text.replace(",", "").strip()
    if not re.fullmatch(r"\d{1,13}(\.\d{1,2})?", cleaned):
        return None
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        return None
    return value.quantize(Decimal("0.01")) if value > 0 else None


# ---------- labelled patterns (case-insensitive, one line at a time) ----------

_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("fdr_number", re.compile(
        r"\b(?:FDR|FD|TDR|Fixed\s+Deposit|Deposit|Receipt)\s*(?:Receipt\s*)?(?:No\.?|Number|#)\s*[:\-]?\s*"
        r"([A-Za-z0-9][A-Za-z0-9/.\-]{2,49})", re.I)),
    ("amount", re.compile(
        r"\b(?:Deposit\s+Amount|Principal(?:\s+Amount)?|Amount\s+of\s+Deposit|Amount)\s*(?:\([^)]*\))?\s*[:\-]?\s*"
        r"(?:Rs\.?|INR|₹)?\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)", re.I)),
    ("issue_date", re.compile(
        r"(?:Date\s+of\s+(?:Issue|Deposit)|Issue\s+Date|Deposit\s+Date|Value\s+Date|Issued\s+on)\s*[:\-]?\s*" + DATE_PATTERN,
        re.I)),
    ("maturity_date", re.compile(
        r"(?:Maturity\s+Date|Date\s+of\s+Maturity|Due\s+Date|Matures\s+on)\s*[:\-]?\s*" + DATE_PATTERN, re.I)),
    ("holder", re.compile(
        r"(?:Name\s+of\s+(?:the\s+)?Depositor|Depositor(?:'s)?\s+Name|Depositor|Account\s+Holder|In\s+(?:the\s+)?favou?r\s+of)"
        r"\s*[:\-]\s*(.{3,150})", re.I)),
    ("bank_name", re.compile(r"^\s*(?:Bank\s*Name|Issuing\s+Bank|Bank)\s*[:\-]\s*(.{2,150})$", re.I)),
]
_IFSC = re.compile(r"\b([A-Z]{4}0[A-Z0-9]{6})\b")
_BANK_TITLE = re.compile(r"^\s*([A-Za-z][A-Za-z .&()'\-]{1,100}\bBank\b[A-Za-z .&()'\-]{0,60})\s*$", re.I)


def _snippet(line: str) -> str:
    line = " ".join(line.split())
    return line if len(line) <= SNIPPET_CHARS else line[: SNIPPET_CHARS - 1] + "…"


def extract_fields_from_text(pages: list[str]) -> list[ExtractedField]:
    found: list[ExtractedField] = []
    seen: set[tuple[str, str]] = set()

    def add(name: str, value: str, line: str, page: int) -> None:
        if (name, value) not in seen:
            seen.add((name, value))
            found.append(ExtractedField(name, value, _snippet(line), page))

    for page_number, text in enumerate(pages, start=1):
        for line in text.splitlines():
            if not line.strip():
                continue
            lowered = line.lower()
            for name, pattern in _PATTERNS:
                match = pattern.search(line)
                if not match:
                    continue
                raw = match.group(1).strip()
                if name == "amount":
                    # Maturity values and interest are different amounts from the deposit.
                    if "maturity" in lowered or "interest" in lowered:
                        continue
                    amount = parse_amount(raw)
                    if amount is not None:
                        add(name, f"{amount:.2f}", line, page_number)
                elif name in ("issue_date", "maturity_date"):
                    parsed = parse_date(raw)
                    if parsed is not None:
                        add(name, parsed.isoformat(), line, page_number)
                elif name == "fdr_number":
                    add(name, raw.rstrip(".-/"), line, page_number)
                else:
                    add(name, " ".join(raw.split()), line, page_number)
            for ifsc in _IFSC.findall(line):
                add("ifsc_code", ifsc, line, page_number)
            if page_number == 1 and ":" not in line and (title := _BANK_TITLE.match(line)):
                add("bank_name", " ".join(title.group(1).split()), line, page_number)
    return found


# ---------- extractors ----------


class PdfTextExtractor:
    """Reads the embedded text layer of a PDF with pypdf (pure Python, local)."""

    method = "pypdf-text-layer"

    def supports(self, content_type: str) -> bool:
        return content_type == "application/pdf"

    def extract(self, data: bytes) -> ExtractionResult:
        from pypdf import PdfReader

        try:
            reader = PdfReader(io.BytesIO(data))
            pages: list[str] = []
            total = 0
            for page in reader.pages[:MAX_PAGES]:
                text = page.extract_text() or ""
                total += len(text)
                if total > MAX_TEXT_CHARS:
                    break
                pages.append(text)
            truncated = len(reader.pages) > MAX_PAGES or total > MAX_TEXT_CHARS
        except Exception:  # pypdf raises many error types for damaged files
            logger.warning("PDF text extraction failed", exc_info=True)
            return ExtractionResult("FAILED", self.method, note="The PDF could not be read; manual review needed.")

        if not any(text.strip() for text in pages):
            return ocr_fallback(data, len(pages)) or ExtractionResult(
                "NO_TEXT_LAYER", self.method, len(pages), note=NO_TEXT_NOTE,
            )
        fields = extract_fields_from_text(pages)
        note = f"Only the first {len(pages)} page(s) were read." if truncated else None
        if not fields:
            return ExtractionResult("NO_FIELDS_FOUND", self.method, len(pages), [],
                                    note or "Text was readable but no supported labelled fields were found.")
        return ExtractionResult("EXTRACTED", self.method, len(pages), fields, note)


# ---------- OCR fallback for scanned PDFs ----------

OCR_METHOD = "tesseract-ocr"
OCR_MAX_PAGES = 3
OCR_DPI = 200
OCR_WARNING = (
    "Read by OCR from a scanned image. Recognition errors are possible: check every value against the "
    "original document before relying on it."
)
NO_TEXT_NOTE = "No readable text (probably a scanned image). OCR is not available; manual review needed."


class OcrEngine(Protocol):
    def available(self) -> bool: ...
    def image_to_text(self, image, timeout_seconds: int) -> str: ...


class TesseractEngine:
    """Local Tesseract through pytesseract. Nothing leaves the machine."""

    @staticmethod
    def _pytesseract():
        import pytesseract

        command = get_settings().ocr_tesseract_cmd
        if command:
            pytesseract.pytesseract.tesseract_cmd = command
        return pytesseract

    def available(self) -> bool:
        try:
            self._pytesseract().get_tesseract_version()
            return True
        except Exception:  # not installed, not on PATH, or cannot start
            return False

    def image_to_text(self, image, timeout_seconds: int) -> str:
        pytesseract = self._pytesseract()
        try:
            return pytesseract.image_to_string(image, lang="eng", timeout=timeout_seconds)
        except RuntimeError as exc:
            # pytesseract kills the process and raises RuntimeError("Tesseract process timeout").
            if "timeout" in str(exc).lower():
                raise TimeoutError(str(exc)) from exc
            raise


OCR_ENGINE: OcrEngine = TesseractEngine()


def render_pdf_pages(data: bytes, max_pages: int) -> tuple[list, int]:
    """Render the first pages as images within the upload image-pixel limit. Returns (images, page count)."""
    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(data)
    try:
        images = []
        for index in range(min(len(document), max_pages)):
            page = document[index]
            try:
                width, height = page.get_size()  # in points (1/72 inch)
                if width <= 0 or height <= 0:
                    raise ValueError("page has no size")
                scale = OCR_DPI / 72
                if width * height * scale * scale > MAX_IMAGE_PIXELS:
                    scale = math.sqrt(MAX_IMAGE_PIXELS / (width * height))
                bitmap = page.render(scale=scale)
                images.append(bitmap.to_pil().copy())  # copy: the bitmap's memory is freed on close
                bitmap.close()
            finally:
                page.close()
        return images, len(document)
    finally:
        document.close()


def ocr_fallback(data: bytes, pages_without_text: int) -> ExtractionResult | None:
    """OCR a PDF that has no text layer.

    Returns None when OCR is disabled, so the caller keeps its usual result.
    Any problem (engine missing, render or OCR error, timeout, nothing read)
    gives the usual NO_TEXT_LAYER result with a note saying why.
    """
    settings = get_settings()
    if not settings.ocr_enabled:
        return None

    def no_text(reason: str) -> ExtractionResult:
        return ExtractionResult(
            "NO_TEXT_LAYER", PdfTextExtractor.method, pages_without_text,
            note=f"No readable text (probably a scanned image). OCR {reason}; manual review needed.",
        )

    if not OCR_ENGINE.available():
        return no_text("is enabled but Tesseract was not found")
    try:
        images, total_pages = render_pdf_pages(data, OCR_MAX_PAGES)
        texts: list[str] = []
        length = 0
        for image in images:
            text = OCR_ENGINE.image_to_text(image, settings.ocr_page_timeout_seconds) or ""
            length += len(text)
            if length > MAX_TEXT_CHARS:
                break
            texts.append(text)
    except TimeoutError:
        logger.warning("OCR timed out", exc_info=True)
        return no_text(f"timed out (limit {settings.ocr_page_timeout_seconds}s per page)")
    except Exception:
        logger.warning("OCR failed", exc_info=True)
        return no_text("could not read the pages")

    if not any(text.strip() for text in texts):
        return no_text("found no readable text")
    notes = [OCR_WARNING]
    if total_pages > len(texts):
        notes.append(f"Only the first {len(texts)} page(s) were read by OCR.")
    fields = extract_fields_from_text(texts)
    if not fields:
        notes.append("No supported labelled fields were found.")
    return ExtractionResult("EXTRACTED" if fields else "NO_FIELDS_FOUND", OCR_METHOD, len(texts), fields, " ".join(notes))


EXTRACTORS: list[Extractor] = [PdfTextExtractor()]


def extract_document(data: bytes, content_type: str) -> ExtractionResult:
    for extractor in EXTRACTORS:
        if extractor.supports(content_type):
            return extractor.extract(data)
    return ExtractionResult(
        "UNSUPPORTED_FORMAT", None,
        note="Field extraction is not available for this file type (no OCR for images); manual review needed.",
    )
