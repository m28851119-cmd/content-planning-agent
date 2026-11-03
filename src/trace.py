"""Trace is an export of persisted events, including actual subsequent actions."""
import json
from pathlib import Path


def export_run(state, directory):
    directory = Path(directory)
    directory.mkdir(parents=True,exist_ok=True)
    for name,value in (("input.json",{"request":state.request,"backend":state.backend,
                                      "run_id":state.run_id,"backend_config":state.backend_config,
                                      "inject_failure":state.injection_config,"max_steps":state.max_steps,
                                      "max_tool_calls":state.max_tool_calls}),
                       ("output.json",state.to_dict())):
        (directory/name).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding="utf-8")
    (directory/"trace.jsonl").write_text(
        "".join(json.dumps(e,ensure_ascii=False)+"\n" for e in state.events),encoding="utf-8")
