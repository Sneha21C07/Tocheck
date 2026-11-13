"""
AI Impact Analyzer Agent.
Performs semantic diffing and cross-repo dependency impact analysis.
Combines Java AST/symbol inspection with LLM reasoning (OpenAI/Gemini) and heuristic fallbacks.
"""

import json
import logging
import os
import re
from typing import List, Optional, Dict, Any

import httpx
from src.config import Config
from src.java_parser import parse_java_source, compare_java_versions
from src.models import (
    ChangedJavaFile,
    DependentTargetFile,
    ImpactFinding,
    RepoDependencyRule,
    SeverityLevel,
)

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """You are an elite Principal Java Microservices Architect and Automated Dependency Guardian.
Your task is to analyze changes made to Java files in a SOURCE REPOSITORY and determine if they introduce breaking or non-breaking changes in a DEPENDENT TARGET REPOSITORY.

You will be given:
1. Source Repository Name and Target Repository Name.
2. The Git diff and old/new code of modified Java file(s) in the Source Repo.
3. The content of candidate dependent Java file(s) in the Target Repo.
4. The Dependency Type (e.g., REST_API_CONSUMER, EVENT_PAYLOAD_SCHEMA, SHARED_DTO, RPC_INTERFACE).

Analyze carefully:
- Field renames, removals, type modifications in DTOs, entities, or request/response payloads.
- Added non-optional fields that break JSON deserialization or serialization (Jackson/Gson).
- Modified method signatures, removed methods, or changed return types in interfaces/clients.
- REST endpoint URL path changes, HTTP method changes, altered headers or query parameters.
- Event / messaging schema changes (Kafka, RabbitMQ, JMS).

Return ONLY valid JSON with this exact schema:
{
  "is_impacted": true | false,
  "severity": "CRITICAL" | "HIGH" | "MEDIUM" | "LOW" | "NONE",
  "breaking_change_summary": "1-2 sentence high-level summary of the breaking change",
  "detailed_reason": "Detailed architectural explanation of why the dependent repo will break in production",
  "suggested_fix": "Actionable instructions for the developer on how to fix the dependent repository",
  "suggested_patch_code": "Java code snippet or diff illustrating the fix needed in the target repo"
}
"""


class DependencyAnalyzerAgent:
    def __init__(self):
        self.config = Config

    def analyze_cross_repo_impact(
        self,
        source_repo: str,
        target_repo: str,
        rule: RepoDependencyRule,
        changed_source_file: ChangedJavaFile,
        target_file: DependentTargetFile,
    ) -> Optional[ImpactFinding]:
        """
        Main analysis method comparing a changed source file against a candidate target file.
        """
        # Step 1: Pre-filter - does target file have any relevance to source file?
        relevance_score, reason = self._check_relevance(changed_source_file, target_file)
        if relevance_score == 0:
            return None

        # Step 2: Attempt LLM reasoning if API key configured
        llm_finding = self._try_llm_analysis(
            source_repo, target_repo, rule, changed_source_file, target_file
        )
        if llm_finding:
            return llm_finding

        # Step 3: Rule-based heuristic analyzer (guaranteed fallback)
        return self._heuristic_analysis(
            source_repo, target_repo, rule, changed_source_file, target_file
        )

    def _check_relevance(
        self, source: ChangedJavaFile, target: DependentTargetFile
    ) -> tuple[float, str]:
        """Quick check to see if target Java file mentions or references the source symbols."""
        src_model = source.parsed_new or parse_java_source(source.new_content or "")
        old_model = source.parsed_old or parse_java_source(source.old_content or "")

        class_name = src_model.class_name or old_model.class_name
        target_content = target.content

        # Direct class reference or import
        if class_name in target_content:
            return 1.0, f"References class {class_name}"

        # Check if any REST endpoints match target strings
        for ep in src_model.rest_endpoints + old_model.rest_endpoints:
            path = ep.get("path", "")
            if path and len(path) > 3 and path in target_content:
                return 0.8, f"References endpoint path {path}"

        # Check if DTO fields match with high overlap
        common_fields = [f for f in old_model.fields if f in target_content]
        if len(common_fields) >= 3:
            return 0.6, f"Shared field names: {common_fields[:3]}"

        return 0.0, "No apparent reference"

    def _try_llm_analysis(
        self,
        source_repo: str,
        target_repo: str,
        rule: RepoDependencyRule,
        source: ChangedJavaFile,
        target: DependentTargetFile,
    ) -> Optional[ImpactFinding]:
        """Calls OpenAI or Gemini API if credentials are present."""
        prompt = f"""
SOURCE REPOSITORY: {source_repo}
TARGET REPOSITORY: {target_repo}
DEPENDENCY TYPE: {rule.dependency_type}
FILE IN SOURCE REPO: {source.path}
FILE IN TARGET REPO: {target.path}

GIT DIFF IN SOURCE REPO:
```diff
{source.diff[:3000]}
```

SOURCE FILE NEW CONTENT:
```java
{(source.new_content or '')[:3000]}
```

TARGET FILE CURRENT CONTENT:
```java
{target.content[:3500]}
```
"""
        # 1. Try Gemini if configured
        if self.config.GEMINI_API_KEY:
            try:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-pro:generateContent?key={self.config.GEMINI_API_KEY}"
                payload = {
                    "contents": [{"parts": [{"text": f"{SYSTEM_PROMPT}\n\n{prompt}"}]}],
                    "generationConfig": {"temperature": 0.1, "responseMimeType": "application/json"},
                }
                res = httpx.post(url, json=payload, timeout=25.0)
                if res.status_code == 200:
                    text_out = res.json()["candidates"][0]["content"]["parts"][0]["text"]
                    data = json.loads(text_out)
                    if data.get("is_impacted"):
                        return self._dict_to_finding(data, source_repo, target_repo, source.path, target.path, rule.dependency_type)
            except Exception as e:
                logger.warning(f"Gemini API call failed: {e}")

        # 2. Try OpenAI if configured
        if self.config.OPENAI_API_KEY:
            try:
                url = "https://api.openai.com/v1/chat/completions"
                headers = {"Authorization": f"Bearer {self.config.OPENAI_API_KEY}"}
                payload = {
                    "model": "gpt-4o",
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                    "response_format": {"type": "json_object"},
                    "temperature": 0.1,
                }
                res = httpx.post(url, headers=headers, json=payload, timeout=25.0)
                if res.status_code == 200:
                    data = json.loads(res.json()["choices"][0]["message"]["content"])
                    if data.get("is_impacted"):
                        return self._dict_to_finding(data, source_repo, target_repo, source.path, target.path, rule.dependency_type)
            except Exception as e:
                logger.warning(f"OpenAI API call failed: {e}")

        return None

    def _dict_to_finding(
        self,
        data: Dict[str, Any],
        source_repo: str,
        target_repo: str,
        source_path: str,
        target_path: str,
        dep_type: str,
    ) -> ImpactFinding:
        return ImpactFinding(
            target_repo=target_repo,
            target_file=target_path,
            source_repo=source_repo,
            source_file=source_path,
            is_impacted=bool(data.get("is_impacted", True)),
            severity=data.get("severity", "HIGH"),
            dependency_type=dep_type,
            breaking_change_summary=data.get("breaking_change_summary", "Contract incompatibility detected."),
            detailed_reason=data.get("detailed_reason", ""),
            suggested_fix=data.get("suggested_fix", ""),
            suggested_patch_code=data.get("suggested_patch_code", ""),
        )

    def _heuristic_analysis(
        self,
        source_repo: str,
        target_repo: str,
        rule: RepoDependencyRule,
        source: ChangedJavaFile,
        target: DependentTargetFile,
    ) -> Optional[ImpactFinding]:
        """
        Deterministic, AST-based heuristic analysis.
        Identifies removed fields, modified types, deleted methods, and endpoint changes.
        """
        old_content = source.old_content or ""
        new_content = source.new_content or ""

        # If old_content is not available directly, infer from diff
        if not old_content and source.diff:
            old_lines = []
            for line in source.diff.splitlines():
                if line.startswith("-") and not line.startswith("---"):
                    old_lines.append(line[1:])
                elif not line.startswith("+"):
                    old_lines.append(line)
            old_content = "\n".join(old_lines)

        diff_summary = compare_java_versions(old_content, new_content)
        target_content = target.content

        breaking_reasons = []
        suggested_patches = []
        severity = SeverityLevel.HIGH

        # 1. Removed fields
        for rem_f in diff_summary["removed_fields"]:
            fname = rem_f["name"]
            # Look for getter/setter or direct usage
            getter = f"get{fname[0].upper()}{fname[1:]}()"
            setter = f"set{fname[0].upper()}{fname[1:]}("
            if fname in target_content or getter in target_content or setter in target_content:
                breaking_reasons.append(
                    f"Field `{fname}` of type `{rem_f['type']}` was removed/renamed in `{source.path}`, but `{target.path}` still references it."
                )
                severity = SeverityLevel.CRITICAL
                suggested_patches.append(
                    f"// In {target.path}:\n// Remove references to {fname} / {getter} or update to the new field name."
                )

        # 2. Type changed fields
        for tc_f in diff_summary["type_changed_fields"]:
            fname = tc_f["name"]
            if fname in target_content:
                breaking_reasons.append(
                    f"Field `{fname}` type changed from `{tc_f['old_type']}` to `{tc_f['new_type']}` in `{source.path}`."
                )
                suggested_patches.append(
                    f"// In {target.path}:\n// Update variable or DTO field `{fname}` type to `{tc_f['new_type']}`."
                )

        # 3. Removed methods
        for rem_m in diff_summary["removed_methods"]:
            mname = rem_m["name"]
            if f"{mname}(" in target_content:
                breaking_reasons.append(
                    f"Method `{mname}({', '.join(rem_m['params'])})` was deleted from `{source.path}`, but called in `{target.path}`."
                )
                severity = SeverityLevel.CRITICAL
                suggested_patches.append(
                    f"// In {target.path}:\n// Replace call to `{mname}()` with the updated API method."
                )

        # 4. Method signature changes
        for sig_m in diff_summary["method_signature_changes"]:
            mname = sig_m["name"]
            if f"{mname}(" in target_content:
                breaking_reasons.append(
                    f"Method signature of `{mname}` changed from `({', '.join(sig_m['old_params'])}) -> {sig_m['old_return']}` "
                    f"to `({', '.join(sig_m['new_params'])}) -> {sig_m['new_return']}`."
                )
                suggested_patches.append(
                    f"// In {target.path}:\n// Update invocation of `{mname}` to pass new parameter types: ({', '.join(sig_m['new_params'])})."
                )

        # 5. REST endpoint path modifications
        old_eps = {ep["path"] for ep in diff_summary["old_endpoints"] if ep["path"]}
        new_eps = {ep["path"] for ep in diff_summary["new_endpoints"] if ep["path"]}
        for removed_path in old_eps - new_eps:
            if removed_path in target_content:
                breaking_reasons.append(
                    f"REST endpoint `{removed_path}` was changed or removed in `{source.path}`, but `{target.path}` invokes it."
                )
                severity = SeverityLevel.CRITICAL
                suggested_patches.append(
                    f"// In {target.path}:\n// Update HTTP client URL from `{removed_path}` to the new endpoint path."
                )

        if not breaking_reasons:
            return None

        return ImpactFinding(
            target_repo=target_repo,
            target_file=target.path,
            source_repo=source_repo,
            source_file=source.path,
            is_impacted=True,
            severity=severity.value,
            dependency_type=rule.dependency_type,
            breaking_change_summary=breaking_reasons[0],
            detailed_reason="\n".join(f"- {r}" for r in breaking_reasons),
            suggested_fix=f"Update `{target.path}` in `{target_repo}` to accommodate contract modifications in `{source_repo}`.",
            suggested_patch_code="\n\n".join(suggested_patches),
        )
