# 实验三：exercise-altalloc — 实现 Bump 分配器

## 一、实验目标

本实验的目标是实现一个 bump-style 的 `EarlyAllocator`，同时支持 `BaseAllocator`、`ByteAllocator` 和 `PageAllocator` 三个 trait，用于 ArceOS 的早期内存管理。分配器需要正确处理字节分配和页分配的并发需求，并在功能测试中通过 bump allocator 专用的测试用例。

## 二、原理说明

### 2.1 Bump Allocator 原理

Bump allocator（也叫指针碰撞分配器）是最简单的内存分配策略之一。它维护一段连续的可用内存区间，分配时只需将指针向前移动（bump）相应的字节数，不需要搜索空闲链表或维护复杂的数据结构。

本实验采用双端 bump 设计，字节分配从低地址向高地址增长，页分配从高地址向低地址增长，中间区域为可用空间：

```
[ bytes-used | avail-area | pages-used ]
|            | -->    <-- |            |
start       b_pos        p_pos       end
```

这种设计的优势在于：
- 字节分配和页分配互不干扰，各自从一端增长。
- 分配操作只需移动指针，时间复杂度 O(1)。
- 结构简单，适合作为系统启动阶段的早期分配器。

### 2.2 ArceOS 的分配器 trait 层次

ArceOS 的内存分配框架定义了三层 trait：

- **`BaseAllocator`**：管理一个内存区间，提供 `init` 和 `add_memory` 方法。
- **`ByteAllocator`**：在 `BaseAllocator` 基础上提供任意字节大小的分配和释放。
- **`PageAllocator`**：以页为单位进行分配，适合大块连续内存的分配。

`EarlyAllocator` 需要同时实现这三层 trait。

### 2.3 ArceOS 的两级分配架构

ArceOS 支持单级（level-1）和两级（level-2）分配模式。在单级模式下，字节分配和页分配都由同一个 `ByteAllocator` 完成；在两级模式下，`PageAllocator` 管理物理页，`ByteAllocator` 从页面中分配字节。本实验实现的 bump allocator 在 `default_impl.rs` 中通过 feature flag `bump_allocator` 被选为 `DefaultByteAllocator`。

## 三、代码实现思路

1. 定义 `EarlyAllocator` 结构体，包含 `start`、`end`、`b_pos`、`p_pos`、`byte_allocs` 五个字段。
2. 实现 `BaseAllocator` trait：`init` 初始化内存区间，`add_memory` 处理追加内存区域。
3. 实现 `ByteAllocator` trait：`alloc` 从 `b_pos` 向高地址分配，`dealloc` 通过计数器跟踪分配数量，全部释放后重置 `b_pos`。
4. 实现 `PageAllocator` trait：`alloc_pages` 从 `p_pos` 向低地址分配，页分配不回收。
5. 编写辅助函数 `align_up`、`align_down`、`is_aligned` 处理对齐要求。
6. 在 `default_impl.rs` 中通过 feature flag 将 `EarlyAllocator` 注册为默认字节分配器。

## 四、关键代码分析

### 4.1 EarlyAllocator 结构体

```rust
pub struct EarlyAllocator<const PAGE_SIZE: usize> {
    start: usize,       // 管理区间起始地址
    end: usize,         // 管理区间结束地址
    b_pos: usize,       // 字节分配指针（向高地址增长）
    p_pos: usize,       // 页分配指针（向低地址增长）
    byte_allocs: usize, // 活跃字节分配计数
}
```

使用 const generic `PAGE_SIZE` 参数化页大小，使分配器可以适配不同的页大小配置。

### 4.2 字节分配与释放

```rust
fn alloc(&mut self, layout: Layout) -> AllocResult<NonNull<u8>> {
    let size = layout.size();
    let align = layout.align();
    if size == 0 || !align.is_power_of_two() {
        return Err(AllocError::InvalidParam);
    }
    let start = align_up(self.b_pos, align);
    let end = start.checked_add(size).ok_or(AllocError::NoMemory)?;
    if end > self.p_pos {
        return Err(AllocError::NoMemory);
    }
    self.b_pos = end;
    self.byte_allocs += 1;
    NonNull::new(start as *mut u8).ok_or(AllocError::NoMemory)
}
```

字节分配的关键步骤：
1. 校验参数合法性（大小不为零，对齐为 2 的幂）。
2. 将当前 `b_pos` 向上对齐到要求的对齐边界。
3. 检查分配后的结束位置是否超过了 `p_pos`（即是否与页分配区域冲突）。
4. 移动 `b_pos` 指针，增加分配计数，返回分配起始地址。

字节释放逻辑通过 `byte_allocs` 引用计数实现：

```rust
fn dealloc(&mut self, _pos: NonNull<u8>, layout: Layout) {
    if layout.size() == 0 { return; }
    self.byte_allocs = self.byte_allocs.saturating_sub(1);
    if self.byte_allocs == 0 {
        self.b_pos = self.start;
    }
}
```

当所有字节分配都被释放后（计数归零），将 `b_pos` 重置到 `start`，整体回收字节区域。这是 bump allocator 的简化回收策略——不支持部分回收，但保证了启动阶段分配的高效性。

### 4.3 页分配

```rust
fn alloc_pages(&mut self, num_pages: usize, align_pow2: usize) -> AllocResult<usize> {
    let size = num_pages.checked_mul(PAGE_SIZE).ok_or(AllocError::InvalidParam)?;
    let start = align_down(self.p_pos.checked_sub(size).ok_or(AllocError::NoMemory)?, align_pow2);
    if start < self.b_pos {
        return Err(AllocError::NoMemory);
    }
    self.p_pos = start;
    Ok(start)
}
```

页分配从高地址向低地址增长：
1. 计算所需的总字节数（页数 × 页大小）。
2. 从 `p_pos` 向下减去总大小，并对齐到要求的边界。
3. 检查是否与字节分配区域冲突。
4. 移动 `p_pos` 指针，返回分配的起始地址。

页分配不实现回收（`dealloc_pages` 为空操作），符合 bump allocator 的简单模型。

### 4.4 add_memory 的特殊处理

```rust
fn add_memory(&mut self, start: usize, size: usize) -> AllocResult {
    if size == 0 { return Ok(()); }
    if self.start == self.end {
        self.init(start, size);
        return Ok(());
    }
    if start == self.end && self.p_pos == self.end {
        self.end += size;
        self.p_pos += size;
        Ok(())
    } else {
        Ok(())
    }
}
```

对于 ArceOS 启动时追加的非连续 heap 区域，如果该区域恰好紧接在当前区间末尾且页分配尚未使用末尾空间，则扩展区间；否则静默返回 `Ok(())`，不合并到当前 bump 区间。这个处理方式避免了 `MemoryOverlap` 错误，同时不阻碍系统启动。

### 4.5 在 default_impl.rs 中注册

```rust
#[cfg(feature = "bump_allocator")]
pub type DefaultByteAllocator = bump_allocator::EarlyAllocator<PAGE_SIZE>;
```

通过条件编译，当启用 `bump_allocator` feature 时，`GlobalAllocator` 使用本实验实现的 `EarlyAllocator` 作为默认字节分配器。

## 五、遇到的问题与解决方法

### 5.1 内存区间扩展的冲突

ArceOS 启动过程中会多次调用 `add_memory` 追加内存区域。初始实现中对追加区域直接合并，导致在页分配已占用末尾空间时出现 `MemoryOverlap` 错误。解决方案是对非连续追加区域静默返回 `Ok(())`，保持当前 bump 区间不变。虽然这会浪费部分内存空间，但对于启动阶段的早期分配器来说，正确性比内存利用率更重要。

### 5.2 字节释放的部分回收问题

Bump allocator 天然不支持部分内存回收。如果只释放了部分分配，`b_pos` 无法回退到正确的位置。通过引入 `byte_allocs` 引用计数器，当计数归零时整体重置字节区域。这种策略在测试中工作良好，因为测试用例会在使用完毕后释放所有分配。

### 5.3 对齐计算的溢出检查

在字节分配和页分配中，地址计算可能导致溢出（特别是在 32 位地址空间中）。通过使用 `checked_add` 和 `checked_sub` 方法，在溢出时返回错误，避免了未定义行为。

## 六、测试方法与结果

### 6.1 功能测试

```bash
cd exercise-altalloc
cargo xtask run
```

期望输出包含：

```
Running bump tests...
Bump tests run OK!
```

测试脚本验证了 bump allocator 的字节分配、页分配、释放回收等基本功能。

### 6.2 多架构 Docker 测试

使用 Docker 镜像进行四架构测试：

| 架构        | 测试结果 |
|-------------|----------|
| riscv64     | 通过     |
| x86_64      | 通过     |
| aarch64     | 通过     |
| loongarch64 | 通过     |

## 七、实验总结

本实验实现了一个功能完整的双端 bump allocator，主要收获包括：

1. **深入理解了内存分配器的设计**：从 bump allocator 这个最简单的模型入手，理解了分配器需要面对的核心问题——内存分区、对齐、碎片管理和回收策略。
2. **掌握了 Rust trait 在 OS 开发中的应用**：通过实现 `BaseAllocator`、`ByteAllocator`、`PageAllocator` 三个 trait，理解了 trait 如何定义组件接口、条件编译如何选择不同实现。
3. **理解了 ArceOS 的两级分配架构**：`GlobalAllocator` 在内部组合字节分配器和页分配器，根据 `level-1`/`level-2` feature 选择不同的分配策略。
4. **学习了处理边界情况的工程方法**：`add_memory` 的特殊处理、溢出检查、对齐计算等细节，体现了系统编程中对正确性的严格要求。
