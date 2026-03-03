# porygon_t - 自动测试生成器计划

## 项目概述

创建一个类似 Ralph 的自主 AI Agent，专门用于自动生成 Python 项目的测试代码。

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
├── utils/
│   ├── __init__.py
│   ├── git_helper.py         # Git 操作封装（含 commit diff 分析）
│   ├── coverage.py           # 覆盖率分析
│   └── report.py             # 报告生成
└── reports/                  # 报告目录（自动生成）
    └── 20260303_143052_a1b2c3d/   # 按时间_commitId 命名
        ├── test_plan_program_<name>.md       # test_programs 指定程序的测试方案（自动生成）
        ├── test_plan_case_<file_name>.md     # 修改的文件1的测试方案（自动生成）
        ├── test_plan_case_<file_name>.md     # 修改的文件2的测试方案（自动生成）
        ├── summary_report.md                 # 总体测试报告
        └── detail/
            ├──program_<name>
            |  ├──program_<name>_report.md
            |  ├──program_<name>_config.json # 自动生成
            |  └── fig/      
            ├──<file_name>
            |  ├──<file_name>_report.md
            |  ├──<file_name>_config.json # 自动生成
            |  └── fig/    
            ├──<file_name>
                ├──<file_name>_report.md
             |  ├──program_<name>_config.json # 自动生成
                └── fig/              
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
      "name": "calculator",
      "path": "examples/calculator.py",
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

### 1.2 自动生成program_<name>_config.json 和 <file_name>_config.json
# TODO 完善文件结构和字段说明，其中program_<name>_config.json就是test_plan.json，"test_programs"的信息

### 1.3 test_plan_program_<name>.md和test_plan_case_<file_name>.md应该执行的工作

### 1.4 program_<name>_report.md和 <file_name>_report.md


---

## 2. 输入输出设计

### 2.1 输入（Agent 读取）

### 2.2 输出（Agent 产生）

---

## 3. Agent 提示词设计（prompt.md）


## 4. 经验保存与复用

### 4.1 保存到 reports/<timestamp_commit_id>/test_progress.txt

### 4.2 复用方式

---

## 5. 测试报告设计


---