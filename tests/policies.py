"""Adversarial scripted policies for executor tests; never real model evidence."""
from src.llm import MockLLM


class SequenceLLM:
    name = "mock-adversarial"
    def __init__(self, actions):
        self.actions = list(actions)
        self.contexts = []

    def choose(self, context):
        self.contexts.append(context)
        if self.actions:
            return self.actions.pop(0)
        return MockLLM().choose(context)


def action(name, **args):
    return {"action":name,"args":args,"rationale":"测试策略请求，用于验证执行器护栏。"}


def force_save():
    return SequenceLLM([
        action("search_materials",topic="秋季新品推广",variant="full"),
        action("generate_script",search_step="s1",variant="full"),
        action("estimate_cost",script_step="s2",save_variant="full"),
        action("save_plan",estimate_step="s3"),
    ])
