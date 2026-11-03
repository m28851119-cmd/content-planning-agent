"""Generate evidence by executing the agent. Never synthesize outputs or traces."""
import json
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from src.agent import Agent
from src.llm import MockLLM
from src.state import RunState
from src.tools import Tools
from src.trace import export_run
from tests.policies import force_save, SequenceLLM, action


def main():
    root=Path("examples")
    root.mkdir(exist_ok=True)
    session=Path("runs")/("evaluation-"+uuid.uuid4().hex)
    session.mkdir(parents=True)
    results=[]
    def run(name,budget=20,deadline=120,failures=None,max_steps=12,max_calls=12,model=None,shared=None,missing=None):
        request={"topic":"秋季新品推广","budget":budget,"deadline":deadline}
        if missing:
            request[missing]=None
        state=RunState(request,failures_remaining=failures or {},max_steps=max_steps,
                       max_tool_calls=max_calls,backend=getattr(model,"name","mock"))
        agent=Agent(state,model or MockLLM(),Tools(shared or session/name/"saved"),session/"states")
        output=agent.run()
        export_run(output,root/name)
        input_path=root/name/"input.json"
        metadata=json.loads(input_path.read_text(encoding="utf-8"))
        metadata.update(inject_failure=failures or {},execution="mock 运行；只验证流程，不证明真实模型决策效果")
        input_path.write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding="utf-8")
        results.append({"scenario":name,"status":output.status,"reason":output.reason,
                        "total_cost":output.total_cost,"charged_cost":output.charged_cost,
                        "run_id":output.run_id})
        if output.saved:
            # This is a byte-for-byte copy of the actual saved file, not hand-written evidence.
            saved=Path(output.saved["path"])
            (root/name/"saved_plan.json").write_bytes(saved.read_bytes())
        return output
    run("01-normal")
    run("02-missing-budget",missing="budget")
    run("03-missing-deadline",missing="deadline")
    run("04-tool-failure",failures={"generate_script":1})
    interrupted=run("05-resume-before",failures={"generate_script":1},max_steps=2)
    restored=RunState.load(session/"states",interrupted.run_id)
    restored.max_steps=12
    output=Agent(restored,MockLLM(),Tools(session/"05-resume-before"/"saved"),session/"states").run(resume=True)
    export_run(output,root/"06-resume-after")
    (root/"06-resume-after"/"saved_plan.json").write_bytes(Path(output.saved["path"]).read_bytes())
    results.append({"scenario":"06-resume-after","status":output.status,"reason":output.reason,
                    "total_cost":output.total_cost,"charged_cost":output.charged_cost,"run_id":output.run_id})
    run("07-budget-replan",budget=10)
    run("08-no-feasible",budget=5)
    shared=session/"duplicate"/"saved"
    run("09-duplicate-first",budget=10,shared=shared)
    run("10-duplicate-second",budget=10,shared=shared)
    assert len(list(shared.glob("*.json")))==1
    run("11-max-steps",max_steps=1)
    run("12-save-guardrail",budget=10,model=force_save())
    run("13-max-tool-calls",max_calls=1)
    run("14-deadline-replan",deadline=29)
    run("15-invalid-action",model=SequenceLLM([action("unknown")]))
    report={"generated_at_utc":datetime.now(timezone.utc).isoformat(),
            "python":sys.version,"backend":"mock (scripted policies only)","results":results,
            "duplicate_saved_file_count":len(list(shared.glob("*.json")))}
    (root/"manifest.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    test=subprocess.run([sys.executable,"-m","pytest","-v","--basetemp",str(session/"pytest")],
                        stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    (root/"pytest-results.txt").write_bytes(test.stdout)
    print(json.dumps(report,ensure_ascii=False,indent=2))
    print(test.stdout.decode(errors="replace"))
    return test.returncode


if __name__=="__main__":
    raise SystemExit(main())
