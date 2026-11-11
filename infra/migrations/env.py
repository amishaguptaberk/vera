import os

from alembic import context
from sqlalchemy import create_engine

DEFAULT_URL = "postgresql+psycopg://vera:vera@127.0.0.1:54329/vera"


def run() -> None:
    url = os.environ.get("VERA_DATABASE_URL", DEFAULT_URL)
    if context.is_offline_mode():
        context.configure(url=url, literal_binds=True)
        with context.begin_transaction():
            context.run_migrations()
        return
    engine = create_engine(url)
    with engine.connect() as connection:
        context.configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


run()
