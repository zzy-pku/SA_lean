import Lean

namespace DependencyCase

def gate (mode value noise : Int) : Prop :=
  mode = 0 ∨ value + 2 * noise - noise - noise = 7

def caller (a b c : Int) : Prop :=
  gate ((a + b) + (a - b) - 2 * a) (a + b) c

end DependencyCase
