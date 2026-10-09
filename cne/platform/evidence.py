"""Single-run, source-bound evidence reports. Never aggregates separate test runs."""
import hashlib
import json
import os
import subprocess
import argparse
import xml.etree.ElementTree as ET
import time
import uuid
from pathlib import Path


def _git(root, *args):
    try:
        return subprocess.check_output(
            ["git", "-C", str(root), *args], text=True
        ).strip()
    except Exception:
        return None


def source_identity(root):
    status = _git(root, "status", "--porcelain") or ""
    tracked_diff = subprocess.check_output(
        ["git", "-C", str(root), "diff", "--binary", "HEAD", "--"],
        stderr=subprocess.DEVNULL,
    )
    untracked = subprocess.check_output(
        ["git", "-C", str(root), "ls-files", "--others", "--exclude-standard", "-z"],
        stderr=subprocess.DEVNULL,
    ).split(b"\0")
    content_hash = hashlib.sha256()
    content_hash.update(tracked_diff)
    for encoded in sorted(x for x in untracked if x):
        relative = encoded.decode(errors="surrogateescape")
        path = root / relative
        if path.is_file():
            content_hash.update(encoded + b"\0")
            content_hash.update(path.read_bytes())
    return {
        "commit": _git(root, "rev-parse", "HEAD"),
        "commit_tree": _git(root, "rev-parse", "HEAD^{tree}"),
        "dirty": bool(status),
        "status_sha256": hashlib.sha256(status.encode()).hexdigest(),
        "working_tree_content_sha256": content_hash.hexdigest(),
    }


def _junit_summary(path):
    if not path:
        return None, None
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
    counts = {
        key: sum(int(suite.attrib.get(key, 0)) for suite in suites)
        for key in ("tests", "failures", "errors", "skipped")
    }
    test_ids = sorted(
        f"{case.attrib.get('classname', '')}::{case.attrib.get('name', '')}"
        for suite in suites for case in suite.findall("testcase")
    )
    return counts, test_ids


def build_evidence_report(
    root, command, junit_path=None, corpus_path=None, full_suite=False,
    exit_code=None, expected_junit_path=None, expected_inventory_path=None,
    actual_inventory_path=None, ci_run_id=None, ci_job=None,
):
    root = Path(root).resolve()
    junit_sha = (
        hashlib.sha256(Path(junit_path).read_bytes()).hexdigest()
        if junit_path else None
    )
    corpus_sha = (
        hashlib.sha256(Path(corpus_path).read_bytes()).hexdigest()
        if corpus_path else None
    )
    counts, actual_ids = _junit_summary(junit_path)
    expected_counts, expected_ids = _junit_summary(expected_junit_path)
    inventory_hashes = {"expected": None, "actual": None}
    if expected_inventory_path and actual_inventory_path:
        expected_inventory_bytes = Path(expected_inventory_path).read_bytes()
        actual_inventory_bytes = Path(actual_inventory_path).read_bytes()
        inventory_hashes = {
            "expected": hashlib.sha256(expected_inventory_bytes).hexdigest(),
            "actual": hashlib.sha256(actual_inventory_bytes).hexdigest(),
        }
        expected_ids = json.loads(expected_inventory_bytes)
        actual_inventory = json.loads(actual_inventory_bytes)
        inventory_matches = expected_ids == actual_inventory and len(actual_inventory) == (counts or {}).get("tests")
        expected_counts = {"tests": len(expected_ids)}
    else:
        inventory_matches = (expected_ids is not None and actual_ids == expected_ids) if expected_junit_path else None
    junit_passed = bool(
        counts and counts["tests"] > 0 and counts["failures"] == counts["errors"] == 0
    )
    command_succeeded = exit_code == 0
    passed = bool(
        full_suite and junit_passed and command_succeeded
        and inventory_matches is True
    )

    source = source_identity(root)
    github_sha = os.environ.get("GITHUB_SHA")
    ci_source_matches = bool(
        github_sha and source.get("commit") == github_sha and not source.get("dirty")
    )
    report = {
        "schema": "cne-evidence-1",
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "run_id": uuid.uuid4().hex,
        "source": source,
        "command": command,
        "junit_sha256": junit_sha,
        "corpus_sha256": corpus_sha,
        "test_counts_single_run": counts,
        "expected_test_counts": expected_counts,
        "test_inventory_matches": inventory_matches,
        "test_inventory_sha256": inventory_hashes,
        "pytest_exit_code": exit_code,
        "single_full_suite_pass": passed,
        "status": "PASSED" if passed else "INCOMPLETE_OR_FAILED",
        "ci": {
            "run_id": ci_run_id,
            "job": ci_job,
            "commit": os.environ.get("GITHUB_SHA"),
        },
        "ci_source_matches": ci_source_matches,
        "ci_commit_evidence": bool(ci_run_id and ci_source_matches),
    }
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build source-bound CNE test evidence")
    parser.add_argument("--root", required=True)
    parser.add_argument("--command", required=True)
    parser.add_argument("--junit", required=True)
    parser.add_argument("--corpus")
    parser.add_argument("--expected-junit")
    parser.add_argument("--expected-inventory")
    parser.add_argument("--actual-inventory")
    parser.add_argument("--output", required=True)
    parser.add_argument("--exit-code", required=True, type=int)
    parser.add_argument("--full-suite", action="store_true")
    parser.add_argument("--ci-job")
    args = parser.parse_args(argv)
    report = build_evidence_report(
        args.root, args.command, args.junit, corpus_path=args.corpus, full_suite=args.full_suite,
        exit_code=args.exit_code, expected_junit_path=args.expected_junit,
        expected_inventory_path=args.expected_inventory,
        actual_inventory_path=args.actual_inventory,
        ci_run_id=os.environ.get("GITHUB_RUN_ID"), ci_job=args.ci_job,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "tests": report["test_counts_single_run"], "inventory_matches": report["test_inventory_matches"]}))
    return 0 if report["single_full_suite_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
