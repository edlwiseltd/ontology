"""A small JSON Schema checker: the subset Autology's contracts use (types, enums, required and additional
properties, items, string and number bounds, ``allOf`` / ``oneOf`` / ``anyOf``, ``$ref`` into components).

It validates what crosses a trust boundary without a third-party dependency: API responses against the published
contracts (tests), and a model's structured answer against the schema it was asked for (:mod:`autology.ai`).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

TYPES: Dict[str, Any] = {"string": str, "integer": int, "number": (int, float), "boolean": bool, "object": dict, "array": list,
         "null": type(None)}


def errors(value: Any, schema: Dict[str, Any], components: Optional[Dict[str, Any]] = None,
           path: str = "$") -> List[str]:
    """What is wrong with ``value`` under ``schema`` (an empty list: it conforms)."""
    components = components or {}
    if "$ref" in schema:
        return errors(value, components[schema["$ref"].rsplit("/", 1)[1]], components, path)
    out: List[str] = []
    for sub in schema.get("allOf", []):
        out += errors(value, sub, components, path)
    if "oneOf" in schema:
        matching = [s for s in schema["oneOf"] if not errors(value, s, components, path)]
        if len(matching) != 1:
            out.append(f"{path}: matches {len(matching)} of the oneOf schemas, expected exactly 1")
    if "anyOf" in schema and all(errors(value, s, components, path) for s in schema["anyOf"]):
        out.append(f"{path}: matches none of the anyOf schemas")
    if "type" in schema:
        kinds = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        ok = any(isinstance(value, TYPES[k]) and not (k in ("integer", "number") and isinstance(value, bool))
                 for k in kinds)
        if not ok:
            return out + [f"{path}: expected {'/'.join(kinds)}, got {type(value).__name__}"]
    if "enum" in schema and value not in schema["enum"]:
        out.append(f"{path}: {str(value)[:60]!r} not in {schema['enum']}")
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0) or len(value) > schema.get("maxLength", 10 ** 9):
            out.append(f"{path}: length out of range")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if value < schema.get("minimum", -10 ** 18):
            out.append(f"{path}: below minimum")
        if value > schema.get("maximum", 10 ** 18):
            out.append(f"{path}: above maximum")
    if isinstance(value, dict):
        props = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                out.append(f"{path}: missing {key!r}")
        for key, item in value.items():
            if key in props:
                out += errors(item, props[key], components, f"{path}.{key}")
            elif schema.get("additionalProperties") is False:
                out.append(f"{path}: unexpected {str(key)[:60]!r}")
            elif isinstance(schema.get("additionalProperties"), dict):
                out += errors(item, schema["additionalProperties"], components, f"{path}.{key}")
    if isinstance(value, list):
        if len(value) > schema.get("maxItems", 10 ** 9):
            out.append(f"{path}: more than {schema['maxItems']} items")
        if "items" in schema:
            for i, item in enumerate(value):
                out += errors(item, schema["items"], components, f"{path}[{i}]")
    return out
