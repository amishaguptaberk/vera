"""Makes tests/support importable from unit, integration, contract and eval tests alike."""

import sys
from pathlib import Path

SUPPORT = str(Path(__file__).parent / "support")
if SUPPORT not in sys.path:
    sys.path.insert(0, SUPPORT)
# The repository root, so any test can drive the shared evaluation harness (evals.harness).
ROOT = str(Path(__file__).resolve().parents[1])
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# Load the gateway (and with it every feature in plugins.FEATURES) before any test module imports
# a core module such as vera_api.evidence directly: evidence imports the gateway, the gateway loads
# the features, and features read evidence attributes at import. The app and the worker import the
# gateway first, so production entry points never hit the partial-module cycle.
# Then register every feature's command test inputs (tests/support/payloads_<feature>.py) up
# front, so each test file runs alone or together.
import command_payloads  # noqa: E402
import vera_api.gateway  # noqa: E402,F401

command_payloads.load_features()
