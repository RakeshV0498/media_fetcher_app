import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.db import Base
from app.seed import seed


@pytest.fixture()
def session_factory():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        seed(db)
    return factory


@pytest.fixture()
def db(session_factory) -> Session:
    with session_factory() as s:
        yield s


@pytest.fixture()
def api_client(session_factory, monkeypatch):
    """TestClient with auth bypassed, DB overridden, and `settings` restored afterwards."""
    from fastapi.testclient import TestClient

    from app.auth import require_user
    from app.config import settings
    from app.db import get_db
    from app.main import app

    def override():
        with session_factory() as s:
            yield s
    saved = settings.model_copy()
    app.dependency_overrides[get_db] = override
    app.dependency_overrides[require_user] = lambda: "admin"
    yield TestClient(app)
    app.dependency_overrides.clear()
    for k, v in saved.model_dump().items():
        setattr(settings, k, v)
