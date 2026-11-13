"""
GitHub REST API Client for Cross-Repository Operations.
Uses GITHUB_PAT for authenticated repository traversal and pull request commenting.
"""

import base64
from typing import Dict, List, Optional, Any
import requests
from src.config import Config, matches_git_pattern
from src.models import ChangedJavaFile


class GitHubClient:
    def __init__(self, token: Optional[str] = None):
        self.token = token or Config.GITHUB_PAT
        self.base_url = "https://api.github.com"
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/vnd.github+json",
                "User-Agent": "CrossRepo-Dependency-Guardian/1.0",
            }
        )
        if self.token:
            self.session.headers["Authorization"] = f"Bearer {self.token}"

    def _split_repo(self, repo_identifier: str) -> tuple[str, str]:
        parts = repo_identifier.strip().split("/")
        if len(parts) >= 2:
            return parts[-2], parts[-1]
        raise ValueError(f"Invalid repository identifier: {repo_identifier}. Expected 'owner/repo'")

    def get_repo_metadata(self, repo: str) -> Dict[str, Any]:
        """Fetch general repository information and metadata."""
        owner, repo_name = self._split_repo(repo)
        url = f"{self.base_url}/repos/{owner}/{repo_name}"
        try:
            response = self.session.get(url)
            if response.status_code == 200:
                return response.json()
        except Exception:
            pass
        return {}

    def get_tree(self, repo: str, branch: str = "main") -> List[Dict[str, Any]]:
        """Fetch recursive git tree for repository."""
        owner, repo_name = self._split_repo(repo)
        url = f"{self.base_url}/repos/{owner}/{repo_name}/git/trees/{branch}?recursive=1"
        try:
            response = self.session.get(url)
            if response.status_code == 200:
                return response.json().get("tree", [])
        except Exception:
            pass
        return []

    def get_pull_request_files(self, repo: str, pr_number: int) -> List[ChangedJavaFile]:
        """Fetch all changed files in a pull request."""
        owner, repo_name = self._split_repo(repo)
        url = f"{self.base_url}/repos/{owner}/{repo_name}/pulls/{pr_number}/files"
        response = self.session.get(url)
        response.raise_for_status()
        files_data = response.json()

        changed_files: List[ChangedJavaFile] = []
        for f in files_data:
            filename = f.get("filename", "")
            if not filename.endswith(".java"):
                continue

            status = f.get("status", "modified")
            patch = f.get("patch", "")
            raw_url = f.get("raw_url", "")

            # Fetch new content
            new_content = None
            if raw_url and status != "removed":
                try:
                    c_res = self.session.get(raw_url)
                    if c_res.status_code == 200:
                        new_content = c_res.text
                except Exception:
                    pass

            changed_files.append(
                ChangedJavaFile(
                    path=filename,
                    status=status,
                    diff=patch,
                    new_content=new_content,
                )
            )

        return changed_files

    def get_commit_files(self, repo: str, commit_sha: str) -> List[ChangedJavaFile]:
        """Fetch changed files from a specific commit (e.g. from a push event)."""
        owner, repo_name = self._split_repo(repo)
        url = f"{self.base_url}/repos/{owner}/{repo_name}/commits/{commit_sha}"
        response = self.session.get(url)
        response.raise_for_status()
        commit_data = response.json()

        changed_files: List[ChangedJavaFile] = []
        for f in commit_data.get("files", []):
            filename = f.get("filename", "")
            if not filename.endswith(".java"):
                continue

            changed_files.append(
                ChangedJavaFile(
                    path=filename,
                    status=f.get("status", "modified"),
                    diff=f.get("patch", ""),
                )
            )

        return changed_files

    def get_file_content(self, repo: str, path: str, ref: str = "main") -> Optional[str]:
        """Retrieve raw file content from a repository branch or sha."""
        owner, repo_name = self._split_repo(repo)
        url = f"{self.base_url}/repos/{owner}/{repo_name}/contents/{path}?ref={ref}"
        response = self.session.get(url)
        if response.status_code != 200:
            return None

        data = response.json()
        encoding = data.get("encoding")
        content_str = data.get("content")

        if encoding == "base64" and content_str:
            return base64.b64decode(content_str).decode("utf-8", errors="replace")

        return None

    def list_repo_java_files(
        self, repo: str, branch: str = "main", patterns: Optional[List[str]] = None
    ) -> List[str]:
        """
        Recursively lists all .java file paths in the repository matching any given glob pattern.
        """
        owner, repo_name = self._split_repo(repo)
        url = f"{self.base_url}/repos/{owner}/{repo_name}/git/trees/{branch}?recursive=1"
        response = self.session.get(url)
        if response.status_code != 200:
            return []

        tree = response.json().get("tree", [])
        patterns = patterns or ["**/*.java"]

        matched_paths: List[str] = []
        for node in tree:
            if node.get("type") == "blob":
                path = node.get("path", "")
                if path.endswith(".java"):
                    # Check pattern match
                    if any(matches_git_pattern(path, pat) for pat in patterns):
                        matched_paths.append(path)

        return matched_paths

    def post_pr_comment(self, repo: str, pr_number: int, comment_markdown: str) -> bool:
        """Post a comment to a GitHub Pull Request."""
        owner, repo_name = self._split_repo(repo)
        url = f"{self.base_url}/repos/{owner}/{repo_name}/issues/{pr_number}/comments"
        payload = {"body": comment_markdown}
        response = self.session.post(url, json=payload)
        return response.status_code in (200, 201)
