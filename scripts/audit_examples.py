"""Read-only verification of recorded artifacts. Output is generated, not curated."""
import hashlib
import json
from pathlib import Path


def main():
    root=Path("examples")
    entries=[]
    for output in sorted(root.glob("*/output.json")):
        state=json.loads(output.read_text(encoding="utf-8"))
        trace=output.with_name("trace.jsonl")
        events=[json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines()]
        assert events==state["events"], str(output)
        assert state["charged_cost"]==sum(e["charged_cost"] for e in state["ledger"])
        for step in state["plan"]:
            assert step["status"] in ("pending","running","succeeded","failed","skipped")
            if step["status"]=="failed":
                assert step["result"] is None and "error" in step
            if step["tool"]=="estimate_cost" and step["status"]=="succeeded":
                quote=step["result"]["estimate"]
                assert quote["total_cost"]==sum(c["cost"] for c in quote["components"])
                assert quote["total_minutes"]==sum(c["minutes"] for c in quote["components"])
        if state["status"]=="completed":
            assert state["saved"] and state["total_cost"]<=state["request"]["budget"]
            assert state["total_minutes"]<=state["request"]["deadline"]
        if state["reason"]=="missing_fields":
            assert not state["plan"] and state["tool_calls"]==0
        entries.append({"scenario":output.parent.name,"status":state["status"],
                        "backend":state["backend"],"total_cost":state["total_cost"],
                        "output_sha256":hashlib.sha256(output.read_bytes()).hexdigest(),
                        "trace_sha256":hashlib.sha256(trace.read_bytes()).hexdigest(),"verified":True})
    report={"count":len(entries),"artifacts":entries}
    (root/"evidence-audit.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
