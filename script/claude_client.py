"""
Claude Code 调用客户端

提供调用 Claude Code 生成测试代码和报告的功能。
"""

import logging
import os
import sys
import subprocess
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger('porygon_t.claude')


class ClaudeError(Exception):
    """Claude 调用错误"""
    pass


class ClaudeClient:
    """Claude Code 客户端"""

    def __init__(
        self,
        project_path: Path,
        prompt_path: Optional[Path] = None,
        timeout: int = 300
    ):
        """
        初始化客户端

        Args:
            project_path: 项目路径
            prompt_path: 系统提示词文件路径
            timeout: 默认超时时间（秒）
        """
        self.project_path = project_path
        self.prompt_path = prompt_path
        self.timeout = timeout

    def _embed_files_in_prompt(self, prompt: str, files: Optional[List[Path]] = None) -> str:
        """
        将文件内容嵌入到 prompt 中

        Args:
            prompt: 原始提示词
            files: 需要嵌入的文件列表

        Returns:
            嵌入文件内容后的完整 prompt
        """
        if not files:
            return prompt

        sections = [prompt, "", "=" * 60, "参考文件内容", "=" * 60, ""]

        for file_path in files:
            if not file_path or not file_path.exists():
                logger.warning(f"文件不存在，跳过: {file_path}")
                continue

            try:
                content = file_path.read_text(encoding='utf-8')
                sections.append(f"\n--- 文件: {file_path} ---\n")
                sections.append(f"```python\n{content}\n```\n")
            except Exception as e:
                logger.warning(f"读取文件失败 {file_path}: {e}")
                continue

        return "\n".join(sections)

    def call(
        self,
        prompt: str,
        files: Optional[List[Path]] = None,
        output_file: Optional[Path] = None
    ) -> str:
        """
        调用 Claude Code

        Args:
            prompt: 提示词
            files: 需要引用的文件列表（内容将嵌入到 prompt 中）
            output_file: 输出文件路径（可选）

        Returns:
            Claude 的响应内容

        Raises:
            ClaudeError: 调用失败
        """
        # 将文件内容嵌入到 prompt 中
        full_prompt = self._embed_files_in_prompt(prompt, files)

        logger.info(f"调用 Claude: {prompt[:50]}...")
        if files:
            logger.info(f"嵌入文件: {[str(f) for f in files if f and f.exists()]}")

        try:
            # 公司内网一般在linux使用
            if sys.platform == "win32":
                cmd = ['claude', '-p']
                shell = True
            else:
                cmd = ['ccr', 'code', '-p']
                shell = False

            # 添加系统提示词
            if self.prompt_path and self.prompt_path.exists():
                cmd.extend(['--system-prompt', str(self.prompt_path)])

            logger.debug(f"执行命令: {' '.join(cmd)}")

            # 设置环境变量确保 UTF-8 编码
            env = os.environ.copy()
            env['PYTHONIOENCODING'] = 'utf-8'
            env['LANG'] = 'en_US.UTF-8'

            # 通过 stdin 传递 prompt 内容
            result = subprocess.run(
                cmd,
                cwd=self.project_path,
                input=full_prompt,
                capture_output=True,
                text=True,
                encoding='utf-8',  # 明确指定编码
                errors='replace',  # 遇到解码错误时替换而不是崩溃
                timeout=self.timeout,
                shell=shell,
                env=env
            )

            if result.returncode != 0:
                error_msg = f"Claude 调用失败: {result.stderr}"
                logger.error(error_msg)
                raise ClaudeError(error_msg)

            output = result.stdout

            # 保存到文件
            if output_file:
                output_file.parent.mkdir(parents=True, exist_ok=True)
                with open(output_file, 'w', encoding='utf-8') as f:
                    f.write(output)
                logger.info(f"输出已保存: {output_file}")

            return output

        except subprocess.TimeoutExpired as e:
            raise ClaudeError(f"Claude 调用超时 ({self.timeout}s)") from e
        except Exception as e:
            raise ClaudeError(f"Claude 调用异常: {e}") from e

    def generate_test_plan(
        self,
        target_file: Path,
        target_type: str,  # 'program' 或 'diff'
        config: Dict,
        output_file: Path
    ) -> bool:
        """
        生成测试方案

        Args:
            target_file: 被测文件
            target_type: 目标类型
            config: 配置信息
            output_file: 输出文件

        Returns:
            是否成功
        """
        # 构建提示词
        prompt_lines = [
            "请为以下 Python 文件生成详细的测试方案文档。",
            "",
            f"被测文件: {target_file}",
            f"目标类型: {target_type}",
            "",
            "请分析文件内容并生成包含以下部分的测试方案:",
            "1. 被测程序/变更分析",
            "2. 测试目标定义（覆盖率目标）",
            "3. 测试用例设计（正向、边界、异常、回归）",
            "",
        ]

        if target_type == 'program' and config.get('issues'):
            prompt_lines.append("用户指定的关注点:")
            for issue in config['issues']:
                prompt_lines.append(f"- {issue}")
            prompt_lines.append("")

        if target_type == 'diff' and config.get('diff_info'):
            diff_info = config['diff_info']
            prompt_lines.append("变更信息:")
            prompt_lines.append(f"- Commit: {diff_info.get('commit_id')}")
            prompt_lines.append(f"- 类型: {diff_info.get('change_type')}")
            prompt_lines.append(f"- 新增行数: {diff_info.get('lines_added')}")
            prompt_lines.append(f"- 删除行数: {diff_info.get('lines_deleted')}")
            prompt_lines.append("")

        prompt_lines.append("请使用 Markdown 格式输出测试方案文档。")

        prompt = "\n".join(prompt_lines)

        try:
            self.call(
                prompt=prompt,
                files=[target_file],
                output_file=output_file
            )
            return True
        except ClaudeError as e:
            logger.error(f"生成测试方案失败: {e}")
            return False

    def generate_test_code(
        self,
        target_file: Path,
        test_plan_file: Path,
        existing_test_file: Optional[Path],
        output_file: Path
    ) -> bool:
        """
        生成测试代码

        Args:
            target_file: 被测文件
            test_plan_file: 测试方案文件
            existing_test_file: 已有测试文件（用于增量更新）
            output_file: 输出文件

        Returns:
            是否成功
        """
        # 计算相对于项目根目录的模块导入路径
        try:
            rel_path = target_file.relative_to(self.project_path)
            # 去掉 .py 扩展名，将路径分隔符替换为点
            module_path = str(rel_path.with_suffix('')).replace('\\', '.').replace('/', '.')
        except ValueError:
            module_path = target_file.stem

        prompt_lines = [
            "请根据测试方案生成 pytest 测试代码。",
            "",
            f"被测文件: {target_file}",
            f"模块导入路径: {module_path}",
            "",
            "要求:",
            "1. 使用 pytest 框架",
            "2. 每个测试函数包含清晰的 docstring",
            "3. 包含必要的 fixtures",
            "4. 行覆盖率目标 >= 90%",
            "5. 分支覆盖率目标 >= 85%",
            f"6. 导入被测模块时使用: from {module_path} import xxx",
            "7. 不要使用完整的文件系统路径作为导入前缀",
            "",
        ]

        if existing_test_file and existing_test_file.exists():
            prompt_lines.append("已有测试文件，请在此基础上增量更新:")
            prompt_lines.append(str(existing_test_file))
            prompt_lines.append("")

        prompt_lines.append("只输出测试代码，不要其他解释。")

        prompt = "\n".join(prompt_lines)

        # 构建文件列表
        files = [target_file, test_plan_file]
        if existing_test_file and existing_test_file.exists():
            files.append(existing_test_file)

        try:
            output = self.call(prompt=prompt, files=files)

            # 提取代码块
            code = self._extract_code_block(output)

            # 保存到文件
            output_file.parent.mkdir(parents=True, exist_ok=True)
            output_file.write_text(code, encoding='utf-8')

            logger.info(f"测试代码已生成: {output_file}")
            return True

        except ClaudeError as e:
            logger.error(f"生成测试代码失败: {e}")
            return False

    def generate_report(
        self,
        summary_files: List[Path],
        coverage_files: List[Path],
        output_file: Path
    ) -> bool:
        """
        生成综合分析报告

        Args:
            summary_files: 所有测试摘要文件
            coverage_files: 覆盖率文件
            output_file: 输出文件

        Returns:
            是否成功
        """
        prompt_lines = [
            "请根据所有测试结果生成综合测试报告。",
            "",
            "包含以下内容:",
            "1. 执行概览（测试时间、范围、配置）",
            "2. 总体统计（用例数、通过率、覆盖率）",
            "3. 文件级汇总表",
            "4. 关键问题（失败用例、低覆盖率文件）",
            "5. 质量评估（总体结论、合并建议）",
            "6. 后续行动建议（优先级排序）",
            "",
            "使用 Markdown 格式输出。",
        ]

        prompt = "\n".join(prompt_lines)

        all_files = summary_files + coverage_files

        try:
            self.call(
                prompt=prompt,
                files=all_files if all_files else None,
                output_file=output_file
            )
            return True
        except ClaudeError as e:
            logger.error(f"生成报告失败: {e}")
            return False

    def _extract_code_block(self, text: str) -> str:
        """从 Markdown 响应中提取 Python 代码块"""
        lines = text.split('\n')
        in_code_block = False
        code_lines = []

        for line in lines:
            if line.strip().startswith('```python'):
                in_code_block = True
                continue
            elif line.strip() == '```':
                in_code_block = False
                continue
            if in_code_block:
                code_lines.append(line)

        return '\n'.join(code_lines) if code_lines else text
