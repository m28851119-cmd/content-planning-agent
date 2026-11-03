from src.agent import Agent
from src.llm import MockLLM
from src.state import RunState
from src.tools import Tools


def run(tmp_path, budget=20, failures=None, max_steps=12):
    s = RunState({"topic":"秋季新品推广","budget":budget,"deadline":120},
                 failures_remaining=failures or {},max_steps=max_steps)
    return Agent(s,MockLLM(),Tools(tmp_path/"saved"),tmp_path/"runs").run()


def test_normal(tmp_path):
    s = run(tmp_path)
    assert s.status == "completed"
    assert s.total_cost == s.charged_cost == 12
    assert s.total_cost == sum(c["cost"] for c in s.ledger[0]["components"])


def test_replan(tmp_path):
    s = run(tmp_path,10)
    assert s.status == "completed"
    assert [p["result"]["estimate"]["total_cost"] for p in s.plan if p["tool"]=="estimate_cost"] == [12,8]
    assert s.total_cost == s.charged_cost == 8


def test_failure(tmp_path):
    s = run(tmp_path,failures={"generate_script":1})
    assert s.status == "completed"
    failed = [p for p in s.plan if p["status"]=="failed"]
    assert len(failed)==1 and failed[0]["tool"]=="generate_script"
    assert s.plan[0]["status"]=="succeeded" and s.plan[0]["result"]["materials"]
