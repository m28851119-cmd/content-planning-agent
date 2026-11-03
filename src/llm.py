"""OpenAI-compatible backend and an explicitly scripted OFFLINE flow validator.

MockLLM is NOT evidence of actual language-model decision quality.
No backend automatically retries failed model or tool calls.
"""
import json
import os
import urllib.request


SYSTEM = """You are a content planning agent. Choose ONE action per response, as JSON:
{"action":"...","args":{...},"rationale":"one or two short sentences"}
Do not return internal reasoning. All arithmetic, dependencies and saving are enforced by code.
Actions and exact args:
search_materials: {"topic": request.topic, "variant":"full"|"lite"}
generate_script: {"search_step":"successful search step id","variant":"full"|"lite"}
estimate_cost: {"script_step":"successful generation step id","save_variant":"full"|"lite"}
save_plan: {"estimate_step":"successful estimate step id"}
finish: {"reason":"completed"|"no_feasible_plan"|"model_stopped"}
ask_user: {"fields":["field name"]}
Read observation and state. For the evaluation, first explore a full-quality candidate
and request its estimate as the quality baseline, even if the price table suggests
it may exceed the budget. Then adjust using the observed quote. This is a planning
preference, not an executor-enforced action sequence. Estimate before saving.
If quote exceeds constraints choose another variant, reuse successful search if useful,
generate and estimate again. Failed attempts are not successes. You may retry or downgrade.
The provided feasible_options are code-computed candidate quotes, not executed plans.
Never claim completion without a saved plan. Prefer finish no_feasible_plan if none fit.
"""


class ModelError(Exception):
    pass


class RealLLM:
    name = "real"

    def __init__(self):
        self.base_url = os.getenv("LLM_BASE_URL", "https://api.deepseek.com").rstrip("/")
        self.model = os.getenv("LLM_MODEL", "deepseek-v4-pro")
        self.key = os.getenv("LLM_API_KEY")
        if not self.key:
            raise ModelError("LLM_API_KEY is missing; use --mock-llm for offline validation")
        if not self.base_url.startswith("https://") and not self.base_url.startswith("http://localhost"):
            raise ModelError("LLM_BASE_URL requires HTTPS (or localhost)")

    def choose(self, context):
        payload = {"model":self.model, "messages":[{"role":"system","content":SYSTEM},
                   {"role":"user","content":json.dumps(context, ensure_ascii=False)}],
                   "response_format":{"type":"json_object"}, "stream":False}
        request = urllib.request.Request(self.base_url + "/chat/completions",
                  data=json.dumps(payload).encode(), headers={
                  "Authorization":"Bearer " + self.key, "Content-Type":"application/json"})
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                value = json.load(response)
            # Provider reasoning_content is deliberately neither read nor logged.
            return value["choices"][0]["message"]["content"]
        except Exception as exc:
            # Do not log request headers, keys or provider error bodies.
            raise ModelError(f"model_request_failed: {type(exc).__name__}") from None


class MockLLM:
    """Scripted observation-based policy. Tests flow ONLY, not real model decisions."""
    name = "mock"

    def choose(self, context):
        s = context["state"]
        steps = s["plan"]
        def action(name, args, why):
            return {"action":name,"args":args,"rationale":why}
        def latest(tool):
            return next((p for p in reversed(steps) if p["tool"] == tool and p["status"] == "succeeded"), None)
        if s["saved"]:
            return action("finish", {"reason":"completed"}, "保存结果已确认。")
        options = context["feasible_options"]
        feasible = [o for o in options if not any(o["gap"].values())]
        if not feasible:
            return action("finish", {"reason":"no_feasible_plan"}, "代码计算的所有候选均不满足约束。")
        search = latest("search_materials")
        script = latest("generate_script")
        estimate = latest("estimate_cost")
        last = s["observations"][-1] if s["observations"] else {}
        if last.get("error") == "injected_failure" and last.get("tool") == "generate_script":
            return action("generate_script", {"search_step":search["id"],"variant":"lite"},
                          "脚本生成失败，保留成功检索并改为轻量版。")
        if estimate and any(estimate["result"]["gap"].values()):
            preferred = next((o for o in feasible if o["variants"]["search_materials"] == search["args"]["variant"]), feasible[0])
            variants = preferred["variants"]
            if search["args"]["variant"] != variants["search_materials"]:
                return action("search_materials", {"topic":s["request"]["topic"],"variant":variants["search_materials"]}, "估算超限，减少素材范围。")
            if not script or script["args"]["variant"] != variants["generate_script"] or script["dependencies"] != [search["id"]]:
                return action("generate_script", {"search_step":search["id"],"variant":variants["generate_script"]}, "观察到超限报价，改选可行的脚本版本。")
            if estimate["dependencies"] != [script["id"]] or estimate["args"]["save_variant"] != variants["save_plan"]:
                return action("estimate_cost", {"script_step":script["id"],"save_variant":variants["save_plan"]}, "替代方案必须重新估算。")
        if not search:
            return action("search_materials", {"topic":s["request"]["topic"],"variant":"full"}, "先获取主题素材。")
        if not script:
            return action("generate_script", {"search_step":search["id"],"variant":"full"}, "使用已成功检索的素材生成脚本。")
        if not estimate or estimate["dependencies"] != [script["id"]]:
            return action("estimate_cost", {"script_step":script["id"],"save_variant":"full"}, "获取代码计算的费用与时间。")
        return action("save_plan", {"estimate_step":estimate["id"]}, "估算符合约束，请求保存并接受最终护栏校验。")
