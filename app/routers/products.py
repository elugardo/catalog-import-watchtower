"""`GET /api/products`: the catalog, newest `updated_at` first (spec section 4 F3, section 7).

The only list the UI pages (**Load more**, #6): request with `offset` = the
items received so far until that equals `total`.
"""

from fastapi import APIRouter

from app.schemas import ErrorOut, Page, ProductOut
from app.schemas.query import DEFAULT_LIMIT, Limit, Offset, VendorId
from app.services import lists

router = APIRouter(tags=["catalog"])


@router.get(
    "/products",
    response_model=Page[ProductOut],
    summary="Catalog products, newest `updated_at` first",
    responses={400: {"model": ErrorOut}, 500: {"model": ErrorOut}},
)
def list_products(
    vendor_id: VendorId = None, limit: Limit = DEFAULT_LIMIT, offset: Offset = 0
) -> Page[ProductOut]:
    return lists.list_products(vendor_id, limit, offset)
