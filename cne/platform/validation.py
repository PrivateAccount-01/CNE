"""Reproducible local integration smoke checks; never evaluates the blind corpus.

python -m cne.platform.validation --gguf PATH --base-model PATH --output PATH
Add --sandbox to exercise the native Linux / Windows-to-WSL worker boundary.
"""
from __future__ import annotations
import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from cne.platform.models import (
    LlamaCppRuntimeAdapter,
    ModelDescriptor,
    ModelKind,
    ModelRequest,
    ModelResidencyManager,
)


def validate(gguf_path, output_directory, base_model=None, sandbox=False):
    root = Path(output_directory)
    root.mkdir(parents=True, exist_ok=True)
    path = Path(gguf_path).resolve()
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    descriptor = ModelDescriptor(
        "validation-model",
        ModelKind.TEXT_GENERATION,
        digest,
        0,
        estimated_ram_mb=300,
        context_window=256,
        asset_path=str(path),
    )
    runtime = LlamaCppRuntimeAdapter()
    manager = ModelResidencyManager(1024, runtime)
    report = {
        "scope": "Integration smoke only; no model-quality, deployment-gate or Android claims",
        "asset_sha256": digest,
        "asset_bytes": path.stat().st_size,
    }
    try:
        manager.ensure_resident(descriptor, owner="validation")
        report["residency"] = manager.get_residency_snapshot()
        report["inference"] = []
        for user in ("public-development", "other-public-development"):
            result = runtime.infer(
                ModelRequest(
                    user,
                    descriptor.model_id,
                    "The answer is",
                    {"max_tokens": 8, "temp": 0.0},
                    user_scope=user,
                )
            )
            report["inference"].append(asdict(result))
        manager.release(descriptor.model_id, owner="validation")
        manager.evict_if_needed(1024)
        assert not runtime.is_loaded(descriptor.model_id)
        manager.ensure_resident(descriptor, owner="validation")
        report["reload_verified"] = runtime.is_loaded(descriptor.model_id)
        if base_model:
            import torch
            from cne.platform.learning import LearningReplayStore
            from cne.platform.memory import ExperienceRecord, request_fingerprint
            from cne.platform.training import SupervisedLoRATrainer

            torch.set_num_threads(2)
            torch.manual_seed(0)
            replay = LearningReplayStore()
            example = ExperienceRecord(
                "public-development",
                "validation",
                "",
                ["development.literal"],
                descriptor.model_id,
                "v = LIT value=42\ne = EMI in=v",
                "COMPILED",
                True,
                0,
                user_id="public-development",
                input_fingerprint=request_fingerprint("Public literal 42"),
            )
            replay.admit(
                example,
                "Public literal inspected",
                "Literal independently checked",
                privacy_approved=True,
            )
            trained = SupervisedLoRATrainer().train(
                replay,
                "development.literal",
                "public-development",
                base_model,
                root / "adapter",
                "validation-lora",
                "1",
                descriptor.model_id,
                steps=2,
                rank=2,
                max_tokens=64,
            )
            commits = []
            runtime.activate_adapter(
                descriptor,
                trained.candidate.artifact_path,
                lambda: commits.append(True),
            )
            adapted = runtime.infer(
                ModelRequest(
                    "adapted",
                    descriptor.model_id,
                    "The answer is",
                    {"max_tokens": 8, "temp": 0.0},
                    user_scope="public-development",
                )
            )
            assert commits == [True]
            assert (
                adapted.metadata["adapter_dependencies"][0][1]
                == trained.candidate.artifact_sha256
            )
            report["training"] = asdict(trained)
            report["adapted_inference"] = asdict(adapted)
        if sandbox:
            from cne.platform.sandbox import BubblewrapWorker, WSLBubblewrapWorker

            worker = (
                WSLBubblewrapWorker() if sys.platform == "win32" else BubblewrapWorker()
            )
            with tempfile.TemporaryDirectory() as directory:
                tool = Path(directory) / "probe.py"
                tool.write_text(
                    "def probe():\n import socket\n blocked=[]\n try: open('/etc/passwd').read()\n except OSError: blocked.append('host_files')\n s=socket.socket(); s.settimeout(1)\n try: s.connect(('1.1.1.1',53))\n except OSError: blocked.append('network')\n return blocked\n"
                )
                blocked = worker.run(directory, "probe:probe", [])
                assert blocked == ["host_files", "network"]
                report["sandbox_blocked"] = blocked
    finally:
        if runtime.is_loaded(descriptor.model_id):
            runtime.unload_model(descriptor.model_id)
    report["status"] = "PASSED"
    (root / "validation.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gguf", required=True)
    parser.add_argument(
        "--base-model", help="Local matching Llama-family Transformers base, optional"
    )
    parser.add_argument("--output", required=True)
    parser.add_argument("--sandbox", action="store_true")
    args = parser.parse_args()
    result = validate(args.gguf, args.output, args.base_model, args.sandbox)
    print(result["status"])


if __name__ == "__main__":
    main()
