import Lean

open Lean Meta Elab Command

namespace SemanticAnalysis

private def emit (name kind : String) (index : Option Nat) (dependencies : Array String) (binders : Array Expr) (goal : Expr) : MetaM Unit := do
  let rendered ← withOptions (fun o => o.setBool `pp.fullNames true) do
    return (← ppExpr goal).pretty
  let binderData ← binders.mapM fun arg => do
    let decl ← arg.fvarId!.getDecl
    let ty ← ppExpr decl.type
    pure <| Json.mkObj [("name", toJson decl.userName.toString), ("type", toJson ty.pretty)]
  let msg := Json.mkObj [
    ("declaration", toJson name), ("kind", toJson kind),
    ("parameter_index", toJson index), ("unfold_dependencies", toJson dependencies),
    ("binders", toJson binderData), ("goal", toJson rendered)]
  (liftM (IO.println s!"SA_GOAL:{msg.compress}") : MetaM Unit)

private def supportedType (e : Expr) : Bool :=
  e.isConstOf ``Int || e.isConstOf ``Nat || e.isConstOf ``Bool

def generateGoals (name : Name) : MetaM Unit := do
  let info ← getConstInfo name
  unless info.levelParams.isEmpty do
    throwError "unsupported: universe-polymorphic declaration"
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
  forallTelescope info.type fun args resultType => do
    unless ← isDefEq resultType (mkSort levelZero) do
      throwError "unsupported: target must return Prop and have nondependent parameters"
    for arg in args do
      let decl ← arg.fvarId!.getDecl
      unless decl.binderInfo == .default do
        throwError "unsupported: implicit or instance argument {decl.userName}"
      unless supportedType decl.type do
        throwError "unsupported: parameter {decl.userName} has unsupported or dependent type {decl.type}"
    let application := mkAppN (mkConst name) args
    emit name.toString "always_true" none dependencies args (← mkForallFVars args application)
    let neg ← mkAppM ``Not #[application]
    emit name.toString "always_false" none dependencies args (← mkForallFVars args neg)
    for i in [:args.size] do
      let decl ← args[i]!.fvarId!.getDecl
      withLocalDeclD `sa_alternative decl.type fun alternative => do
        let other := mkAppN (mkConst name) (args.set! i alternative)
        let iff ← mkAppM ``Iff #[application, other]
        emit name.toString "independent" (some i) dependencies (args.push alternative) (← mkForallFVars (args.push alternative) iff)

syntax (name := semanticGoals) "#semantic_goals " ident : command

@[command_elab semanticGoals]
def elabSemanticGoals : CommandElab := fun stx => do
  let name ← liftCoreM <| realizeGlobalConstNoOverloadWithInfo stx[1]
  liftTermElabM <| generateGoals name

end SemanticAnalysis
