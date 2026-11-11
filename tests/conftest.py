"""Makes tests/support importable from unit, integration, contract and eval tests alike."""

import sys
from pathlib import Path

SUPPORT = str(Path(__file__).parent / "support")
if SUPPORT not in sys.path:
    sys.path.insert(0, SUPPORT)
