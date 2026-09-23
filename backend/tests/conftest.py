import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.db.base import Base
from app.db.session import get_db

# setup_db() below runs Base.metadata.drop_all() at the end of every pytest
# session, so this must never resolve to a real database. In a production
# environment (APP_ENV=production, set in .env.production) that is an
# absolute rule with no override: DATABASE_URL there IS the live application
# database, and running pytest against it once already wiped it for real
# (2026-09-17). Only outside production do we fall back to TEST_DATABASE_URL
# (an explicit, separate override) or DATABASE_URL (dev-container convenience,
# where that value points at a disposable dev database, not production).
if settings.APP_ENV.lower() == "production":
    TEST_DATABASE_URL = None
else:
    TEST_DATABASE_URL = (
        os.environ.get("TEST_DATABASE_URL") or settings.TEST_DATABASE_URL or settings.DATABASE_URL
    )


def _db_available():
    if not TEST_DATABASE_URL:
        return False
    try:
        engine = create_engine(TEST_DATABASE_URL)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


DB_AVAILABLE = _db_available()

skip_if_no_db = pytest.mark.skipif(
    not DB_AVAILABLE,
    reason=(
        "No test database available. Refused (APP_ENV=production never runs "
        "DB-backed tests) or TEST_DATABASE_URL/DATABASE_URL unreachable."
    ),
)

if DB_AVAILABLE:
    engine = create_engine(TEST_DATABASE_URL)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
else:
    engine = None
    TestingSessionLocal = None


@pytest.fixture(scope="session", autouse=True)
def setup_db():
    if not DB_AVAILABLE:
        yield
        return
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db_session():
    if not DB_AVAILABLE:
        pytest.skip("PostgreSQL not available")
    connection = engine.connect()
    transaction = connection.begin()
    session = TestingSessionLocal(bind=connection)

    yield session

    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture
def client(db_session):
    from app.main import app
    from fastapi.testclient import TestClient

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    del app.dependency_overrides[get_db]
