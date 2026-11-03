"""Persist every transition atomically; historical attempts are append-only."""
import json
import os
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path


@dataclass
class RunState:
    request: dict
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    plan: list = field(default_factory=list)
    ledger: list = field(default_factory=list)
    events: list = field(default_factory=list)
    observations: list = field(default_factory=list)
    used_steps: int = 0
    tool_calls: int = 0
    status: str = "pending"
    reason: str | None = None
    selected_plan: dict | None = None
    total_cost: int = 0
    total_minutes: int = 0
    saved: dict | None = None
    gap: dict = field(default_factory=dict)
    missing_fields: list = field(default_factory=list)
    failures_remaining: dict = field(default_factory=dict)
    backend: str = "mock"
    backend_config: dict = field(default_factory=dict)
    injection_config: dict = field(default_factory=dict)
    max_steps: int = 12
    max_tool_calls: int = 12

    def __post_init__(self):
        if not self.injection_config:
            self.injection_config = dict(self.failures_remaining)

    @property
    def charged_cost(self):
        return sum(item["charged_cost"] for item in self.ledger)

    def to_dict(self):
        return {**asdict(self), "charged_cost": self.charged_cost}

    def persist(self, directory):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{self.run_id}.json"
        temp = path.with_suffix(".tmp")
        with temp.open("w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)

    @classmethod
    def load(cls, directory, run_id):
        if not run_id.isalnum():
            raise ValueError("invalid run_id")
        value = json.loads((Path(directory) / f"{run_id}.json").read_text(encoding="utf-8"))
        value.pop("charged_cost", None)
        return cls(**value)

    def successful(self, step_id, tool):
        for step in self.plan:
            if step["id"] == step_id and step["tool"] == tool and step["status"] == "succeeded":
                return step
        raise ValueError(f"dependency_not_satisfied: {step_id} must be succeeded {tool}")
