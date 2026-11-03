from src.tools import Tools, digest


def test_quotes_and_idempotency(tmp_path):
    t = Tools(tmp_path)
    s = t.search_materials("秋季新品推广")
    assert t.generate_script(s["material_ids"])["quote"]["cost"] == 8
    plan = {"variants": {"search_materials":"full", "generate_script":"full", "save_plan":"full"}}
    assert t.estimate_cost(plan)["total_cost"] == 12
    plan["variants"]["generate_script"] = "lite"
    assert t.estimate_cost(plan)["total_cost"] == 8
    key = digest(plan)
    assert t.save_plan(plan, key)["charged_cost"] == 8
    assert t.save_plan(plan, key)["charged_cost"] == 0
    assert len(list(tmp_path.glob("*.json"))) == 1
