import json
import pytest
from src.agent import Agent
from src.llm import MockLLM, RealLLM, ModelError
from src.state import RunState
from src.tools import Tools
from src.cli import main
from tests.policies import SequenceLLM, action, force_save


def execute(tmp_path, request=None, model=None, **kwargs):
    s = RunState(request or {"topic":"秋季新品推广","budget":10,"deadline":120}, **kwargs)
    return Agent(s,model or MockLLM(),Tools(tmp_path/"saved"),tmp_path/"runs").run()


@pytest.mark.parametrize("missing",["budget","deadline","topic"])
def test_missing_no_tool_no_model(tmp_path,missing):
    request = {"topic":"秋季新品推广","budget":10,"deadline":120}
    del request[missing]
    model = SequenceLLM([])
    s = execute(tmp_path,request,model)
    assert s.status=="needs_input" and missing in s.missing_fields
    assert not s.plan and s.tool_calls==0 and not model.contexts


def test_no_feasible_gap(tmp_path):
    s = execute(tmp_path,{"topic":"秋季新品推广","budget":5,"deadline":120})
    assert s.status=="incomplete" and s.reason=="no_feasible_plan"
    assert s.gap["minimum_cost"]==6 and s.gap["cost"]==1
    assert not s.saved and not list((tmp_path/"saved").glob("*.json"))


def test_idempotency_across_runs(tmp_path):
    first = execute(tmp_path)
    second = execute(tmp_path)
    assert first.charged_cost==8 and second.charged_cost==0
    assert second.saved["already_exists"]
    assert first.saved["path"]==second.saved["path"]
    assert len(list((tmp_path/"saved").glob("*.json")))==1


def test_resume_only_remaining(tmp_path):
    s = execute(tmp_path,failures_remaining={"generate_script":1},max_steps=2)
    assert s.status=="incomplete" and s.reason=="max_steps_reached"
    assert s.plan[0]["status"]=="succeeded" and s.plan[1]["status"]=="failed"
    original = s.plan[0].copy()
    restored = RunState.load(tmp_path/"runs",s.run_id)
    restored.max_steps=12
    result = Agent(restored,MockLLM(),Tools(tmp_path/"saved"),tmp_path/"runs").run(resume=True)
    assert result.status=="completed"
    assert result.plan[0]==original and result.plan[1]["status"]=="failed"
    assert len([p for p in result.plan if p["tool"]=="search_materials"])==1
    assert result.failures_remaining["generate_script"]==0
    assert any(e["action"]=="resume" and e["observation"]["reused_successful_steps"]==["s1"] for e in result.events)


@pytest.mark.parametrize("limits",[{"max_steps":1},{"max_tool_calls":1}])
def test_limits(tmp_path,limits):
    s = execute(tmp_path,**limits)
    assert s.status=="incomplete" and s.reason=="max_steps_reached"
    assert s.plan[0]["status"]=="succeeded" and s.tool_calls==1


def test_save_guardrail_cannot_be_prompted_away(tmp_path):
    s = execute(tmp_path,model=force_save())
    failed = [p for p in s.plan if p["tool"]=="save_plan" and p["status"]=="failed"]
    assert len(failed)==1 and "save_guardrail_rejected" in failed[0]["error"]
    assert s.status=="completed" and s.total_cost==8
    assert len(s.ledger)==1 and s.charged_cost==8


@pytest.mark.parametrize("bad",[
    action("unknown"), "{broken", action("search_materials",topic="秋季新品推广",variant="evil"),
    action("generate_script",search_step=123,variant="lite")
])
def test_invalid_actions_return_observation_and_recover(tmp_path,bad):
    model = SequenceLLM([bad])
    s = execute(tmp_path,model=model)
    assert s.status=="completed"
    assert s.events[0]["action"]=="invalid_action"
    assert "error" in model.contexts[1]["state"]["observations"][0]


def test_dependency_refusal(tmp_path):
    s = execute(tmp_path,model=SequenceLLM([action("save_plan",estimate_step="s999")]))
    assert s.plan[0]["status"]=="failed"
    assert "dependency_not_satisfied" in s.plan[0]["error"]
    assert s.status=="completed"


def test_no_false_finish(tmp_path):
    s = execute(tmp_path,model=SequenceLLM([action("finish",reason="completed"),
                                          action("finish",reason="no_feasible_plan")]))
    assert s.observations[0]["error"]=="cannot_finish_without_save"
    assert s.observations[1]["error"]=="feasible_option_exists"
    assert s.status=="completed"


def test_deadline_replan_and_guardrail(tmp_path):
    s = execute(tmp_path,{"topic":"秋季新品推广","budget":20,"deadline":29})
    assert s.status=="completed" and s.total_minutes<=29
    assert [p for p in s.plan if p["tool"]=="estimate_cost"][0]["result"]["gap"]["minutes"]>0


def test_model_network_error_no_retry(tmp_path):
    class Broken:
        def choose(self,context):
            raise ModelError("network failure")
    s = execute(tmp_path,model=Broken())
    assert s.status=="incomplete" and s.reason=="model_error"
    assert s.used_steps==1 and s.tool_calls==0


def test_real_adapter_sends_observations_without_reasoning(monkeypatch):
    from io import BytesIO
    captures=[]
    def response(request,timeout):
        captures.append(json.loads(request.data))
        return BytesIO(json.dumps({"choices":[{"message":{
            "content":json.dumps(action("finish",reason="model_stopped")),
            "reasoning_content":"PRIVATE"}}]}).encode())
    monkeypatch.setenv("LLM_API_KEY","test-only")
    monkeypatch.setenv("LLM_BASE_URL","https://example.test/v1")
    monkeypatch.setattr("urllib.request.urlopen",response)
    model = RealLLM()
    raw = model.choose({"observation":{"error":"injected_failure"}})
    assert "PRIVATE" not in raw
    assert "injected_failure" in captures[0]["messages"][1]["content"]


def test_cli_resume(tmp_path,capsys):
    common=["--runs-dir",str(tmp_path/"runs"),"--saved-dir",str(tmp_path/"saved"),
            "--example-dir",str(tmp_path/"example")]
    assert main(common+["--topic","秋季新品推广","--budget","10","--deadline","120",
                        "--mock-llm","--inject-failure","generate_script:1","--max-steps","2"])==2
    first=json.loads(capsys.readouterr().out)
    assert main(common+["--resume",first["run_id"],"--max-steps","12"])==0
    final=json.loads(capsys.readouterr().out)
    assert final["plan"][1]["status"]=="failed"
    assert final["status"]=="completed"


def test_interrupted_running_recovery(tmp_path):
    s = RunState({"topic":"秋季新品推广","budget":10,"deadline":120})
    s.plan.append({"id":"s1","tool":"search_materials","args":{},"status":"running","dependencies":[],"result":None})
    s.persist(tmp_path/"runs")
    s = Agent(RunState.load(tmp_path/"runs",s.run_id),MockLLM(),Tools(tmp_path/"saved"),tmp_path/"runs").run(resume=True)
    assert s.plan[0]["status"]=="failed" and s.plan[0]["error"]=="interrupted_unknown_outcome"
    assert s.status=="completed"


def test_ledger_minutes_derived_from_tool(tmp_path):
    s=execute(tmp_path)
    assert s.total_minutes==sum(c["minutes"] for c in s.ledger[0]["components"])
    for step in s.plan:
        if step["tool"]=="estimate_cost" and step["status"]=="succeeded":
            e=step["result"]["estimate"]
            assert e["total_cost"]==sum(c["cost"] for c in e["components"])
            assert e["total_minutes"]==sum(c["minutes"] for c in e["components"])


def test_cached_success_is_skipped_not_reexecuted(tmp_path):
    model=SequenceLLM([action("search_materials",topic="秋季新品推广",variant="full"),
                      action("search_materials",topic="秋季新品推广",variant="full")])
    s=execute(tmp_path,model=model)
    assert s.plan[1]["status"]=="skipped"
    assert s.plan[1]["reused_step"]=="s1"
    assert s.status=="completed"
