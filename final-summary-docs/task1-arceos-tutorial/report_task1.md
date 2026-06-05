# Task1 总报告：ArceOS 基础实验完成总结

## 一、任务概述

### 1.1 任务目标

本阶段的任务是完成 tg-arceos-tutorial 仓库中的五个基础 exercise，覆盖 ArceOS 操作系统的多个核心模块。五个实验按照复杂度递增排列，分别涉及终端输出、标准库扩展、内存分配器、文件系统和系统调用模拟。

### 1.2 五个实验简介

| 编号 | 实验名称           | 核心模块         | 关键修改文件                                       |
|------|--------------------|------------------|----------------------------------------------------|
| 1    | exercise-printcolor | axstd (println)  | src/main.rs                                       |
| 2    | exercise-hashmap    | axstd (collections) | Cargo.toml + axstd/src/lib.rs                  |
| 3    | exercise-altalloc   | axalloc          | bump_allocator/src/lib.rs + axalloc/src/default_impl.rs |
| 4    | exercise-ramfs-rename | axfs + axfs_ramfs | Cargo.toml + axfs/src/root.rs + axfs_ramfs/src/dir.rs |
| 5    | exercise-sysmap     | syscall + axmm   | src/syscall.rs                                    |

## 二、总体技术路线

### 2.1 准备阶段

在开始实现之前，首先阅读了仓库根目录的 `codex.md` 和各 exercise 目录下的 `README.md`，了解每个实验的目标、要求和评分标准。同时搭建了基于 Docker 镜像 `starryos-dev:ubuntu-qemu10.2.1` 的开发环境，该镜像包含 Rust nightly 工具链、QEMU 10.2.1 和多架构的 musl cross compiler。

### 2.2 实现策略

对于每个 exercise，遵循统一的工作流程：

1. **定位待实现代码**：通过搜索 `TODO`、`unimplemented!` 和空白函数体，找到需要补充的代码位置。
2. **理解上下文**：阅读相关的 trait 定义、数据结构、已有实现和调用链，建立对模块内部工作机制的理解。
3. **本地 patch**：对于 `axstd`、`axfs`、`axfs_ramfs` 等 crates.io 上的 crate，使用 Cargo 的 `[patch.crates-io]` 机制将依赖指向本地修改副本，避免 fork 和发布流程。
4. **逐步实现**：从最简单的功能开始，先通过编译再通过功能测试。
5. **QEMU 验证**：使用 `cargo xtask run [--arch <ARCH>]` 在 QEMU 中运行，检查输出是否符合预期。

### 2.3 多架构验证

在所有 exercise 实现完成并通过单架构测试后，使用 Docker 容器进行四架构（riscv64、x86_64、aarch64、loongarch64）的批量测试。测试通过 `scripts/test.sh` 脚本自动化执行，该脚本会依次构建各架构的目标程序、启动 QEMU、检查输出中的关键标识字符串。

## 三、各实验完成情况

### 3.1 exercise-printcolor

**实现内容**：在 `println!` 输出中添加 ANSI SGR 转义序列 `\x1b[1;32m` 和 `\x1b[0m`，使 "Hello, Arceos!" 以高亮绿色显示。

**复杂度评估**：五个实验中最简单的一个，仅修改一行代码。主要价值在于熟悉 ArceOS 的构建运行流程。

**四架构测试**：全部通过。

### 3.2 exercise-hashmap

**实现内容**：通过 Cargo patch 机制引入本地修改的 `axstd`，在 `collections` 模块中导出 `hashbrown::{HashMap, HashSet}`，使应用可以使用 `std::collections::HashMap`。

**核心技术点**：
- Cargo `[patch.crates-io]` 的使用方法。
- `hashbrown` crate 的 `no_std` 兼容性。
- `alloc::collections` 和 `hashbrown` 的组合导出。

**四架构测试**：全部通过，50000 次 HashMap 操作验证了分配器稳定性。

### 3.3 exercise-altalloc

**实现内容**：实现双端 bump allocator（`EarlyAllocator`），字节分配从低地址向高地址增长，页分配从高地址向低地址增长。

**核心技术点**：
- `BaseAllocator`、`ByteAllocator`、`PageAllocator` 三个 trait 的实现。
- 内存对齐计算（`align_up`、`align_down`）。
- 字节分配的引用计数回收策略。
- `add_memory` 对非连续区域的容错处理。
- 通过 feature flag 在 `default_impl.rs` 中注册分配器。

**四架构测试**：全部通过。

### 3.4 exercise-ramfs-rename

**实现内容**：在 VFS 层（`RootDirectory`）实现 rename 的 mount point 路由和跨设备检测，在 ramfs 层（`DirNode`）实现 BTreeMap 中的节点重命名。

**核心技术点**：
- VFS 分层架构：`RootDirectory` 负责路由策略，底层 FS 负责具体实现。
- `find_best_mount` 的最长前缀匹配算法。
- `Arc::ptr_eq` 判断两个路径是否在同一文件系统。
- BTreeMap 的原子移除-重插入操作。
- 使用 `RwLock` 保证并发安全。

**四架构测试**：全部通过。

### 3.5 exercise-sysmap

**实现内容**：实现 `SYS_MMAP` 系统调用的完整处理流程，包括参数校验、地址空间分配、页表映射建立和文件数据读取。

**核心技术点**：
- mmap 参数的解析和校验（prot、flags、offset 对齐）。
- `AddrSpace` 的 `find_free_area`、`map_alloc`、`write`、`unmap` API 使用。
- `NEXT_MMAP_BASE` 原子变量的地址分配追踪。
- 文件映射和非匿名映射的数据写入流程。
- 错误路径的资源回滚机制。
- Linux errno 返回值约定（负数表示错误码）。

**四架构测试**：riscv64、x86_64、aarch64 通过 `scripts/test.sh`；loongarch64 在修复容器环境后通过 `cargo xtask run --arch=loongarch64`。

## 四、测试结论

### 4.1 测试环境

所有测试在 Docker 镜像 `starryos-dev:ubuntu-qemu10.2.1` 中进行，该镜像包含：
- Rust nightly 工具链
- QEMU 10.2.1（支持 riscv64、x86_64、aarch64、loongarch64）
- 多架构 musl cross compiler（riscv64、x86_64、aarch64、loongarch64 的 Linux musl 目标）

镜像默认运行环境为 `linux/arm64`。

### 4.2 测试结果汇总

| 实验              | riscv64 | x86_64 | aarch64 | loongarch64 |
|-------------------|---------|--------|---------|-------------|
| exercise-printcolor | 通过   | 通过   | 通过    | 通过        |
| exercise-hashmap    | 通过   | 通过   | 通过    | 通过        |
| exercise-altalloc   | 通过   | 通过   | 通过    | 通过        |
| exercise-ramfs-rename | 通过 | 通过   | 通过    | 通过        |
| exercise-sysmap     | 通过   | 通过   | 通过    | 通过*       |

\* loongarch64 的 sysmap 测试需要修复容器中的工具链兼容性问题（详见 4.3 节）。

### 4.3 loongarch64 工具链问题及解决

在 arm64 Docker 容器中测试 loongarch64 架构时发现，镜像中预装的 `loongarch64-linux-musl-gcc` 是 x86_64 ELF 格式的二进制文件，无法在 arm64 宿主机上直接执行。

排查过程：
1. 运行 `scripts/test.sh --arch loongarch64` 失败，报错找不到编译器。
2. 检查 `loongarch64-linux-musl-gcc` 的文件格式：`file $(which loongarch64-linux-musl-gcc)` 显示为 x86_64 ELF。
3. arm64 Linux 支持运行 x86_64 用户态程序，但需要安装 `libc6:amd64` 提供运行时库。
4. 安装后编译器可正常运行，`cargo xtask run --arch=loongarch64` 输出包含预期的 "Read back content: hello, arceos!" 和 "MapFile ok!"。

这个问题体现了交叉编译环境中的架构嵌套复杂性：在 arm64 主机上运行 x86_64 格式的编译器，生成 loongarch64 目标代码。

## 五、主要收获

### 5.1 对 ArceOS 模块化架构的理解

通过五个实验，逐步理解了 ArceOS 的模块化设计理念：

- **axstd**：作为 `no_std` 环境下的标准库替代品，通过条件编译和 feature gate 选择性地提供标准库接口子集。实验一和实验二分别涉及了它的 `println` 宏和 `collections` 模块。
- **axalloc**：内存分配器框架，通过 trait 层次（BaseAllocator → ByteAllocator / PageAllocator）定义了分配器接口，允许通过 feature flag 选择不同的分配算法。实验三实现了 bump allocator，注册为可选的默认分配器。
- **axfs / axfs_ramfs**：文件系统框架采用 VFS 抽象层设计，上层通过 `RootDirectory` 统一路径解析和 mount point 管理，底层各文件系统只需实现 `VfsNodeOps` trait。实验四在两层分别实现了 rename 功能。
- **axmm**：内存管理模块提供 `AddrSpace` 抽象，封装了页表操作和虚拟地址空间管理。实验五通过 mmap 系统调用的实现深入使用了其 API。
- **syscall emulation**：系统调用模拟层拦截用户态程序的 Linux 系统调用，在内核态处理后将结果返回给用户态。这种设计允许未经修改的 musl libc 程序在 ArceOS 上运行。

### 5.2 Cargo 工作流和 patch 机制

在多个实验中使用了 Cargo 的 `[patch.crates-io]` 机制来修改上游 crate。这种方式的优点是：
- 不需要 fork 整个仓库或发布新版本。
- 修改范围仅限于当前 exercise 目录，不影响其他实验。
- 可以精确控制修改的粒度。

同时也了解了 `extern crate axstd as std` 的技巧，使应用代码可以按标准库的风格编写，降低了学习成本。

### 5.3 系统编程实践

五个实验涵盖了系统编程的多个核心领域：
- **终端 I/O**：ANSI 转义序列在串口通信中的传递。
- **数据结构**：`no_std` 环境下引入第三方哈希表实现。
- **内存管理**：从最简单的 bump allocator 入手，理解分配器的核心概念。
- **文件系统**：VFS 分层设计、目录项管理、挂载点路由。
- **系统调用**：参数解析、地址空间操作、错误处理、资源回滚。

## 六、问题排查经验

### 6.1 编译错误的定位

ArceOS 涉及大量条件编译和 feature gate，编译错误有时难以直接定位。解决方法是仔细阅读错误信息中的 feature 条件链，理解当前启用了哪些 feature，然后针对性地查看相关代码。

### 6.2 运行时调试

ArceOS 在 QEMU 中运行时，可以通过 `ax_println!` 宏输出调试信息。在 syscall 模拟层中，`handle_syscall` 函数已经在入口处打印了系统调用号，方便跟踪用户程序的执行流程。

### 6.3 跨架构兼容性

不同架构的系统调用号不同（例如 SYS_MMAP 在 riscv64 上是 222，在 x86_64 上是 9），寄存器约定也不同。ArceOS 通过 `#[cfg(target_arch = "...")]` 条件编译处理这些差异。在实现新系统调用时，需要确保所有目标架构的系统调用号都已正确定义。

## 七、后续思考

### 7.1 可能的扩展方向

基于当前实验的基础，可以考虑以下扩展方向：
- 为 bump allocator 实现更精细的回收策略，减少内存浪费。
- 支持 ramfs 的跨目录 move 操作。
- 实现更多的 Linux 系统调用（如 `munmap`、`mprotect`）。
- 添加多进程支持，使 mmap 在进程间共享内存。

### 7.2 ArceOS 设计哲学的思考

ArceOS 的"组件化操作系统"设计理念在本系列实验中体现得非常清晰：每个功能模块通过 trait 定义接口、通过 feature flag 选择实现、通过 Cargo patch 允许定制。这种设计使得：
- 学习曲线平缓——每个实验只涉及一两个模块。
- 测试方便——可以在不同架构上快速验证。
- 扩展灵活——添加新功能只需实现对应的 trait。

但同时也能看到一些局限：Cargo patch 机制在多 exercise 共存时可能导致版本冲突；bump allocator 的简单模型在复杂场景下不够用；VFS 层的 mount point 管理在嵌套挂载时存在边界情况。

### 7.3 对操作系统课程学习的启发

通过实践而非单纯理论学习操作系统概念，获得了很多书本上难以传达的认识。例如，mmap 看似只是一个系统调用，但实现时需要同时处理参数校验、虚拟地址分配、页表映射、文件 I/O 和错误恢复，这涉及操作系统中虚拟内存管理、文件系统和系统调用三个核心子系统的协作。类似的，文件重命名看似简单，但在 VFS 分层架构中需要正确处理挂载点路由、跨设备检测和目录项操作的交互。这些实践经验加深了对操作系统整体架构的理解。
