"""API drift: the OpenAPI document must equal tests/contract/openapi.snapshot.json.

After an intentional API change, regenerate with:
    uv run python -m evals.snapshot_openapi
"""

import difflib

from evals.snapshot_openapi import SNAPSHOT, current


def test_openapi_matches_snapshot() -> None:
    want = SNAPSHOT.read_text()
    got = current()
    if got != want:
        diff = "".join(
            difflib.unified_diff(
                want.splitlines(keepends=True),
                got.splitlines(keepends=True),
                "openapi.snapshot.json",
                "create_app().openapi()",
                n=2,
            )
        )
        raise AssertionError(
            "API drift: the OpenAPI schema changed. If intended, run "
            "`uv run python -m evals.snapshot_openapi` and commit the snapshot.\n" + diff[:6000]
        )
