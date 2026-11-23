# 第三阶段教学语料

6 份英文技能指南、4 道 discovery 题与 2 道 holdout 题，均为项目内人工编写或从前两阶段的教学题扩展，不代表从真实开源技能库或标准评测集抽样。

| 任务 | 划分 | 覆盖行为 |
| --- | --- | --- |
| clamp | discovery | 数值边界和无效区间 |
| merge-intervals | discovery | 排序、闭区间合并、不可修改输入 |
| get-path | discovery | 转义、完整路径校验、缺失与空值区分 |
| toposort | discovery | 动态字典序、重复依赖、隐含节点、环检测 |
| deduplicate | holdout | 顺序、不可哈希值、相等性 |
| parse-duration | holdout | 单位顺序、语法和无效输入 |

参考实现仅用于检查评分器，不进入模型消息。对 holdout 进行确定性评分器校验，不会调用模型；正式模型批次只取 discovery。公开教学 holdout 不能替代将来新增的真正未参与开发任务。

技能为根因调查、最小修复、边界检查、输入校验、兼容性和 Python 惯用法。它们没有要求忽略任务、泄露信息或故意答错；是否出现退化须由实验判断。

维护脚本为 scripts/build_stage3_corpus.py，需要项目开发依赖；它只生成静态语料并统一格式，不读取模型实验结果。
