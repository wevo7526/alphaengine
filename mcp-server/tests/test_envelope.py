"""
T3 tests — SignalEnvelope round-trips from a real memo fixture, and the
structural "no edge without validation" rule is enforced.
"""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from envelope import SignalEnvelope, build_envelope_from_memo
from envelope.models import Signal, Validation

_MEMO = json.loads((Path(__file__).parent / "fixtures" / "sample_memo.json").read_text())


def _envelope():
    return build_envelope_from_memo(
        _MEMO, request_id="req_test_01", engine_version="quant_core@1.0.0", determinism="agent"
    )


def test_envelope_roundtrips_from_memo():
    env = _envelope()
    assert env.schema_version == "1.0.0"
    assert env.engine_version == "quant_core@1.0.0"
    assert env.determinism == "agent"
    assert env.generated_at == "2026-05-30T18:22:04Z"
    assert len(env.signals) == 3
    # re-serialize and re-parse — the contract is stable
    SignalEnvelope.model_validate(env.model_dump())


def test_first_signal_mapping():
    s = _envelope().signals[0]
    assert s.idea_id == "asle-outright-00"
    assert s.instruments[0].symbol == "ASLE"
    assert s.instruments[0].side == "long"
    assert s.instruments[0].weight == 0.05
    assert s.levels.entry == 12.40
    assert s.levels.stop == 10.90
    assert s.levels.target == 17.20
    assert s.thesis is not None
    assert s.context.regime == "expansion"
    assert s.context.regime_posterior["risk_on"] == 0.61
    assert s.risk.factor_betas == {"spy": 1.18}
    # falsification + provenance carried from the memo
    assert len(s.falsification_criteria) == 2
    assert s.provenance[0].tool == "filing"
    assert s.provenance[0].inputs_hash == "0001067983-25-000412"


def test_short_side_mapping():
    # TGLS is bearish → short
    s = [x for x in _envelope().signals if x.instruments[0].symbol == "TGLS"][0]
    assert s.instruments[0].side == "short"


def test_gate_reuses_decision_gate():
    # Every signal carries a gate; the high-conviction expansion longs should
    # not be blocked. (Uses the real compute_decision via conftest path.)
    gates = {s.instruments[0].symbol: s.risk.gate for s in _envelope().signals}
    assert gates["ASLE"] in ("pass", "warn", "block")
    # ASLE conviction 84, expansion, bullish, elevated risk → GO → pass
    assert gates["ASLE"] == "pass"


def test_deterministic_plane_nulls_thesis():
    env = build_envelope_from_memo(
        _MEMO, request_id="r", engine_version="quant_core@1.0.0", determinism="exact"
    )
    assert all(s.thesis is None for s in env.signals)
    assert env.determinism == "exact"


def test_agent_memo_never_claims_edge():
    # The memo has no overfitting figures, so no signal may be stamped edge.
    assert all(s.validation.verdict != "edge" for s in _envelope().signals)


def test_edge_without_validation_is_rejected():
    with pytest.raises(ValidationError):
        Signal(idea_id="x", validation=Validation(verdict="edge"))


def test_edge_with_validation_is_allowed():
    s = Signal(idea_id="x", validation=Validation(verdict="edge", deflated_sharpe=0.91, pbo=0.18))
    assert s.validation.verdict == "edge"
