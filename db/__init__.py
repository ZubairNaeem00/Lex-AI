"""MongoDB data layer: configuration, document models, schemas, and CRUD."""

from db.config import COLLECTIONS, Collections, database, ensure_indexes
from db.models import MODEL_BY_COLLECTION

__all__ = ["COLLECTIONS", "Collections", "MODEL_BY_COLLECTION", "database", "ensure_indexes"]
