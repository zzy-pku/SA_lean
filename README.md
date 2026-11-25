# SA Lean

面向 Lean 4 谓词的语义依赖与退化分析原型。工具自动生成恒真、恒假和逐参数独立性目标，通过 Lean-blaster 调用 SMT 求解器，并尝试用 Lean 独立复核结果。

> 当前为研究原型，只在少量示例上验证；不应将未复核的候选结论作为证明。独立的、可观察的符号执行状态和调用路径解释尚未实现。

## 功能

- 从指定的已编译 Lean 定义生成分析目标。
- 调用 Lean-blaster 和 Z3，记录工具输出和可复现的 SMT-LIB 查询（如果工具输出查询）。
- 将简单反例代入原 Lean 定义；验证成功才标记 `refuted`。
- 对后端报告有效的目标独立尝试 Lean `omega` 等策略；验证成功才标记 `confirmed`。
- 未验证的结果保留为 `candidate`；工具未执行、未知和错误分别记录，不将它们解释为性质不成立。

对于 `examples/DependencyCase.lean` 中的示例，原型实测得到 `gate.noise` 无影响、`gate.mode` 和 `gate.value` 有影响；`caller` 恒真且三个参数均无影响。

## 项目结构

```text
smt_route/
  Goals.lean          Lean 元编程：提取参数并生成目标
  analyze.py          命令行编排、后端调用和结果复核
examples/
  DependencyCase.lean       主示例
  DependencyCaseProofs.lean 手写 Lean 对照证明
  ExtraCase.lean            Nat 和 Bool 对照示例
  z3_gate_probe.py          手写 Z3 查询对照，不代表自动翻译
tests/
  test_goals.py       目标生成、见证处理及可选后端集成测试
docs/                 设计和实验记录
```

## 环境准备

已验证组合：

- Lean `4.24.0`；根目录 `lean-toolchain` 固定该版本。
- [Lean-blaster](https://github.com/input-output-hk/Lean-blaster) 提交 `3b8ad910575c712320565a791a1b244d42859b09`，使用同一 Lean 工具链构建。
- 可执行的 Z3 `5.4.1`。
- Python `3.13`；核心编排器只依赖 Python 标准库。

示例使用 Windows PowerShell；其他平台可按对应的命令调整路径。以下命令会在仓库外创建 Lean-blaster 目录，避免将其源码和构建产物加入本仓库：

```powershell
git clone https://github.com/input-output-hk/Lean-blaster.git ../Lean-blaster
git -C ../Lean-blaster checkout 3b8ad910575c712320565a791a1b244d42859b09
Push-Location ../Lean-blaster
lake build Blaster
Pop-Location
```

需要自行安装 Lean/elan 和 Z3，确保 `lean`、`lake` 与 `z3` 可运行。目标项目、其编译产物和 Lean-blaster 必须使用兼容的 Lean 工具链；本工具不会自动修改目标项目版本。如果 `z3` 不在 PATH，可以通过 `--z3` 指定可执行文件。

## 运行示例

在仓库根目录先编译示例模块：

```powershell
Push-Location examples
lean -o DependencyCase.olean DependencyCase.lean
Pop-Location
```

然后分析 `gate`，其中 `--out` 必须是新目录或空目录：

```powershell
python -m smt_route.analyze `
  --lean (Get-Command lean).Source `
  --project . `
  --lean-path examples `
  --module DependencyCase `
  --decl DependencyCase.gate `
  --blaster-path ../Lean-blaster/.lake/build/lib/lean `
  --z3 (Get-Command z3).Source `
  --out sa-output/gate `
  --timeout 60
```

将 `--decl` 改为 `DependencyCase.caller`，并使用另一个输出目录，可分析调用方。分析其他项目时，`--project` 指向其项目根，`--module` 和 `--decl` 指向目标，`--lean-path` 应包含已构建模块和所需依赖；也可在适当的 `lake env` 中提供项目环境。

不传 `--blaster-path` 时，仅生成目标并将后端状态记为 `not_run`，进程返回码为 `2`。完整调用返回 `0` 只表示执行无适配器错误，不表示每个目标都已证明。

## 输出和可信边界

输出目录中的 `goals.json`、`results.json` 分别记录生成目标和结果；`query-*.lean`、`query-*.log` 保留后端输入输出。若 Lean-blaster 提供 SMT 转储，还会生成以 `(check-sat)` 结尾的 `query-*.smt2` 用于重跑；该文件是基于转储的复现文件。`witness-*.lean` 和 `validate-*.lean` 分别记录反例重放与独立证明尝试。

`confirmed` 和 `refuted` 表示对**生成的目标**完成了相应 Lean 检查，并不判断该目标是否符合用户原始意图。Lean-blaster 的原始 `Valid` 不是 Lean 内核证明；独立验证失败时结果保留为 `candidate`。如果后端输出格式发生变化，解析可能失败，应检查完整日志。

主要限制：目前目标参数仅支持显式、非依赖的 `Int`、`Nat`、`Bool`，目标必须是返回 `Prop` 的 `def`/`abbrev`；不支持转义的复杂 Lean 标识符。反例解析仅处理简单整数与布尔值；重放只尝试展开目标及同命名空间的直接依赖。尚未提供完整的输入语言支持检查、递归检测、路径解释、跨版本适配或大规模性能保证。

## 测试

设置 Lean 路径后运行目标生成和见证解析测试：

```powershell
$env:SA_LEAN = (Get-Command lean).Source
python -m unittest tests.test_goals -v
```

若还要运行实际 Lean-blaster/Z3 的端到端测试：

```powershell
$env:SA_BLASTER = (Resolve-Path ../Lean-blaster/.lake/build/lib/lean).Path
$env:SA_Z3 = (Get-Command z3).Source
python -m unittest tests.test_goals -v
```

没有设置对应环境变量的集成测试会标记为跳过。手写 Z3 对照 `examples/z3_gate_probe.py` 另需安装 `z3-solver` Python 包。

设计及后续实验见 [项目设计文档](docs/项目设计文档.md) 和 [实验设计与暂行约定](docs/实验设计与暂行约定.md)。
