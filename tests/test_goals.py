"""Integration tests: set SA_LEAN to an installed Lean executable."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tests.benchmark import compare_case

ROOT = Path(__file__).resolve().parents[1]
LEAN = os.environ.get("SA_LEAN")


class BenchmarkComparisonTest(unittest.TestCase):
    def test_match_mismatch_and_unresolved_are_distinct(self):
        case = {"declaration": "Example.f", "expected": {"constant": "valid", "independent:0": "falsified", "independent:1": "valid"}}
        results = [{"declaration": "Example.f", "kind": "constant", "parameter_index": None, "status": "valid"},
                   {"declaration": "Example.f", "kind": "independent", "parameter_index": 0, "status": "valid"},
                   {"declaration": "Example.f", "kind": "independent", "parameter_index": 1, "status": "error"}]
        self.assertEqual([r["grade"] for r in compare_case(case, results)], ["match", "mismatch", "unresolved"])

    def test_missing_goal_and_changed_comparison_are_not_scored(self):
        case = {"declaration": "Example.f", "expected": {"constant": "valid"}}
        with self.assertRaises(ValueError):
            compare_case(case, [])
        with self.assertRaises(ValueError):
            compare_case(case, [{"declaration": "Example.f", "kind": "constant", "parameter_index": None, "status": "valid", "comparison": "heterogeneous"}])


@unittest.skipUnless(LEAN, "set SA_LEAN to run Lean integration tests")
class GoalGenerationTest(unittest.TestCase):
    def test_structure_case_goals_are_well_formed_and_labelled(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "smt_route") as tmp:
            temp = Path(tmp)
            build = temp / "smt_route"
            build.mkdir()
            env = {**os.environ, "LEAN_PATH": str(temp)}
            for source, target, cwd in [
                (ROOT / "smt_route" / "Goals.lean", build / "Goals.olean", ROOT),
                (ROOT / "examples" / "StructureCases.lean", temp / "StructureCases.olean", ROOT / "examples"),
            ]:
                proc = subprocess.run([LEAN, "-o", str(target), str(source)], cwd=cwd, env=env,
                                      capture_output=True, text=True, encoding="utf-8")
                self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            labels = json.loads((ROOT / "tests" / "expected_results.json").read_text(encoding="utf-8"))["cases"]
            cases = [case for case in labels if case["module"] == "StructureCases"]
            self.assertEqual(len(cases), 10)
            source = temp / "Extract.lean"
            source.write_text("import smt_route.Goals\nimport StructureCases\n" + "".join(
                f"#semantic_goals {case['declaration']}\n" for case in cases), encoding="utf-8")
            proc = subprocess.run([LEAN, str(source)], cwd=temp, env=env, capture_output=True,
                                  text=True, encoding="utf-8")
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            goals = [json.loads(line[8:]) for line in proc.stdout.splitlines() if line.startswith("SA_GOAL:")]
            self.assertEqual(len(goals), 31)
            for case in cases:
                items = [{**g, "status": "not_run"} for g in goals if g["declaration"] == case["declaration"]]
                self.assertTrue(all(r["grade"] == "unresolved" for r in compare_case(case, items)))
            check = temp / "Check.lean"
            check.write_text("import StructureCases\n" + "".join(
                f"#check (show Prop from ({goal['goal']}))\n" for goal in goals), encoding="utf-8")
            proc = subprocess.run([LEAN, str(check)], cwd=temp, env=env, capture_output=True,
                                  text=True, encoding="utf-8")
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_general_function_goals_reelaborate(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "smt_route") as tmp:
            temp = Path(tmp)
            build = temp / "smt_route"
            build.mkdir()
            env = {**os.environ, "LEAN_PATH": str(temp)}
            for source, target, cwd in [
                (ROOT / "smt_route" / "Goals.lean", build / "Goals.olean", ROOT),
                (ROOT / "examples" / "FunctionCases.lean", temp / "FunctionCases.olean", ROOT / "examples"),
            ]:
                p = subprocess.run([LEAN, "-o", str(target), str(source)], cwd=cwd, env=env,
                                   capture_output=True, text=True, encoding="utf-8")
                self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            declarations = ["scalar", "collection", "polymorphic", "withInstance", "higherOrder", "dependent", "dependentResult"]
            source = temp / "Extract.lean"
            source.write_text("import smt_route.Goals\nimport FunctionCases\n" + "".join(
                f"#semantic_goals FunctionCases.{name}\n" for name in declarations), encoding="utf-8")
            p = subprocess.run([LEAN, str(source)], cwd=temp, env=env, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            goals = [json.loads(line[8:]) for line in p.stdout.splitlines() if line.startswith("SA_GOAL:")]
            self.assertEqual(len(goals), 22)
            self.assertTrue(any(g["comparison"] == "heterogeneous_fiberwise" for g in goals))
            self.assertTrue(any(g["universe_parameters"] == ["u"] for g in goals))
            self.assertTrue(all(g["kind"] in ("constant", "independent") for g in goals))
            check = temp / "Reelaborate.lean"
            check.write_text("import FunctionCases\nuniverse u\n" + "".join(
                f"#check (show Prop from ({g['goal']}))\n" for g in goals), encoding="utf-8")
            p = subprocess.run([LEAN, str(check)], cwd=temp, env=env, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            out = temp / "polymorphic-out"
            p = subprocess.run([sys.executable, str(ROOT / "smt_route" / "analyze.py"),
                "--lean", LEAN, "--project", str(temp), "--lean-path", str(temp),
                "--module", "FunctionCases", "--decl", "FunctionCases.polymorphic", "--out", str(out)],
                cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
            generated = json.loads((out / "goals.json").read_text(encoding="utf-8"))
            self.assertEqual(len(generated), 4)
            self.assertTrue(all(g["universe_parameters"] == ["u"] for g in generated))

    def test_predicate_targets_are_well_formed(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "smt_route") as temp:
            temp = Path(temp)
            source = temp / "DependencyCase.lean"
            source.write_text((ROOT / "examples" / "DependencyCase.lean").read_text(encoding="utf-8"), encoding="utf-8")
            built = subprocess.run([LEAN, "-o", str(temp / "DependencyCase.olean"), str(source)],
                                   cwd=temp, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            all_goals = {}
            for decl in ("gate", "caller"):
                out = temp / (decl + "-out")
                cmd = [sys.executable, str(ROOT / "smt_route" / "analyze.py"),
                       "--lean", LEAN, "--project", str(temp), "--lean-path", str(temp),
                       "--module", "DependencyCase", "--decl", f"DependencyCase.{decl}", "--out", str(out)]
                proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
                debug = (out / "generator-build.log").read_text(encoding="utf-8") if (out / "generator-build.log").exists() else ""
                self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr + debug)
                goals = json.loads((out / "goals.json").read_text(encoding="utf-8"))
                self.assertEqual(len(goals), 5)
                self.assertTrue(all(g["status"] == "not_run" for g in json.loads((out / "results.json").read_text(encoding="utf-8"))))
                all_goals[decl] = {(g["kind"], g["parameter_index"]): g["goal"] for g in goals}
            source = temp / "Check.lean"
            source.write_text("import DependencyCase\n" + "".join(
                f"#check (show Prop from ({goal}))\n" for goals in all_goals.values() for goal in goals.values()), encoding="utf-8")
            env = {**os.environ, "LEAN_PATH": str(temp)}
            checked = subprocess.run([LEAN, str(source)], cwd=temp, env=env, capture_output=True,
                                     text=True, encoding="utf-8")
            self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)

    @unittest.skipUnless(os.environ.get("SA_BLASTER") and os.environ.get("SA_Z3"),
                         "set SA_BLASTER and SA_Z3 for backend integration")
    def test_blaster_gate_end_to_end(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "smt_route") as temp:
            temp = Path(temp)
            source = temp / "DependencyCase.lean"
            source.write_text((ROOT / "examples" / "DependencyCase.lean").read_text(encoding="utf-8"), encoding="utf-8")
            built = subprocess.run([LEAN, "-o", str(temp / "DependencyCase.olean"), str(source)],
                                   cwd=temp, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            out = temp / "out"
            proc = subprocess.run([sys.executable, str(ROOT / "smt_route" / "analyze.py"),
                "--lean", LEAN, "--project", str(temp), "--lean-path", str(temp),
                "--module", "DependencyCase", "--decl", "DependencyCase.gate", "--out", str(out),
                "--blaster-path", os.environ["SA_BLASTER"], "--z3", os.environ["SA_Z3"], "--timeout", "60"],
                cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=300)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            results = json.loads((out / "results.json").read_text(encoding="utf-8"))
            cases = json.loads((ROOT / "tests" / "expected_results.json").read_text(encoding="utf-8"))["cases"]
            case = next(c for c in cases if c["declaration"] == "DependencyCase.gate")
            self.assertTrue(all(r["grade"] == "match" for r in compare_case(case, results)))
            self.assertFalse(list(out.glob("witness-*.lean")))
            self.assertFalse(list(out.glob("validate-*.lean")))
            self.assertTrue((out / results[-1]["smt_query"]).is_file())


if __name__ == "__main__":
    unittest.main()
