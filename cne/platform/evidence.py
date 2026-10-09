"""Single-run, source-bound evidence reports. Never aggregates separate test runs."""
import hashlib
import json
import os
import subprocess
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


def build_evidence_report(
    root, command, junit_path=None, corpus_path=None, full_suite=False
):
    root = Path(root).resolve()
    junit_sha = (
        hashlib.sha256(Path(junit_path).read_bytes()).hexdigest()
        if junit_path
        else None
    )
    corpus_sha = (
        hashlib.sha256(Path(corpus_path).read_bytes()).hexdigest()
        if corpus_path
        else None
    )
    passed = False
    counts = None
    if junit_path:
        import xml.etree.ElementTree as ET

        suite = ET.parse(junit_path).getroot()
        nodes = (
            [suite] if suite.tag == "testsuite" else list(suite.findall("testsuite"))
        )
        counts = {
            k: sum(int(n.attrib.get(k, 0)) for n in nodes)
            for k in ("tests", "failures", "errors", "skipped")
        }
        passed = counts["tests"] > 0 and counts["failures"] == counts["errors"] == 0
    report = {
        "schema": "cne-evidence-1",
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "run_id": uuid.uuid4().hex,
        "source": source_identity(root),
        "command": command,
        "junit_sha256": junit_sha,
        "corpus_sha256": corpus_sha,
        "test_counts_single_run": counts,
        "single_full_suite_pass": bool(full_suite and passed),
        "status": "PASSED" if passed else "INCOMPLETE_OR_FAILED",
        "ci_commit_evidence": False,
    }
    return report
