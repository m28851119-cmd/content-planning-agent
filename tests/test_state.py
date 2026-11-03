import pytest
from src.state import RunState
from src.tools import Tools
from src.guardrails import assert_save_allowed, totals, validate_request


def test_state_roundtrip(tmp_path):
    s = RunState({"topic":"测试", "budget":10, "deadline":120})
    s.plan.append({"id":"s1", "tool":"search_materials", "status":"failed", "result":None})
    s.persist(tmp_path)
    loaded = RunState.load(tmp_path, s.run_id)
    assert loaded.to_dict() == s.to_dict()
    with pytest.raises(ValueError, match="dependency"):
        loaded.successful("s1", "search_materials")


def test_hard_guardrail(tmp_path):
    t = Tools(tmp_path)
    plan = {"variants":dict(search_materials="full", generate_script="full", save_plan="full")}
    quote = t.estimate_cost(plan)
    assert totals(quote) == (12,55)
    with pytest.raises(ValueError, match="save_guardrail_rejected"):
        assert_save_allowed(t, {"topic":"测试", "budget":10, "deadline":120}, plan, quote)
    with pytest.raises(ValueError, match="save_guardrail_rejected"):
        assert_save_allowed(t, {"topic":"测试", "budget":20, "deadline":1}, plan, quote)
    assert not list(tmp_path.glob("*.json"))


def test_missing_and_invalid():
    assert validate_request({"topic":"测试"}) == ["budget","deadline"]
    with pytest.raises(ValueError):
        validate_request({"topic":"测试","budget":float("nan"),"deadline":120})
