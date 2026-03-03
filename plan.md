# porygon_t - 自动测试生成器计划

## 项目概述

这是一个AI 自主测试的 Agent，专门用于自动生成 Python 项目的测试代码。

**核心思想**：
- 编排层：Python 脚本 (`porygon_t.py`)
- 执行层：Claude Code 命令
- **多源测试输入**：
  - 基于 Commit Diff：读取给定 branch 的 commit ID，分析每个修改的文件
  - 自定义问题程序：指定包含已知 bug 的代码文件，重点测试边界和异常
  - 自定义测试文件：直接指定需要测试的目标文件
- **智能测试管理**：新增文件创建全新测试，已有文件更新现有测试
- **测试文件位置**：与被测文件同级的 `./test/` 文件夹内
- **并行执行**：多个文件的测试生成和验证可并行执行，提高效率

---

## 1. 文件结构设计

### Agent 项目结构
```
porygon_t/
├── porygon_t.py              # 主编排脚本（Python）
├── prompt.md                 # 给 Claude 的指令提示词
├── test_plan.json            # 测试计划定义（含配置和任务）
├── script/
│   ├── __init__.py
│   └── *.py                  # 本agent需要的工具
└── reports/                  # 报告目录（自动生成）
    └── 20260303_143052_a1b2c3d/   # 按时间_commitId 命名
        ├── test_plan_program_<file_name>.md       # test_programs 指定程序的测试方案（自动生成）
        ├── test_plan_case_<file_name>.md     # 修改的文件1的测试方案（自动生成）
        ├── test_plan_case_<file_name>.md     # 修改的文件2的测试方案（自动生成）
        ├── summary_report.md                 # 总体测试报告
        └── detail/
            ├──program_<file_name>
            |  ├──program_<file_name>_summary.md
            |  ├──program_<file_name>_report.md
            |  ├──program_<file_name>_config.json # 自动生成
            |  └── fig/      
            ├──<file_name>
            |  ├──<file_name>_summary.md
            |  ├──<file_name>_report.md
            |  ├──<file_name>_config.json # 自动生成
            |  └── fig/    
            ├──<file_name>
            |  ├──<file_name>_summary.md
            |  ├──<file_name>_report.md
            |  ├──<file_name>_config.json # 自动生成
            |  └── fig/            
```

### 生成的测试文件结构（示例）
```
project-src/
├── src/
│   └── user/
│       ├── auth.py           # 被测文件
│       ├── registration.py   # 被测文件
│       └── test/             # 测试文件夹（自动生成）
│           ├── test_auth.py
│           └── test_registration.py
└── utils/
    ├── helpers.py            # 被测文件
    └── test/                 # 测试文件夹（自动生成）
        └── test_helpers.py
```

### 1.1 test_plan.json 结构（全局配置）
这个配置文件由用户说明

```json
{
  "project": "MyProject",
  "commit_id": "a1b2c3d",
  "branch": "<selected_branch>",
  "project_path": "/path/to/target/project",
  "claude_config": {
    "timeoutSeconds": 300
  },
  "test_programs": [
    {
      "file_name": "<file_name>",
      "file_path": "/path/to/file_folder/<file_name>",
      "issues": ["<告诉大模型应该注意的点>"]
    }
  ],
  "execution": {
    "mode": "parallel",
    "maxWorkers": 4
  }
}
```

**字段说明**：
- `commit_id`: 目标 commit ID（必需）
- `project_path`: 被测项目的绝对路径（必需）
- `branch`: 切换到必要的branch（可选），默认路径下当前branch;
- `claude_config`: Claude Code 相关配置
- `test_programs`: 自定义需要测试的程序列表（可选）
- `execution`: 执行配置

### 1.2 自动生成配置文件结构

#### 1.2.1 `program_<file_name>`

##### 1.2.1.1 `program_<file_name>_config.json`
该文件确定指定的文件和指定文件的测试用例的存储位置

```json
{
  "file_name": "<file_name>",
  "file_path": "/path/to/file_folder/<file_name>",
  "test_file_path": "/path/to/file_folder/test/test_<file_name>.py",
  "issues": ["<告诉大模型应该注意的点>"]
}
```

**字段说明**：
- `file_name`: 程序名称（来自 test_plan.json）
- `file_path`: 文件路径（来自 test_plan.json）
- `test_file_path`: 该文件的测试程序路径
- `issues`: 用户配置的留言（来自 test_plan.json）

---

##### 1.2.1.2 `program_<file_name>_summary.md`
该文件和`./fig`记录用户指定测试程序的运行摘要，由测试执行脚本生成

**生成方式**：
- 执行 `/path/to/file_folder/test/test_<file_name>.py` 测试程序
- 测试程序需支持 `--summary=</path/to/program_<file_name>_summary.md>` 选项输出结构化结果
- 同时生成测试覆盖率图表（保存至 `fig/` 目录）

**内容结构**：
- **程序基本信息**：文件名、路径、测试时间
- **测试用例统计**：总用例数、通过数、失败数、跳过数
- **测试覆盖率**：行覆盖率、分支覆盖率（目标 ≥ 90%）
- **问题点覆盖**：用户指定的 issues 是否被测试覆盖
- **关键发现**：边界条件、异常情况、潜在问题
- **测试结论**：是否通过整体测试评估

---

##### 1.2.1.3 `program_<file_name>_report.md`
该文件基于 `program_<file_name>_summary.md` 由 Claude 生成的综合分析报告, 包含`./fig`中的结果

**内容结构**：
- **被测代码分析**：函数/类结构、输入输出、关键逻辑
- **测试用例详情**：每个用例的输入、预期输出、实际结果、状态
- **覆盖率报告**：行覆盖率、分支覆盖率分析
- **失败用例分析**：失败原因、堆栈信息、修复建议
- **改进建议**：代码可测试性、边界处理、异常处理建议

---

#### 1.2.2 `<file_name>_config`（commit diff 文件）
针对 commit diff 中修改的文件的配置和报告，结构与 1.2.1 类似，但关注变更影响而非完整测试

##### 1.2.2.1 `<file_name>_config.json`
该文件确定被测文件和测试用例的存储位置

```json
{
  "file_name": "<file_name>",
  "file_path": "/path/to/file_folder/<file_name>",
  "test_file_path": "/path/to/file_folder/test/test_<file_name>.py",
  "diff_info": {
    "commit_id": "a1b2c3d",
    "change_type": "<modified/added/deleted>",
    "lines_added": 15,
    "lines_deleted": 8
  }
}
```

**字段说明**：
- `file_name`: 被测文件名（从 git diff 获取）
- `file_path`: 文件绝对路径
- `test_file_path`: 生成的测试文件路径
- `diff_info`: Git 差异信息
  - `commit_id`: 提交哈希
  - `change_type`: 变更类型（modified/added/deleted）
  - `lines_added`: 新增行数
  - `lines_deleted`: 删除行数

---

##### 1.2.2.2 `<file_name>_summary.md`
该文件和`./fig`记录针对修改文件的测试摘要，由测试执行脚本生成

**生成方式**：
- 执行 `/path/to/file_folder/test/test_<file_name>.py` 测试程序
- 测试程序需支持 `--summary=</path/to/<file_name>_summary.md>` 选项输出结构化结果
- 同时生成变更影响的覆盖率图表（保存至 `fig/` 目录）

**内容结构**：
- **变更概览**：修改类型、影响范围、关联函数
- **测试用例统计**：总行数变化对应的测试覆盖、新增/修改用例数
- **测试覆盖率**：变更代码的行覆盖率、分支覆盖率（目标 ≥ 90%）
- **回归测试统计**：原有功能验证通过/失败数
- **关键发现**：变更引入的边界条件、异常风险
- **测试结论**：变更是否通过测试评估，是否可以安全合并

---

##### 1.2.2.3 `<file_name>_report.md`
该文件基于 `<file_name>_summary.md` 由 Claude 生成的综合分析报告，包含`./fig`中的结果

**内容结构**：
- **Diff 分析**：具体修改内容、新增/删除的逻辑、影响面评估
- **关联影响**：受影响的调用链、依赖关系、潜在副作用
- **测试用例设计**：基于变更的用例设计思路、边界测试、回归测试
- **覆盖率报告**：变更代码的行覆盖率、分支覆盖率分析
- **失败用例分析**：失败原因、堆栈信息、修复建议
- **回归测试**：验证原有功能未被破坏，兼容性评估
- **合并建议**：是否建议合并、风险提示、后续注意事项

### 1.3 自动生成测试方案

#### 1.3.1 `test_plan_program_<file_name>.md`

该文件由 Claude 基于 `program_<file_name>_config.json` 自动生成，包含针对用户指定程序的详细测试方案设计。

**生成流程**：
1. 读取 `program_<file_name>_config.json` 获取 `file_path` 和 `issues`
2. 解析目标文件，提取以下信息：
   - 函数/类定义（名称、参数、返回值）
   - 关键逻辑分支和条件判断
   - 外部依赖（导入的其他模块）
   - 边界条件和异常处理点
3. 分析 `issues` 中用户指定的关注点
4. 调用 Claude 生成完整测试方案

**内容结构**：
- **被测程序分析**：
  - 文件路径、类/函数列表、功能描述
  - 输入输出定义、依赖关系
  - 关键逻辑路径识别
- **测试目标定义**：
  - 功能覆盖目标（核心功能、边界场景）
  - 覆盖率目标（行覆盖 ≥ 90%，分支覆盖 ≥ 85%）
  - 用户指定的 issues 覆盖要求
- **测试用例设计**：
  - 正向测试用例（正常输入预期输出）
  - 边界测试用例（极值、空值、类型边界）
  - 异常测试用例（错误输入、异常情况）
  - 回归测试用例（验证原有功能）

#### 1.3.2 `test_plan_case_<file_name>.md`

该文件由 Claude 基于 `<file_name>_config.json` 自动生成，包含针对 commit diff 修改文件的测试方案设计。

**生成流程**：
1. 读取 `<file_name>_config.json` 获取 `file_path` 和 `diff_info`
2. 解析目标文件当前状态，提取以下信息：
   - 函数/类定义（名称、参数、返回值）
   - 关键逻辑分支和条件判断
   - 外部依赖（导入的其他模块）
   - 边界条件和异常处理点
3. 执行 `git diff <commit_id>` 获取具体变更内容
4. 分析变更影响：新增/删除/修改的代码行、关联函数、潜在副作用
5. 调用 Claude 生成针对变更的测试方案

**内容结构**：
- **变更分析**：
  - 文件路径、变更类型（新增/修改/删除）
  - 具体变更内容：新增/删除的函数、修改的逻辑行
  - 影响范围：受影响的调用链、依赖关系
  - 潜在风险：变更引入的边界条件、异常风险
- **测试目标定义**：
  - 变更覆盖目标（新增代码、修改逻辑）
  - 覆盖率目标（变更代码行覆盖 ≥ 95%，分支覆盖 ≥ 90%）
  - 回归目标（验证原有功能未被破坏）
- **测试用例设计**：
  - 新增功能测试（针对新增代码的正向测试）
  - 变更影响测试（针对修改逻辑的边界测试）
  - 异常测试（变更后的错误处理、异常情况）
  - 回归测试（验证未变更的功能完整性）
---

## 2. 程序流程总体设计

本节描述 Agent 的整体工作流程和核心算法框架。Agent 采用**多阶段流水线**设计，从输入解析到测试生成执行，各阶段松耦合、可独立运行。

**流程概览**：
1. **初始化阶段**：读取 `test_plan.json`，解析用户配置
2. **发现阶段**：基于 commit_id 获取变更文件，合并 `test_programs` 自定义文件
3. **计划阶段**：为每个目标文件生成测试方案（test_plan_*.md）
4. **生成阶段**：基于测试方案生成/更新测试代码
5. **执行阶段**：运行测试，收集结果和覆盖率数据
6. **报告阶段**：生成摘要和详细分析报告

各阶段通过文件系统传递状态，支持断点续跑和增量更新。

---

### 2.1 Agent 总体算法框架

Agent 的核心是一个**事件驱动的状态机**，主循环协调多个工作线程并行处理测试任务。

**算法伪代码**：

```python
def main():
    # 1. 初始化
    config = load_test_plan("test_plan.json")
    workers = config.execution.maxWorkers

    # 2. 发现待测试文件
    targets = []
    targets += get_commit_diff_files(config.commit_id)      # commit diff 文件
    targets += config.test_programs                          # 用户指定文件

    ## 2.1 生成program_<file_name>_config.json和<file_name>_config.json

    # 3. 生成测试方案（可并行）
    plans = []
    for target in targets:
        plan = generate_test_plan(target)    # 调用 Claude 生成 test_plan_*.md
        plans.append(plan)

    # 4. 生成/更新测试代码（可并行）
    for plan in plans:
        if test_file_exists(plan.test_file_path):
            update_tests(plan)               # 增量更新现有测试
        else:
            generate_tests(plan)             # 创建新测试文件

    # 5. 执行测试（可并行），执行之后会生成测试_summary.md
    results = []
    for plan in plans:
        result = run_tests(plan.test_file_path)
        result.create_summary()
        result.create_report() # 调用Claude模型生成 program_<file_name>_report.md或者<file_name>_report.md
        results.append(result)

    # 6. 生成报告（调用 Claude）
    generate_summary_report(results)
```

**关键设计决策**：

| 设计点 | 决策 | 理由 |
|--------|------|------|
| 并行粒度 | 文件级并行 | 不同文件的测试相互独立，易于并行化 |
| 状态持久化 | 文件系统 | 每个阶段输出独立文件，支持断点续跑 |
| 增量更新 | 测试文件存在性检查 | 避免重复生成，支持持续迭代 |
| Claude 调用 | 阶段级批量调用 | 减少上下文切换，提高生成质量 |


### 2.2 输入（Agent 读取）
输入文件为`test_plan.json`

### 2.3 输出`summary_report.md`



## 3. 保存与经验复用

### 3.1 保存到 reports/<timestamp_commit_id>/test_progress.txt

### 3.2 复用方式 
# 读取或者写入./lesson/文件夹

---

## 4. 测试报告设计


---