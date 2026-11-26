"""Compare end-to-end tool results against human-labelled expected goals."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
LABELS = ROOT / "tests" / "expected_results.json"


def goal_key(goal: dict) -> str:
    index = goal.get("parameter_index")
    return goal["kind"] if index is None else f"{goal['kind']}:{index}"


def compare_case(case: dict, results: list[dict]) -> list[dict]:
    expected = case["expected"]
    actual = {}
    for result in results:
        if result.get("declaration") != case["declaration"]:
            raise ValueError(f"result belongs to another declaration: {case['declaration']}")
        key = goal_key(result)
        if key in actual:
            raise ValueError(f"duplicate result: {case['declaration']} {key}")
        actual[key] = result
    if set(actual) != set(expected):
        raise ValueError(f"goal set mismatch for {case['declaration']}: expected {sorted(expected)}, got {sorted(actual)}")
    records = []
    for key, label in expected.items():
        result = actual[key]
        comparison = case.get("comparisons", {}).get(key, "ordinary")
        if result.get("comparison", "ordinary") != comparison:
            raise ValueError(f"comparison convention changed for {case['declaration']} {key}")
        status = result["status"]
        grade = ("match" if status == label else "mismatch") if status in ("valid", "falsified") else "unresolved"
        records.append({"declaration": case["declaration"], "goal": key, "comparison": comparison,
                        "expected": label, "actual": status, "grade": grade,
                        "log": result.get("log"), "reason": result.get("reason")})
    return records


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--lean", required=True)
    p.add_argument("--blaster-path", required=True)
    p.add_argument("--z3", required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--timeout", type=int, default=60)
    p.add_argument("--jobs", type=int, default=2)
    p.add_argument("--module", action="append", help="run only cases from this module; repeatable")
    args = p.parse_args()
    if args.jobs < 1 or args.timeout < 1:
        p.error("--jobs and --timeout must be positive")
    out = args.out.resolve()
    if out.exists() and any(out.iterdir()):
        p.error("--out must be new or empty")
    out.mkdir(parents=True, exist_ok=True)
    lean = str(Path(args.lean).resolve())
    blaster = str(Path(args.blaster_path).resolve())
    z3 = str(Path(args.z3).resolve())
    labels_text = LABELS.read_text(encoding="utf-8")
    (out / "expected_results.json").write_text(labels_text, encoding="utf-8")
    cases = json.loads(labels_text)["cases"]
    if args.module:
        cases = [case for case in cases if case["module"] in args.module]
        if not cases or set(args.module) - {case["module"] for case in cases}:
            p.error("every selected module must have at least one labelled case")
    source_dir = out / "sources"
    source_dir.mkdir()
    for module in sorted({c["module"] for c in cases}):
        source = source_dir / f"{module}.lean"
        source.write_text((ROOT / "examples" / f"{module}.lean").read_text(encoding="utf-8"), encoding="utf-8")
        build = subprocess.run([lean, "-o", str(source_dir / f"{module}.olean"), str(source)],
                               cwd=source_dir, capture_output=True, text=True, encoding="utf-8", errors="replace")
        (source_dir / f"{module}.build.log").write_text(build.stdout + build.stderr, encoding="utf-8")
        if build.returncode:
            print(f"Failed to compile {module}; see build log", file=sys.stderr)
            return 2

    def run_case(case):
        name = case["declaration"]
        result_dir = out / name
        cmd = [sys.executable, str(ROOT / "smt_route" / "analyze.py"), "--lean", lean,
               "--project", str(source_dir), "--lean-path", str(source_dir), "--module", case["module"],
               "--decl", name, "--blaster-path", blaster, "--z3", z3, "--timeout", str(args.timeout),
               "--out", str(result_dir)]
        proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
        (out / f"{name}.run.log").write_text(proc.stdout + proc.stderr, encoding="utf-8")
        results_path = result_dir / "results.json"
        if not results_path.exists():
            return case, None, f"tool failed before writing results (exit {proc.returncode})"
        return case, json.loads(results_path.read_text(encoding="utf-8")), None

    records, failures = [], []
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        for future in as_completed([pool.submit(run_case, case) for case in cases]):
            case, results, error = future.result()
            if error:
                failures.append({"declaration": case["declaration"], "error": error})
            else:
                try:
                    records.extend(compare_case(case, results))
                except ValueError as exc:
                    failures.append({"declaration": case["declaration"], "error": str(exc)})
            print(f"Finished {case['declaration']}" + (f": {error}" if error else ""), flush=True)
    records.sort(key=lambda r: (r["declaration"], r["goal"]))
    counts = {key: sum(r["grade"] == key for r in records) for key in ("match", "mismatch", "unresolved")}
    report = {"labels": "expected_results.json", "selected_modules": args.module,
              "counts": counts, "case_failures": failures, "results": records}
    (out / "benchmark.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{counts}; case failures: {len(failures)}; report: {out / 'benchmark.json'}")
    return 1 if counts["mismatch"] or failures else (2 if counts["unresolved"] else 0)


if __name__ == "__main__":
    sys.exit(main())
