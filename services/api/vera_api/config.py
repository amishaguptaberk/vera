import os
from dataclasses import dataclass, field

DEFAULT_DATABASE_URL = "postgresql+psycopg://vera:vera@127.0.0.1:54329/vera"


@dataclass(frozen=True)
class Settings:
    database_url: str = field(
        default_factory=lambda: os.environ.get("VERA_DATABASE_URL", DEFAULT_DATABASE_URL)
    )
    env: str = field(default_factory=lambda: os.environ.get("VERA_ENV", "synthetic"))
    # Assumption: the demo clock is expressed in Pacific time unless overridden.
    demo_tz: str = field(
        default_factory=lambda: os.environ.get("VERA_DEMO_TZ", "America/Los_Angeles")
    )

    @property
    def synthetic(self) -> bool:
        return self.env == "synthetic"
