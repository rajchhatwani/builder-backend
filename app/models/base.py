from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative base for all builder tables (projects, entities, fields, relations, etc.)."""
