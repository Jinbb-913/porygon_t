"""
Git 操作工具模块

提供获取 commit diff、切换分支、获取文件变更信息等功能。
"""

import logging
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger('porygon_t.git')


class GitError(Exception):
    """Git 操作错误"""
    pass


def run_git_command(
    args: List[str],
    cwd: Path,
    check: bool = True,
    capture_output: bool = True
) -> subprocess.CompletedProcess:
    """
    执行 Git 命令

    Args:
        args: Git 命令参数
        cwd: 工作目录
        check: 失败时是否抛出异常
        capture_output: 是否捕获输出

    Returns:
        命令执行结果

    Raises:
        GitError: Git 命令执行失败
    """
    cmd = ['git'] + args
    logger.debug(f"执行命令: {' '.join(cmd)}")

    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=capture_output,
            text=True,
            check=check
        )
        return result
    except subprocess.CalledProcessError as e:
        error_msg = f"Git 命令失败: {' '.join(cmd)}\n{e.stderr}"
        logger.error(error_msg)
        raise GitError(error_msg)


def checkout_branch(branch: str, project_path: Path) -> bool:
    """
    切换到指定分支

    Args:
        branch: 分支名称
        project_path: 项目路径

    Returns:
        是否成功
    """
    try:
        run_git_command(['checkout', branch], project_path)
        logger.info(f"已切换到分支: {branch}")
        return True
    except GitError:
        return False


def get_commit_diff_files(
    commit_id: str,
    project_path: Path
) -> List[Dict]:
    """
    获取指定 commit 的变更文件列表

    Args:
        commit_id: Commit 哈希
        project_path: 项目路径

    Returns:
        变更文件信息列表，每项包含:
        - change_type: 'modified', 'added', 'deleted'
        - file_path: 相对路径
        - full_path: 绝对路径
    """
    files = []

    try:
        # 检查是否有父提交（不是第一个提交）
        try:
            run_git_command(['rev-parse', f'{commit_id}^'], project_path)
            has_parent = True
        except GitError:
            has_parent = False

        # 如果是第一个提交，使用 git show；否则使用 git diff
        if has_parent:
            result = run_git_command(
                ['diff', '--name-status', f'{commit_id}^..{commit_id}'],
                project_path
            )
        else:
            # 第一个提交，使用 git show 获取变更
            result = run_git_command(
                ['show', '--name-status', '--format=', commit_id],
                project_path
            )

        for line in result.stdout.strip().split('\n'):
            if not line:
                continue

            parts = line.split('\t')
            if len(parts) < 2:
                continue

            status_code = parts[0][0].upper()
            file_path = parts[1]

            # 映射状态码
            change_map = {
                'M': 'modified',
                'A': 'added',
                'D': 'deleted',
            }
            change_type = change_map.get(status_code, 'unknown')

            full_path = project_path / file_path

            files.append({
                'change_type': change_type,
                'file_path': file_path,
                'full_path': str(full_path),
                'file_name': Path(file_path).name
            })

        logger.info(f"发现 {len(files)} 个变更文件")
        return files

    except GitError as e:
        logger.error(f"获取 diff 文件失败: {e}")
        return []


def get_diff_stat(
    commit_id: str,
    file_path: str,
    project_path: Path
) -> Dict:
    """
    获取文件变更统计

    Args:
        commit_id: Commit 哈希
        file_path: 文件路径（相对或绝对）
        project_path: 项目路径

    Returns:
        统计信息，包含 lines_added 和 lines_deleted
    """
    try:
        # 确保使用相对路径
        rel_path = Path(file_path)
        if rel_path.is_absolute():
            rel_path = rel_path.relative_to(project_path)

        # 检查是否有父提交
        try:
            run_git_command(['rev-parse', f'{commit_id}^'], project_path)
            has_parent = True
        except GitError:
            has_parent = False

        # 根据是否有父提交选择命令
        if has_parent:
            result = run_git_command(
                ['diff', '--stat', f'{commit_id}^..{commit_id}', '--', str(rel_path)],
                project_path
            )
        else:
            # 第一个提交，使用 git show
            result = run_git_command(
                ['show', '--stat', '--format=', commit_id, '--', str(rel_path)],
                project_path
            )

        line = result.stdout.strip()
        if '|' not in line:
            return {'lines_added': 0, 'lines_deleted': 0}

        # 解析 "file.py | 5 +++--" 格式
        parts = line.split('|')[1].strip().split()
        changes = parts[0]

        added = changes.count('+')
        deleted = changes.count('-')

        return {
            'lines_added': added,
            'lines_deleted': deleted
        }

    except GitError as e:
        logger.warning(f"获取 diff 统计失败: {e}")
        return {'lines_added': 0, 'lines_deleted': 0}


def get_diff_content(
    commit_id: str,
    file_path: str,
    project_path: Path
) -> str:
    """
    获取文件的具体 diff 内容

    Args:
        commit_id: Commit 哈希
        file_path: 文件路径
        project_path: 项目路径

    Returns:
        diff 内容字符串
    """
    try:
        rel_path = Path(file_path)
        if rel_path.is_absolute():
            rel_path = rel_path.relative_to(project_path)

        # 检查是否有父提交
        try:
            run_git_command(['rev-parse', f'{commit_id}^'], project_path)
            has_parent = True
        except GitError:
            has_parent = False

        # 根据是否有父提交选择命令
        if has_parent:
            result = run_git_command(
                ['diff', f'{commit_id}^..{commit_id}', '--', str(rel_path)],
                project_path
            )
        else:
            # 第一个提交，使用 git show
            result = run_git_command(
                ['show', commit_id, '--', str(rel_path)],
                project_path
            )

        return result.stdout

    except GitError as e:
        logger.error(f"获取 diff 内容失败: {e}")
        return ""


def get_file_content_at_commit(
    commit_id: str,
    file_path: str,
    project_path: Path
) -> str:
    """
    获取指定 commit 时文件的内容

    Args:
        commit_id: Commit 哈希
        file_path: 文件路径
        project_path: 项目路径

    Returns:
        文件内容
    """
    try:
        rel_path = Path(file_path)
        if rel_path.is_absolute():
            rel_path = rel_path.relative_to(project_path)

        result = run_git_command(
            ['show', f'{commit_id}:{rel_path}'],
            project_path
        )

        return result.stdout

    except GitError as e:
        logger.error(f"获取文件内容失败: {e}")
        return ""


def is_valid_git_repo(path: Path) -> bool:
    """
    检查路径是否是有效的 Git 仓库

    Args:
        path: 待检查路径

    Returns:
        是否是有效仓库
    """
    git_dir = path / '.git'
    if not git_dir.exists():
        return False

    try:
        run_git_command(['rev-parse', '--git-dir'], path)
        return True
    except GitError:
        return False
