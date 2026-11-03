"""All arithmetic and save authorization live here, never in model output."""
import itertools
import math
from src.tools import digest


def validate_request(request):
    missing = [k for k in ("topic", "budget", "deadline") if request.get(k) is None or request.get(k) == ""]
    if missing:
        return missing
    if not isinstance(request["topic"], str) or not request["topic"].strip():
        raise ValueError("topic must be nonempty text")
    for key in ("budget", "deadline"):
        value = request[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError(f"{key} must be a finite nonnegative number")
    return []


def totals(estimate):
    return (sum(c["cost"] for c in estimate["components"]),
            sum(c["minutes"] for c in estimate["components"]))


def gap_for(cost, minutes, request):
    return {"cost": max(0, cost - request["budget"]),
            "minutes": max(0, minutes - request["deadline"])}


def feasible_options(tools, request):
    options = []
    for variants in itertools.product(("full", "lite"), repeat=3):
        plan = {"variants": dict(zip(("search_materials", "generate_script", "save_plan"), variants))}
        estimate = tools.quote(plan)
        cost, minutes = totals(estimate)
        options.append({"variants": plan["variants"], "cost": cost, "minutes": minutes,
                        "gap": gap_for(cost, minutes, request)})
    return options


def assert_save_allowed(tools, request, plan, estimate):
    fresh = tools.quote(plan)
    if fresh != estimate or estimate["plan_hash"] != digest(plan):
        raise ValueError("stale_estimate: re-estimate the selected plan")
    cost, minutes = totals(fresh)
    gap = gap_for(cost, minutes, request)
    if any(gap.values()):
        raise ValueError(f"save_guardrail_rejected: cost={cost}, minutes={minutes}, gap={gap}")
    normalized = {**request, "budget": float(request["budget"]), "deadline": float(request["deadline"])}
    return digest({"request": normalized, "plan": plan}), cost, minutes
