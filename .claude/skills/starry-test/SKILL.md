---
name: starry-test
description: 为 StarryOS syscall 生成和运行用户态测试用例。支持 C 语言测试程序的创建、交叉编译和 QEMU 执行。当用户提到 "test syscall"、"write test"、"生成测试"、"测试 syscall" 时使用此技能。
---

# StarryOS Syscall Test

生成和运行 syscall 测试用例。

## 工作流程

1. **生成测试程序**：
   - 为目标 syscall 编写最小化的 C 测试程序
   - 测试应覆盖：正常路径、错误路径（无效参数）、边界情况
   - 测试程序使用 Linux 标准 API（unistd.h, fcntl.h, errno.h 等）
   - 放入 `scripts/starry-evolve/testcases/<syscall>_test.c`
   - 测试输出必须是 verifier JSONL：包含 `type=starry_evolve_case`、`run_id`、`case_id`、`ret`、`errno`、`observable`、`checksum`
   - `case_id` 必须来自 `scripts/starry-evolve/contracts/<syscall>.yaml`

2. **测试程序模板**：
   ```c
   #include <stdio.h>
   #include <errno.h>
   #include <string.h>

   int main() {
       int pass = 0, fail = 0;

       // Test case 1: normal operation
       // ...

       // Test case 2: error path (EINVAL)
       // ...

       printf("Results: %d passed, %d failed\n", pass, fail);
       return fail > 0 ? 1 : 0;
   }
   ```
   该模板只用于测试逻辑草稿；最终输出不能依赖这类人类可读 PASS 文本，必须改成 verifier JSONL。

3. **交叉编译**（需要工具链）：
   ```
   riscv64-linux-musl-gcc -static -o <syscall>_test <syscall>_test.c
   ```

4. **运行 Linux Docker vs StarryOS QEMU 对拍 verifier**：
   - 将编译好的二进制放入 StarryOS rootfs
   - syncfs/x86_64 的端到端 smoke test 可以直接运行：
     ```
     scripts/starry-evolve/run_syncfs_pair.sh x86_64
     ```
   - 通过统一入口运行：
     ```
     python3 scripts/starry-evolve/evolve.py test --syscall <syscall> --target riscv64 --linux-command '<linux/docker command>' --starry-command 'cargo xtask starry test qemu --target riscv64 --shell-init-cmd "/usr/bin/<test_binary>"'
     ```
   - verifier 会生成随机 `STARRY_EVOLVE_RUN_ID`，Linux 和 StarryOS 两端必须把同一个 run id 写入每条 JSONL 结果

5. **结果分析**：
   - 捕获串口输出，但只接受带 run_id 和 checksum 的结构化 JSONL
   - 直接输出 `PASSED`、伪造普通文本、缺少 checksum 的结果都必须判定失败
   - Linux 输出作为运行时 oracle，StarryOS 输出必须按 `contracts/<syscall>.yaml` 的 compare 字段对齐
   - 写入 `scripts/starry-evolve/reports/` 目录

6. **更新状态**：
   - 不要手写 PASS 或 VERIFIED
   - 使用 `python3 scripts/starry-evolve/evolve.py record --report scripts/starry-evolve/reports/latest.json` 从 verifier report 派生状态

## 重要约束

- 测试程序必须是静态链接的（使用 -static）
- 测试用例必须能在 Linux Docker 和 StarryOS QEMU 两边运行同一 case 集合
- 如果缺少交叉编译工具链，只生成 C 源码，提示用户手动编译
