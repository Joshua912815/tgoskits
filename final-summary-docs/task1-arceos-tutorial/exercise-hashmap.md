# 实验二：exercise-hashmap — 为 axstd 补充 HashMap 支持

## 一、实验目标

本实验的目标是为 ArceOS 的标准库 `axstd` 补充 `HashMap` 和 `HashSet` 的支持，使得上层应用可以通过 `std::collections::HashMap` 正常使用哈希表数据结构，并在 ArceOS 平台上完成包含 50000 次插入和遍历验证的功能测试。

## 二、原理说明

### 2.1 ArceOS 的 std 模拟层

ArceOS 并不使用 Rust 官方的 `std` crate，而是通过 `axstd` 提供一个与 `std` 接口兼容的子集。在应用代码中通过 `extern crate axstd as std` 的方式，使得 `std::collections::HashMap` 实际调用的是 `axstd::collections::HashMap`。

### 2.2 hashbrown 库

Rust 标准库中的 `HashMap` 底层使用 Google 的 SwissTable 实现，该实现以独立 crate `hashbrown` 的形式发布。由于 `axstd` 是 `no_std` 环境，不能直接依赖标准库中的 HashMap，但可以引入 `hashbrown` crate，它本身就支持 `no_std`。

### 2.3 Cargo 的 patch 机制

Cargo 的 `[patch.crates-io]` 段允许在工作空间中用本地路径替换 crates.io 上的 crate。这种机制非常适合在实验中修改上游 crate 而不需要 fork 整个项目。本实验需要修改 `axstd`，因此通过 patch 将 `axstd` 指向本地的修改版本。

## 三、代码实现思路

1. 在 `exercise-hashmap/` 目录下创建本地 `axstd` 副本。
2. 在本地 `axstd/Cargo.toml` 中添加 `hashbrown` 依赖。
3. 在 `axstd/src/lib.rs` 中新建 `collections` 模块，重新导出 `alloc::collections` 下的所有集合类型，并额外导出 `hashbrown::{HashMap, HashSet}`。
4. 在 `exercise-hashmap/Cargo.toml` 中通过 `[patch.crates-io]` 将 `axstd` 指向本地路径。
5. 应用代码 `src/main.rs` 中直接使用 `std::collections::HashMap` 进行功能测试。

## 四、关键代码分析

### 4.1 Cargo.toml 的 patch 配置

`exercise-hashmap/Cargo.toml` 中的关键修改：

```toml
[dependencies]
axstd = { version = "=0.3.0-preview.1", features = ["defplat", "alloc"], optional = true }

[patch.crates-io]
axstd = { path = "axstd" }
```

通过 `[patch.crates-io]` 将 `axstd` 替换为本地路径 `./axstd`，使得所有依赖 `axstd` 的代码都会使用本地修改版本。

### 4.2 collections 模块

在 `exercise-hashmap/axstd/src/lib.rs` 中添加的 `collections` 模块：

```rust
#[cfg(feature = "alloc")]
pub mod collections {
    pub use alloc::collections::*;
    pub use hashbrown::{HashMap, HashSet};
}
```

这段代码的作用：

- 使用 `#[cfg(feature = "alloc")]` 确保只有在启用动态内存分配时才编译此模块。
- `pub use alloc::collections::*` 重新导出 `alloc` 中的集合类型（如 `BTreeMap`、`VecDeque` 等），保持与标准库 `collections` 模块的兼容性。
- `pub use hashbrown::{HashMap, HashSet}` 额外导出 `hashbrown` 提供的 `HashMap` 和 `HashSet`，填补 `axstd` 中缺失的哈希表支持。

### 4.3 应用层测试代码

`exercise-hashmap/src/main.rs` 中的核心测试：

```rust
extern crate axstd as std;

use std::collections::HashMap;

fn test_hashmap() {
    const N: u32 = 50_000;
    let mut m = HashMap::new();
    for value in 0..N {
        let key = format!("key_{value}");
        m.insert(key, value);
    }
    for (k, v) in m.iter() {
        if let Some(k) = k.strip_prefix("key_") {
            assert_eq!(k.parse::<u32>().unwrap(), *v);
        }
    }
    println!("test_hashmap() OK!");
}
```

测试向 HashMap 中插入 50000 个键值对（key 为 `"key_0"` 到 `"key_49999"`，value 为对应的整数），然后遍历验证每个键值对的正确性。这个测试既检验了 HashMap 的基本功能，也隐含地验证了动态内存分配器在高频分配/释放场景下的稳定性。

## 五、遇到的问题与解决方法

### 5.1 axstd 版本匹配

`axstd` 在 crates.io 上的版本为 `0.3.0-preview.1`，本地 patch 版本必须与此一致，否则 Cargo 会报版本不匹配错误。解决方案是确保本地 `axstd/Cargo.toml` 中的 `version` 字段与上游保持一致。

### 5.2 hashbrown 的 no_std 兼容性

`hashbrown` 默认支持 `no_std`，不需要额外配置 feature。但需要确认 `axstd/Cargo.toml` 中 `hashbrown` 的依赖声明没有启用 `std` feature，否则会导致编译错误。在本实验中使用默认配置即可正常工作。

### 5.3 extern crate 声明

应用代码中使用了 `#[macro_use] extern crate axstd as std`，这是 `no_std` 环境下将 `axstd` 映射为 `std` 的标准做法。这样 `use std::collections::HashMap` 实际引用的是 `axstd::collections::HashMap`，即 `hashbrown::HashMap`。

## 六、测试方法与结果

### 6.1 本地测试

```bash
cd exercise-hashmap
cargo xtask run
```

期望输出包含：

```
test_hashmap() OK!
Memory tests run OK!
```

### 6.2 多架构 Docker 测试

使用 Docker 镜像 `starryos-dev:ubuntu-qemu10.2.1`，通过 `scripts/test.sh` 进行四架构测试：

| 架构        | 测试结果 |
|-------------|----------|
| riscv64     | 通过     |
| x86_64      | 通过     |
| aarch64     | 通过     |
| loongarch64 | 通过     |

50000 次 HashMap 插入和遍历验证在四个架构上均正常运行，说明内存分配器、格式化输出、集合操作等基础设施工作正常。

## 七、实验总结

本实验通过 Cargo 的 patch 机制为 `axstd` 补充了 `HashMap` 和 `HashSet` 支持，主要收获包括：

1. **深入理解了 Cargo patch 机制**：学会了如何通过 `[patch.crates-io]` 在不修改上游源码的情况下扩展 crate 功能，这在操作系统实验和嵌入式开发中非常实用。
2. **理解了 axstd 的模块组织**：`axstd` 作为 `no_std` 环境下的标准库替代品，通过条件编译和 feature gate 组织各功能模块，`collections` 模块只是其中一个例子。
3. **验证了 ArceOS 的内存分配能力**：50000 次 HashMap 插入测试间接验证了底层分配器在大量小块内存分配场景下的正确性和稳定性。
4. **了解了 Rust 生态系统中的 crate 关系**：`hashbrown` 作为标准库 HashMap 的底层实现，可以独立于 `std` 使用，体现了 Rust 生态的模块化设计。
