"""Generate Lean predicate goals and optionally submit them to Lean-blaster.

This is an experimental adapter, not a verified Lean-to-SMT translator.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parent
IDENT = re.compile(r"^[^\W\d]\w*(?:\.[^\W\d]\w*)*$", re.UNICODE)


def run(command: list[str], *, cwd: Path, env: dict[str, str], timeout: int):
    try:
        return subprocess.run(command, cwd=cwd, env=env, capture_output=True,
                              text=True, encoding="utf-8", errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"timeout after {timeout}s: {command[0]}") from exc
    except OSError as exc:
        raise RuntimeError(f"cannot start {command[0]}: {exc}") from exc


def valid_name(value: str) -> str:
    if not IDENT.fullmatch(value):
        raise argparse.ArgumentTypeError("expected a simple fully qualified Lean name")
    return value


def candidate_values(output: str, binders: list[dict]) -> list[dict] | None:
    """Decode only simple values; symbolic/missing values get a tested default.

    The resulting assignment is never trusted until Lean checks the instance.
    """
    if len({b["name"] for b in binders}) != len(binders):
        return None
    raw = dict(re.findall(r" - ([^\s:]+):\s*([^\r\n]+)", output))
    values = []
    for binder in binders:
        name, ty = binder["name"], binder["type"]
        value = raw.get(name, "").strip()
        defaulted = False
        if ty in ("Int", "Nat"):
            match = re.fullmatch(r"\(-\s+(\d+)\)", value)
            if match:
                value = "-" + match.group(1)
            if not re.fullmatch(r"-?\d+", value):
                value = "0"
                defaulted = True
            if ty == "Nat" and value.startswith("-"):
                return None
            literal = f"({value} : {ty})"
        elif ty == "Bool":
            if value not in ("true", "false"):
                value = "false"
                defaulted = True
            literal = value
        else:
            return None
        values.append({"name": name, "type": ty, "value": value, "literal": literal,
                       "defaulted": defaulted})
    return values


def replay_counterexample(lean: str, project: Path, module: str, goal: dict,
                          output: str, env: dict[str, str], out: Path, i: int,
                          timeout: int) -> dict | None:
    values = candidate_values(output, goal["binders"])
    if values is None:
        return None
    args = " ".join(v["literal"] for v in values)
    instance = f"h {args}" if args else "h"
    dependencies = [name for name in goal.get("unfold_dependencies", []) if IDENT.fullmatch(name)]
    unfold = "".join(f"  try unfold {name} at k\n" for name in dependencies)
    source = out / f"witness-{i:03d}.lean"
    source.write_text(f"import {module}\n\nexample : ¬ ({goal['goal']}) := by\n"
                      f"  intro h\n  have k := {instance}\n"
                      f"  unfold {goal['declaration']} at k\n{unfold}  revert k\n  decide\n", encoding="utf-8")
    try:
        check = run([lean, str(source)], cwd=project, env=env, timeout=timeout)
    except RuntimeError as exc:
        (out / f"witness-{i:03d}.log").write_text(str(exc), encoding="utf-8")
        return None
    (out / f"witness-{i:03d}.log").write_text(check.stdout + check.stderr, encoding="utf-8")
    if check.returncode != 0:
        return None
    return {"values": values, "validation": "lean_checked", "source": source.name,
            "log": f"witness-{i:03d}.log"}


def validate_valid_goal(lean: str, project: Path, module: str, goal: dict,
                        env: dict[str, str], out: Path, i: int, timeout: int) -> dict | None:
    """Independently try kernel-checked Lean proof; failure is not refutation."""
    dependencies = [name for name in goal.get("unfold_dependencies", []) if IDENT.fullmatch(name)]
    unfold = "".join(f"  try unfold {name}\n" for name in dependencies)
    source = out / f"validate-{i:03d}.lean"
    source.write_text(f"import {module}\n\nexample : {goal['goal']} := by\n"
                      f"  intros\n  unfold {goal['declaration']}\n{unfold}"
                      "  first | omega | (left; omega)\n", encoding="utf-8")
    try:
        check = run([lean, str(source)], cwd=project, env=env, timeout=timeout)
    except RuntimeError as exc:
        (out / f"validate-{i:03d}.log").write_text(str(exc), encoding="utf-8")
        return None
    (out / f"validate-{i:03d}.log").write_text(check.stdout + check.stderr, encoding="utf-8")
    if check.returncode != 0 or "declaration uses 'sorry'" in check.stdout + check.stderr:
        return None
    return {"validation": "lean_checked", "source": source.name, "log": f"validate-{i:03d}.log"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lean", required=True, help="path to the target Lean executable")
    parser.add_argument("--project", type=Path, required=True, help="Lean project root")
    parser.add_argument("--module", required=True, type=valid_name)
    parser.add_argument("--decl", required=True, type=valid_name)
    parser.add_argument("--lean-path", action="append", default=[], help="extra Lean module directory; repeatable")
    parser.add_argument("--out", type=Path, required=True, help="new or empty output directory")
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--blaster-path", type=Path, help="directory containing compiled Blaster.olean")
    parser.add_argument("--z3", type=Path, help="path to z3 executable used by Lean-blaster")
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    project = args.project.resolve()
    if not project.is_dir():
        parser.error("--project must be an existing directory")
    lean = str(Path(args.lean).resolve())
    out = args.out.resolve()
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        parser.error("--out must be a new or empty directory")
    out.mkdir(parents=True, exist_ok=True)
    build = out / "build" / "smt_route"
    build.mkdir(parents=True)
    env = os.environ.copy()
    paths = [str(out / "build"), *(str(Path(p).resolve()) for p in args.lean_path)]
    if args.blaster_path:
        if not (args.blaster_path.resolve() / "Blaster.olean").is_file():
            parser.error("--blaster-path must contain a compiled Blaster.olean")
        paths.append(str(args.blaster_path.resolve()))
    if args.z3:
        z3 = args.z3.resolve()
        if not z3.is_file():
            parser.error("--z3 must point to an existing executable")
        env["PATH"] = str(z3.parent) + os.pathsep + env.get("PATH", "")
    if env.get("LEAN_PATH"):
        paths.append(env["LEAN_PATH"])
    env["LEAN_PATH"] = os.pathsep.join(paths)
    version = run([lean, "--version"], cwd=project, env=env, timeout=args.timeout)
    z3_version = None
    if args.z3:
        z3_result = run([str(args.z3.resolve()), "--version"], cwd=project, env=env, timeout=args.timeout)
        if z3_result.returncode:
            raise RuntimeError("configured z3 executable failed its version check")
        z3_version = z3_result.stdout.strip()
    (out / "lean_version.txt").write_text(version.stdout + version.stderr, encoding="utf-8")
    (out / "manifest.json").write_text(json.dumps({"project": str(project), "module": args.module,
        "declaration": args.decl, "lean": lean, "lean_version": version.stdout.strip(),
        "blaster_path": str(args.blaster_path.resolve()) if args.blaster_path else None,
        "z3": str(args.z3.resolve()) if args.z3 else None, "z3_version": z3_version,
        "lean_path": paths, "timeout_seconds": args.timeout}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    compilation = run([lean, "-o", str(build / "Goals.olean"), str(ROOT / "Goals.lean")],
                      cwd=ROOT.parent, env=env, timeout=args.timeout)
    (out / "generator-build.log").write_text(compilation.stdout + compilation.stderr, encoding="utf-8")
    if compilation.returncode:
        raise RuntimeError("goal generator failed to compile; see generator-build.log")
    input_file = out / "extract.lean"
    input_file.write_text(f"import smt_route.Goals\nimport {args.module}\n\n#semantic_goals {args.decl}\n", encoding="utf-8")
    extracted = run([lean, str(input_file)], cwd=project, env=env, timeout=args.timeout)
    (out / "extract.log").write_text(extracted.stdout + extracted.stderr, encoding="utf-8")
    if extracted.returncode:
        raise RuntimeError("goal generation failed; see extract.log")
    goals = [json.loads(line.removeprefix("SA_GOAL:")) for line in extracted.stdout.splitlines()
             if line.startswith("SA_GOAL:")]
    if len(goals) < 2:
        raise RuntimeError("goal generator returned incomplete output")
    (out / "goals.json").write_text(json.dumps(goals, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    results = []
    for i, goal in enumerate(goals):
        result = {**goal, "backend": "lean-blaster", "status": "not_run", "reason": "no compiled Lean-blaster specified"}
        if args.blaster_path:
            source = out / f"query-{i:03d}.lean"
            source.write_text(f"import Blaster\nimport {args.module}\n\n#blaster (timeout: {args.timeout}) (dump-smt-lib: 1) [{goal['goal']}]\n", encoding="utf-8")
            try:
                proc = run([lean, str(source)], cwd=project, env=env, timeout=args.timeout + 10)
                output = proc.stdout + proc.stderr
                (out / f"query-{i:03d}.log").write_text(output, encoding="utf-8")
                if "Smt Query:\n" in output:
                    dumped = output.split("Smt Query:\n", 1)[1].strip()
                    # Blaster's dump in the tested version omits the final check.
                    # Preserve it separately, then add a check in the runnable copy.
                    (out / f"query-{i:03d}.smt2").write_text(
                        dumped + ("\n" if "(check-sat)" in dumped else "\n(check-sat)\n"), encoding="utf-8")
                    result["smt_query"] = f"query-{i:03d}.smt2"
                # Blaster's #command checks an expected outcome; a false goal can
                # legitimately produce a nonzero process exit. Never equate that
                # exit code with falsity or with a verified model.
                if "Undetermined" in output:
                    result.update(status="unknown", backend_verdict="undetermined", reason="Lean-blaster reported undetermined")
                elif "Falsified" in output:
                    witness = replay_counterexample(lean, project, args.module, goal, output, env, out, i, args.timeout)
                    if witness is not None:
                        result.update(status="refuted", backend_verdict="falsified", witness=witness,
                                      reason="Lean checked a concrete counterexample to the generated goal")
                    else:
                        result.update(status="candidate", backend_verdict="falsified",
                                      reason="Lean-blaster reported a counterexample; concrete replay did not succeed")
                elif "Unexpected Valid" in output or ("Valid" in output and proc.returncode == 0):
                    checked = validate_valid_goal(lean, project, args.module, goal, env, out, i, args.timeout)
                    if checked is None:
                        result.update(status="candidate", backend_verdict="valid", reason="Lean-blaster reports valid; independent Lean check did not succeed")
                    else:
                        result.update(status="confirmed", backend_verdict="valid", evidence=checked,
                                      reason="independent Lean tactic closed the generated goal")
                else:
                    result.update(status="error", reason="unrecognized Lean-blaster output or execution failure")
                result["exit_code"] = proc.returncode
                result["log"] = f"query-{i:03d}.log"
            except RuntimeError as exc:
                result.update(status="unknown" if str(exc).startswith("timeout") else "error", reason=str(exc))
        results.append(result)
        parameter = f"[{goal['parameter_index']}]" if goal["parameter_index"] is not None else ""
        print(f"{goal['kind']}{parameter}: {result['status']} ({result.get('backend_verdict', 'not_run')})", flush=True)
    (out / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Generated {len(goals)} goals: {out / 'goals.json'}")
    print(f"Results: {out / 'results.json'}")
    return 0 if args.blaster_path and all(r["status"] not in {"error", "not_run"} for r in results) else 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)
