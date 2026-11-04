"""Database connection and query helpers for Turin Spatial Routing backend."""

import os
from typing import Optional
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(BASE_DIR, ".env"))


def get_db_uri() -> str:
    """Returns database connection URI from environment."""
    if os.getenv("POSTGIS_URI"):
        return os.getenv("POSTGIS_URI")

    user = os.getenv("POSTGRES_USER", "postgres")
    password = os.getenv("POSTGRES_PASSWORD", "postgres")
    host = os.getenv("POSTGRES_HOST", "127.0.0.1")
    if host == "localhost":
        host = "127.0.0.1"
    port = os.getenv("POSTGRES_PORT", "5432")
    db = os.getenv("POSTGRES_DB", "postgres")

    return f"postgresql://{user}:{password}@{host}:{port}/{db}"


_engine: Optional[Engine] = None


def get_engine() -> Engine:
    """Returns a singleton SQLAlchemy engine with timeout."""
    global _engine
    if _engine is None:
        _engine = create_engine(
            get_db_uri(),
            connect_args={"connect_timeout": 5},
            pool_pre_ping=True,
        )
    return _engine
