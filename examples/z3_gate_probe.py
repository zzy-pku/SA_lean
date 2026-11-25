"""Hand-encoded SMT control: this does not test Lean-to-SMT translation."""

import json
import z3


def gate(mode, value, noise):
    return z3.Or(mode == 0, value + 2 * noise - noise - noise == 7)


def caller(a, b, c):
    return gate((a + b) + (a - b) - 2 * a, a + b, c)


m, v, n, x, y, a, b, c = z3.Ints("mode value noise x y a b c")
queries = {
    "gate.noise.independent": gate(m, v, x) != gate(m, v, y),
    "gate.mode.independent": gate(x, v, n) != gate(y, v, n),
    "gate.value.independent": gate(m, x, n) != gate(m, y, n),
    "caller.always_true": z3.Not(caller(a, b, c)),
    "caller.always_false": caller(a, b, c),
}
expected = {
    "gate.noise.independent": "unsat",
    "gate.mode.independent": "sat",
    "gate.value.independent": "sat",
    "caller.always_true": "unsat",
    "caller.always_false": "sat",
}

print(json.dumps({"z3_version": z3.get_version_string(), "encoding": "handwritten"}))
failed = False
for name, query in queries.items():
    solver = z3.Solver()
    solver.add(query)
    status = str(solver.check())
    model = str(solver.model()) if status == "sat" else None
    print(json.dumps({"query": name, "result": status, "model": model}))
    failed |= status != expected[name]
if failed:
    raise SystemExit(1)
