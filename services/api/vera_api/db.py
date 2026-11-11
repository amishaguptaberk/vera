from collections.abc import Iterator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


def make_engine(url: str) -> Engine:
    return create_engine(url, pool_pre_ping=True, connect_args={"options": "-c timezone=UTC"})


def session_iter(factory: sessionmaker[Session]) -> Iterator[Session]:
    with factory() as session:
        yield session
