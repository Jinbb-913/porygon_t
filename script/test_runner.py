"""
测试执行器模块

提供运行 pytest、Google Test，收集测试结果等功能。
"""

import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
import xml.etree.ElementTree as ET

# 导入常量
from constants import CoverageTarget

logger = logging.getLogger('porygon_t.runner')

# 线程锁，用于保护 matplotlib 图表生成（pyplot 不是线程安全的）
_chart_lock = threading.Lock()


def generate_coverage_chart(coverage_data: Dict, output_path: Path) -> bool:
    """
    生成覆盖率可视化图表

    Args:
        coverage_data: 覆盖率数据
        output_path: 输出路径（fig/目录下的文件）

    Returns:
        是否成功
    """
    # 获取阈值
    line_target = int(CoverageTarget.LINE_RATE * 100)
    branch_target = int(CoverageTarget.BRANCH_RATE * 100)

    # 使用线程锁保护 matplotlib 操作（pyplot 不是线程安全的）
    with _chart_lock:
        try:
            import matplotlib
            matplotlib.use('Agg')  # 非交互式后端
            import matplotlib.pyplot as plt

            line_rate = coverage_data.get('line_rate', 0) * 100
            branch_rate = coverage_data.get('branch_rate', 0) * 100

            # 创建图表
            fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 4))

            # 行覆盖率饼图
            colors1 = ['#4CAF50', '#FFC107'] if line_rate >= line_target else ['#FFC107', '#F44336']
            ax1.pie([line_rate, 100 - line_rate], labels=[f'Covered\n{line_rate:.1f}%', f'Uncovered\n{100-line_rate:.1f}%'],
                    colors=colors1, autopct='', startangle=90)
            ax1.set_title(f'Line Coverage (Target: >={line_target}%)', fontsize=12, fontweight='bold')

            # 分支覆盖率饼图
            if branch_rate > 0:
                colors2 = ['#4CAF50', '#FFC107'] if branch_rate >= branch_target else ['#FFC107', '#F44336']
                ax2.pie([branch_rate, 100 - branch_rate], labels=[f'Covered\n{branch_rate:.1f}%', f'Uncovered\n{100-branch_rate:.1f}%'],
                        colors=colors2, autopct='', startangle=90)
                ax2.set_title(f'Branch Coverage (Target: >={branch_target}%)', fontsize=12, fontweight='bold')
            else:
                ax2.text(0.5, 0.5, 'Branch coverage\nnot available', ha='center', va='center', fontsize=10)
                ax2.set_title('Branch Coverage', fontsize=12, fontweight='bold')
                ax2.axis('off')

            plt.tight_layout()

            # 强制渲染并保存图表
            fig.canvas.draw()
            output_path.parent.mkdir(parents=True, exist_ok=True)
            plt.savefig(output_path, dpi=150, bbox_inches='tight', pad_inches=0.2)
            plt.close(fig)

            logger.info(f"覆盖率图表已生成: {output_path} (line_rate={line_rate:.1f}%, branch_rate={branch_rate:.1f}%)")
            return True

        except ImportError:
            logger.warning("matplotlib 未安装，跳过覆盖率图表生成")
            return False
        except Exception as e:
            logger.error(f"生成覆盖率图表失败: {e}")
            return False


@dataclass
class TestCase:
    """单个测试用例结果"""
    name: str
    status: str  # 'passed', 'failed', 'skipped', 'error'
    duration: float = 0.0
    message: Optional[str] = None
    traceback: Optional[str] = None


@dataclass
class TestResult:
    """测试结果"""
    test_file: str
    total: int = 0
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    errors: int = 0
    duration: float = 0.0
    cases: List[TestCase] = field(default_factory=list)
    coverage: Dict = field(default_factory=dict)

    @property
    def success_rate(self) -> float:
        if self.total == 0:
            return 0.0
        return self.passed / self.total * 100

    @property
    def failure_rate(self) -> float:
        """计算失败率"""
        if self.total == 0:
            return 0.0
        return (self.failed + self.errors) / self.total

    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            'test_file': self.test_file,
            'summary': {
                'total': self.total,
                'passed': self.passed,
                'failed': self.failed,
                'skipped': self.skipped,
                'errors': self.errors,
                'duration': self.duration,
                'success_rate': self.success_rate
            },
            'coverage': self.coverage
        }

    def to_json(self, indent: int = 2) -> str:
        """转换为 JSON 字符串"""
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)


class TestRunner:
    """Python 测试执行器（基于 pytest）"""

    def __init__(self, test_file_path: Path, project_path: Optional[Path] = None):
        self.test_file_path = Path(test_file_path)
        self.project_path = project_path or self.test_file_path.parent
        self.result = TestResult(test_file=str(test_file_path))
        self.junit_file = Path(tempfile.mktemp(suffix='.xml'))

    def _posix_path(self, path: Path) -> str:
        """将路径转换为 POSIX 格式（正斜杠），用于命令行参数"""
        return path.as_posix()

    def run(self, with_coverage: bool = True, coverage_target: Optional[Path] = None,
            timeout: int = 300) -> TestResult:
        """运行 pytest 测试，支持覆盖率收集"""
        logger.info(f"运行测试: {self.test_file_path.name}")

        cmd = [
            'python', '-m', 'pytest',
            self._posix_path(self.test_file_path),
            '-v', '--tb=short',
            f'--junitxml={self._posix_path(self.junit_file)}'
        ]

        # 覆盖率收集配置
        coverage_file = None
        if with_coverage and coverage_target:
            coverage_file = Path(tempfile.mktemp(suffix='.json'))
            cmd.extend([
                f'--cov={self._posix_path(coverage_target.parent)}',
                '--cov-branch',
                f'--cov-report=json:{self._posix_path(coverage_file)}',
            ])

        try:
            result = subprocess.run(
                cmd, cwd=self.project_path,
                capture_output=True, text=True, timeout=timeout
            )

            if result.stderr:
                logger.warning(f"pytest: {result.stderr[:500]}")

            self._parse_junit_results()

            # 如果用例数为0，可能是收集失败
            if self.result.total == 0:
                logger.error(f"测试收集失败: {result.stdout[:1000]}")
                self.result.errors += 1

            # 解析覆盖率结果
            if coverage_file and coverage_file.exists():
                self._parse_coverage_results(coverage_file, coverage_target)

            logger.info(f"测试完成: {self.result.passed}/{self.result.total} 通过")

        except subprocess.TimeoutExpired:
            logger.error(f"测试超时 ({timeout}s)")
            self.result.errors += 1
        except Exception as e:
            logger.error(f"运行测试失败: {e}")
            self.result.errors += 1
        finally:
            self._cleanup()
            if coverage_file and coverage_file.exists():
                try:
                    coverage_file.unlink()
                except OSError:
                    pass

        return self.result

    def _parse_coverage_results(self, coverage_file: Path, coverage_target: Path):
        """解析 pytest-cov 生成的覆盖率报告"""
        try:
            with open(coverage_file, 'r', encoding='utf-8') as f:
                cov_data = json.load(f)

            target_name = coverage_target.name
            target_stem = coverage_target.stem

            # 在覆盖率报告中查找目标文件
            for file_path, file_data in cov_data.get('files', {}).items():
                # 使用 Path 对象统一处理路径格式（解决 Windows 反斜杠/正斜杠问题）
                cov_path = Path(file_path)
                cov_name = cov_path.name
                cov_stem = cov_path.stem

                # 匹配条件：文件名相同或 stem 相同
                if cov_name == target_name or cov_stem == target_stem:
                    summary = file_data.get('summary', {})
                    self.result.coverage = {
                        'line_rate': summary.get('percent_covered', 0) / 100.0,
                        'branch_rate': self._calculate_branch_coverage(file_data),
                        'lines_covered': summary.get('covered_lines', 0),
                        'lines_total': summary.get('num_statements', 0),
                        'missing_lines': file_data.get('missing_lines', [])
                    }
                    logger.debug(f"找到覆盖率数据: {file_path} -> {self.result.coverage['line_rate']:.1%}")
                    return

            # 如果没有找到具体文件，使用总体覆盖率
            totals = cov_data.get('totals', {})
            if totals:
                branch_rate = 0.0
                if totals.get('num_branches', 0) > 0:
                    branch_rate = totals.get('covered_branches', 0) / totals['num_branches']
                self.result.coverage = {
                    'line_rate': totals.get('percent_covered', 0) / 100.0,
                    'branch_rate': branch_rate,
                    'lines_covered': totals.get('covered_lines', 0),
                    'lines_total': totals.get('num_statements', 0),
                    'missing_lines': []
                }
                logger.debug(f"使用总体覆盖率: {self.result.coverage['line_rate']:.1%}")
            else:
                logger.warning(f"未找到 {target_name} 的覆盖率数据，可用文件: {list(cov_data.get('files', {}).keys())[:5]}")

        except Exception as e:
            logger.warning(f"解析覆盖率结果失败: {e}")

    def _calculate_branch_coverage(self, file_data: Dict) -> float:
        """计算分支覆盖率"""
        summary = file_data.get('summary', {})
        # 如果数据中有分支信息则使用，否则返回0
        if 'num_branches' in summary and summary['num_branches'] > 0:
            return summary.get('covered_branches', 0) / summary['num_branches']
        return 0.0

    def _parse_junit_results(self):
        """解析 JUnit XML 结果"""
        if not self.junit_file.exists():
            return

        try:
            tree = ET.parse(self.junit_file)
            root = tree.getroot()

            for testsuite in root.findall('testsuite'):
                self.result.total = int(testsuite.get('tests', 0))
                self.result.failed = int(testsuite.get('failures', 0))
                self.result.errors = int(testsuite.get('errors', 0))
                self.result.skipped = int(testsuite.get('skipped', 0))
                self.result.duration = float(testsuite.get('time', 0))
                self.result.passed = (
                    self.result.total - self.result.failed
                    - self.result.errors - self.result.skipped
                )

                for testcase in testsuite.findall('testcase'):
                    case = self._parse_test_case(testcase)
                    self.result.cases.append(case)

        except Exception:
            logger.exception("解析 JUnit 结果失败")

    def _parse_test_case(self, testcase: ET.Element) -> TestCase:
        """解析单个测试用例"""
        name = testcase.get('name', 'unknown')
        duration = float(testcase.get('time', 0))
        status = 'passed'
        message = None
        traceback = None

        failure = testcase.find('failure')
        if failure is not None:
            status = 'failed'
            message = failure.get('message', '')
            traceback = failure.text

        error = testcase.find('error')
        if error is not None:
            status = 'error'
            message = error.get('message', '')
            traceback = error.text

        skipped = testcase.find('skipped')
        if skipped is not None:
            status = 'skipped'
            message = skipped.get('message', '')

        return TestCase(
            name=name, status=status, duration=duration,
            message=message, traceback=traceback
        )

    def _cleanup(self):
        """清理临时文件"""
        if self.junit_file.exists():
            try:
                self.junit_file.unlink()
            except OSError:
                pass

    def generate_summary(self, output_path: Path, target_file: Optional[str] = None) -> bool:
        """生成测试摘要文件（Markdown格式，符合plan.md要求）"""
        lines = _format_test_summary(self.result, target_file, language='python')
        return _write_summary_file(output_path, self.result, lines)


def _format_test_summary(
    result: TestResult,
    target_file: Optional[str],
    language: str = 'python'
) -> List[str]:
    """
    格式化测试摘要为 Markdown 行列表

    Args:
        result: 测试结果
        target_file: 被测文件路径
        language: 语言类型 ('python' 或 'cpp')

    Returns:
        Markdown 行列表
    """
    line_rate = result.coverage.get('line_rate', 0)
    branch_rate = result.coverage.get('branch_rate', 0)
    lines_covered = result.coverage.get('lines_covered', 0)
    lines_total = result.coverage.get('lines_total', 0)
    missing_lines = result.coverage.get('missing_lines', [])

    is_cpp = language == 'cpp'

    # 判断测试结论 - 标准：失败率 <= MAX_FAILURE_RATE
    failure_rate = 0 if result.total == 0 else (result.failed + result.errors) / result.total
    if failure_rate <= CoverageTarget.MAX_FAILURE_RATE and line_rate >= CoverageTarget.LINE_RATE:
        conclusion = "✅ 通过"
    elif failure_rate <= CoverageTarget.MAX_FAILURE_RATE and not is_cpp:
        conclusion = "⚠️ 有条件通过"
    elif failure_rate <= CoverageTarget.MAX_FAILURE_RATE:
        conclusion = "✅ 通过"
    else:
        conclusion = "❌ 未通过"

    # 标题
    title_suffix = " (C++)" if is_cpp else ""
    lines = [
        f"# 测试摘要 - {Path(result.test_file).name}{title_suffix}",
        "",
        "## 程序基本信息",
        "",
        f"- **测试文件**: `{result.test_file}`",
        f"- **被测文件**: `{target_file or 'N/A'}`",
    ]

    # C++ 特有信息
    if is_cpp:
        lines.extend([
            f"- **编程语言**: C++",
            f"- **测试框架**: Google Test",
        ])

    lines.extend([
        f"- **测试时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- **执行耗时**: {result.duration:.2f} 秒",
        "",
        "---",
        "",
        "## 测试用例统计",
        "",
        "| 指标 | 数值 |",
        "|------|------|",
        f"| 总用例数 | {result.total} |",
        f"| 通过 | {result.passed} ({result.success_rate:.1f}%) |",
        f"| 失败 | {result.failed} |",
        f"| 错误 | {result.errors} |",
        f"| 跳过 | {result.skipped} |",
        "",
        "---",
        "",
        "## 测试覆盖率",
        "",
        "| 指标 | 数值 | 目标 | 状态 |",
        "|------|------|------|------|",
        f"| 行覆盖率 | {line_rate:.1%} | ≥ {int(CoverageTarget.LINE_RATE * 100)}% | {'✅' if line_rate >= CoverageTarget.LINE_RATE else '⚠️'} |",
        f"| 分支覆盖率 | {branch_rate:.1%} | ≥ {int(CoverageTarget.BRANCH_RATE * 100)}% | {'✅' if branch_rate >= CoverageTarget.BRANCH_RATE else '⚠️'} |",
    ])

    # Python 特有：覆盖行数详情
    if not is_cpp:
        lines.append(f"| 覆盖行数 | {lines_covered} / {lines_total} | - | - |")

    lines.extend(["",])

    # Python 特有：未覆盖行信息
    if not is_cpp and missing_lines:
        lines.extend([
            "### 未覆盖行",
            "",
            f"```\n{', '.join(map(str, missing_lines[:50]))}{'...' if len(missing_lines) > 50 else ''}\n```",
            "",
        ])

    # 用例详情表头
    lines.extend([
        "---",
        "",
        "## 测试用例详情",
        "",
    ])

    if is_cpp:
        lines.append("| 用例名称 | 状态 | 耗时(ms) |")
        lines.append("|----------|------|----------|")
    else:
        lines.append("| 用例名称 | 状态 | 耗时(ms) | 说明 |")
        lines.append("|----------|------|----------|------|")

    # 用例详情
    for case in result.cases:
        status_icon = {'passed': '✅', 'failed': '❌', 'error': '💥', 'skipped': '⏭️'}.get(case.status, '❓')
        duration_ms = case.duration * 1000
        if is_cpp:
            lines.append(f"| {case.name} | {status_icon} {case.status} | {duration_ms:.1f} |")
        else:
            message = case.message[:30] + '...' if case.message and len(case.message) > 30 else (case.message or '')
            lines.append(f"| {case.name} | {status_icon} {case.status} | {duration_ms:.1f} | {message} |")

    # 测试结论
    lines.extend([
        "",
        "---",
        "",
        "## 测试结论",
        "",
        f"**总体评估**: {conclusion}",
        "",
        "### 关键发现",
        "",
    ])

    if result.failed > 0:
        lines.append(f"- ❌ 存在 {result.failed} 个失败用例，需要修复")
    if line_rate < CoverageTarget.LINE_RATE and not is_cpp:
        lines.append(f"- ⚠️ 行覆盖率 {line_rate:.1%} 未达到 {int(CoverageTarget.LINE_RATE * 100)}% 目标")
    if branch_rate < CoverageTarget.BRANCH_RATE and branch_rate > 0 and not is_cpp:
        lines.append(f"- ⚠️ 分支覆盖率 {branch_rate:.1%} 未达到 {int(CoverageTarget.BRANCH_RATE * 100)}% 目标")
    if result.failed == 0 and (is_cpp or line_rate >= CoverageTarget.LINE_RATE):
        lines.append("- ✅ 所有测试通过" + ("，覆盖率达标" if not is_cpp else ""))

    # JSON 数据
    json_data = {
        'test_file': result.test_file,
        'summary': {
            'total': result.total,
            'passed': result.passed,
            'failed': result.failed,
            'skipped': result.skipped,
            'errors': result.errors,
            'duration': result.duration,
            'success_rate': result.success_rate
        },
        'coverage': result.coverage,
    }
    if is_cpp:
        json_data['language'] = 'cpp'

    lines.extend([
        "",
        "---",
        "",
        "## 原始数据",
        "",
        "```json",
        json.dumps(json_data, indent=2, ensure_ascii=False),
        "```",
        "",
    ])

    return lines


def _write_summary_file(
    output_path: Path,
    result: TestResult,
    lines: List[str]
) -> bool:
    """
    将摘要写入文件并生成图表

    Args:
        output_path: 输出文件路径
        result: 测试结果（用于生成图表）
        lines: Markdown 行列表

    Returns:
        是否成功
    """
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text('\n'.join(lines), encoding='utf-8')

        # 生成覆盖率图表
        if result.coverage:
            fig_dir = output_path.parent / 'fig'
            chart_path = fig_dir / 'coverage_chart.png'
            generate_coverage_chart(result.coverage, chart_path)

        return True
    except Exception as e:
        logger.error(f"生成摘要失败: {e}")
        return False


def run_single_test(test_file: Path, project_path: Optional[Path] = None,
                    output_summary: Optional[Path] = None,
                    coverage_target: Optional[Path] = None) -> TestResult:
    """运行单个测试文件的便捷函数"""
    runner = TestRunner(test_file, project_path)
    result = runner.run(with_coverage=True, coverage_target=coverage_target)
    if output_summary:
        runner.generate_summary(output_summary, target_file=str(coverage_target) if coverage_target else None)
    return result


class CppTestRunner:
    """C++ 测试执行器（基于 Google Test）"""

    def __init__(self, test_file_path: Path, project_path: Optional[Path] = None,
                 target_file: Optional[Path] = None):
        self.test_file_path = Path(test_file_path)
        self.project_path = project_path or self.test_file_path.parent
        self.target_file = target_file
        self.result = TestResult(test_file=str(test_file_path))
        self.test_binary: Optional[Path] = None

    def _find_cmake_or_build_system(self) -> Optional[Path]:
        """向上查找 CMakeLists.txt"""
        current = self.project_path
        for _ in range(5):
            cmake_file = current / 'CMakeLists.txt'
            if cmake_file.exists():
                return current
            parent = current.parent
            if parent == current:
                break
            current = parent
        return None

    def _compile_test(self, timeout: int = 300) -> bool:
        """编译 C++ 测试"""
        cmake_root = self._find_cmake_or_build_system()
        if cmake_root:
            logger.info(f"检测到 CMake 项目: {cmake_root}")
            return self._compile_with_cmake(cmake_root, timeout)
        else:
            logger.info("未检测到 CMake，尝试直接编译")
            return self._compile_directly(timeout)

    def _find_cmake_executable(self) -> str:
        """查找 CMake 可执行文件"""
        cmake_exe = 'cmake.exe' if os.name == 'nt' else 'cmake'
        cmake_path = shutil.which(cmake_exe)
        if cmake_path:
            return cmake_path
        try:
            import cmake
            cmake_dir = Path(cmake.CMAKE_BIN_DIR)
            cmake_exe_path = cmake_dir / cmake_exe
            if cmake_exe_path.exists():
                return str(cmake_exe_path)
        except ImportError:
            pass
        return cmake_exe

    def _detect_mingw(self) -> Optional[Path]:
        """检测 MinGW 安装路径"""
        if os.name != 'nt':
            return None
        msys2_paths = [
            Path('C:/msys64/ucrt64/bin'),
            Path('C:/msys64/mingw64/bin'),
            Path('C:/mingw64/bin'),
            Path('C:/mingw/bin'),
        ]
        for path in msys2_paths:
            if path.exists() and (path / 'g++.exe').exists():
                return path
        return None

    def _compile_with_cmake(self, cmake_root: Path, timeout: int) -> bool:
        """使用 CMake 编译"""
        build_dir = Path(tempfile.mkdtemp(prefix=f'cmake_build_{self.test_file_path.stem}_'))
        logger.info(f"CMake 构建目录: {build_dir}")

        env = os.environ.copy()
        mingw_path = self._detect_mingw()
        if mingw_path:
            logger.info(f"检测到 MinGW: {mingw_path}")
            env['PATH'] = str(mingw_path) + os.pathsep + env.get('PATH', '')
            env['CXX'] = str(mingw_path / 'g++.exe')

        cmake_exe = self._find_cmake_executable()
        logger.info(f"使用 CMake: {cmake_exe}")

        cmake_cmd = [cmake_exe, str(cmake_root), '-DCMAKE_BUILD_TYPE=Debug']
        if os.name == 'nt' and mingw_path:
            cmake_cmd.extend(['-G', 'MinGW Makefiles'])

        try:
            result = subprocess.run(
                cmake_cmd, cwd=build_dir, capture_output=True,
                text=True, timeout=timeout, env=env
            )
            if result.returncode != 0:
                logger.error(f"CMake 配置失败: {result.stderr}")
                return False

            build_cmd = [cmake_exe, '--build', str(build_dir), '--parallel', '4']
            result = subprocess.run(
                build_cmd, capture_output=True,
                text=True, timeout=timeout, env=env
            )
            if result.returncode != 0:
                logger.error(f"CMake 构建失败: {result.stderr}")
                return False

            # 查找测试二进制文件
            test_name = self.test_file_path.stem.replace('test_', '')
            exe_suffix = '.exe' if os.name == 'nt' else ''
            for pattern in [f'test_{test_name}{exe_suffix}', f'{test_name}_test{exe_suffix}']:
                for search_dir in [build_dir, build_dir / 'src', build_dir / 'tests']:
                    binary = search_dir / pattern
                    if binary.exists():
                        self.test_binary = binary
                        break
                if self.test_binary:
                    break

            if self.test_binary:
                logger.info(f"找到测试二进制文件: {self.test_binary}")
            else:
                logger.error("未找到测试二进制文件")

            return self.test_binary is not None

        except Exception as e:
            logger.error(f"CMake 编译失败: {e}")
            return False

    def _compile_directly(self, timeout: int) -> bool:
        """直接编译单个测试文件"""
        temp_dir = Path(tempfile.mkdtemp(prefix='cpp_test_'))
        exe_suffix = '.exe' if os.name == 'nt' else ''
        self.test_binary = temp_dir / f'test_runner{exe_suffix}'

        cmd = [
            'g++', '-std=c++14', '-O0', '-g',
            '-I', str(self.project_path),
            '-I', str(self.project_path / 'src'),
            str(self.test_file_path)
        ]

        if self.target_file and self.target_file.suffix in ['.cpp', '.cc', '.cxx']:
            cmd.append(str(self.target_file))

        cmd.extend(['-lgtest', '-lgtest_main', '-lpthread', '-o', str(self.test_binary)])

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout
            )
            if result.returncode != 0:
                logger.error(f"编译失败: {result.stderr}")
                return False
            return True
        except Exception as e:
            logger.error(f"编译异常: {e}")
            return False

    def _parse_gtest_output(self, output: str):
        """解析 Google Test 输出"""
        test_pattern = re.compile(r'\[\s+(\w+)\s+\]\s+(\w+)\.(\w+)\s+\((\d+)\s*ms\)')

        for line in output.split('\n'):
            match = test_pattern.search(line)
            if match:
                status_str, suite, test_name, duration = match.groups()
                status_map = {'OK': 'passed', 'FAILED': 'failed', 'SKIPPED': 'skipped'}
                case = TestCase(
                    name=f"{suite}.{test_name}",
                    status=status_map.get(status_str, 'unknown'),
                    duration=float(duration) / 1000.0
                )
                self.result.cases.append(case)
                self.result.total += 1
                if case.status == 'passed':
                    self.result.passed += 1
                elif case.status == 'failed':
                    self.result.failed += 1
                elif case.status == 'skipped':
                    self.result.skipped += 1

    def run(self, with_coverage: bool = True, coverage_target: Optional[Path] = None,
            timeout: int = 300) -> TestResult:
        """运行 C++ 测试"""
        # with_coverage 和 coverage_target 参数暂时保留以保持兼容性
        _ = with_coverage, coverage_target
        logger.info(f"编译 C++ 测试: {self.test_file_path.name}")

        if not self._compile_test(timeout):
            logger.error("C++ 测试编译失败")
            self.result.errors += 1
            return self.result

        logger.info(f"执行 C++ 测试: {self.test_binary}")

        try:
            env = os.environ.copy()
            mingw_path = self._detect_mingw()
            if mingw_path:
                env['PATH'] = str(mingw_path) + os.pathsep + env.get('PATH', '')

            cmd = [str(self.test_binary), '--gtest_color=no']
            result = subprocess.run(
                cmd, capture_output=True, text=True,
                timeout=timeout, shell=False, env=env
            )

            self._parse_gtest_output(result.stdout)
            self._parse_gtest_output(result.stderr)

            logger.info(f"测试完成: {self.result.passed}/{self.result.total} 通过")

        except subprocess.TimeoutExpired:
            logger.error(f"测试超时 ({timeout}s)")
            self.result.errors += 1
        except Exception as e:
            logger.error(f"运行测试失败: {e}")
            self.result.errors += 1

        return self.result

    def generate_summary(self, output_path: Path, target_file: Optional[str] = None) -> bool:
        """生成测试摘要文件（Markdown格式，符合plan.md要求）"""
        lines = _format_test_summary(self.result, target_file, language='cpp')
        return _write_summary_file(output_path, self.result, lines)
