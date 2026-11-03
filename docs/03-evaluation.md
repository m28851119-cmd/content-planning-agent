# 03 验收与实际结果

本表由 scripts.report_evaluation 读取实际 output.json 自动生成，原始输出与 Trace 没有手工改写。01–15 为 Mock 运行，只验证执行流程；16–19 为真实 DeepSeek Pro 调用，工具仍为本地 Mock。

## 测试

实际 pytest 结果：**41 passed in 8.49s**。完整输出：[examples/pytest-results.txt](../examples/pytest-results.txt)。测试不访问真实 API，真实网络样本单独保留，不能混淆为大规模模型评测。环境 Windows / Python 3.12.15 / pytest 8.3.5。

## 场景对照

| 场景/后端 | 预期 | 实际读取结果 | 证据 |
|---|---|---|---|
| 01-normal (mock) | completed，12 | completed; 报价 12; 扣费 12; 55 分钟; 4 调用; 估算 12 | [输入](../examples/01-normal/input.json) · [输出](../examples/01-normal/output.json) · [Trace](../examples/01-normal/trace.jsonl) |
| 02-missing-budget (mock) | needs_input，0 调用 | needs_input; 报价 0; 扣费 0; 0 分钟; 0 调用; missing_fields | [输入](../examples/02-missing-budget/input.json) · [输出](../examples/02-missing-budget/output.json) · [Trace](../examples/02-missing-budget/trace.jsonl) |
| 03-missing-deadline (mock) | needs_input，0 调用 | needs_input; 报价 0; 扣费 0; 0 分钟; 0 调用; missing_fields | [输入](../examples/03-missing-deadline/input.json) · [输出](../examples/03-missing-deadline/output.json) · [Trace](../examples/03-missing-deadline/trace.jsonl) |
| 04-tool-failure (mock) | 失败保留，调整成功 | completed; 报价 8; 扣费 8; 35 分钟; 5 调用; 估算 8; failed=s2 | [输入](../examples/04-tool-failure/input.json) · [输出](../examples/04-tool-failure/output.json) · [Trace](../examples/04-tool-failure/trace.jsonl) |
| 05-resume-before (mock) | 2 轮后 incomplete | incomplete; 报价 0; 扣费 0; 0 分钟; 2 调用; failed=s2; max_steps_reached | [输入](../examples/05-resume-before/input.json) · [输出](../examples/05-resume-before/output.json) · [Trace](../examples/05-resume-before/trace.jsonl) |
| 06-resume-after (mock) | 同 run 续跑成功，保留检索 | completed; 报价 8; 扣费 8; 35 分钟; 5 调用; 估算 8; failed=s2 | [输入](../examples/06-resume-after/input.json) · [输出](../examples/06-resume-after/output.json) · [Trace](../examples/06-resume-after/trace.jsonl) |
| 07-budget-replan (mock) | 估算 12 → 8，保存 | completed; 报价 8; 扣费 8; 35 分钟; 6 调用; 估算 12 → 8 | [输入](../examples/07-budget-replan/input.json) · [输出](../examples/07-budget-replan/output.json) · [Trace](../examples/07-budget-replan/trace.jsonl) |
| 08-no-feasible (mock) | 预算 5，最低 6，缺口 1 | incomplete; 报价 0; 扣费 0; 0 分钟; 0 调用; no_feasible_plan; 最低 6，费用缺口 1 | [输入](../examples/08-no-feasible/input.json) · [输出](../examples/08-no-feasible/output.json) · [Trace](../examples/08-no-feasible/trace.jsonl) |
| 09-duplicate-first (mock) | 首次扣费 8 | completed; 报价 8; 扣费 8; 35 分钟; 6 调用; 估算 12 → 8 | [输入](../examples/09-duplicate-first/input.json) · [输出](../examples/09-duplicate-first/output.json) · [Trace](../examples/09-duplicate-first/trace.jsonl) |
| 10-duplicate-second (mock) | 同文件，扣费 0 | completed; 报价 8; 扣费 0; 35 分钟; 6 调用; 估算 12 → 8 | [输入](../examples/10-duplicate-second/input.json) · [输出](../examples/10-duplicate-second/output.json) · [Trace](../examples/10-duplicate-second/trace.jsonl) |
| 11-max-steps (mock) | incomplete/max_steps_reached | incomplete; 报价 0; 扣费 0; 0 分钟; 1 调用; max_steps_reached | [输入](../examples/11-max-steps/input.json) · [输出](../examples/11-max-steps/output.json) · [Trace](../examples/11-max-steps/trace.jsonl) |
| 12-save-guardrail (mock-adversarial) | 拒绝 12，调整至 8 后保存 | completed; 报价 8; 扣费 8; 35 分钟; 6 调用; 估算 12 → 8; failed=s4 | [输入](../examples/12-save-guardrail/input.json) · [输出](../examples/12-save-guardrail/output.json) · [Trace](../examples/12-save-guardrail/trace.jsonl) |
| 13-max-tool-calls (mock) | 工具上限触发，保留成功 | incomplete; 报价 0; 扣费 0; 0 分钟; 1 调用; max_steps_reached | [输入](../examples/13-max-tool-calls/input.json) · [输出](../examples/13-max-tool-calls/output.json) · [Trace](../examples/13-max-tool-calls/trace.jsonl) |
| 14-deadline-replan (mock) | 模拟耗时 ≤29 | completed; 报价 6; 扣费 6; 28 分钟; 7 调用; 估算 12 → 6 | [输入](../examples/14-deadline-replan/input.json) · [输出](../examples/14-deadline-replan/output.json) · [Trace](../examples/14-deadline-replan/trace.jsonl) |
| 15-invalid-action (mock-adversarial) | 返回错误后模型修正 | completed; 报价 12; 扣费 12; 55 分钟; 4 调用; 估算 12 | [输入](../examples/15-invalid-action/input.json) · [输出](../examples/15-invalid-action/output.json) · [Trace](../examples/15-invalid-action/trace.jsonl) |
| 16-real-budget-replan (real) | 真实模型预算内完成；不保证走重规划 | completed; 报价 8; 扣费 8; 35 分钟; 4 调用; 估算 8 | [输入](../examples/16-real-budget-replan/input.json) · [输出](../examples/16-real-budget-replan/output.json) · [Trace](../examples/16-real-budget-replan/trace.jsonl) |
| 17-real-tool-failure (real) | 真实模型处理失败；可重试或降级 | completed; 报价 8; 扣费 8; 35 分钟; 5 调用; 估算 8; failed=s2 | [输入](../examples/17-real-tool-failure/input.json) · [输出](../examples/17-real-tool-failure/output.json) · [Trace](../examples/17-real-tool-failure/trace.jsonl) |
| 18-real-observed-replan (real) | 真实模型先评估 full，再据超限调整 | completed; 报价 8; 扣费 8; 35 分钟; 6 调用; 估算 12 → 8 | [输入](../examples/18-real-observed-replan/input.json) · [输出](../examples/18-real-observed-replan/output.json) · [Trace](../examples/18-real-observed-replan/trace.jsonl) |
| 19-real-failure-final (real) | 真实模型依据失败选择下一步 | completed; 报价 12; 扣费 12; 55 分钟; 5 调用; 估算 12; failed=s2 | [输入](../examples/19-real-failure-final/input.json) · [输出](../examples/19-real-failure-final/output.json) · [Trace](../examples/19-real-failure-final/trace.jsonl) |

## 对应测试

- 01-normal: `tests/test_agent.py::test_normal`。
- 02-missing-budget: `tests/test_acceptance.py::test_missing_no_tool_no_model`。
- 03-missing-deadline: `tests/test_acceptance.py::test_missing_no_tool_no_model`。
- 04-tool-failure: `tests/test_agent.py::test_failure`。
- 05-resume-before: `tests/test_acceptance.py::test_resume_only_remaining`。
- 06-resume-after: `tests/test_acceptance.py::test_resume_only_remaining`。
- 07-budget-replan: `tests/test_agent.py::test_replan`。
- 08-no-feasible: `tests/test_acceptance.py::test_no_feasible_gap`。
- 09-duplicate-first: `tests/test_acceptance.py::test_idempotency_across_runs`。
- 10-duplicate-second: `tests/test_acceptance.py::test_idempotency_across_runs`。
- 11-max-steps: `tests/test_acceptance.py::test_limits`。
- 12-save-guardrail: `tests/test_acceptance.py::test_save_guardrail_cannot_be_prompted_away`。
- 13-max-tool-calls: `tests/test_acceptance.py::test_limits`。
- 14-deadline-replan: `tests/test_acceptance.py::test_deadline_replan_and_guardrail`。
- 15-invalid-action: `tests/test_acceptance.py::test_invalid_actions_return_observation_and_recover`。
- 16-real-budget-replan: `tests/test_agent.py::test_replan（离线机制测试）`。
- 17-real-tool-failure: `tests/test_agent.py::test_failure（离线机制测试）`。
- 18-real-observed-replan: `tests/test_agent.py::test_replan（离线机制测试）`。
- 19-real-failure-final: `tests/test_commit.py（保存边界测试）`。

## 两条真实 observation 驱动路径

- 18：读取 Trace 可见 full 脚本报价 12；模型下一轮改选 lite，随后再次 estimate 为 8，才调用 save。每一动作都是实际 API 返回的结构化结果。
- 19：首次 generate 被注入失败，failed 记录保留；模型下一轮重试 full，最终报价 12，在预算 20 内保存。17 是早期另一条实际路径：失败后改 lite，最终报价 8。模型并没有被执行器自动重试。
- 16 虽目录名包含 replan，实际只估算了 8：早期 prompt 下模型直接选择 lite。该样本不能作为“观察超预算后重规划”的证明，故原样保留并补充 18。
- 18/19 的 backend_config 记录具体模型和 base URL；早期 16/17 在增加该状态字段前运行，实际命令也使用 deepseek-v4-pro，原输出未为补元数据而改写。

## 核算、幂等与续跑证据

预算 10 的可行替代方案费用来自 2+4+2，35 分钟；失败和废弃预览不扣费。最低全 lite 为 6，预算 5 的 no_feasible 缺口是 1。重复样例 09/10 指向相同路径，manifest 记录实际保存目录只有一个文件。examples 中每次运行的 saved_plan.json 是保存文件的字节副本，属于证据快照，不是第二次实际保存。

05/06 的 run_id 相同，检索步骤与结果保留，失败步骤仍为 failed；resume 事件列出复用的成功步骤。人工上限触发用来构造可复现的中断点，另有单测覆盖进程留在 running 和保存已提交但状态未写入的恢复窗口。

12 使用专门的对抗 Mock 策略强行请求超预算保存，实际 save 步骤被拒绝为 failed，之后模型策略收到 observation 并调整。它证明硬护栏生效，不宣称是真实模型主动违规。

## 已知失败、限制与复现差异

开发中先遇到 Python 启动别名无效、pytest 默认临时目录权限问题；配置工作区临时目录后通过。原子保存使用硬链接的第一次尝试在 Windows 沙箱中被拒绝，相关回归当时失败；已改用 Windows 不覆盖 rename，再全部重跑。当前记录的是修复后真实测试输出，不声称开发过程中从未失败。

免费估算器不纳入执行组件；业务模拟费用不包含 API token 账单和等待时间。真实样本数量少且非确定性，同样输入可能得到直接 lite、重试 full 或降级等不同路径，不保证再次运行的动作逐字一致。

16–19 保留各自运行时的状态结构和报价结果。最终报价表补齐了 lite 保存的低价档（1），这些真实记录都使用 full 保存（2），已保存方案报价不受影响；离线 01–15 已按最终表重新生成。prompt 修改及旧样本差异已明确说明，不将旧样本描述为最终程序逐位一致的输出。

没有运行远端 GitHub Actions、真实发布或生产压力测试。状态目录可信、同一个 run 只能单进程操作；真实 API 服务异常会 incomplete/model_error，不自动重试。完整边界见 README 与方案文档。

## 证据审计

执行 `python -m scripts.audit_examples`，从原文件重新计算 [evidence-audit.json](../examples/evidence-audit.json)，校验 Trace 与持久化事件一致、失败不记成功、费用求和及完成状态的预算/时间上限，并生成 SHA-256。该摘要用于本地一致性检查，不是外部签名。
