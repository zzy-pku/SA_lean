import Lean

open Lean Meta Elab Command

namespace SemanticAnalysis

private def emit (name kind : String) (index : Option Nat) (dependencies : Array String) (binders : Array Expr) (goal : Expr) (levels : List Name) (semantics : String := "ordinary") : MetaM Unit := do
  discard <| inferType goal
  let rendered ← withOptions (fun o => o.setBool `pp.fullNames true) do
    return (← ppExpr goal).pretty
  let binderData ← binders.mapM fun arg => do
    let decl ← arg.fvarId!.getDecl
    let ty ← ppExpr decl.type
    pure <| Json.mkObj [("name", toJson decl.userName.toString), ("type", toJson ty.pretty)]
  let msg := Json.mkObj [
    ("declaration", toJson name), ("kind", toJson kind),
    ("parameter_index", toJson index), ("unfold_dependencies", toJson dependencies),
    ("binders", toJson binderData), ("goal", toJson rendered),
    ("universe_parameters", toJson (levels.map Name.toString)), ("comparison", toJson semantics)]
  (liftM (IO.println s!"SA_GOAL:{msg.compress}") : MetaM Unit)

def generateGoals (name : Name) : MetaM Unit := do
  let info ← getConstInfo name
  match info with
  | .defnInfo _ => pure ()
  | _ => throwError "unsupported: target must be a definition"
  let mut dependencies : Array String := #[]
  if let some value := info.value? then
    let namespacePrefix := name.getPrefix.toString ++ "."
    let env ← getEnv
    for dep in value.getUsedConstants do
      if dep.toString.startsWith namespacePrefix then
        if let some (.defnInfo _) := env.find? dep then
          dependencies := dependencies.push dep.toString
  let levels := info.levelParams.map Level.param
  let target := mkConst name levels
  forallTelescope info.type fun args resultType => do
    let isPredicate ← isDefEq resultType (mkSort levelZero)
    let application := mkAppN target args
    if isPredicate then
      emit name.toString "always_true" none dependencies args (← mkForallFVars args application) info.levelParams
      let neg ← mkAppM ``Not #[application]
      emit name.toString "always_false" none dependencies args (← mkForallFVars args neg) info.levelParams
    else
      forallTelescope info.type fun others _ => do
        let other := mkAppN target others
        let otherType ← inferType other
        let sameType ← isDefEq resultType otherType
        let comparison ← if sameType then mkEq application other else mkAppM ``HEq #[application, other]
        let binders := args ++ others
        emit name.toString "constant" none dependencies binders (← mkForallFVars binders comparison) info.levelParams (if sameType then "ordinary" else "heterogeneous")
    for i in [:args.size] do
      let decl ← args[i]!.fvarId!.getDecl
      let mut dependent := resultType.containsFVar args[i]!.fvarId!
      for j in [i+1:args.size] do
        let next ← args[j]!.fvarId!.getDecl
        dependent := dependent || next.type.containsFVar args[i]!.fvarId!
      if !dependent then
        withLocalDeclD `sa_alternative decl.type fun alternative => do
          let other := mkAppN target (args.set! i alternative)
          let comparison ← if isPredicate then mkAppM ``Iff #[application, other] else mkEq application other
          emit name.toString "independent" (some i) dependencies (args.push alternative) (← mkForallFVars (args.push alternative) comparison) info.levelParams
      else
        forallTelescope info.type fun others _ => do
          let other := mkAppN target others
          let mut comparison ← mkAppM ``HEq #[application, other]
          for j in [:args.size] do
            if j != i then
              let constraint ← mkAppM ``HEq #[args[j]!, others[j]!]
              comparison ← mkArrow constraint comparison
          let binders := args ++ others
          emit name.toString "independent" (some i) dependencies binders (← mkForallFVars binders comparison) info.levelParams "heterogeneous_fiberwise"

syntax (name := semanticGoals) "#semantic_goals " ident : command

@[command_elab semanticGoals]
def elabSemanticGoals : CommandElab := fun stx => do
  let name ← liftCoreM <| realizeGlobalConstNoOverloadWithInfo stx[1]
  liftTermElabM <| generateGoals name

end SemanticAnalysis
