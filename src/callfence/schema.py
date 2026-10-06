from dataclasses import dataclass
import re

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError
from referencing import Registry

from .source import lookup, pointer, reference_path

MAP_SCHEMAS = {"properties", "patternProperties", "$defs", "dependentSchemas"}
LIST_SCHEMAS = {"allOf", "anyOf", "oneOf", "prefixItems"}
SINGLE_SCHEMAS = {"items", "additionalProperties", "unevaluatedProperties", "unevaluatedItems", "contains",
                  "propertyNames", "not", "if", "then", "else"}
KEYWORDS = MAP_SCHEMAS | LIST_SCHEMAS | SINGLE_SCHEMAS | {
    "type", "enum", "const", "required", "dependentRequired", "minProperties", "maxProperties",
    "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf", "minLength",
    "maxLength", "pattern", "minItems", "maxItems", "uniqueItems", "minContains", "maxContains", "format",
    "title", "description", "default", "examples", "deprecated", "$comment", "readOnly", "writeOnly"
}
FORMAT_CHECKER = FormatChecker()


@dataclass
class PreparedSchema:
    schema: dict | bool
    origins: dict
    references: list

    def source_pointer(self, parts):
        parts = tuple(parts)
        while parts not in self.origins and parts:
            parts = parts[:-1]
        return self.origins[parts]

    def errors(self, value):
        validator = Draft202012Validator(self.schema, format_checker=FORMAT_CHECKER, registry=Registry())
        return sorted(validator.iter_errors(value), key=lambda error: (pointer(error.absolute_path), error.message))


def prepare_schema(source, value, path):
    origins, references, budget = {}, [], [1200]

    def expand(schema, origin, location=(), ancestors=(), depth=0):
        budget[0] -= 1
        if depth > 32 or budget[0] < 0:
            raise ValueError("Schema exceeds expansion depth 32 or 1,200 schema nodes.")
        origins[location] = origin
        if type(schema) is bool:
            return schema
        if not isinstance(schema, dict):
            raise ValueError("Schema must be an object or boolean.")
        if "$ref" in schema:
            target = reference_path(schema["$ref"])
            if target in ancestors:
                raise ValueError("Recursive schemas need manual review in this version.")
            references.append({"from": f"{origin}/$ref", "to": target})
            resolved = lookup(source.data, target)
            siblings = {key: child for key, child in schema.items() if key != "$ref"}
            if not siblings:
                return expand(resolved, target, location, ancestors + (target,), depth + 1)
            return {"allOf": [expand(resolved, target, location + ("allOf", 0), ancestors + (target,), depth + 1),
                              expand(siblings, origin, location + ("allOf", 1), ancestors, depth + 1)]}
        result = {}
        for key, child in schema.items():
            child_origin = f"{origin}{pointer([key])}"
            child_location = location + (key,)
            origins[child_location] = child_origin
            if key not in KEYWORDS and not key.startswith("x-"):
                raise ValueError(f"Unsupported schema keyword {key!r} at {child_origin}.")
            if key in {"readOnly", "writeOnly"} and child is not False:
                raise ValueError("Directional readOnly/writeOnly annotations require manual review.")
            if key == "format" and child not in FORMAT_CHECKER.checkers:
                raise ValueError(f"No installed checker for format {child!r}.")
            if key == "pattern":
                re.compile(child)
            if key in MAP_SCHEMAS:
                if not isinstance(child, dict):
                    raise ValueError(f"{key} must be an object.")
                result[key] = {name: expand(nested, f"{child_origin}{pointer([name])}", child_location + (name,), ancestors, depth + 1)
                               for name, nested in child.items()}
            elif key in LIST_SCHEMAS:
                if not isinstance(child, list):
                    raise ValueError(f"{key} must be an array.")
                result[key] = [expand(nested, f"{child_origin}/{index}", child_location + (index,), ancestors, depth + 1)
                               for index, nested in enumerate(child)]
            elif key in SINGLE_SCHEMAS:
                result[key] = expand(child, child_origin, child_location, ancestors, depth + 1)
            else:
                result[key] = child
        return result

    expanded = expand(value, path)
    try:
        Draft202012Validator.check_schema(expanded)
    except SchemaError as error:
        raise ValueError(f"Invalid JSON Schema: {error.message}") from error
    return PreparedSchema(expanded, origins, references)


def declared_fields(schema):
    if not isinstance(schema, dict):
        return set(), []
    names, patterns = set(schema.get("properties", {})), list(schema.get("patternProperties", {}))
    for keyword in ("allOf", "anyOf", "oneOf"):
        for branch in schema.get(keyword, []):
            branch_names, branch_patterns = declared_fields(branch)
            names.update(branch_names)
            patterns.extend(branch_patterns)
    return names, patterns
