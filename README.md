# SA Lean

面向 Lean 4 函数的语义依赖与退化分析原型。工具生成逐参数独立性目标；谓词生成恒真和恒假目标，一般函数生成常值性目标，并可通过 Lean-blaster 调用 SMT 求解器。

> 当前为研究原型。运行结果来自后端，本工具不生成 Lean 证明证书或复核反例；独立的符号执行状态和调用路径解释尚未实现。

## 功能

- 从指定的已编译 Lean 定义生成分析目标。
- 参数和返回值不限制为基础类型：支持生成多态、隐式参数、高阶参数和依赖类型的 Lean 目标；目标能否被后端翻译和求解另行报告。
- 调用 Lean-blaster 和 Z3，记录工具输出和可复现的 SMT-LIB 查询（如果工具输出查询）。
- 报告后端的 `valid`、`falsified`、`unknown` 和错误；保留完整查询及日志。
- 以人工标注的答案为测试基准，统计符合、不符合和未解决的目标。

对于 `examples/DependencyCase.lean` 中的示例，人工标注为 `gate.noise` 无影响、`gate.mode` 和 `gate.value` 有影响；`caller` 恒真且三个参数均无影响。

## 项目结构

```text
smt_route/
  Goals.lean          Lean 元编程：提取参数并生成目标
  analyze.py          命令行编排和后端调用
examples/
  DependencyCase.lean       主示例
  DependencyCaseProofs.lean 手写 Lean 对照证明
  ExtraCase.lean            Nat 和 Bool 对照示例
  FunctionCases.lean        普通函数、泛型和依赖类型示例
  StructureCases.lean       分支、绑定、匹配、调用及递归示例
  z3_gate_probe.py          手写 Z3 查询对照，不代表自动翻译
tests/
  test_goals.py       目标生成、标注比较及可选后端集成测试
  expected_results.json  人工标注的预期结论和理由
  benchmark.py        全部标注案例的端到端运行与比较
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

输出目录中的 `goals.json`、`results.json` 分别记录生成目标和结果；`query-*.lean`、`query-*.log` 保留后端输入输出。若 Lean-blaster 提供 SMT 转储，还会生成以 `(check-sat)` 结尾的 `query-*.smt2` 用于重跑；该文件是基于转储的复现文件。

`valid` 和 `falsified` 是后端对生成目标的判断，没有经过独立 Lean 复核。`unknown`、`error`、`not_run` 分别表示未判定、执行错误和未运行，均不能视作性质为假。如果后端输出格式发生变化，解析可能失败，应检查完整日志。历史输出中的 `confirmed`、`refuted`、`candidate` 使用旧版协议，不与新状态混用。

主要限制：目标必须是 `def`/`abbrev`；不支持转义的复杂 Lean 标识符。Lean 目标生成不等同于 SMT 翻译成功，特别是泛型、高阶函数和依赖类型的后端支持尚未保证。反例解析仅处理简单整数与布尔值；重放只尝试展开目标及同命名空间的直接依赖。尚未提供完整的输入语言支持检查、递归检测、路径解释、跨版本适配或大规模性能保证。

### 生成目标的约定

参数索引按声明中的所有参数从零开始计算，包括隐式参数和实例参数。普通独立性目标固定其他参数，只改变待分析参数；返回 `Prop` 时用 `↔` 比较，其他同类型返回值用命题等式 `=`。一般函数的 `constant` 目标比较任意两组输入的输出；所有输入一起变化，包括类型参数。空输入域会使全称常值性目标空真，因此这不表示一定存在可取到的返回值。

生成器沿函数类型展开参数；对于柯里化形式的函数值返回，后续函数参数也会被纳入参数列表，当前不提供将整个函数值作为最终输出进行比较的选项。

当变化一个参数会改变后续参数类型或返回类型时，使用两组完整输入，并要求其余参数两两满足异构等式 `HEq`，结论也使用 `HEq`；JSON 的 `comparison` 记为 `heterogeneous_fiberwise`。这是一种固定其他输入的依赖类型约定，可能因其他参数的类型依赖而限制能比较的输入对，不能解释为无条件改变任意参数。`constant` 在两组返回类型不定义相等时也使用 `HEq`，标为 `heterogeneous`。多态目标的 `universe_parameters` 列出需要声明的 universe；调用器自动加入 `universe` 声明。

工具不进行 Lean 证明或反例重放；后端原始模型可在日志中查看。

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

运行完整人工标注案例（输出目录必须为新目录或空目录）：

```powershell
python -m tests.benchmark --lean $env:SA_LEAN --blaster-path $env:SA_BLASTER --z3 $env:SA_Z3 --out sa-output/benchmark --jobs 2
```

`benchmark.json` 将后端结果与人工标注逐目标比较，`match` / `mismatch` 分别表示一致和冲突，`unresolved` 表示未知、错误或未运行。遗漏目标、重复目标或比较约定改变会作为案例错误，不参与评分。退出码 `0` 表示全部一致，`1` 表示存在冲突或案例错误，`2` 表示无冲突但有未解决目标。

只运行函数结构案例时可附加 `--module StructureCases`；重复该参数可以选择多个模块。结构案例覆盖相同与不同分支、嵌套条件、`let` 算术抵消、`Option` 模式匹配、嵌套调用、结构递归、尾递归和相互递归。所有结论仅以当前测试定义为范围，不代表相应结构的任意程序都可求解。

设计背景见 [项目设计文档](docs/项目设计文档.md) 和 [实验设计与暂行约定](docs/实验设计与暂行约定.md)；旧文档中的复核与结果状态约定已被本 README 取代。
