import json
import threading
import time
import urllib.error
import urllib.request
import pytest
from src.web import WebApp, make_server, BusyError


@pytest.fixture
def app(tmp_path):
    instance=WebApp(tmp_path/"web")
    yield instance
    instance.close()


def finished(app, run_id):
    deadline=time.monotonic()+10
    while time.monotonic()<deadline:
        state=app.snapshot(run_id)
        if not state["active"]:
            return state
        time.sleep(.01)
    pytest.fail("Agent did not finish")


def payload(**changes):
    return {"topic":"秋季新品推广","budget":10,"deadline":120,"backend":"mock",**changes}


def test_web_budget_replan_and_export(app):
    state=finished(app,app.create(payload()))
    assert state["status"]=="completed" and state["total_cost"]==8
    assert [p["result"]["estimate"]["total_cost"] for p in state["plan"] if p["tool"]=="estimate_cost"]==[12,8]
    assert (app.storage/"exports"/state["run_id"]/"trace.jsonl").is_file()
    assert len(app.history())==1


def test_web_missing_never_initializes_real_model(app,monkeypatch):
    monkeypatch.delenv("LLM_API_KEY",raising=False)
    state=finished(app,app.create(payload(budget=None,backend="real")))
    assert state["status"]=="needs_input" and state["tool_calls"]==0


def test_web_resume_and_idempotency(app):
    first=finished(app,app.create(payload(failure="generate_script",max_steps=2)))
    assert first["status"]=="incomplete"
    result=finished(app,app.resume(first["run_id"],{}))
    assert result["status"]=="completed" and result["plan"][1]["status"]=="failed"
    assert result["plan"][0]==first["plan"][0]
    second=finished(app,app.create(payload()))
    assert second["saved"]["already_exists"] and second["charged_cost"]==0
    assert len(list(app.saved.glob("*.json")))==1


@pytest.mark.parametrize("changes",[{"max_steps":0},{"max_steps":True},{"max_tool_calls":101},
    {"backend":"bad"},{"budget":-1},{"deadline":float("nan")},{"failure":"arbitrary"},
    {"topic":"x"*501},{"api_key":"not-accepted"}])
def test_bad_inputs(app,changes):
    with pytest.raises((ValueError,TypeError)):
        app.create(payload(**changes))
    assert not app.history()


def test_web_examples_read_only(app):
    examples=app.example_list()
    assert len(examples)>=19
    state=app.example("18-real-observed-replan")
    assert state["archived"] and not state["active"] and state["backend"]=="real"
    assert not app.history()
    with pytest.raises(ValueError):
        app.example("../.env")


def test_no_concurrent_resume(app,monkeypatch):
    entered=threading.Event()
    release=threading.Event()
    from src.llm import MockLLM
    class Slow(MockLLM):
        def choose(self,context):
            entered.set()
            assert release.wait(5)
            return super().choose(context)
    monkeypatch.setattr("src.web.MockLLM",Slow)
    run_id=app.create(payload())
    try:
        assert entered.wait(3)
        with pytest.raises(BusyError):
            app.resume(run_id,{})
    finally:
        release.set()
    assert finished(app,run_id)["status"]=="completed"


@pytest.fixture
def server(app):
    http=make_server(app,0)
    thread=threading.Thread(target=http.serve_forever,daemon=True)
    thread.start()
    yield "http://127.0.0.1:"+str(http.server_port)
    http.shutdown()
    http.server_close()
    thread.join()


def test_http_api_and_static_page(server,app):
    with urllib.request.urlopen(server) as response:
        html=response.read().decode()
        assert "内容规划工作台" in html and 'id="run-form"' in html
        assert "script-src 'self'" in response.headers["Content-Security-Policy"]
    request=urllib.request.Request(server+"/api/runs",data=json.dumps(payload()).encode(),
                                   headers={"Content-Type":"application/json"})
    with urllib.request.urlopen(request) as response:
        assert response.status==202
        run_id=json.load(response)["run_id"]
    state=finished(app,run_id)
    with urllib.request.urlopen(server+"/api/runs/"+run_id) as response:
        assert json.load(response)["total_cost"]==state["total_cost"]
    with urllib.request.urlopen(server+"/api/config") as response:
        assert set(json.load(response))=={"model","real_available"}


def test_http_rejects_cross_origin_and_files(server):
    request=urllib.request.Request(server+"/api/runs",data=b"{}",
        headers={"Content-Type":"application/json","Origin":"https://evil.example"})
    with pytest.raises(urllib.error.HTTPError) as error:
        urllib.request.urlopen(request)
    assert error.value.code==403
    with pytest.raises(urllib.error.HTTPError) as error:
        urllib.request.urlopen(server+"/.env")
    assert error.value.code==404


def test_resume_cannot_change_request(app):
    state=finished(app,app.create(payload(max_steps=1)))
    with pytest.raises(ValueError):
        app.resume(state["run_id"],{"budget":100})
    assert app.snapshot(state["run_id"])["request"]["budget"]==10
