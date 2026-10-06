from collections import Counter
from hashlib import sha256
import json
import re

from .schema import declared_fields, prepare_schema
from .source import METHODS, pointer, read_cases, read_spec, route_shape


def _finding(code, level, message, client, client_path, spec, spec_path, references=()):
    return {"code": code, "level": level, "message": message,
            "client": client.evidence(client_path), "server": spec.evidence(spec_path),
            "references": list(references)}


def _validate(value, schema, schema_path, client_path, label, client, spec, findings):
    prepared = prepare_schema(spec, schema, schema_path)
    errors = prepared.errors(value)
    for error in errors[:30]:
        findings.append(_finding(f"{label}_INVALID", "failed", error.message, client,
                                 f"{client_path}{pointer(error.absolute_path)}", spec,
                                 prepared.source_pointer(error.absolute_schema_path), prepared.references))
    if len(errors) > 30:
        findings.append(_finding("ERROR_LIMIT", "blocked", "More than 30 validation errors; evidence was truncated.",
                                 client, client_path, spec, schema_path))
    if not errors:
        findings.append(_finding(f"{label}_VALID", "passed", "This sample satisfies the supported schema.",
                                 client, client_path, spec, schema_path, prepared.references))
    return prepared


def _case_result(case, findings, operation_path=None):
    levels = {finding["level"] for finding in findings}
    status = "blocked" if "blocked" in levels else "failed" if "failed" in levels else "passed"
    return {"id": case["id"], "title": case["title"], "method": case["method"].upper(),
            "path": case["path"], "status": status, "operation_pointer": operation_path,
            "findings": findings}


def _check_case(case, index, client, spec):
    base, findings, operation_path = f"/cases/{index}", [], None
    spec_path = "/paths"
    try:
        shape, client_names = route_shape(case["path"])
        matches = [(path, item) for path, item in spec.data["paths"].items()
                   if not path.startswith("x-") and route_shape(path)[0] == shape]
        if not matches:
            findings.append(_finding("ROUTE_MISSING", "failed", "No matching path template is declared.",
                                     client, f"{base}/path", spec, "/paths"))
            return _case_result(case, findings)
        path, path_item = matches[0]
        spec_path = f"/paths{pointer([path])}"
        path_item, item_path, route_refs = spec.resolve(path_item, spec_path)
        if not isinstance(path_item, dict):
            raise ValueError("Resolved Path Item must be an object.")
        method = case["method"].lower()
        if method not in path_item:
            findings.append(_finding("METHOD_MISSING", "failed", f"{method.upper()} is not declared at this path.",
                                     client, f"{base}/method", spec, item_path, route_refs))
            return _case_result(case, findings)
        operation = path_item[method]
        spec_path = operation_path = f"{item_path}/{method}"
        if not isinstance(operation, dict) or not isinstance(operation.get("responses"), dict) or not operation["responses"]:
            raise ValueError("Operation must contain a nonempty responses object.")
        findings.append(_finding("OPERATION_FOUND", "passed", "Path template and HTTP method are declared.",
                                 client, f"{base}/path", spec, operation_path, route_refs))

        security_path = f"{operation_path}/security" if "security" in operation else "/security"
        security = operation.get("security", spec.data.get("security", []))
        if not isinstance(security, list) or any(not isinstance(value, dict) for value in security):
            raise ValueError("Security must be an array of requirement objects.")
        if security and {} not in security:
            findings.append(_finding("AUTH_NOT_CHECKED", "blocked", "Every declared security alternative requires authentication; credentials and scopes are not checked.",
                                     client, base, spec, security_path))

        merged = {}
        for owner, owner_path in ((path_item, item_path), (operation, operation_path)):
            entries = owner.get("parameters", [])
            if not isinstance(entries, list):
                raise ValueError("Parameters must be arrays.")
            seen = set()
            for position, entry in enumerate(entries):
                entry_path = f"{owner_path}/parameters/{position}"
                entry, entry_path, refs = spec.resolve(entry, entry_path)
                if not isinstance(entry, dict) or entry.get("in") not in {"path", "query", "header", "cookie"}:
                    raise ValueError("Parameter has an unsupported location.")
                name, location = entry.get("name"), entry["in"]
                if not isinstance(name, str) or not name:
                    raise ValueError("Parameter name must be nonempty.")
                if "required" in entry and type(entry["required"]) is not bool:
                    raise ValueError("Parameter required must be a boolean.")
                key = (location, name.lower() if location == "header" else name)
                if key in seen:
                    raise ValueError("Duplicate parameters at the same level.")
                seen.add(key)
                merged[key] = (entry, entry_path, refs)
        _, server_names = route_shape(path)
        path_mapping = dict(zip(server_names, client_names))
        declared_path = {name for location, name in merged if location == "path"}
        if declared_path != set(server_names) or any(not merged[("path", name)][0].get("required") for name in server_names):
            raise ValueError("Every server path placeholder needs exactly one required path parameter.")
        supplied = case.get("parameters", {})
        used = set()
        for (location, name), (entry, entry_path, refs) in merged.items():
            spec_path = entry_path
            if "schema" not in entry or "content" in entry:
                raise ValueError("Parameters require schema; content parameters need manual review.")
            if any(key in entry for key in ("style", "explode", "allowReserved", "allowEmptyValue")):
                raise ValueError("Explicit parameter serialization options need manual review.")
            client_name = path_mapping[name] if location == "path" else name
            values = supplied.get(location, {})
            actual_name = next((key for key in values if key.lower() == client_name), client_name) if location == "header" else client_name
            client_path = f"{base}/parameters/{location}{pointer([actual_name])}"
            if actual_name not in values:
                # Required-ness is a declaration even when the schema has a default.
                if entry.get("required", False):
                    findings.append(_finding("PARAMETER_MISSING", "failed", f"Required {location} parameter {entry['name']!r} is missing.",
                                             client, client_path, spec, f"{entry_path}/required", refs))
                prepare_schema(spec, entry["schema"], f"{entry_path}/schema")
                continue
            used.add((location, actual_name))
            value = values[actual_name]
            if isinstance(value, (dict, list)):
                findings.append(_finding("SERIALIZATION_NOT_CHECKED", "blocked", "Only typed scalar parameter samples are supported; collection serialization is not checked.",
                                         client, client_path, spec, entry_path, refs))
                continue
            _validate(value, entry["schema"], f"{entry_path}/schema", client_path, "PARAMETER", client, spec, findings)
        if client.data.get("policy", {}).get("declared_parameters", False):
            for location, values in supplied.items():
                for name in values:
                    if (location, name) not in used:
                        findings.append(_finding("PARAMETER_UNDECLARED", "failed", "The declared-parameters policy requires this supplied parameter to be named in OpenAPI.",
                                                 client, f"{base}/parameters/{location}{pointer([name])}", spec, operation_path))

        spec_path = operation_path
        has_body = "body" in case
        if "requestBody" not in operation:
            if has_body:
                findings.append(_finding("BODY_UNDECLARED", "failed", "This sample has a body but the operation declares no request body.",
                                         client, f"{base}/body", spec, operation_path))
        else:
            body_path = f"{operation_path}/requestBody"
            body, body_path, refs = spec.resolve(operation["requestBody"], body_path)
            spec_path = body_path
            if not isinstance(body, dict) or type(body.get("required", False)) is not bool:
                raise ValueError("Request Body must be an object with boolean required.")
            content = body.get("content")
            if not isinstance(content, dict) or not content:
                raise ValueError("Request Body requires nonempty content.")
            if not has_body:
                if body.get("required", False):
                    findings.append(_finding("BODY_MISSING", "failed", "A request body is required; omission is different from JSON null.",
                                             client, f"{base}/body", spec, f"{body_path}/required", refs))
            elif "application/json" not in content:
                findings.append(_finding("MEDIA_TYPE_MISSING", "failed", "The JSON sample's exact application/json media type is not declared; wildcard negotiation is outside this profile.",
                                         client, f"{base}/body", spec, f"{body_path}/content", refs))
            else:
                schema_path = f"{body_path}/content/application~1json/schema"
                media = content["application/json"]
                spec_path = schema_path
                if not isinstance(media, dict) or "schema" not in media:
                    raise ValueError("JSON request media type needs a schema for this profile.")
                if "encoding" in media:
                    raise ValueError("Request encoding requires manual review.")
                prepared = _validate(case["body"], media["schema"], schema_path, f"{base}/body", "BODY", client, spec, findings)
                if client.data.get("policy", {}).get("declared_body_fields", False) and isinstance(case["body"], dict):
                    names, patterns = declared_fields(prepared.schema)
                    for name in case["body"]:
                        if name not in names and not any(re.search(pattern, name) for pattern in patterns):
                            findings.append(_finding("BODY_FIELD_UNDECLARED", "failed", "The declared-body-fields policy requires this top-level field to be explicitly named (or pattern-declared). This is a policy check, not JSON Schema rejection.",
                                                     client, f"{base}/body{pointer([name])}", spec, schema_path, prepared.references))
    except (ValueError, KeyError, IndexError, TypeError, re.error, RecursionError) as error:
        findings.append(_finding("UNSUPPORTED_OR_INVALID", "blocked", str(error), client, base, spec, spec_path))
    return _case_result(case, findings, operation_path)


def _run(spec, client):
    cases = [_check_case(case, index, client, spec) for index, case in enumerate(client.data["cases"])]
    counts = Counter(case["status"] for case in cases)
    return {"cases": cases, "summary": {status: counts[status] for status in ("passed", "failed", "blocked")},
            "spec": {"file": spec.name, "sha256": spec.digest, "title": spec.data["info"]["title"], "version": spec.data["info"]["version"]}}


def _report(client, runs, mode):
    identity = {"version": "0.1.0", "mode": mode, "client": client.digest,
                "specs": [run["spec"]["sha256"] for run in runs], "policy": client.data.get("policy", {})}
    run_id = sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {"tool": "CallFence", "version": "0.1.0", "mode": mode, "run_id": run_id,
            "consumer": client.data["consumer"], "client": {"file": client.name, "sha256": client.digest},
            "policy": client.data.get("policy", {}), "runs": runs,
            "scope": "Offline request samples only. No HTTP execution, response validation, authentication proof or universal compatibility guarantee."}


def check(spec_path, cases_path):
    client, spec = read_cases(cases_path), read_spec(spec_path)
    return _report(client, [_run(spec, client)], "check")


def compare(baseline_path, candidate_path, cases_path):
    client = read_cases(cases_path)
    runs = [_run(read_spec(path), client) for path in (baseline_path, candidate_path)]
    report = _report(client, runs, "compare")
    changes = []
    for before, after in zip(runs[0]["cases"], runs[1]["cases"]):
        statuses = (before["status"], after["status"])
        if "blocked" in statuses:
            effect = "needs_review"
        else:
            effect = {("passed", "failed"): "regression", ("failed", "passed"): "fixed",
                      ("passed", "passed"): "stable", ("failed", "failed"): "existing_failure"}[statuses]
        changes.append({"id": before["id"], "effect": effect, "before": statuses[0], "after": statuses[1]})
    report["changes"] = changes
    counts = Counter(change["effect"] for change in changes)
    report["change_summary"] = {key: counts[key] for key in ("regression", "fixed", "stable", "existing_failure", "needs_review")}
    return report


def exit_code(report):
    return int(any(run["summary"]["failed"] or run["summary"]["blocked"] for run in report["runs"]))
