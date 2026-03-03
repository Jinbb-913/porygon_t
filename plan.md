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
    ├── 20260303_143052_a1b2c3d/   # 按时间_commitId 命名
    │   ├── test_case_registration.json  # 每个文件的测试任务（自动生成）
    │   ├── test_case_auth.json
    │   ├── test_report.md
    │   └── test_progress.txt
    └── 20260304_090123_e4f5g6h/
        ├── test_case_*.json
        ├── test_report.md
        └── test_progress.txt
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
  "project_path": "/path/to/target/project",
  "claude_config": {
    "timeoutSeconds": 300
  },
  "testPrograms": [
    {
      "name": "calculator",
      "path": "examples/calculator.py",
      "issues": ["divide 未处理除零错误", "calculate_average 未处理空列表"]
    }
  ],
  "execution": {
    "mode": "parallel",
    "maxWorkers": 4,
    "batchBy": "file"
  }
}
```

**字段说明**：
- `commit_id`: 目标 commit ID（必需）
- `project_path`: 被测项目的绝对路径（必需）
- `claude_config`: Claude Code 相关配置
- `testPrograms`: 自定义问题程序列表（可选）
- `execution`: 执行配置

### 1.2 test_case.json 结构（每个文件独立）

程序根据 commit_id 自动分析修改的文件，为每个文件生成独立的 test_case.json：

```
reports/
└── 20260303_143052_a1b2c3d/
    ├── test_case_registration.json    # 对应 registration.py
    ├── test_case_auth.json            # 对应 auth.py
    ├── test_progress.txt
    └── test_report.md
```

```json
{
  "id": "TC-001",
  "targetModule": "src/user/registration.py",
  "title": "Test user registration edge cases",
  "acceptanceCriteria": [
    "Add test for duplicate email validation",
    "Coverage for registration.py >= 90%"
  ],
  "priority": 1,
  "passes": false,
  "notes": ""
}
```

**生成流程**：
1. 读取 `test_plan.json` 获取 `commit_id`
2. 执行 `git diff` 获取修改的文件列表
3. 为每个修改的文件生成 `test_case_<module>.json`
4. 根据 `testPrograms` 补充问题描述到对应的 test_case
5. 并行执行每个 test_case 的测试生成

---

## 2. 输入输出设计

### 2.1 输入（Agent 读取）

| 输入源 | 用途 |
|--------|------|
| `test_plan.json` | 全局配置（commit_id、project_path、execution 等） |
| `test_plan.json` -> `project_path` | 被测项目的根目录路径 |
| `test_plan.json` -> `testPrograms` | 自定义问题程序列表（补充到对应 test_case） |
| `test_plan.json` -> `commit_id` | 目标 commit，用于获取修改的文件列表 |
| `reports/*/test_case_*.json` | 每个文件独立的测试任务定义 |
| `reports/*/test_progress.txt` | 历史测试经验和代码模式（读取最新） |
| `pytest --cov` 输出 | 当前覆盖率基线 |
| 目标模块源代码 | 分析需要测试的函数/类/边界条件 |
| **Git Diff** | 基于 commit_id 分析修改文件的变更内容 |

**生成流程**：
1. 读取 `test_plan.json` 获取全局配置
2. 基于 `commit_id` 获取修改的文件列表
3. 为每个文件生成 `reports/<timestamp_commit_id>/test_case_<module>.json`
4. 并行执行每个 test_case 的测试生成

### 2.2 输出（Agent 产生）

| 输出 | 说明 |
|------|------|
| `./test/test_*.py` | 新生成的测试代码文件（位于被测文件同级 `./test` 文件夹内） |
| `reports/<timestamp_commit_id>/test_case_*.json` | 每个文件独立的测试任务（自动生成） |
| `reports/<timestamp_commit_id>/test_progress.txt` | 本次测试的经验教训 |
| `reports/<timestamp_commit_id>/test_report.md` | 最终测试报告 |
| Git commit | 每次完成的测试用例 |

---

## 3. Agent 提示词设计（prompt.md）

### 3.1 指令框架

```markdown
# Python 测试 Agent 指令

你是一个专门编写 Python 测试的 AI Agent。

## 你的任务

1. **读取 Commit 变更**：
   - 基于 `commit_id` 执行 `git diff <commit_id>^..<commit_id>` 获取该 commit 修改的文件列表
   - 遍历每个修改的文件

2. **分析变更内容**：
   - 对于每个修改的文件，分析具体的代码变更（新增/修改的函数/类）
   - 识别需要测试的：
     - 公开函数/方法
     - 边界条件（空值、极值、类型错误）
     - 异常处理路径

3. **生成或更新测试**：
   - **新增文件**：创建全新的测试用例文件
   - **已有文件**：检查 `./test/` 目录下是否已有对应测试，如有则更新，否则创建新测试
   - 测试文件放在被测文件同级的 `./test/` 文件夹内

4. **运行测试确保通过**

## 测试编写规范

### 文件命名与位置
- 被测模块: `src/user/auth.py`
- 测试文件: `src/user/test/test_auth.py`（必须放在被测文件同级的 `./test/` 文件夹内）

### 测试文件创建规则
1. **新增源文件**：在被测文件同级创建 `./test/` 目录，生成 `test_<module>.py`
2. **已有源文件**：
   - 检查 `./test/test_<module>.py` 是否存在
   - 若存在：更新现有测试，添加新用例覆盖变更代码
   - 若不存在：创建 `./test/test_<module>.py`

### 测试结构（given-when-then）
```python
class TestAuthenticateUser:
    """Test suite for authenticate_user function."""

    def test_success_with_valid_credentials(self):
        """Given valid email and password, return user object."""
        # Arrange
        email = "user@example.com"
        password = "correct_password"

        # Act
        result = authenticate_user(email, password)

        # Assert
        assert result is not None
        assert result.email == email
```

### 必须遵循的原则

1. **pytest 最佳实践**：
   - 用 `pytest.fixture` 共享测试数据
   - 用 `@pytest.mark.parametrize` 覆盖多种输入
   - 用 `unittest.mock` 隔离外部依赖

2. **覆盖率优先**：
   - 测试正常路径和异常路径
   - 测试边界条件
   - 每个 public 函数都要有测试

3. **可读性**：
   - 测试函数名：`test_<action>_<condition>_<expected>`

## 质量检查（必须执行）

```bash
# 1. 运行新测试
pytest test_<module>.py -v

# 2. 检查覆盖率
pytest --cov=<target_module> --cov-report=term-missing test_<module>.py

# 3. 运行完整测试套件（无回归）
pytest

# 4. 代码格式化
black test_<module>.py
```

## 输出要求

1. 编写测试代码
2. 运行质量检查
3. 如果全部通过，输出：
```
   <TEST_COMPLETE>
   Story [ID] completed.
   Coverage: X%
   Tests added: N
   ```
```

---

## 4. 经验保存与复用

### 4.1 保存到 reports/<timestamp_commit_id>/test_progress.txt

每次运行生成独立的报告目录：
```
reports/
└── 20260303_143052_a1b2c3d/
    ├── test_progress.txt     # 本次经验记录
    └── test_report.md        # 本次测试报告
```

`test_progress.txt` 格式：
```markdown
## Codebase Patterns
- 使用 factory_boy 创建测试数据
- 数据库测试使用 @pytest.mark.django_db
- Mock 外部 HTTP 调用
- 时间相关测试使用 freezegun

## 2026-03-03 - TC-001
- Target: src/user/registration.py
- New tests: 5
- Coverage: 45% -> 78%
- **Learnings:**
 - 边界条件: 邮箱格式有3种错误消息
 - 难点: 异步邮件任务需要特殊 mock
 - 模式: 使用 fixture 共享用户创建逻辑
---
```

### 4.2 复用方式

Agent 在每次迭代前读取**最新的** `reports/*/test_progress.txt` 中的 **Codebase Patterns** 部分，遵循其中的约定。

查找最新经验文件的逻辑：
```python
def get_latest_progress_file(reports_dir="reports"):
    """获取最新的 test_progress.txt 路径"""
    report_dirs = sorted(os.listdir(reports_dir), reverse=True)
    for dir_name in report_dirs:
        progress_file = os.path.join(reports_dir, dir_name, "test_progress.txt")
        if os.path.exists(progress_file):
            return progress_file
    return None
```

---

## 5. 测试报告设计

循环结束时在 `reports/<timestamp_commit_id>/` 目录下生成 `test_report.md`：

```markdown
# 测试完成报告

## 执行摘要

| 指标 | 数值 |
|------|------|
| 测试任务完成 | 5/5 |
| 新增测试用例 | 23 |
| 整体覆盖率 | 45% → 82% |

## 详细结果

### TC-001: 测试用户注册边界情况
- 目标: `src/user/registration.py`
- 新增: `test_registration.py` (5个测试)
- 覆盖率: 45% → 78%

## 遗留问题
- OAuth 流程需要手动测试
- 异步邮件测试覆盖率 < 60%

## 建议
1. 提取 factory_boy 到共享模块
2. 添加 OAuth 集成测试
3. CI 阈值：覆盖率不低于 80%
```

---

## 6. 编排层核心逻辑（agent.py）

### 6.1 主循环流程（支持并行执行）

```python
import concurrent.futures
from dataclasses import dataclass
from typing import List, Dict, Optional

@dataclass
class TestTask:
    source_file: str
    test_file_path: str
    is_new_test: bool
    diff: Optional[str] = None
    priority: int = 1

class TestAgent:
    def run(self):
        plan = self.load_plan()

        # 1. 收集所有需要测试的文件
        all_files = self._collect_all_test_files(plan)

        # 2. 为每个文件生成 test_case.json
        report_dir = self._create_report_dir(plan.commit_id)
        test_cases = self._generate_test_cases(all_files, plan, report_dir)

        # 3. 并行执行测试生成
        if plan.execution.get('mode') == 'parallel':
            self._run_parallel(test_cases, plan, report_dir)
        else:
            self._run_sequential(test_cases, plan, report_dir)

        self.generate_report(plan, report_dir)

    def _collect_all_test_files(self, plan) -> List[str]:
        """收集所有需要测试的文件（多来源合并）"""
        files = set()

        # 来源 1: 基于 commit_id 自动获取修改的文件
        if plan.commit_id:
            modified = self._get_modified_files(plan.commit_id)
            files.update(modified)

        # 来源 2: 自定义问题程序 (testPrograms)
        for program in plan.test_programs:
            files.add(program['path'])

        return sorted(list(files))

    def _generate_test_cases(self, files: List[str], plan, report_dir: str) -> List[TestTask]:
        """为每个文件生成 test_case.json 并返回测试任务列表"""
        test_cases = []
        for idx, source_file in enumerate(files):
            test_file_path = self._get_test_file_path(source_file)
            is_new_test = not os.path.exists(test_file_path)

            # 获取 diff（基于 commit_id）
            diff = None
            if plan.commit_id:
                diff = self._get_file_diff(plan.commit_id, source_file)

            # 生成 test_case.json
            test_case = {
                'id': f'TC-{idx+1:03d}',
                'targetModule': source_file,
                'title': f'Test {os.path.basename(source_file)}',
                'acceptanceCriteria': [
                    f'Coverage for {source_file} >= 80%',
                    'All tests pass: pytest test_*.py -v'
                ],
                'priority': 1,
                'passes': False,
                'notes': ''
            }

            # 如果文件在 testPrograms 中，补充问题描述
            for program in plan.test_programs:
                if program['path'] == source_file:
                    test_case['issues'] = program.get('issues', [])
                    test_case['notes'] = 'Focus on boundary and error handling tests'

            # 保存 test_case.json
            case_filename = f'test_case_{os.path.basename(source_file).replace(".py", "")}.json'
            case_path = os.path.join(report_dir, case_filename)
            with open(case_path, 'w') as f:
                json.dump(test_case, f, indent=2)

            test_cases.append(TestTask(
                source_file=source_file,
                test_file_path=test_file_path,
                is_new_test=is_new_test,
                diff=diff
            ))
        return test_cases

    def _create_report_dir(self, commit_id: str) -> str:
        """创建报告目录（时间_commitId 格式）"""
        from datetime import datetime
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        dir_name = f"{timestamp}_{commit_id[:7]}"
        report_dir = os.path.join('reports', dir_name)
        os.makedirs(report_dir, exist_ok=True)
        return report_dir

    def _run_parallel(self, test_cases: List[TestTask], plan, report_dir: str):
        """并行执行测试生成（按文件隔离）"""
        max_workers = plan.execution.get('maxWorkers', 4)

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            # 提交所有任务
            future_to_task = {
                executor.submit(self._process_single_file, case, plan, report_dir): case
                for case in test_cases
            }

            # 收集结果
            results = []
            for future in concurrent.futures.as_completed(future_to_task):
                case = future_to_task[future]
                try:
                    result = future.result()
                    results.append(result)
                except Exception as e:
                    self.logger.error(f"Task failed for {case.source_file}: {e}")

        # 统一更新 test_case.json
        self._update_test_cases(results, report_dir)

    def _process_single_file(self, task: TestTask, plan, report_dir: str) -> Dict:
        """处理单个文件的测试生成（可在独立线程/进程中运行）"""
        # 1. 构建上下文
        context = self._build_context(
            task.source_file,
            task.diff,
            task.test_file_path,
            task.is_new_test
        )

        # 2. 调用 Claude 生成测试
        output = self.run_claude_iteration(task.source_file, context)

        # 3. 质量检查
        passed, checks = self.check_quality(task.test_file_path)

        # 4. 更新 test_case.json
        self._update_single_test_case(task.source_file, passed, report_dir)

        return {
            'source_file': task.source_file,
            'test_file': task.test_file_path,
            'passed': passed,
            'checks': checks,
            'output': output
        }

    def _update_single_test_case(self, source_file: str, passed: bool, report_dir: str):
        """更新单个 test_case.json 的 passes 状态"""
        case_filename = f'test_case_{os.path.basename(source_file).replace(".py", "")}.json'
        case_path = os.path.join(report_dir, case_filename)
        if os.path.exists(case_path):
            with open(case_path, 'r') as f:
                test_case = json.load(f)
            test_case['passes'] = passed
            with open(case_path, 'w') as f:
                json.dump(test_case, f, indent=2)

    def _get_modified_files(self, commit_id):
        """基于 commit_id 获取修改的所有文件"""
        # 使用 commit_id 与父 commit 对比，获取该 commit 修改的文件
        result = subprocess.run(
            ["git", "diff", "--name-only", f"{commit_id}^..{commit_id}"],
            capture_output=True, text=True
        )
        return [f for f in result.stdout.strip().split("\n") if f.endswith(".py")]

    def _get_test_file_path(self, source_file):
        """确定测试文件路径：与源文件同级 ./test/ 目录下"""
        source_dir = os.path.dirname(source_file)
        source_name = os.path.basename(source_file).replace(".py", "")
        test_dir = os.path.join(source_dir, "test")
        return os.path.join(test_dir, f"test_{source_name}.py")
```

### 6.2 质量检查内容

1. **运行测试**：`pytest <source_dir>/test/test_<module>.py -v`
2. **检查覆盖率**：`pytest --cov=<source_module> <source_dir>/test/`
3. **无回归**：`pytest`（完整套件）
4. **代码风格**：`black`, `mypy`（可选）

---

## 6.3 自定义测试用例

### testPrograms 格式

用于指定已知有问题的程序，Agent 会针对这些问题生成边界测试：

```json
{
  "testPrograms": [
    {
      "name": "calculator",
      "path": "examples/calculator.py",
      "issues": [
        "divide 函数未处理除零错误",
        "calculate_average 未处理空列表",
        "power 函数大数可能导致内存问题"
      ],
      "focusAreas": ["异常处理", "边界条件"]
    }
  ]
}
```

### 优先级规则

当多个来源指定同一文件时，按以下优先级合并：
1. `testPrograms` - 最高优先级（需要重点测试边界和异常）
2. Git diff（基于 commit_id 自动获取）- 基础优先级（常规测试覆盖）

---

## 6.4 并行执行方案

### 并行策略

```
┌─────────────────────────────────────────────────────────────┐
│                      TestAgent.run()                        │
├─────────────────────────────────────────────────────────────┤
│  1. 收集所有测试文件（去重合并）                               │
├─────────────────────────────────────────────────────────────┤
│  2. 按文件创建独立任务                                        │
│     ├─ Task 1: calculator.py → test_calculator.py          │
│     ├─ Task 2: data_processor.py → test_data_processor.py  │
│     ├─ Task 3: string_utils.py → test_string_utils.py      │
│     └─ Task 4: file_handler.py → test_file_handler.py      │
├─────────────────────────────────────────────────────────────┤
│  3. 线程池并行执行 (max_workers=4)                           │
│     ├─ Worker 1: Process Task 1                             │
│     ├─ Worker 2: Process Task 2                             │
│     ├─ Worker 3: Process Task 3                             │
│     └─ Worker 4: Process Task 4                             │
├─────────────────────────────────────────────────────────────┤
│  4. 等待所有任务完成，收集结果                                │
├─────────────────────────────────────────────────────────────┤
│  5. 统一更新 test_plan.json                                   │
└─────────────────────────────────────────────────────────────┘
```

### 并行边界

- **文件级隔离**：每个文件独立处理，无共享状态
- **同一文件串行**：单个文件内的多个测试用例按优先级顺序执行
- **结果合并**：所有任务完成后统一更新进度

### 线程安全考虑

```python
# 每个工作线程独立：
# - 独立的 Claude Code 会话
# - 独立的文件 I/O
# - 独立的 pytest 进程

# 共享资源（需加锁）：
# - test_plan.json 更新
# - reports/<timestamp_commit_id>/ 目录创建
# - Git 提交操作
```

---

## 7. 使用方式

### 7.1 初始化测试计划

```bash
# 创建 test_plan.json
python porygon_t.py --init

# 或使用示例
cp test_plan.example.json test_plan.json
```

### 7.2 运行 Agent

```bash
# 默认：读取 test_plan.json 中的配置
python porygon_t.py

# 指定 commit_id（覆盖 test_plan.json 中的值）
python porygon_t.py --commit a1b2c3d

# 指定被测项目路径
python porygon_t.py --project-path /path/to/project
```

### 7.3 查看状态

```bash
# 查看最新报告目录下的所有 test_case
ls -t reports/ | head -1 | xargs -I {} ls reports/{}/test_case_*.json

# 查看特定 test_case
cat reports/20260303_143052_a1b2c3d/test_case_registration.json | jq '{id, targetModule, passes}'

# 查看最新的经验积累
ls -t reports/ | head -1 | xargs -I {} cat reports/{}/test_progress.txt

# 查看最新的最终报告
ls -t reports/ | head -1 | xargs -I {} cat reports/{}/test_report.md

# 查看指定报告的目录内容
ls reports/20260303_143052_a1b2c3d/
```

---

## 8. 后续扩展建议

1. **并行测试**：同时处理多个无依赖的测试用例
2. **智能分析**：自动识别需要测试的模块（无需手动填写 test_plan.json）
3. **CI 集成**：作为 GitHub Action 自动运行
4. **失败重试**：失败的测试用例自动重试并记录原因
5. **测试数据生成**：集成 AI 生成边界测试数据

---

## 9. 与 Ralph 的对比

| 方面 | Ralph | porygon_t |
|------|-------|--------------|
| 用途 | 功能开发 | 测试生成 |
| 编排层 | bash (ralph.sh) | Python (porygon_t.py) |
| 任务定义 | prd.json | test_plan.json |
| 任务单元 | User Story (US-001) | Test Case (TC-001) |
| 输出 | 功能代码 | 测试代码 |
| 完成信号 | `<promise>COMPLETE</promise>` | `<TEST_COMPLETE>` |

---

## 下一步行动

1. [ ] 创建 `porygon_t.py` 主文件
2. [ ] 创建 `prompt.md` 提示词
3. [ ] 创建 `test_plan.example.json` 示例
4. [ ] 在一个真实 Python 项目上测试
5. [ ] 根据测试结果迭代优化
