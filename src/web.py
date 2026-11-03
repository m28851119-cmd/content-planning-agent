"""Local interactive UI adapter. All decisions and accounting still use Agent.

Run: python -m src.web
This is a loopback-only development server, not a public hosting runtime.
"""
import argparse
import json
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from src.agent import Agent
from src.guardrails import validate_request
from src.llm import MockLLM, RealLLM
from src.state import RunState
from src.tools import Tools
from src.trace import export_run

ROOT = Path(__file__).resolve().parents[1]
TOOL_NAMES = {"search_materials", "generate_script", "estimate_cost", "save_plan"}


class BusyError(Exception):
    pass


class WebApp:
    def __init__(self, storage="runs/web", examples=None):
        self.storage = Path(storage)
        self.states = self.storage / "states"
        self.saved = self.storage / "saved"
        self.examples = Path(examples or ROOT / "examples")
        self.states.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.active = set()
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="agent")

    @staticmethod
    def limit(value):
        if type(value) is not int or not 1 <= value <= 100:
            raise ValueError("步数和调用上限必须是 1 到 100 的整数")
        return value

    def create(self, body):
        if not isinstance(body, dict):
            raise ValueError("请求必须是 JSON 对象")
        allowed = {"topic", "budget", "deadline", "backend", "max_steps", "max_tool_calls", "failure"}
        if set(body) - allowed:
            raise ValueError("请求含未知字段")
        request = {k: body.get(k) for k in ("topic", "budget", "deadline")}
        validate_request(request)
        if isinstance(request["topic"], str) and len(request["topic"]) > 500:
            raise ValueError("主题不能超过 500 个字符")
        backend = body.get("backend", "mock")
        if backend not in ("mock", "real"):
            raise ValueError("不支持的模型后端")
        failures = {}
        if body.get("failure"):
            if body["failure"] not in TOOL_NAMES:
                raise ValueError("不支持的故障工具")
            failures[body["failure"]] = 1
        state = RunState(request, backend=backend, failures_remaining=failures,
                         max_steps=self.limit(body.get("max_steps", 12)),
                         max_tool_calls=self.limit(body.get("max_tool_calls", 12)))
        self.submit(state)
        return state.run_id

    def resume(self, run_id, body):
        if not isinstance(body, dict) or set(body) - {"max_steps", "max_tool_calls"}:
            raise ValueError("续跑只能修改累计步数和调用上限")
        with self.lock:
            if run_id in self.active:
                raise BusyError("这个任务正在运行")
            state = RunState.load(self.states, run_id)
            if state.status in ("completed", "needs_input"):
                raise ValueError("已完成任务无需续跑；缺少输入时请补齐后新建任务")
            state.max_steps = self.limit(body.get("max_steps", min(100, max(12, state.used_steps + 12))))
            state.max_tool_calls = self.limit(body.get("max_tool_calls", min(100, max(12, state.tool_calls + 12))))
            if state.max_steps <= state.used_steps or state.max_tool_calls <= state.tool_calls:
                raise ValueError("累计上限必须大于已经使用的次数")
            self.submit(state, resume=True)
        return run_id

    def submit(self, state, resume=False):
        with self.lock:
            if len(self.active) >= 2:
                raise BusyError("已有两个任务运行中，请等待完成")
            state.persist(self.states)
            self.active.add(state.run_id)
            try:
                self.pool.submit(self.execute, state, resume)
            except Exception:
                self.active.discard(state.run_id)
                raise

    def execute(self, state, resume):
        agent = None
        try:
            missing = validate_request(state.request)
            model = MockLLM() if missing or state.backend == "mock" else RealLLM()
            if isinstance(model, RealLLM):
                state.backend_config = {"model": model.model, "base_url": model.base_url}
            app_lock = self.lock
            class WebAgent(Agent):
                def persist(self):
                    # Windows readers and atomic replacements share one process lock.
                    with app_lock:
                        super().persist()
            agent = WebAgent(state, model, Tools(self.saved), self.states)
            agent.run(resume=resume)
        except Exception as exc:
            state.status, state.reason = "incomplete", "web_execution_error"
            # Exception type only: never expose environment, credentials, or HTTP headers.
            state.events.append({"step": state.used_steps, "action": "web_error", "args": {},
                                 "observation": {"error": type(exc).__name__},
                                 "rationale": "运行异常；请检查服务端模型配置或重试。",
                                 "next_action": None})
            with self.lock:
                state.persist(self.states)
        finally:
            try:
                export_run(state, self.storage / "exports" / state.run_id)
            finally:
                with self.lock:
                    self.active.discard(state.run_id)

    def snapshot(self, run_id):
        with self.lock:
            state = RunState.load(self.states, run_id).to_dict()
            state["active"] = run_id in self.active
        return state

    def history(self):
        result = []
        for path in sorted(self.states.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:100]:
            state = self.snapshot(path.stem)
            result.append({k: state[k] for k in ("run_id", "request", "status", "backend", "active", "total_cost")})
        return result

    def example_list(self):
        return [{"id": p.parent.name, "topic": s["request"]["topic"],
                 "backend": s["backend"], "status": s["status"]}
                for p in sorted(self.examples.glob("*/output.json"))
                for s in [json.loads(p.read_text(encoding="utf-8"))]]

    def example(self, name):
        if not re.fullmatch(r"[a-zA-Z0-9-]+", name):
            raise ValueError("非法示例名称")
        state = json.loads((self.examples / name / "output.json").read_text(encoding="utf-8"))
        return {**state, "active": False, "archived": True}

    def close(self):
        self.pool.shutdown(wait=True)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    @property
    def app(self):
        return self.server.app

    def respond(self, value, status=200, content_type="application/json; charset=utf-8"):
        data = json.dumps(value, ensure_ascii=False).encode() if not isinstance(value, bytes) else value
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'")
        self.end_headers()
        self.wfile.write(data)

    def valid_origin(self):
        host = self.headers.get("Host", "")
        allowed = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
        return host in allowed and self.headers.get("Origin", "http://" + host) == "http://" + host

    def do_GET(self):
        if not self.valid_origin():
            return self.respond({"error": "仅允许本机同源请求"}, 403)
        path = urlsplit(self.path).path
        try:
            if path == "/api/config":
                return self.respond({"real_available": bool(os.getenv("LLM_API_KEY")),
                                     "model": os.getenv("LLM_MODEL", "deepseek-v4-pro")})
            if path == "/api/runs":
                return self.respond(self.app.history())
            if path.startswith("/api/runs/"):
                return self.respond(self.app.snapshot(path.removeprefix("/api/runs/")))
            if path == "/api/examples":
                return self.respond(self.app.example_list())
            if path.startswith("/api/examples/"):
                return self.respond(self.app.example(path.removeprefix("/api/examples/")))
            files = {"/": ("index.html", "text/html; charset=utf-8"),
                     "/app.js": ("app.js", "application/javascript; charset=utf-8"),
                     "/styles.css": ("styles.css", "text/css; charset=utf-8"),
                     "/favicon.svg": ("favicon.svg", "image/svg+xml")}
            if path in files:
                filename, mime = files[path]
                return self.respond((ROOT / "frontend" / filename).read_bytes(), content_type=mime)
            return self.respond({"error": "未找到资源"}, 404)
        except (FileNotFoundError, ValueError):
            return self.respond({"error": "未找到任务或示例"}, 404)

    def do_POST(self):
        if not self.valid_origin():
            return self.respond({"error": "仅允许本机同源请求"}, 403)
        try:
            if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                return self.respond({"error": "需要 application/json"}, 415)
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 8192:
                return self.respond({"error": "请求过大或为空"}, 413)
            body = json.loads(self.rfile.read(length))
            path = urlsplit(self.path).path
            if path == "/api/runs":
                run_id = self.app.create(body)
            elif re.fullmatch(r"/api/runs/[a-zA-Z0-9]+/resume", path):
                run_id = self.app.resume(path.split("/")[3], body)
            else:
                return self.respond({"error": "未找到接口"}, 404)
            self.respond({"run_id": run_id}, 202)
        except BusyError as exc:
            self.respond({"error": str(exc)}, 409)
        except FileNotFoundError:
            self.respond({"error": "任务不存在"}, 404)
        except (ValueError, TypeError) as exc:
            self.respond({"error": str(exc)}, 400)


def make_server(app, port=8765):
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.app = app
    return server


def main():
    parser = argparse.ArgumentParser(description="内容任务规划交互工作台")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--storage", default="runs/web")
    args = parser.parse_args()
    app = WebApp(args.storage)
    server = make_server(app, args.port)
    print(f"Content planning studio: http://127.0.0.1:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        app.close()


if __name__ == "__main__":
    main()
