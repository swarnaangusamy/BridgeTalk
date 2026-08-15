"""Shared pytest fixtures.

The whole suite runs against a throwaway in-memory SQLite database, never
against MySQL. Three reasons:

1. Tests must pass on a machine where MySQL is not installed or not running.
2. A test must never be able to delete real meeting data.
3. In-memory SQLite is fast enough that running the suite is not a chore.

The trade-off is honest: SQLite is not MySQL, so these tests verify application
logic (auth, validation, permissions) rather than MySQL-specific behaviour such
as ENUM storage or index plans. `database/schema.sql` is what proves the MySQL
side, and Phase 1's acceptance check runs the real endpoints against real MySQL.
"""

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Put `backend/` on the import path so `from app...` resolves whether pytest is
# invoked from the repository root or from inside backend/.
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.database import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture()
def db_session():
    """A fresh, empty database for a single test."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        # An in-memory SQLite database lives inside its connection. The default
        # pool hands out different connections, so the tables created here
        # would be invisible to the request under test. StaticPool forces every
        # checkout to reuse the one connection, keeping a single database.
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture()
def client(db_session):
    """A TestClient whose endpoints use the throwaway database.

    Note that `TestClient` is deliberately NOT used as a context manager here.
    Entering the context would run the app's lifespan, which connects to the
    real MySQL database from .env — exactly what these tests avoid.
    """

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    test_client = TestClient(app)
    try:
        yield test_client
    finally:
        # Overrides live on the app object, which is shared across tests.
        # Clearing them stops one test's database leaking into the next.
        app.dependency_overrides.clear()


@pytest.fixture()
def registered_user(client):
    """A registered account plus its auth token.

    Returns the parsed /register response, which contains both `access_token`
    and the public `user` object.
    """
    response = client.post(
        "/api/auth/register",
        json={
            "name": "Swarna Rathna A",
            "email": "swarna@example.com",
            "password": "correct horse battery",
            "role": "deaf",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture()
def auth_headers(registered_user):
    """Authorization header for the registered user."""
    return {"Authorization": f"Bearer {registered_user['access_token']}"}
