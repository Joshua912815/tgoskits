# starry-evolve: AI 驱动的 StarryOS 内核持续改进框架

## 一、这个系统是什么

starry-evolve 是一个**让 AI 自主发现并修复操作系统内核 bug 的自动化框架**。

具体来说，它解决的问题是：StarryOS 是一个兼容 Linux 的教学操作系统内核，目前有约 200 个系统调用（syscall）被分发处理，但其中一部分只是空壳（stub）——函数存在但只打印一条 `warn!("dummy")` 日志就返回了，或者实现不完全，和 Linux 的真实行为有差异。手动找出这些问题、一个一个修复、测试、确保不引入新问题，是非常耗时的工作。

starry-evolve 让 Claude（AI）能够自动完成这个循环：

```
发现内核中哪些 syscall 实现不完整
      ↓
查找 Linux 对这个 syscall 的行为规范（"契约"）
      ↓
修改内核代码，让行为和 Linux 一致
      ↓
编写 C 语言测试程序，在 QEMU 模拟器中运行验证
      ↓
跨所有支持的 CPU 架构做回归测试，确保修复没有破坏其他功能
      ↓
记录结果，选择下一个改进目标，循环往复
```

这个框架运行在 Claude Code（Anthropic 官方的命令行 AI 工具）内部，利用 Claude Code 的 skill（技能）、agent（专家）、hook（钩子）机制来组织工作流。用户既可以让 AI 自主循环（自动模式），也可以手动调用单个技能来处理特定任务（手动模式）。

---

## 二、核心设计理念

### 2.1 确定性工具 > AI 猜测

AI 可以"幻觉"——编造不存在的函数、错误地声称某个 syscall 已实现。为了避免这个问题，框架的核心分析工作由 **Python 脚本** 完成。这些脚本直接解析源代码文件，输出 JSON 或 Markdown 格式的确定结果。AI 只负责**解释和决策**，不负责**发现事实**。

例如，`syscall_audit.py` 会逐行解析 `os/StarryOS/kernel/src/syscall/mod.rs` 文件中的 match 分支，提取每个 `Sysno::XXX =>` 后面调用的函数名，然后用 grep 查找该函数的实际实现，检查函数体中是否包含 `warn!("dummy")`、`todo!()` 等桩标志。整个过程完全基于文本解析，AI 无法干预结果。

### 2.2 ANALYZE → CONTRACT → FIX → TEST → VERIFY 五阶段循环

每一轮改进都严格遵循这个顺序：

1. **ANALYZE（分析）**：扫描内核，找出所有不完整的 syscall 实现，按优先级排序
2. **CONTRACT（契约）**：查阅 Linux man page，理解这个 syscall 的正确行为，和 StarryOS 当前实现对比
3. **FIX（修复）**：编写或修改内核代码
4. **TEST（测试）**：生成 C 测试程序，在 QEMU 中运行
5. **VERIFY（验证）**：跨所有架构做回归测试

每个阶段都有对应的 Claude Code 技能。如果任何一个阶段失败（比如测试没通过），变更会被回滚，目标标记为需要后续关注。

### 2.3 状态持久化

框架在工作过程中会持续记录状态，这样即使 Claude Code 会话中断，下次启动也能从断点继续。状态存储在以下文件中：

- `scripts/starry-evolve/journal.md`：人工可读的操作日志
- `scripts/starry-evolve/syscall_status.yaml`：每个 syscall 的跟踪状态
- `scripts/starry-evolve/baseline.json`：上次测试通过的基线结果

---

## 三、系统组成详解

整个框架由四个层次组成：

```
┌─────────────────────────────────────────────────┐
│            用户交互层                              │
│  /starry-analyze  /starry-fix  /starry-iterate   │
│  /starry-contract /starry-test /starry-verify     │
│  /starry-report                                   │
├─────────────────────────────────────────────────┤
│            安全护栏层                              │
│  SessionStart Hook（自动加载上下文）               │
│  Stop Hook（自动检查代码质量）                     │
│  .claude/settings.json（权限白名单）              │
├─────────────────────────────────────────────────┤
│            专家审查层                              │
│  syscall-reviewer Agent（代码审查）               │
│  regression-watcher Agent（回归检测）             │
├─────────────────────────────────────────────────┤
│            确定性分析层                            │
│  syscall_audit.py   stub_scanner.py              │
│  build_checker.py   test_runner.py               │
│  regression_diff.py                               │
└─────────────────────────────────────────────────┘
```

下面逐个详细说明。

---

## 四、七个技能（Skills）详解

技能是 Claude Code 的核心概念。一个技能就是一个 `SKILL.md` 文件，里面写好了"当用户说 X 时，你应该做 Y"的详细指令。Claude Code 会自动扫描 `.claude/skills/` 目录，把所有技能注册到系统中。

### 4.1 `/starry-analyze` — 内核分析

**文件位置**：`.claude/skills/starry-analyze/SKILL.md`

**触发方式**：用户说 "analyze starry"、"syscall audit"、"find kernel issues"、"内核分析"、"发现内核问题"，或者在命令行输入 `/starry-analyze`

**做什么**：
1. 运行 `python3 scripts/starry-evolve/syscall_audit.py --repo-root . --format markdown`
   - 这个脚本会解析 `os/StarryOS/kernel/src/syscall/mod.rs`（syscall 分发表）
   - 提取所有 `Sysno::XXX => handler(...)` 分支
   - 对每个 handler 函数，grep 查找其定义，检查函数体中是否有 stub 标志
   - 输出分类结果：IMPLEMENTED / PARTIAL / STUB
2. 运行 `python3 scripts/starry-evolve/stub_scanner.py --repo-root . --format markdown`
   - 扫描所有 `os/StarryOS/kernel/src/` 下的 `.rs` 文件
   - 搜索 8 种模式：`warn!("dummy")`、`warn!("Unimplemented")`、`todo!()`、`unimplemented!()`、`FIXME`、`return Ok(0)`（硬编码空返回）、`ENOSYS`、空函数体
   - 每个发现标注严重性：CRITICAL / HIGH / MEDIUM / LOW
3. 综合两个工具的输出，按子系统（fs/task/mm/net/signal/ipc/sync/io_mpx/time）分组
4. 按优先级排序：安全相关 stub > 被 busybox 使用的 syscall > 容易验证的改进
5. 更新 `scripts/starry-evolve/syscall_status.yaml` 记录发现的 syscall

**当前验证结果**：
```
Total dispatched: 200
- Implemented: 145（已完整实现）
- Partial: 28（部分实现，有功能但缺少边界情况处理）
- Stub/Dummy: 27（空壳或桩实现）
```

### 4.2 `/starry-contract` — 契约对比

**文件位置**：`.claude/skills/starry-contract/SKILL.md`

**触发方式**：用户说 "check contract for readlinkat"、"compare syscall openat"、"对比 Linux 行为"

**做什么**：
1. 在 `os/StarryOS/kernel/src/syscall/` 下搜索目标 syscall 的实现函数
2. 阅读完整实现，注意错误处理路径和边界情况
3. 检查 `scripts/starry-evolve/contracts/` 是否已有该 syscall 的契约文档
4. 如果没有，通过 web search 查找 Linux man page：
   - 参数的语义和验证规则
   - 返回值：成功返回什么、错误返回什么
   - 错误码（ENOSYS/EINVAL/ENOENT/ENOMEM...）的触发条件
   - 边界情况：NULL 指针、零长度缓冲区、整数溢出
5. 生成结构化对比文档，写入 `scripts/starry-evolve/contracts/<syscall>.md`
6. 更新 `syscall_status.yaml` 状态为 ANALYZED 或 CONTRACTED

**为什么需要这一步**：不能直接上手改代码，必须先搞清楚 Linux 对这个 syscall 的"契约"是什么。比如 `readlinkat` 系统调用，Linux 规定：如果缓冲区太小，返回 `ERANGE`；如果路径不存在，返回 `ENOENT`；如果路径不是符号链接，返回 `EINVAL`。StarryOS 可能只处理了正常路径，漏掉了错误路径。

### 4.3 `/starry-fix` — 代码修复

**文件位置**：`.claude/skills/starry-fix/SKILL.md`

**触发方式**：用户说 "fix sys_readlinkat"、"implement syscall mmap"、"修复内核"、"实现 syscall"

**做什么**：
1. 阅读契约文档和当前实现
2. 阅读同一子系统中其他已正确实现的 syscall（学习代码风格）
3. 修改代码，遵循：
   - 使用 `ax_errno::LinuxError` 进行错误处理（和 Linux errno 对应）
   - 使用 `starry_vm` 模块的安全函数访问用户空间内存
   - 处理所有错误路径（每个 Linux man page 中定义的 errno）
   - 使用 `unsafe(no_mangle)` 而不是 `#[no_mangle]`（仓库规范）
4. 运行 `cargo xtask clippy --package starry-kernel`（Rust 代码检查）
5. 运行 `cargo fmt`（代码格式化）
6. 运行 `cargo xtask starry build --arch riscv64`（验证编译通过）
7. 更新 `syscall_status.yaml` 和 `journal.md`

**关键约束**：
- 必须用 `cargo xtask` 命令，不能用原生 `cargo`（项目规范）
- 不能用 `#[allow(...)]` 消除 clippy 警告，必须修复根本原因
- 不能提交未通过验证的代码

### 4.4 `/starry-test` — 测试生成

**文件位置**：`.claude/skills/starry-test/SKILL.md`

**触发方式**：用户说 "test syscall readlinkat"、"write test for openat"、"生成测试"

**做什么**：
1. 为目标 syscall 编写最小化的 C 测试程序：
   ```c
   #include <stdio.h>
   #include <errno.h>
   #include <string.h>
   int main() {
       int pass = 0, fail = 0;
       // 测试1：正常操作
       // 测试2：错误路径（EINVAL）
       printf("Results: %d passed, %d failed\n", pass, fail);
       return fail > 0 ? 1 : 0;
   }
   ```
2. 放入 `scripts/starry-evolve/testcases/<syscall>_test.c`
3. 交叉编译为 RISC-V 静态二进制（需要 `riscv64-linux-musl-gcc` 工具链）
4. 注入 StarryOS 的 rootfs 文件系统
5. 运行 `cargo xtask starry qemu --arch riscv64` 启动 QEMU 执行测试
6. 解析串口输出，分类为 PASS / FAIL / CRASH / TIMEOUT
7. 结果写入 `scripts/starry-evolve/reports/`

**为什么用 C 而不是 Rust**：测试程序运行在 StarryOS 用户态，使用的是 Linux 系统调用接口。C 语言直接调用 libc 函数（如 `readlink()`、`open()`），对应底层 syscall，最贴近真实应用的使用方式。

### 4.5 `/starry-verify` — 回归验证

**文件位置**：`.claude/skills/starry-verify/SKILL.md`

**触发方式**：用户说 "verify starry"、"run regression"、"回归测试"、"全面验证"

**做什么**（按顺序执行）：
1. `cargo xtask clippy` — 全工作空间代码检查
2. `cargo xtask test` — 运行所有主机端标准测试（`scripts/test/std_crates.csv` 中的 54 个包）
3. `python3 scripts/starry-evolve/build_checker.py --repo-root .` — 四个架构全部编译
4. 对每个架构运行 `cargo xtask starry test qemu --target <arch>` — QEMU 测试
5. （可选）`cargo xtask test arceos --target riscv64` — 检查共享的 ArceOS 模块没有回归
6. `python3 scripts/starry-evolve/regression_diff.py --repo-root .` — 和基线对比
7. 如果全部通过，用 `test_runner.py --update-baseline` 更新基线

**回归处理规则**：如果发现任何测试从 PASS 变成 FAIL，不提交变更，分析原因，修复或回滚。

### 4.6 `/starry-iterate` — 自主迭代

**文件位置**：`.claude/skills/starry-iterate/SKILL.md`

**触发方式**：用户说 "iterate on starry"、"autonomous improve"、"自动迭代"、"持续改进"

**做什么**：自动执行一个完整的改进循环：

```
Phase 1: 调用 starry-analyze → 选出最高优先级目标
Phase 2: 调用 starry-contract → 理解 Linux 行为
Phase 3: 调用 starry-fix → 实现修复
Phase 4: 调用 starry-test → 生成和运行测试
Phase 5: 调用 starry-verify → 回归检测
```

目标选择优先级：
1. 安全相关的 stub（`todo!()` 会导致运行时 panic）
2. 被 busybox 等应用广泛使用的 syscall
3. 容易验证的改进
4. 尚未被分析过的 syscall

**配合 `/loop` 实现多轮自主循环**：
```
/loop use starry-iterate to improve the StarryOS kernel
```
这会让 Claude 在每一轮结束后自动开始下一轮，持续改进直到没有目标或会话结束。

**安全约束**：
- 每轮只修改一个 syscall
- 失败的目标最多重试 2 次
- 所有变更必须通过 clippy + fmt + 编译 + 测试
- 不提交未验证的变更

### 4.7 `/starry-report` — 进度报告

**文件位置**：`.claude/skills/starry-report/SKILL.md`

**触发方式**：用户说 "show progress"、"report status"、"进度报告"、"改进总结"

**做什么**：读取所有状态文件，生成格式化的进度报告，包含：
- 已分析/已实现/已测试/已验证的 syscall 数量
- 每个子系统的改进进度
- 最近 5 条操作记录
- 待处理的目标列表
- 各架构的测试通过率

---

## 五、两个专家（Agents）详解

Agent 是独立的 AI 角色，拥有受限的工具权限。它们被技能调用，提供"第二双眼睛"来审查工作。

### 5.1 `syscall-reviewer`（系统调用审查员）

**文件位置**：`.claude/skills/starry-iterate/agents/syscall-reviewer.yaml`

**权限**：只读（Read、Grep、Glob）——不能修改任何文件

**什么时候被调用**：在 `starry-fix` 完成代码修改之后、测试之前

**做什么**：逐项检查修改后的 syscall 实现：
1. 参数处理：所有参数是否按正确顺序验证？
2. 错误码：是否返回了正确的 errno（ENOSYS、EINVAL、ENOENT、EACCES 等）？
3. 返回值：成功和失败的返回值是否符合 Linux 契约？
4. 用户空间内存访问：是否使用了 `starry_vm` 安全函数？
5. 边界情况：NULL 指针、零长度、溢出条件是否处理？
6. 风格一致性：是否遵循了相邻 syscall 实现的模式？

**输出格式**：对每个变更给出 PASS / ISSUE（附文件:行号）/ SUGGESTION（不阻塞）

**为什么需要它**：写代码的 AI 和审查代码的 AI 是独立的。审查者没有写代码时的思维惯性，更容易发现问题。这类似于人类开发中的 code review。

### 5.2 `regression-watcher`（回归监控器）

**文件位置**：`.claude/skills/starry-iterate/agents/regression-watcher.yaml`

**权限**：Read + Bash（只读命令）

**什么时候被调用**：在任何内核变更之后、提交之前

**做什么**：
1. `git diff --name-only HEAD` — 查看哪些文件被修改了
2. 如果内核文件有变更，`cargo xtask starry build --arch riscv64` — 编译检查
3. `cargo xtask starry test qemu --target riscv64` — 运行测试
4. `python3 scripts/starry-evolve/regression_diff.py` — 和基线对比

**输出格式**：
- BUILD: 每个架构 PASS/FAIL
- TEST: 每个目标 PASS/FAIL
- REGRESSIONS: 从 PASS 变成 FAIL 的测试列表
- IMPROVEMENTS: 从 FAIL 变成 PASS 的测试列表

---

## 六、两个钩子（Hooks）详解

Hook 是在特定事件发生时自动执行的脚本。它们在 `.claude/settings.json` 中配置。

### 6.1 SessionStart Hook（会话启动钩子）

**触发时机**：每次启动新的 Claude Code 会话时

**配置位置**：`.claude/settings.json` → `hooks.SessionStart`

**执行的脚本**：`scripts/starry-evolve/hooks/session_context.py`

**做什么**：
1. 查找仓库根目录（向上搜索包含 `[workspace]` 的 `Cargo.toml`）
2. 读取 Git 信息（当前分支、最近 5 条 commit）
3. 读取 `scripts/starry-evolve/journal.md` 的最后 50 行
4. 读取 `scripts/starry-evolve/syscall_status.yaml` 的统计摘要
5. 输出一个结构化的上下文块

**输出示例**：
```
[starry-evolve session context]
Branch: b1
Status: No syscalls tracked yet. Run /starry-analyze to populate.

Recent commits:
d2294a838 Adjust VirtIO net device queue size and buffer management (#184)
762359358 Merge branch 'dev' of github.com:rcore-os/tgoskits into dev
...

Journal (last entries):
# StarryOS Evolution Journal
...
```

**为什么需要它**：Claude 每次启动新会话时没有任何记忆。这个钩子让 Claude 在会话一开始就知道：当前在哪个分支、之前做过什么、还有什么待做。类似于你每天上班前看一眼昨天的笔记。

### 6.2 Stop Hook（会话结束钩子）

**触发时机**：每次 Claude Code 会话即将结束时

**配置位置**：`.claude/settings.json` → `hooks.Stop`

**执行的脚本**：`scripts/starry-evolve/hooks/pre_commit_check.py`

**做什么**：
1. `git diff --name-only HEAD` — 检查是否有 `os/StarryOS/kernel/` 下的文件被修改
2. 如果没有内核修改，直接返回（不做任何检查）
3. 如果有内核修改：
   - `cargo fmt --check` — 检查代码格式
   - `cargo xtask clippy --package starry-kernel` — 检查代码质量
4. 如果任何检查失败，输出警告

**为什么需要它**：防止 AI（或人）在匆忙中提交格式混乱或有 clippy 警告的代码。类似于 Git 的 pre-commit hook，但在 Claude Code 层面执行。

---

## 七、五个确定性工具（Python Scripts）详解

这五个脚本是框架的"眼睛"——它们提供 AI 无法伪造的、基于源代码分析的确切数据。

### 7.1 `syscall_audit.py` — 系统调用审计

**文件位置**：`scripts/starry-evolve/syscall_audit.py`

**用法**：
```bash
python3 scripts/starry-evolve/syscall_audit.py --repo-root . --format markdown
python3 scripts/starry-evolve/syscall_audit.py --repo-root . --format json
```

**工作原理**：

1. **解析分发表**：读取 `os/StarryOS/kernel/src/syscall/mod.rs`，找到 `match sysno { ... }` 块
2. **提取 match 分支**：用正则表达式匹配 `Sysno::XXX => handler(...)` 格式
   - 处理多路分支：`Sysno::A | Sysno::B => handler(...)`
   - 处理条件编译：`#[cfg(target_arch = "x86_64")]`
   - 识别直接返回：`=> Ok(0)` 或 `=> Err(...)`
   - 识别 dummy fd：`=> sys_dummy_fd(sysno)`
3. **分类每个 handler**：对提取到的函数名，用 grep 在 `os/StarryOS/kernel/src/syscall/` 下搜索定义
   - 读取函数体（最多 2000 字符）
   - 检查是否包含 stub 标志：`warn!("dummy")`、`warn!("Dummy")`、`warn!("Unimplemented")`、`todo!()`、`unimplemented!()`
   - 检查是否包含硬编码返回：`return Ok(0)`
   - 分类为：IMPLEMENTED（完整实现）、PARTIAL（部分实现）、STUB（桩）
4. **按子系统分组**：通过解析注释标签（`// fs ctl`、`// mm`、`// task management` 等）归类
5. **输出报告**

**当前输出摘要**：
```
Total dispatched: 200
- Implemented: 145
- Partial: 28
- Stub/Dummy: 27
```

### 7.2 `stub_scanner.py` — 桩函数扫描

**文件位置**：`scripts/starry-evolve/stub_scanner.py`

**用法**：
```bash
python3 scripts/starry-evolve/stub_scanner.py --repo-root . --format markdown
```

**工作原理**：递归扫描 `os/StarryOS/kernel/src/` 下所有 `.rs` 文件，搜索 8 种模式：

| 模式 ID | 正则 | 严重性 | 说明 |
|---------|------|--------|------|
| `warn_dummy` | `warn!("([Dd]ummy[^"]*)")` | HIGH | 桩函数警告 |
| `warn_unimplemented` | `warn!("([Uu]nimplemented[^"]*)")` | HIGH | 未实现警告 |
| `todo_macro` | `todo!()` | CRITICAL | 运行时会 panic |
| `unimplemented_macro` | `unimplemented!()` | CRITICAL | 运行时会 panic |
| `fixme_comment` | `FIXME\|TODO\|HACK\|XXX` | LOW | 待办注释 |
| `ok_zero_return` | `return\s+Ok\(\s*0\s*\)` | MEDIUM | 硬编码空返回 |
| `enosys_return` | `ENOSYS` | HIGH | "系统调用未实现"错误 |
| `empty_fn_body` | `pub fn \w+\(...\) -> ...{\s*}` | CRITICAL | 空函数体 |

**当前输出摘要**：
```
Total findings: 89
- Critical: 1（pseudofs/dev/tty/terminal/ldisc.rs:347 有一个 todo!()）
- High: 7（6 个 warn!("dummy") + 1 个 ENOSYS）
- Medium: 21（21 个 return Ok(0)）
- Low: 60（60 个 FIXME/TODO/HACK 注释）
```

### 7.3 `build_checker.py` — 多架构构建检查

**文件位置**：`scripts/starry-evolve/build_checker.py`

**用法**：
```bash
python3 scripts/starry-evolve/build_checker.py --repo-root . --archs riscv64,aarch64
```

**工作原理**：对每个指定的 CPU 架构，运行 `cargo xtask starry build --arch <arch>`，捕获结果。超时 300 秒。输出每个架构的编译状态和关键错误信息。

**支持的架构**：riscv64、aarch64、x86_64、loongarch64

### 7.4 `test_runner.py` — QEMU 测试执行

**文件位置**：`scripts/starry-evolve/test_runner.py`

**用法**：
```bash
# 运行测试
python3 scripts/starry-evolve/test_runner.py --repo-root . --target riscv64
# 运行并更新基线
python3 scripts/starry-evolve/test_runner.py --repo-root . --target riscv64 --update-baseline
```

**工作原理**：
1. 运行 `cargo xtask starry test qemu --target <arch>`
2. 捕获 stdout/stderr，解析结果
3. 如果指定 `--update-baseline`，将结果写入 `baseline.json`
4. 超时 120 秒

### 7.5 `regression_diff.py` — 回归对比

**文件位置**：`scripts/starry-evolve/regression_diff.py`

**用法**：
```bash
python3 scripts/starry-evolve/regression_diff.py --repo-root .
```

**工作原理**：
1. 读取 `scripts/starry-evolve/baseline.json`（上次通过的基线）
2. 对每个架构运行测试
3. 对比：
   - **回归（REGRESSION）**：基线 PASS → 当前 FAIL
   - **改进（IMPROVEMENT）**：基线 FAIL → 当前 PASS
   - **不变（SAME）**：状态没变
4. 输出报告

---

## 八、状态管理系统

### 8.1 `syscall_status.yaml` — syscall 跟踪状态

**文件位置**：`scripts/starry-evolve/syscall_status.yaml`

每个被跟踪的 syscall 有一个状态，按以下生命周期流转：

```
DISCOVERED → ANALYZED → CONTRACTED → IMPLEMENTED → TESTED → VERIFIED
```

- **DISCOVERED**：被审计工具发现，但还没深入分析
- **ANALYZED**：已阅读 StarryOS 实现
- **CONTRACTED**：已生成 Linux 契约文档
- **IMPLEMENTED**：已修改内核代码
- **TESTED**：已在至少一个架构上测试通过
- **VERIFIED**：已在所有架构上回归测试通过

### 8.2 `journal.md` — 操作日志

**文件位置**：`scripts/starry-evolve/journal.md`

人工可读的日志文件，记录每次操作的详情。格式：
```markdown
## 2026-05-09 -- sys_readlinkat
- Analyzed: found stub returning ENOSYS
- Contract: compared with Linux man page
- Fixed: implemented symlink resolution via VFS
- Tested: PASS on riscv64
- Regression: no regressions detected
```

### 8.3 `baseline.json` — 测试基线

**文件位置**：`scripts/starry-evolve/baseline.json`

存储上次测试通过的结果，用于回归对比。由 `test_runner.py --update-baseline` 更新。

### 8.4 其他状态目录

- `scripts/starry-evolve/contracts/`：每个 syscall 的 Linux 契约文档（Markdown）
- `scripts/starry-evolve/testcases/`：C 测试程序源码
- `scripts/starry-evolve/reports/`：测试执行报告（JSON）

---

## 九、配置文件详解

### 9.1 `.claude/settings.json` — 权限和钩子配置

```json
{
  "permissions": {
    "allow": [
      "Bash(cargo xtask *)",    // 允许运行所有 cargo xtask 命令
      "Bash(cargo fmt *)",       // 允许代码格式化
      "Bash(cargo clippy *)",    // 允许代码检查
      "Bash(python3 scripts/starry-evolve/*)",  // 允许运行框架脚本
      "Bash(git log/diff/status/branch/stash *)",  // 允许 git 只读操作
      "Bash(ls/find/grep/wc/cat *)"  // 允许通用只读命令
    ]
  },
  "hooks": {
    "SessionStart": [
      {
        "type": "command",
        "command": "python3 scripts/starry-evolve/hooks/session_context.py"
      }
    ],
    "Stop": [
      {
        "type": "command",
        "command": "python3 scripts/starry-evolve/hooks/pre_commit_check.py"
      }
    ]
  }
}
```

**permissions.allow 的作用**：Claude Code 默认会在执行 shell 命令前向用户确认。配置了 allow 列表后，匹配的命令会自动执行，不需要人工点击"允许"。这里允许的都是只读命令和构建/测试命令，不包含 `git push`、`rm` 等危险操作。

### 9.2 `AGENTS.md` — 项目级规则

这个文件被追加了一段新内容：

```markdown
## StarryOS Evolution Skills
- `starry-analyze`: Audit syscall coverage and find kernel issues
- `starry-contract`: Extract Linux syscall contracts and compare with StarryOS implementation
...
Use `starry-iterate` for autonomous improvement sessions. Use individual skills for targeted work.
All kernel improvement state is tracked in `scripts/starry-evolve/`.
```

**作用**：Claude Code 在每次会话开始时都会读取 AGENTS.md。这段文字让 Claude 知道有这些技能可用，以及去哪里找状态数据。

---

## 十、目录结构总览

```
scripts/starry-evolve/                    ← 框架根目录
├── syscall_audit.py                      ← 工具：审计 syscall 分发表
├── stub_scanner.py                       ← 工具：扫描桩函数和不完整实现
├── build_checker.py                      ← 工具：多架构编译检查
├── test_runner.py                        ← 工具：QEMU 测试执行
├── regression_diff.py                    ← 工具：回归对比
├── syscall_status.yaml                   ← 状态：syscall 跟踪
├── journal.md                            ← 状态：操作日志
├── baseline.json                         ← 状态：测试基线
├── contracts/                            ← 状态：Linux 契约文档
├── testcases/                            ← 状态：C 测试程序
├── reports/                              ← 状态：测试报告
└── hooks/
    ├── session_context.py                ← 钩子：SessionStart 上下文加载
    └── pre_commit_check.py               ← 钩子：Stop 代码质量检查

.claude/
├── settings.json                         ← 配置：权限白名单 + 钩子定义
└── skills/
    ├── update-std-tests/                 ← 已有技能（未修改）
    ├── arceos-test-adapter/              ← 已有技能（未修改）
    ├── starry-analyze/SKILL.md           ← 新技能：内核分析
    ├── starry-contract/SKILL.md          ← 新技能：契约对比
    ├── starry-fix/SKILL.md               ← 新技能：代码修复
    ├── starry-test/SKILL.md              ← 新技能：测试生成
    ├── starry-verify/SKILL.md            ← 新技能：回归验证
    ├── starry-iterate/                   ← 新技能：自主迭代
    │   ├── SKILL.md
    │   └── agents/
    │       ├── syscall-reviewer.yaml     ← 专家：系统调用审查员
    │       └── regression-watcher.yaml   ← 专家：回归监控器
    └── starry-report/SKILL.md            ← 新技能：进度报告

.agents/skills/                           ← .claude/skills/ 的镜像
├── (与 .claude/skills/starry-* 相同)     ← 供其他 agent 框架使用
└── ...

AGENTS.md                                 ← 追加了 StarryOS Evolution Skills 段落
```

---

## 十一、使用方法

### 手动模式

逐个调用技能，适合调试或处理特定问题：

```
> /starry-analyze          # 先看看内核里有什么问题
> /starry-contract readlinkat  # 看看 readlinkat 和 Linux 的差异
> /starry-fix readlinkat       # 修复它
> /starry-test readlinkat      # 测试修复
> /starry-verify               # 确认没有回归
> /starry-report               # 看看总体进度
```

### 自动模式

让 AI 自主循环：

```
> /loop use starry-iterate to improve the StarryOS kernel
```

这会自动重复以下循环：选择目标 → 分析 → 修复 → 测试 → 验证 → 记录 → 选择下一个目标...

---

## 十二、与其他框架的对比

### 与 starryos-codex-pipeline（参考1）的对比

| 方面 | codex-pipeline | starry-evolve |
|------|---------------|---------------|
| AI 工具 | OpenAI Codex CLI | Claude Code |
| 编排方式 | Python 脚本 (`agent_loop.py`) | Claude Code 原生 skill + `/loop` |
| 角色分离 | Developer/Reviewer/Committer 作为独立进程 | Skill/Agent 作为 Claude Code 内部组件 |
| 输出验证 | JSON Schema 校验 | 确定性 Python 工具 + clippy/fmt |
| 安全措施 | Committer 是非 AI 的 Python 代码 | Stop hook + 权限白名单 |
| 状态管理 | `loop_state.json` + `journal.md` | `syscall_status.yaml` + `journal.md` |
| 与项目集成 | 独立运行 | 深度集成 `cargo xtask` |

**核心区别**：codex-pipeline 用 Python 编排器驱动独立的 Codex 进程，我们用 Claude Code 原生的 skill 系统直接在编辑器内工作，无需额外进程管理。

### 与 starry-harness（参考2）的对比

| 方面 | starry-harness | starry-evolve |
|------|---------------|---------------|
| 安装方式 | Claude Code 插件（plugin.json + marketplace.json） | 直接放在 `.claude/skills/` 中 |
| 技能数量 | 9 个 | 7 个（更聚焦） |
| Agent 数量 | 3 个 | 2 个 |
| 分析工具 | 5 个 Python 脚本（abi-check, lock-order, pattern-scanner, kernel-graph, change-tracker） | 5 个 Python 脚本（syscall_audit, stub_scanner, build_checker, test_runner, regression_diff） |
| 测试框架 | 自定义 pipeline.sh + stress-test.sh | 集成 `cargo xtask starry test qemu` |
| 评估体系 | 7 级证据等级 + 自适应审查管道 | ANALYZE→CONTRACT→FIX→TEST→VERIFY 五阶段 |
| 策略系统 | `strategy.json` 维护覆盖率和效果指标 | `syscall_status.yaml` 简化状态跟踪 |

**核心区别**：starry-harness 是一个完整的插件包，功能全面但复杂；我们更聚焦在 syscall 改进这一核心场景，工具更轻量，直接利用项目已有的 `cargo xtask` 基础设施。
