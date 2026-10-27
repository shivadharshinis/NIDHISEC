"""Private on-disk storage for uploaded documents.

Files are addressed only by random server-generated keys and stored outside
any publicly served directory. Client-supplied names never reach the
filesystem. Writes are atomic: data goes to a temporary file in the target
directory, is flushed to disk and then renamed into place, so a crash or error
never leaves a partial file under a real key.
"""

import hashlib
import os
import re
import secrets
import tempfile
from dataclasses import dataclass
from pathlib import Path

from app.core.config import get_settings

_KEY_PATTERN = re.compile(r"^[0-9a-f]{32}$")
_TEMP_SUFFIX = ".part"


class StorageKeyError(ValueError):
    pass


def storage_root() -> Path:
    root = get_settings().document_storage_path
    root.mkdir(parents=True, exist_ok=True)
    return root


def new_storage_key() -> str:
    return secrets.token_hex(16)


def _path_for(key: str) -> Path:
    # Keys are validated so a tampered database value can never escape the root.
    if not _KEY_PATTERN.fullmatch(key):
        raise StorageKeyError("Invalid storage key")
    return storage_root() / key[:2] / key


def write_atomic(key: str, data: bytes) -> None:
    final_path = _path_for(key)
    final_path.parent.mkdir(parents=True, exist_ok=True)
    if final_path.exists():
        raise FileExistsError("Storage key already in use")
    fd, temp_name = tempfile.mkstemp(dir=final_path.parent, prefix=".", suffix=_TEMP_SUFFIX)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, final_path)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise


def delete(key: str) -> None:
    """Remove a stored file. Only used to clean up after a failed upload."""
    _path_for(key).unlink(missing_ok=True)


def read(key: str) -> bytes:
    """Raises FileNotFoundError when the stored file is missing."""
    return _path_for(key).read_bytes()


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class IntegrityResult:
    status: str  # "intact" | "mismatch" | "missing"
    actual_sha256: str | None
    data: bytes | None = None


def check_integrity(key: str, expected_sha256: str) -> IntegrityResult:
    try:
        data = read(key)
    except FileNotFoundError:
        return IntegrityResult("missing", None)
    actual = sha256_hex(data)
    if not secrets.compare_digest(actual, expected_sha256):
        return IntegrityResult("mismatch", actual)
    return IntegrityResult("intact", actual, data)


def list_stored_files() -> list[Path]:
    """All files under the storage root, including temporary ones (used by tests and maintenance)."""
    root = storage_root()
    return [path for path in root.rglob("*") if path.is_file()]
