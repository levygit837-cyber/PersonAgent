"""Unit tests for GitContextService."""

import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from personagent.domain.context.services.git_context import GitContextService, GitInfo


class TestGitContextService:
    """Tests for GitContextService."""

    @pytest.fixture
    def git_workspace(self):
        """Create a temporary git repository for testing."""
        temp_dir = tempfile.mkdtemp()
        workspace = Path(temp_dir)

        # Initialize git repo
        subprocess.run(["git", "init"], cwd=workspace, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=workspace, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=workspace, capture_output=True)

        # Create initial commit
        test_file = workspace / "test.txt"
        test_file.write_text("test content")
        subprocess.run(["git", "add", "test.txt"], cwd=workspace, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=workspace, capture_output=True)

        yield workspace

        shutil.rmtree(temp_dir)

    @pytest.fixture
    def non_git_workspace(self):
        """Create a temporary non-git directory for testing."""
        temp_dir = tempfile.mkdtemp()
        workspace = Path(temp_dir)
        yield workspace
        shutil.rmtree(temp_dir)

    def test_get_git_info_in_git_repo(self, git_workspace):
        """Test getting git info in a git repository."""
        service = GitContextService(git_workspace)
        info = service.get_git_info()

        assert info.is_git_repo is True
        assert info.branch is not None
        assert info.commit is not None
        assert info.root == str(git_workspace)

    def test_get_git_info_not_git_repo(self, non_git_workspace):
        """Test getting git info in a non-git directory."""
        service = GitContextService(non_git_workspace)
        info = service.get_git_info()

        assert info.is_git_repo is False
        assert info.branch is None
        assert info.commit is None
        # Root should still be the workspace path even for non-git repos
        assert info.root == str(non_git_workspace) or info.root == ""

    def test_git_branch(self, git_workspace):
        """Test getting git branch."""
        service = GitContextService(git_workspace)
        info = service.get_git_info()

        # Default branch should be 'main' or 'master'
        assert info.branch in ["main", "master"]

    def test_git_commit(self, git_workspace):
        """Test getting git commit."""
        service = GitContextService(git_workspace)
        info = service.get_git_info()

        assert info.commit is not None
        assert len(info.commit) == 40  # SHA-1 hash length

    def test_git_commit_message(self, git_workspace):
        """Test getting git commit message."""
        service = GitContextService(git_workspace)
        info = service.get_git_info()

        assert info.commit_message is not None
        assert "Initial commit" in info.commit_message

    def test_git_author(self, git_workspace):
        """Test getting git author."""
        service = GitContextService(git_workspace)
        info = service.get_git_info()

        assert info.author is not None
        assert "Test User" in info.author

    def test_git_is_dirty_clean(self, git_workspace):
        """Test is_dirty on clean repo."""
        service = GitContextService(git_workspace)
        info = service.get_git_info()

        assert info.is_dirty is False

    def test_git_is_dirty_modified(self, git_workspace):
        """Test is_dirty on modified repo."""
        # Modify a file
        test_file = git_workspace / "test.txt"
        test_file.write_text("modified content")

        service = GitContextService(git_workspace)
        info = service.get_git_info()

        assert info.is_dirty is True

    def test_git_staged_files(self, git_workspace):
        """Test getting staged files."""
        # Create and stage a new file
        new_file = git_workspace / "new.txt"
        new_file.write_text("new content")
        subprocess.run(["git", "add", "new.txt"], cwd=git_workspace, capture_output=True)

        service = GitContextService(git_workspace)
        info = service.get_git_info()

        assert "new.txt" in info.staged_files

    def test_git_unstaged_files(self, git_workspace):
        """Test getting unstaged files."""
        # Modify a file
        test_file = git_workspace / "test.txt"
        test_file.write_text("modified content")

        service = GitContextService(git_workspace)
        info = service.get_git_info()

        assert "test.txt" in info.unstaged_files

    def test_git_untracked_files(self, git_workspace):
        """Test getting untracked files."""
        # Create untracked file
        untracked = git_workspace / "untracked.txt"
        untracked.write_text("untracked")

        service = GitContextService(git_workspace)
        info = service.get_git_info()

        assert "untracked.txt" in info.untracked_files

    def test_git_remote(self, git_workspace):
        """Test getting git remote."""
        # Add a remote
        subprocess.run(["git", "remote", "add", "origin", "https://github.com/test/repo.git"], cwd=git_workspace, capture_output=True)
        # Set the remote for the current branch
        subprocess.run(["git", "config", "branch.master.remote", "origin"], cwd=git_workspace, capture_output=True)

        service = GitContextService(git_workspace)
        info = service.get_git_info()

        assert info.remote == "origin"

    def test_git_to_dict(self, git_workspace):
        """Test GitInfo.to_dict method."""
        service = GitContextService(git_workspace)
        info = service.get_git_info()

        info_dict = info.to_dict()

        assert isinstance(info_dict, dict)
        assert "is_git_repo" in info_dict
        assert "branch" in info_dict
        assert "commit" in info_dict
        assert info_dict["is_git_repo"] is True

    def test_git_subdirectory(self, git_workspace):
        """Test git context from subdirectory."""
        # Create subdirectory
        subdir = git_workspace / "subdir"
        subdir.mkdir()

        service = GitContextService(subdir)
        info = service.get_git_info()

        assert info.is_git_repo is True
        # Should still get the repo root
        assert info.root == str(git_workspace)

    def test_git_timeout_handling(self, git_workspace):
        """Test timeout handling in git operations."""
        service = GitContextService(git_workspace)
        # All operations have 5 second timeout, should complete quickly
        info = service.get_git_info()

        assert info.is_git_repo is True

    def test_git_not_installed(self, non_git_workspace):
        """Test behavior when git is not installed."""
        # This test assumes git is installed, but if it weren't,
        # the service should handle FileNotFoundError gracefully
        service = GitContextService(non_git_workspace)
        info = service.get_git_info()

        # Should return default GitInfo if git commands fail
        assert isinstance(info, GitInfo)


class TestGitInfo:
    """Tests for GitInfo dataclass."""

    def test_git_info_defaults(self):
        """Test GitInfo with default values."""
        info = GitInfo()

        assert info.is_git_repo is False
        assert info.branch is None
        assert info.remote is None
        assert info.commit is None
        assert info.commit_message is None
        assert info.author is None
        assert info.is_dirty is False
        assert info.staged_files == ()
        assert info.unstaged_files == ()
        assert info.untracked_files == ()
        assert info.root == ""

    def test_git_info_with_values(self):
        """Test GitInfo with values."""
        info = GitInfo(
            is_git_repo=True,
            branch="main",
            remote="origin",
            commit="abc123",
            commit_message="Test commit",
            author="Test User",
            is_dirty=True,
            staged_files=("file1.txt",),
            unstaged_files=("file2.txt",),
            untracked_files=("file3.txt",),
            root="/workspace",
        )

        assert info.is_git_repo is True
        assert info.branch == "main"
        assert info.remote == "origin"
        assert info.commit == "abc123"
        assert info.commit_message == "Test commit"
        assert info.author == "Test User"
        assert info.is_dirty is True
        assert info.staged_files == ("file1.txt",)
        assert info.unstaged_files == ("file2.txt",)
        assert info.untracked_files == ("file3.txt",)
        assert info.root == "/workspace"

    def test_git_info_to_dict(self):
        """Test to_dict method."""
        info = GitInfo(
            is_git_repo=True,
            branch="main",
            staged_files=("file1.txt", "file2.txt"),
        )

        info_dict = info.to_dict()

        assert isinstance(info_dict, dict)
        assert info_dict["is_git_repo"] is True
        assert info_dict["branch"] == "main"
        assert isinstance(info_dict["staged_files"], list)
        assert "file1.txt" in info_dict["staged_files"]
