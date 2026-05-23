#!/usr/bin/env bash
set -euo pipefail

IMAGE="${STARRY_EVOLVE_DOCKER_IMAGE:-starryos-dev:ubuntu-qemu10.2.1}"
ARCH="${1:-x86_64}"

if [[ "$ARCH" != "x86_64" ]]; then
  echo "run_syncfs_pair.sh currently supports x86_64 only" >&2
  exit 2
fi

scripts/starry-evolve/prepare_pair_test.sh "$ARCH" syncfs

python3 scripts/starry-evolve/evolve.py test \
  --syscall syncfs \
  --target "$ARCH" \
  --timeout 600 \
  --linux-command "docker run --rm -e STARRY_EVOLVE_RUN_ID -v \"\$PWD\":/mnt -w /mnt ${IMAGE} /opt/qemu-10.2.1/bin/qemu-x86_64 /mnt/target/starry-evolve/starry-evolve-syncfs" \
  --starry-command "docker run --rm -v \"\$PWD\":/mnt -w /mnt ${IMAGE} bash -lc 'export PATH=/opt/qemu-10.2.1/bin:\$PATH; cargo xtask starry test qemu --target ${ARCH} --timeout 40 --shell-init-cmd \"STARRY_EVOLVE_RUN_ID={run_id} /usr/bin/starry-evolve-syncfs && echo All tests passed!\"'" \
  --source scripts/starry-evolve/testcases/syncfs_pair.c \
  --binary target/starry-evolve/starry-evolve-syncfs
