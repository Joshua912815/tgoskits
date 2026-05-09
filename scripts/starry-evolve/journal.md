# StarryOS Evolution Journal

Tracking kernel improvements made by the starry-evolve framework.

## 2026-05-09 -- sys_sync / sys_syncfs

- **Analyzed**: `starry-analyze` identified sys_sync and sys_syncfs as stub (warn!("dummy") + Ok(0))
- **Contract**: Linux sync() flushes all filesystem buffers, syncfs(fd) flushes one filesystem. Both always succeed. StarryOS uses in-memory filesystems where sync is a VFS no-op, but calling VFS sync is correct behavior.
- **Fixed**: Replaced dummy stubs with real VFS calls:
  - `sys_sync()`: `FS_CONTEXT.lock().root_dir().sync(false)`
  - `sys_syncfs(fd)`: `File::from_fd(fd)?.inner().sync(false)` (matches existing fsync pattern)
- **Build**: PASS on riscv64, PASS on aarch64
- **Test**: PASS on riscv64 QEMU (starryos-test)
- **Regression**: No regressions detected

