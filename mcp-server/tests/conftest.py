"""
Test bootstrap. Adds the backend package to sys.path so the gateway can reuse
the real Decision Gate (agents.desk5_decision_gate.compute_decision) and, later,
the orchestrator. quant_core stays self-contained and never needs this.
"""

import os
import sys
from pathlib import Path

# Tests run with auth stubbed on (local). The production default is now OFF
# (secure-by-default); test_gateway flips this per-test to exercise enforcement.
os.environ.setdefault("AUTH_STUB", "1")

_BACKEND = Path(__file__).resolve().parents[2] / "backend"
if _BACKEND.is_dir() and str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

# The SDK lives in mcp-server/sdk/ so `import alphaengine` resolves in tests.
_SDK = Path(__file__).resolve().parents[1] / "sdk"
if _SDK.is_dir() and str(_SDK) not in sys.path:
    sys.path.insert(0, str(_SDK))
