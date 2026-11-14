"""
Java Source Code and AST/Semantic Parser.
Extracts class details, fields, methods, REST endpoints, and annotations
including Bean Validation (@NotNull, @NotBlank, @Size) and Jackson (@JsonProperty, @JsonIgnore).
Tracks exact 1-based source line numbers for all parsed elements.
"""

import re
from typing import Dict, List, Optional, Tuple, Set, Any
from src.models import JavaClassModel, JavaField, JavaMethod, RestEndpoint


# Regex patterns for Java parsing
PKG_REGEX = re.compile(r"^\s*package\s+([\w\.]+)\s*;", re.MULTILINE)
CLASS_DECL_REGEX = re.compile(
    r"(?:public|protected|private|abstract|static|final|\s)*\s*(class|interface|enum|record)\s+([A-Za-z0-9_]+)",
    re.MULTILINE,
)
FIELD_LINE_REGEX = re.compile(
    r"^(?:(?:private|protected|public)\s+)?(?:static\s+)?(?:final\s+)?([A-Za-z0-9_<>,?\[\]]+)\s+([A-Za-z0-9_]+)\s*(?:=\s*[^;]+)?\s*;$"
)
METHOD_LINE_REGEX = re.compile(
    r"^(?:(?:public|protected|private)\s+)?(?:static\s+)?(?:final\s+)?(?:synchronized\s+)?([A-Za-z0-9_<>,?\[\]]+)\s+([A-Za-z0-9_]+)\s*\(([^)]*)\)"
)
REST_MAPPING_REGEX = re.compile(
    r"@(GetMapping|PostMapping|PutMapping|DeleteMapping|PatchMapping|RequestMapping)\s*(?:\(\s*(?:value\s*=\s*)?\"([^\"]*)\")?",
    re.MULTILINE,
)
KAFKA_REGEX = re.compile(
    r"@KafkaListener\s*\(\s*(?:topics\s*=\s*\"([^\"]+)\"|value\s*=\s*\"([^\"]+)\")",
    re.MULTILINE,
)

# Annotation inspection regexes
JSON_PROPERTY_REGEX = re.compile(r'@JsonProperty\s*\(\s*(?:value\s*=\s*)?\"([^\"]+)\"\s*\)')
JSON_IGNORE_REGEX = re.compile(r'@JsonIgnore\b')
VALIDATION_ANNOS = ["@NotNull", "@NotBlank", "@NotEmpty", "@Size", "@Min", "@Max", "@Pattern", "@Positive", "@Email"]


def get_line_number(content: str, char_index: int) -> int:
    """Calculate 1-based line number for a character offset."""
    return content[:char_index].count("\n") + 1


def find_symbol_line(content: str, symbol: str) -> Optional[int]:
    """Finds the 1-based line number where a symbol appears in text."""
    pattern = re.compile(r"\b" + re.escape(symbol) + r"\b")
    match = pattern.search(content)
    if match:
        return get_line_number(content, match.start())
    # Fallback to simple substring
    pos = content.find(symbol)
    if pos != -1:
        return get_line_number(content, pos)
    return None


def parse_field_annotations(annotations: List[str]) -> Tuple[Optional[str], bool, List[str]]:
    """Extract Jackson and Bean Validation metadata from raw annotation strings."""
    json_prop = None
    is_ignored = False
    validations = []

    for a in annotations:
        jp_match = JSON_PROPERTY_REGEX.search(a)
        if jp_match:
            json_prop = jp_match.group(1)
        if JSON_IGNORE_REGEX.search(a):
            is_ignored = True
        for val_prefix in VALIDATION_ANNOS:
            if val_prefix in a:
                validations.append(a.strip())

    return json_prop, is_ignored, validations


def parse_method_request_params(param_str: str, method_line: int) -> List[Dict[str, Any]]:
    """Extracts @RequestParam requirements and constraints from a method parameter list."""
    if not param_str:
        return []

    req_params: List[Dict[str, Any]] = []
    # Split parameters by comma (simple split, handles typical controller signatures)
    params = [p.strip() for p in param_str.split(",") if p.strip()]

    for p in params:
        if "@RequestParam" in p:
            # Check if required is explicitly set or default (in Spring @RequestParam, required defaults to true)
            is_required = True
            if "required = false" in p or "required=false" in p:
                is_required = False
            if "defaultValue" in p:
                is_required = False

            # Extract parameter name
            name_match = re.search(r'@RequestParam\s*(?:\(\s*(?:value\s*=\s*|name\s*=\s*)?\"([^\"]+)\")?', p)
            param_name = name_match.group(1) if name_match and name_match.group(1) else None

            # If not in annotation value, take the variable name (last word)
            if not param_name:
                parts = p.split()
                if parts:
                    param_name = parts[-1].strip()

            req_params.append({
                "param_name": param_name or "unknown",
                "is_required": is_required,
                "raw_param": p,
                "line_number": method_line,
            })

    return req_params


def parse_java_source(content: str) -> JavaClassModel:
    """
    Parses a Java source file string into a structured JavaClassModel,
    annotated with 1-based line numbers, Jackson properties, and Bean validations.
    """
    if not content:
        return JavaClassModel(package_name="", class_name="", class_type="class")

    # Extract Package
    pkg_match = PKG_REGEX.search(content)
    package_name = pkg_match.group(1) if pkg_match else ""

    # Extract Class / Interface declaration & line
    class_match = CLASS_DECL_REGEX.search(content)
    class_type = class_match.group(1) if class_match else "class"
    class_name = class_match.group(2) if class_match else "UnknownClass"
    class_line = get_line_number(content, class_match.start()) if class_match else 1

    # Extract Fields & Methods line by line with accurate annotations and line numbers
    fields: Dict[str, JavaField] = {}
    methods: Dict[str, JavaMethod] = {}
    lines = content.splitlines()
    pending_annotations: List[str] = []

    for idx, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped:
            continue

        if stripped.startswith("@"):
            pending_annotations.append(stripped)
            continue

        # Check for field declaration
        fm = FIELD_LINE_REGEX.match(stripped)
        if fm:
            f_type = fm.group(1).strip()
            f_name = fm.group(2).strip()
            if f_type not in ("return", "package", "import", "class", "interface"):
                json_prop, is_ignored, validations = parse_field_annotations(pending_annotations)
                fields[f_name] = JavaField(
                    name=f_name,
                    type_name=f_type,
                    line_number=idx,
                    annotations=list(pending_annotations),
                    json_property=json_prop,
                    is_json_ignored=is_ignored,
                    validation_constraints=validations,
                )
                pending_annotations = []
                continue

        # Check for method declaration
        mm = METHOD_LINE_REGEX.match(stripped)
        if mm:
            m_return = mm.group(1).strip()
            m_name = mm.group(2).strip()
            m_params_raw = mm.group(3)
            m_params = [p.strip() for p in m_params_raw.split(",") if p.strip()]
            if m_return not in ("if", "for", "while", "switch", "catch"):
                methods[m_name] = JavaMethod(
                    name=m_name,
                    return_type=m_return,
                    line_number=idx,
                    parameters=m_params,
                    annotations=list(pending_annotations),
                )
                pending_annotations = []
                continue

        if not stripped.startswith("//") and not stripped.startswith("/*") and not stripped.startswith("*"):
            pending_annotations = []

    # Extract Annotations on class
    class_annots = re.findall(r"^@\w+(?:\([^)]*\))?", content, re.MULTILINE)

    # Extract REST endpoints with line numbers & required parameter specifications
    endpoints: List[Dict[str, Any]] = []
    for match in REST_MAPPING_REGEX.finditer(content):
        verb = match.group(1)
        path = match.group(2) or "/"
        ep_line = get_line_number(content, match.start())

        # Inspect the method attached to this endpoint to find required query parameters
        method_chunk = content[match.end():match.end() + 350]
        method_match = METHOD_REGEX.search(method_chunk)
        req_params = []
        if method_match:
            req_params = parse_method_request_params(method_match.group(3), ep_line)

        endpoints.append({
            "verb": verb,
            "path": path,
            "line_number": ep_line,
            "required_params": req_params,
        })

    return JavaClassModel(
        package_name=package_name,
        class_name=class_name,
        class_type=class_type,
        line_number=class_line,
        fields=fields,
        methods=methods,
        annotations=class_annots,
        rest_endpoints=endpoints,
    )


def compare_java_versions(old_code: str, new_code: str) -> Dict[str, Any]:
    """
    Compares two versions of the same Java file and computes detailed delta.
    Detects removed fields, renamed/modified fields, removed methods, signature changes,
    Bean validation additions, Jackson @JsonProperty mutations, and newly required query parameters.
    """
    old_model = parse_java_source(old_code)
    new_model = parse_java_source(new_code)

    old_field_names: Set[str] = set(old_model.fields.keys())
    new_field_names: Set[str] = set(new_model.fields.keys())

    removed_fields = [
        {
            "name": f,
            "type": old_model.fields[f].type_name,
            "line_number": old_model.fields[f].line_number,
        }
        for f in (old_field_names - new_field_names)
    ]
    added_fields = [
        {
            "name": f,
            "type": new_model.fields[f].type_name,
            "line_number": new_model.fields[f].line_number,
            "validation_constraints": new_model.fields[f].validation_constraints,
        }
        for f in (new_field_names - old_field_names)
    ]

    type_changed_fields = []
    validation_tightened_fields = []
    jackson_mutated_fields = []

    for common_field in old_field_names & new_field_names:
        old_f = old_model.fields[common_field]
        new_f = new_model.fields[common_field]

        # 1. Type change
        if old_f.type_name != new_f.type_name:
            type_changed_fields.append({
                "name": common_field,
                "old_type": old_f.type_name,
                "new_type": new_f.type_name,
                "line_number": new_f.line_number,
            })

        # 2. Validation constraint tightening (e.g. added @NotNull, @NotBlank)
        new_constraints = set(new_f.validation_constraints) - set(old_f.validation_constraints)
        if new_constraints:
            validation_tightened_fields.append({
                "name": common_field,
                "field_type": new_f.type_name,
                "added_constraints": sorted(list(new_constraints)),
                "line_number": new_f.line_number,
            })

        # 3. Jackson wire serialization change (@JsonProperty renamed or @JsonIgnore added)
        if old_f.json_property != new_f.json_property:
            jackson_mutated_fields.append({
                "name": common_field,
                "old_property": old_f.json_property or common_field,
                "new_property": new_f.json_property or common_field,
                "reason": "JsonProperty wire-name changed",
                "line_number": new_f.line_number,
            })
        elif not old_f.is_json_ignored and new_f.is_json_ignored:
            jackson_mutated_fields.append({
                "name": common_field,
                "old_property": old_f.json_property or common_field,
                "new_property": "[IGNORED]",
                "reason": "@JsonIgnore added to field",
                "line_number": new_f.line_number,
            })

    old_methods: Set[str] = set(old_model.methods.keys())
    new_methods: Set[str] = set(new_model.methods.keys())

    removed_methods = [
        {
            "name": m,
            "return_type": old_model.methods[m].return_type,
            "params": old_model.methods[m].parameters,
            "line_number": old_model.methods[m].line_number,
        }
        for m in (old_methods - new_methods)
    ]

    method_signature_changes = []
    for common_method in old_methods & new_methods:
        old_m = old_model.methods[common_method]
        new_m = new_model.methods[common_method]
        if old_m.parameters != new_m.parameters or old_m.return_type != new_m.return_type:
            method_signature_changes.append({
                "name": common_method,
                "old_return": old_m.return_type,
                "new_return": new_m.return_type,
                "old_params": old_m.parameters,
                "new_params": new_m.parameters,
                "line_number": new_m.line_number,
            })

    # REST endpoint parameter requirements
    newly_required_params = []
    for ep in new_model.rest_endpoints:
        for p in ep.get("required_params", []):
            if p.get("is_required"):
                # Check if old endpoints already required this param
                old_has_param = False
                for old_ep in old_model.rest_endpoints:
                    if old_ep.get("path") == ep.get("path"):
                        for old_p in old_ep.get("required_params", []):
                            if old_p.get("param_name") == p.get("param_name"):
                                old_has_param = True
                if not old_has_param and old_model.rest_endpoints:
                    newly_required_params.append({
                        "endpoint_path": ep.get("path"),
                        "param_name": p.get("param_name"),
                        "line_number": p.get("line_number"),
                    })

    return {
        "class_name": new_model.class_name or old_model.class_name,
        "package": new_model.package_name or old_model.package_name,
        "class_line": new_model.line_number or old_model.line_number,
        "removed_fields": removed_fields,
        "added_fields": added_fields,
        "type_changed_fields": type_changed_fields,
        "validation_tightened_fields": validation_tightened_fields,
        "jackson_mutated_fields": jackson_mutated_fields,
        "removed_methods": removed_methods,
        "method_signature_changes": method_signature_changes,
        "newly_required_params": newly_required_params,
        "old_endpoints": old_model.rest_endpoints,
        "new_endpoints": new_model.rest_endpoints,
    }
