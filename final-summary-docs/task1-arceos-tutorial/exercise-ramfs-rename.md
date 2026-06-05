# 实验四：exercise-ramfs-rename — 实现 ramfs 的文件重命名

## 一、实验目标

本实验的目标是为 ArceOS 的内存文件系统（ramfs）实现文件重命名（rename）操作。具体需要修改两个组件：在 `axfs` 的 `RootDirectory` 中实现 rename 请求的转发逻辑，在 `axfs_ramfs` 的 `DirNode` 中实现底层 rename 操作。最终使应用可以通过 `std::fs::rename` 完成同目录下的文件重命名。

## 二、原理说明

### 2.1 ArceOS 的文件系统架构

ArceOS 的文件系统采用 VFS（Virtual File System）抽象层设计，分层结构如下：

```
应用层:  std::fs::rename
         ↓
VFS 层:  axfs::RootDirectory → 查找 mount point → 转发到底层 fs
         ↓
具体 FS: axfs_ramfs::DirNode → 操作 BTreeMap 中的子节点
```

`RootDirectory` 作为 VFS 的根节点，负责管理主文件系统和各个挂载点。当收到操作请求时，它需要判断路径属于哪个文件系统，然后将请求转发到对应的底层实现。

### 2.2 rename 的语义

Linux 的 `rename` 系统调用要求：
- 源路径和目标路径位于同一个文件系统（跨文件系统返回 `EXDEV`）。
- 目标路径已存在时，原子性地替换目标。

本实验仅要求实现同目录内的重命名（不涉及跨目录移动），简化了实现复杂度。

### 2.3 ramfs 的目录结构

ramfs 使用 `BTreeMap<String, VfsNodeRef>` 维护目录中的子节点。重命名操作的本质就是从 BTreeMap 中移除旧名称的条目，再以新名称插入同一个节点。

## 三、代码实现思路

1. 在 `exercise-ramfs-rename/Cargo.toml` 中通过 `[patch.crates-io]` 将 `axfs` 和 `axfs_ramfs` 指向本地修改版本。
2. 在 `axfs/src/root.rs` 的 `RootDirectory` 中实现 `VfsNodeOps::rename` 方法，处理 mount point 路由和跨设备检测。
3. 在 `axfs_ramfs/src/dir.rs` 的 `DirNode` 中实现 `VfsNodeOps::rename` 方法和辅助方法 `rename_node`，完成 BTreeMap 中的节点移除和重新插入。
4. 编写应用测试代码，验证创建文件、重命名、读取内容的完整流程。

## 四、关键代码分析

### 4.1 RootDirectory 的 rename 转发逻辑

`axfs/src/root.rs` 中 `RootDirectory` 的 `rename` 实现：

```rust
fn rename(&self, src_path: &str, dst_path: &str) -> VfsResult {
    let src_path = self.normalize_path(src_path);
    let dst_path = self.normalize_path(dst_path);
    match (
        self.find_best_mount(src_path),
        self.find_best_mount(dst_path),
    ) {
        (Some((src_fs, src_rest)), Some((dst_fs, dst_rest)))
            if Arc::ptr_eq(&src_fs, &dst_fs) =>
        {
            src_fs.root_dir().rename(src_rest, dst_rest)
        }
        (None, None) => self.main_fs.root_dir().rename(src_path, dst_path),
        _ => Err(axfs_vfs::VfsError::CrossesDevices),
    }
}
```

这段代码的处理逻辑：

1. **路径规范化**：调用 `normalize_path` 去除前导 `/` 和 `./` 前缀。
2. **查找 mount point**：使用 `find_best_mount` 分别查找源路径和目标路径所属的挂载文件系统。
3. **三种情况**：
   - 源和目标都在同一个挂载文件系统中（通过 `Arc::ptr_eq` 判断指针是否相同），则转发到该文件系统的 `root_dir().rename`。
   - 源和目标都不在任何挂载点中（即都在主文件系统中），则直接调用主文件系统的 rename。
   - 其他情况（跨文件系统）返回 `CrossesDevices` 错误。

`find_best_mount` 方法通过遍历所有挂载点，找到与给定路径前缀匹配的最长挂载路径（最长前缀匹配），确保嵌套挂载点能被正确处理。

### 4.2 DirNode 的 rename 实现

`axfs_ramfs/src/dir.rs` 中 `DirNode` 的 `rename` 和 `rename_node`：

```rust
fn rename(&self, src_path: &str, dst_path: &str) -> VfsResult {
    let (src_parent, src_name) = split_parent(src_path);
    let (dst_parent, dst_name) = split_parent(dst_path);
    if src_parent != dst_parent {
        return Err(VfsError::Unsupported);
    }
    if src_parent.is_empty() {
        return self.rename_node(src_name, dst_name);
    }
    let parent = self.this.upgrade().ok_or(VfsError::NotFound)?
        .lookup(src_parent)?;
    let parent = parent.as_any().downcast_ref::<DirNode>()
        .ok_or(VfsError::NotADirectory)?;
    parent.rename_node(src_name, dst_name)
}
```

```rust
fn rename_node(&self, src_name: &str, dst_name: &str) -> VfsResult {
    if src_name.is_empty() || dst_name.is_empty()
        || src_name == "." || src_name == ".."
        || dst_name == "." || dst_name == ".."
    {
        return Err(VfsError::InvalidInput);
    }
    let mut children = self.children.write();
    if !children.contains_key(src_name) {
        return Err(VfsError::NotFound);
    }
    if children.contains_key(dst_name) {
        return Err(VfsError::AlreadyExists);
    }
    let node = children.remove(src_name).ok_or(VfsError::NotFound)?;
    children.insert(dst_name.into(), node);
    Ok(())
}
```

实现细节：

1. `rename` 方法先用 `split_parent` 分离出父路径和文件名，检查源和目标的父路径是否相同（即是否在同一目录）。
2. 如果父路径为空，说明是当前目录的直接子节点，直接调用 `rename_node`。
3. 如果父路径非空，先 lookup 找到父目录节点，再在父目录上调用 `rename_node`。
4. `rename_node` 进行参数校验后，获取 children 的写锁，从 BTreeMap 中 `remove` 旧名称的条目，再用新名称 `insert` 回去。节点本身（`VfsNodeRef`）不变，只是改变了它在 BTreeMap 中的键。

### 4.3 应用层测试代码

`exercise-ramfs-rename/src/main.rs` 的测试流程：

```rust
fn process() -> io::Result<()> {
    create_dir("/tmp")?;
    create_file("/tmp/f1", "hello")?;
    print_file("/tmp/f1")?;
    rename_file("/tmp/f1", "/tmp/f2")?;
    print_file("/tmp/f2")
}
```

1. 创建 `/tmp` 目录。
2. 在其中创建文件 `f1`，写入内容 "hello"。
3. 读取 `f1` 验证内容。
4. 将 `f1` 重命名为 `f2`。
5. 读取 `f2` 验证重命名后内容不变。

### 4.4 Cargo.toml 的 patch 配置

```toml
[patch.crates-io]
axfs = { path = "axfs" }
axfs_ramfs = { path = "axfs_ramfs" }
```

同时 patch 两个 crate：`axfs`（VFS 层）和 `axfs_ramfs`（具体文件系统实现），确保 rename 请求能从 VFS 层正确传递到 ramfs 底层。

## 五、遇到的问题与解决方法

### 5.1 VFS 层与具体 FS 层的分工

最初对 rename 应该在哪一层实现感到困惑。经过阅读代码，理解了 `RootDirectory`（VFS 层）负责 mount point 路由和跨设备检测，而 `DirNode`（具体 FS 层）负责实际的节点操作。两层的分工使得文件系统的挂载和重命名可以独立演进。

### 5.2 BTreeMap 的操作顺序

在 `rename_node` 中，必须先 `remove` 再 `insert`。如果先 `insert` 再 `remove`，由于旧名称仍然存在，会导致节点丢失。同时需要注意目标名称已存在的情况——本实验返回 `AlreadyExists` 错误，而不是像 Linux 那样自动替换。但在上层 `rename` 函数中，如果目标已存在会先调用 `remove_file` 删除目标文件，再执行 rename。

### 5.3 同目录限制的处理

`DirNode::rename` 方法通过比较 `src_parent` 和 `dst_parent` 来限制只在同一目录内操作。如果尝试跨目录移动，会返回 `VfsError::Unsupported`。这符合本实验的要求——只实现 rename，不要求跨目录 move。

## 六、测试方法与结果

### 6.1 功能测试

```bash
cd exercise-ramfs-rename
cargo xtask run
```

期望输出包含：

```
Create directory '/tmp' ...
Create '/tmp/f1' and write [hello] ...
Read '/tmp/f1' content: [hello] ok!
Rename '/tmp/f1' to '/tmp/f2' ...
Read '/tmp/f2' content: [hello] ok!

[Ramfs-Rename]: ok!
```

### 6.2 多架构 Docker 测试

| 架构        | 测试结果 |
|-------------|----------|
| riscv64     | 通过     |
| x86_64      | 通过     |
| aarch64     | 通过     |
| loongarch64 | 通过     |

## 七、实验总结

本实验在 ArceOS 的 VFS 框架中实现了文件重命名功能，主要收获包括：

1. **理解了 VFS 分层架构的设计思想**：VFS 层（`RootDirectory`）负责路由和策略，具体文件系统层（`DirNode`）负责实现。这种分层使得添加新文件系统时只需实现 VfsNodeOps trait，无需修改上层代码。
2. **掌握了 Cargo 多 crate patch 的使用**：同时 patch `axfs` 和 `axfs_ramfs` 两个 crate，理解了它们之间的依赖关系。
3. **学习了 ramfs 的内部实现**：通过 `BTreeMap` 管理目录项，使用 `RwLock` 保证并发安全，使用 `Arc` 和 `Weak` 处理父子目录的引用关系。
4. **加深了对文件系统语义的理解**：rename 的跨设备检测、目标文件存在时的处理等细节，体现了 POSIX 语义在实现中的考量。
