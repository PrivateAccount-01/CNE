"""
Unit tests for RealisticCorpusGenerator (Phase P0.7 §6).
Validates:
1. Total corpus size >= 1,500 queries (1,550 queries).
2. Category shares: template_canonical (7), llm_paraphrase (>=60%), adversarial (>=20%).
3. Multi-batch tagging: >= 3 independent generation batches for paraphrases (batch_1, batch_2, batch_3).
4. Structured adversarial families: 6 distinct families (A1-A6) with >= 15 examples each.
5. All 7 topologies represented including structural outlier.
"""
from cne.bench.corpus.realistic_corpus_generator import RealisticCorpusGenerator


def test_realistic_corpus_size_and_composition():
    corpus = RealisticCorpusGenerator.generate_corpus()
    queries = corpus["queries"]
    meta = corpus["metadata"]

    assert len(queries) >= 1500
    assert len(queries) == 1550

    categories = {}
    batches = {}
    topologies = {}
    adv_families = {}

    for q in queries:
        cat = q["category"]
        categories[cat] = categories.get(cat, 0) + 1

        b = q["generation_batch"]
        batches[b] = batches.get(b, 0) + 1

        topo = q["intended_topology"]
        topologies[topo] = topologies.get(topo, 0) + 1

        adv = q.get("adversarial_family")
        if adv:
            adv_families[adv] = adv_families.get(adv, 0) + 1

    # Check category shares
    assert categories["template_canonical"] == 7
    assert categories["llm_paraphrase"] >= 900  # >= 60% of 1500
    assert categories["adversarial"] >= 300     # >= 20% of 1500
    assert categories["out_of_distribution"] >= 200

    # Check 3 independent generation batches for paraphrases
    assert "batch_1" in batches and batches["batch_1"] == 330
    assert "batch_2" in batches and batches["batch_2"] == 330
    assert "batch_3" in batches and batches["batch_3"] == 330

    # Check 6 adversarial families (A1-A6) with >= 15 examples each
    for fam in ["A1", "A2", "A3", "A4", "A5", "A6"]:
        assert fam in adv_families, f"Missing adversarial family {fam}"
        assert adv_families[fam] >= 15, f"Adversarial family {fam} has {adv_families[fam]} < 15 examples"

    # Check all 7 topologies represented
    for t in RealisticCorpusGenerator.TOPOLOGIES:
        assert t in topologies
        assert topologies[t] > 50

    assert "cross_source_join_aggregate" in topologies
