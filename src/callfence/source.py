from dataclasses import dataclass
from hashlib import sha256
import json
import math
from pathlib import Path
import re
from urllib.parse import unquote

METHODS = {"get", "put", "post", "delete", "options", "head", "patch", "trace"}
MAX_BYTES = 2 * 1024 * 1024


def pointer(parts):
    return "".join(f"/{str(part).replace('~', '~0').replace('/', '~1')}" for part in parts)


def tokens(path):
    if path == "":
        return []
    if not path.startswith("/") or re.search(r"~(?![01])", path):
        raise ValueError(f"Invalid JSON Pointer: {path}")
    return [part.replace("~1", "/").replace("~0", "~") for part in path[1:].split("/")]


def lookup(document, path):
    value = document
    for part in tokens(path):
        if isinstance(value, list):
            if not re.fullmatch(r"0|[1-9][0-9]*", part):
                raise KeyError(path)
            value = value[int(part)]
        elif isinstance(value, dict):
            value = value[part]
        else:
            raise KeyError(path)
    return value


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _bounded(value, depth=0, budget=None):
    budget = [50000] if budget is None else budget
    budget[0] -= 1
    if depth > 48 or budget[0] < 0:
        raise ValueError("JSON exceeds depth 48 or 50,000 nodes.")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("JSON numbers must be finite.")
    if isinstance(value, str) and (len(value) > 32767 or re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]", value)):
        raise ValueError("JSON text exceeds 32,767 characters or contains invalid XML/Unicode characters.")
    if isinstance(value, (dict, list)):
        if isinstance(value, dict):
            for key in value:
                _bounded(key, depth + 1, budget)
        values = value.values() if isinstance(value, dict) else value
        for child in values:
            _bounded(child, depth + 1, budget)


@dataclass(frozen=True)
class Source:
    name: str
    digest: str
    data: dict

    @classmethod
    def read(cls, path):
        path = Path(path)
        with path.open("rb") as handle:
            raw = handle.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError("Input exceeds 2 MiB.")
        def reject_constant(value):
            raise ValueError(f"Non-finite JSON number: {value}")
        data = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_unique_object,
                          parse_constant=reject_constant)
        _bounded(data)
        if not isinstance(data, dict):
            raise ValueError("Input JSON must be an object.")
        return cls(path.name, sha256(raw).hexdigest(), data)

    def evidence(self, path):
        try:
            value = lookup(self.data, path)
        except (KeyError, IndexError):
            return {"file": self.name, "sha256": self.digest, "pointer": path,
                    "present": False, "value": None}
        return {"file": self.name, "sha256": self.digest, "pointer": path,
                "present": True, "value": value}

    def resolve(self, value, path):
        chain, seen = [], set()
        while isinstance(value, dict) and "$ref" in value:
            if set(value) - {"$ref", "summary", "description"}:
                raise ValueError("OpenAPI Reference Object has unsupported siblings.")
            target = reference_path(value["$ref"])
            if target in seen or len(chain) >= 24:
                raise ValueError("Cyclic or excessive OpenAPI references.")
            seen.add(target)
            chain.append({"from": f"{path}/$ref", "to": target})
            value, path = lookup(self.data, target), target
        return value, path, chain


def reference_path(ref):
    if not isinstance(ref, str) or not ref.startswith("#/"):
        raise ValueError("Only local JSON Pointer references are supported; no retrieval is performed.")
    path = unquote(ref[1:])
    tokens(path)
    return path


def route_shape(path):
    if not isinstance(path, str) or not path.startswith("/") or "?" in path or "#" in path:
        raise ValueError("Paths must be relative, start with / and omit query/fragment.")
    names = re.findall(r"\{([^/{}]+)\}", path)
    shape = re.sub(r"\{[^/{}]+\}", "{}", path)
    if "{" in shape.replace("{}", "") or "}" in shape.replace("{}", "") or len(names) != len(set(names)):
        raise ValueError("Malformed or repeated path placeholders.")
    return shape, names


def read_spec(path):
    source = Source.read(path)
    data = source.data
    if not isinstance(data.get("openapi"), str) or data["openapi"] not in {"3.1.0", "3.1.1"}:
        raise ValueError("Supported OpenAPI versions: 3.1.0 and 3.1.1 (JSON only).")
    dialect = data.get("jsonSchemaDialect", "https://spec.openapis.org/oas/3.1/dialect/base")
    if not isinstance(dialect, str) or dialect not in {
        "https://spec.openapis.org/oas/3.1/dialect/base", "https://json-schema.org/draft/2020-12/schema"
    }:
        raise ValueError("Custom JSON Schema dialects are unsupported.")
    info = data.get("info")
    if not isinstance(info, dict) or not all(isinstance(info.get(key), str) for key in ("title", "version")):
        raise ValueError("OpenAPI info.title and info.version are required strings.")
    if not isinstance(data.get("paths"), dict):
        raise ValueError("OpenAPI paths must be an object.")
    shapes = set()
    for path, item in data["paths"].items():
        if path.startswith("x-"):
            continue
        shape, _ = route_shape(path)
        if shape in shapes or not isinstance(item, dict):
            raise ValueError("Paths contain ambiguous templates or a non-object Path Item.")
        shapes.add(shape)
    return source


def read_cases(path):
    source = Source.read(path)
    data = source.data
    if set(data) - {"version", "consumer", "policy", "cases"} or type(data.get("version")) is not int or data["version"] != 1:
        raise ValueError("Case document requires version 1 and supported top-level keys.")
    if not isinstance(data.get("consumer"), str) or not data["consumer"].strip():
        raise ValueError("A nonempty consumer name is required.")
    cases = data.get("cases")
    if not isinstance(cases, list) or not 1 <= len(cases) <= 100:
        raise ValueError("Provide between 1 and 100 request cases.")
    policy = data.get("policy", {})
    if not isinstance(policy, dict) or set(policy) - {"declared_body_fields", "declared_parameters"}:
        raise ValueError("Unsupported case policy.")
    if any(type(value) is not bool for value in policy.values()):
        raise ValueError("Policy values must be booleans.")
    ids = set()
    for case in cases:
        if not isinstance(case, dict) or set(case) - {"id", "title", "method", "path", "parameters", "body", "media_type"}:
            raise ValueError("Request case contains unsupported keys.")
        if any(not isinstance(case.get(key), str) or not case[key].strip() for key in ("id", "title", "method", "path")):
            raise ValueError("Case id, title, method and path must be nonempty strings.")
        if case["id"] in ids or case["method"].lower() not in METHODS:
            raise ValueError("Case ids must be unique and methods must be supported.")
        ids.add(case["id"])
        _, path_names = route_shape(case["path"])
        parameters = case.get("parameters", {})
        if not isinstance(parameters, dict) or set(parameters) - {"path", "query", "header", "cookie"}:
            raise ValueError("Parameters must be grouped by path/query/header/cookie.")
        for location, values in parameters.items():
            if not isinstance(values, dict) or any(not key for key in values):
                raise ValueError("Parameter groups must be objects with nonempty names.")
            if location == "header" and len({key.lower() for key in values}) != len(values):
                raise ValueError("Header names must be unique ignoring case.")
        if set(parameters.get("path", {})) != set(path_names):
            raise ValueError("Supply exactly one typed path value for each case placeholder.")
        if "media_type" in case and case["media_type"] != "application/json":
            raise ValueError("Case bodies support application/json only.")
        if "media_type" in case and "body" not in case:
            raise ValueError("media_type requires a body value.")
    return source
