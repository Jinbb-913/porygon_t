# porygon_t - AI 自主测试生成器

一个基于 Claude Code 的自动化测试生成 Agent，专为 Python 项目设计。能够智能分析代码变更，自动生成高质量的测试用例，并提供全面的测试报告。

## 核心特性

- **多源测试输入**
  - 基于 Commit Diff：自动分析指定 commit 的代码变更
  - 自定义问题程序：针对已知问题点进行重点测试
  - 自定义测试文件：直接指定需要测试的目标文件

- **智能测试管理**
  - 新增文件自动创建全新测试
  - 已有文件智能更新现有测试
  - 测试文件自动放置于 `./test/` 目录下

- **并行执行**
  - 多文件测试生成并行处理
  - 可配置并发工作线程数
  - 提高大规模项目测试效率

- **全面报告**
  - 生成详细的测试报告（Markdown 格式）
  - 包含覆盖率图表和统计数据
  - 提供质量评估和合并建议

## 项目结构

```
porygon_t/
├── porygon_t.py              # 主入口脚本
├── prompt.md                 # Claude 指令提示词
├── test_plan.json            # 测试计划配置
├── script/                   # 工具模块
│   ├── __init__.py
│   ├── claude_client.py      # Claude Code 客户端
│   ├── file_parser.py        # Python 文件解析
│   ├── git_utils.py          # Git 操作工具
│   ├── report_generator.py   # 报告生成器
│   └── test_runner.py        # 测试执行器
└── reports/                  # 测试报告目录（自动生成）
    └── <timestamp>_<commit>/
        ├── summary_report.md           # 总体测试报告
        └── detail/
            ├── program_<name>/         # 自定义程序测试详情
            │   ├── test_plan_*.md      # 测试方案
            │   ├── *_summary.md        # 执行摘要
            │   ├── *_report.md         # 分析报告
            │   └── fig/                # 覆盖率图表
            └── <file_name>/            # commit diff 文件测试详情
                └── ...
```

## 安装要求

- Python 3.8+
- Claude Code CLI
- Git
- pytest

## 使用方法

### 1. 配置测试计划

编辑 `test_plan.json`：

```json
{
  "project": "MyProject",
  "commit_id": "a1b2c3d",
  "branch": "main",
  "project_path": "/path/to/project",
  "claude_config": {
    "timeoutSeconds": 300
  },
  "test_programs": [
    {
      "file_name": "calculator.py",
      "file_path": "/path/to/project/src/calculator.py",
      "issues": [
        "注意除法时除数为0的边界条件",
        "验证链式调用功能"
      ]
    }
  ],
  "execution": {
    "mode": "parallel",
    "maxWorkers": 4
  }
}
```

### 2. 运行完整流程

```bash
python porygon_t.py
```

### 3. 单独执行特定阶段

```bash
# 发现阶段：获取待测试文件
python porygon_t.py --stage discover

# 计划阶段：生成测试方案
python porygon_t.py --stage plan

# 生成阶段：创建测试代码
python porygon_t.py --stage generate

# 执行阶段：运行测试
python porygon_t.py --stage execute

# 报告阶段：生成分析报告
python porygon_t.py --stage report
```

### 4. 指定配置文件

```bash
python porygon_t.py --plan /path/to/custom_plan.json
```

## 配置说明

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `project` | string | 是 | 项目名称 |
| `commit_id` | string | 是 | 目标 commit ID |
| `project_path` | string | 是 | 被测项目绝对路径 |
| `branch` | string | 否 | Git 分支（默认当前分支） |
| `claude_config.timeoutSeconds` | int | 否 | 超时时间（默认 300） |
| `test_programs` | array | 否 | 自定义测试程序列表 |
| `execution.mode` | string | 否 | 执行模式（默认 parallel） |
| `execution.maxWorkers` | int | 否 | 最大并发数（默认 4） |

## 工作流程

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│   初始化    │ -> │   发现     │ -> │   计划     │ -> │   生成     │ -> │   执行     │
│ 加载配置    │    │ 获取文件   │    │ 生成方案   │    │ 创建测试   │    │ 运行测试   │
└─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘
                                                                                  │
                                                                                  v
┌─────────────┐
│   报告     │ <-
│ 生成分析   │
└─────────────┘
```

### 阶段说明

1. **初始化**：加载 `test_plan.json`，验证配置
2. **发现**：获取 commit diff 文件 + 用户指定文件
3. **计划**：为每个目标生成详细测试方案
4. **生成**：基于方案创建或更新测试代码
5. **执行**：运行测试，收集覆盖率数据
6. **报告**：生成综合分析报告

## 输出报告

### 总体报告 (`summary_report.md`)

- 执行概览：时间、范围、配置
- 总体统计：用例数、通过率、覆盖率
- 文件级汇总：每个文件的测试状态
- 关键问题：失败用例、低覆盖率警告
- 质量评估：通过/未通过结论
- 后续行动：优先级排序的建议

### 详细报告 (`*_report.md`)

- 被测代码分析：函数/类结构、关键逻辑
- 测试用例详情：输入、预期、实际结果
- 覆盖率报告：行覆盖、分支覆盖分析
- 失败用例分析：原因、堆栈、修复建议

## 测试代码规范

生成的测试代码遵循以下规范：

- 使用 pytest 框架
- 覆盖率目标：行覆盖 ≥ 90%，分支覆盖 ≥ 85%
- 每个函数包含正向、边界、异常测试
- 符合 PEP8 代码规范
- 包含清晰的 docstring 说明

## 许可证

MIT License

## 相关链接

- [Claude Code](https://claude.ai/code)
- [pytest](https://docs.pytest.org/)
