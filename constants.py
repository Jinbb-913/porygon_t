"""
porygon_t 常量定义模块

集中管理所有配置常量，便于维护和扩展。
"""

from enum import Enum
from pathlib import Path
from typing import Set


class Language(str, Enum):
    """支持的语言"""
    PYTHON = 'python'
    CPP = 'cpp'
    # JAVA = 'java'  # 未来扩展


class FileExtension:
    """文件扩展名常量"""
    PYTHON: Set[str] = {'.py'}
    CPP_SOURCE: Set[str] = {'.cpp', '.cc', '.cxx'}
    CPP_HEADER: Set[str] = {'.hpp', '.h'}
    CPP: Set[str] = CPP_SOURCE | CPP_HEADER
    SUPPORTED: Set[str] = PYTHON | CPP

    @classmethod
    def get_file_extension(cls, file_name: str) -> str:
        """
        获取文件扩展名

        优先匹配更长的扩展名（如 .hpp 先于 .h）
        """
        for ext in sorted(cls.SUPPORTED, key=len, reverse=True):
            if file_name.endswith(ext):
                return ext
        return Path(file_name).suffix

    @classmethod
    def is_python(cls, file_name: str) -> bool:
        """判断是否为 Python 文件"""
        return any(file_name.endswith(ext) for ext in cls.PYTHON)

    @classmethod
    def is_cpp_source(cls, file_name: str) -> bool:
        """判断是否为 C++ 源文件（头文件不单独测试）"""
        return any(file_name.endswith(ext) for ext in cls.CPP_SOURCE)

    @classmethod
    def is_cpp(cls, file_name: str) -> bool:
        """判断是否为 C++ 文件（包括头文件）"""
        return any(file_name.endswith(ext) for ext in cls.CPP)

    @classmethod
    def get_language(cls, file_name: str) -> str:
        """获取源文件语言类型"""
        if cls.is_python(file_name):
            return Language.PYTHON
        elif cls.is_cpp_source(file_name):
            return Language.CPP
        return 'unknown'


class TestFramework:
    """测试框架配置"""
    PYTHON = 'pytest'
    CPP = 'Google Test'


class CoverageTarget:
    """覆盖率目标"""
    LINE_RATE = 0.9         # 90%
    BRANCH_RATE = 0.85      # 85%
    MAX_FAILURE_RATE = 0.1  # 10%


class ConfigKey:
    """配置文件键名常量"""
    PROJECT = 'project'
    COMMIT_ID = 'commit_id'
    BRANCH = 'branch'
    PROJECT_PATH = 'project_path'
    CLAUDE_CONFIG = 'claude_config'
    TIMEOUT_SECONDS = 'timeoutSeconds'
    EXECUTION = 'execution'
    MAX_WORKERS = 'maxWorkers'
    TEST_PROGRAMS = 'test_programs'


class Defaults:
    """默认值"""
    TIMEOUT_SECONDS = 300
    MAX_WORKERS = 4
    BRANCH = 'main'
