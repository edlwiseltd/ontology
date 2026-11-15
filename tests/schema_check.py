"""A small JSON Schema checker (the subset the API contracts use), so contract tests validate real responses
against the published OpenAPI schemas without a third-party dependency."""

from typing import Any, Dict, List

TYPES = {"string": str, "integer": int, "number": (int, float), "boolean": bool, "object": dict, "array": list,
         "null": type(None)}


def errors(value: Any, schema: Dict[str, Any], components: Dict[str, Any], path: str = "$") -> List[str]:
    if "$ref" in schema:
        return errors(value, components[schema["$ref"].rsplit("/", 1)[1]], components, path)
    out: List[str] = []
    for sub in schema.get("allOf", []):
        out += errors(value, sub, components, path)
    if "type" in schema:
        kinds = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        ok = any(isinstance(value, TYPES[k]) and not (k in ("integer", "number") and isinstance(value, bool))
                 for k in kinds)
        if not ok:
            return out + [f"{path}: expected {'/'.join(kinds)}, got {type(value).__name__}"]
    if "enum" in schema and value not in schema["enum"]:
        out.append(f"{path}: {value!r} not in {schema['enum']}")
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0) or len(value) > schema.get("maxLength", 10 ** 9):
            out.append(f"{path}: length out of range")
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value < schema.get("minimum", -10 ** 18):
        out.append(f"{path}: below minimum")
    if isinstance(value, dict):
        props = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                out.append(f"{path}: missing {key!r}")
        for key, item in value.items():
            if key in props:
                out += errors(item, props[key], components, f"{path}.{key}")
            elif schema.get("additionalProperties") is False:
                out.append(f"{path}: unexpected {key!r}")
            elif isinstance(schema.get("additionalProperties"), dict):
                out += errors(item, schema["additionalProperties"], components, f"{path}.{key}")
    if isinstance(value, list) and "items" in schema:
        for i, item in enumerate(value):
            out += errors(item, schema["items"], components, f"{path}[{i}]")
    return out
