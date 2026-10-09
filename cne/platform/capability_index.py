"""Local inverted capability index. Prose has no routing authority."""
import re
from collections import defaultdict
from cne.platform.utterances import MAX_QUERY


def tokens(text):
    return set(re.findall(r"[a-z0-9]+", str(text).casefold().replace("_", " ")))


class CapabilityIndex:
    def __init__(self, registry):
        self.registry = registry
        self.generation = None
        self.postings = {}
        self.usage = {}

    def refresh(self):
        if self.generation == self.registry.generation:
            return
        postings = defaultdict(set)
        for pack in self.registry.list_packs(enabled_only=True):
            m = pack.manifest
            texts = [m.id, *m.provided_capabilities, *m.schemas.get("ontology", [])]
            texts.extend(m.schemas.get("sources", []))
            texts.extend(m.schemas.get("slots", {}).keys())
            texts.extend(t.tool_id for t in m.deterministic_tools)
            for intent in m.schemas.get("intents", []):
                texts.extend(
                    [
                        intent["intent"],
                        intent.get("template", intent.get("pattern", "")),
                    ]
                )
            for text in texts:
                for term in tokens(text):
                    postings[term].add(pack.id)
        self.postings = dict(postings)
        self.generation = self.registry.generation

    def shortlist(self, query, k=5, modality=None, user_id="local_device"):
        if not 1 <= k <= 8:
            raise ValueError("Candidate K must be between 1 and 8")
        if len(query) > MAX_QUERY:
            raise ValueError("Request too long")
        self.refresh()
        scores = defaultdict(float)
        for term in tokens(query):
            ids = self.postings.get(term, ())
            for cid in ids:
                scores[cid] += 1 / len(ids)
        ranked = sorted(
            scores,
            key=lambda cid: (-scores[cid], -self.usage.get((user_id, cid), 0), cid),
        )
        return [
            self.registry.get_pack(cid)
            for cid in ranked
            if modality is None
            or modality in self.registry.get_pack(cid).manifest.modalities
        ][:k]

    def record_usage(self, user_id, capability_id):
        self.usage[user_id, capability_id] = (
            self.usage.get((user_id, capability_id), 0) + 1
        )


class CapabilityCandidateRetriever:
    def __init__(self, registry, k=5):
        self.index = CapabilityIndex(registry)
        self.k = k

    def retrieve(self, query, user_id="local_device"):
        return self.index.shortlist(query, self.k, user_id=user_id)
