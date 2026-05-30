"""
T4 tests — inbound contracts: hard validation, typed errors, payload guards.
"""

import pytest

from contracts import (
    InputTooLarge,
    InsufficientObservations,
    SchemaInvalid,
    guard_body_size,
    parse_input,
)
from contracts.inbound import (
    DeflatedSharpeInput,
    DecomposeFactorsInput,
    FindPairsInput,
    PboInput,
    SpreadSignalInput,
    VarCvarInput,
)


def test_valid_deflated_sharpe_parses():
    m = parse_input(DeflatedSharpeInput, {"returns": [0.01] * 10, "n_trials": 50})
    assert m.n_trials == 50 and len(m.returns) == 10


def test_too_few_returns_is_typed():
    with pytest.raises(InsufficientObservations) as e:
        parse_input(DeflatedSharpeInput, {"returns": [0.01] * 5, "n_trials": 50})
    assert e.value.code == "INSUFFICIENT_OBSERVATIONS"
    assert e.value.to_dict("req_1")["error"]["request_id"] == "req_1"


def test_unknown_field_rejected_as_schema_invalid():
    with pytest.raises(SchemaInvalid) as e:
        parse_input(DeflatedSharpeInput, {"returns": [0.01] * 10, "n_trials": 1, "rogue": 7})
    assert e.value.code == "SCHEMA_INVALID"
    assert e.value.details["errors"]


def test_wrong_type_is_schema_invalid():
    with pytest.raises(SchemaInvalid):
        parse_input(VarCvarInput, {"portfolio_returns": "not-a-list"})


def test_body_must_be_object():
    with pytest.raises(SchemaInvalid):
        parse_input(DeflatedSharpeInput, ["not", "a", "dict"])  # type: ignore[arg-type]


def test_confidence_out_of_range_is_schema_invalid():
    with pytest.raises(SchemaInvalid):
        parse_input(VarCvarInput, {"portfolio_returns": [0.01] * 30, "confidence": 1.5})


def test_var_cvar_too_few_obs():
    with pytest.raises(InsufficientObservations):
        parse_input(VarCvarInput, {"portfolio_returns": [0.01] * 10})


def test_pbo_needs_two_configs():
    with pytest.raises(InsufficientObservations):
        parse_input(PboInput, {"pnl_matrix": [[0.1], [0.2], [0.3], [0.4]]})


def test_pbo_ragged_rows_rejected():
    with pytest.raises(SchemaInvalid):
        parse_input(PboInput, {"pnl_matrix": [[0.1, 0.2], [0.3]], "n_splits": 2})


def test_spread_needs_126_obs():
    with pytest.raises(InsufficientObservations):
        parse_input(SpreadSignalInput, {"a_closes": [1.0] * 50, "b_closes": [1.0] * 50})


def test_find_pairs_needs_two_series():
    with pytest.raises(InsufficientObservations):
        parse_input(FindPairsInput, {"prices": {"AAA": [1.0] * 200}})


def test_decompose_requires_factor():
    with pytest.raises(SchemaInvalid):
        parse_input(DecomposeFactorsInput, {"portfolio_returns": [0.01] * 50, "factor_returns": {}})


def test_decompose_too_few_obs():
    with pytest.raises(InsufficientObservations):
        parse_input(DecomposeFactorsInput, {"portfolio_returns": [0.01] * 10, "factor_returns": {"market": [0.01] * 10}})


def test_body_size_guard():
    with pytest.raises(InputTooLarge):
        guard_body_size(20 * 1024 * 1024)


def test_float_count_guard():
    with pytest.raises(InputTooLarge):
        parse_input(VarCvarInput, {"portfolio_returns": [0.01] * 2_000_001})


def test_error_dict_shape():
    err = InsufficientObservations("nope", details={"need": 8})
    d = err.to_dict("req_abc")
    assert d == {"error": {"code": "INSUFFICIENT_OBSERVATIONS", "message": "nope",
                           "request_id": "req_abc", "details": {"need": 8}}}
