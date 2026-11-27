"""SQLAlchemy database setup for the backend."""

from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from .config import get_settings

settings = get_settings()
parsed_url = make_url(settings.database_url)
is_sqlite = parsed_url.get_backend_name() == "sqlite"

connect_args = {"check_same_thread": False} if is_sqlite else {}
engine = create_engine(settings.database_url, connect_args=connect_args)

if is_sqlite:

    @event.listens_for(engine, "do_connect")
    def _ensure_sqlite_parent_directory(_dialect, _conn_rec, cargs, cparams):
        """Create the parent folder just before a real SQLite file connection opens."""
        database = cargs[0] if cargs else cparams.get("database")
        if not database:
            return

        database = str(database)
        if (
            database.lower() == ":memory:"
            or database.lower().startswith("file:")
        ):
            # SQLite file: URIs are handled by SQLAlchemy/SQLite directly. They
            # are not ordinary filesystem paths, so their parent directory must
            # already exist if the URI needs one.
            return

        parent = Path(database).parent
        if parent != Path("."):
            parent.mkdir(parents=True, exist_ok=True)

        # Do not return a DBAPI connection. SQLAlchemy's SQLite dialect still
        # performs the actual connection so URL query options are preserved.
        return

# create_engine and event registration do not open a connection by themselves,
# so importing this module does not create directories, database files, or
# tables. The do_connect listener runs only when the pool needs a new SQLite
# DBAPI connection.

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)


def get_db() -> Generator[Session, None, None]:
    """Yield a database session that can be used by FastAPI routes."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
