"""CLI. Deadline is a nonnegative simulated duration in minutes, not wall time."""
import argparse
import json
from pathlib import Path
from src.agent import Agent, SCHEMAS
from src.guardrails import validate_request
from src.llm import MockLLM, RealLLM, ModelError
from src.state import RunState
from src.tools import Tools
from src.trace import export_run


def positive(value):
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return number


def parser():
    p = argparse.ArgumentParser(description="内容任务规划 Agent")
    p.add_argument("--topic")
    p.add_argument("--budget",type=float)
    p.add_argument("--deadline",type=float,help="simulated duration in minutes")
    p.add_argument("--mock-llm",action="store_true")
    p.add_argument("--resume")
    p.add_argument("--max-steps",type=positive)
    p.add_argument("--max-tool-calls",type=positive)
    p.add_argument("--inject-failure",action="append",default=[])
    p.add_argument("--runs-dir",default="runs")
    p.add_argument("--saved-dir",default="saved_plans")
    p.add_argument("--example-dir",help="default: examples/<run_id>")
    return p


def main(argv=None):
    p = parser()
    args = p.parse_args(argv)
    try:
        if args.resume:
            if any(v is not None for v in (args.topic,args.budget,args.deadline)) or args.inject_failure:
                p.error("resume preserves request and failure counters; do not supply request/injection overrides")
            s = RunState.load(args.runs_dir,args.resume)
            if args.mock_llm and s.backend != "mock":
                p.error("cannot silently replace real model with Mock during resume")
            if args.max_steps is not None:
                s.max_steps = args.max_steps
            if args.max_tool_calls is not None:
                s.max_tool_calls = args.max_tool_calls
        else:
            failures = {}
            for value in args.inject_failure:
                name,count = value.split(":")
                if name not in SCHEMAS or name in ("finish","ask_user") or int(count)<1:
                    raise ValueError("failure format: tool:positive_count")
                failures[name] = int(count)
            s = RunState({"topic":args.topic,"budget":args.budget,"deadline":args.deadline},
                         backend="mock" if args.mock_llm else "real",
                         failures_remaining=failures,max_steps=args.max_steps or 12,
                         max_tool_calls=args.max_tool_calls or 12)
        missing = validate_request(s.request)
        # Missing input must not initialize a network backend or call any tools.
        model = MockLLM() if missing or s.backend=="mock" else RealLLM()
        if isinstance(model,RealLLM):
            s.backend_config = {"model":model.model, "base_url":model.base_url}
        s = Agent(s,model,Tools(args.saved_dir),args.runs_dir).run(resume=bool(args.resume))
    except (ValueError,OSError,ModelError) as exc:
        if "s" not in locals():
            p.error(str(exc))
        s.status,s.reason = "incomplete","configuration_error"
        s.events.append({"step":s.used_steps,"action":"configuration_error","args":{},
                         "observation":{"error":str(exc)},"rationale":"","next_action":None})
        s.persist(args.runs_dir)
    export_run(s,args.example_dir or str(Path("examples")/s.run_id))
    print(json.dumps(s.to_dict(),ensure_ascii=False,indent=2))
    return 0 if s.status=="completed" else 2


if __name__=="__main__":
    raise SystemExit(main())
