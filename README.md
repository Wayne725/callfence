# CallFence

**Check the requests your client actually describes, before the API contract changes underneath them.**

[繁體中文指南](docs/使用指南.md) · [Supported contract](docs/SPEC.md) · [Synthetic interactive report](docs/demo.html) · [Verification record](docs/VERIFICATION.md)

CallFence checks explicit consumer request samples against an OpenAPI 3.1 JSON snapshot. It reports route/method gaps, missing required parameters, invalid typed values and JSON body mismatches, with JSON Pointer evidence from both source files. Compare two snapshots to distinguish new sample failures, existing failures, fixes and cases needing manual review.

The motivating problem is ordinary but costly: backend tests pass while a web client calls the wrong URL or sends a field the backend silently ignores. The optional declared-field policy makes such undeclared top-level fields visible even when JSON Schema permits extra properties. **This is a separate consumer policy, not a claim that the server rejects or drops the field.**

It runs offline. No API calls, tokens, account or model are needed. Only synthetic examples are committed.

## Run the complete example

Python 3.11+:

```sh
git clone https://github.com/Wayne725/callfence.git
cd callfence
python -m venv .venv
source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install .
callfence demo --out runs/demo
```

Open `runs/demo/report.html` directly in a browser. No development server is necessary.

The synthetic web client describes **9 request cases**. All pass against the baseline. The candidate has **7 failed cases, 1 blocked case and 1 passing case**:

| Client sample | Candidate issue |
| --- | --- |
| List the catalog | Path removed |
| Submit a dispatch job | POST changed to PUT |
| Confirm an uploaded file | Required body field renamed |
| Load the next item page | New required query parameter |
| Create a courier order | Submitted enum value no longer allowed |
| Open dispatch batch 42 | Path value exceeds the new maximum |
| Load the monthly report | Authentication required; not checked |
| Check service health | Sample still passes |
| Keep the delivery choice | Top-level field no longer declared; consumer policy fails |

Switch between baseline and candidate, filter by outcome and inspect source evidence. A missing route points to the actual `paths` collection; it does not invent a declaration for an absent operation.

**`demo` returns 0 when the report is generated. It is not a CI gate.** The intentionally broken snapshot fails the actual check/compare commands:

```sh
callfence check runs/demo/inputs/baseline.json runs/demo/inputs/consumer.json --out runs/healthy
# exit 0
callfence compare runs/demo/inputs/baseline.json runs/demo/inputs/candidate.json \
  runs/demo/inputs/consumer.json --out runs/broken
# exit 1, with the report still written
```

## Describe a client request

An explicit manifest avoids pretending that a regex understands every JavaScript SDK, interceptor or dynamically constructed URL:

```json
{
  "version": 1,
  "consumer": "Dispatch web",
  "policy": {"declared_body_fields": true, "declared_parameters": true},
  "cases": [
    {
      "id": "create-order",
      "title": "Create a courier order",
      "method": "POST",
      "path": "/v1/orders",
      "body": {"shipping": "courier"}
    }
  ]
}
```

```sh
callfence check openapi.json consumer.json --out runs/current
callfence compare openapi-before.json openapi-after.json consumer.json --out runs/release
```

Include the API prefix in each path. Paths are exact templates: `/v1/batches/{batch_id}` matches a server template `/v1/batches/{id}` by placeholder position. Supply the sample's typed value in `parameters.path.batch_id`. A concrete URL `/v1/batches/42` does not stand in for a template. Query strings and base URLs are not embedded in `path`.

Parameters are grouped under `path`, `query`, `header` and `cookie`. Header names are case-insensitive. Parameter values are **typed JSON scalars**, such as `20`, not the serialized HTTP string `"20"`. Transport serialization is not tested. Path-level parameter declarations are inherited; operation-level declarations override the same name/location.

Presence matters: omitting `body` differs from `"body": null`. JSON bodies require the exact `application/json` content entry. This profile does not perform wildcard media negotiation.

## A gate that does not turn unknown into success

| Exit | Meaning |
| --- | --- |
| 0 | Every sample in every checked snapshot passed the supported checks |
| 1 | At least one sample failed or was blocked; report was produced |
| 2 | Invalid input, unreadable file or output error; no successful analysis is claimed |

`compare` checks both snapshots. A broken baseline continues to fail the gate even if the candidate fixes it. Resolve or explain the baseline problem before using it as acceptance evidence. Unsupported checks take precedence in a case's status (`blocked`), while known failures remain visible in its findings. Authentication, recursive/external references, directional annotations and unsupported schema features are never counted as passed.

Both optional policies default to `false`:

- `declared_body_fields`: submitted **top-level** object keys must be explicitly declared by `properties` or `patternProperties`, including declarations in composition branches. It does not recursively enforce named fields or infer whether a server silently drops data.
- `declared_parameters`: supplied parameter names must be declared in OpenAPI. This does not assert that an undeclared parameter is invalid HTTP.

## Deliverables

Every new output directory contains:

| File | Use |
| --- | --- |
| `report.html` | Self-contained case filtering, snapshot switching and source inspection |
| `results.json` | Findings, source values, JSON Pointers, hashes, policies and outcomes |
| `junit.xml` | CI test report; failed and blocked cases are failures |
| `manifest.json` | SHA-256 checksums and the analysis gate result |

The demo also copies its three synthetic inputs into `inputs/`; manifest checksums cover the three report files, not those copied inputs. Existing output directories are refused. Input files are never modified. Reports include supplied data, so use sanitized examples and handle reports according to the source data's sensitivity.

## Scope and evidence

Version 0.1.0 supports an explicit **request sample profile**, not the entire OpenAPI ecosystem. OpenAPI 3.1.0/3.1.1 JSON only; JSON Schema 2020-12 supported keywords are listed in [SPEC.md](docs/SPEC.md). Local JSON Pointer references preserve source provenance. No reference retrieval is performed. Unknown keywords, custom dialects, unknown formats, recursive schemas, `readOnly`/`writeOnly: true`, collection parameters and explicit serialization options require manual review.

Passing demonstrates only that the supplied examples fit the supported declarations. It does not prove all possible client calls are compatible. It does not execute HTTP, validate responses, verify authentication/scopes, inspect client source, honor `servers` base URLs, test redirects, test actual backend behavior or validate every unused OpenAPI field. It is not a full OpenAPI validator or an untrusted-input sandbox. Regexes and schema combinators still require trusted, bounded inputs.

Use a complete API diff tool such as [oasdiff](https://github.com/oasdiff/oasdiff) for broad specification-change analysis. CallFence supplies explicit consumer examples, observed outcomes and source evidence; runtime integration tests remain necessary.

## Verification

```sh
python -m unittest discover -s tests -v
```

Tests exercise the intentionally broken fixture and assert CLI exits, local-reference provenance, placeholder renaming, required defaults, null versus omission, compositions, formats, unsupported-feature blocking, no network retrieval, immutability, HTML escaping, JUnit and checksum outputs. See [verification record](docs/VERIFICATION.md) for actual execution results and limits.

## A bounded service this can support

For a web/mobile client and an API snapshot: identify representative calls, agree on declared-field policies, create a sanitized manifest, deliver the exception report and add a failing CI gate. Each failure comes with evidence for the client/backend maintainer. Capturing cases and exporting the real server's current specification are part of the engagement; this repository does not establish a client's full coverage or production reliability.

## Primary references

- [OpenAPI 3.1.1 specification](https://spec.openapis.org/oas/v3.1.1.html)
- [jsonschema validation and format checks](https://python-jsonschema.readthedocs.io/en/stable/validate/)
- [jsonschema reference handling](https://python-jsonschema.readthedocs.io/en/stable/referencing/)
- [oasdiff project](https://github.com/oasdiff/oasdiff)

MIT licensed. Built with AI assistance. Synthetic fixtures, tests and recorded checks describe the delivered behavior; no customer outcome or market-scarcity claim is made.
