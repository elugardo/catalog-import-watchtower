"""Shared response pieces: UTC timestamps, the error shape, the list envelope."""

from datetime import UTC, datetime
from typing import Annotated, Any

from pydantic import AfterValidator, BaseModel, ConfigDict, Field


def _to_utc(value: datetime) -> datetime:
    """Every timestamp leaves the API in UTC, which Pydantic serialises with a `Z` suffix."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamps must be timezone-aware")
    return value.astimezone(UTC)


UtcDateTime = Annotated[datetime, AfterValidator(_to_utc)]


class ApiModel(BaseModel):
    """Base for every response model; builds from ORM objects as well as dicts."""

    model_config = ConfigDict(from_attributes=True)


class ErrorOut(ApiModel):
    """The one error shape of every 4xx response (`_docs/api.md`)."""

    code: str
    message: str
    details: list[dict[str, Any]]


class ValidationErrorOut(ApiModel):
    """One validation finding inside an import; `line` is the file line (header = 1)."""

    line: int = Field(ge=1)
    column: str
    message: str


class Page[T](ApiModel):
    """`{ items, total }`, the envelope of every list endpoint."""

    items: list[T]
    total: int = Field(ge=0)
