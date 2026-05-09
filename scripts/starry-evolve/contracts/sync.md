# sys_sync / sys_syncfs — Linux Contract

## sys_sync

**原型**: `void sync(void)`
**系统调用号**: `SYS_sync` (无参数)
**glibc wrapper**: 不返回值，系统调用本身返回 0

### Linux 行为
- 将所有脏缓冲区刷新到存储设备
- 同步所有已挂载的文件系统
- 不保证数据落盘完成，只保证提交到设备队列
- 总是成功，不返回错误（Linux 内核中 sync 无失败路径）

### 返回值
- 成功：0
- 不可能失败（Linux 实现中不会返回错误）

### 实现
```c
// Linux kernel: fs/sync.c
SYSCALL_DEFINE0(sync)
{
    iterate_supers(sync_fs_one_sb, 0);
    iterate_blockdevs(flush_one_bdev, 0);
    return 0;
}
```

---

## sys_syncfs

**原型**: `int syncfs(int fd)`
**系统调用号**: `SYS_syncfs`

### Linux 行为
- 将指定 fd 所属文件系统的脏缓冲区刷新到存储设备
- `fd` 必须是一个有效的打开文件描述符

### 参数
- `fd`: 打开文件描述符

### 返回值
- 成功：0
- 失败：-1 并设置 errno

### 错误码
- `EBADF`: fd 不是有效的打开文件描述符

---

## StarryOS 实现状态

**当前**: stub，只打印 `warn!("dummy sys_sync")` 然后返回 `Ok(0)`

**修复方案**:
- `sys_sync()`: 调用 `FS_CONTEXT.lock().root_dir().sync(false)`
- `sys_syncfs(fd)`: 从 fd 获取文件，调用 `file.inner().sync(false)`，与已有的 `sys_fsync` 模式一致

**注意**: StarryOS 使用内存文件系统（tmpfs/pseudofs），sync 的 VFS 实现通常是空操作（返回 Ok），但调用 VFS sync 是正确的行为，确保如果有持久化后端也能正常工作。
