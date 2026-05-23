---
name: starry-verify
description: 对 StarryOS 内核变更进行全面的回归验证。跨所有支持架构构建和测试，与基线结果对比。当用户提到 "verify starry"、"run regression"、"回归测试"、"全面验证" 时使用此技能。
---

# StarryOS Regression Verification

全面验证内核变更，检测回归。

## 工作流程

1. **Clippy 检查**：
   ```
   cargo xtask clippy
   ```
   确保所有包通过 clippy 检查。

2. **Host std 测试**：
   ```
   cargo xtask test
   ```
   运行 `scripts/test/std_crates.csv` 中所有包的测试。

3. **多架构构建验证**：
   ```
   python3 scripts/starry-evolve/evolve.py build --repo-root . --format markdown
   ```
   验证所有支持架构（riscv64, aarch64, x86_64, loongarch64）能成功编译。

4. **QEMU verifier 测试**：
   对目标 syscall 和架构运行统一入口：
   ```
   python3 scripts/starry-evolve/evolve.py test --syscall <syscall> --target <arch> --linux-command '<linux/docker command>' --starry-command '<starry qemu command>'
   ```
   只接受 verifier report，不接受手写 PASS/PASSED 文本。

5. **ArceOS 回归**（可选，检查共享模块）：
   ```
   cargo xtask test arceos --target riscv64
   ```

6. **回归对比**：
   ```
   python3 scripts/starry-evolve/evolve.py verify --repo-root . --format markdown
   ```
   与 case-level `baseline.json` 对比，只有同一 syscall/arch/case 从通过变失败才算回归。

7. **更新基线**（如果全部通过）：
   ```
   python3 scripts/starry-evolve/evolve.py test --syscall <syscall> --target riscv64 --linux-command '<linux/docker command>' --starry-command '<starry qemu command>' --update-baseline
   ```

8. **生成报告**：
   - 汇总所有检查结果
   - 报告任何回归（pass → fail 的变化）
   - 报告任何改进（fail → pass 的变化）

## 回归处理

如果发现回归：
1. 不要提交变更
2. 分析回归原因
3. 修复回归或回滚变更
4. 重新运行验证
