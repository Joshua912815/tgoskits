---
name: starry-analyze
description: 分析 StarryOS 内核的 syscall 覆盖率和实现状态，发现未实现的 syscall、stub 函数和代码质量问题。当用户提到 "analyze starry"、"syscall audit"、"find kernel issues"、"内核分析"、"发现内核问题" 时使用此技能。
---

# StarryOS Kernel Analysis

分析 StarryOS 内核，发现改进机会。

## 工作流程

1. 运行确定性分析工具：
   ```
   python3 scripts/starry-evolve/evolve.py audit --format markdown
   ```
   这会解析 `os/StarryOS/kernel/src/syscall/mod.rs` 中的 dispatch 表，分类每个 syscall 的实现状态，并输出 handler 文件、行号、证据和置信度。

2. 运行 stub 扫描工具：
   ```
   python3 scripts/starry-evolve/evolve.py select
   ```
   这会基于确定性审计结果选择下一候选目标。不要绕过统一入口直接进入修复。

3. 综合两个工具的输出，生成改进目标列表，按子系统分组：
   - fs (文件系统)
   - task (进程/线程管理)
   - mm (内存管理)
   - net (网络/socket)
   - signal (信号处理)
   - ipc (进程间通信)
   - sync (同步原语)
   - io_mpx (I/O 多路复用)
   - time (时间)

4. 根据以下标准优先排序目标：
   - 影响范围广的 syscall（被 busybox 等应用使用）
   - 安全相关的 stub（如 `todo!()` 会导致 panic）
   - 容易验证的改进（有明确的 Linux 行为作为对照）

5. 状态更新必须由 `evolve.py record --report <report>` 从 verifier report 派生；分析阶段不要手写 VERIFIED/PASS。

## 重要约束

- 不要猜测 syscall 的实现状态，只依赖工具的确定性输出。
- 优先关注 `os/StarryOS/kernel/src/syscall/` 目录下的代码。
- 输出的目标列表应该具体到文件和函数名。
