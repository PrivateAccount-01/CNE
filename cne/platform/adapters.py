"""Content-addressed adapter staging and crash-recoverable live activation."""
from __future__ import annotations
import hashlib
import os
from pathlib import Path
import tempfile


class AdapterDeploymentManager:
    def __init__(self, pipeline, runtime, asset_directory):
        self.pipeline = pipeline
        self.runtime = runtime
        self.root = Path(asset_directory).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, candidate):
        digest = candidate.artifact_sha256
        if (
            not digest
            or len(digest) != 64
            or any(c not in "0123456789abcdef" for c in digest)
        ):
            raise ValueError("An evaluated adapter artifact SHA-256 is required")
        return self.root / (digest + ".gguf")

    def stage(self, candidate):
        destination = self._path(candidate)
        data = Path(candidate.artifact_path).read_bytes()
        if hashlib.sha256(data).hexdigest() != candidate.artifact_sha256:
            raise ValueError("ADAPTER_HASH_MISMATCH")
        with tempfile.NamedTemporaryFile(dir=self.root, delete=False) as out:
            temporary = Path(out.name)
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temporary, destination)
        return destination

    def deploy(self, candidate, evaluation, descriptor):
        if candidate.target_model_id != descriptor.model_id:
            raise ValueError("MODEL_VERSION_MISMATCH")
        # Evaluation provenance is checked before touching runtime state.
        from cne.platform.learning import candidate_identity

        if (
            not evaluation.passed
            or evaluation.candidate_identity != candidate_identity(candidate)
            or self.pipeline.evaluator is None
            or self.pipeline.evaluator._artifacts.get(evaluation.artifact_hash())
            != evaluation
        ):
            return False
        path = self.stage(candidate)

        def commit():
            if not self.pipeline.deploy_candidate(candidate, evaluation):
                raise ValueError("Evaluation gate rejected activation")

        self.runtime.activate_adapter(descriptor, str(path), commit)
        return True

    def recover(self, capability_id, descriptor):
        active = self.pipeline.get_active(capability_id)
        if active is None:
            return False
        if active.target_model_id != descriptor.model_id:
            raise ValueError("MODEL_VERSION_MISMATCH")
        path = self._path(active)
        if hashlib.sha256(path.read_bytes()).hexdigest() != active.artifact_sha256:
            raise ValueError("ADAPTER_HASH_MISMATCH")
        self.runtime.activate_adapter(descriptor, str(path), lambda: None)
        return True

    def evaluate_active(
        self, capability_id, descriptor, candidate_fn, baseline_fn, baseline_version
    ):
        """Run independent regression cases and roll back a failing active adapter."""
        active = self.pipeline.get_active(capability_id)
        if active is None:
            raise ValueError("No active adapter")
        evaluation = self.pipeline.evaluate_candidate(
            active, candidate_fn, baseline_fn, baseline_version
        )
        if not evaluation.passed:
            self.rollback(capability_id, descriptor)
        return evaluation

    def rollback(self, capability_id, descriptor):
        import json
        from cne.platform.learning import AdaptationCandidate

        row = self.pipeline.db.execute(
            "SELECT previous FROM adapters WHERE capability=?", (capability_id,)
        ).fetchone()
        if not row or not row[0]:
            active = self.pipeline.get_active(capability_id)
            if active is not None:
                if active.target_model_id != descriptor.model_id:
                    raise ValueError("MODEL_VERSION_MISMATCH")

                def restore_base():
                    with self.pipeline.db:
                        self.pipeline.db.execute(
                            "DELETE FROM adapters WHERE capability=?", (capability_id,)
                        )

                self.runtime.activate_adapter(descriptor, None, restore_base)
            return None
        previous = AdaptationCandidate(**json.loads(row[0]))
        if previous.target_model_id != descriptor.model_id:
            raise ValueError("MODEL_VERSION_MISMATCH")
        path = self._path(previous)
        if hashlib.sha256(path.read_bytes()).hexdigest() != previous.artifact_sha256:
            raise ValueError("ADAPTER_HASH_MISMATCH")
        self.runtime.activate_adapter(
            descriptor, str(path), lambda: self.pipeline.rollback_adapter(capability_id)
        )
        return previous
