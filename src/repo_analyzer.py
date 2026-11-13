"""
Repository Architecture Analyzer Module.
Implements the inspection, stack discovery, and component breakdown
originally defined in github-repo-analyzer for both source and target repositories.
"""

import logging
from typing import Dict, List, Optional, Any
from src.github_client import GitHubClient
from src.models import RepoArchitectureSummary

logger = logging.getLogger(__name__)


class RepoAnalyzer:
    """Analyzes remote repository metadata, build manifests, and component architecture."""

    def __init__(self, client: GitHubClient):
        self.client = client

    def analyze_repository(
        self,
        repo: str,
        branch: str = "main",
        role_hint: str = "Participant",
    ) -> RepoArchitectureSummary:
        """
        Inspects repository metadata, build files, and git tree to produce
        an architectural summary of the codebase.
        """
        meta = self.client.get_repo_metadata(repo)
        description = meta.get("description") or "Microservice repository"
        def_branch = meta.get("default_branch") or branch
        primary_lang = meta.get("language") or "Java"
        topics = meta.get("topics") or []

        # Inspect build manifests
        build_tool = "Maven"
        frameworks = set()

        pom_content = self.client.get_file_content(repo, "pom.xml", ref=def_branch)
        gradle_content = self.client.get_file_content(repo, "build.gradle", ref=def_branch)

        manifest_text = (pom_content or "") + (gradle_content or "")
        if gradle_content and not pom_content:
            build_tool = "Gradle"
        elif pom_content:
            build_tool = "Maven"

        if manifest_text:
            m_lower = manifest_text.lower()
            if "spring-boot" in m_lower:
                frameworks.add("Spring Boot")
            if "openfeign" in m_lower or "spring-cloud-starter-openfeign" in m_lower:
                frameworks.add("Spring Cloud OpenFeign")
            if "kafka" in m_lower:
                frameworks.add("Apache Kafka")
            if "spring-web" in m_lower or "spring-boot-starter-web" in m_lower:
                frameworks.add("Spring Web MVC / REST")
            if "grpc" in m_lower:
                frameworks.add("gRPC")
            if "jackson" in m_lower:
                frameworks.add("Jackson Databind")
            if "lombok" in m_lower:
                frameworks.add("Project Lombok")

        if not frameworks:
            frameworks.add("Spring Boot")
            frameworks.add("Spring Web MVC")

        # Discover key directory components
        key_dirs = set()
        tree = self.client.get_tree(repo, branch=def_branch)
        for node in tree:
            path = node.get("path", "")
            if path.startswith("src/main/java/"):
                parts = path.split("/")
                if len(parts) >= 5:
                    key_dirs.add("/".join(parts[:5]))

        return RepoArchitectureSummary(
            repo_name=repo,
            description=description,
            default_branch=def_branch,
            primary_language=primary_lang,
            topics=topics,
            build_tool=build_tool,
            frameworks=sorted(list(frameworks)),
            key_directories=sorted(list(key_dirs))[:5],
            role_in_contract=role_hint,
        )
