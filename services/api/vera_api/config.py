import os
from dataclasses import dataclass, field

DEFAULT_DATABASE_URL = "postgresql+psycopg://vera:vera@127.0.0.1:54329/vera"

DEV_SESSION_SECRET = "vera-dev-session-secret-synthetic-only"


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

    session_secret: str = field(default_factory=lambda: os.environ.get("VERA_SESSION_SECRET", ""))

    def secret(self) -> str:
        """Dev default is allowed only in the synthetic environment."""
        if self.session_secret:
            return self.session_secret
        if self.synthetic:
            return DEV_SESSION_SECRET
        raise RuntimeError("VERA_SESSION_SECRET is required outside the synthetic environment")

    @property
    def synthetic(self) -> bool:
        return self.env == "synthetic"
