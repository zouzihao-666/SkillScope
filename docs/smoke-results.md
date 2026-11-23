# 真实管道试运行：2026-11-23

目的：验证模型调用、三阶段切换、候选代码提交与容器外评分是否贯通。

| 配置 | 任务 | 独立测试 | 模型调用 | 输入 tokens | 输出 tokens | 总 tokens |
| --- | --- | --- | --- | --- | --- | --- |
| baseline（无技能） | clamp | 9/9 通过 | 3 | 1,744 | 562 | 2,306 |
| scoped（阶段加载） | clamp | 9/9 通过 | 3 | 2,052 | 792 | 2,844 |
| 合计 | 同一道题运行两次 | 各自通过 | 6 | 3,796 | 1,354 | 5,150 |

数据来自真实 DeepSeek 响应的 usage 字段与独立 pytest 结果。请求和返回模型名均为 `deepseek-flash`，非思考模式，每次最多输出 1,024 tokens，不自动重试。模型返回别名，不能据此证明服务端权重版本固定。费用未换算，保留未知值，以账户账单为准。

候选函数在 Docker Linux 容器中执行，每个测试调用使用新容器；测试源码和判定过程在宿主机。基础镜像摘要、实际评分镜像 ID、输入指纹和依赖版本见原始摘要。

公开记录：

- [baseline 原始运行摘要](evidence/baseline/run.json) · [实际候选代码](evidence/baseline/candidate.py.txt)
- [scoped 原始运行摘要](evidence/scoped/run.json) · [实际候选代码](evidence/scoped/candidate.py.txt)

候选代码以 `.py.txt` 原样保存，便于审阅。完整调用轨迹、输入快照、评分日志和 XML 留在本机 `results/deepseek-baseline-001/` 与 `results/deepseek-scoped-001/`。

这两次运行没有出现技能退化。每个配置只运行了一次，且只覆盖一道开发题，不能证明阶段加载更好，也不能证明技能组合没有冲突。下一阶段需要更多任务、技能、重复实验及顺序/长度对照，先验证稳定案例再开发诊断算法。holdout 任务未请求模型。
