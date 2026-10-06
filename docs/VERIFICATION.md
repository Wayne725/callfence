# Verification record

Date: 2026-10-06 · Version: 0.1.0

## Local behavior

35 unittest methods passed on macOS, Python 3.12.14 with jsonschema 4.26.0. Subcases cover invalid schemas, formats, references and input metadata; count is not coverage percentage.

Independent synthetic expectations: nine baseline samples pass. Candidate samples produce seven failures, one authentication-blocked case and one pass; compare records seven regressions, one needs-review case and one stable case. CLI checks assert actual process return codes 0/1/2. The broken candidate returns 1 and still writes evidence. Demo generation is explicitly separate and returns 0.

Other exercised boundaries include local-reference keyword provenance, ref-sibling conjunction, path placeholder renaming, inherited/overridden parameters, header case, required defaults, null versus omission, boolean schemas, arrays/composition, date formats, no network retrieval, recursive/missing refs, unsupported feature blocking, field policies, duplicate keys, finite numbers, input size, XML/Unicode restrictions, input immutability, HTML escaping, JUnit counts and output checksums/no overwrite.

## Installed package

Built `callfence-0.1.0-py3-none-any.whl` in an isolated build environment and installed it into the project virtual environment. Runtime dependencies had been installed from PyPI into that newly created environment. Ran the installed `callfence demo` command from `/private/tmp`, outside the source checkout; all packaged examples and HTML assets were present and the expected 9/7/1/1 result was reproduced.

Wheel SHA-256: `fc41722ea54db5a16c7158028e795b06a8a13d6a5e5ca3bd6c956e8f61168bf8`. This identifies the locally built package; no public PyPI release is claimed.

## Browser

The generated synthetic report opened in the Codex in-app browser. Case selection, baseline/candidate switching, needs-review filtering, search matches and empty search results were exercised. The upload case changed from baseline passed to candidate failed, and the authentication case displayed blocked. Browser console inspection returned no errors or warnings at that check.

Failed findings appear before successful checks in the final interface. The upload example's first finding displayed the missing size_bytes requirement and its original component pointer. Reversing the snapshots verified the needs-review metric remains one when the candidate itself passes all nine cases but its baseline contains an authentication-blocked case.

No mobile, Safari or real server behavior is claimed verified. Export-link download completion was not tested; results.json is already available in the output directory.

## Published checks

The first published 23-file tree exactly matched the locally tested tree: `091b39e4811ec05ca7cce6a3248593f339fe47df`. [GitHub Actions run 1](https://github.com/Wayne725/callfence/actions/runs/37403128712), commit `b5f105a7071345bca9e5cb57c37390bc4219e244`, passed on Ubuntu for Python 3.11, 3.12 and 3.13. Each job installed the package, ran all 35 tests, generated the demo, verified the healthy gate and asserted that the intentionally broken comparison exits 1. The final interface ordering/count refinement was checked separately in the browser as recorded above.

## Limits

Only synthetic samples were used. The test suite proves the specified examples and boundaries, not universal API compatibility or complete OpenAPI validity. No live API request, credential use, customer data, response check or production deployment occurred.
