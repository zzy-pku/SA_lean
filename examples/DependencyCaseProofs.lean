import DependencyCase

namespace DependencyCase

theorem gate_summary (mode value noise : Int) :
    gate mode value noise ↔ mode = 0 ∨ value = 7 := by
  have h : value + 2 * noise - noise - noise = value := by omega
  simp only [gate, h]

theorem gate_noise_irrelevant (mode value n₁ n₂ : Int) :
    gate mode value n₁ ↔ gate mode value n₂ := by
  exact (gate_summary mode value n₁).trans (gate_summary mode value n₂).symm

-- Vary only mode, then vary only value.
theorem gate_mode_witness : gate 0 0 0 ∧ ¬ gate 1 0 0 := by
  unfold gate
  decide

theorem gate_value_witness : gate 1 7 0 ∧ ¬ gate 1 0 0 := by
  unfold gate
  decide

theorem caller_always_true (a b c : Int) : caller a b c := by
  have h : (a + b) + (a - b) - 2 * a = 0 := by omega
  exact (gate_summary ((a + b) + (a - b) - 2 * a) (a + b) c).mpr (Or.inl h)

-- Check whether plain simplification can close the automatically generated goals.
example (a b c : Int) : caller a b c := by
  fail_if_success solve | simp [caller, gate]
  unfold caller gate
  exact Or.inl (by omega)

example (mode value n₁ n₂ : Int) : gate mode value n₁ ↔ gate mode value n₂ := by
  fail_if_success solve | simp [gate]
  unfold gate
  omega

#print axioms gate_mode_witness
#print axioms gate_value_witness
#print axioms caller_always_true
#print axioms gate_noise_irrelevant

end DependencyCase
