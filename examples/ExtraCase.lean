import Lean

namespace ExtraCase

def natCheck (x : Nat) : Prop := x - 1 = 0

def choice (b : Bool) (x : Int) : Prop := (if b then x else 0) = 0

end ExtraCase
