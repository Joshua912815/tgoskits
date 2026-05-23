#define _GNU_SOURCE

#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/syscall.h>
#include <unistd.h>

#ifndef SYS_syncfs
#if defined(__x86_64__)
#define SYS_syncfs 306
#elif defined(__aarch64__)
#define SYS_syncfs 267
#elif defined(__riscv)
#define SYS_syncfs 267
#elif defined(__loongarch64)
#define SYS_syncfs 267
#else
#error "SYS_syncfs is not defined for this architecture"
#endif
#endif

static uint64_t fnv1a64_update(uint64_t value, const char *text) {
    const unsigned char *p = (const unsigned char *)text;
    while (*p) {
        value ^= (uint64_t)(*p++);
        value *= 0x100000001b3ULL;
    }
    return value;
}

static void checksum(
    char out[17],
    const char *run_id,
    const char *case_id,
    long ret,
    int err,
    const char *observable_json
) {
    char number[64];
    uint64_t value = 0xcbf29ce484222325ULL;
    value = fnv1a64_update(value, run_id);
    value = fnv1a64_update(value, "\n");
    value = fnv1a64_update(value, case_id);
    value = fnv1a64_update(value, "\n");
    snprintf(number, sizeof(number), "%ld", ret);
    value = fnv1a64_update(value, number);
    value = fnv1a64_update(value, "\n");
    snprintf(number, sizeof(number), "%d", err);
    value = fnv1a64_update(value, number);
    value = fnv1a64_update(value, "\n");
    value = fnv1a64_update(value, observable_json);
    snprintf(out, 17, "%016llx", (unsigned long long)value);
}

static void emit_case(
    const char *run_id,
    const char *case_id,
    long ret,
    int err,
    const char *observable_json
) {
    char sum[17];
    checksum(sum, run_id, case_id, ret, err, observable_json);
    printf(
        "{\"type\":\"starry_evolve_case\",\"run_id\":\"%s\",\"case_id\":\"%s\","
        "\"ret\":%ld,\"errno\":%d,\"observable\":%s,\"checksum\":\"%s\"}\n",
        run_id,
        case_id,
        ret,
        err,
        observable_json,
        sum
    );
}

int main(void) {
    const char *run_id = getenv("STARRY_EVOLVE_RUN_ID");
    if (run_id == NULL || run_id[0] == '\0') {
        fputs("STARRY_EVOLVE_RUN_ID is required\n", stderr);
        return 2;
    }

    errno = 0;
    long ret = syscall(SYS_syncfs, -1);
    int err = errno;
    if (ret == -1 && err == EBADF) {
        emit_case(run_id, "syncfs_invalid_fd_ebadf", ret, err, "{\"error\":\"EBADF\"}");
    } else {
        emit_case(run_id, "syncfs_invalid_fd_ebadf", ret, err, "{\"error\":\"unexpected\"}");
    }

    return 0;
}
