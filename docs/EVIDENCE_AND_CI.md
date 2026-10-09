# Evidence and CI policy

A result report describes one test command and one JUnit file. It includes the source commit and tree, dirty-working-tree status digest, command, corpus digest, run id, timestamp, test counts, and JUnit digest. Separate test runs are never combined into one passing count. A dirty local run is useful implementation evidence but is not committed CI evidence.

The pull-request workflow runs the full test suite on a clean checkout and pins the realistic corpus source checksum. Its uploaded JUnit artifact is the authoritative run artifact for that CI job. GGUF smoke is optional and runs only on a configured self-hosted runner with a locally licensed asset; no model is downloaded by the workflow. Adapter-training and target-device memory or latency claims require separate reproducible reports and are not implied by the correctness suite.

A controller tournament must invoke the same controller, prompt builder, structured output schema, runtime adapter, bridge validation, permission checks, and CNE execution used in production. Keep the model asset SHA, source, revision, license, tokenizer/chat formatting, BOS/EOS policy, runtime version, and test corpus hashes with every result. Do not automatically select or promote a winner.
