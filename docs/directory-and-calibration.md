# 真实目录与第一轮真实任务校准

## 第一步：让项目以目录形式运行

旧原型把 Python 模块装进内存。现在可以在 task.json 设置 `execution_mode: directory`，将清单中的文件写入独立临时目录，再只读挂载到 Docker 的 `/candidate`。Python 正常导入模块，`__file__`、相对路径和资源文件可以使用。

作用：让模型面对更接近实际开发的项目，而不是只能提交一个函数。

目录仍限制为 16 个文件、合计 64 KiB 的 UTF-8 文本；不安装任意依赖，不支持完整通用仓库构建。只允许修改清单中的 Python 文件。评分器在容器外运行，隐藏测试、参考实现、密钥和 Docker socket 不挂载。候选函数通过 JSON 与评分器通信；每次调用启动新容器，写入仅可发生在临时 `/tmp` 中。

资源夹具 `benchmarks/repo-prototype/resources` 是人工编写的工程测试。其初始版本公开检查失败 2 项；参考实现公开 2/2、隐藏 8/8。隐藏检查也验证目录只读、文件清单、命名空间包资源访问及无 API Key/宿主评分文件。它不计入真实任务成功率。

## 第二步：允许提交小补丁

目录模式新增 `replace_in_file(path, old, new)`。旧文本必须恰好出现一次，替换后必须通过 Python 语法检查，且只能在实现阶段修改指定文件。

作用：真实源码较长，修复几行时无需生成整个文件，减少工具协议导致的输出截断。找不到旧文本、有重复匹配、语法错误或越权时返回错误，原文件保持不变。旧导入型原型的公开记录不作修改。

## 第三步：固定真实任务的来源和分组

任务来自 [python-dotenv](https://github.com/theskumar/python-dotenv)，原 BSD-3-Clause 许可证随每份源码保留。完整 `src/dotenv` 映射到工作区的 `dotenv`，保留库模块，不安装 CLI/IPython 的可选依赖。这是来源明确的库任务投影，不等同于完整仓库环境或完整上游测试集。

| 任务 | 分组 | 来源 | 上游修复 |
| --- | --- | --- | --- |
| dotenv-backslash | 开发 | [issue 661](https://github.com/theskumar/python-dotenv/issues/661) | [f7b18d9](https://github.com/theskumar/python-dotenv/commit/f7b18d9c72d1abcc2ad4023424b84f5bee30d266) |
| dotenv-comment | 开发 | [issue 600](https://github.com/theskumar/python-dotenv/issues/600) | [f5485a6](https://github.com/theskumar/python-dotenv/commit/f5485a61eefa5e686d6d5bdc7aa9ad6b104b1e92) |
| dotenv-bom | 保留 | [issue 637](https://github.com/theskumar/python-dotenv/issues/637) | [bca6644](https://github.com/theskumar/python-dotenv/commit/bca6644d9aedbe287b792b756b3ae3d650cd0d3a) |

每题以修复提交的父提交为初始版本，`provenance.json` 记录完整提交、源码 Git blob 和 SHA-256；`reference` 存上游修改文件。任务说明与独立回归测试由 SkillScope 编写，参考实现及隐藏评分不进入模型可读清单。

开发题已验证旧版本失败、上游修复通过：反斜杠题公开 2 项、隐藏 13 项；注释题公开 2 项、隐藏 9 项。保留题只检查来源完整性和清单结构，不进行模型调用或评分。三题来自同一代码库且有共享源码，不能当作独立项目的泛化证据。

## 第四步：预先登记四次无技能试验

作用：观察真实历史缺陷在当前模型和工具预算下是否仍然太容易，或是否被运行预算限制。

- 开发题各重复 2 次，共 4 次；固定 seed=2718 随机排期，串行执行。
- DeepSeek `deepseek-flash`，非思考模式，temperature=0，不加载技能。
- 每次最多 10 次请求，每阶段最多 4 次，每次最多输出 2,048 tokens；消息与工具输入合计不超过 64 KiB。
- 每次模型最多运行 2 次公开测试，另有自动初始检查和最终隐藏评分。调查、验证阶段只读。
- 总请求最多 40 次，按仓库中固定高峰价计算的费用估算上限 USD 1.00；每次开始前保守预留整次预算。不自动重试付费请求；费用未知则停止后续试验。
- 提交方案和代码指纹后才调用模型；冻结输入和镜像。所有失败、截断和接口错误都保留，不补跑替换原结果。

先报告每题两次的原始状态、隐藏评分、调用数、tokens 和费用估算。仅当出现通过与隐藏功能测试失败的空间，才认为值得进一步扩大校准；截断、工具格式失败和环境故障单列，不能直接当作语义难度。若全部通过或全部失败，先扩大任务池并公开筛选过程；本轮不自动启动技能对照或组合诊断。两次重复不能证明稳定成功率。

运行命令（`run` 会产生模型费用；`export` 不调用模型）：

```powershell
.\.venv\Scripts\python.exe -m scripts.repo_calibration plan
# 提交 calibration-plan.json 和执行代码后运行
.\.venv\Scripts\python.exe -m scripts.repo_calibration run
.\.venv\Scripts\python.exe -m scripts.repo_calibration export
```

已有冻结方案和输出目录不会覆盖；再次实验应单独制定并提交新方案。
