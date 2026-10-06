"""Offline supervised LoRA training and GGUF export for Llama-family down projections.

This implements gradient updates to adapters only. It does not run RL or grant
deployment approval. Training inputs must be admitted, user-scoped replay records.
"""
from __future__ import annotations
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from cne.platform.learning import AdaptationCandidate


@dataclass(frozen=True)
class TrainingResult:
    candidate: AdaptationCandidate
    losses: tuple
    sample_count: int
    dataset_hash: str
    base_weights_unchanged: bool


class SupervisedLoRATrainer:
    def train(
        self,
        replay_store,
        capability_id,
        user_id,
        base_model_path,
        output_directory,
        adapter_id,
        version,
        model_id,
        steps=10,
        rank=4,
        learning_rate=1e-4,
        max_tokens=256,
    ):
        import torch
        import gguf
        from transformers import AutoModelForCausalLM, AutoTokenizer
        from peft import LoraConfig, TaskType, get_peft_model

        if steps <= 0 or rank <= 0 or max_tokens < 2:
            raise ValueError("Invalid training configuration")
        records = replay_store.sample_batch(capability_id, user_id=user_id)
        if not records:
            raise ValueError("No TRAINING_ELIGIBLE samples")
        # Only allowlisted semantic material enters training; no arbitrary contract
        # fields or raw queries are consumed. Reviewed DSL is the supervised target.
        texts = [
            f"Capability: {capability_id}\nSemantic plan:\n{r.semantic_dsl}"
            for r in records
        ]
        if any(not r.semantic_dsl for r in records):
            raise ValueError("Training requires reviewed semantic DSL")
        dataset_hash = hashlib.sha256(
            json.dumps(texts, sort_keys=True).encode()
        ).hexdigest()
        tokenizer = AutoTokenizer.from_pretrained(
            base_model_path, local_files_only=True, trust_remote_code=False
        )
        base = AutoModelForCausalLM.from_pretrained(
            base_model_path, local_files_only=True, trust_remote_code=False
        ).cpu()
        if base.config.model_type != "llama":
            raise ValueError(
                "GGUF export currently supports Llama-family down_proj only"
            )

        def digest(parameters):
            h = hashlib.sha256()
            for name, tensor in parameters:
                h.update(name.encode())
                h.update(tensor.detach().cpu().contiguous().numpy().tobytes())
            return h.hexdigest()

        # Hash after wrapping so parameter names stay identical for the comparison.
        model = get_peft_model(
            base,
            LoraConfig(
                task_type=TaskType.CAUSAL_LM,
                r=rank,
                lora_alpha=rank,
                target_modules=["down_proj"],
                lora_dropout=0,
                bias="none",
            ),
        )
        frozen = lambda: (
            (n, p) for n, p in model.named_parameters() if not p.requires_grad
        )
        before = digest(frozen())
        optimizer = torch.optim.AdamW(
            (p for p in model.parameters() if p.requires_grad), lr=learning_rate
        )
        model.train()
        losses = []
        for index in range(steps):
            batch = tokenizer(
                texts[index % len(texts)],
                return_tensors="pt",
                truncation=True,
                max_length=max_tokens,
            )
            if batch["input_ids"].shape[1] < 2:
                raise ValueError("Insufficient training tokens")
            optimizer.zero_grad(set_to_none=True)
            loss = model(**batch, labels=batch["input_ids"]).loss
            if not torch.isfinite(loss):
                raise ValueError("Non-finite training loss")
            loss.backward()
            optimizer.step()
            losses.append(float(loss.detach()))
        unchanged = before == digest(frozen())
        if not unchanged:
            raise RuntimeError("Frozen base model changed")
        root = Path(output_directory)
        root.mkdir(parents=True, exist_ok=True)
        path = root / "adapter.gguf"
        writer = gguf.GGUFWriter(str(path), "llama")
        writer.add_type(gguf.GGUFType.ADAPTER)
        writer.add_string(gguf.Keys.Adapter.TYPE, "lora")
        writer.add_float32(gguf.Keys.Adapter.LORA_ALPHA, float(rank))
        count = 0
        for name, tensor in model.named_parameters():
            if not tensor.requires_grad:
                continue
            match = re.search(
                r"layers\.(\d+)\.mlp\.down_proj\.lora_([AB])\.default\.weight$", name
            )
            if not match:
                raise ValueError(f"Unsupported adapter tensor: {name}")
            writer.add_tensor(
                f"blk.{match[1]}.ffn_down.weight.lora_{match[2].lower()}",
                tensor.detach().float().cpu().numpy(),
            )
            count += 1
        if not count:
            raise ValueError("No adapter tensors exported")
        writer.write_header_to_file()
        writer.write_kv_data_to_file()
        writer.write_tensors_to_file()
        writer.close()
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        candidate = AdaptationCandidate(
            adapter_id,
            version,
            capability_id,
            model_id,
            len(texts),
            artifact_path=str(path.resolve()),
            artifact_sha256=sha,
        )
        result = TrainingResult(
            candidate, tuple(losses), len(texts), dataset_hash, unchanged
        )
        from dataclasses import asdict

        (root / "training_report.json").write_text(json.dumps(asdict(result), indent=2))
        return result
