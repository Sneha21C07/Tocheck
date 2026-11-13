"""
Configuration and Excel Dependency Matrix Loader.
"""

import os
import re
from pathlib import Path
from typing import List, Optional, Any
import openpyxl
from dotenv import load_dotenv

from src.models import RepoDependencyRule

# Load environment variables from .env
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def matches_git_pattern(path: str, pattern: str) -> bool:
    """
    Evaluates whether a relative path matches a git glob pattern (including **).
    """
    path = path.replace("\\", "/").strip("/")
    pat = pattern.replace("\\", "/").strip("/")
    if pat == "**" or pat == "**/*":
        return True
    if "/" not in pat:
        return re.search(pat.replace("*", ".*"), path, re.IGNORECASE) is not None

    pat = pat.replace("/**/", "/<DIR_WILDCARD>/")
    if pat.startswith("**/"):
        pat = "<START_DIR_WILDCARD>" + pat[3:]
    if pat.endswith("/**"):
        pat = pat[:-3] + "<END_DIR_WILDCARD>"

    escaped = re.escape(pat)
    escaped = escaped.replace(re.escape("<START_DIR_WILDCARD>"), "(?:.*/)?")
    escaped = escaped.replace(re.escape("/<DIR_WILDCARD>/"), "(?:/|/.*/)")
    escaped = escaped.replace(re.escape("<END_DIR_WILDCARD>"), "(?:/.*)?")
    escaped = escaped.replace(r"\*", "[^/]*")
    return bool(re.match("^" + escaped + "$", path, re.IGNORECASE))


class Config:
    GITHUB_PAT: str = os.getenv("GITHUB_PAT", "")
    EXCEL_MAPPING_PATH: Path = Path(os.getenv("EXCEL_MAPPING_PATH", str(BASE_DIR / "repo_dependency_mapping.xlsx")))
    OPENAI_API_KEY: Optional[str] = os.getenv("OPENAI_API_KEY")
    GEMINI_API_KEY: Optional[str] = os.getenv("GEMINI_API_KEY")
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "auto")  # auto, openai, gemini, fallback
    SLACK_WEBHOOK_URL: Optional[str] = os.getenv("SLACK_WEBHOOK_URL")


def parse_pattern_list(raw_value: Optional[str]) -> List[str]:
    """Split comma or newline separated glob patterns into clean list."""
    if not raw_value:
        return ["**/*.java"]
    items = [item.strip() for item in raw_value.replace("\n", ",").split(",") if item.strip()]
    return items if items else ["**/*.java"]


def load_dependency_rules(excel_path: Optional[Any] = None) -> List[RepoDependencyRule]:
    """
    Reads the repo_dependency_mapping.xlsx workbook and returns typed rules.
    """
    if excel_path is None:
        path = Config.EXCEL_MAPPING_PATH
    elif isinstance(excel_path, str):
        path = Path(excel_path)
    else:
        path = excel_path

    if not path.exists():
        raise FileNotFoundError(f"Dependency mapping Excel file not found at: {path}")

    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb.active

    rules: List[RepoDependencyRule] = []

    # Map column headers to index
    headers = [cell.value for cell in ws[1]]
    header_map = {str(name).strip(): idx for idx, name in enumerate(headers) if name is not None}

    def get_val(row, field_name: str, default: str = ""):
        idx = header_map.get(field_name)
        if idx is None or idx >= len(row):
            return default
        val = row[idx].value
        return str(val).strip() if val is not None else default

    for row in ws.iter_rows(min_row=2):
        if not any(cell.value for cell in row):
            continue

        pair_id = get_val(row, "Pair_ID")
        source_repo = get_val(row, "Source_Repo")
        target_repo = get_val(row, "Target_Repo")

        if not source_repo or not target_repo:
            continue

        source_branch = get_val(row, "Source_Branch", "main")
        source_patterns = parse_pattern_list(get_val(row, "Source_File_Pattern", "**/*.java"))
        target_branch = get_val(row, "Target_Branch", "main")
        target_patterns = parse_pattern_list(get_val(row, "Target_File_Pattern", "**/*.java"))
        dependency_type = get_val(row, "Dependency_Type", "SHARED_DTO")
        severity_level = get_val(row, "Severity_Level", "HIGH")
        notification_channel = get_val(row, "Notification_Channel", "PR_COMMENT")
        auto_block_pr = get_val(row, "Auto_Block_PR", "FALSE").upper() == "TRUE"
        owner_team = get_val(row, "Owner_Team", "Platform-Team")
        description = get_val(row, "Description", "")

        rules.append(
            RepoDependencyRule(
                pair_id=pair_id,
                source_repo=source_repo,
                source_branch=source_branch,
                source_file_pattern=source_patterns,
                target_repo=target_repo,
                target_branch=target_branch,
                target_file_pattern=target_patterns,
                dependency_type=dependency_type,
                severity_level=severity_level,
                notification_channel=notification_channel,
                auto_block_pr=auto_block_pr,
                owner_team=owner_team,
                description=description,
            )
        )

    return rules


def find_matching_rules(source_repo: str, rules: List[RepoDependencyRule]) -> List[RepoDependencyRule]:
    """Find all rules where the source repo matches (case-insensitive)."""
    norm_source = source_repo.lower().strip()
    return [
        rule for rule in rules
        if rule.source_repo.lower().strip() == norm_source
        or rule.source_repo.lower().strip().endswith(f"/{norm_source.split('/')[-1]}")
    ]
