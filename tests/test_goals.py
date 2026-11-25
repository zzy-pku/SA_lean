"""Integration tests: set SA_LEAN to an installed Lean executable."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from smt_route.analyze import candidate_values

ROOT = Path(__file__).resolve().parents[1]
LEAN = os.environ.get("SA_LEAN")


class WitnessParsingTest(unittest.TestCase):
    def test_incomplete_model_uses_defaults_but_marks_them(self):
        values = candidate_values(" - mode: 1\n - noise: $2\n", [
            {"name": "mode", "type": "Int"}, {"name": "noise", "type": "Int"}])
        self.assertEqual([v["value"] for v in values], ["1", "0"])
        self.assertEqual([v["defaulted"] for v in values], [False, True])

    def test_duplicate_binders_are_not_guessed(self):
        self.assertIsNone(candidate_values("", [
            {"name": "x", "type": "Int"}, {"name": "x", "type": "Int"}]))


@unittest.skipUnless(LEAN, "set SA_LEAN to run Lean integration tests")
class GoalGenerationTest(unittest.TestCase):
    def test_generated_targets_are_well_formed_and_semantically_correct(self):
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
            goal = all_goals["gate"][("independent", 2)]
            mode = all_goals["gate"][("independent", 0)]
            value = all_goals["gate"][("independent", 1)]
            caller = all_goals["caller"][("always_true", None)]
            source = temp / "Check.lean"
            source.write_text("import DependencyCase\n"
                f"example : {goal} := by\n  unfold DependencyCase.gate\n  omega\n"
                f"example : ¬ ({mode}) := by\n  intro h\n  have k := h 0 0 0 1\n  unfold DependencyCase.gate at k\n  omega\n"
                f"example : ¬ ({value}) := by\n  intro h\n  have k := h 1 7 0 0\n  unfold DependencyCase.gate at k\n  omega\n"
                f"example : {caller} := by\n  intro a b c\n  unfold DependencyCase.caller DependencyCase.gate\n  exact Or.inl (by omega)\n",
                encoding="utf-8")
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
            self.assertEqual([r["status"] for r in results],
                             ["refuted", "refuted", "refuted", "refuted", "confirmed"])
            self.assertEqual(results[-1]["evidence"]["validation"], "lean_checked")
            self.assertTrue(all(r["witness"]["validation"] == "lean_checked" for r in results[:-1]))
            self.assertTrue((out / results[-1]["smt_query"]).is_file())


if __name__ == "__main__":
    unittest.main()
