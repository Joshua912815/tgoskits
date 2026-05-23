# syncfs Linux Contract

- Schema: 1
- Status: CONTRACTED

## Linux Sources
- man-pages: syncfs(2) - syncfs(fd) synchronizes the filesystem containing fd.
- linux-kernel: fs/sync.c: SYSCALL_DEFINE1(syncfs, int, fd) - Linux validates fd and returns EBADF for invalid descriptors.

## Pairwise Cases
- `syncfs_invalid_fd_ebadf`: syncfs(-1) fails with EBADF
  compare: ret, errno, observable
