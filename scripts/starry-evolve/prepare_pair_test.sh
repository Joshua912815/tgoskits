#!/usr/bin/env bash
set -euo pipefail

ARCH="${1:-x86_64}"
SYSCALL="${2:-syncfs}"
IMAGE="${STARRY_EVOLVE_DOCKER_IMAGE:-starryos-dev:ubuntu-qemu10.2.1}"

if [[ "$ARCH" != "x86_64" ]]; then
  echo "prepare_pair_test.sh currently supports x86_64 only" >&2
  exit 2
fi

if [[ "$SYSCALL" != "syncfs" ]]; then
  echo "prepare_pair_test.sh currently supports syncfs only" >&2
  exit 2
fi

case "$ARCH" in
  x86_64) TARGET="x86_64-unknown-none" ;;
esac

ROOTFS="target/${TARGET}/rootfs-${ARCH}.img"
OUT_DIR="target/starry-evolve"
BIN="${OUT_DIR}/starry-evolve-${SYSCALL}"
SRC="scripts/starry-evolve/testcases/${SYSCALL}_pair.c"

mkdir -p "$OUT_DIR"

docker run --rm -v "$PWD":/mnt -w /mnt "$IMAGE" \
  bash -lc "export PATH=/opt/x86_64-linux-musl-cross/bin:\$PATH; x86_64-linux-musl-gcc -static -O2 -march=x86-64 -mtune=generic -Wall -Wextra -o '$BIN' '$SRC'"

cargo xtask starry rootfs --arch "$ARCH"

if [[ ! -f "$ROOTFS" ]]; then
  echo "rootfs not found at $ROOTFS" >&2
  exit 1
fi

docker run --rm -v "$PWD":/mnt -w /mnt "$IMAGE" bash -lc "
  debugfs -w -R 'rm /usr/bin/starry-evolve-${SYSCALL}' '$ROOTFS' >/dev/null 2>&1 || true
  debugfs -w -R 'write $BIN /usr/bin/starry-evolve-${SYSCALL}' '$ROOTFS'
  debugfs -w -R 'sif /usr/bin/starry-evolve-${SYSCALL} mode 0100755' '$ROOTFS'
"

echo "prepared $BIN and injected /usr/bin/starry-evolve-${SYSCALL} into $ROOTFS"
