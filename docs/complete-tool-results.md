# v0.6：完整工具交付与真实验收

## 可以直接使用的功能

| 功能 | 交付与验证 |
| --- | --- |
| 统一入口 | analyze、diagnose、diagnosis-report、export-diagnosis、run-policy |
| 自动定位 | 重复评分、分块删除、一阶删除检查；区分单技能问题、组合候选、基线不可靠和未知 |
| 阶段方案 | 构造阶段映射，比较全部加载、人工规则、相关性筛选和候选方案，按预定规则选择 |
| 固定后验证 | 保存 policy.json 的 SHA-256 后才开启保留题，评分不反向修改方案 |
| 可读结果 | 自动生成中文 Markdown、离线 HTML、预算、原始轨迹和校验和 |
| 直接使用 | run-policy 从冻结记录加载准确指南，不重新搜索，生成 candidate 源码目录与 changes.patch |
| 运行控制 | 完整试次预算预留、未知费用停止、缓存复用、进程锁与不重复调用的恢复 |
| 可安装性 | 核心运行器已进入 skillscope 包；wheel 在仓库目录外验证通过，不依赖 scripts 导入 |

自动缩减算法的单技能、二技能交互、未知和预算分支有已知答案的确定性测试。它们是工程测试，不伪装成真实模型冲突案例。

## 真实流程的结果

修正版从新样本开始，自动走完配置比较、选择、冻结和保留验证，21 次运行全部有完整用量记录。

| 任务与配置 | 通过 | 功能失败 | 未获有效评分 |
| --- | ---: | ---: | ---: |
| 开发题：无技能 | 0 | 3 | 0 |
| 开发题：全部加载 | 2 | 1 | 0 |
| 开发题：阶段方案／人工阶段规则 | 3 | 0 | 0 |
| 开发题：相关性筛选 | 3 | 0 | 0 |
| 保留题：无技能 | 3 | 0 | 0 |
| 保留题：全部加载 | 3 | 0 | 0 |
| 保留题：选定方案 | 3 | 0 | 0 |

阶段方案和人工阶段规则恰好是同一映射，共享相同的 3 次测量，不计成两组独立样本。在同分方案中，程序按事先规则保留更多指南—阶段位置，选择阶段方案；不是人工在看到保留结果后改选。

本例无技能基线不可靠，因此程序没有强行做技能归因，也没有执行真实集合缩减。它仍比较实际可用配置并产出方案。这次验证证明完整工程链路可运行，不能据此宣称已确认组合冲突、学到了最优策略，或在新任务上取得泛化优势；保留题三种配置都通过 3/3。

## 自动选中的阶段映射

| 阶段 | 指南 |
| --- | --- |
| 调查 | root-cause、input-validation、compatibility |
| 修改 | minimal-fix、input-validation、python-idioms |
| 验证 | edge-cases、compatibility |

阶段规则来自配置中原有声明，经开发评分自动选择，不是训练得到的最优策略。[冻结方案](../artifacts/v06-complete-diagnosis/policy.json)保持原字节；[保留评分](../artifacts/v06-complete-diagnosis/policy-validation.json)存放在独立文件中。

dotenv-bom 从本轮开始已使用，后续不能继续称作未见保留题；使用情况记录在 benchmarks/upstream/holdout-usage.json。

## 不重跑诊断，直接修复新任务

选定方案随后只应用一次到已知开发题 dotenv-comment，没有重新搜索或调参。通过隐藏测试 9/9，8 次请求，自动生成源码目录和补丁；git apply --check 验证补丁格式可用，原任务文件没有被修改。

```powershell
.\.venv\Scripts\python.exe -m skillscope run-policy --study artifacts/v06-complete-diagnosis --task-manifest benchmarks/upstream/dotenv-comment/task.json --output results/my-policy-run
```

查看输出目录的 report.html、candidate 文件夹、changes.patch。这是单次工程应用，不是额外的保留集实验。

## 预算与所有工程版本

初次 6 次验收、修正后的 21 次完整验收与 1 次直接应用全部保留，不合并不同执行协议的成功率。合计 28 次运行、265 次请求、1,733,887 reported tokens；固定价格下的费用估算 USD 0.396879804，低于原 USD 1.50 限额，响应与用量记录完整；它不是账户账单。

- [初次六项与早退问题](../artifacts/v06-initial-acceptance/report.md)：执行前提交 de61b88。
- [完整真实流程](../artifacts/v06-complete-diagnosis/report.md)：执行前提交 7a14be7，原始轨迹与冻结输入一并导出。
- [直接应用结果](../artifacts/v06-policy-application/report.md)：执行前提交 6d1fe38，补丁及候选源码快照保留。
- [完整使用步骤](one-command-guide.md)与[执行前约定](one-command-protocol.md)。

v0.5 及更早的全部成功、失败、中断和未知费用记录保持不变，本轮结果没有填补或替换旧样本。
