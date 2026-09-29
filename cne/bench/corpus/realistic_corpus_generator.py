"""
CNE Realistic Benchmark Corpus Generator (Phase P0.7).
Constructs a 1,550-query corpus with complete provenance, generation-batch tagging,
and structured adversarial families across 7 topologies.

Composition:
1. Template-canonical: 7 queries (1 per topology, baseline sanity check).
2. LLM-generated paraphrases: 990 queries (>=60%) across 3 independent generation batches:
   - batch_1: formal, precise phrasing (330 queries)
   - batch_2: conversational, colloquial phrasing (330 queries)
   - batch_3: compound, multi-clause phrasing (330 queries)
3. Adversarial families: 330 queries (>=20%) across 6 structured families (A1-A6, 55 each):
   - A1: Same wording, different dependency (sensors/accounts)
   - A2: Same wording, different OutcomeContract
   - A3: Small parameter change (micro-parameter sensitivity)
   - A4: Different wording, identical computation (shape invariance)
   - A5: Same topology, different cost class (cardinality 10 vs 100,000)
   - A6: Same topology, different effect set (Pure vs WriteExternal)
4. Out-of-distribution: 223 queries:
   - 123 unsupported domain requests (weather, crypto, travel, translation, recipe, code)
   - 50 ambiguous cross-domain queries
   - 50 low-confidence / fragment queries

Total: 1,550 queries. Deterministic via frozen seed.
"""
from __future__ import annotations

import random
from typing import Any, Dict, List, Optional


class RealisticCorpusGenerator:
    """
    Builds the 1,550-query realistic corpus with generation batch and provenance dimensions.
    """

    TOPOLOGIES = [
        "expense",
        "troubleshooting",
        "scheduling",
        "habit_fitness",
        "factual_decision",
        "recommendation",
        "cross_source_join_aggregate"
    ]

    @classmethod
    def generate_corpus(cls, seed: int = 42) -> Dict[str, Any]:
        rng = random.Random(seed)
        queries: List[Dict[str, Any]] = []

        # =====================================================================
        # 1. Template-Canonical Baseline (7 queries: 1 per topology)
        # =====================================================================
        canonical_queries = [
            ("p07_canon_expense", "expense", "Calculate total food spending over $100"),
            ("p07_canon_troubleshooting", "troubleshooting", "Diagnose telemetry alerts on node_1 with error threshold exceeding 5"),
            ("p07_canon_scheduling", "scheduling", "Schedule a meeting with alice for duration of 30 minutes"),
            ("p07_canon_habit_fitness", "habit_fitness", "Log my running workout activity and verify goal of 30 minutes"),
            ("p07_canon_factual_decision", "factual_decision", "Decide on deployment options with confidence above 0.75"),
            ("p07_canon_recommendation", "recommendation", "Recommend catalog items with rating above 4.0 for user_1"),
            ("p07_canon_join", "cross_source_join_aggregate", "Reconcile orders and inventory matching stock quantity exceeding 5")
        ]

        for qid, topo, text in canonical_queries:
            queries.append({
                "id": qid,
                "query_text": text,
                "category": "template_canonical",
                "generation_batch": "canonical",
                "intended_topology": topo,
                "expected_classification": "COMPILED",
                "adversarial_family": None,
                "slots": {}
            })

        # =====================================================================
        # 2. LLM-Generated Paraphrases (990 queries: 3 batches x 330 queries)
        # =====================================================================
        # Batch 1: Formal / technical style
        b1_templates = {
            "expense": [
                "Compute aggregate {cat} expenditure exceeding {thresh} dollars",
                "Sum financial transactions for category {cat} greater than {thresh}",
                "Calculate total {cat} disbursement above limit {thresh}",
                "Evaluate net {cat} expenses higher than threshold {thresh}",
                "Audit {cat} purchases where expenditure exceeds {thresh}"
            ],
            "troubleshooting": [
                "Execute diagnostic telemetry assessment on host {node} for error count > {thresh}",
                "Diagnose system health for {node} with incident threshold exceeding {thresh}",
                "Inspect diagnostic logs on {node} alerting when failures exceed {thresh}",
                "Perform automated troubleshooting on host {node} above error bound {thresh}",
                "Verify operational integrity of {node} against error limit {thresh}"
            ],
            "scheduling": [
                "Identify viable calendar appointment slot with {user} for duration {dur} minutes",
                "Schedule a formal calendar consultation with {user} requiring {dur} minutes",
                "Determine optimal meeting availability with {user} for {dur} minutes",
                "Book calendar slot for session with {user} allocated {dur} minutes",
                "Find mutual meeting availability with attendee {user} for duration {dur} min"
            ],
            "habit_fitness": [
                "Log daily {act} fitness workout session and verify target goal of {goal} minutes",
                "Record {act} training activity duration against threshold goal of {goal} minutes",
                "Audit {act} exercise performance against daily target goal of {goal} min",
                "Track {act} workout telemetry to confirm achievement of goal {goal} minutes",
                "Evaluate {act} fitness activity completion towards target {goal} min"
            ],
            "factual_decision": [
                "Decide on strategic {topic} alternatives with confidence parameter >= {conf}",
                "Evaluate policy options for {topic} requiring certainty threshold {conf}",
                "Formulate decision on {topic} selecting candidate with confidence exceeding {conf}",
                "Select optimal hypothesis for {topic} under confidence constraint {conf}",
                "Conduct factual decision analysis on {topic} with confidence >= {conf}"
            ],
            "recommendation": [
                "Retrieve top catalog recommendations with consumer rating >= {rate} for user {user}",
                "Generate personalized product suggestions exceeding rating {rate} for user {user}",
                "Recommend catalog inventory items meeting rating threshold {rate} for user {user}",
                "Query top rated merchandise recommendations above {rate} stars for user {user}",
                "Filter and suggest catalog offerings with rating exceeding {rate} for user {user}"
            ],
            "cross_source_join_aggregate": [
                "Reconcile orders and inventory ledgers for sku items with quantity exceeding {qty}",
                "Cross-reference orders and warehouse inventory data where batch quantity > {qty}",
                "Join customer orders with inventory stock to aggregate valuations above quantity {qty}",
                "Execute cross-source reconciliation of orders and inventory records exceeding {qty}",
                "Aggregate supply orders and warehouse inventory quantities higher than {qty}"
            ]
        }

        # Batch 2: Conversational / colloquial style
        b2_templates = {
            "expense": [
                "How much did I spend on {cat} over {thresh} bucks?",
                "Can you check what I spent on {cat} above {thresh}?",
                "Total up all my {cat} spending over {thresh} please",
                "Show me purchases for {cat} that went higher than {thresh}",
                "Give me the spending sum on {cat} past {thresh} dollars"
            ],
            "troubleshooting": [
                "Check if {node} has telemetry errors past {thresh}",
                "Run a quick troubleshoot on {node} if errors are above {thresh}",
                "Is {node} healthy or are telemetry error alerts past {thresh}?",
                "Diagnose what's wrong with {node} exceeding {thresh} error limit",
                "Look at {node} telemetry alerts and troubleshoot if errors > {thresh}"
            ],
            "scheduling": [
                "Set up a quick chat with {user} for {dur} minutes",
                "Find me a meeting slot with {user} lasting {dur} mins",
                "Can we schedule some time with {user} for {dur} minutes?",
                "Book a {dur} minute slot on my calendar with {user}",
                "Look for an open slot with {user} for a {dur} min meeting"
            ],
            "habit_fitness": [
                "Did I hit my {goal} minute {act} goal for workout today?",
                "Log my {act} workout and tell me if goal of {goal} min is reached",
                "Track today's {act} exercise toward my {goal} minute fitness goal",
                "Check my {act} workout minutes against the {goal} minute target",
                "Record my {act} habit and check if {goal} min goal achieved"
            ],
            "factual_decision": [
                "Help me decide on {topic} with confidence over {conf}",
                "Which option should we pick for {topic} at confidence {conf}?",
                "Evaluate the choices for {topic} with confidence above {conf}",
                "Need a decision on {topic} having confidence >= {conf}",
                "Make the call on {topic} with high confidence past {conf}"
            ],
            "recommendation": [
                "What items do you recommend for user {user} with rating over {rate}?",
                "Suggest some good catalog stuff rated above {rate} for user {user}",
                "Give user {user} product recommendations having rating over {rate}",
                "Show top recommended products rated past {rate} stars for user {user}",
                "Find me suggestions from catalog rated at least {rate} for user {user}"
            ],
            "cross_source_join_aggregate": [
                "Match orders and inventory to see stock totals over {qty}",
                "Join up the orders with inventory stock where quantity is over {qty}",
                "Cross-check orders against warehouse inventory with quantity exceeding {qty}",
                "Reconcile orders and inventory items that have quantity above {qty}",
                "Connect orders with inventory and sum values with quantity past {qty}"
            ]
        }

        # Batch 3: Compound / multi-clause style
        b3_templates = {
            "expense": [
                "I want to review my account records: calculate total spending on {cat} exceeding {thresh}",
                "Looking across monthly statements, please sum up all {cat} expenses higher than {thresh}",
                "To optimize my budget, show aggregate {cat} expenditure with values above {thresh}",
                "Perform an account audit and compute total {cat} purchase costs greater than {thresh}",
                "From our financial ledger, summarize total amount spent on {cat} exceeding {thresh}"
            ],
            "troubleshooting": [
                "Automated system patrol: inspect telemetry and diagnose failures on {node} exceeding {thresh}",
                "Under infrastructure alerting rules, troubleshoot host {node} when errors rise above {thresh}",
                "Run diagnostic telemetry analysis on {node} and remediate if error threshold exceeds {thresh}",
                "To prevent production incidents, diagnose telemetry alerts on {node} higher than {thresh}",
                "Verify system reliability metrics and troubleshoot {node} if critical errors exceed {thresh}"
            ],
            "scheduling": [
                "Coordinating team agenda: schedule an appointment slot with {user} for {dur} minutes",
                "Check availability across calendars and schedule a meeting with {user} lasting {dur} minutes",
                "To prepare for project sync, book a dedicated calendar slot with {user} for {dur} min",
                "Scan schedule for free intervals and arrange a consultation with {user} of {dur} minutes",
                "Schedule a working session with {user} ensuring required slot duration is {dur} minutes"
            ],
            "habit_fitness": [
                "Daily health routine: log my {act} workout session and confirm if goal {goal} min is met",
                "Fitness tracker update: record {act} exercise telemetry and verify target goal of {goal} min",
                "Review athletic activity: calculate total {act} workout time toward daily goal of {goal} minutes",
                "Tracking weekly wellness: record {act} fitness activity and evaluate if goal of {goal} min achieved",
                "Log {act} training minutes and verify whether workout goal of {goal} minutes was satisfied"
            ],
            "factual_decision": [
                "Policy review protocol: evaluate decision alternatives on {topic} requiring confidence {conf}",
                "Based on analytical evidence, decide on {topic} selecting candidates with confidence >= {conf}",
                "Conduct tradeoff study to choose optimal alternative for {topic} with confidence over {conf}",
                "Review hypothesis space and formulate decision on {topic} under confidence limit {conf}",
                "Structured decision workflow: evaluate options for {topic} having minimum confidence {conf}"
            ],
            "recommendation": [
                "Catalog curation engine: recommend top items and suggestions with rating above {rate} for user {user}",
                "Personalized shopping pipeline: query catalog and suggest products with rating over {rate} for user {user}",
                "Deliver customer recommendations: identify top catalog merchandise with rating exceeding {rate} for user {user}",
                "From consumer inventory, recommend highest scored items with rating above {rate} for user {user}",
                "Generate top item recommendations based on catalog ratings exceeding {rate} for attendee user {user}"
            ],
            "cross_source_join_aggregate": [
                "Supply chain reconciliation: cross-reference orders and inventory to sum items with quantity > {qty}",
                "Warehouse analytics: join orders with inventory stock and calculate values exceeding quantity {qty}",
                "Inventory control pipeline: reconcile orders and inventory databases where line quantity exceeds {qty}",
                "Perform cross-source data join between orders and inventory to total goods with quantity over {qty}",
                "Reconcile customer order records against warehouse inventory data for batch quantities above {qty}"
            ]
        }

        batches = [
            ("batch_1", b1_templates),
            ("batch_2", b2_templates),
            ("batch_3", b3_templates)
        ]

        categories = ["food", "travel", "utilities", "shopping", "entertainment", "health", "office", "electronics"]
        users = ["alice", "bob", "carol", "david", "emma", "frank", "grace"]
        activities = ["running", "cycling", "walking", "swimming", "gym", "cardio"]
        topics = ["deployment", "migration", "architecture", "caching", "failover", "scaling"]

        for b_name, b_tmpls in batches:
            # 330 queries per batch: 7 topologies * ~47 queries each = 329 + 1 = 330
            queries_per_topo = 47
            for t_idx, topo in enumerate(cls.TOPOLOGIES):
                tmpl_list = b_tmpls[topo]
                # extra 1 query on last topology so 47 * 7 + 1 = 330
                count = queries_per_topo + (1 if t_idx == len(cls.TOPOLOGIES) - 1 else 0)
                for i in range(count):
                    tmpl = tmpl_list[i % len(tmpl_list)]
                    qid = f"p07_para_{b_name}_{topo}_{i}"

                    cat = categories[rng.randint(0, len(categories) - 1)]
                    thresh = 25.0 + rng.randint(1, 50) * 10.0
                    node = f"node_{rng.randint(1, 20)}"
                    err_thresh = rng.randint(2, 15)
                    user = users[rng.randint(0, len(users) - 1)]
                    dur = rng.choice([15, 30, 45, 60, 90])
                    act = activities[rng.randint(0, len(activities) - 1)]
                    goal = rng.choice([20.0, 30.0, 45.0, 60.0])
                    topic = topics[rng.randint(0, len(topics) - 1)]
                    conf = round(0.65 + rng.random() * 0.30, 2)
                    rate = round(3.5 + rng.random() * 1.4, 1)
                    qty = rng.randint(2, 50)

                    text = tmpl.format(
                        cat=cat, thresh=thresh, node=node, user=user,
                        dur=dur, act=act, goal=goal, topic=topic,
                        conf=conf, rate=rate, qty=qty
                    )

                    queries.append({
                        "id": qid,
                        "query_text": text,
                        "category": "llm_paraphrase",
                        "generation_batch": b_name,
                        "intended_topology": topo,
                        "expected_classification": "COMPILED",
                        "adversarial_family": None,
                        "slots": {
                            "category": cat.capitalize(),
                            "threshold": thresh,
                            "system_id": node,
                            "error_threshold": err_thresh,
                            "user_id": user,
                            "duration": dur,
                            "activity_type": act,
                            "goal": goal,
                            "topic": topic,
                            "min_confidence": conf,
                            "min_rating": rate,
                            "min_quantity": qty
                        }
                    })

        # =====================================================================
        # 3. Adversarial Families (330 queries: 6 families x 55 queries)
        # =====================================================================
        # A1: Same wording, different dependency (sensors/accounts)
        for i in range(55):
            src_variant = f"sensor_cluster_{i % 5}"
            account_id = f"account_{100 + i}"
            text = f"Calculate total food spending over $100 for user account {account_id}"
            queries.append({
                "id": f"p07_adv_a1_{i}",
                "query_text": text,
                "category": "adversarial",
                "generation_batch": "adv_a1",
                "intended_topology": "expense",
                "expected_classification": "COMPILED",
                "adversarial_family": "A1",
                "slots": {"category": "Food", "threshold": 100.0, "source_dep": src_variant}
            })

        # A2: Same wording, different OutcomeContract
        contracts = ["EXACT", "APPROXIMATE_NUMERIC", "SET_VALUED", "DECISION"]
        for i in range(55):
            c_type = contracts[i % len(contracts)]
            text = f"Evaluate options and decide on deployment strategy with confidence >= 0.80"
            queries.append({
                "id": f"p07_adv_a2_{i}",
                "query_text": text,
                "category": "adversarial",
                "generation_batch": "adv_a2",
                "intended_topology": "factual_decision",
                "expected_classification": "COMPILED",
                "adversarial_family": "A2",
                "contract_override": c_type,
                "slots": {"topic": "deployment", "min_confidence": 0.80}
            })

        # A3: Small parameter change (micro-parameter sensitivity)
        for i in range(55):
            micro_thresh = 100.0 + (i * 0.01)
            text = f"Calculate total travel spending over ${micro_thresh:.2f}"
            queries.append({
                "id": f"p07_adv_a3_{i}",
                "query_text": text,
                "category": "adversarial",
                "generation_batch": "adv_a3",
                "intended_topology": "expense",
                "expected_classification": "COMPILED",
                "adversarial_family": "A3",
                "slots": {"category": "Travel", "threshold": micro_thresh}
            })

        # A4: Different wording, identical computation (shape invariance)
        a4_phrasings = [
            "Calculate total food spending over $100",
            "Show me all food expenses exceeding 100 dollars",
            "Sum food purchases greater than 100",
            "Give total spent on food above $100",
            "Find net food costs higher than 100"
        ]
        for i in range(55):
            text = a4_phrasings[i % len(a4_phrasings)]
            queries.append({
                "id": f"p07_adv_a4_{i}",
                "query_text": text,
                "category": "adversarial",
                "generation_batch": "adv_a4",
                "intended_topology": "expense",
                "expected_classification": "COMPILED",
                "adversarial_family": "A4",
                "slots": {"category": "Food", "threshold": 100.0}
            })

        # A5: Same topology, different cost class (cardinality 10 vs 100,000)
        for i in range(55):
            cardinality = 10 if (i % 2 == 0) else 100000
            text = f"Diagnose telemetry alerts on node_1 with error threshold exceeding 5"
            queries.append({
                "id": f"p07_adv_a5_{i}",
                "query_text": text,
                "category": "adversarial",
                "generation_batch": "adv_a5",
                "intended_topology": "troubleshooting",
                "expected_classification": "COMPILED",
                "adversarial_family": "A5",
                "env_override": {"telemetry_cardinality": cardinality},
                "slots": {"system_id": "node_1", "error_threshold": 5}
            })

        # A6: Same topology, different effect set (Pure vs WriteExternal)
        for i in range(55):
            effect_mode = "pure" if (i % 2 == 0) else "audit_log"
            text = f"Reconcile orders and inventory matching stock quantity exceeding 10"
            queries.append({
                "id": f"p07_adv_a6_{i}",
                "query_text": text,
                "category": "adversarial",
                "generation_batch": "adv_a6",
                "intended_topology": "cross_source_join_aggregate",
                "expected_classification": "COMPILED",
                "adversarial_family": "A6",
                "effect_mode": effect_mode,
                "slots": {"min_quantity": 10}
            })

        # =====================================================================
        # 4. Out-of-Distribution / Non-compilable (223 queries)
        # =====================================================================
        # 4a. Unsupported domain queries (123 queries)
        unsupported_pool = [
            "What will the weather forecast be in Tokyo tomorrow with rain?",
            "Can you translate this official legal contract into Spanish and French?",
            "Buy 500 shares of Apple stock on Nasdaq and track dividend yield",
            "Write a poem about the beauty of the starry night sky",
            "Generate a high-resolution photograph of a futuristic cyberpunk city",
            "Write a python script with recursive backtracking to solve sudoku",
            "Book a roundtrip flight from San Francisco to Paris next Monday",
            "Provide an authentic Italian recipe for making homemade pizza dough",
            "What is the current temperature and humidity in London?",
            "Can you write a funny rhyming joke about a software developer?"
        ]
        for i in range(123):
            base_text = unsupported_pool[i % len(unsupported_pool)]
            queries.append({
                "id": f"p07_ood_unsupported_{i}",
                "query_text": f"{base_text} (variant {i})",
                "category": "out_of_distribution",
                "generation_batch": "ood_unsupported",
                "intended_topology": "none",
                "expected_classification": "UNSUPPORTED_INTENT",
                "adversarial_family": None,
                "slots": {}
            })

        # 4b. Ambiguous cross-domain queries (50 queries)
        ambiguous_pool = [
            "Schedule a meeting with alice to reconcile orders and inventory spending",
            "Diagnose telemetry alerts on node_1 while evaluating decision options with confidence 0.8",
            "Recommend catalog items for user_1 and schedule appointment slot for 30 minutes",
            "Calculate total food spending and diagnose node_2 error limit exceeding 5",
            "Decide on deployment options and recommend products for user_3"
        ]
        for i in range(50):
            base_text = ambiguous_pool[i % len(ambiguous_pool)]
            queries.append({
                "id": f"p07_ood_ambiguous_{i}",
                "query_text": f"{base_text} (case {i})",
                "category": "out_of_distribution",
                "generation_batch": "ood_ambiguous",
                "intended_topology": "none",
                "expected_classification": "AMBIGUOUS_INTENT",
                "adversarial_family": None,
                "slots": {}
            })

        # 4c. Low-confidence / fragment queries (50 queries)
        vague_pool = [
            "check status of some stuff exceeding 5",
            "look at some data maybe above 10",
            "analyze random items over threshold",
            "system check thing maybe",
            "find something about numbers exceeding 50"
        ]
        for i in range(50):
            base_text = vague_pool[i % len(vague_pool)]
            queries.append({
                "id": f"p07_ood_vague_{i}",
                "query_text": f"{base_text} ref_{i}",
                "category": "out_of_distribution",
                "generation_batch": "ood_vague",
                "intended_topology": "none",
                "expected_classification": "LOW_CONFIDENCE_MAPPING",
                "adversarial_family": None,
                "slots": {}
            })

        assert len(queries) == 1550, f"Expected 1,550 queries, got {len(queries)}"

        return {
            "metadata": {
                "total_queries": len(queries),
                "seed": seed,
                "num_canonical": len(canonical_queries),
                "num_paraphrases": 990,
                "num_adversarial": 330,
                "num_ood": 223,
                "batches": ["canonical", "batch_1", "batch_2", "batch_3", "adv_a1", "adv_a2", "adv_a3", "adv_a4", "adv_a5", "adv_a6", "ood_unsupported", "ood_ambiguous", "ood_vague"]
            },
            "queries": queries
        }
