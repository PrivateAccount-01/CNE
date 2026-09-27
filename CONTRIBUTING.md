# Contributing to CNE (Computation Necessity Engine)

Thank you for your interest in contributing to the Computation Necessity Engine (CNE).

## Core Principles & Frozen Architecture

1. **Frozen Specification**: The architecture defined in `system.md` represents the consolidated v1.5 baseline. No new semantic primitives may be introduced beyond the frozen 11 hardware-agnostic primitives:
   - `Observe`
   - `Map`
   - `Filter`
   - `Reduce`
   - `Join`
   - `Branch`
   - `Iterate`
   - `Choose`
   - `Update`
   - `Call`
   - `Emit`

2. **Invariance to Surface Wording**: Signatures, shape keys, and canonical representations must never leak natural language prompts, labels, descriptions, or formatting into semantic identities.

3. **Information Honesty**: Optimizations must never access future or out-of-sample data. All oracle bounds and interventions must be provably admissible under outcome contracts.

4. **Zero Cloud / NPU Dependency for Core**: The core execution target remains mobile ARM CPU (Android 6–8 GB RAM). Any auxiliary compute tiers (such as USB accelerators) must remain strictly secondary and non-mandatory.

## Development Workflow

### Setting up Environment

```bash
git clone https://github.com/PrivateAccount-01/CNE.git
cd CNE
python -m venv .venv
source .venv/bin/activate  # Or on Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
```

### Running the Test Suites

1. **Full Pytest Suite**:
   ```bash
   pytest
   ```

2. **Extreme Black-Box Stress Tests** (148 tests across 8 subsystems):
   ```bash
   pytest cne/tests/extreme
   ```

3. **Master Benchmark Gates Validation** (Gates G0 through G7):
   ```bash
   python -m cne.bench.run_all_gates
   ```

4. **Phase P3 Ablation Ladder**:
   ```bash
   python -m cne.bench.ablations
   ```

## Gate Invariant Criteria

Any proposed change or PR must satisfy:
- **G0**: Fixture representability without domain-specific nodes.
- **G1**: Paraphrase invariance $\ge 80\%$, topology discrimination, and anti-reuse memo key sensitivity.
- **G2**: Information-honest oracle ($R^* \ge 0$, train/eval disjoint).
- **G3**: Positive net savings ($\Delta C_{\text{total}} > 0$) and control overhead $A_{\text{corpus}} \le 20\%$.
- **G4**: 100/100 state correctness and selective invalidation.
- **G5**: Calibration and Wilson score lower bound $LB_{\text{CI}} \ge 95\%$.
- **G6**: Frozen threshold compliance.
- **G7**: CPU-first mobile envelope compatibility.
