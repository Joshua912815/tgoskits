---
name: starry-iterate
description: 自主执行 StarryOS 内核改进的完整迭代循环。自动选择目标、分析、修复、测试、验证。与 /loop 配合使用可实现持续自主改进。当用户提到 "iterate on starry"、"autonomous improve"、"自动迭代"、"持续改进" 时使用此技能。
---

# StarryOS Autonomous Iteration

自主执行 ANALYZE → CONTRACT → FIX → TEST → VERIFY 改进循环。

## 工作方式

本技能执行一个完整的改进迭代。每一轮包括：

### Phase 1: 选择目标

1. 运行 `starry-analyze` 分析当前内核状态
2. 通过统一入口选择目标：
   ```
   python3 scripts/starry-evolve/evolve.py select
   ```
3. 优先级规则：
   - 安全相关的 stub（`todo!()` 等 panic 风险）
   - 被 busybox 等应用广泛使用的 syscall
   - 容易验证的改进
   - 尚未被分析过的 syscall

### Phase 2: 分析契约

1. 对选定目标运行 `starry-contract`
2. 确认 `scripts/starry-evolve/contracts/<syscall>.yaml` 通过：
   ```
   python3 scripts/starry-evolve/evolve.py contract --syscall <syscall>
   ```
3. 如果差异过于复杂，跳过此目标，选择下一个

### Phase 3: 实现修复

1. 运行 `starry-fix` 实现改进
2. 确保 clippy 和 fmt 通过

### Phase 4: 测试验证

1. 运行 `starry-test` 生成 verifier JSONL 测试
2. 通过 `python3 scripts/starry-evolve/evolve.py test --syscall <syscall> --linux-command '<linux/docker command>' --starry-command '<starry qemu command>'` 生成对拍 verifier report
3. 运行 `python3 scripts/starry-evolve/evolve.py verify --repo-root .` 做 case-level 回归检测

### Phase 5: 记录结果

- 如果全部通过：
  - 通过 `python3 scripts/starry-evolve/evolve.py record --report scripts/starry-evolve/reports/latest.json` 记录成功
  - VERIFIED 状态只能从 verifier report 派生
  - 提示用户可以提交变更
- 如果有失败：
  - 回滚代码变更
  - 记录失败原因到 journal
  - 将该目标标记为需要后续关注

## 使用 /loop 进行多轮迭代

配合 `/loop` 使用时，每轮自动选择新目标，持续改进：

```
/loop use starry-iterate to improve the StarryOS kernel
```

## 重要约束

- 每轮只修改一个 syscall 或一个子系统
- 不要在失败的修复上反复尝试超过 2 次
- 所有代码变更必须通过 clippy + fmt + 编译
- 不要提交未通过验证的变更
- 不要手写 PASS/PASSED、VERIFIED、journal 成功项；必须引用 verifier report 的 run_id
- 不要手写 Linux oracle；Linux Docker 输出就是运行时 oracle，StarryOS 必须与其对拍
- 严格遵循 AGENTS.md 中的所有规则
