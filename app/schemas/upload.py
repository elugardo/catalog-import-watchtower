"""Request side of `POST /api/imports`: the checks that need no parsing (spec section 4 F1).

Pure helpers, no database. The router runs them in the order of `_docs/api.md`
-> *Upload checks*: field presence, field values, filename and content type,
size, encoding. Each failing check raises `UploadRejected`, which the router
turns into the one error shape, before any record exists.
"""

from dataclasses import dataclass

# 256 KiB. The handler reads at most one byte more than this from the file part.
MAX_UPLOAD_BYTES = 256 * 1024
MAX_VENDOR_NAME_LENGTH = 80

ALLOWED_CONTENT_TYPES = frozenset(
    {"text/csv", "text/plain", "application/vnd.ms-excel", "application/octet-stream"}
)
# RFC 7578 section 4.4: a file part without a Content-Type is text/plain.
DEFAULT_PART_CONTENT_TYPE = "text/plain"

_UTF8_BOM = b"\xef\xbb\xbf"


class UploadRejected(Exception):
    """A no-parse check failed; nothing has been written."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


@dataclass(frozen=True)
class UploadRequest:
    """A request that passed every no-parse check."""

    vendor_name: str  # trimmed display name
    filename: str
    data: bytes  # the raw upload, BOM included, at most MAX_UPLOAD_BYTES
    inject_transient_failure: bool


def missing(field: str) -> UploadRejected:
    return UploadRejected(400, "MISSING_FIELD", f"{field} is required")


def invalid(message: str) -> UploadRejected:
    return UploadRejected(400, "INVALID_FIELD", message)


def clean_vendor_name(value: str) -> str:
    """Trimmed vendor name of 1 to 80 printable characters, or `INVALID_FIELD`."""
    name = value.strip()
    if not 1 <= len(name) <= MAX_VENDOR_NAME_LENGTH or not name.isprintable():
        raise invalid(f"vendor_name must be 1 to {MAX_VENDOR_NAME_LENGTH} printable characters")
    return name


def parse_injection_flag(value: str | None) -> bool:
    """`"true"` or `"false"` exactly; absent means false."""
    if value is None:
        return False
    if value == "true":
        return True
    if value == "false":
        return False
    raise invalid('inject_transient_failure must be "true" or "false"')


def check_file_type(filename: str | None, content_type: str | None) -> None:
    """Filename ends in `.csv` (any case); content type allowed, parameters ignored."""
    if not filename or not filename.lower().endswith(".csv"):
        raise UploadRejected(400, "INVALID_CONTENT_TYPE", "file must be a .csv")
    media_type = (content_type or "").split(";", 1)[0].strip().lower()
    if not media_type:
        media_type = DEFAULT_PART_CONTENT_TYPE
    if media_type not in ALLOWED_CONTENT_TYPES:
        raise UploadRejected(
            400,
            "INVALID_CONTENT_TYPE",
            "file content type must be text/csv, text/plain, application/vnd.ms-excel "
            "or application/octet-stream",
        )


def check_size(data: bytes) -> None:
    if len(data) > MAX_UPLOAD_BYTES:
        raise UploadRejected(413, "FILE_TOO_LARGE", "CSV exceeds 256 KiB")


def check_encoding(data: bytes) -> None:
    """UTF-8, with or without a BOM."""
    try:
        data.removeprefix(_UTF8_BOM).decode("utf-8")
    except UnicodeDecodeError:
        raise UploadRejected(400, "INVALID_ENCODING", "file is not valid UTF-8") from None
