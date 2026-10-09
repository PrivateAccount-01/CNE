"""Opt-in local GGUF runtime probe for a licensed, pre-provisioned asset."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import threading
import time

import psutil
from cne.platform.device import RuntimeBackend
from cne.platform.models import (
    LlamaCppRuntimeAdapter,
    ModelDescriptor,
    ModelKind,
    ModelRequest,
)


def run(output):
    path = Path(os.environ["CNE_GGUF_PATH"]).resolve()
    expected = os.environ["CNE_GGUF_SHA256"].lower()
    model_id = os.environ.get("CNE_GGUF_MODEL_ID", "licensed-smoke-model")
    license_id = os.environ.get("CNE_GGUF_LICENSE", "UNSPECIFIED")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != expected:
        raise ValueError("GGUF asset SHA-256 mismatch")
    descriptor = ModelDescriptor(
        model_id,
        ModelKind.TEXT_GENERATION,
        "asset:" + digest[:16],
        0,
        file_size_mb=path.stat().st_size / 1048576,
        estimated_ram_mb=max(256, path.stat().st_size / 1048576 * 2),
        preferred_backend=RuntimeBackend.CPU,
        asset_path=str(path),
        asset_sha256=digest,
        asset_bytes=path.stat().st_size,
        source_repository=os.environ.get("CNE_GGUF_SOURCE", "local-provisioned"),
        source_revision=os.environ.get("CNE_GGUF_REVISION", "unknown"),
        license=license_id,
        chat_template_mode="metadata",
    )
    runtime = LlamaCppRuntimeAdapter()
    process = psutil.Process()
    peak = [process.memory_info().rss]
    stop = threading.Event()

    def sample():
        while not stop.wait(0.01):
            try:
                peak[0] = max(peak[0], process.memory_info().rss)
            except psutil.Error:
                pass

    sampler = threading.Thread(target=sample, daemon=True)
    sampler.start()
    before = process.memory_info().rss
    load_start = time.perf_counter()
    runtime.load_model(descriptor, RuntimeBackend.CPU)
    load_ms = (time.perf_counter() - load_start) * 1000
    request = ModelRequest(
        "public-smoke",
        model_id,
        json.dumps({"request": "Return a JSON object with ready=true."}),
        {"max_tokens": 8, "temp": 0.0},
        timeout_s=30,
        user_scope="public-smoke",
        response_schema={
            "type": "object",
            "properties": {"ready": {"type": "boolean"}},
            "required": ["ready"],
            "additionalProperties": False,
        },
    )
    inference_start = time.perf_counter()
    result = runtime.infer(request)
    structured_output = json.loads(result.outputs)
    if structured_output != {"ready": True}:
        raise ValueError("Structured decoding did not satisfy the response schema")
    inference_ms = (time.perf_counter() - inference_start) * 1000
    prompt_format = result.metadata.get("prompt_format")
    runtime.unload_model(model_id)
    stop.set()
    sampler.join()
    report = {
        "status": "PASSED",
        "scope": "single licensed GGUF CPU structured-decoding smoke; no quality or device claims",
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "host": platform.platform(),
        "model": {
            "id": descriptor.model_id,
            "version": descriptor.version,
            "sha256": digest,
            "bytes": descriptor.asset_bytes,
            "source_repository": descriptor.source_repository,
            "source_revision": descriptor.source_revision,
            "license": descriptor.license,
        },
        "runtime": "llama-cpp-python/CPU",
        "prompt_format": prompt_format,
        "load_latency_ms": load_ms,
        "inference_latency_ms": inference_ms,
        "ttft_ms": result.metadata.get("ttft_ms"),
        "tokens_generated": result.tokens_generated,
        "tokens_per_second": result.metadata.get("tokens_per_second"),
        "rss_before_bytes": before,
        "rss_peak_sampled_bytes": peak[0],
        "rss_delta_to_peak_bytes": max(0, peak[0] - before),
        "structured_output": structured_output,
    }
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    Path(output).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="gguf-smoke.json")
    args = parser.parse_args()
    print(json.dumps(run(args.output), indent=2))


if __name__ == "__main__":
    main()
