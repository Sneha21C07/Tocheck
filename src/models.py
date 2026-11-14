"""
Data models for Cross-Repository Java Dependency Guardian.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from enum import Enum


class SeverityLevel(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"


class DependencyType(str, Enum):
    REST_API_CONSUMER = "REST_API_CONSUMER"
    EVENT_PAYLOAD_SCHEMA = "EVENT_PAYLOAD_SCHEMA"
    SHARED_DTO = "SHARED_DTO"
    RPC_INTERFACE = "RPC_INTERFACE"
    GENERIC = "GENERIC"


@dataclass
class RepoDependencyRule:
    pair_id: str
    source_repo: str
    source_branch: str
    source_file_pattern: List[str]
    target_repo: str
    target_branch: str
    target_file_pattern: List[str]
    dependency_type: str
    severity_level: str
    notification_channel: str
    auto_block_pr: bool
    owner_team: str
    description: str


@dataclass
class JavaField:
    name: str
    type_name: str
    line_number: int = 1
    annotations: List[str] = field(default_factory=list)
    json_property: Optional[str] = None
    is_json_ignored: bool = False
    validation_constraints: List[str] = field(default_factory=list)


@dataclass
class JavaMethod:
    name: str
    return_type: str
    line_number: int = 1
    parameters: List[str] = field(default_factory=list)
    annotations: List[str] = field(default_factory=list)


@dataclass
class RestEndpoint:
    verb: str
    path: str
    line_number: int = 1
    required_params: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class JavaClassModel:
    package_name: str
    class_name: str
    class_type: str  # class, interface, enum, record
    line_number: int = 1
    fields: Dict[str, JavaField] = field(default_factory=dict)
    methods: Dict[str, JavaMethod] = field(default_factory=dict)
    annotations: List[str] = field(default_factory=list)
    rest_endpoints: List[Dict[str, Any]] = field(default_factory=list)  # method, path, line_number, required_params


@dataclass
class ChangedJavaFile:
    path: str
    status: str  # added, modified, removed
    diff: str
    old_content: Optional[str] = None
    new_content: Optional[str] = None
    parsed_old: Optional[JavaClassModel] = None
    parsed_new: Optional[JavaClassModel] = None


@dataclass
class DependentTargetFile:
    repo: str
    path: str
    content: str
    parsed_model: Optional[JavaClassModel] = None


@dataclass
class ImpactFinding:
    target_repo: str
    target_file: str
    source_repo: str
    source_file: str
    is_impacted: bool
    severity: str
    dependency_type: str
    breaking_change_summary: str
    detailed_reason: str
    suggested_fix: str
    suggested_patch_code: str
    source_line: Optional[int] = None
    target_line: Optional[int] = None


@dataclass
class RepoArchitectureSummary:
    repo_name: str
    description: str = ""
    default_branch: str = "main"
    primary_language: str = "Java"
    topics: List[str] = field(default_factory=list)
    build_tool: str = "Maven"
    frameworks: List[str] = field(default_factory=list)
    key_directories: List[str] = field(default_factory=list)
    role_in_contract: str = "Participant"


@dataclass
class AnalysisReport:
    source_repo: str
    target_repos_checked: List[str]
    changed_java_files_count: int
    has_breaking_changes: bool
    findings: List[ImpactFinding] = field(default_factory=list)
    repo_architectures: Dict[str, RepoArchitectureSummary] = field(default_factory=dict)
    markdown_summary: str = ""
