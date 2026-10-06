# Supported request contract

Version: 0.1.0 · Date: 2026-10-06

## Inputs

Local UTF-8 JSON (BOM accepted), maximum 2 MiB per file. Duplicate keys, non-finite numbers, invalid XML/Unicode characters, strings over 32,767 characters, depth over 48 and more than 50,000 nodes are rejected. Schema expansion is bounded to depth 32 and 1,200 schema nodes per validation. These are usability bounds, not a hostile-schema execution-time guarantee.

OpenAPI versions 3.1.0 and 3.1.1. `info.title`, `info.version` and object `paths` are required. Custom JSON Schema dialects are rejected. This is not complete OpenAPI document validation: used request declarations are inspected; unused response/callback/server/extension content is not certified.

The consumer document has integer `version: 1`, nonempty `consumer`, optional boolean `policy` keys and 1–100 `cases`. Case keys are limited to `id`, `title`, `method`, `path`, `parameters`, `body`, `media_type`. Unknown keys are rejected rather than silently ignoring a misspelled assertion. Case ids are unique. No credential field exists; avoid putting real credentials in header samples.

## Route and method

Methods: GET, PUT, POST, DELETE, OPTIONS, HEAD, PATCH, TRACE. Exact relative paths, preserving case, trailing slash and literal segments. Placeholder names are normalized by position; repeated names and malformed braces are rejected. Ambiguous server template shapes are invalid input. Concrete parameter URLs are not inferred into templates. API prefixes belong in the paths. `servers` base paths are not applied.

Path Item local Reference Objects are supported only without semantic siblings; summary/description annotations are allowed. Other combinations are blocked. Reference Objects for parameters/request bodies preserve resolved declaration locations. Local JSON Pointer references only; no file or HTTP retrieval. Cycles, named anchors and missing targets are blocked.

## Parameters

Path-level parameters are inherited; operation-level same-name/location parameters override them. Duplicate declarations at the same level block the case. Header names are case-insensitive. Every path placeholder must have a required server parameter and a typed sample value under the client placeholder's name.

Only typed JSON scalar samples and schema parameters. Content parameters, collection values and explicit style/explode/allowReserved/allowEmptyValue settings block the case. Default serialization is outside the checks too; no wire-format validation is claimed. Missing required parameters fail even with defaults. Optional missing parameter schemas are prepared to catch unsupported declarations, but their values are not validated because no value is supplied.

## JSON body and schemas

An omitted body differs from JSON null. Body supplied without a request declaration fails the declared-request profile. Only the exact `application/json` media entry and its schema are supported; wildcard negotiation/encodings are outside the profile. Optional omitted bodies do not traverse unused body schemas.

Validation uses jsonschema's Draft202012Validator after checking the schema and expanding local JSON Pointer references. `$ref` siblings retain conjunctive semantics through `allOf`; provenance maps validation keywords back to original source locations. Standard supported keywords:

- `type`, `enum`, `const`, `required`, `properties`, `patternProperties`, `$defs`, `additionalProperties`, `unevaluatedProperties`, `dependentRequired`, `dependentSchemas`, `minProperties`, `maxProperties`, `propertyNames`.
- `items`, `prefixItems`, `unevaluatedItems`, `contains`, `minContains`, `maxContains`, `minItems`, `maxItems`, `uniqueItems`.
- `minimum`, `maximum`, `exclusiveMinimum`, `exclusiveMaximum`, `multipleOf`, `minLength`, `maxLength`, `pattern`.
- `allOf`, `anyOf`, `oneOf`, `not`, `if`, `then`, `else`; boolean schemas.
- `format` only when an installed FormatChecker explicitly recognizes it; unknown formats block. Formats use the library's documented semantics, not server-specific validation.
- Annotation keywords `title`, `description`, `default`, `examples`, `deprecated`, `$comment`, and `x-` extensions do not become validation assertions.

`readOnly`/`writeOnly: false` are accepted; true or malformed directional annotations block. No directional required-field rewriting is attempted. `$id`, `$schema`, anchors/dynamic references, custom vocabularies, discriminator/nullable/XML hints and other unsupported keywords block. The supported global dialect does not imply every feature of that dialect is handled.

Up to 30 validation errors per value are recorded. Exceeding this adds a blocking truncation finding; the case never passes on incomplete evidence. Input regexes and schema combinators are not sandboxed or given a wall-clock timeout. Use trusted schema snapshots.

## Consumer policies

Both defaults are false. `declared_body_fields` checks top-level supplied object names against properties/patternProperties, including branches of allOf/anyOf/oneOf. This is an explicit field-inventory policy, not a claim about JSON Schema additionalProperties or branch-specific declaration guarantees. Nested objects are outside this inventory policy but still undergo ordinary supported schema validation.

`declared_parameters` checks supplied names against server declarations. An undeclared name can be legal HTTP and still violate the selected policy.

## Outcomes and gate

Case status: blocked if any unsupported/invalid declaration or authentication uncertainty exists; otherwise failed if a check fails; otherwise passed. All known findings are retained. Authentication is blocked when every declared security alternative requires a scheme. Operation `security: []` or an empty requirement alternative allows anonymous checks. Credentials, token validity, scopes and security-scheme definitions are not verified.

Compare preserves manifest case order and identity. Passed→failed is regression; failed→passed fixed; passed→passed stable; failed→failed existing_failure; blocked on either side needs_review. These labels describe supplied samples, not schema-set inclusion or full backward compatibility.

check/compare exit 0 only when all cases on all snapshots pass. Exit 1 includes failures and blocked cases. Input/output error returns 2. Demo generation returns 0 on successful export and explicitly announces that it is not a gate; manifest still contains the actual analysis exit code.

## Evidence and export

Findings contain client/server basename, input SHA-256, JSON Pointer, presence flag and original value. Missing data is represented as absent, not JSON null. Missing route/method evidence points to the declaration container. References record original and target pointers where schemas are traversed. Run id includes input bytes, policy, mode and tool version; it is a content identity, not a signature.

Output uses temporary staging then renames to a new directory. Existing outputs are refused. JSON disallows non-finite values; HTML data escapes script terminators and uses textContent/DOM APIs for all supplied text. CSP blocks connections. JUnit records blocked cases as failures and emits both snapshots in compare. Checksum manifest covers results.json/report.html/junit.xml. Demo copies inputs after report export; they are not included in the manifest or covered by the report export transaction.
