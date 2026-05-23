# sync Linux Contract

- Schema: 1
- Status: CONTRACTED

## Linux Sources
- man-pages: sync(2) - sync() schedules dirty filesystem buffers for writeback and reports no errno to user space.
- linux-kernel: fs/sync.c: SYSCALL_DEFINE0(sync) - Linux returns 0 after iterating superblocks and block devices.

## Pairwise Cases
- `sync_returns_zero`: sync() succeeds and reports no errno
  compare: ret, errno, observable
