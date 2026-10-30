# Frozen corpus byte attestation and checkout migration

Attested baseline: feature `4d586f0f8f0f4ef96941ef6e36e185d0ea377a66`, parent `440f5e9c16e2d08b815e81604e46f7821dc1dba2`. Neither asset differs between these commits. No records/questions/expected labels were inspected or regenerated to diagnose this issue. Git raw object bytes, file hashes and exact LF->CRLF transformation alone establish the discrepancy.

| Asset | Git blob | Canonical LF SHA-256 | Historical CRLF SHA-256 (old workflow) |
|---|---|---|---|
| `test_heldout_blind.jsonl` | `233dac27fa029a26782e0fe269c20eca4a2363f8` | `90bad5884125af7971318a8243be35e172679e73a86cbe5f2fbd0abf148f31ce` | `ed56f7665b1a05159460362f806cd56f712afedc948a0613c4024a2df309f3bd` |
| `dataset_summary.json` | `870c30d59693d77903f102ce33fd6bac7de98593` | `23d4052be450ccfa3ebee5cb36d600b0e3627762e963de3c9d1a0a013971b778` | `4c27bf9107c05dd68bed5d0209c7c0163e57ff622fa52c30fb8000e239ba1bf9` |

Full repository paths begin `cne/artifacts/p1_dataset/`. Digests were independently reproduced from `git cat-file` and match the audit's preexisting values. These constants are not hashes of regenerated/edited data. Review this mapping and baseline blob identity as part of the repair.

Policy: narrow `.gitattributes` sets `text eol=lf` for these two paths only ([Git documentation](https://git-scm.com/docs/gitattributes)). Verification requires both exact attested Git-object bytes and byte-identical actual execution checkout; it does not strip whitespace, parse/rewrite JSON or normalize files while checking. CRLF checkout is rejected even though historical CRLF provenance is recorded. Newly checking out the attributes makes the same LF bytes available on Linux and Windows. Existing Windows checkouts require an explicit narrow migration only after confirming their bytes are either the attested LF or the exact historical CRLF version; tampered content must not be overwritten.

`python -m cne.platform.frozen_integrity --root . --output artifacts/integrity.json` fails closed on changed Git reference/blob, changed/missing checkout, line-ending mismatch, missing required attributes or any other byte discrepancy. Adversarial tests use synthetic fixture data, not modified production corpus records. The workflow gate must remain fatal.
