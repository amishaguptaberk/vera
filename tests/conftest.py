"""Makes tests/support importable from unit, integration, contract and eval tests alike."""

import sys
from pathlib import Path

SUPPORT = str(Path(__file__).parent / "support")
if SUPPORT not in sys.path:
    sys.path.insert(0, SUPPORT)

# Load the gateway (and with it every feature in plugins.FEATURES) before any test module imports
# a core module such as vera_api.evidence directly: evidence imports the gateway, the gateway loads
# the features, and features read evidence attributes at import. The app and the worker import the
# gateway first, so production entry points never hit the partial-module cycle.
import vera_api.gateway  # noqa: E402,F401
