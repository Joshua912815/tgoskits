---
name: starry-fix
description: 实现或修复 StarryOS 内核中的 syscall。根据契约文档和 Linux 行为实现缺失或错误的 syscall。当用户提到 "fix sys_X"、"implement syscall"、"修复内核"、"实现 syscall" 时使用此技能。
---

# StarryOS Kernel Fix

根据 Linux 行为契约实现或修复 StarryOS syscall。

## 前置条件

修复前必须完成：
- 目标 syscall 必须有 `scripts/starry-evolve/contracts/<syscall>.yaml`
- 必须先运行 `python3 scripts/starry-evolve/evolve.py contract --syscall <syscall>` 并通过校验
- 如果没有机器契约，先使用 `starry-contract` 技能生成；不要只根据 Markdown 或模型记忆修复

## 工作流程

1. **理解现有实现**：
   - 阅读 `os/StarryOS/kernel/src/syscall/` 下目标文件
   - 阅读同子系统中已正确实现的 syscall 作为参考（风格、错误处理模式）
   - 理解相关数据结构（`starry_process`、`starry_vm`、`starry_signal` 等）

2. **实现修复**：
   - 遵循现有代码风格和模式
   - 使用 `ax_errno::LinuxError` 进行错误处理
   - 使用 `starry_vm` 中的安全函数访问用户空间内存
   - 实现完整的错误路径，包括所有 Linux man page 中定义的 errno
   - 注意 `unsafe(no_mangle)` 而非 `#[no_mangle]`（按仓库风格）

3. **验证代码质量**：
   ```
   cargo xtask clippy --package starry-kernel
   cargo fmt
   ```
   - 不使用 `#[allow(...)]` 消除警告
   - 确保 clippy 无警告

4. **验证编译**：
   ```
   cargo xtask starry build --arch riscv64
   ```

5. **更新状态**：
   - 不要手写 VERIFIED/PASS
   - 只有 verifier report 可以通过 `python3 scripts/starry-evolve/evolve.py record --report <report>` 更新 VERIFIED 状态

## 编码规范

- 使用 `cargo xtask` 命令，不用原生 cargo（per AGENTS.md）
- 返回 `AxResult<isize>`，错误通过 `?` 传播
- 用户空间指针用 `starry_vm::check_and_get_*` 系列函数验证
- 文件操作通过 VFS 层，不要直接操作设备
- 进程操作通过 `starry_process::current()` 获取当前进程
