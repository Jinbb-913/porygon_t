#!/usr/bin/env python3
"""
porygon_t - AI 自主测试生成器

一个基于 Claude Code 的自动化测试生成 Agent，支持：
- 基于 Commit Diff 生成测试
- 自定义问题程序测试
- 智能测试管理和更新

执行流程：
1. 初始化 - 读取 test_plan.json
2. 发现 - 获取 commit diff 文件 + 用户指定文件
3. 计划 - 为每个目标生成测试方案
4. 生成 - 基于方案创建/更新测试代码
5. 执行 - 运行测试，收集结果
6. 报告 - 生成综合分析报告
"""

import json
import logging
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

# 导入常量
from constants import (
    ConfigKey,
    CoverageTarget,
    Defaults,
    FileExtension,
    Language,
)

# 导入工具模块
from script import (
    ClaudeClient,
    ClaudeError,
    ReportData,
    ReportGenerator,
    TestRunner,
    checkout_branch,
    get_commit_diff_files,
    get_diff_stat,
    is_valid_git_repo,
)


# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('porygon_t')


# 为向后兼容保留别名
SUPPORTED_EXTENSIONS = FileExtension.SUPPORTED
PYTHON_EXTENSIONS = FileExtension.PYTHON
CPP_SOURCE_EXTENSIONS = FileExtension.CPP_SOURCE
CPP_HEADER_EXTENSIONS = FileExtension.CPP_HEADER
CPP_EXTENSIONS = FileExtension.CPP

# 为向后兼容保留函数
def get_file_extension(file_name: str) -> str:
    """获取文件扩展名"""
    return FileExtension.get_file_extension(file_name)


def is_python_file(file_name: str) -> bool:
    """判断是否为 Python 文件"""
    return FileExtension.is_python(file_name)


def is_cpp_file(file_name: str) -> bool:
    """判断是否为 C++ 源文件（头文件不单独测试）"""
    return FileExtension.is_cpp_source(file_name)


def get_source_language(file_name: str) -> str:
    """获取源文件语言类型"""
    return FileExtension.get_language(file_name)


class TestTarget:
    """测试目标封装类"""

    def __init__(
        self,
        file_name: str,
        file_path: str,
        target_type: str,
        issues: Optional[List[str]] = None,
        diff_info: Optional[Dict] = None
    ):
        # 移除扩展名，支持多种语言
        self.file_ext = get_file_extension(file_name)
        if self.file_ext in SUPPORTED_EXTENSIONS:
            self.file_name = file_name[:-len(self.file_ext)]
        else:
            self.file_name = file_name
        self.file_path = file_path
        self.target_type = target_type
        self.issues = issues or []
        self.diff_info = diff_info or {}
        self.language = get_source_language(file_name)

        file_dir = Path(file_path).parent
        self.test_dir = file_dir / 'test'

        # 根据语言确定测试文件扩展名
        if self.language == 'cpp':
            self.test_file_path = self.test_dir / f'test_{self.file_name}.cpp'
        else:
            self.test_file_path = self.test_dir / f'test_{self.file_name}.py'

        self.config_dir: Optional[Path] = None
        self.config_path: Optional[Path] = None
        self.plan_path: Optional[Path] = None
        self.summary_path: Optional[Path] = None
        self.report_path: Optional[Path] = None

    def set_report_paths(self, report_dir: Path):
        """设置报告相关路径"""
        prefix = f'program_{self.file_name}' if self.target_type == 'program' else self.file_name
        self.config_dir = report_dir / 'detail' / prefix

        self.config_path = self.config_dir / f'{prefix}_config.json'
        self.plan_path = self.config_dir / f'test_plan_{"program" if self.target_type == "program" else "case"}_{self.file_name}.md'
        self.summary_path = self.config_dir / f'{prefix}_summary.md'
        self.report_path = self.config_dir / f'{prefix}_report.md'

    def to_config(self) -> Dict:
        """转换为配置文件格式"""
        config = {
            'file_name': self.file_name,
            'file_path': self.file_path,
            'test_file_path': str(self.test_file_path),
            'language': self.language,
            self.target_type: self.issues if self.target_type == 'program' else self.diff_info
        }
        return config


class PorygonT:
    """porygon_t 核心类"""

    def __init__(self, plan_path: str):
        """
        初始化 Agent

        Args:
            plan_path: test_plan.json 文件路径
        """
        self.plan_path = Path(plan_path)
        self.config = self._load_config()
        self.report_dir: Optional[Path] = None
        self.targets: List[TestTarget] = []

        # 初始化 Claude 客户端
        project_path = Path(self.config.get('project_path', '.'))
        timeout = self.config.get(ConfigKey.CLAUDE_CONFIG, {}).get(ConfigKey.TIMEOUT_SECONDS, Defaults.TIMEOUT_SECONDS)
        self.claude = ClaudeClient(project_path, Path('prompt.md'), timeout)

        self.start_time: Optional[datetime] = None

    def _load_config(self) -> Dict:
        """加载测试计划配置文件"""
        logger.info(f"加载配置文件: {self.plan_path}")
        with open(self.plan_path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def _validate_config(self) -> bool:
        """验证配置完整性"""
        required_fields = ['project', 'commit_id', 'project_path']
        for field in required_fields:
            if field not in self.config:
                logger.error(f"配置缺少必填项: {field}")
                return False

        # 验证项目路径存在
        project_path = Path(self.config['project_path'])
        if not project_path.exists():
            logger.error(f"项目路径不存在: {project_path}")
            return False

        # 验证是有效的 Git 仓库（如果需要）
        if self.config.get('commit_id') and not is_valid_git_repo(project_path):
            logger.error(f"项目路径不是有效的 Git 仓库: {project_path}")
            return False

        return True

    def _create_report_directory(self) -> Path:
        """创建报告目录结构"""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        commit_id = self.config['commit_id'][:7]
        report_name = f"{timestamp}_{commit_id}"

        report_dir = Path('reports') / report_name
        detail_dir = report_dir / 'detail'

        # 创建目录
        report_dir.mkdir(parents=True, exist_ok=True)
        detail_dir.mkdir(exist_ok=True)

        logger.info(f"创建报告目录: {report_dir}")
        return report_dir

    def _get_commit_diff_targets(self) -> List[TestTarget]:
        """
        获取 commit diff 中的变更文件作为测试目标

        Returns:
            变更文件目标列表（仅 Python 文件）
        """
        targets = []
        commit_id = self.config.get('commit_id')
        project_path = Path(self.config['project_path'])
        branch = self.config.get('branch')

        if not commit_id:
            logger.warning("未配置 commit_id，跳过 diff 文件获取")
            return targets

        try:
            # 如果指定了 branch，先切换
            if branch:
                checkout_branch(branch, project_path)

            # 获取变更文件列表
            diff_files = get_commit_diff_files(commit_id, project_path)

            # 用于去重：同名 .h/.hpp 和 .cpp 只保留 .cpp
            processed_names = set()

            for file_info in diff_files:
                file_name = file_info['file_name']
                full_path = Path(file_info['full_path'])

                # 只处理支持的文件类型，跳过删除的文件
                if not any(file_name.endswith(ext) for ext in SUPPORTED_EXTENSIONS):
                    continue
                # Python 特有：跳过 __init__.py
                if is_python_file(file_name) and file_name.endswith('__init__.py'):
                    continue
                if file_info['change_type'] == 'deleted':
                    continue

                # 获取基础名（不含扩展名）
                file_ext = get_file_extension(file_name)
                base_name = file_name[:-len(file_ext)] if file_ext in SUPPORTED_EXTENSIONS else file_name

                # 如果是头文件，检查是否存在同名的源文件
                if file_ext in CPP_HEADER_EXTENSIONS:
                    cpp_file = full_path.parent / f"{base_name}.cpp"
                    if cpp_file.exists():
                        logger.info(f"头文件 {file_name} 存在对应源文件，跳过独立测试")
                        continue
                    # 否则使用头文件作为目标（但需要找对应的源文件）
                    for ext in CPP_SOURCE_EXTENSIONS:
                        src_file = full_path.parent / f"{base_name}{ext}"
                        if src_file.exists():
                            file_name = f"{base_name}{ext}"
                            full_path = src_file
                            break
                    else:
                        # 没有找到对应源文件，跳过
                        continue

                # 去重检查
                if base_name in processed_names:
                    continue
                processed_names.add(base_name)

                # 获取 diff 统计（使用源文件路径）
                diff_stat = get_diff_stat(
                    commit_id,
                    str(full_path.relative_to(project_path)).replace('\\', '/'),
                    project_path
                )

                target = TestTarget(
                    file_name=file_name,
                    file_path=str(full_path),
                    target_type='diff',
                    diff_info={
                        'commit_id': commit_id,
                        'change_type': file_info['change_type'],
                        'lines_added': diff_stat.get('lines_added', 0),
                        'lines_deleted': diff_stat.get('lines_deleted', 0)
                    }
                )
                targets.append(target)
                logger.info(f"发现 diff 文件: {target.file_name} ({file_info['change_type']})")

        except Exception as e:
            logger.error(f"获取 diff 文件失败: {e}")

        return targets

    def _get_program_targets(self) -> List[TestTarget]:
        """
        获取用户指定的测试程序

        Returns:
            用户指定的程序列表
        """
        targets = []
        programs = self.config.get('test_programs', [])

        for prog in programs:
            file_name = prog.get('file_name')
            file_path = prog.get('file_path')
            issues = prog.get('issues', [])

            if not file_name or not file_path:
                logger.warning(f"程序配置不完整: {prog}")
                continue

            # Python 特有：跳过 __init__.py
            if is_python_file(file_name) and file_name.endswith('__init__.py'):
                logger.info(f"跳过 __init__.py 文件: {file_name}")
                continue

            if not Path(file_path).exists():
                logger.warning(f"程序文件不存在: {file_path}")
                continue

            target = TestTarget(
                file_name=file_name,
                file_path=file_path,
                target_type='program',
                issues=issues
            )
            targets.append(target)
            logger.info(f"添加程序测试目标: {file_name}")

        return targets

    def _generate_config_files(self):
        """为每个目标生成配置文件"""
        for target in self.targets:
            # 设置报告路径
            target.set_report_paths(self.report_dir)

            # 创建配置目录
            target.config_dir.mkdir(parents=True, exist_ok=True)

            # 写入配置文件
            with open(target.config_path, 'w', encoding='utf-8') as f:
                json.dump(target.to_config(), f, indent=2, ensure_ascii=False)

            logger.info(f"生成配置文件: {target.config_path}")

    def _generate_test_plan(self, target: TestTarget) -> bool:
        """生成测试方案"""
        logger.info(f"生成测试方案: {target.file_name}")
        try:
            return self.claude.generate_test_plan(
                target_file=Path(target.file_path),
                target_type=target.target_type,
                config=target.to_config(),
                output_file=target.plan_path
            )
        except ClaudeError as e:
            logger.error(f"生成测试方案失败 [{target.file_name}]: {e}")
            return False

    def _generate_test_code(self, target: TestTarget) -> bool:
        """生成/更新测试代码"""
        logger.info(f"生成测试代码: {target.file_name} (语言: {target.language})")

        target.test_dir.mkdir(parents=True, exist_ok=True)

        # Python 特有：创建 __init__.py
        if target.language == 'python':
            init_file = target.test_dir / '__init__.py'
            if not init_file.exists():
                init_file.touch()

        existing_test = target.test_file_path if target.test_file_path.exists() else None

        try:
            return self.claude.generate_test_code(
                target_file=Path(target.file_path),
                test_plan_file=target.plan_path,
                existing_test_file=existing_test,
                output_file=target.test_file_path,
                language=target.language
            )
        except ClaudeError as e:
            logger.error(f"生成测试代码失败 [{target.file_name}]: {e}")
            return False

    def _run_parallel(self, func: Callable[[TestTarget], bool], stage_name: str) -> int:
        """并行执行目标处理函数"""
        max_workers = self.config.get(ConfigKey.EXECUTION, {}).get(ConfigKey.MAX_WORKERS, Defaults.MAX_WORKERS)
        success_count = 0

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(func, target): target for target in self.targets}

            for future in as_completed(futures):
                target = futures[future]
                try:
                    if future.result():
                        success_count += 1
                except Exception as e:
                    logger.error(f"{stage_name}失败 [{target.file_name}]: {e}")

        return success_count

    MAX_RETRIES = 3  # 最大重试次数

    def _run_tests(self, target: TestTarget) -> bool:
        """执行测试，失败时自动修复并重试"""
        if not target.test_file_path.exists():
            logger.warning(f"测试文件不存在: {target.test_file_path}")
            return False

        for attempt in range(self.MAX_RETRIES + 1):
            success, error_info = self._execute_single_test(target)

            if success:
                if attempt > 0:
                    logger.info(f"[{target.file_name}] 修复成功，测试通过")
                return True

            if attempt >= self.MAX_RETRIES:
                logger.error(f"[{target.file_name}] 达到最大重试次数 ({self.MAX_RETRIES})")
                return False

            logger.warning(f"[{target.file_name}] 测试失败，尝试修复 ({attempt + 1}/{self.MAX_RETRIES})")
            if not self._fix_test_code(target, error_info):
                return False

        return False

    def _execute_single_test(self, target: TestTarget) -> Tuple[bool, str]:
        """执行单次测试，返回 (是否成功, 错误信息)"""
        try:
            runner = self._create_runner(target)
            result = runner.run(
                with_coverage=True,
                coverage_target=Path(target.file_path),
                timeout=self.config.get(ConfigKey.CLAUDE_CONFIG, {}).get(ConfigKey.TIMEOUT_SECONDS, Defaults.TIMEOUT_SECONDS)
            )
            runner.generate_summary(target.summary_path, target_file=target.file_path)

            return self._evaluate_result(result)

        except Exception as e:
            error_msg = f"执行测试异常: {e}"
            logger.error(f"[{target.file_name}] {error_msg}")
            return False, error_msg

    def _create_runner(self, target: TestTarget):
        """创建对应语言的测试运行器"""
        project_path = Path(self.config['project_path'])

        if target.language == 'cpp':
            from script.test_runner import CppTestRunner
            return CppTestRunner(target.test_file_path, project_path, target_file=Path(target.file_path))
        return TestRunner(target.test_file_path, project_path)

    def _evaluate_result(self, result) -> Tuple[bool, str]:
        """评估测试结果"""
        if result.total == 0:
            return False, "测试收集失败：没有收集到任何测试用例"

        failure_rate = (result.failed + result.errors) / result.total
        if failure_rate <= CoverageTarget.MAX_FAILURE_RATE:
            return True, ""

        error_info = self._format_error_info(result)
        return False, error_info

    def _format_error_info(self, result) -> str:
        """格式化错误信息"""
        lines = []
        for case in result.cases:
            if case.status in ('failed', 'error'):
                lines.append(f"\n测试用例: {case.name}")
                lines.append(f"状态: {case.status}")
                if case.message:
                    lines.append(f"错误: {case.message[:200]}")
                if case.traceback:
                    lines.append(f"堆栈:\n{case.traceback[:1000]}")
        return '\n'.join(lines) if lines else "未知错误"

    def _fix_test_code(self, target: TestTarget, error_info: str) -> bool:
        """调用 Claude 修复测试代码"""
        try:
            current_code = target.test_file_path.read_text(encoding='utf-8')
        except Exception as e:
            logger.error(f"读取测试文件失败: {e}")
            return False

        # 构建修复提示词
        prompt = f"""请修复以下 {target.language} 测试代码中的错误。

被测文件: {target.file_path}
测试文件: {target.test_file_path}

【错误信息】
```
{error_info[:1500]}
```

【当前代码】
```{target.language}
{current_code[:2500]}
```

【修复要求】
1. 分析并修复导致测试失败的问题
2. 确保代码可以直接运行通过
3. 修正导入路径或函数签名不匹配问题

只输出修复后的完整代码，不要其他解释。"""

        try:
            output = self.claude.call(prompt=prompt, files=[Path(target.file_path)])
            code = self.claude._extract_code_block(output)

            if not code.strip():
                logger.error("Claude 返回的修复代码为空")
                return False

            target.test_file_path.write_text(code, encoding='utf-8')
            logger.info(f"测试代码已修复: {target.test_file_path}")
            return True

        except Exception as e:
            logger.error(f"调用 Claude 修复失败: {e}")
            return False

    def _generate_reports(self) -> bool:
        """生成综合报告"""
        logger.info("生成综合报告")

        summary_files = [t.summary_path for t in self.targets if t.summary_path.exists()]
        if not summary_files:
            logger.warning("没有可用的摘要文件")
            return False

        # 使用 Claude 生成详细报告
        try:
            self.claude.generate_report(
                summary_files=summary_files,
                coverage_files=[],
                output_file=self.report_dir / 'summary_report.md'
            )
        except ClaudeError as e:
            logger.error(f"Claude 生成报告失败: {e}")

        # 生成本地 JSON 报告作为备份
        try:
            from script.report_generator import aggregate_summaries
            files_data = aggregate_summaries(summary_files)
            report_data = ReportData(
                project=self.config['project'],
                commit_id=self.config['commit_id'],
                branch=self.config.get('branch', 'main'),
                start_time=self.start_time,
                end_time=datetime.now(),
                files=files_data
            )
            ReportGenerator(self.report_dir).generate_json_report(report_data)
        except Exception as e:
            logger.error(f"生成本地报告失败: {e}")

        return True

    def discover(self) -> bool:
        """发现阶段：获取所有待测试文件并生成配置文件"""
        logger.info("=" * 50)
        logger.info("阶段 1/5: 发现待测试文件")
        logger.info("=" * 50)

        diff_targets = self._get_commit_diff_targets()
        program_targets = self._get_program_targets()

        # 去重：优先使用用户配置
        program_paths = {Path(t.file_path).resolve() for t in program_targets}
        unique_diff_targets = [
            t for t in diff_targets
            if Path(t.file_path).resolve() not in program_paths
        ]

        self.targets = unique_diff_targets + program_targets

        if not self.targets:
            logger.warning("未发现任何待测试文件")
            return False

        logger.info(f"共发现 {len(self.targets)} 个测试目标")
        if len(unique_diff_targets) < len(diff_targets):
            logger.info(f"去重：跳过 {len(diff_targets) - len(unique_diff_targets)} 个重复目标")

        logger.info("生成目标配置文件...")
        self._generate_config_files()

        return True

    def plan(self) -> bool:
        """计划阶段：生成测试方案"""
        logger.info("=" * 50)
        logger.info("阶段 2/5: 生成测试方案")
        logger.info("=" * 50)

        success_count = self._run_parallel(self._generate_test_plan, "生成测试方案")
        logger.info(f"测试方案生成完成: {success_count}/{len(self.targets)}")
        return success_count > 0

    def generate(self) -> bool:
        """生成阶段：创建/更新测试代码"""
        logger.info("=" * 50)
        logger.info("阶段 3/5: 生成测试代码")
        logger.info("=" * 50)

        success_count = self._run_parallel(self._generate_test_code, "生成测试代码")
        logger.info(f"测试代码生成完成: {success_count}/{len(self.targets)}")
        return success_count > 0

    def execute(self) -> bool:
        """执行阶段：运行测试"""
        logger.info("=" * 50)
        logger.info("阶段 4/5: 执行测试")
        logger.info("=" * 50)

        success_count = self._run_parallel(self._run_tests, "执行测试")
        total = len(self.targets)
        logger.info(f"测试执行完成: {success_count}/{total} 通过")

        if success_count < total:
            logger.warning(f"有 {total - success_count} 个目标测试失败或修复失败")

        return True  # 即使部分失败也继续

    def report(self) -> bool:
        """报告阶段：生成综合分析报告"""
        logger.info("=" * 50)
        logger.info("阶段 5/5: 生成报告")
        logger.info("=" * 50)

        return self._generate_reports()

    def run(self) -> bool:
        """执行完整流程"""
        logger.info("=" * 50)
        logger.info("porygon_t - AI 自主测试生成器")
        logger.info("=" * 50)

        self.start_time = datetime.now()

        if not self._validate_config():
            return False

        self.report_dir = self._create_report_directory()

        stages = [
            ("发现", self.discover),
            ("计划", self.plan),
            ("生成", self.generate),
            ("执行", self.execute),
            ("报告", self.report),
        ]

        for stage_name, stage_func in stages:
            try:
                if not stage_func():
                    logger.error(f"阶段 '{stage_name}' 执行失败")
                    return False
            except Exception as e:
                logger.error(f"阶段 '{stage_name}' 发生异常: {e}")
                return False

        logger.info("=" * 50)
        logger.info("所有阶段执行完成")
        logger.info(f"报告目录: {self.report_dir}")
        logger.info("=" * 50)

        return True


def main():
    """主入口函数"""
    import argparse

    parser = argparse.ArgumentParser(
        description='porygon_t - AI 自主测试生成器'
    )
    parser.add_argument(
        '--plan', '-p',
        default='test_plan.json',
        help='测试计划配置文件路径 (默认: test_plan.json)'
    )
    parser.add_argument(
        '--stage', '-s',
        choices=['discover', 'plan', 'generate', 'execute', 'report'],
        help='单独执行某个阶段'
    )

    args = parser.parse_args()

    # 初始化 Agent
    agent = PorygonT(args.plan)

    # 如果指定了阶段，单独执行
    if args.stage:
        if not agent._validate_config():
            sys.exit(1)
        agent.report_dir = agent._create_report_directory()

        stage_map = {
            'discover': agent.discover,
            'plan': agent.plan,
            'generate': agent.generate,
            'execute': agent.execute,
            'report': agent.report,
        }

        success = stage_map[args.stage]()
        sys.exit(0 if success else 1)
    else:
        # 执行完整流程
        success = agent.run()
        sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
