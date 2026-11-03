import json
from src.agent import Agent
from src.llm import MockLLM
from src.state import RunState
from src.tools import Tools
from tests.policies import SequenceLLM, action


def test_cannot_commit_two_plans_in_one_run(tmp_path):
    model=SequenceLLM([
        action("search_materials",topic="秋季新品推广",variant="full"),
        action("generate_script",search_step="s1",variant="full"),
        action("estimate_cost",script_step="s2",save_variant="full"),
        action("save_plan",estimate_step="s3"),
        action("search_materials",topic="秋季新品推广",variant="lite")])
    s=RunState({"topic":"秋季新品推广","budget":20,"deadline":120})
    Agent(s,model,Tools(tmp_path/"saved"),tmp_path/"runs").run()
    assert s.status=="completed" and s.charged_cost==12
    assert any(o.get("error","").startswith("plan_already_committed") for o in s.observations)
    assert len(s.ledger)==1


def test_save_completed_before_state_persist_is_reconciled(tmp_path):
    s=RunState({"topic":"秋季新品推广","budget":20,"deadline":120},max_steps=3)
    t=Tools(tmp_path/"saved")
    a=Agent(s,MockLLM(),t,tmp_path/"runs")
    a.run()
    kwargs,deps=a.prepare("save_plan",{"estimate_step":"s3"})
    result=t.save_plan(**kwargs)  # Simulate crash after file commit, before RunState success.
    assert result["charged_cost"]==12
    s.plan.append({"id":"s4","tool":"save_plan","args":{"estimate_step":"s3"},
                   "tool_args":kwargs,"dependencies":deps,"status":"running","result":None})
    s.persist(tmp_path/"runs")
    restored=RunState.load(tmp_path/"runs",s.run_id)
    restored.max_steps=12
    Agent(restored,MockLLM(),Tools(tmp_path/"saved"),tmp_path/"runs").run(resume=True)
    assert restored.status=="completed" and restored.charged_cost==12
    assert restored.saved["already_exists"] and restored.saved["recovered_commit"]
    assert restored.plan[3]["status"]=="failed"
    assert len(list((tmp_path/"saved").glob("*.json")))==1


def test_duplicate_does_not_rewrite_saved_file(tmp_path):
    t=Tools(tmp_path)
    plan={"variants":dict(search_materials="full",generate_script="lite",save_plan="full")}
    key="a"*64
    first=t.save_plan(plan,key)
    path=tmp_path/(key+".json")
    before=(path.stat().st_mtime_ns,path.read_bytes())
    second=t.save_plan(plan,key)
    assert second["charged_cost"]==0
    assert before==(path.stat().st_mtime_ns,path.read_bytes())


def test_internal_accounting_is_not_hidden_tool_call(tmp_path):
    class CountTools(Tools):
        def __init__(self, path):
            super().__init__(path)
            self.estimate_invocations=0
        def estimate_cost(self, plan):
            self.estimate_invocations+=1
            return super().estimate_cost(plan)
    t=CountTools(tmp_path/"saved")
    s=RunState({"topic":"秋季新品推广","budget":10,"deadline":120})
    Agent(s,MockLLM(),t,tmp_path/"runs").run()
    assert s.status=="completed"
    assert t.estimate_invocations==2
    assert s.tool_calls==len([p for p in s.plan if p["status"]=="succeeded"])
