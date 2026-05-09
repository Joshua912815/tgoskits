---
name: starry-contract
description: 提取指定 syscall 的 Linux 行为契约，与 StarryOS 实现对比，发现语义差异。当用户提到 "check contract"、"compare syscall"、"syscall 契约"、"对比 Linux 行为" 时使用此技能。
---

# Syscall Contract Analysis

提取 Linux syscall 行为契约，与 StarryOS 实现对比。

## 工作流程

1. 定位 StarryOS 实现：
   - 在 `os/StarryOS/kernel/src/syscall/` 下搜索目标 syscall 的实现函数
   - 阅读完整的函数实现，注意错误处理路径和边界情况

2. 查看 `scripts/starry-evolve/contracts/` 目录下是否已有该 syscall 的契约文档。

3. 如果没有契约文档，通过以下方式提取 Linux 行为：
   - 搜索 Linux man page 了解参数语义、返回值、错误码
   - 关注：参数验证顺序、错误码优先级、边界值行为、信号中断处理

4. 生成结构化的契约对比文档，包含：
   - **参数处理**：参数类型、验证规则、转换逻辑
   - **返回值语义**：成功返回值、错误返回值
   - **错误码**：ENOSYS/EINVAL/ENOENT/ENOMEM 等的触发条件
   - **边界情况**：NULL 指针、零长度、溢出等
   - **实现状态**：COMPLETE / PARTIAL / STUB / SEMANTIC_MISMATCH / MISSING

5. 将契约文档写入 `scripts/starry-evolve/contracts/<syscall>.md`

6. 更新 `scripts/starry-evolve/syscall_status.yaml` 中该 syscall 的状态为 ANALYZED 或 CONTRACTED。

## 重要约束

- 契约文档必须基于实际的 Linux man page 和 Linux 内核源码，不要猜测。
- 对比时以 Linux 行为为标准，标注每个差异。
- 使用 StarryOS 中的错误类型 `ax_errno::LinuxError`。
