# 直接使用 SkillScope

## 1. 先看现有数据，不花 API 费用

在项目根目录运行：

```powershell
.\.venv\Scripts\python.exe -m skillscope analyze --output results/my-analysis
```

作用：读取已有真实实验，列出低表现技能，生成阶段方案草稿和可直接打开的 `results/my-analysis/report.html`。这一步不把历史疑点说成新确认，也不调用模型。

## 2. 一次命令走完整诊断

确认本机 `.env` 和 Docker 已配置，再运行：

```powershell
.\.venv\Scripts\python.exe -m skillscope diagnose --config diagnosis.json --output results/my-diagnosis --allow-holdout
```

作用：自动完成新基线、退化复核、技能集合缩减、方案构造与比较。只有方案先被冻结，才会开启配置中的保留题。该命令会产生 API 费用，额度由 diagnosis.json 中的 limits 限定；已有输出目录不会覆盖。

想先查看输入与预算，可以加 `--plan-only`；之后对同一输出目录加 `--resume --allow-holdout` 开始执行。完成的配置不会再请求。未知用量的中断请求不会自动重发。

## 3. 看四个结果文件

| 文件 | 作用 |
| --- | --- |
| report.html / report.md | 中文结果、对照分数、诊断和预算 |
| state.json | 每次调用归属、缓存测量、缩减证据与阶段比较 |
| policy.json | 选定阶段映射及冻结依据；没有有效方案时不会伪造 |
| policy-validation.json | 冻结方案后的保留题评分，不参与方案选择 |

“单技能退化”表示新重复中一个技能就表现较差；“组合候选”还要求相应单技能对照表现正常。两者不能混为一谈。没有复现、基线不可靠或预算不足也是保留的正式输出。

自动方案使用输入文件中的阶段声明并按开发评分选择，未训练模型或声称最优。当前适配的是清单限制下的小型 Python 库和 JSON 函数接口；不安装任意项目依赖或执行宿主 shell。

## 4. 导出可复查证据

```powershell
.\.venv\Scripts\python.exe -m skillscope diagnosis-report results/my-diagnosis
.\.venv\Scripts\python.exe -m skillscope export-diagnosis results/my-diagnosis --output artifacts/my-diagnosis
```

作用：离线重建报告，导出方案、状态、原始轨迹、冻结输入、候选代码和校验和。导出会检查常见凭证形式，结果不覆盖已有文件。

原始研究脚本保留用于对应历史提交的复现，新使用从上述统一命令开始。历史实验的冻结源码与旧统计不会被新版本覆盖。

## 5. 直接把现成方案用于新任务

```powershell
.\.venv\Scripts\python.exe -m skillscope run-policy --study artifacts/v06-complete-diagnosis --task-manifest benchmarks/upstream/dotenv-comment/task.json --output results/my-policy-run
```

作用：校验保存的方案与指南，从原计划读取准确的指南正文，直接修复并评分指定新任务。不重新诊断、缩减或选择策略，最多使用保存计划规定的一次运行额度。输出 run.json、applied-policy.json 和 report.html。

本轮首次完整验收已使用 dotenv-bom，因此它已不再是未使用保留题。后续要验证真正的新任务效果，应另建未参与开发的新任务集。
