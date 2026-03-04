"""
测试执行器模块

提供运行 pytest、收集测试结果和覆盖率等功能。
"""

import json
import logging
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional
import xml.etree.ElementTree as ET

logger = logging.getLogger('porygon_t.runner')


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
    html_report_path: Optional[str] = None

    @property
    def success_rate(self) -> float:
        """成功率"""
        if self.total == 0:
            return 0.0
        return self.passed / self.total * 100


class TestRunner:
    """测试执行器"""

    def __init__(
        self,
        test_file_path: Path,
        project_path: Optional[Path] = None
    ):
        """
        初始化测试执行器

        Args:
            test_file_path: 测试文件路径
            project_path: 项目根路径（用于覆盖率计算）
        """
        self.test_file_path = Path(test_file_path)
        self.project_path = project_path or self.test_file_path.parent
        self.result = TestResult(test_file=str(test_file_path))
        # 创建临时文件用于存储结果
        self.junit_file = Path(tempfile.mktemp(suffix='.xml'))
        self.coverage_file = Path(tempfile.mktemp(suffix='.xml'))

    def run(
        self,
        with_coverage: bool = True,
        coverage_target: Optional[Path] = None,
        timeout: int = 300
    ) -> TestResult:
        """
        运行测试

        Args:
            with_coverage: 是否收集覆盖率
            coverage_target: 覆盖率计算目标文件
            timeout: 超时时间（秒）

        Returns:
            测试结果
        """
        logger.info(f"运行测试: {self.test_file_path.name}")

        # 辅助函数：转换路径为 posix 格式（跨平台兼容）
        def _posix(path):
            return path.as_posix() if hasattr(path, 'as_posix') else str(path).replace('\\', '/')

        # 构建 pytest 命令
        cmd = [
            'python', '-m', 'pytest',
            _posix(self.test_file_path),
            '-v',
            '--tb=short',
            f'--junitxml={_posix(self.junit_file)}'
        ]

        # 添加覆盖率
        # if with_coverage:
        #     cmd.extend(['--cov', _posix(self.project_path)])
        #     cmd.append(f'--cov-report=xml:{_posix(self.coverage_file)}')
        #     cmd.append(f'--cov-report=html:{_posix(self.project_path / "htmlcov")}')

        try:
            result = subprocess.run(
                cmd,
                cwd=self.project_path,
                capture_output=True,
                text=True,
                timeout=timeout
            )

            # 如果测试执行出错（非测试失败），记录 stderr 以便调试
            if result.returncode != 0 and result.stderr:
                logger.warning(f"pytest stderr: {result.stderr[:500]}")

            # 解析结果
            self._parse_junit_results()

            # 解析覆盖率
            if with_coverage:
                self._parse_coverage(coverage_target)
                self.result.html_report_path = str(self.project_path / 'htmlcov' / 'index.html')

            logger.info(
                f"测试完成: {self.result.passed}/{self.result.total} 通过 "
                f"({self.result.success_rate:.1f}%)"
            )
            if self.result.html_report_path:
                logger.info(f"覆盖率报告: {self.result.html_report_path}")

        except subprocess.TimeoutExpired:
            logger.error(f"测试超时 ({timeout}s)")
            self.result.errors += 1
        except Exception as e:
            logger.error(f"运行测试失败: {e}")
            self.result.errors += 1
        finally:
            self._cleanup()

        return self.result

    def _parse_junit_results(self):
        """解析 JUnit XML 结果"""
        if not self.junit_file.exists():
            return

        try:
            tree = ET.parse(self.junit_file)
            root = tree.getroot()

            # 解析测试套件
            for testsuite in root.findall('testsuite'):
                self.result.total = int(testsuite.get('tests', 0))
                self.result.failed = int(testsuite.get('failures', 0))
                self.result.errors = int(testsuite.get('errors', 0))
                self.result.skipped = int(testsuite.get('skipped', 0))
                self.result.duration = float(testsuite.get('time', 0))

                # 计算通过数
                self.result.passed = (
                    self.result.total
                    - self.result.failed
                    - self.result.errors
                    - self.result.skipped
                )

                # 解析每个测试用例
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

        # 检查失败
        failure = testcase.find('failure')
        if failure is not None:
            status = 'failed'
            message = failure.get('message', '')
            traceback = failure.text

        # 检查错误
        error = testcase.find('error')
        if error is not None:
            status = 'error'
            message = error.get('message', '')
            traceback = error.text

        # 检查跳过
        skipped = testcase.find('skipped')
        if skipped is not None:
            status = 'skipped'
            message = skipped.get('message', '')

        return TestCase(
            name=name,
            status=status,
            duration=duration,
            message=message,
            traceback=traceback
        )

    def _parse_coverage(self, target_file: Optional[Path]):
        """解析覆盖率报告"""
        if not self.coverage_file.exists():
            return

        try:
            tree = ET.parse(self.coverage_file)
            root = tree.getroot()

            # 获取总体覆盖率
            line_rate = float(root.get('line-rate', 0))
            branch_rate = float(root.get('branch-rate', 0))

            self.result.coverage = {
                'line_rate': line_rate * 100,
                'branch_rate': branch_rate * 100,
                'line_covered': 0,
                'line_valid': 0,
                'branch_covered': 0,
                'branch_valid': 0
            }

            # 如果有目标文件，获取该文件的覆盖率
            if target_file:
                for package in root.findall('.//package'):
                    for cls in package.findall('classes/class'):
                        filename = cls.get('filename', '')
                        if target_file.name in filename:
                            self.result.coverage['line_rate'] = float(cls.get('line-rate', 0)) * 100
                            self.result.coverage['branch_rate'] = float(cls.get('branch-rate', 0)) * 100
                            break

        except Exception:
            logger.exception("解析覆盖率失败")

    def _cleanup(self):
        """清理临时文件"""
        for f in [self.junit_file, self.coverage_file]:
            if f.exists():
                try:
                    f.unlink()
                except OSError:
                    pass
        # 清理 pytest-cov 生成的 .coverage 文件
        coverage_data = self.project_path / '.coverage'
        if coverage_data.exists():
            try:
                coverage_data.unlink()
            except OSError:
                pass

    def generate_summary(self, output_path: Path) -> bool:
        """
        生成测试摘要文件

        Args:
            output_path: 输出文件路径

        Returns:
            是否成功
        """
        summary = {
            'test_file': self.result.test_file,
            'summary': {
                'total': self.result.total,
                'passed': self.result.passed,
                'failed': self.result.failed,
                'skipped': self.result.skipped,
                'errors': self.result.errors,
                'duration': self.result.duration,
                'success_rate': self.result.success_rate
            },
            'coverage': self.result.coverage,
            'cases': [
                {
                    'name': case.name,
                    'status': case.status,
                    'duration': case.duration,
                    'message': case.message
                }
                for case in self.result.cases
            ]
        }

        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding='utf-8')
            return True
        except Exception as e:
            logger.error(f"生成摘要失败: {e}")
            return False


def run_single_test(
    test_file: Path,
    target_file: Optional[Path] = None,
    project_path: Optional[Path] = None,
    output_summary: Optional[Path] = None
) -> TestResult:
    """
    运行单个测试文件的便捷函数

    Args:
        test_file: 测试文件路径
        target_file: 被测目标文件（用于覆盖率）
        project_path: 项目路径
        output_summary: 摘要输出路径

    Returns:
        测试结果
    """
    runner = TestRunner(test_file, project_path)
    result = runner.run(with_coverage=True, coverage_target=target_file)

    if output_summary:
        runner.generate_summary(output_summary)

    return result
