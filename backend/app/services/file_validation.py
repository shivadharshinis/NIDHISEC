"""Content-based validation of uploaded documents.

The file type is determined from the bytes themselves; the client-supplied
filename extension must agree with it, and the client-supplied MIME type is
ignored. Checks are structural and conservative. They reject malformed,
truncated and active-content files, but they are not an antivirus scan and
say nothing about whether a document is genuine.
"""

import re
import struct
import unicodedata
import zlib
from dataclasses import dataclass


class FileRejected(ValueError):
    """The upload was rejected. The message is safe to show to the user."""


@dataclass(frozen=True)
class FileKind:
    content_type: str
    extensions: tuple[str, ...]
    label: str


PDF = FileKind("application/pdf", (".pdf",), "PDF")
PNG = FileKind("image/png", (".png",), "PNG")
JPEG = FileKind("image/jpeg", (".jpg", ".jpeg"), "JPEG")
ALLOWED_KINDS = (PDF, PNG, JPEG)
ALLOWED_EXTENSIONS = tuple(ext for kind in ALLOWED_KINDS for ext in kind.extensions)

MAX_IMAGE_DIMENSION = 20_000
MAX_IMAGE_PIXELS = 100_000_000  # guards against decompression bombs

# PDF features that can execute code, launch programs or carry hidden payloads.
_PDF_ACTIVE_CONTENT = re.compile(rb"/(JavaScript|JS|Launch|EmbeddedFile|RichMedia|XFA|SubmitForm|ImportData)(?![A-Za-z0-9])")
_PDF_ENCRYPTED = re.compile(rb"/Encrypt(?![A-Za-z0-9])")
# Markup or script that would make the file a polyglot. Tags are long enough
# that random compressed image data practically never matches them.
_MARKUP = re.compile(rb"<(script|html|iframe|\?php)", re.IGNORECASE)

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _check_pdf(data: bytes) -> None:
    if not data.startswith(b"%PDF-1.") and not data.startswith(b"%PDF-2."):
        raise FileRejected("The file is not a valid PDF")
    if b"%%EOF" not in data[-2048:]:
        raise FileRejected("The PDF appears to be truncated or malformed")
    if _PDF_ENCRYPTED.search(data):
        raise FileRejected("Password-protected or encrypted PDFs are not accepted")
    if _PDF_ACTIVE_CONTENT.search(data):
        raise FileRejected("PDFs containing scripts, embedded files or other active content are not accepted")


def _check_png(data: bytes) -> None:
    if not data.startswith(_PNG_SIGNATURE):
        raise FileRejected("The file is not a valid PNG image")
    offset = len(_PNG_SIGNATURE)
    first = True
    while True:
        if offset + 12 > len(data):
            raise FileRejected("The PNG image is truncated or malformed")
        (length,) = struct.unpack(">I", data[offset : offset + 4])
        chunk_type = data[offset + 4 : offset + 8]
        end = offset + 12 + length
        if end > len(data):
            raise FileRejected("The PNG image is truncated or malformed")
        body = data[offset + 8 : offset + 8 + length]
        (crc,) = struct.unpack(">I", data[offset + 8 + length : end])
        if zlib.crc32(chunk_type + body) & 0xFFFFFFFF != crc:
            raise FileRejected("The PNG image is corrupted (checksum mismatch)")
        if first:
            if chunk_type != b"IHDR" or length != 13:
                raise FileRejected("The PNG image is malformed")
            width, height = struct.unpack(">II", body[:8])
            _check_dimensions(width, height)
            first = False
        if chunk_type == b"IEND":
            if data[end:].strip(b"\x00"):
                raise FileRejected("The PNG image has unexpected data after its end")
            return
        offset = end


def _check_jpeg(data: bytes) -> None:
    if not data.startswith(b"\xff\xd8\xff"):
        raise FileRejected("The file is not a valid JPEG image")
    if not data.rstrip(b"\x00").endswith(b"\xff\xd9"):
        raise FileRejected("The JPEG image is truncated or malformed")
    # Walk header segments up to the start of scan to find the frame dimensions.
    offset = 2
    while offset + 4 <= len(data):
        if data[offset] != 0xFF:
            raise FileRejected("The JPEG image is malformed")
        marker = data[offset + 1]
        if marker == 0xFF:  # fill byte
            offset += 1
            continue
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:  # markers without a length
            offset += 2
            continue
        (length,) = struct.unpack(">H", data[offset + 2 : offset + 4])
        if length < 2 or offset + 2 + length > len(data):
            raise FileRejected("The JPEG image is truncated or malformed")
        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            if length < 7:
                raise FileRejected("The JPEG image is malformed")
            height, width = struct.unpack(">HH", data[offset + 5 : offset + 9])
            _check_dimensions(width, height)
            return
        if marker == 0xDA:  # start of scan before any frame header
            break
        offset += 2 + length
    raise FileRejected("The JPEG image is malformed")


def _check_dimensions(width: int, height: int) -> None:
    if width == 0 or height == 0:
        raise FileRejected("The image has no pixels")
    if width > MAX_IMAGE_DIMENSION or height > MAX_IMAGE_DIMENSION or width * height > MAX_IMAGE_PIXELS:
        raise FileRejected("The image dimensions are too large")


def detect_kind(data: bytes) -> FileKind | None:
    if data.startswith(b"%PDF-"):
        return PDF
    if data.startswith(_PNG_SIGNATURE):
        return PNG
    if data.startswith(b"\xff\xd8\xff"):
        return JPEG
    return None


def sanitize_filename(raw: str | None, kind: FileKind) -> str:
    """A safe display name: no path components, control or reserved characters,
    limited length, and an extension matching the detected type."""
    name = (raw or "").replace("\\", "/").rsplit("/", 1)[-1]
    name = unicodedata.normalize("NFKC", name)
    name = "".join(ch for ch in name if unicodedata.category(ch)[0] != "C")
    name = re.sub(r"[^\w .()\-]", "_", name, flags=re.UNICODE)
    name = re.sub(r"\s+", " ", name).strip(" .")
    stem, dot, ext = name.rpartition(".")
    if not dot:
        stem, ext = name, ""
    stem = stem.strip(" .")[:120] or "document"
    extension = f".{ext.lower()}"
    if extension not in kind.extensions:
        extension = kind.extensions[0]
    return f"{stem}{extension}"


def validate_upload(data: bytes, filename: str | None, max_bytes: int) -> tuple[FileKind, str]:
    """Validate an upload and return its detected kind and a sanitised display name."""
    if not data:
        raise FileRejected("The file is empty")
    if len(data) > max_bytes:
        raise FileRejected(f"The file exceeds the {max_bytes // (1024 * 1024)} MB limit")

    extension = ""
    if filename and "." in filename:
        extension = "." + filename.rsplit(".", 1)[-1].strip().lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise FileRejected("Only PDF, PNG and JPEG files are accepted")

    kind = detect_kind(data)
    if kind is None:
        raise FileRejected("The file content is not a PDF, PNG or JPEG document")
    if extension not in kind.extensions:
        raise FileRejected(f"The file extension does not match its content (the file is a {kind.label})")

    {PDF: _check_pdf, PNG: _check_png, JPEG: _check_jpeg}[kind](data)
    if _MARKUP.search(data):
        raise FileRejected("The file contains embedded markup or script and was rejected")
    return kind, sanitize_filename(filename, kind)
