# Persistence and key management

Production construction requires a private storage root. Volatile repositories require explicit `mode="test", in_memory=True`. The factory gives the registry, permissions, identity, sessions, correction ledger, experiences, replay, semantic plan cache, state fabric, external-data cache, adapter metadata, and telemetry durable SQLite stores beneath that root.

Persistent CNE state stores only bounded JSON values with exact contracts, source fingerprints, dependency snapshots, and provenance. Opaque values, calls, constrained/equivalent contracts, and values with executable behavior stay ephemeral. A restart validates owner, memo identity, source fingerprints, contract type, dependencies, and data mutation before reuse; the CNE evaluator remains authoritative.

`EncryptedPayloadCodec` uses AES-GCM with owner and repository namespace as authenticated associated data. A host-provided `KeyProvider` and key id can be supplied in `PlatformRuntimeConfig`; the library does not generate key files. Without a provider, SQLite payloads are plaintext and deployments must protect the app-private storage root. Device integrations should use OS-backed key storage and define key rotation, backup, and deletion policies. SQLite metadata such as row counts and owner identifiers remains visible.
