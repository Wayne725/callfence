from copy import deepcopy
from hashlib import sha256
from importlib.resources import files
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from xml.etree.ElementTree import fromstring

from callfence.engine import check, compare, exit_code
from callfence.report import export_report, render_html, render_junit
from callfence.source import MAX_BYTES, Source, lookup, pointer, read_cases


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        example_dir = files("callfence").joinpath("examples")
        self.baseline = json.loads(example_dir.joinpath("baseline.json").read_text())
        self.candidate = json.loads(example_dir.joinpath("candidate.json").read_text())
        self.consumer = json.loads(example_dir.joinpath("consumer.json").read_text())

    def write(self, name, data):
        path = self.root / name
        path.write_text(json.dumps(data))
        return path

    def run_check(self, spec=None, consumer=None):
        return check(self.write("spec.json", spec or self.baseline), self.write("client.json", consumer or self.consumer))

    def body_case(self, schema, value, include_body=True):
        spec = deepcopy(self.baseline)
        spec["paths"] = {"/submit": {"post": {"responses": {"200": {"description": "OK"}},
                         "requestBody": {"required": True, "content": {"application/json": {"schema": schema}}}}}}
        case = {"id": "submit", "title": "Submit a sample", "method": "POST", "path": "/submit"}
        if include_body:
            case["body"] = value
        consumer = {"version": 1, "consumer": "Test consumer", "cases": [case]}
        return spec, consumer

    def test_baseline_accepts_all_nine_independent_samples(self):
        result = self.run_check()
        self.assertEqual(result["runs"][0]["summary"], {"passed": 9, "failed": 0, "blocked": 0})
        self.assertEqual(exit_code(result), 0)

    def test_candidate_has_seven_failures_one_unknown_one_pass(self):
        result = self.run_check(self.candidate)
        self.assertEqual(result["runs"][0]["summary"], {"passed": 1, "failed": 7, "blocked": 1})
        expected = {"catalog-list": "ROUTE_MISSING", "job-submit": "METHOD_MISSING",
                    "upload-confirm": "BODY_INVALID", "items-page": "PARAMETER_MISSING",
                    "order-courier": "BODY_INVALID", "batch-detail": "PARAMETER_INVALID",
                    "monthly-report": "AUTH_NOT_CHECKED", "delivery-method": "BODY_FIELD_UNDECLARED"}
        cases = {case["id"]: case for case in result["runs"][0]["cases"]}
        for case_id, code in expected.items():
            self.assertIn(code, {item["code"] for item in cases[case_id]["findings"]})
        self.assertEqual(cases["health-check"]["status"], "passed")
        self.assertEqual(exit_code(result), 1)

    def test_compare_labels_observed_regressions_and_unknown(self):
        result = compare(self.write("before.json", self.baseline), self.write("after.json", self.candidate), self.write("client.json", self.consumer))
        self.assertEqual(result["change_summary"], {"regression": 7, "fixed": 0, "stable": 1, "existing_failure": 0, "needs_review": 1})

    def test_fixed_baseline_still_fails_strict_gate(self):
        result = compare(self.write("before.json", self.candidate), self.write("after.json", self.baseline), self.write("client.json", self.consumer))
        self.assertEqual(result["change_summary"]["fixed"], 7)
        self.assertEqual(exit_code(result), 1)

    def test_existing_failures_are_not_new_regressions(self):
        result = compare(self.write("before.json", self.candidate), self.write("after.json", self.candidate), self.write("client.json", self.consumer))
        self.assertEqual(result["change_summary"]["existing_failure"], 7)
        self.assertEqual(result["change_summary"]["regression"], 0)

    def test_local_ref_evidence_points_to_original_component_keyword(self):
        case = self.run_check(self.candidate)["runs"][0]["cases"][2]
        finding = next(item for item in case["findings"] if item["code"] == "BODY_INVALID")
        self.assertEqual(finding["server"]["pointer"], "/components/schemas/UploadConfirmation/required")
        self.assertEqual(finding["server"]["value"], ["size_bytes"])
        self.assertEqual(finding["client"]["pointer"], "/cases/2/body")
        self.assertEqual(finding["references"][0]["to"], "/components/schemas/UploadConfirmation")

    def test_path_parameter_renaming_preserves_position_and_value(self):
        candidate = deepcopy(self.candidate)
        candidate["paths"]["/v1/batches/{id}"]["get"]["parameters"][0]["schema"]["maximum"] = 50
        self.assertEqual(self.run_check(candidate)["runs"][0]["cases"][5]["status"], "passed")

    def test_path_item_parameters_and_operation_override(self):
        spec = deepcopy(self.baseline)
        route = spec["paths"]["/v1/items"]
        route["parameters"] = [{"name": "limit", "in": "query", "required": True, "schema": {"maximum": 10}}]
        self.assertEqual(self.run_check(spec)["runs"][0]["cases"][3]["status"], "passed")

    def test_case_insensitive_header_names(self):
        spec = deepcopy(self.baseline)
        spec["paths"]["/v1/health"]["get"]["parameters"] = [{"name": "X-Trace", "in": "header", "required": True, "schema": {"type": "string"}}]
        consumer = deepcopy(self.consumer)
        consumer["cases"][7]["parameters"] = {"header": {"x-TRACE": "trace-42"}}
        self.assertEqual(self.run_check(spec, consumer)["runs"][0]["cases"][7]["status"], "passed")

    def test_default_does_not_make_required_parameter_optional(self):
        candidate = deepcopy(self.candidate)
        candidate["paths"]["/v1/items"]["get"]["parameters"][1]["schema"]["default"] = "start"
        self.assertEqual(self.run_check(candidate)["runs"][0]["cases"][3]["status"], "failed")

    def test_null_and_omitted_body_are_different(self):
        spec, consumer = self.body_case({"type": ["object", "null"]}, None)
        self.assertEqual(self.run_check(spec, consumer)["runs"][0]["cases"][0]["status"], "passed")
        del consumer["cases"][0]["body"]
        finding = self.run_check(spec, consumer)["runs"][0]["cases"][0]["findings"][-1]
        self.assertEqual(finding["code"], "BODY_MISSING")
        self.assertFalse(finding["client"]["present"])

    def test_boolean_schemas(self):
        for schema, expected in [(True, "passed"), (False, "failed")]:
            with self.subTest(schema=schema):
                spec, consumer = self.body_case(schema, {"sample": 1})
                self.assertEqual(self.run_check(spec, consumer)["runs"][0]["cases"][0]["status"], expected)

    def test_composition_and_ref_sibling_constraints(self):
        schema = {"$ref": "#/components/schemas/Amount", "maximum": 5}
        spec, consumer = self.body_case(schema, 8)
        spec["components"]["schemas"]["Amount"] = {"type": "integer", "minimum": 1}
        case = self.run_check(spec, consumer)["runs"][0]["cases"][0]
        self.assertEqual(case["status"], "failed")
        finding = next(item for item in case["findings"] if item["code"] == "BODY_INVALID")
        self.assertTrue(finding["server"]["pointer"].endswith("/schema/maximum"))

    def test_nested_array_and_anyof_validation(self):
        schema = {"type": "array", "items": {"anyOf": [{"type": "integer"}, {"type": "null"}]}}
        spec, consumer = self.body_case(schema, [1, None, "bad"])
        finding = next(item for item in self.run_check(spec, consumer)["runs"][0]["cases"][0]["findings"] if item["code"] == "BODY_INVALID")
        self.assertEqual(finding["client"]["value"], "bad")
        self.assertTrue(finding["client"]["pointer"].endswith("/body/2"))

    def test_known_format_is_enforced(self):
        spec, consumer = self.body_case({"type": "string", "format": "date"}, "2026-02-31")
        self.assertEqual(self.run_check(spec, consumer)["runs"][0]["cases"][0]["status"], "failed")

    def test_unsupported_features_are_blocked_not_passed(self):
        schemas = [{"type": "integer", "format": "int64"}, {"type": "object", "readOnly": True},
                   {"type": "string", "$id": "https://example.invalid/schema"},
                   {"type": "string", "mysteryValidation": True}, {"type": "string", "nullable": True},
                   {"type": "not-a-type"}, {"pattern": "["}]
        for schema in schemas:
            with self.subTest(schema=schema):
                spec, consumer = self.body_case(schema, "sample")
                self.assertEqual(self.run_check(spec, consumer)["runs"][0]["cases"][0]["status"], "blocked")

    def test_external_refs_never_open_network(self):
        for ref in ["https://example.invalid/schema.json", "file:///private/schema.json", "#namedAnchor"]:
            with self.subTest(ref=ref), patch("socket.socket", side_effect=AssertionError("Network access attempted")):
                spec, consumer = self.body_case({"$ref": ref}, {"value": 1})
                self.assertEqual(self.run_check(spec, consumer)["runs"][0]["cases"][0]["status"], "blocked")

    def test_recursive_and_missing_refs_are_blocked(self):
        for target in [{"$ref": "#/components/schemas/Loop"}, {"$ref": "#/missing"}]:
            spec, consumer = self.body_case(target, {})
            spec["components"]["schemas"]["Loop"] = {"$ref": "#/components/schemas/Loop"}
            self.assertEqual(self.run_check(spec, consumer)["runs"][0]["cases"][0]["status"], "blocked")

    def test_security_inheritance_and_anonymous_alternative(self):
        spec = deepcopy(self.baseline)
        spec["security"] = [{"bearer": []}]
        self.assertEqual(self.run_check(spec)["runs"][0]["summary"]["blocked"], 9)
        spec["paths"]["/v1/health"]["get"]["security"] = [{}]
        self.assertEqual(self.run_check(spec)["runs"][0]["cases"][7]["status"], "passed")

    def test_collection_parameters_and_explicit_serialization_block(self):
        for change, sample in [({"schema": {"type": "array"}}, [1, 2]), ({"style": "form"}, 20)]:
            spec, consumer = deepcopy(self.baseline), deepcopy(self.consumer)
            spec["paths"]["/v1/items"]["get"]["parameters"][0].update(change)
            consumer["cases"][3]["parameters"]["query"]["limit"] = sample
            self.assertEqual(self.run_check(spec, consumer)["runs"][0]["cases"][3]["status"], "blocked")

    def test_optional_body_can_be_absent(self):
        spec, consumer = self.body_case({"type": "object"}, {}, include_body=False)
        spec["paths"]["/submit"]["post"]["requestBody"]["required"] = False
        self.assertEqual(self.run_check(spec, consumer)["runs"][0]["cases"][0]["status"], "passed")

    def test_undeclared_field_policy_is_distinct_from_schema_validation(self):
        consumer = deepcopy(self.consumer)
        consumer["policy"]["declared_body_fields"] = False
        self.assertEqual(self.run_check(self.candidate, consumer)["runs"][0]["cases"][8]["status"], "passed")
        self.assertEqual(self.run_check(self.candidate)["runs"][0]["cases"][8]["status"], "failed")

    def test_undeclared_parameter_policy(self):
        consumer = deepcopy(self.consumer)
        consumer["cases"][7]["parameters"] = {"query": {"unused": "sample"}}
        self.assertEqual(self.run_check(consumer=consumer)["runs"][0]["cases"][7]["status"], "failed")
        consumer["policy"]["declared_parameters"] = False
        self.assertEqual(self.run_check(consumer=consumer)["runs"][0]["cases"][7]["status"], "passed")

    def test_malformed_client_metadata_and_empty_cases_rejected(self):
        mutations = [lambda c: c.update(version=True), lambda c: c.update(cases=[]),
                     lambda c: c["cases"].append(deepcopy(c["cases"][0])),
                     lambda c: c["cases"][0].update(expects={}),
                     lambda c: c["cases"][5].update(parameters={}),
                     lambda c: c["cases"][0].update(path="https://example.invalid"),
                     lambda c: c["cases"][0].update(parameters={"header": {"X-A": "1", "x-a": "2"}})]
        for mutation in mutations:
            consumer = deepcopy(self.consumer)
            mutation(consumer)
            with self.subTest(consumer=consumer), self.assertRaises(ValueError):
                read_cases(self.write("bad.json", consumer))

    def test_duplicate_keys_nonfinite_and_invalid_unicode_rejected(self):
        for text in ['{"a":1,"a":2}', '{"a":NaN}', '{"a":1e999}', '{"a":"\\u0001"}', '{"a":"\\ud800"}']:
            path = self.root / "bad.json"
            path.write_text(text)
            with self.subTest(text=text), self.assertRaises(ValueError):
                Source.read(path)

    def test_input_size_limit(self):
        path = self.root / "huge.json"
        path.write_bytes(b" " * (MAX_BYTES + 1))
        with self.assertRaises(ValueError):
            Source.read(path)

    def test_wrong_openapi_version_and_ambiguous_templates_rejected(self):
        for mutation in [lambda s: s.update(openapi="3.0.3"),
                         lambda s: s.update(openapi=[]), lambda s: s.update(jsonSchemaDialect={}),
                         lambda s: s["paths"].update({"/v1/batches/{other}": deepcopy(s["paths"]["/v1/batches/{batch_id}"])})]:
            spec = deepcopy(self.baseline)
            mutation(spec)
            with self.assertRaises(ValueError):
                self.run_check(spec)

    def test_input_bytes_unchanged_and_report_deterministic(self):
        spec, cases = self.write("spec.json", self.baseline), self.write("client.json", self.consumer)
        raw = (spec.read_bytes(), cases.read_bytes())
        first, second = check(spec, cases), check(spec, cases)
        self.assertEqual(first, second)
        self.assertEqual(raw, (spec.read_bytes(), cases.read_bytes()))
        self.assertEqual(first["client"]["sha256"], sha256(raw[1]).hexdigest())

    def test_json_pointer_escaped_names(self):
        data = {"a/b": {"~item": [42]}}
        path = pointer(["a/b", "~item", 0])
        self.assertEqual(path, "/a~1b/~0item/0")
        self.assertEqual(lookup(data, path), 42)

    def test_html_payload_cannot_close_data_script(self):
        consumer = deepcopy(self.consumer)
        consumer["consumer"] = '</script><img src=x onerror="alert(1)">&'
        html = render_html(self.run_check(consumer=consumer))
        self.assertNotIn(consumer["consumer"], html)
        self.assertIn("\\u003c/script\\u003e", html)
        self.assertIn("connect-src 'none'", html)

    def test_junit_counts_failures_and_unknowns_as_failures(self):
        xml = fromstring(render_junit(self.run_check(self.candidate)))
        suite = xml.find("testsuite")
        self.assertEqual(suite.attrib["tests"], "9")
        self.assertEqual(suite.attrib["failures"], "8")
        self.assertEqual(len(suite.findall("testcase/failure")), 8)

    def test_export_checksums_and_no_overwrite(self):
        report = self.run_check()
        output = export_report(report, self.root / "output")
        manifest = json.loads((output / "manifest.json").read_text())
        for name, digest in manifest["sha256"].items():
            self.assertEqual(sha256((output / name).read_bytes()).hexdigest(), digest)
        original = (output / "results.json").read_bytes()
        with self.assertRaises(ValueError):
            export_report(self.run_check(self.candidate), output)
        self.assertEqual((output / "results.json").read_bytes(), original)

    def test_cli_pass_fail_and_invalid_input_exit_codes(self):
        cases = self.write("client.json", self.consumer)
        for name, spec, code in [("good", self.baseline, 0), ("bad", self.candidate, 1), ("invalid", {"openapi": "3.0.3"}, 2)]:
            process = subprocess.run([sys.executable, "-m", "callfence", "check", str(self.write(f"{name}.json", spec)), str(cases),
                                      "--out", str(self.root / name)], capture_output=True, text=True)
            self.assertEqual(process.returncode, code, process.stdout + process.stderr)
            self.assertEqual((self.root / name).exists(), code != 2)

    def test_cli_compare_intentionally_broken_fixture_exits_one(self):
        process = subprocess.run([sys.executable, "-m", "callfence", "compare", str(self.write("before.json", self.baseline)),
                                  str(self.write("after.json", self.candidate)), str(self.write("client.json", self.consumer)),
                                  "--out", str(self.root / "compare")], capture_output=True, text=True)
        self.assertEqual(process.returncode, 1, process.stdout + process.stderr)
        self.assertIn('"regression": 7', process.stdout)

    def test_cli_demo_is_explicitly_not_a_gate(self):
        process = subprocess.run([sys.executable, "-m", "callfence", "demo", "--out", str(self.root / "demo")], capture_output=True, text=True)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertIn("intentionally fails", process.stdout)
        self.assertEqual(json.loads((self.root / "demo" / "manifest.json").read_text())["exit_code"], 1)
        self.assertTrue((self.root / "demo" / "inputs" / "consumer.json").exists())


if __name__ == "__main__":
    unittest.main()
