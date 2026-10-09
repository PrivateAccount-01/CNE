"""Audited correction promotion and deterministic, bounded planning constraints."""
from dataclasses import asdict, replace
import copy, hashlib, json, time, uuid
from cne.platform.memory import (
    CorrectionRecord,
    AuditStatus,
    RedactionPolicy,
    request_fingerprint,
)
from cne.platform.errors import SemanticPlanError


class CorrectionReviewService:
    def __init__(self, store, experiences=None, verifiers=None):
        self.store = store
        self.experiences = experiences
        self.verifiers = verifiers or {}
        self.store.db.execute(
            "CREATE TABLE IF NOT EXISTS correction_transitions (id INTEGER PRIMARY KEY, correction TEXT, owner TEXT, before_state TEXT, after_state TEXT, evidence TEXT, timestamp REAL)"
        )
        self.store.db.commit()

    def submit_user_feedback(
        self, user_id, experience_id, query, feedback, constraint, kind="factual"
    ):
        if self.experiences is None:
            raise ValueError("Request trajectory repository required")
        exp = self.experiences.get(user_id, experience_id)
        if exp is None or len(exp.capability_ids) != 1:
            raise ValueError("One actual capability trajectory required")
        if exp.input_fingerprint != request_fingerprint(query, exp.capability_ids):
            raise ValueError("Request fingerprint mismatch")
        CorrectionConstraintApplier.validate(constraint)
        cid = exp.capability_ids[0]
        rec = CorrectionRecord(
            uuid.uuid4().hex,
            exp.input_fingerprint,
            query,
            cid,
            json.dumps(exp.model_versions, sort_keys=True),
            exp.controller_version,
            exp.error_classification or "SEMANTIC_PLAN_ERROR",
            exp.semantic_dsl,
            feedback,
            user_feedback=feedback,
            user_id=user_id,
            capability_version=exp.capability_versions[cid],
            semantic_shape=exp.semantic_shape,
            intent=exp.intent,
            tool_versions=exp.tool_versions,
            constraint=copy.deepcopy(constraint),
            correction_kind=kind,
            experience_id=exp.experience_id,
        )
        with self.store.db:
            self.store.add_correction(rec, commit=False)
            self._event(rec, None, AuditStatus.UNVERIFIED, "user assertion")
        return rec

    def _event(self, rec, before, after, evidence):
        self.store.db.execute(
            "INSERT INTO correction_transitions VALUES (NULL,?,?,?,?,?,?)",
            (
                rec.record_id,
                rec.user_id,
                before,
                after,
                hashlib.sha256(evidence.encode()).hexdigest(),
                time.time(),
            ),
        )

    def _transition(self, user_id, record_id, status, evidence="", global_scope=False):
        rec = self.store.get_correction(user_id, record_id)
        if rec is None:
            raise KeyError(record_id)
        if rec.audit_status in (AuditStatus.REJECTED, AuditStatus.SUPERSEDED):
            raise ValueError("Terminal correction state")
        before = rec.audit_status
        rec = replace(
            rec,
            audit_status=status,
            verifier_evidence=evidence or rec.verifier_evidence,
            scope="global" if global_scope else rec.scope,
        )
        with self.store.db:
            self.store.add_correction(rec, commit=False)
            self._event(rec, before, status, evidence)
        return rec

    def promote_user_scoped(self, user_id, record_id):
        rec = self.store.get_correction(user_id, record_id)
        if (
            rec is None
            or rec.correction_kind != "preference"
            or rec.constraint.get("kind") != "slot_preference"
        ):
            raise ValueError("Only a scoped preference may bypass factual verification")
        return self._transition(
            user_id, record_id, AuditStatus.USER_SCOPED, "owner preference"
        )

    def verify(self, user_id, record_id, verifier_ids, global_scope=False):
        if isinstance(verifier_ids, str):
            verifier_ids = [verifier_ids]
        if len(set(verifier_ids)) < (2 if global_scope else 1):
            raise ValueError("Independent verifier authorities required")
        rec = self.store.get_correction(user_id, record_id)
        evidence = []
        examples = []
        for name in verifier_ids:
            if name not in self.verifiers:
                raise PermissionError("Untrusted verifier")
            result = self.verifiers[name](copy.deepcopy(rec))
            if (
                not isinstance(result, dict)
                or result.get("passed") is not True
                or not result.get("evidence")
            ):
                raise ValueError("Independent verification failed")
            evidence.append({"authority": name, "evidence": result["evidence"]})
            if result.get("training_example") is not None:
                examples.append(
                    self.validate_training_example(result["training_example"])
                )
        if examples and (
            len(examples) != len(verifier_ids)
            or any(x != examples[0] for x in examples)
        ):
            raise ValueError(
                "Independent authorities must approve the same training example"
            )
        rec = self._transition(
            user_id,
            record_id,
            AuditStatus.VERIFIED,
            json.dumps(evidence, sort_keys=True),
            global_scope,
        )
        if examples:
            rec.training_example = examples[0]
            self.store.add_correction(rec)
            if self.experiences is not None and rec.experience_id:
                exp = self.experiences.get(user_id, rec.experience_id)
                if exp:
                    from dataclasses import replace

                    self.experiences.save(replace(exp, training_example=examples[0]))
        return rec

    @staticmethod
    def validate_training_example(example):
        required = {
            "sanitized_request",
            "intent",
            "slot_schema_hash",
            "incorrect_plan_sha256",
            "correct_plan",
            "provenance",
            "privacy_approved",
        }
        if (
            not isinstance(example, dict)
            or set(example) != required
            or example["privacy_approved"] is not True
        ):
            raise ValueError("Reviewed training example schema required")
        if not all(
            isinstance(example[k], str) and 0 < len(example[k]) <= 4096
            for k in (
                "sanitized_request",
                "intent",
                "slot_schema_hash",
                "incorrect_plan_sha256",
                "correct_plan",
                "provenance",
            )
        ):
            raise ValueError("Invalid training example field")
        from cne.platform.memory import RedactionPolicy

        if (
            RedactionPolicy().redact(example["sanitized_request"])
            != example["sanitized_request"]
        ):
            raise ValueError("Training request representation contains private data")
        from cne.platform.dsl import SemanticDSLParser

        compiled = SemanticDSLParser.compile_dsl(
            example["correct_plan"], intent=example["intent"]
        )
        if not compiled.is_valid:
            raise ValueError("Verified training target is invalid CNE DSL")
        return dict(example)

    def reject(self, user_id, record_id, reason):
        return self._transition(user_id, record_id, AuditStatus.REJECTED, reason)

    def supersede(self, user_id, record_id, replacement_id):
        other = self.store.get_correction(user_id, replacement_id)
        if other is None or other.audit_status not in (
            AuditStatus.USER_SCOPED,
            AuditStatus.VERIFIED,
        ):
            raise ValueError("Approved replacement required")
        return self._transition(
            user_id, record_id, AuditStatus.SUPERSEDED, replacement_id
        )


class CorrectionConstraintApplier:
    KINDS = {
        "slot_normalization",
        "slot_preference",
        "routing",
        "intent",
        "invalid_plan",
    }

    @classmethod
    def validate(cls, constraint):
        if not isinstance(constraint, dict) or constraint.get("kind") not in cls.KINDS:
            raise ValueError("Unsupported correction constraint")
        if set(constraint) - {
            "kind",
            "slot",
            "from",
            "to",
            "capability_id",
            "intent",
            "plan_sha256",
        }:
            raise ValueError("Correction cannot override authority")
        if len(json.dumps(constraint)) > 2048:
            raise ValueError("Constraint too large")

    def apply_slots(self, values, matches, scope, capability_id, intent):
        result = dict(values)
        applied = []
        for match in matches:
            r = match.correction
            c = r.constraint
            if r.audit_status not in (AuditStatus.VERIFIED, AuditStatus.USER_SCOPED):
                continue
            if r.user_id != scope and r.scope != "global":
                continue
            if r.capability_id != capability_id or (r.intent and r.intent != intent):
                continue
            self.validate(c)
            if c["kind"] not in ("slot_normalization", "slot_preference"):
                continue
            if (
                c["kind"] == "slot_normalization"
                and r.audit_status != AuditStatus.VERIFIED
            ):
                continue
            name = c.get("slot")
            # Guard on the old value prevents preference or factual edits bleeding into unrelated slots.
            if name in result and result[name] == c.get("from"):
                result[name] = c.get("to")
                applied.append(r.record_id)
        return result, applied

    def select_mapping(self, matches, corrections, scope):
        for match in corrections:
            r = match.correction
            c = r.constraint
            if r.audit_status != AuditStatus.VERIFIED or (
                r.user_id != scope and r.scope != "global"
            ):
                continue
            if c.get("kind") in ("routing", "intent"):
                selected = [
                    m
                    for m in matches
                    if m[0].id == c.get("capability_id", r.capability_id)
                    and m[1]["intent"] == c.get("intent", r.intent)
                ]
                if len(selected) == 1:
                    return selected
        return matches

    def validate_plan(self, dsl, matches, scope, capability_ids):
        digest = hashlib.sha256(dsl.encode()).hexdigest()
        for match in matches:
            r = match.correction
            if (
                r.audit_status == AuditStatus.VERIFIED
                and r.capability_id in capability_ids
                and (r.user_id == scope or r.scope == "global")
                and r.constraint.get("kind") == "invalid_plan"
                and r.constraint.get("plan_sha256") == digest
            ):
                raise SemanticPlanError("Verified invalid plan pattern")
