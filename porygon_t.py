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
from typing import Callable, Dict, List, Optional

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
        self.file_name = file_name[:-3] if file_name.endswith('.py') else file_name
        self.file_path = file_path
        self.target_type = target_type
        self.issues = issues or []
        self.diff_info = diff_info or {}

        file_dir = Path(file_path).parent
        self.test_dir = file_dir / 'test'
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
        timeout = self.config.get('claude_config', {}).get('timeoutSeconds', 300)
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

            for file_info in diff_files:
                # 只处理 Python 文件，跳过删除的文件和 __init__.py
                if not file_info['file_name'].endswith('.py'):
                    continue
                if file_info['file_name'].endswith('__init__.py'):
                    continue
                if file_info['change_type'] == 'deleted':
                    continue

                # 获取 diff 统计
                diff_stat = get_diff_stat(
                    commit_id,
                    file_info['file_path'],
                    project_path
                )

                target = TestTarget(
                    file_name=file_info['file_name'],
                    file_path=file_info['full_path'],
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

            if file_name.endswith('__init__.py'):
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
        logger.info(f"生成测试代码: {target.file_name}")

        target.test_dir.mkdir(parents=True, exist_ok=True)
        init_file = target.test_dir / '__init__.py'
        if not init_file.exists():
            init_file.touch()

        existing_test = target.test_file_path if target.test_file_path.exists() else None

        try:
            return self.claude.generate_test_code(
                target_file=Path(target.file_path),
                test_plan_file=target.plan_path,
                existing_test_file=existing_test,
                output_file=target.test_file_path
            )
        except ClaudeError as e:
            logger.error(f"生成测试代码失败 [{target.file_name}]: {e}")
            return False

    def _run_parallel(self, func: Callable[[TestTarget], bool], stage_name: str) -> int:
        """并行执行目标处理函数"""
        max_workers = self.config.get('execution', {}).get('maxWorkers', 4)
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

    def _run_tests(self, target: TestTarget) -> bool:
        """执行测试"""
        if not target.test_file_path.exists():
            logger.warning(f"测试文件不存在: {target.test_file_path}")
            return False

        logger.info(f"执行测试: {target.file_name}")

        try:
            runner = TestRunner(
                target.test_file_path,
                Path(self.config['project_path'])
            )
            result = runner.run(
                with_coverage=True,
                coverage_target=Path(target.file_path),
                timeout=self.config.get('claude_config', {}).get('timeoutSeconds', 300)
            )
            runner.generate_summary(target.summary_path)
            # 通过标准：失败率 < 10% 或 没有错误（允许少量失败）
            if result.total == 0:
                return False
            failure_rate = (result.failed + result.errors) / result.total
            return failure_rate <= 0.1
        except Exception as e:
            logger.error(f"执行测试失败 [{target.file_name}]: {e}")
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
        logger.info(f"测试执行完成: {success_count}/{len(self.targets)} 通过")
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
