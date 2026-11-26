import Lean

namespace StructureCases

def ifSame (flag : Bool) (x : Int) : Int :=
  if flag then x else x

def ifSelect (flag : Bool) (x : Int) : Int :=
  if flag then x else 0

def ifNested (outer inner : Bool) (x : Int) : Int :=
  if outer then (if inner then x else x) else 0

def letCancel (x y : Int) : Int :=
  let sum := x + y
  sum - y

def matchChoice (value : Option Nat) (fallback : Nat) : Nat :=
  match value with
  | none => fallback
  | some n => n

def addHelper (x y : Int) : Int := x + y
def subtractHelper (x y : Int) : Int := x - y

def nestedCall (x y : Int) : Int :=
  subtractHelper (addHelper x y) y

def structural (n ignored : Nat) : Nat :=
  match n with
  | 0 => 0
  | k + 1 => structural k ignored + 1

def tailAux : Nat → Nat → Nat
  | 0, acc => acc
  | n + 1, acc => tailAux n (acc + 1)

def tailLoop (n ignored : Nat) : Nat := tailAux n 0

mutual
  def evenParity (n ignored : Nat) : Bool :=
    match n with
    | 0 => true
    | k + 1 => oddParity k ignored
  def oddParity (n ignored : Nat) : Bool :=
    match n with
    | 0 => false
    | k + 1 => evenParity k ignored
end

end StructureCases
