"""
报告生成器模块

提供生成测试报告、摘要和可视化图表等功能。
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger('porygon_t.report')


@dataclass
class ReportData:
    """报告数据"""
    project: str
    commit_id: str
    branch: str
    start_time: datetime
    end_time: Optional[datetime] = None
    files: List[Dict] = field(default_factory=list)

    @property
    def duration(self) -> float:
        """总耗时（秒）"""
        if self.end_time:
            return (self.end_time - self.start_time).total_seconds()
        return 0.0

    @property
    def total_cases(self) -> int:
        """总用例数"""
        return sum(f.get('total', 0) for f in self.files)

    @property
    def total_passed(self) -> int:
        """通过数"""
        return sum(f.get('passed', 0) for f in self.files)

    @property
    def total_failed(self) -> int:
        """失败数"""
        return sum(f.get('failed', 0) for f in self.files)

    @property
    def total_skipped(self) -> int:
        """跳过数"""
        return sum(f.get('skipped', 0) for f in self.files)

    @property
    def avg_line_coverage(self) -> float:
        """平均行覆盖率"""
        if not self.files:
            return 0.0
        coverages = [f.get('line_coverage', 0) for f in self.files]
        return sum(coverages) / len(coverages)

    @property
    def avg_branch_coverage(self) -> float:
        """平均分支覆盖率"""
        if not self.files:
            return 0.0
        coverages = [f.get('branch_coverage', 0) for f in self.files]
        return sum(coverages) / len(coverages)


class ReportGenerator:
    """报告生成器"""

    def __init__(self, output_dir: Path):
        """
        初始化报告生成器

        Args:
            output_dir: 报告输出目录
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate_markdown_report(self, data: ReportData) -> Path:
        """
        生成 Markdown 格式报告

        Args:
            data: 报告数据

        Returns:
            生成的报告路径
        """
        report_path = self.output_dir / 'summary_report.md'

        lines = [
            f"# 测试报告 - {data.project}",
            "",
            f"**Commit:** {data.commit_id}",
            f"**分支:** {data.branch}",
            f"**测试时间:** {data.start_time.strftime('%Y-%m-%d %H:%M:%S')}",
            f"**总耗时:** {data.duration:.1f} 秒",
            "",
            "---",
            "",
            "## 1. 执行概览",
            "",
            f"- **测试文件数:** {len(data.files)}",
            f"- **总用例数:** {data.total_cases}",
            f"- **通过:** {data.total_passed} ({self._pct(data.total_passed, data.total_cases)})",
            f"- **失败:** {data.total_failed} ({self._pct(data.total_failed, data.total_cases)})",
            f"- **跳过:** {data.total_skipped} ({self._pct(data.total_skipped, data.total_cases)})",
            "",
            "---",
            "",
            "## 2. 覆盖率统计",
            "",
            f"- **平均行覆盖率:** {data.avg_line_coverage:.1f}%",
            f"- **平均分支覆盖率:** {data.avg_branch_coverage:.1f}%",
            "",
            "---",
            "",
            "## 3. 文件级汇总",
            "",
            "| 文件 | 类型 | 用例数 | 通过 | 失败 | 行覆盖 | 状态 |",
            "|------|------|--------|------|------|--------|------|",
        ]

        for f in data.files:
            status_icon = '✅' if f.get('status') == 'passed' else '⚠️' if f.get('status') == 'warning' else '❌'
            lines.append(
                f"| {f.get('file_name', '-')} | "
                f"{f.get('type', '-')} | "
                f"{f.get('total', 0)} | "
                f"{f.get('passed', 0)} | "
                f"{f.get('failed', 0)} | "
                f"{f.get('line_coverage', 0):.0f}% | "
                f"{status_icon} |"
            )

        lines.extend([
            "",
            "---",
            "",
            "## 4. 关键问题",
            "",
        ])

        # 失败用例
        failed_files = [f for f in data.files if f.get('failed', 0) > 0]
        if failed_files:
            lines.append("### 失败用例")
            lines.append("")
            for f in failed_files:
                lines.append(f"- **{f.get('file_name')}**: {f.get('failed')} 个失败")
            lines.append("")

        # 低覆盖率文件
        low_coverage = [f for f in data.files if f.get('line_coverage', 0) < 90]
        if low_coverage:
            lines.append("### 低覆盖率文件 (< 90%)")
            lines.append("")
            for f in low_coverage:
                lines.append(
                    f"- **{f.get('file_name')}**: {f.get('line_coverage', 0):.1f}%"
                )
            lines.append("")

        lines.extend([
            "---",
            "",
            "## 5. 质量评估",
            "",
        ])

        # 总体结论
        if data.total_failed == 0 and data.avg_line_coverage >= 90:
            conclusion = "✅ **通过** - 所有测试通过，覆盖率达标"
        elif data.total_failed == 0:
            conclusion = "⚠️ **有条件通过** - 测试通过但覆盖率未达标"
        else:
            conclusion = "❌ **未通过** - 存在失败用例"

        lines.append(f"### 总体结论")
        lines.append("")
        lines.append(conclusion)
        lines.append("")

        # 合并建议
        lines.append("### 合并建议")
        lines.append("")
        if data.total_failed == 0 and data.avg_line_coverage >= 90:
            lines.append("✅ 建议合并到主分支")
        elif data.total_failed == 0:
            lines.append("⚠️ 建议补充测试后再合并")
        else:
            lines.append("❌ 不建议合并，请先修复失败用例")
        lines.append("")

        lines.extend([
            "---",
            "",
            "## 6. 后续行动建议",
            "",
        ])

        # 优先级建议
        if data.total_failed > 0:
            lines.append("### 高优先级")
            lines.append("- [ ] 修复所有失败用例")
            lines.append("")

        if low_coverage:
            lines.append("### 中优先级")
            lines.append("- [ ] 提高以下文件的测试覆盖率:")
            for f in low_coverage:
                lines.append(f"  - {f.get('file_name')}")
            lines.append("")

        if not failed_files and not low_coverage:
            lines.append("🎉 所有测试通过，覆盖率达标，无需后续行动。")
            lines.append("")

        # 写入文件
        content = '\n'.join(lines)
        report_path.write_text(content, encoding='utf-8')

        logger.info(f"报告已生成: {report_path}")
        return report_path

    def generate_json_report(self, data: ReportData) -> Path:
        """
        生成 JSON 格式报告

        Args:
            data: 报告数据

        Returns:
            生成的报告路径
        """
        report_path = self.output_dir / 'summary_report.json'

        report_data = {
            'project': data.project,
            'commit_id': data.commit_id,
            'branch': data.branch,
            'timestamp': data.start_time.isoformat(),
            'duration': data.duration,
            'summary': {
                'total_files': len(data.files),
                'total_cases': data.total_cases,
                'passed': data.total_passed,
                'failed': data.total_failed,
                'skipped': data.total_skipped,
                'pass_rate': data.total_passed / data.total_cases * 100 if data.total_cases > 0 else 0,
                'avg_line_coverage': data.avg_line_coverage,
                'avg_branch_coverage': data.avg_branch_coverage
            },
            'files': data.files
        }

        with open(report_path, 'w', encoding='utf-8') as f:
            json.dump(report_data, f, indent=2, ensure_ascii=False)

        logger.info(f"JSON 报告已生成: {report_path}")
        return report_path

    @staticmethod
    def _pct(part: int, whole: int) -> str:
        """计算百分比"""
        if whole == 0:
            return "0%"
        return f"{part / whole * 100:.1f}%"


def load_test_summary(summary_path: Path) -> Dict:
    """
    加载测试摘要文件

    Args:
        summary_path: 摘要文件路径

    Returns:
        摘要数据
    """
    try:
        with open(summary_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"加载摘要失败 [{summary_path}]: {e}")
        return {}


def aggregate_summaries(summary_paths: List[Path]) -> ReportData:
    """
    聚合多个测试摘要

    Args:
        summary_paths: 摘要文件路径列表

    Returns:
        聚合后的报告数据
    """
    files = []

    for path in summary_paths:
        data = load_test_summary(path)
        if not data:
            continue

        file_info = {
            'file_name': data.get('test_file', ''),
            'type': 'program' if 'program_' in str(path) else 'diff',
            'total': data.get('summary', {}).get('total', 0),
            'passed': data.get('summary', {}).get('passed', 0),
            'failed': data.get('summary', {}).get('failed', 0),
            'skipped': data.get('summary', {}).get('skipped', 0),
            'line_coverage': data.get('coverage', {}).get('line_rate', 0),
            'branch_coverage': data.get('coverage', {}).get('branch_rate', 0),
            'status': 'passed' if data.get('summary', {}).get('failed', 0) == 0 else 'failed'
        }
        files.append(file_info)

    # 创建 ReportData（需要外部提供 project/commit_id/branch）
    return files
