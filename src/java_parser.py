"""
Java Source Code and AST/Semantic Parser.
Extracts class details, fields, methods, REST endpoints, and Kafka/Event annotations.
"""

import re
from typing import Dict, List, Optional, Tuple, Set, Any
from src.models import JavaClassModel, JavaField, JavaMethod


# Regex patterns for Java parsing
PKG_REGEX = re.compile(r"^\s*package\s+([\w\.]+)\s*;", re.MULTILINE)
CLASS_DECL_REGEX = re.compile(
    r"(?:public|protected|private|abstract|static|final|\s)*\s*(class|interface|enum|record)\s+([A-Za-z0-9_]+)",
    re.MULTILINE,
)
FIELD_REGEX = re.compile(
    r"^\s*(?:@[\w\(\)\"=,\.\s]+\s+)*(?:private|protected|public)?\s*(?:static\s+)?(?:final\s+)?([A-Za-z0-9_<>,?\[\]]+)\s+([A-Za-z0-9_]+)\s*(?:=\s*[^;]+)?\s*;",
    re.MULTILINE,
)
METHOD_REGEX = re.compile(
    r"^\s*(?:@[\w\(\)\"=,\.\s]+\s+)*(?:public|protected|private)?\s*(?:static\s+)?(?:final\s+)?(?:synchronized\s+)?([A-Za-z0-9_<>,?\[\]]+)\s+([A-Za-z0-9_]+)\s*\(([^)]*)\)\s*(?:throws\s+[\w\s,]+)?\s*[\{\;]",
    re.MULTILINE,
)
REST_MAPPING_REGEX = re.compile(
    r"@(GetMapping|PostMapping|PutMapping|DeleteMapping|PatchMapping|RequestMapping)\s*(?:\(\s*(?:value\s*=\s*)?\"([^\"]*)\")?",
    re.MULTILINE,
)
KAFKA_REGEX = re.compile(
    r"@KafkaListener\s*\(\s*(?:topics\s*=\s*\"([^\"]+)\"|value\s*=\s*\"([^\"]+)\")",
    re.MULTILINE,
)


def parse_java_source(content: str) -> JavaClassModel:
    """
    Parses a Java source file string into a structured JavaClassModel.
    """
    if not content:
        return JavaClassModel(package_name="", class_name="", class_type="class")

    # Extract Package
    pkg_match = PKG_REGEX.search(content)
    package_name = pkg_match.group(1) if pkg_match else ""

    # Extract Class / Interface declaration
    class_match = CLASS_DECL_REGEX.search(content)
    class_type = class_match.group(1) if class_match else "class"
    class_name = class_match.group(2) if class_match else "UnknownClass"

    # Extract Fields
    fields: Dict[str, JavaField] = {}
    for match in FIELD_REGEX.finditer(content):
        f_type = match.group(1).strip()
        f_name = match.group(2).strip()
        # Filter out common false positives like return or import
        if f_type in ("return", "package", "import", "class", "interface"):
            continue
        # Extract annotations preceding the field
        start_pos = max(0, match.start() - 150)
        prefix = content[start_pos:match.start()]
        annots = re.findall(r"@\w+(?:\([^)]*\))?", prefix)
        fields[f_name] = JavaField(name=f_name, type_name=f_type, annotations=annots)

    # Extract Methods
    methods: Dict[str, JavaMethod] = {}
    for match in METHOD_REGEX.finditer(content):
        m_return = match.group(1).strip()
        m_name = match.group(2).strip()
        m_params = [p.strip() for p in match.group(3).split(",") if p.strip()]
        if m_return in ("if", "for", "while", "switch", "catch"):
            continue
        start_pos = max(0, match.start() - 150)
        prefix = content[start_pos:match.start()]
        annots = re.findall(r"@\w+(?:\([^)]*\))?", prefix)
        methods[m_name] = JavaMethod(
            name=m_name,
            return_type=m_return,
            parameters=m_params,
            annotations=annots,
        )

    # Extract Annotations on class
    class_annots = re.findall(r"^@\w+(?:\([^)]*\))?", content, re.MULTILINE)

    # Extract REST endpoints
    endpoints: List[Dict[str, str]] = []
    for match in REST_MAPPING_REGEX.finditer(content):
        verb = match.group(1)
        path = match.group(2) or "/"
        endpoints.append({"verb": verb, "path": path})

    return JavaClassModel(
        package_name=package_name,
        class_name=class_name,
        class_type=class_type,
        fields=fields,
        methods=methods,
        annotations=class_annots,
        rest_endpoints=endpoints,
    )


def compare_java_versions(old_code: str, new_code: str) -> Dict[str, Any]:
    """
    Compares two versions of the same Java file and computes detailed delta.
    Detects removed fields, renamed/modified fields, removed methods, signature changes.
    """
    old_model = parse_java_source(old_code)
    new_model = parse_java_source(new_code)

    old_field_names: Set[str] = set(old_model.fields.keys())
    new_field_names: Set[str] = set(new_model.fields.keys())

    removed_fields = [
        {"name": f, "type": old_model.fields[f].type_name}
        for f in (old_field_names - new_field_names)
    ]
    added_fields = [
        {"name": f, "type": new_model.fields[f].type_name}
        for f in (new_field_names - old_field_names)
    ]
    type_changed_fields = []
    for common_field in old_field_names & new_field_names:
        old_f = old_model.fields[common_field]
        new_f = new_model.fields[common_field]
        if old_f.type_name != new_f.type_name:
            type_changed_fields.append(
                {
                    "name": common_field,
                    "old_type": old_f.type_name,
                    "new_type": new_f.type_name,
                }
            )

    old_methods: Set[str] = set(old_model.methods.keys())
    new_methods: Set[str] = set(new_model.methods.keys())

    removed_methods = [
        {
            "name": m,
            "return_type": old_model.methods[m].return_type,
            "params": old_model.methods[m].parameters,
        }
        for m in (old_methods - new_methods)
    ]

    method_signature_changes = []
    for common_method in old_methods & new_methods:
        old_m = old_model.methods[common_method]
        new_m = new_model.methods[common_method]
        if old_m.parameters != new_m.parameters or old_m.return_type != new_m.return_type:
            method_signature_changes.append(
                {
                    "name": common_method,
                    "old_return": old_m.return_type,
                    "new_return": new_m.return_type,
                    "old_params": old_m.parameters,
                    "new_params": new_m.parameters,
                }
            )

    return {
        "class_name": new_model.class_name or old_model.class_name,
        "package": new_model.package_name or old_model.package_name,
        "removed_fields": removed_fields,
        "added_fields": added_fields,
        "type_changed_fields": type_changed_fields,
        "removed_methods": removed_methods,
        "method_signature_changes": method_signature_changes,
        "old_endpoints": old_model.rest_endpoints,
        "new_endpoints": new_model.rest_endpoints,
    }
