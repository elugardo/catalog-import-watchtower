"""SQLAlchemy models for the six tables of spec section 6.

Importing this package registers every table on `app.db.Base.metadata`, which
is what `alembic/env.py` compares against the migrations.
"""

from app.models.catalog import Product, Vendor
from app.models.imports import Import, ImportAttempt
from app.models.incidents import AgentAction, Alert

__all__ = ["AgentAction", "Alert", "Import", "ImportAttempt", "Product", "Vendor"]
