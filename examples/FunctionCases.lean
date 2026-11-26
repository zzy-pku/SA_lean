import Lean

namespace FunctionCases

universe u

def scalar (x : Int) (ignored : Bool) : Int := x + 1
def collection (xs : List Nat) (ignored : Option Bool) : Nat := xs.length
def polymorphic {α : Type u} (x : α) (ignored : Bool) : α := x
def withInstance {α : Type u} [Inhabited α] (ignored : Bool) : α := default
def higherOrder (f : Nat → Nat) (n : Nat) : Nat := f n
def dependent (n : Nat) (x : Fin (n + 1)) : Nat := x.val
def dependentResult (n : Nat) : Fin (n + 1) := ⟨0, Nat.zero_lt_succ n⟩

end FunctionCases
