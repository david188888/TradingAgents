"""Model-facing schema adaptation; canonical Pydantic validation stays unchanged."""

import json

STRUCTURED_OUTPUT_POLICY = "provider-schema-or-json-v1"


def strict_schema(source):
    """Close objects and require original types, without making defaults nullable."""
    enum_names, enum_definitions = {}, {}

    def visit(node):
        if isinstance(node, list):
            return [visit(child) for child in node]
        if not isinstance(node, dict):
            return node
        result = {key: visit(value) for key, value in node.items()
                  if key not in {"default", "minLength", "maxLength", "discriminator"}}
        bounds = {key: node[key] for key in ("minLength", "maxLength") if key in node}
        if bounds:
            result["description"] = (result.get("description", "") + " Length constraints validated after "
                "generation: " + ", ".join(f"{key}={value}" for key, value in bounds.items())).strip()
        if "oneOf" in result:
            if "discriminator" not in node:
                branches = node["oneOf"]
                common = set.intersection(*(set(branch.get("required", [])) for branch in branches)) if branches else set()
                disjoint = False
                for name in common:
                    fields = [branch.get("properties", {}).get(name, {}) for branch in branches]
                    if all("const" in field for field in fields) and len({
                        json.dumps(field["const"], sort_keys=True) for field in fields
                    }) == len(branches):
                        disjoint = True
                        break
                if not disjoint:
                    raise ValueError("unsupported_structured_schema_union")
            result["anyOf"] = result.pop("oneOf")
        if "const" in result:
            result["enum"] = [result.pop("const")]
        if result.get("type") == "object":
            if "properties" not in result and result.get("additionalProperties") is not False:
                raise ValueError("unsupported_structured_schema_mapping")
            result.setdefault("properties", {})
            result["additionalProperties"] = False
            result["required"] = list(result["properties"])
        if len(result.get("enum", [])) > 1:
            # Citation choices repeat in each narrative field. Share identical
            # schemas so their enums count once against the provider's limit.
            key = json.dumps(result, sort_keys=True)
            if key not in enum_names:
                name = f"StrictEnum{len(enum_names)}"
                while name in source.get("$defs", {}) or name in enum_definitions:
                    name += "_"
                enum_names[key] = name
                enum_definitions[name] = result
            return {"$ref": "#/$defs/" + enum_names[key]}
        return result

    result = visit(source)
    if enum_definitions:
        result.setdefault("$defs", {}).update(enum_definitions)
    definitions = result.get("$defs", {})

    def depth(node, level=0, refs=frozenset()):
        if not isinstance(node, dict):
            return level
        if "$ref" in node:
            ref = node["$ref"]
            if not ref.startswith("#/$defs/") or ref[8:] not in definitions or ref in refs:
                raise ValueError("unsupported_structured_schema_reference")
            return depth(definitions[ref[8:]], level, refs | {ref})
        level += node.get("type") in {"object", "array"}
        children = [*node.get("properties", {}).values(), *node.get("anyOf", [])]
        if isinstance(node.get("items"), dict):
            children.append(node["items"])
        return max([level, *(depth(child, level, refs) for child in children)])

    if depth(result) > 10:
        raise ValueError("structured_schema_depth_limit")
    properties, enums, string_size = 0, 0, 0

    def count(node):
        nonlocal properties, enums, string_size
        if isinstance(node, dict):
            properties += len(node.get("properties", {}))
            enums += len(node.get("enum", []))
            string_size += sum(len(name) for name in node.get("properties", {}))
            string_size += sum(len(name) for name in node.get("$defs", {}))
            string_size += sum(len(value) for value in node.get("enum", []) if isinstance(value, str))
            if len(node.get("enum", [])) > 250 and sum(len(str(v)) for v in node["enum"]) > 15000:
                raise ValueError("structured_schema_enum_string_limit")
            for child in node.values():
                count(child)
        elif isinstance(node, list):
            for child in node:
                count(child)
    count(result)
    if properties > 5000 or enums > 1000 or string_size > 120000:
        raise ValueError("structured_schema_size_limit")
    return result
