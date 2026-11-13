"""
Cross-Repo Guardian Orchestrator.
Coordinates Excel rule lookup, GitHub interaction, AST/LLM analysis, and notifications.
"""

import logging
from typing import List, Optional
from src.analyzer_agent import DependencyAnalyzerAgent
from src.config import Config, load_dependency_rules, find_matching_rules, matches_git_pattern
from src.github_client import GitHubClient
from src.repo_analyzer import RepoAnalyzer
from src.models import (
    AnalysisReport,
    ChangedJavaFile,
    DependentTargetFile,
    ImpactFinding,
    RepoDependencyRule,
    RepoArchitectureSummary,
)
from src.notifier import generate_pr_comment_markdown, write_step_summary, send_slack_notification

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("Guardian")


class CrossRepoGuardian:
    def __init__(self, excel_path: Optional[str] = None, github_token: Optional[str] = None):
        self.excel_path = excel_path
        self.client = GitHubClient(token=github_token)
        self.agent = DependencyAnalyzerAgent()
        self.repo_analyzer = RepoAnalyzer(self.client)

    def run_check(
        self,
        source_repo: str,
        pr_number: Optional[int] = None,
        commit_sha: Optional[str] = None,
        changed_files_override: Optional[List[ChangedJavaFile]] = None,
        target_files_override: Optional[List[DependentTargetFile]] = None,
    ) -> AnalysisReport:
        """
        Executes the cross-repo dependency check.
        Can run with live GitHub API or with provided in-memory test overrides.
        """
        logger.info(f"Starting Cross-Repo Dependency Check for repo: {source_repo}")

        # 1. Load rules from Excel
        all_rules = load_dependency_rules(self.excel_path)
        matching_rules = find_matching_rules(source_repo, all_rules)

        if not matching_rules:
            logger.info(f"No dependent repository rules configured in Excel for {source_repo}.")
            return AnalysisReport(
                source_repo=source_repo,
                target_repos_checked=[],
                changed_java_files_count=0,
                has_breaking_changes=False,
                findings=[],
                markdown_summary="No dependency rules registered for this repository.",
            )

        logger.info(f"Found {len(matching_rules)} dependency mapping rule(s) for {source_repo}.")

        # 2. Get changed Java files
        if changed_files_override is not None:
            changed_java_files = changed_files_override
        elif pr_number is not None:
            changed_java_files = self.client.get_pull_request_files(source_repo, pr_number)
        elif commit_sha is not None:
            changed_java_files = self.client.get_commit_files(source_repo, commit_sha)
        else:
            changed_java_files = []

        logger.info(f"Found {len(changed_java_files)} changed Java file(s) in source repo.")
        if not changed_java_files:
            return AnalysisReport(
                source_repo=source_repo,
                target_repos_checked=[r.target_repo for r in matching_rules],
                changed_java_files_count=0,
                has_breaking_changes=False,
                findings=[],
                markdown_summary="No Java files were modified in this event.",
            )

        # 3. For each matching rule, check target repository
        all_findings: List[ImpactFinding] = []
        target_repos_checked = set()
        repo_architectures = {}

        # Analyze source repo architecture using GitHub Repo Analyzer integration
        try:
            repo_architectures[source_repo] = self.repo_analyzer.analyze_repository(
                source_repo, role_hint="Service Provider / API Producer"
            )
        except Exception as e:
            logger.debug(f"Source repo architecture analysis fallback: {e}")

        for rule in matching_rules:
            target_repo = rule.target_repo
            target_repos_checked.add(target_repo)
            logger.info(f"Evaluating rule {rule.pair_id}: {source_repo} -> {target_repo} ({rule.dependency_type})")

            # Analyze target repo architecture
            if target_repo not in repo_architectures:
                try:
                    repo_architectures[target_repo] = self.repo_analyzer.analyze_repository(
                        target_repo,
                        branch=rule.target_branch,
                        role_hint=f"Service Consumer ({rule.dependency_type})",
                    )
                except Exception as e:
                    logger.debug(f"Target repo architecture analysis fallback: {e}")

            # Filter source files matching rule's source_file_pattern
            relevant_source_files = [
                cf for cf in changed_java_files
                if any(matches_git_pattern(cf.path, pat) for pat in rule.source_file_pattern)
            ]

            if not relevant_source_files:
                logger.info(f"No changed files matched source pattern {rule.source_file_pattern} for rule {rule.pair_id}")
                continue

            # Fetch candidate target Java files
            candidate_target_files: List[DependentTargetFile] = []
            if target_files_override:
                candidate_target_files = [tf for tf in target_files_override if tf.repo == target_repo]
            else:
                target_paths = self.client.list_repo_java_files(
                    target_repo, branch=rule.target_branch, patterns=rule.target_file_pattern
                )
                logger.info(f"Discovered {len(target_paths)} candidate Java file(s) in target repo {target_repo}")

                for path in target_paths[:20]:  # Cap scanning batch for performance
                    content = self.client.get_file_content(target_repo, path, ref=rule.target_branch)
                    if content:
                        candidate_target_files.append(
                            DependentTargetFile(repo=target_repo, path=path, content=content)
                        )

            # Analyze cross-file impact
            for src_file in relevant_source_files:
                for tgt_file in candidate_target_files:
                    finding = self.agent.analyze_cross_repo_impact(
                        source_repo=source_repo,
                        target_repo=target_repo,
                        rule=rule,
                        changed_source_file=src_file,
                        target_file=tgt_file,
                    )
                    if finding and finding.is_impacted:
                        logger.warning(
                            f"IMPACT DETECTED: {src_file.path} breaks {tgt_file.path} in {target_repo}!"
                        )
                        all_findings.append(finding)

        has_breaking = any(f.severity in ("CRITICAL", "HIGH") for f in all_findings)

        report = AnalysisReport(
            source_repo=source_repo,
            target_repos_checked=list(target_repos_checked),
            changed_java_files_count=len(changed_java_files),
            has_breaking_changes=has_breaking,
            findings=all_findings,
            repo_architectures=repo_architectures,
        )
        report.markdown_summary = generate_pr_comment_markdown(report)

        # 4. Dispatch Notifications
        # Write to GitHub Step Summary
        write_step_summary(report)

        # Post to Pull Request comment if running in PR context
        if pr_number is not None and Config.GITHUB_PAT:
            try:
                self.client.post_pr_comment(source_repo, pr_number, report.markdown_summary)
                logger.info(f"Posted review comment on PR #{pr_number}")
            except Exception as e:
                logger.error(f"Failed to post PR comment: {e}")

        # Post to Slack if configured
        if Config.SLACK_WEBHOOK_URL:
            send_slack_notification(Config.SLACK_WEBHOOK_URL, report)

        return report
