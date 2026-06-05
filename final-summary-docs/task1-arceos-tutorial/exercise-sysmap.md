# 实验五：exercise-sysmap — 实现 SYS_MMAP 系统调用

## 一、实验目标

本实验的目标是在 ArceOS 的 syscall 模拟层中实现 `SYS_MMAP` 系统调用，使得用户态程序可以通过 `mmap` 将文件内容映射到用户地址空间，并成功读回映射的内容。具体需要修改 `exercise-sysmap/src/syscall.rs`，实现完整的 mmap 参数校验、地址空间分配和文件数据写入逻辑。

## 二、原理说明

### 2.1 mmap 系统调用

`mmap` 是 Linux 中将文件或设备映射到进程地址空间的系统调用，其函数签名为：

```c
void *mmap(void *addr, size_t length, int prot, int flags, int fd, off_t offset);
```

关键参数：
- `addr`：建议的映射起始地址（hint）。
- `length`：映射长度。
- `prot`：内存保护标志（`PROT_READ`、`PROT_WRITE`、`PROT_EXEC`）。
- `flags`：映射类型标志（`MAP_PRIVATE`、`MAP_SHARED`、`MAP_FIXED`、`MAP_ANONYMOUS`）。
- `fd`：文件描述符（`MAP_ANONYMOUS` 时忽略）。
- `offset`：文件偏移量（必须是页大小的整数倍）。

### 2.2 ArceOS 的 syscall 模拟

ArceOS 在内核态运行用户程序时，通过 syscall 模拟层拦截用户态的 Linux 系统调用。`handle_syscall` 函数根据系统调用号分发到对应的处理函数，处理完成后将返回值写入用户上下文。

本实验中，用户程序 `mapfile` 由 musl libc 编译，运行时通过 syscall 请求 mmap 服务。

### 2.3 用户地址空间管理

ArceOS 使用 `axmm` 模块管理用户地址空间。`AddrSpace` 提供了以下关键方法：
- `map_alloc`：在指定地址分配新的映射。
- `find_free_area`：在给定范围内寻找空闲区域。
- `write`：向用户地址空间写入数据。
- `unmap`：取消映射。

## 三、代码实现思路

1. 在 `syscall.rs` 中定义 `MmapProt` 和 `MmapFlags` bitflags，用于解析 mmap 参数。
2. 实现 `MappingFlags` 的 `From<MmapProt>` 转换，将 mmap 保护标志映射到 ArceOS 的页表权限。
3. 实现 `sys_mmap` 函数：参数校验 → 寻址/分配虚拟地址 → 建立映射 → 读取文件内容 → 写入用户空间。
4. 在 `handle_syscall` 中添加 `SYS_MMAP` 的分发逻辑。
5. 管理 `NEXT_MMAP_BASE` 全局变量，跟踪 mmap 分配位置。

## 四、关键代码分析

### 4.1 参数定义与转换

```rust
bitflags::bitflags! {
    struct MmapProt: i32 {
        const PROT_READ  = 1 << 0;
        const PROT_WRITE = 1 << 1;
        const PROT_EXEC  = 1 << 2;
    }
}

bitflags::bitflags! {
    struct MmapFlags: i32 {
        const MAP_SHARED    = 1 << 0;
        const MAP_PRIVATE   = 1 << 1;
        const MAP_FIXED     = 1 << 4;
        const MAP_ANONYMOUS = 1 << 5;
        const MAP_NORESERVE = 1 << 14;
        const MAP_STACK     = 0x20000;
    }
}
```

使用 `bitflags` 宏定义 mmap 的保护和标志位，方便进行位操作和组合判断。

权限转换实现：

```rust
impl From<MmapProt> for MappingFlags {
    fn from(value: MmapProt) -> Self {
        let mut flags = MappingFlags::USER;
        if value.contains(MmapProt::PROT_READ) {
            flags |= MappingFlags::READ;
        }
        if value.contains(MmapProt::PROT_WRITE) {
            flags |= MappingFlags::WRITE;
        }
        if value.contains(MmapProt::PROT_EXEC) {
            flags |= MappingFlags::EXECUTE;
        }
        flags
    }
}
```

所有用户态映射默认添加 `USER` 标志，确保页表项设置了用户态访问权限。

### 4.2 sys_mmap 核心实现

```rust
fn sys_mmap(
    addr: *mut c_void, length: usize, prot: i32,
    flags: i32, fd: i32, offset: isize,
) -> isize {
    // 1. 参数校验
    if length == 0 || offset < 0 || offset as usize % PAGE_SIZE_4K != 0 {
        return neg_errno(LinuxError::EINVAL);
    }
    let prot = MmapProt::from_bits_truncate(prot);
    let flags = MmapFlags::from_bits_truncate(flags);
    if !flags.intersects(MmapFlags::MAP_PRIVATE | MmapFlags::MAP_SHARED) {
        return neg_errno(LinuxError::EINVAL);
    }

    // 2. 对齐计算
    let map_size = match align_up(length, PAGE_SIZE_4K) {
        Some(size) => size,
        None => return neg_errno(LinuxError::ENOMEM),
    };

    // 3. 获取用户地址空间
    let aspace = match crate::USER_ASPACE.lock().as_ref().cloned() {
        Some(aspace) => aspace,
        None => return neg_errno(LinuxError::ENOMEM),
    };
    let mut aspace = aspace.lock();

    // 4. 确定映射起始地址
    let start = if flags.contains(MmapFlags::MAP_FIXED) {
        let start = addr as usize;
        if start == 0 || start % PAGE_SIZE_4K != 0 {
            return neg_errno(LinuxError::EINVAL);
        }
        VirtAddr::from(start)
    } else {
        let hint = if addr.is_null() {
            NEXT_MMAP_BASE.load(Ordering::Relaxed)
        } else {
            match align_up(addr as usize, PAGE_SIZE_4K) {
                Some(hint) => hint,
                None => return neg_errno(LinuxError::ENOMEM),
            }
        };
        let limit = VirtAddrRange::from_start_size(aspace.base(), aspace.size());
        match aspace.find_free_area(VirtAddr::from(hint), map_size, limit) {
            Some(start) => start,
            None => return neg_errno(LinuxError::ENOMEM),
        }
    };

    // 5. 建立映射
    if let Err(e) = aspace.map_alloc(start, map_size, map_flags, true) {
        return neg_errno(LinuxError::from(e));
    }

    // 6. 文件映射：读取内容并写入用户空间
    if !flags.contains(MmapFlags::MAP_ANONYMOUS) {
        let mut data = Vec::new();
        data.resize(length, 0);
        let read_res = with_file_fd(fd, |file| {
            let mut done = 0;
            while done < data.len() {
                let n = file.read_at(offset as u64 + done as u64, &mut data[done..])
                    .map_err(LinuxError::from)?;
                if n == 0 { break; }
                done += n;
            }
            Ok(())
        });
        if let Err(e) = read_res {
            let _ = aspace.unmap(start, map_size);
            return neg_errno(e);
        }
        if let Err(e) = aspace.write(start, &data) {
            let _ = aspace.unmap(start, map_size);
            return neg_errno(LinuxError::from(e));
        }
    }

    // 7. 更新 mmap 基址并返回
    NEXT_MMAP_BASE.store((start + map_size).as_usize(), Ordering::Relaxed);
    start.as_usize() as isize
}
```

### 4.3 实现流程分析

`sys_mmap` 的完整流程分为七个步骤：

1. **参数校验**：检查 length 不为零、offset 非负且页对齐、flags 包含 MAP_PRIVATE 或 MAP_SHARED。
2. **长度对齐**：将映射长度向上取整到页大小的整数倍。
3. **获取地址空间**：从全局 `USER_ASPACE` 获取当前用户进程的地址空间。
4. **确定映射地址**：MAP_FIXED 模式直接使用指定地址；否则从 `NEXT_MMAP_BASE` 或 hint 开始，调用 `find_free_area` 寻找空闲区域。
5. **建立页映射**：调用 `aspace.map_alloc` 在页表中建立映射。
6. **文件数据读取**：非 MAP_ANONYMOUS 时，通过文件描述符读取文件内容，用 `aspace.write` 写入用户映射区域。读取失败时回滚映射。
7. **更新全局状态**：将 `NEXT_MMAP_BASE` 推进到映射结束位置，为下次分配做准备。

### 4.4 系统调用分发

在 `handle_syscall` 中添加了 `SYS_MMAP` 的处理：

```rust
SYS_MMAP => sys_mmap(
    args[0] as *mut c_void,
    args[1],
    args[2] as i32,
    args[3] as i32,
    args[4] as i32,
    args[5] as isize,
),
```

注意 mmap 使用 6 个参数（是 Linux 中参数最多的系统调用之一），所有参数通过 `UserContext` 的 `arg0` 到 `arg5` 获取。

## 五、遇到的问题与解决方法

### 5.1 loongarch64 交叉编译工具链问题

在 arm64 Docker 容器中测试 loongarch64 架构时，`scripts/test.sh` 失败。排查发现镜像中的 `loongarch64-linux-musl-gcc` 是 x86_64 ELF 格式的二进制文件，无法在 arm64 宿主上直接运行。

解决方案是在容器中安装 `libc6:amd64` 以支持运行 x86_64 二进制文件（arm64 Docker 支持 amd64 用户态模拟）。修复环境后，使用 `cargo xtask run --arch=loongarch64` 直接运行测试通过。

### 5.2 mmap 长度的页对齐

Linux mmap 要求映射长度自动向上取整到页大小的整数倍。初始实现中遗漏了这一步，导致短于页大小的映射请求分配了错误的内存量。通过添加 `align_up(length, PAGE_SIZE_4K)` 解决。

### 5.3 错误路径的资源清理

文件读取失败或用户空间写入失败时，已经建立的页映射需要被清理。通过在错误路径中调用 `aspace.unmap(start, map_size)` 确保资源不泄漏。使用 `let _ =` 忽略 unmap 的返回值，因为在错误路径上不需要再报告错误。

### 5.4 NEXT_MMAP_BASE 的并发安全

`NEXT_MMAP_BASE` 使用 `AtomicUsize` 和 `Relaxed` ordering。由于 ArceOS 当前是单核单任务环境，不存在真正的并发竞争，但使用原子变量保证了代码语义的正确性。

## 六、测试方法与结果

### 6.1 功能测试

```bash
cd exercise-sysmap
cargo xtask run
```

期望输出包含：

```
Read back content: hello, arceos!
MapFile ok!
```

### 6.2 多架构 Docker 测试

| 架构        | 测试方法                     | 测试结果 |
|-------------|------------------------------|----------|
| riscv64     | scripts/test.sh              | 通过     |
| x86_64      | scripts/test.sh              | 通过     |
| aarch64     | scripts/test.sh              | 通过     |
| loongarch64 | cargo xtask run --arch=loongarch64（修复容器环境后） | 通过     |

loongarch64 在 arm64 Docker 环境下需要额外安装 `libc6:amd64` 以运行 x86_64 格式的交叉编译工具链，修复后功能验证通过。

## 七、实验总结

本实验实现了 SYS_MMAP 系统调用，是五个基础实验中最复杂的一个，主要收获包括：

1. **深入理解了 mmap 的工作原理**：从参数校验到地址空间分配、从页表映射到文件数据读取，完整实现了 mmap 的核心路径。对虚拟内存管理有了更加具体的认识。
2. **理解了 ArceOS 的 syscall 模拟机制**：内核态拦截用户态系统调用、参数提取、返回值设置、错误码转换的完整流程。
3. **学习了用户地址空间管理**：`AddrSpace` 提供的 `find_free_area`、`map_alloc`、`write`、`unmap` 等方法构成了完整的虚拟内存操作 API。
4. **积累了跨架构调试经验**：loongarch64 工具链的架构兼容性问题让我认识到，在实际的操作系统开发中，构建环境和运行环境的架构差异会带来额外的复杂性。
5. **理解了错误处理和资源管理的重要性**：mmap 实现中的错误路径回滚、原子变量使用、溢出检查等细节，体现了系统编程对安全性和正确性的严格要求。
