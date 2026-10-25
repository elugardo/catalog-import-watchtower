"""`GET /api/alerts`: current and recent incidents with their import summary (spec section 7).

Every alert whatever its status, newest first; the UI splits open from recent
(#5). Alerts are created by CIW-05 (#7), never through this API.
"""

from fastapi import APIRouter

from app.schemas import AlertListItemOut, ErrorOut, Page
from app.schemas.query import DEFAULT_LIMIT, Limit, Offset
from app.services import lists

router = APIRouter(tags=["alerts"])


@router.get(
    "/alerts",
    response_model=Page[AlertListItemOut],
    summary="Current and recent incidents with their import summary",
    responses={400: {"model": ErrorOut}},
)
def list_alerts(limit: Limit = DEFAULT_LIMIT, offset: Offset = 0) -> Page[AlertListItemOut]:
    return lists.list_alerts(limit, offset)
