import json
from src.cli import main


def test_cli_and_trace(tmp_path,capsys):
    root = tmp_path
    code = main(["--topic","秋季新品推广","--budget","10","--deadline","120","--mock-llm",
                 "--runs-dir",str(root/"runs"),"--saved-dir",str(root/"saved"),
                 "--example-dir",str(root/"example")])
    assert code == 0
    s = json.loads(capsys.readouterr().out)
    trace = [json.loads(x) for x in (root/"example"/"trace.jsonl").read_text(encoding="utf-8").splitlines()]
    assert s["status"] == "completed"
    assert trace[0]["next_action"] == "generate_script"
    assert trace[-1]["action"] == "finish"
    assert trace[-1]["state"]["total_cost"] == 8


def test_cli_missing_without_api_key(tmp_path,monkeypatch,capsys):
    monkeypatch.delenv("LLM_API_KEY",raising=False)
    assert main(["--topic","x","--runs-dir",str(tmp_path/"r"),"--example-dir",str(tmp_path/"e")]) == 2
    s = json.loads(capsys.readouterr().out)
    assert s["status"]=="needs_input" and s["tool_calls"]==0
