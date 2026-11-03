import json
import pytest
from src.tools import Tools
from src.guardrails import assert_save_allowed
from src.agent import Agent
from src.state import RunState
from src.llm import MockLLM


def test_changed_price_requires_reestimate(tmp_path):
    t=Tools(tmp_path)
    plan={"variants":dict(search_materials="full",generate_script="full",save_plan="full")}
    estimate=t.estimate_cost(plan)
    t.costs["generate_script"]["full"]["cost"]=9
    with pytest.raises(ValueError,match="stale_estimate"):
        assert_save_allowed(t,{"topic":"x","budget":20,"deadline":120},plan,estimate)


def test_semantic_numeric_idempotency(tmp_path):
    saved=[]
    for budget in (10,10.0):
        s=RunState({"topic":"秋季新品推广","budget":budget,"deadline":120})
        Agent(s,MockLLM(),Tools(tmp_path/"saved"),tmp_path/"runs").run()
        saved.append(s)
    assert saved[0].saved["path"]==saved[1].saved["path"]
    assert saved[1].charged_cost==0


@pytest.mark.parametrize("tool",["search_materials","estimate_cost","save_plan"])
def test_other_tool_failure_recoverable(tmp_path,tool):
    s=RunState({"topic":"秋季新品推广","budget":10,"deadline":120},failures_remaining={tool:1})
    Agent(s,MockLLM(),Tools(tmp_path/"saved"),tmp_path/"runs").run()
    assert s.status=="completed"
    assert any(p["tool"]==tool and p["status"]=="failed" for p in s.plan)


def test_trace_actual_tool_arguments(tmp_path):
    s=RunState({"topic":"秋季新品推广","budget":20,"deadline":120})
    Agent(s,MockLLM(),Tools(tmp_path/"saved"),tmp_path/"runs").run()
    event=next(e for e in s.events if e["action"]=="generate_script")
    assert event["tool_args"]["material_ids"]==["m1","m2"]
