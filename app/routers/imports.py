"""`POST /api/imports`, `GET /api/imports` and `GET /api/imports/{id}` (spec section 4 F1
to F3, section 7).

No route here answers 422: the upload parses its own form, a bad query value is
400 `INVALID_QUERY` and a bad id is 404 (`app.main`), and the 422 FastAPI would
list in the generated schema is removed there too.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Request
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.formparsers import MultiPartException

from app.schemas import ErrorOut, ImportDetailOut, ImportOut, Page
from app.schemas.query import DEFAULT_LIMIT, MAX_BIGINT, Limit, Offset
from app.schemas.upload import (
    MAX_UPLOAD_BYTES,
    UploadRequest,
    check_encoding,
    check_file_type,
    check_size,
    clean_vendor_name,
    invalid,
    missing,
    parse_injection_flag,
)
from app.services import importer, lists

router = APIRouter(tags=["imports"])

# The request body as `openapi.yaml` describes it. The handler parses the form
# itself (so that no request ever ends in FastAPI's 422), which means FastAPI
# cannot infer this part of the schema.
_UPLOAD_REQUEST_BODY = {
    "required": True,
    "content": {
        "multipart/form-data": {
            "schema": {
                "type": "object",
                "required": ["vendor_name", "file"],
                "properties": {
                    "vendor_name": {"type": "string"},
                    "file": {"type": "string", "format": "binary"},
                    "inject_transient_failure": {
                        "type": "string",
                        "enum": ["true", "false"],
                        "default": "false",
                    },
                },
            }
        }
    },
}


async def read_upload(request: Request) -> UploadRequest:
    """Run the no-parse checks in their documented order; raises `UploadRejected`.

    Order (`_docs/api.md` -> *Upload checks*): field presence, field values,
    filename and content type, size, encoding. The file part is read with a
    bounded read of at most 256 KiB + 1 byte; Starlette's parser may still
    spool the whole part to a temporary file.
    """
    try:
        form = await request.form()
    except (StarletteHTTPException, MultiPartException):
        # Starlette re-raises a parser error as its own HTTPException, which
        # FastAPI's subclass would not catch.
        raise invalid("the request body is not a valid multipart form") from None
    try:
        # 1. Presence.
        if "vendor_name" not in form:
            raise missing("vendor_name")
        if "file" not in form:
            raise missing("file")

        # 2. Values.
        vendor_field = form["vendor_name"]
        if not isinstance(vendor_field, str):
            raise invalid("vendor_name must be a text field")
        vendor_name = clean_vendor_name(vendor_field)
        flag_field = form.get("inject_transient_failure")
        if flag_field is not None and not isinstance(flag_field, str):
            raise invalid('inject_transient_failure must be "true" or "false"')
        inject = parse_injection_flag(flag_field)
        upload = form["file"]
        if not isinstance(upload, UploadFile):
            raise invalid("file must be a file part")

        # 3. Filename and content type.
        filename = upload.filename or ""
        check_file_type(filename, upload.content_type)

        # 4. Size: a bounded read, never trusting Content-Length.
        data = await upload.read(MAX_UPLOAD_BYTES + 1)
        check_size(data)

        # 5. Encoding.
        check_encoding(data)
    finally:
        await form.close()

    return UploadRequest(
        vendor_name=vendor_name,
        filename=filename,
        data=data,
        inject_transient_failure=inject,
    )


@router.post(
    "/imports",
    status_code=201,
    response_model=ImportDetailOut,
    summary="Upload a CSV and process it",
    responses={400: {"model": ErrorOut}, 413: {"model": ErrorOut}},
    openapi_extra={"requestBody": _UPLOAD_REQUEST_BODY},
)
def create_import(upload: Annotated[UploadRequest, Depends(read_upload)]) -> ImportDetailOut:
    """Create the import and process it synchronously; 201 whatever the outcome."""
    import_id = importer.create_import(upload)
    importer.run_attempt(import_id, 1)
    detail = importer.load_import_detail(import_id)
    assert detail is not None  # the row was committed above and imports are never deleted
    return detail


@router.get(
    "/imports",
    response_model=Page[ImportOut],
    summary="Recent imports, newest first",
    responses={400: {"model": ErrorOut}},
)
def list_imports(limit: Limit = DEFAULT_LIMIT, offset: Offset = 0) -> Page[ImportOut]:
    """The import resource without `attempts`, `alert` and `agent_actions`."""
    return lists.list_imports(limit, offset)


@router.get(
    "/imports/{id}",
    response_model=ImportDetailOut,
    summary="One import with its errors, attempts, alert and agent activity",
    responses={404: {"model": ErrorOut}},
)
def get_import(id: Annotated[int, Path(ge=1)]) -> ImportDetailOut:  # the contract names it `id`
    import_id = id
    # A larger id cannot exist and is a 404, not a database error.
    detail = importer.load_import_detail(import_id) if import_id <= MAX_BIGINT else None
    if detail is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": f"import {import_id} not found"},
        )
    return detail
