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

3. **交叉编译**（需要工具链）：
   ```
   riscv64-linux-musl-gcc -static -o <syscall>_test <syscall>_test.c
   ```

4. **注入 rootfs 并运行**：
   - 将编译好的二进制放入 StarryOS rootfs
   - 运行 QEMU 测试：
     ```
     cargo xtask starry qemu --arch riscv64
     ```
   - 或使用 StarryOS 测试套件框架：
     ```
     cargo xtask starry test qemu --target riscv64
     ```

5. **结果分析**：
   - 捕获串口输出
   - 分类结果：PASS / FAIL / CRASH / TIMEOUT
   - 写入 `scripts/starry-evolve/reports/` 目录

6. **更新状态**：
   - 更新 `scripts/starry-evolve/syscall_status.yaml` 中的 arch_status
   - 在 journal.md 中记录测试结果

## 重要约束

- 测试程序必须是静态链接的（使用 -static）
- 测试用例应首先在 Linux 上验证通过，确保测试本身没有 bug
- 如果缺少交叉编译工具链，只生成 C 源码，提示用户手动编译
