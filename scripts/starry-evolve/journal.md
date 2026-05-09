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

## 2026-05-09 -- sys_get_mempolicy

- **Analyzed**: `starry-analyze` identified sys_get_mempolicy as stub (warn!("Dummy"))
- **Contract**: Linux get_mempolicy() on non-NUMA returns MPOL_DEFAULT (policy=0), zero nodemask. Both policy and nodemask are optional output (can be NULL).
- **Fixed**: Replaced dummy stub with real write: `policy.vm_write(0)` and `nodemask.vm_write(0)` when non-NULL. Uses VmMutPtr trait on raw pointers (same pattern as sys_capget).
- **Build**: PASS on riscv64
- **Test**: PASS on riscv64 QEMU
- **Regression**: No regressions detected

