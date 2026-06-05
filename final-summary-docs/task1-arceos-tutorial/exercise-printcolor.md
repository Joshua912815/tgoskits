# 实验一：exercise-printcolor — 带颜色的终端输出

## 一、实验目标

本实验的目标是在 ArceOS 平台上实现带有 ANSI 颜色控制序列的终端输出。具体而言，需要修改 `exercise-printcolor/src/main.rs`，使程序在打印 "Hello, Arceos!" 时能够输出带有高亮绿色样式的文本，并最终在 QEMU 模拟器中通过终端正确显示。

这是五个基础实验中最简单的一个，主要用于熟悉 ArceOS 的构建与运行流程，理解 `axstd` 提供的 `println!` 宏的基本用法。

## 二、原理说明

### 2.1 ANSI SGR 控制序列

终端颜色控制基于 ANSI X3.64 标准中的 SGR（Select Graphic Rendition）转义序列。其基本格式为：

```
\x1b[<参数>m
```

其中 `\x1b` 是 ESC 字符（ASCII 0x1B），`[` 是 CSI（Control Sequence Introducer），`<参数>` 指定样式代码，`m` 是命令字母。常用代码包括：

| 代码 | 含义 |
|------|------|
| 0    | 重置所有样式 |
| 1    | 高亮（粗体） |
| 30   | 黑色前景 |
| 31   | 红色前景 |
| 32   | 绿色前景 |
| 33   | 黄色前景 |

多个参数可以用分号组合，例如 `\x1b[1;32m` 表示高亮绿色。

### 2.2 ArceOS 的 println 宏

在 ArceOS 中，`println!` 宏由 `axstd` 提供，其底层通过 `axlog` 组件将字符输出到平台相关的串口设备。由于串口传输的是原始字节流，ANSI 转义序列会直接传递到终端模拟器，由终端负责解释并渲染颜色。

## 三、代码实现思路

1. 阅读 `exercise-printcolor/src/main.rs` 中的初始代码，理解现有输出逻辑。
2. 在要变色的文本前面插入 ANSI SGR 开启序列 `\x1b[1;32m`，设置高亮绿色。
3. 在文本结束后插入 `\x1b[0m`，恢复终端默认样式，避免影响后续输出。
4. 使用 `cargo xtask run` 在 QEMU 中运行验证。

## 四、关键代码分析

修改后的 `exercise-printcolor/src/main.rs` 如下：

```rust
#![cfg_attr(feature = "axstd", no_std)]
#![cfg_attr(feature = "axstd", no_main)]

#[cfg(feature = "axstd")]
use axstd::println;

#[cfg_attr(feature = "axstd", unsafe(no_mangle))]
fn main() {
    println!("\x1b[1;32m[WithColor]: Hello, Arceos!\x1b[0m");
}
```

代码要点分析：

- **`#![cfg_attr(feature = "axstd", no_std)]`**：当启用 `axstd` feature 时使用 `no_std` 环境，因为 ArceOS 运行在裸机之上，不依赖标准库。
- **`#![cfg_attr(feature = "axstd", no_main)]`**：禁用标准入口函数，由 ArceOS 运行时调用 `main`。
- **`println!("\x1b[1;32m[WithColor]: Hello, Arceos!\x1b[0m")`**：核心修改行。`\x1b[1;32m` 开启高亮绿色，`\x1b[0m` 恢复默认样式。前缀 `[WithColor]:` 作为标识，便于测试脚本通过 grep 确认输出。

## 五、遇到的问题与解决方法

### 5.1 转义序列在 println 中的写法

最初不确定 ANSI 转义序列在 `no_std` 环境的 `println!` 宏中是否能正确传递。经过分析，`println!` 最终调用串口输出的字节写入函数，不会对内容做转义处理，因此 `\x1b` 会被正确传递为 ESC 字节。在 QEMU 中运行后确认终端正确渲染了绿色高亮文字。

### 5.2 构建系统熟悉

第一次使用 `cargo xtask run` 命令运行 ArceOS 应用，需要理解 xtask 的工作机制。xtask 是 Cargo 的自定义任务机制，本项目中 `xtask/src/main.rs` 负责调用 ArceOS 的构建系统，根据 `--arch` 参数选择目标架构，生成对应的 QEMU 启动命令。

## 六、测试方法与结果

### 6.1 单架构测试

使用以下命令构建并运行：

```bash
cd exercise-printcolor
cargo xtask run
```

QEMU 启动后，终端输出中包含：

```
[WithColor]: Hello, Arceos!
```

如果终端支持 ANSI 颜色，可以看到该行以高亮绿色显示。

### 6.2 多架构 Docker 测试

使用 Docker 镜像 `starryos-dev:ubuntu-qemu10.2.1`，通过 `scripts/test.sh` 分别对四个架构进行测试：

| 架构        | 测试结果 |
|-------------|----------|
| riscv64     | 通过     |
| x86_64      | 通过     |
| aarch64     | 通过     |
| loongarch64 | 通过     |

测试脚本通过检查输出中是否包含 "Hello, Arceos!" 来判定通过与否。

## 七、实验总结

本实验通过在 `println!` 中添加 ANSI SGR 转义序列，实现了带颜色的终端输出。虽然实现本身非常简单（仅修改一行代码），但通过这个实验，我完成了以下学习目标：

1. 了解了 ArceOS 应用的基本结构：`no_std` + `no_main` + `unsafe(no_mangle)` 的入口模式。
2. 熟悉了 `cargo xtask run` 的构建和运行流程。
3. 理解了串口输出与 ANSI 转义序列在裸机环境中的传递机制。
4. 掌握了多架构 Docker 测试的基本方法。

作为入门实验，它帮助我快速搭建起了 ArceOS 的开发与测试环境，为后续更复杂的实验打下了基础。
