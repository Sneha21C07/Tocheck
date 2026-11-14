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
from src.java_parser import parse_java_source, compare_java_versions, find_symbol_line
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

        # Check if DTO fields match or if any field appears in target
        common_fields = [f for f in set(old_model.fields) | set(src_model.fields) if f in target_content]
        if common_fields:
            return 0.7, f"Contains references to field(s): {common_fields[:3]}"

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
            source_line=data.get("source_line"),
            target_line=data.get("target_line"),
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
        Deterministic, AST-based heuristic analyzer with deep contract intelligence:
        - Exact line numbers for both source mutations and target call sites
        - Bean Validation additions (@NotNull, @NotBlank, @Size)
        - Jackson Wire format changes (@JsonProperty, @JsonIgnore)
        - Newly required @RequestParam query parameters
        - Field removals, renames, and type mutations
        - Method removals and signature shifts
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
        primary_source_line: Optional[int] = None
        primary_target_line: Optional[int] = None

        # 1. Removed fields
        for rem_f in diff_summary["removed_fields"]:
            fname = rem_f["name"]
            src_line = rem_f.get("line_number")
            getter = f"get{fname[0].upper()}{fname[1:]}()"
            setter = f"set{fname[0].upper()}{fname[1:]}("

            tgt_line = (
                find_symbol_line(target_content, getter)
                or find_symbol_line(target_content, setter)
                or find_symbol_line(target_content, fname)
            )

            if tgt_line:
                if not primary_source_line:
                    primary_source_line = src_line
                if not primary_target_line:
                    primary_target_line = tgt_line

                src_loc = f" (Line {src_line})" if src_line else ""
                tgt_loc = f" (Line {tgt_line})" if tgt_line else ""

                breaking_reasons.append(
                    f"Field `{fname}` of type `{rem_f['type']}` was removed/renamed in `{source.path}`{src_loc}, but `{target.path}`{tgt_loc} still references it."
                )
                severity = SeverityLevel.CRITICAL
                suggested_patches.append(
                    f"// In {target.path}{tgt_loc}:\n// Remove references to {fname} / {getter} or update to the new field name."
                )

        # 2. Type changed fields
        for tc_f in diff_summary["type_changed_fields"]:
            fname = tc_f["name"]
            src_line = tc_f.get("line_number")
            tgt_line = find_symbol_line(target_content, fname)

            if tgt_line:
                if not primary_source_line:
                    primary_source_line = src_line
                if not primary_target_line:
                    primary_target_line = tgt_line

                src_loc = f" (Line {src_line})" if src_line else ""
                tgt_loc = f" (Line {tgt_line})" if tgt_line else ""

                breaking_reasons.append(
                    f"Field `{fname}` type changed from `{tc_f['old_type']}` to `{tc_f['new_type']}` in `{source.path}`{src_loc}. Target references it at `{target.path}`{tgt_loc}."
                )
                suggested_patches.append(
                    f"// In {target.path}{tgt_loc}:\n// Update variable or DTO field `{fname}` type from `{tc_f['old_type']}` to `{tc_f['new_type']}`."
                )

        # 3. Bean Validation constraint tightening (@NotNull, @NotBlank, @Size)
        for val_f in diff_summary.get("validation_tightened_fields", []):
            fname = val_f["name"]
            src_line = val_f.get("line_number")
            constraints_str = ", ".join(val_f["added_constraints"])
            tgt_line = find_symbol_line(target_content, fname)

            if tgt_line:
                if not primary_source_line:
                    primary_source_line = src_line
                if not primary_target_line:
                    primary_target_line = tgt_line

                src_loc = f" (Line {src_line})" if src_line else ""
                tgt_loc = f" (Line {tgt_line})" if tgt_line else ""

                breaking_reasons.append(
                    f"Validation constraint(s) [{constraints_str}] added to `{fname}` in `{source.path}`{src_loc}. Dependent `{target.path}`{tgt_loc} sending null/empty values will fail with HTTP 400 (MethodArgumentNotValidException) in production."
                )
                suggested_patches.append(
                    f"// In {target.path}{tgt_loc}:\n// Ensure `{fname}` is always populated with non-null/valid value matching: {constraints_str}."
                )

        # 4. Jackson Wire Serialization mutations (@JsonProperty changed or @JsonIgnore added)
        for jm_f in diff_summary.get("jackson_mutated_fields", []):
            fname = jm_f["name"]
            src_line = jm_f.get("line_number")
            tgt_line = find_symbol_line(target_content, fname)

            if tgt_line:
                if not primary_source_line:
                    primary_source_line = src_line
                if not primary_target_line:
                    primary_target_line = tgt_line

                src_loc = f" (Line {src_line})" if src_line else ""
                tgt_loc = f" (Line {tgt_line})" if tgt_line else ""

                breaking_reasons.append(
                    f"Wire JSON contract changed for `{fname}` in `{source.path}`{src_loc}: {jm_f['reason']} ('{jm_f['old_property']}' -> '{jm_f['new_property']}'). `{target.path}`{tgt_loc} will fail to deserialize or serialize this property."
                )
                suggested_patches.append(
                    f"// In {target.path}{tgt_loc}:\n// Update JSON property mapping for `{fname}` to expect wire name '{jm_f['new_property']}'."
                )

        # 5. Removed methods
        for rem_m in diff_summary["removed_methods"]:
            mname = rem_m["name"]
            src_line = rem_m.get("line_number")
            tgt_line = find_symbol_line(target_content, f"{mname}(")

            if tgt_line:
                if not primary_source_line:
                    primary_source_line = src_line
                if not primary_target_line:
                    primary_target_line = tgt_line

                src_loc = f" (Line {src_line})" if src_line else ""
                tgt_loc = f" (Line {tgt_line})" if tgt_line else ""

                breaking_reasons.append(
                    f"Method `{mname}({', '.join(rem_m['params'])})` was deleted from `{source.path}`{src_loc}, but called in `{target.path}`{tgt_loc}."
                )
                severity = SeverityLevel.CRITICAL
                suggested_patches.append(
                    f"// In {target.path}{tgt_loc}:\n// Replace call to `{mname}()` with the updated API method."
                )

        # 6. Method signature changes
        for sig_m in diff_summary["method_signature_changes"]:
            mname = sig_m["name"]
            src_line = sig_m.get("line_number")
            tgt_line = find_symbol_line(target_content, f"{mname}(")

            if tgt_line:
                if not primary_source_line:
                    primary_source_line = src_line
                if not primary_target_line:
                    primary_target_line = tgt_line

                src_loc = f" (Line {src_line})" if src_line else ""
                tgt_loc = f" (Line {tgt_line})" if tgt_line else ""

                breaking_reasons.append(
                    f"Method signature of `{mname}` changed from `({', '.join(sig_m['old_params'])}) -> {sig_m['old_return']}` "
                    f"to `({', '.join(sig_m['new_params'])}) -> {sig_m['new_return']}` in `{source.path}`{src_loc}. Invoked in `{target.path}`{tgt_loc}."
                )
                suggested_patches.append(
                    f"// In {target.path}{tgt_loc}:\n// Update invocation of `{mname}` to pass new parameter types: ({', '.join(sig_m['new_params'])})."
                )

        # 7. Newly required REST query parameters
        for req_p in diff_summary.get("newly_required_params", []):
            ep_path = req_p["endpoint_path"]
            param_name = req_p["param_name"]
            src_line = req_p.get("line_number")
            tgt_line = find_symbol_line(target_content, ep_path)

            if tgt_line:
                if not primary_source_line:
                    primary_source_line = src_line
                if not primary_target_line:
                    primary_target_line = tgt_line

                src_loc = f" (Line {src_line})" if src_line else ""
                tgt_loc = f" (Line {tgt_line})" if tgt_line else ""

                breaking_reasons.append(
                    f"REST endpoint `{ep_path}` in `{source.path}`{src_loc} added newly required parameter `{param_name}`. Dependent client at `{target.path}`{tgt_loc} omitting it will fail with HTTP 400 (MissingServletRequestParameterException)."
                )
                severity = SeverityLevel.CRITICAL
                suggested_patches.append(
                    f"// In {target.path}{tgt_loc}:\n// Update client request to `{ep_path}` to include required parameter `{param_name}=<value>`."
                )

        # 8. REST endpoint path modifications
        old_eps = {ep["path"]: ep.get("line_number") for ep in diff_summary["old_endpoints"] if ep.get("path")}
        new_eps = {ep["path"]: ep.get("line_number") for ep in diff_summary["new_endpoints"] if ep.get("path")}
        for removed_path, src_line in old_eps.items():
            if removed_path not in new_eps:
                tgt_line = find_symbol_line(target_content, removed_path)
                if tgt_line:
                    if not primary_source_line:
                        primary_source_line = src_line
                    if not primary_target_line:
                        primary_target_line = tgt_line

                    src_loc = f" (Line {src_line})" if src_line else ""
                    tgt_loc = f" (Line {tgt_line})" if tgt_line else ""

                    breaking_reasons.append(
                        f"REST endpoint `{removed_path}` was changed or removed in `{source.path}`{src_loc}, but `{target.path}`{tgt_loc} invokes it."
                    )
                    severity = SeverityLevel.CRITICAL
                    suggested_patches.append(
                        f"// In {target.path}{tgt_loc}:\n// Update HTTP client URL from `{removed_path}` to the new endpoint path."
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
            source_line=primary_source_line,
            target_line=primary_target_line,
        )
