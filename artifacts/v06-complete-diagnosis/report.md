# skillscope-complete-diagnosis：自动诊断报告

状态：执行完成；已记录 21 次运行。单技能干扰、组合候选和未知情况分别报告。

## 对照结果

| 任务 | 配置 | 通过 | 功能失败 | 未获有效评分 |
| --- | --- | ---: | ---: | ---: |
| dotenv-backslash | 无技能基线 | 0 | 3 | 0 |
| dotenv-backslash | 全部加载 | 2 | 1 | 0 |
| dotenv-backslash | 自动生成的阶段方案, 人工阶段规则 | 3 | 0 | 0 |
| dotenv-backslash | 相关性筛选 | 3 | 0 | 0 |
| dotenv-bom | 保留题：无技能 | 3 | 0 | 0 |
| dotenv-bom | 保留题：全部加载 | 3 | 0 | 0 |
| dotenv-bom | 保留题：选定方案 | 3 | 0 | 0 |

同一配置被多个比较角色复用时共享原记录，不计为独立重复。

## 自动诊断

- dotenv-backslash：无技能基线不可靠；可疑技能：未确定。

## 加载方案

```json
{
  "schema_version": 1,
  "status": "selected_on_discovery",
  "source_task": "dotenv-backslash",
  "method": "generated",
  "phases": {
    "investigate": [
      "root-cause",
      "input-validation",
      "compatibility"
    ],
    "implement": [
      "minimal-fix",
      "input-validation",
      "python-idioms"
    ],
    "verify": [
      "edge-cases",
      "compatibility"
    ]
  },
  "basis": "baseline_unreliable",
  "validation_scope": "discovery only; small samples; not an optimal or generally validated policy",
  "holdout_opened": true,
  "holdout_validation_record": "policy-validation.json"
}
```

## 费用与限制

{
  "known_response_estimate_usd": 0.3128244599999999,
  "unknown_reserved_usd": 0.0,
  "conservative_cost_bound_usd": 0.3128244599999999,
  "charged_or_reserved_calls": 197,
  "logged_call_attempts": 197,
  "reported_tokens": 1386494,
  "usage_complete": true
}

费用为固定价格下的估算，不是账户账单；未收到响应时保留整次预算，不把未知费用算成零。
小规模开发题筛选不能证明普遍因果或统计显著性。生成阶段方案使用已有阶段声明和开发集评分，不等于学习到了最优策略。
