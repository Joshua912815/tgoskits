---
name: starry-report
description: 生成 StarryOS 内核改进的进度报告。汇总 journal 记录、syscall 状态和测试结果。当用户提到 "show progress"、"report status"、"进度报告"、"改进总结" 时使用此技能。
---

# StarryOS Progress Report

生成内核改进进度报告。

## 工作流程

1. **读取 journal**：
   - 读取 `scripts/starry-evolve/journal.md` 获取历史操作记录

2. **读取 syscall 状态**：
   - 读取 `scripts/starry-evolve/syscall_status.yaml` 获取每个 syscall 的当前状态
   - 统计各状态的数量

3. **读取测试报告**：
   - 读取 `scripts/starry-evolve/reports/` 下的测试结果
   - 读取 `scripts/starry-evolve/baseline.json` 获取基线数据

4. **生成格式化报告**，包含：
   - **总览**：已分析/已实现/已测试/已验证的 syscall 数量
   - **子系统覆盖**：每个子系统的改进进度
   - **近期活动**：最近 5 条 journal 记录
   - **待处理**：仍需改进的目标列表
   - **测试状态**：各架构的测试通过率

## 报告格式

使用 Markdown 表格和列表，简洁清晰。示例：

```
# StarryOS Evolution Progress

## Summary
- Total syscalls tracked: 42
- Implemented: 28 | Partial: 8 | Stub: 6
- Tested (riscv64): 35 pass, 7 fail

## Recent Activity
- 2026-05-09: Implemented sys_readlinkat (riscv64: PASS)
- 2026-05-09: Analyzed sys_pwritev2 (contract created)
```
