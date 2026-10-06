# CNE Security & Permission Model

## Current implementation evidence (2026-10-06)

Implementation status: durable application guards and restricted Linux workers IMPLEMENTED. Windows uses a WSL Ubuntu transport to the same bubblewrap worker; unsupported hosts fail closed.

Manifest permissions are requested, not granted. Authority grants bind exact user/resource scope and expire. Registration, enable and rollback validate package/dependency prerequisites. PermissionBroker checks grants before reading files and restricts resolved paths to host-configured capability/user roots. Offline network authorization fails even after a grant. Executor rechecks permissions before cached execution and tool dispatch. IdentityAuthority persists hashed expiring bearer tokens; a trusted login service issues them and execute_authenticated resolves the owner. Host login authentication must precede token issuance; callers must never accept a user/pack identity from untrusted tool arguments.

Adversarial tests attempt Bob-to-Alice session/correction/experience access, cross-pack private-store access, undeclared/ungranted file/network access, root escape and corrupt package/model hashes. Production signature verification fails closed unless configured with a trusted signature verifier. Ed25519TrustStore persists domain-bound public keys and revocations, signs canonical manifests and verifies installed packages. Enterprise key distribution is outside this local service.

Only host-configured first-party IDs run tools in process. Other installed tools run in a bubblewrap process with a read-only package mount, private network namespace, cleared environment and bounded resources/output. A real Windows-to-WSL probe denied host-file and network access. Android permission integration remains unimplemented. Filesystem checks retain host filesystem race semantics; the probe is not a complete sandbox security audit.

---

## 1. Principles of Security

1. **Default Deny:** Capabilities have zero access to device resources, hardware sensors, local storage, or network sockets by default.
2. **Deterministic Enforcement:** All permission verifications occur in deterministic platform code. Language models, planners, and prompts have zero authority to grant, alter, or bypass permissions.
3. **State Isolation:** Each capability pack is assigned private isolated storage. Pack A cannot inspect, read, or modify Pack B's private state without an explicit shared state declaration.
4. **Signature & Hash Verification:** Every capability package (`.cap`) must be hash-verifiable against its manifest `package_hash` and cryptographic signature before registration.

---

## 2. Declared Permission Taxonomy

| Permission Identifier | Description | Scope & Constraints |
|:---|:---|:---|
| `filesystem:read` | Read local files | Scoped to pack's data directory or user-selected folder |
| `filesystem:write` | Write local files | Scoped to pack's sandbox directory |
| `network:http` | Outbound HTTP requests | Physically blocked unless capability is `LOCAL_COMPUTE_NETWORK_DATA` |
| `camera` | Frame capture from device camera | Requires active user consent; image processed locally |
| `microphone` | Audio recording | For local ASR speech capabilities |
| `calendar:read` | Calendar event queries | Read-only access to local calendar store |
| `calendar:write` | Calendar event modification | User-confirmed appointment scheduling |
| `contacts:read` | Address book inspection | Contact name resolution |
| `financial_data:read`| Access to local transaction ledgers | Highly sensitive; audited access log |
| `financial_data:write`| Modification of financial ledgers | Requires explicit confirmation and contract verification |
| `location` | Device GPS / coarse location | Local proximity search |
| `sensors` | Step counter, heart rate, accelerometer | Fitness and telemetry packs |

---

## 3. Sandboxing & Cross-Capability Isolation

- **Process Boundaries:** While first-party capability packs can execute in-process in the initial reference implementation, all capability code interacts exclusively through typed, abstract interfaces.
- **Worker Process Isolation:** Third-party packs execute in restricted worker processes with unprivileged system tokens.
- **Tenant Separation:** Multi-user state isolation ensures user A's computational cache, sessions, and corrections cannot leak to user B under any circumstances.
