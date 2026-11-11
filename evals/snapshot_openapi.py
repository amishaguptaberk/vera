"""Regenerate tests/contract/openapi.snapshot.json: uv run python -m evals.snapshot_openapi"""

import json
from pathlib import Path

SNAPSHOT = Path(__file__).resolve().parent.parent / "tests/contract/openapi.snapshot.json"


def current() -> str:
    from vera_api.app import create_app
    from vera_api.config import Settings

    app = create_app(Settings(env="synthetic"))
    return json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n"


if __name__ == "__main__":
    SNAPSHOT.write_text(current())
    print(f"wrote {SNAPSHOT}")
