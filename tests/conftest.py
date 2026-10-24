import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

import pytest

from app.main import app


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    app.state.limiter.reset()
    yield


@pytest.fixture()
def db_factory():
    """Fresh in-memory database wired into the app; yields a session factory."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.database import Base, get_db

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    def _override_get_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    yield Session
    app.dependency_overrides.pop(get_db, None)
    engine.dispose()
