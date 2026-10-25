"""`GET /api/vendors`: the vendor filter options, newest first (spec section 7)."""

from fastapi import APIRouter

from app.schemas import ErrorOut, Page, VendorOut
from app.schemas.query import DEFAULT_LIMIT, Limit, Offset
from app.services import lists

router = APIRouter(tags=["catalog"])


@router.get(
    "/vendors",
    response_model=Page[VendorOut],
    summary="Vendor filter options",
    responses={400: {"model": ErrorOut}, 500: {"model": ErrorOut}},
)
def list_vendors(limit: Limit = DEFAULT_LIMIT, offset: Offset = 0) -> Page[VendorOut]:
    return lists.list_vendors(limit, offset)
