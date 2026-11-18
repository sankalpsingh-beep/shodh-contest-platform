
import os

import jwt
import pytest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import settings
from app.database import Base, get_db
from app.main import app
from app.models import (
    Contest,
    Organization,
    OrganizationMembership,
    Participation,
    User,
)

# Never allow automated tests to run against the development database.
TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")

if not TEST_DATABASE_URL:
    raise RuntimeError("TEST_DATABASE_URL must be configured")

if "shodh_test" not in TEST_DATABASE_URL:
    raise RuntimeError("Tests may only run against shodh_test")


@pytest.fixture(scope="session")
def test_engine():
    engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)

    Base.metadata.create_all(bind=engine)

    yield engine

    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture
def db_session(test_engine):
    connection = test_engine.connect()
    transaction = connection.begin()

    session = Session(
        bind=connection,
        join_transaction_mode="create_savepoint",
        expire_on_commit=False,
    )

    yield session

    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture
def client(db_session):
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


@pytest.fixture
def create_user(db_session):
    def factory(email, display_name, is_active=True):
        user = User(
            email=email,
            password_hash="test-password-hash",
            display_name=display_name,
            is_active=is_active,
        )
        db_session.add(user)
        db_session.flush()
        return user

    return factory


@pytest.fixture
def create_organization(db_session):
    def factory(name, slug):
        organization = Organization(name=name, slug=slug)
        db_session.add(organization)
        db_session.flush()
        return organization

    return factory


@pytest.fixture
def add_membership(db_session):
    def factory(user, organization, role):
        membership = OrganizationMembership(
            user_id=user.id,
            organization_id=organization.id,
            role=role,
        )
        db_session.add(membership)
        db_session.flush()
        return membership

    return factory


@pytest.fixture
def create_contest(db_session):
    from datetime import datetime, timedelta, timezone

    def factory(organization, title="Test Contest"):
        now = datetime.now(timezone.utc)

        contest = Contest(
            organization_id=organization.id,
            title=title,
            description="Automated test contest",
            starts_at=now - timedelta(hours=1),
            ends_at=now + timedelta(hours=2),
            duration_minutes=120,
            is_published=True,
        )
        db_session.add(contest)
        db_session.flush()
        return contest

    return factory


@pytest.fixture
def add_participant(db_session):
    def factory(user, contest):
        participation = Participation(
            user_id=user.id,
            contest_id=contest.id,
        )
        db_session.add(participation)
        db_session.flush()
        return participation

    return factory


@pytest.fixture
def auth_headers():
    def factory(user):
        token = jwt.encode(
            {"sub": str(user.id)},
            settings.JWT_SECRET,
            algorithm=settings.JWT_ALGORITHM,
        )
        return {"Authorization": f"Bearer {token}"}

    return factory
