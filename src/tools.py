"""Local mocks. Charges describe selected plan components, not paid API calls.

Search/generation are free previews; save commits the selected component quote.
An abandoned preview therefore never silently becomes an incurred expense.
"""
import hashlib
import json
import os
import uuid
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data"


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


class ToolError(Exception):
    pass


class Tools:
    def __init__(self, saved_dir="saved_plans", costs_path=None, failures=None):
        self.saved_dir = Path(saved_dir)
        self.costs = json.loads(Path(costs_path or DATA / "tool_costs.json").read_text(encoding="utf-8"))
        self.materials = json.loads((DATA / "materials.json").read_text(encoding="utf-8"))
        self.failures = dict(failures or {})

    def price(self, tool, variant):
        if variant not in ("full", "lite"):
            raise ToolError("variant must be full or lite")
        p = self.costs[tool][variant]
        if any(isinstance(p[k], bool) or not isinstance(p[k], int) or p[k] < 0 for k in ("cost", "minutes")):
            raise ToolError("cost table must contain nonnegative integers")
        return dict(p)

    def invoke(self, name, **args):
        if self.failures.get(name, 0) > 0:
            self.failures[name] -= 1
            raise ToolError("injected_failure")
        return getattr(self, name)(**args)

    def search_materials(self, topic, variant="full"):
        ranked = sorted(self.materials, key=lambda m: -sum(t in topic for t in m["tags"]))
        chosen = ranked[:2 if variant == "full" else 1]
        return {"material_ids": [m["id"] for m in chosen], "materials": chosen,
                "variant": variant, "quote": self.price("search_materials", variant)}

    def generate_script(self, material_ids, variant="full"):
        known = {m["id"]: m for m in self.materials}
        if not material_ids or any(m not in known for m in material_ids):
            raise ToolError("unknown or empty material_ids")
        text = "\n".join(known[m]["text"] for m in material_ids)
        return {"script": f"[{variant}] 开场：提出场景问题。\n{text}\n行动：邀请参与活动。",
                "material_ids": material_ids, "variant": variant,
                "quote": self.price("generate_script", variant)}

    def quote(self, plan):
        # Pure accounting helper: not a model tool invocation.
        components = [{"tool": name, "variant": variant, **self.price(name, variant)}
                      for name, variant in plan["variants"].items()]
        return {"components": components, "total_cost": sum(c["cost"] for c in components),
                "total_minutes": sum(c["minutes"] for c in components), "plan_hash": digest(plan)}

    def estimate_cost(self, plan):
        return self.quote(plan)

    def save_plan(self, plan, idempotency_key):
        # Exclusive creation prevents a second charge/write for the same content.
        if len(idempotency_key) != 64 or any(c not in "0123456789abcdef" for c in idempotency_key):
            raise ToolError("invalid idempotency key")
        self.saved_dir.mkdir(parents=True, exist_ok=True)
        path = self.saved_dir / f"{idempotency_key}.json"
        record = {"idempotency_key": idempotency_key, "plan": plan,
                  "committed_by": getattr(self, "run_id", None)}
        temp = self.saved_dir / f".{idempotency_key}.{uuid.uuid4().hex}.tmp"
        try:
            with temp.open("x", encoding="utf-8") as f:
                f.write(canonical(record))
                f.flush()
                os.fsync(f.fileno())
            try:
                # Atomic no-overwrite publication on the same filesystem.
                if os.name == "nt":
                    os.rename(temp, path)  # Windows rename refuses an existing destination.
                else:
                    os.link(temp, path)
            except FileExistsError:
                existing = json.loads(path.read_text(encoding="utf-8"))
                if existing["plan"] != plan or existing["idempotency_key"] != idempotency_key:
                    raise ToolError("idempotency_conflict")
                return {"path": str(path), "already_exists": True, "charged_cost": 0,
                        "committed_by": existing.get("committed_by")}
        finally:
            temp.unlink(missing_ok=True)
        return {"path": str(path), "already_exists": False,
                "committed_by": record["committed_by"],
                "charged_cost": self.quote(plan)["total_cost"]}
