# StarryOS inotifywait 支持技术文档

> PR #894 · `feat(starry-kernel): add inotifywait support`
> 分支：`codex/inotifywait-starry`

---

## 1 问题背景

### 1.1 `inotifywait` 依赖哪些 Linux 内核能力

Alpine Linux 的 `inotify-tools` 包提供 `inotifywait` 命令行工具，其工作流程为：

1. 调用 `inotify_init1(flags)` 获取一个 inotify 文件描述符；
2. 调用 `inotify_add_watch(fd, path, mask)` 注册一个或多个监控路径；
3. 对该 fd 执行 `poll`（等待可读）、`ioctl(FIONREAD)`（探测可读字节数）、`read`（读取 `inotify_event` 结构体序列）；
4. 使用完毕后调用 `inotify_rm_watch` 移除监控，最终 `close(fd)`。

其中 `inotify_event` 的结构（`<sys/inotify.h>`）为：

```c
struct inotify_event {
    int      wd;       /* watch descriptor */
    uint32_t mask;     /* 事件掩码 */
    uint32_t cookie;   /* rename 关联 cookie（本 PR 始终为 0） */
    uint32_t len;      /* name 字段的长度（含 padding） */
    char     name[];   /* 可选：被监控目录下的子文件名 */
};
```

### 1.2 StarryOS 原有的处理方式

在此 PR 之前，StarryOS 对 `inotify_init1` 仅返回一个 dummy fd，不实现任何语义。`inotify_add_watch` 和 `inotify_rm_watch` 则完全缺失。

这意味着：

- `inotifywait` 调用 `inotify_init1` 得到一个 fd，但后续对该 fd 的 `poll` 永远不返回可读、`read` 行为未定义；
- 即使 `inotify_add_watch` 能注册路径，内核侧也缺乏在文件系统操作发生时向 inotify fd 推送事件的机制。

### 1.3 为什么 dummy fd 不够

`inotifywait` 的工作模式是 **先注册 watch，然后在后台进程执行文件操作（写入、创建、删除等），同时前台阻塞等待 inotify fd 可读**。如果 inotify fd 的行为不符合预期（例如 `poll` 永远不报告 `POLLIN`，或 `read` 返回错误），`inotifywait` 将超时退出并报错。

因此，要让 `inotifywait` 正常工作，必须实现完整的 fd 行为闭环：

| 操作 | 要求 |
|------|------|
| `inotify_init1` | 创建 inotify 对象，支持 `IN_NONBLOCK` 和 `IN_CLOEXEC` |
| `inotify_add_watch` | 记录路径和事件掩码，返回 watch descriptor |
| `inotify_rm_watch` | 移除 watch，推送 `IN_IGNORED` 事件 |
| `poll` | 事件队列非空时报告 `POLLIN` |
| `ioctl(FIONREAD)` | 返回事件队列中待读字节数 |
| `read` | 将排队的 `inotify_event` 结构体拷贝到用户缓冲区 |
| `close` | 关闭 fd |

---

## 2 功能范围

### 2.1 已支持的 syscall

| Syscall | 说明 |
|---------|------|
| `inotify_init1` | 创建 inotify 实例，支持 `IN_NONBLOCK`、`IN_CLOEXEC` |
| `inotify_init`（x86_64 旧版） | 委托到 `inotify_init1(0)` |
| `inotify_add_watch` | 按绝对路径注册 watch，返回 wd |
| `inotify_rm_watch` | 移除 watch，推送 `IN_IGNORED` |

### 2.2 已支持的事件类型

| 事件 | 触发时机 |
|------|----------|
| `IN_MODIFY` | 文件写入成功（`write` 返回 >0 字节） |
| `IN_CREATE` | `open(O_CREAT)` 创建新文件、`mkdirat` 创建新目录 |
| `IN_CLOSE_WRITE` | 可写 fd 被 `close`（包括进程退出时的 `close_all_fds`） |
| `IN_DELETE` | `unlinkat` 删除文件/目录时，通知父目录 watch |
| `IN_DELETE_SELF` | `unlinkat` 删除文件/目录时，通知被删除路径自身的 watch |
| `IN_IGNORED` | `inotify_rm_watch` 移除 watch 后推送 |
| `IN_ISDIR` | 当事件目标为目录时，与 `IN_CREATE`/`IN_DELETE` 等组合使用 |

### 2.3 已支持的 fd 行为

- `read`：从事件队列中读取 `inotify_event` 结构体序列，支持阻塞（`poll_io`）和非阻塞（`IN_NONBLOCK` 时返回 `EAGAIN`）
- `poll`：队列非空时返回 `POLLIN`
- `ioctl(FIONREAD)`：返回队列中所有事件的字节总和
- `close`：关闭 fd（`Arc` 引用计数归零后自动回收）

### 2.4 已支持的 watch 语义

- **直接 watch**：监控特定文件/目录路径本身的事件
- **父目录 watch**：监控目录，事件携带 `name` 字段标识子文件名
- 路径解析使用绝对路径作为 key，通过 `resolve_at(AT_FDCWD, ...)` 获取
- 删除路径后自动移除该路径上的直接 watch

### 2.5 明确未支持的功能

以下功能不在本 PR 范围内：

- 事件类型：`IN_ACCESS`、`IN_ATTRIB`、`IN_OPEN`、`IN_CLOSE_NOWRITE`、`IN_MOVED_FROM`、`IN_MOVED_TO`、`IN_MOVE_SELF`
- rename cookie（`inotify_event.cookie` 始终为 0）
- 完整 inode 语义（当前基于路径匹配而非 inode 编号）
- hardlink 语义
- 控制标志：`IN_ONESHOT`、`IN_ONLYDIR`、`IN_DONT_FOLLOW`、`IN_MASK_ADD`、`IN_EXCL_UNLINK`
- 事件合并（相同 wd 的连续事件不做合并）
- `IN_Q_OVERFLOW`
- 资源限制（`/proc/sys/fs/inotify/max_*`）
- mount / filesystem 边界语义

---

## 3 代码结构

### 3.1 核心实现：`os/StarryOS/kernel/src/file/inotify.rs`

该文件是 inotify 的主体实现（约 315 行），包含以下关键部分：

#### 数据结构

```rust
// Watch 条目：一个绝对路径 + 事件掩码
struct Watch {
    path: String,
    mask: u32,
}

// inotify 实例的内部状态
struct InotifyState {
    next_wd: i32,                     // 下一个可分配的 watch descriptor
    watches: BTreeMap<i32, Watch>,    // wd → Watch 映射
    queue: VecDeque<Vec<u8>>,         // 已序列化的事件队列
}

// 对外暴露的 inotify 文件对象
pub struct Inotify {
    non_blocking: AtomicBool,
    state: Mutex<InotifyState>,
    poll_rx: PollSet,                  // 用于唤醒 poll 等待者
}
```

全局注册表：

```rust
static INOTIFY_INSTANCES: Mutex<Vec<Weak<Inotify>>> = ...;
```

所有活跃的 `Inotify` 实例以弱引用方式挂入此表。文件系统操作触发事件时，遍历此表通知所有实例。

#### Watch 管理

- `add_watch(path, mask)`：若路径已有 watch 则更新掩码并返回原 wd，否则分配新 wd 并插入
- `rm_watch(wd)`：移除 watch，向队列推送 `IN_IGNORED` 事件

#### 事件匹配与投递

核心匹配逻辑在 `notify_path` 方法中：

```
对于给定路径和两个掩码（exact_mask / parent_mask）：

1. 精确匹配：watch.path == 事件路径
   → 使用 exact_mask 投递事件，不携带 name 字段

2. 父目录匹配：watch.path == 路径的父目录
   → 使用 parent_mask 投递事件，携带 name 字段（子文件名）
```

事件掩码还会与 watch 注册的 mask 做按位与过滤，只有 watch 关注的事件类型才会投递。

#### 事件序列化

`push_event` 将一个 `inotify_event` 编码为字节序列并入队：

```
┌──────────┬──────────┬──────────┬──────────┬─────────────┐
│ wd (4B)  │ mask(4B) │ cookie=0 │ len (4B) │ name? (pad) │
└──────────┴──────────┴──────────┴──────────┴─────────────┘
```

- `name` 字段：原始文件名字节 + NUL 结尾 + 按 `size_of::<usize>()` 向上对齐的 padding
- `len` 字段：对齐后的 name 总长度（无 name 时为 0）
- 队列满时（超过 1024 个事件）丢弃最早的事件

#### `FileLike` trait 实现

| 方法 | 行为 |
|------|------|
| `read` | 阻塞等待队列非空，然后依次将完整事件拷贝到用户缓冲区 |
| `write` | 返回 `EBADF`（inotify fd 不可写） |
| `ioctl` | 仅处理 `FIONREAD`，返回队列中所有事件字节总和 |
| `nonblocking` / `set_nonblocking` | 读写 `IN_NONBLOCK` 标志 |
| `path` | 返回 `"anon_inode:[inotify]"` |

#### `Pollable` trait 实现

队列非空时返回 `IoEvents::IN`，通过 `PollSet` 支持异步唤醒。

#### 公共通知接口

四个顶层函数供文件系统各处调用：

```rust
pub fn notify_modify_path(path: &str)
    → exact_mask = IN_MODIFY, parent_mask = IN_MODIFY

pub fn notify_close_write_path(path: &str)
    → exact_mask = IN_CLOSE_WRITE, parent_mask = IN_CLOSE_WRITE

pub fn notify_create_path(path: &str, is_dir: bool)
    → exact_mask = 0, parent_mask = IN_CREATE [| IN_ISDIR]

pub fn notify_delete_path(path: &str, is_dir: bool)
    → 调用 notify_delete()：exact = IN_DELETE_SELF, parent = IN_DELETE
      然后移除被删除路径上的所有 watch
```

它们均通过 `notify_instances` 遍历全局 `INOTIFY_INSTANCES` 表，对每个存活的实例执行通知。

### 3.2 Syscall 层：`os/StarryOS/kernel/src/syscall/fs/inotify.rs`

| 函数 | 参数 | 逻辑 |
|------|------|------|
| `sys_inotify_init1(flags)` | flags: `IN_CLOEXEC` \| `IN_NONBLOCK` | 校验 flags → `Inotify::new()` → 设置 nonblocking → 插入 fd 表 |
| `sys_inotify_add_watch(fd, path, mask)` | fd + 路径指针 + 掩码 | 从用户空间读取路径字符串 → `resolve_at(AT_FDCWD, ...)` 解析为绝对路径 → downcast fd 为 `Inotify` → `add_watch` |
| `sys_inotify_rm_watch(fd, wd)` | fd + watch descriptor | downcast fd → `rm_watch` |

### 3.3 Syscall 分发：`os/StarryOS/kernel/src/syscall/mod.rs`

```rust
// x86_64 旧版入口，无 flags
#[cfg(target_arch = "x86_64")]
Sysno::inotify_init => sys_inotify_init1(0),

Sysno::inotify_init1 => sys_inotify_init1(uctx.arg0() as _),
Sysno::inotify_add_watch => sys_inotify_add_watch(uctx.arg0() as _, uctx.arg1() as _, uctx.arg2() as _),
Sysno::inotify_rm_watch => sys_inotify_rm_watch(uctx.arg0() as _, uctx.arg1() as _),
```

### 3.4 事件触发点

#### `IN_MODIFY` — 文件写入

**文件**：`os/StarryOS/kernel/src/file/fs.rs`

在 `File` 的 `write` 方法中，写入成功且字节数 >0 时触发：

```rust
if let Ok(bytes) = result && bytes > 0 {
    let path = path_for(inner.location()).into_owned();
    crate::file::inotify::notify_modify_path(&path);
}
```

#### `IN_CLOSE_WRITE` — 可写 fd 关闭

**文件**：`os/StarryOS/kernel/src/file/mod.rs`

辅助函数 `notify_close_write` 检查 fd 是否以写模式打开且底层对象为普通文件：

```rust
fn notify_close_write(fd: &FileDescriptor) {
    let access = fd.inner.open_flags() & O_ACCMODE;
    if (access == O_WRONLY || access == O_RDWR) && fd.inner.is::<File>() {
        let path = fd.inner.path();
        inotify::notify_close_write_path(path.as_ref());
    }
}
```

该函数在两处被调用：
- `release_locks_on_close`：单 fd 关闭路径（`close` syscall）
- `close_all_fds`：进程退出时批量关闭所有 fd

#### `IN_CREATE` — 创建新文件/目录

**文件（普通文件）**：`os/StarryOS/kernel/src/syscall/fs/fd_ops.rs`

`openat` 在执行前先探测文件是否存在，仅当 `O_CREAT` 置位且文件原不存在时才设置 `should_notify_create` 标志。`open` 成功后触发通知：

```rust
let should_notify_create = uflags & O_CREAT != 0
    && uflags & O_PATH == 0
    && with_fs(dirfd, |fs| match fs.resolve_no_follow(&path) {
        Ok(_) => Ok(false),           // 文件已存在，不是创建
        Err(AxError::NotFound) => Ok(true),  // 文件不存在，open 将创建
        Err(err) => Err(err),
    })?;
// ... 执行 open ...
if should_notify_create {
    crate::file::inotify::notify_create_path(file.path().as_ref(), false);
}
```

**文件（目录）**：`os/StarryOS/kernel/src/syscall/fs/ctl.rs`

`sys_mkdirat` 成功后触发，`is_dir = true` 表示附加 `IN_ISDIR`：

```rust
if result.is_ok() && let Ok((path, _)) = path_info_at(dirfd, &path) {
    crate::file::inotify::notify_create_path(&path, true);
}
```

#### `IN_DELETE` / `IN_DELETE_SELF` — 删除文件/目录

**文件**：`os/StarryOS/kernel/src/syscall/fs/ctl.rs`

`sys_unlinkat` 在删除前先通过 `path_info_at` 获取路径的绝对路径和 `is_dir` 信息（因为删除后就无法再查询元数据了），删除成功后触发：

```rust
let deleted = path_info_at(dirfd, &path).ok();  // 删除前快照
let result = with_fs(dirfd, |fs| {
    if flags & AT_REMOVEDIR as usize != 0 {
        fs.remove_dir(&path)?;
    } else {
        fs.remove_file(&path)?;
    }
    Ok(0)
});
if result.is_ok() && let Some((path, is_dir)) = deleted {
    crate::file::inotify::notify_delete_path(&path, is_dir);
}
```

---

## 4 关键实现逻辑

### 4.1 Watch 以解析后的绝对路径为 key

`sys_inotify_add_watch` 接收用户传入的路径字符串，通过 `resolve_at(AT_FDCWD, ...)` 解析为绝对路径后存入 `Watch`。这保证了对同一文件的多次 `add_watch`（如使用相对路径和绝对路径）能够正确去重并返回相同的 wd。

### 4.2 事件投递的双重匹配策略

```
                    ┌─────────────────────────────────────┐
                    │  文件系统操作（如 write / close）      │
                    │  产生事件通知 notify_*_path(path)     │
                    └──────────────┬──────────────────────┘
                                   │
                    ┌──────────────▼──────────────────────┐
                    │  notify_instances 遍历所有 Inotify   │
                    └──────────────┬──────────────────────┘
                                   │
               ┌───────────────────┴───────────────────┐
               │  对每个 Inotify 实例的 watch 表遍历     │
               └───────────────────┬───────────────────┘
                                   │
                ┌──────────────────┼──────────────────┐
                │                  │                   │
        ┌───────▼──────┐  ┌───────▼──────┐  ┌────────▼─────┐
        │ 精确路径匹配  │  │ 父目录匹配   │  │ 不匹配，跳过  │
        │ path == watch │  │ parent ==    │  │              │
        │              │  │ watch        │  │              │
        │ 不带 name    │  │ 带 name 字段 │  │              │
        └──────────────┘  └──────────────┘  └──────────────┘
```

以 `IN_MODIFY` 为例，假设用户操作 `/tmp/watchdir/file.txt`：

- 如果 watch 注册了 `/tmp/watchdir/file.txt`：精确匹配，事件 `wd=X, mask=IN_MODIFY, len=0`（无 name）
- 如果 watch 注册了 `/tmp/watchdir`：父目录匹配，事件 `wd=Y, mask=IN_MODIFY, name="file.txt"`

`IN_CREATE` 只有父目录匹配（`exact_mask=0`），因为创建事件总是由监控父目录的 watch 来报告子文件名。

### 4.3 `inotify_event` 序列化格式

每个事件按以下方式编码为字节：

```
偏移    字段          大小       说明
──────────────────────────────────────────────
0       wd           4 bytes    native endian
4       mask         4 bytes    native endian
8       cookie       4 bytes    始终 0
12      len          4 bytes    name 字段对齐后长度
16      name[0..]    len bytes  NUL 结尾 + padding

固定头部大小 = 16 bytes (INOTIFY_EVENT_SIZE)
```

name 的对齐规则：

```rust
fn align_event_name_len(len: usize) -> usize {
    let align = size_of::<usize>();     // x86_64 上为 8
    (len + align - 1) & !(align - 1)
}
```

例如：文件名 `"abc"` → 3 字节 + 1 NUL = 4 字节 → 按 8 对齐 → `len = 8`。

### 4.4 `FIONREAD` 的用途

`inotifywait` 在调用 `read` 之前可能通过 `ioctl(FIONREAD)` 查询待读字节数，以便分配足够大的缓冲区。本实现遍历事件队列，累加所有 `Vec<u8>` 的长度并返回：

```rust
FIONREAD => {
    let pending = self.state.lock()
        .queue.iter()
        .map(Vec::len)
        .sum::<usize>()
        .min(u32::MAX as usize) as u32;
    (arg as *mut u32).vm_write(pending)?;
    Ok(0)
}
```

### 4.5 可写 fd 关闭时触发 `IN_CLOSE_WRITE`

`IN_CLOSE_WRITE` 的语义是"以写模式打开的文件被关闭"。在 Linux 中，`close(fd)` 是触发此事件的唯一时机（而非 `write`）。因此需要在 fd 关闭路径中检查该 fd 是否具有写权限，而非在写入路径中触发。

StarryOS 在 `release_locks_on_close`（单 fd 关闭）和 `close_all_fds`（进程退出批量关闭）两处调用 `notify_close_write`。

### 4.6 删除后移除直接 watch

当 `unlinkat` 删除一个文件时，如果该文件路径上有直接 watch（即用户通过 `inotify_add_watch` 监控了被删除的文件本身），该 watch 的目标已不存在，必须移除。`notify_delete` 在推送 `IN_DELETE_SELF` 和 `IN_DELETE` 事件后，执行：

```rust
state.watches.retain(|_, watch| watch.path != path);
```

这与 Linux 行为一致：被删除文件的 watch 会收到 `IN_DELETE_SELF` + `IN_IGNORED`，然后被自动移除。

---

## 5 测试说明

### 5.1 测试位置

```
test-suit/starryos/normal/qemu-smp1/inotifywait/
├── qemu-x86_64.toml           # QEMU 测试配置
└── sh/
    └── inotifywait-tests.sh   # 测试脚本
```

### 5.2 测试配置

`qemu-x86_64.toml` 关键配置：

- 使用 Alpine rootfs 镜像（`rootfs-x86_64-alpine.img`）
- QEMU 启动后自动执行 `/usr/bin/inotifywait-tests.sh`
- 成功匹配：`INOTIFYWAIT_TEST_PASSED`
- 失败匹配：panic 信息 或 `INOTIFYWAIT_TEST_FAILED:`
- 超时：600 秒（考虑到 `apk add` 需要联网下载）

### 5.3 测试脚本流程

`inotifywait-tests.sh` 执行以下四个子测试：

#### 测试 1：IN_MODIFY

```
1. 后台进程 sleep 1 后向 watched.txt 追加内容
2. 前台 inotifywait -e modify 等待 watched.txt 的修改事件
3. 验证输出包含 "MODIFY"
```

#### 测试 2：IN_CREATE

```
1. 后台进程 sleep 1 后在 watchdir/ 下创建 created.txt
2. 前台 inotifywait -e create 等待 watchdir 的创建事件
3. 验证输出包含 "created.txt" 和 "CREATE"
```

#### 测试 3：IN_CLOSE_WRITE

```
1. 后台进程 sleep 1 后在 watchdir/ 下写入 closed.txt
2. 前台 inotifywait -e close_write 等待 watchdir 的关闭写入事件
3. 验证输出包含 "closed.txt" 和 "CLOSE_WRITE"
```

#### 测试 4：IN_DELETE

```
1. 预先创建 watchdir/deleted.txt
2. 后台进程 sleep 1 后 rm 删除该文件
3. 前台 inotifywait -e delete 等待 watchdir 的删除事件
4. 验证输出包含 "deleted.txt" 和 "DELETE"
```

全部通过时输出 `INOTIFYWAIT_TEST_PASSED`，任一失败输出 `INOTIFYWAIT_TEST_FAILED: <原因>`。

---

## 6 验证命令

### 6.1 代码格式检查

```bash
cargo fmt --all -- --check
```

### 6.2 Clippy 检查

```bash
cargo xtask clippy --package starry-kernel
```

检查 `starry-kernel` crate 是否有 clippy 警告。

### 6.3 QEMU 集成测试

```bash
# 在 Docker 容器中运行（推荐）
cargo xtask starry test qemu --arch x86_64 -c inotifywait
```

该命令会：
1. 编译 StarryOS x86_64 内核
2. 准备/复用 Alpine rootfs 镜像
3. 启动 QEMU
4. 在 guest 中执行测试脚本
5. 匹配输出判断通过/失败

---

## 7 当前局限

本 PR 的目标是让 StarryOS 能运行 Alpine 的 `inotifywait` 工具，属于**最小可用实现**，并非完整的 Linux inotify 子系统。以下列出主要差距：

### 7.1 未实现的事件类型

| 事件 | 说明 |
|------|------|
| `IN_ACCESS` | 文件被读取 |
| `IN_ATTRIB` | 文件元数据（权限、时间戳等）变更 |
| `IN_OPEN` | 文件被打开 |
| `IN_CLOSE_NOWRITE` | 只读 fd 关闭 |
| `IN_MOVED_FROM` / `IN_MOVED_TO` | 文件被 rename（需要 cookie 关联） |
| `IN_MOVE_SELF` | 被监控的路径自身被 rename |

### 7.2 未实现的 watch 控制标志

| 标志 | 说明 |
|------|------|
| `IN_ONESHOT` | 只触发一次事件后自动移除 watch |
| `IN_ONLYDIR` | 仅当路径为目录时才注册 watch |
| `IN_DONT_FOLLOW` | 不跟随符号链接 |
| `IN_MASK_ADD` | 向已有 watch 追加事件掩码（而非替换） |
| `IN_EXCL_UNLINK` | 不报告已 unlink 但仍有 fd 引用的文件事件 |

### 7.3 其他差距

- **基于路径而非 inode**：当前以路径字符串匹配 watch。如果文件被 rename 后仍保持原路径的 watch，行为与 Linux 不同（Linux 按 inode 追踪）
- **无事件合并**：Linux 会合并同一 wd 的相同事件（如连续两次 `IN_MODIFY` 只投递一次），本实现不做合并
- **无 `IN_Q_OVERFLOW`**：事件队列溢出时不通知用户空间
- **无资源限制**：不限制 inotify 实例数、watch 数、队列大小（仅硬编码 1024 上限）
- **无 mount 边界**：不检查 watch 与事件是否在同一 mount 点内
- **hardlink**：同一 inode 的多个路径被视为不同的 watch 目标

---

## 8 后续扩展建议

### 8.1 近期优先项

1. **支持 rename/move 事件**（`IN_MOVED_FROM`、`IN_MOVED_TO`、`IN_MOVE_SELF`）
   - 需要在 `sys_renameat` 中添加通知点
   - 需要实现 `cookie` 机制以关联 FROM/TO 事件对

2. **支持 `IN_OPEN` / `IN_ACCESS` / `IN_ATTRIB`**
   - `IN_OPEN`：在 `openat` 成功时触发
   - `IN_ACCESS`：在 `read` 成功时触发
   - `IN_ATTRIB`：在 `chmod` / `chown` / `utimens` 等 syscall 中触发

3. **将路径匹配升级为 inode/watch 语义**
   - 使用 `(device_id, inode_number)` 替代路径字符串作为 watch key
   - 这将自然支持 hardlink 和 rename 追踪

### 8.2 中期目标

4. **补充 syscall 级 C 测试**
   - 直接调用 `inotify_init1` / `inotify_add_watch` / `read` 等接口
   - 覆盖边界情况：空掩码、无效 fd、wd 不存在、缓冲区不足等
   - 不依赖 `inotifywait` 命令行工具

5. **增加更多架构的 QEMU 测试**
   - 目前仅有 `x86_64`，应扩展到 `riscv64`、`aarch64`
   - 需要为每个架构添加对应的 `qemu-<arch>.toml`

6. **实现 `IN_MASK_ADD`**
   - 允许向已有 watch 追加掩码而非替换
   - 这是 `inotify-tools` 某些用法所需的

### 8.3 长期方向

7. **实现事件合并**
8. **实现 `IN_Q_OVERFLOW` 和资源限制**
9. **实现 `IN_ONESHOT`、`IN_ONLYDIR`、`IN_DONT_FOLLOW`、`IN_EXCL_UNLINK`**
10. **mount 边界检查**
