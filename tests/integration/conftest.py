import os
from collections.abc import Iterator

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

TEST_DB_URL = os.environ.get(
    "VERA_TEST_DATABASE_URL", "postgresql+psycopg://vera:vera@127.0.0.1:54329/vera_test"
)


@pytest.fixture(scope="session")
def db_url() -> str:
    """Real Postgres (run infra/dev-db.sh start); schema comes from the Alembic migrations."""
    os.environ["VERA_DATABASE_URL"] = TEST_DB_URL
    command.upgrade(Config("alembic.ini"), "head")
    return TEST_DB_URL


@pytest.fixture
def client(db_url: str) -> Iterator[TestClient]:
    from vera_api.app import create_app
    from vera_api.config import Settings

    app = create_app(Settings(database_url=db_url, env="synthetic"))
    with TestClient(app) as c:
        assert c.post("/api/demo/reset").status_code == 200
        yield c
