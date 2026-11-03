"""Real ReAct execution skeleton: every next action comes from the backend."""
import json
from src.state import RunState
from src.tools import ToolError
from src.guardrails import validate_request, totals, gap_for, feasible_options, assert_save_allowed
from src.llm import ModelError

SCHEMAS = {
    "search_materials":{"topic":str,"variant":str},
    "generate_script":{"search_step":str,"variant":str},
    "estimate_cost":{"script_step":str,"save_variant":str},
    "save_plan":{"estimate_step":str},
    "finish":{"reason":str},
    "ask_user":{"fields":list},
}


class Agent:
    def __init__(self, state, model, tools, runs_dir="runs"):
        self.s, self.model, self.tools, self.runs_dir = state, model, tools, runs_dir
        self.tools.failures = dict(state.failures_remaining)
        self.tools.run_id = state.run_id

    def persist(self):
        self.s.persist(self.runs_dir)

    def event(self, action, args, observation, rationale="", **extra):
        s = self.s
        if s.events:
            s.events[-1]["next_action"] = action
        s.events.append({"step":s.used_steps, "action":action,"args":args,
                         "observation":observation,"rationale":rationale,
                         "state": {"status":s.status,"total_cost":s.total_cost,
                                   "total_minutes":s.total_minutes,"charged_cost":s.charged_cost,
                                   "tool_calls":s.tool_calls,
                                   "steps":{p["id"]:p["status"] for p in s.plan}},
                         "next_action":None, **extra})
        self.persist()

    def observe(self, action, args, obs, rationale):
        self.s.observations.append(obs)
        step = next((p for p in self.s.plan if p["id"] == obs.get("step_id")), None)
        self.event(action,args,obs,rationale,tool_args=step.get("tool_args") if step else None)

    def validate(self, raw):
        if isinstance(raw, str):
            raw = json.loads(raw)
        if not isinstance(raw, dict) or set(raw) != {"action","args","rationale"}:
            raise ValueError("action requires exactly action, args, rationale")
        name, args = raw["action"], raw["args"]
        if not isinstance(name,str) or name not in SCHEMAS:
            raise ValueError("unknown action")
        if not isinstance(raw["rationale"],str) or not 1 <= len(raw["rationale"]) <= 1000:
            raise ValueError("rationale must be 1..1000 characters")
        if not isinstance(args,dict) or set(args) != set(SCHEMAS[name]):
            raise ValueError("illegal argument names")
        if any(not isinstance(args[k],typ) for k,typ in SCHEMAS[name].items()):
            raise ValueError("illegal argument types")
        for k in ("variant","save_variant"):
            if k in args and args[k] not in ("full","lite"):
                raise ValueError("variant must be full or lite")
        if name == "search_materials" and args["topic"] != self.s.request["topic"]:
            raise ValueError("topic must match request")
        if name == "ask_user" and (not args["fields"] or any(not isinstance(f,str) for f in args["fields"])):
            raise ValueError("fields must be nonempty list of strings")
        return name, args, raw["rationale"]

    def prepare(self, name, args):
        s = self.s
        if name == "search_materials":
            return args, []
        if name == "generate_script":
            search = s.successful(args["search_step"],"search_materials")
            return {"material_ids":search["result"]["material_ids"],"variant":args["variant"]}, [search["id"]]
        if name == "estimate_cost":
            script = s.successful(args["script_step"],"generate_script")
            search = s.successful(script["dependencies"][0],"search_materials")
            plan = {"topic":s.request["topic"], "material_ids":script["result"]["material_ids"],
                    "script":script["result"]["script"],
                    "variants":{"search_materials":search["result"]["variant"],
                                "generate_script":script["result"]["variant"], "save_plan":args["save_variant"]}}
            return {"plan":plan}, [script["id"]]
        estimate = s.successful(args["estimate_step"],"estimate_cost")
        script = s.successful(estimate["dependencies"][0],"generate_script")
        s.successful(script["dependencies"][0],"search_materials")
        plan = estimate["tool_args"]["plan"]
        key, _, _ = assert_save_allowed(self.tools, s.request, plan, estimate["result"]["estimate"])
        return {"plan":plan,"idempotency_key":key}, [estimate["id"]]

    def run(self, resume=False):
        s = self.s
        if s.status == "completed":
            return s
        missing = validate_request(s.request)
        if missing:
            s.status, s.reason, s.missing_fields = "needs_input", "missing_fields", missing
            self.event("input_validation", {}, {"missing_fields":missing})
            return s
        if resume:
            for p in s.plan:
                if p["status"] == "running":
                    p.update(status="failed", error="interrupted_unknown_outcome")
                    self.persist()
            s.status, s.reason = "running", None
            self.event("resume",{}, {"reused_successful_steps":[p["id"] for p in s.plan if p["status"]=="succeeded"]})
        else:
            s.status = "running"
            self.persist()
        options = feasible_options(self.tools,s.request)
        while s.used_steps < s.max_steps and s.tool_calls < s.max_tool_calls:
            s.used_steps += 1
            self.persist()
            try:
                raw = self.model.choose({"state":s.to_dict(), "feasible_options":options,
                                         "tool_costs":self.tools.costs})
            except ModelError as exc:
                s.status, s.reason = "incomplete", "model_error"
                self.event("model_error",{}, {"error":str(exc)})
                return s
            try:
                name,args,why = self.validate(raw)
            except (ValueError,TypeError) as exc:
                self.observe("invalid_action",{}, {"error":str(exc)}, "动作校验失败，返回模型修正。")
                continue
            if name == "ask_user":
                s.status,s.reason,s.missing_fields = "needs_input","model_requested_input",args["fields"]
                self.event(name,args,{"missing_fields":args["fields"]},why)
                return s
            if name == "finish":
                reason = args["reason"]
                if s.saved:
                    s.status,s.reason = "completed",None
                elif reason == "no_feasible_plan":
                    if any(not any(o["gap"].values()) for o in options):
                        self.observe(name,args,{"error":"feasible_option_exists","options":options},why)
                        continue
                    best = min(options,key=lambda o:(o["cost"],o["minutes"]))
                    s.status,s.reason = "incomplete","no_feasible_plan"
                    s.gap = {"minimum_cost":best["cost"],"minimum_minutes":min(o["minutes"] for o in options),
                             **best["gap"],"alternatives":options}
                elif reason == "completed":
                    self.observe(name,args,{"error":"cannot_finish_without_save"},why)
                    continue
                else:
                    s.status,s.reason = "incomplete","model_stopped"
                self.event(name,args,{"status":s.status,"reason":s.reason,"gap":s.gap},why)
                return s
            if s.saved:
                self.observe(name,args,{"error":"plan_already_committed: finish required"},why)
                continue
            step = {"id":f"s{len(s.plan)+1}","tool":name,"args":args,
                    "dependencies":[],"status":"pending","result":None}
            s.plan.append(step)
            self.persist()
            try:
                tool_args, deps = self.prepare(name,args)
                step.update(tool_args=tool_args,dependencies=deps)
                # The model requested this action. Reusing an identical successful result
                # is an executor cache, never an automatic next-action decision.
                cached = next((p for p in s.plan[:-1] if p["status"]=="succeeded"
                               and p["tool"]==name and p["args"]==args),None)
                if cached and name != "save_plan":
                    step.update(status="skipped", reused_step=cached["id"])
                    self.observe(name,args,{"reused_step":cached["id"],"result":cached["result"]},why)
                    continue
                step["status"] = "running"
                s.tool_calls += 1
                # Persist consumed injection before execution, so resume won't inject twice.
                if s.failures_remaining.get(name,0)>0:
                    s.failures_remaining[name] -= 1
                self.persist()
                result = self.tools.invoke(name,**tool_args)
                if name == "estimate_cost":
                    cost,minutes = totals(result)
                    result = {"estimate":result,"gap":gap_for(cost,minutes,s.request)}
                    s.selected_plan = tool_args["plan"]
                    s.total_cost,s.total_minutes = cost,minutes
                if name == "save_plan":
                    quote = self.tools.quote(tool_args["plan"])
                    s.total_cost,s.total_minutes = totals(quote)
                    s.selected_plan,s.saved = tool_args["plan"],result
                    if result.get("committed_by") == s.run_id and not any(
                            entry["idempotency_key"] == tool_args["idempotency_key"] for entry in s.ledger):
                        result["charged_cost"] = quote["total_cost"]
                        result["recovered_commit"] = result["already_exists"]
                    s.ledger.append({"step_id":step["id"],"idempotency_key":tool_args["idempotency_key"],
                                     "components":quote["components"],"charged_cost":result["charged_cost"],
                                     "already_exists":result["already_exists"]})
                step.update(status="succeeded",result=result)
                self.persist()
                self.observe(name,args,{"step_id":step["id"],"tool":name,"result":result},why)
            except (ValueError,ToolError,OSError) as exc:
                step.update(status="failed",error=str(exc))
                self.persist()
                self.observe(name,args,{"step_id":step["id"],"tool":name,"error":str(exc)},why)
        s.status,s.reason = "incomplete","max_steps_reached"
        self.event("limit",{}, {"reason":s.reason,
                   "limit":"max_steps" if s.used_steps>=s.max_steps else "max_tool_calls"})
        return s
