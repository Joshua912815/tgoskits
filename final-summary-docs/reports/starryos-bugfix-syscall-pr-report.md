# StarryOS BUG 修复与 syscall 增量 PR 报告

本文整理 GitHub 用户 `Joshua912815` 向 upstream 仓库 `rcore-os/tgoskits` 提交的、与 StarryOS BUG 修复和 syscall/系统兼容能力补齐直接相关的 PR。

统计时间：2026-06-05，时区按 UTC+8 记录。

## 范围说明

本报告纳入两类 PR：

- 修复 StarryOS 行为错误、Linux 兼容性问题、用户态程序无法运行的问题。
- 新增或补齐系统调用、系统调用 option、内核文件对象、伪文件系统语义，使 Linux/BusyBox/Go/PicoClaw/inotifywait 等用户态程序能够继续运行。

不纳入本报告的 PR：

- K230/QEMU/KPU/NNCase 支持类 PR，已在 KPU 专项文档中归档。
- 单纯新增 Starry app、示例、测试覆盖而没有 StarryOS bugfix/syscall 语义变化的 PR。

## 汇总

| PR | 状态 | 分类 | 核心内容 |
| --- | --- | --- | --- |
| [#224](https://github.com/rcore-os/tgoskits/pull/224) | 已合入 | StarryOS bugfix | 修复 signal check 屏蔽位的线程间串扰 |
| [#225](https://github.com/rcore-os/tgoskits/pull/225) | 已关闭，未合入 | StarryOS bugfix 尝试稿 | 修复 `/proc/[pid]/status` CPU affinity 固定为 CPU0，后续由 #267 收敛合入 |
| [#267](https://github.com/rcore-os/tgoskits/pull/267) | 已合入 | StarryOS bugfix | 正式修复 `/proc/[pid]/status` CPU affinity 输出 |
| [#276](https://github.com/rcore-os/tgoskits/pull/276) | 已合入 | syscall bugfix | 修复 `sched_getaffinity` / `sched_setaffinity` 对 `pid` 参数的处理 |
| [#475](https://github.com/rcore-os/tgoskits/pull/475) | 已关闭，未合入 | StarryOS bugfix 尝试稿 | 为 BusyBox `iostat` 补齐 `/proc/stat`、`/proc/diskstats`、`/proc/uptime` |
| [#659](https://github.com/rcore-os/tgoskits/pull/659) | 已合入 | syscall implementation | 将 `sync()` 从 stub 改成真实 VFS flush |
| [#660](https://github.com/rcore-os/tgoskits/pull/660) | 已合入 | syscall implementation | 将 `syncfs(fd)` 从 stub 改成文件系统级 sync |
| [#689](https://github.com/rcore-os/tgoskits/pull/689) | 已合入 | syscall compatibility | 为 PicoClaw/Go DNS 路径兼容 `setsockopt(SO_BROADCAST)` |
| [#776](https://github.com/rcore-os/tgoskits/pull/776) | 已合入 | StarryOS bugfix | 修复 readline/TUI 被 `ESC[6n` 光标位置查询阻塞 |
| [#780](https://github.com/rcore-os/tgoskits/pull/780) | 已合入 | syscall compatibility | 为 `prctl(PR_SET_VMA, PR_SET_VMA_ANON_NAME)` 提供 silent no-op |
| [#781](https://github.com/rcore-os/tgoskits/pull/781) | 已合入 | syscall implementation | 新增 `waitid()` 系统调用 |
| [#894](https://github.com/rcore-os/tgoskits/pull/894) | 已合入 | syscall implementation | 新增 inotify 系统调用和 `inotifywait` 支持 |

合入情况：

- 已合入：10 个。
- 已关闭未合入：2 个，其中 #225 后续由 #267 收敛合入，#475 是未合入的 BusyBox `/proc` 兼容尝试。

## PR 详细记录

### #224 fix: 修复 StarryOS 中 signal check 屏蔽位的线程间串扰问题

- 链接：[https://github.com/rcore-os/tgoskits/pull/224](https://github.com/rcore-os/tgoskits/pull/224)
- 状态：已合入。
- 创建时间：2026-04-16 18:34:31 UTC+8。
- 合入时间：2026-05-07 17:34:48 UTC+8。
- 规模：1 个 commit，4 个文件，新增 159 行，删除 6 行。

问题背景：

StarryOS 的 signal check 路径中，`block_next_signal` 原本使用全局原子变量保存“跳过下一次 signal check”的状态。这个设计在单线程或低并发场景中不明显，但在多线程、多核场景下会出现线程间串扰：一个线程设置的跳过标记可能被另一个线程提前消费，导致真正需要跳过 signal check 的线程失去保护。

修复内容：

- 将 signal check 的一次性屏蔽状态从全局变量迁移为线程私有状态。
- 在 `Thread` 结构中保存当前线程自己的 signal check block 状态。
- 在 signal handling 路径中通过当前线程访问该状态，而不是访问全局原子变量。
- 补充回归测试，分别证明旧实现会在线程间泄漏，修复后状态隔离。
- 更新 StarryOS bugfix 文档，记录现象、原因和修复方式。

主要改动文件：

- `.gitignore`
- `os/StarryOS/docs/bug-fixes.md`
- `os/StarryOS/kernel/src/task/mod.rs`
- `os/StarryOS/kernel/src/task/signal.rs`

验证记录：

- `cargo fmt --all -- --check`
- `cargo test -p starry-kernel old_global_signal_check_block_leaks_between_threads -- --nocapture`
- `cargo test -p starry-kernel per_thread_signal_check_block_is_isolated -- --nocapture`
- `cargo check -p starry-kernel --all-targets`

结果意义：

该 PR 修复的是内核信号处理的 SMP 语义错误。修复后，线程私有的一次性 signal check 屏蔽不再被其他线程消费，避免了多线程程序在信号处理路径上的不可预测行为。

### #225 fix: 修复 /proc/[pid]/status 中 CPU affinity 固定为 CPU0 的错误

- 链接：[https://github.com/rcore-os/tgoskits/pull/225](https://github.com/rcore-os/tgoskits/pull/225)
- 状态：已关闭，未合入。
- 创建时间：2026-04-16 19:24:16 UTC+8。
- 关闭时间：2026-05-07 16:53:41 UTC+8。
- 规模：37 个 commits，47 个文件，新增 1274 行，删除 343 行。

问题背景：

StarryOS 的 `/proc/[pid]/status` 中，CPU affinity 字段被固定输出为：

```text
Cpus_allowed:      1
Cpus_allowed_list: 0
```

这意味着无论线程真实 affinity 是否已经被调度系统设置到其他 CPU，用户态从 procfs 看到的结果都像“只能运行在 CPU0”。这与 Linux `/proc/[pid]/status` 语义不符，也会误导依赖 procfs 的诊断工具和测试程序。

修复思路：

- 在 `task_status()` 中读取线程真实 `cpumask`。
- 将 `Cpus_allowed` 按 Linux 风格十六进制位图输出。
- 将 `Cpus_allowed_list` 按 CPU 编号或连续区间输出。
- 添加内核单元测试证明旧实现固定输出错误，以及新实现能够反映真实 affinity。
- 在 `os/StarryOS/docs/bug-fixes.md` 中记录该问题。

主要改动文件：

该 PR 的分支携带了较多后续无关或工作区级改动，实际与本 bug 直接相关的核心文件是：

- `os/StarryOS/kernel/src/pseudofs/proc.rs`
- `os/StarryOS/docs/bug-fixes.md`

处理结果：

该 PR 未合入。后续通过更小、更聚焦的 #267 重新提交并合入了同一问题的最终修复。报告中保留 #225，是因为它是向 upstream 提交过的初始修复尝试；统计最终落地效果时应以 #267 为准。

### #267 fix: report real cpu affinity in proc status

- 链接：[https://github.com/rcore-os/tgoskits/pull/267](https://github.com/rcore-os/tgoskits/pull/267)
- 状态：已合入。
- 创建时间：2026-04-18 21:30:26 UTC+8。
- 合入时间：2026-04-19 00:16:54 UTC+8。
- 规模：1 个 commit，8 个文件，新增 350 行，删除 9 行。

问题背景：

这是 #225 的聚焦版和最终合入版，解决同一个 `/proc/[pid]/status` CPU affinity 输出错误。旧实现不读取真实 `cpumask`，导致 `Cpus_allowed` 和 `Cpus_allowed_list` 永远显示 CPU0。

修复内容：

- 在 `os/StarryOS/kernel/src/pseudofs/proc.rs` 中动态生成 CPU affinity 字段。
- `Cpus_allowed` 输出真实 bitmask，例如绑定 CPU1 后输出 `00000002`。
- `Cpus_allowed_list` 输出真实 CPU 编号或区间，例如绑定 CPU1 后输出 `1`。
- 新增用户态回归测试 `bug-proc-status-affinity`：
  - 调用 `sched_setaffinity()` 绑定到 CPU1。
  - 用 `sched_getaffinity()` 确认绑定生效。
  - 读取 `/proc/self/status`。
  - 检查 `Cpus_allowed` 和 `Cpus_allowed_list` 是否反映真实状态。
- 修改 `scripts/axbuild` 的 Starry normal case 处理，使 `qemu-<arch>.toml` 中的 `-smp` 参数可以通过标准测试入口同步生效。

主要改动文件：

- `os/StarryOS/kernel/src/pseudofs/proc.rs`
- `scripts/axbuild/src/starry/mod.rs`
- `scripts/axbuild/src/starry/rootfs.rs`
- `test-suit/starryos/GUIDE.md`
- `test-suit/starryos/normal/bug-proc-status-affinity/c/src/main.c`
- `test-suit/starryos/normal/bug-proc-status-affinity/qemu-x86_64.toml`

验证记录：

- `cargo fmt --manifest-path Cargo.toml --all`
- 多个 `starry-kernel` 单元测试，覆盖旧硬编码输出、真实 affinity 输出、十六进制 bitmask 格式和 CPU list 压缩格式。
- `cargo check -p starry-kernel --all-targets`
- `cargo xtask clippy --package axbuild`
- `cargo xtask starry test qemu -t x86_64 -c bug-proc-status-affinity`

结果意义：

该 PR 修复了 procfs 与调度状态不一致的问题，使 StarryOS 对 Linux 用户态诊断工具、进程状态读取工具和 affinity 测试程序更加兼容。

### #276 fix: respect pid in sched affinity syscalls

- 链接：[https://github.com/rcore-os/tgoskits/pull/276](https://github.com/rcore-os/tgoskits/pull/276)
- 状态：已合入。
- 创建时间：2026-04-19 23:48:39 UTC+8。
- 合入时间：2026-04-20 23:12:22 UTC+8。
- 规模：1 个 commit，5 个文件，新增 135 行，删除 14 行。

问题背景：

StarryOS 的 `sched_getaffinity()` / `sched_setaffinity()` 对 `pid` 参数处理不正确：

- `sched_getaffinity(pid != 0)` 直接返回错误，无法查询其他任务的 CPU affinity。
- `sched_setaffinity(pid)` 忽略传入的 `pid`，总是修改当前任务 affinity。

这会导致 Linux 程序无法正确管理子进程或其他线程的 CPU 亲和性，也会使 `/proc` affinity 修复无法形成完整闭环。

修复内容：

- 在 `os/StarryOS/kernel/src/syscall/task/schedule.rs` 中根据 `pid` 查找目标任务。
- 保留 `pid == 0` 表示当前任务的 Linux 语义。
- `sched_getaffinity()` 返回目标任务真实 `cpumask`。
- `sched_setaffinity()` 将非空 CPU mask 设置到目标任务。
- 对当前任务仍走原有 `set_current_affinity()`，保留迁移逻辑。
- 对其他任务更新其 `cpumask` 并触发 `interrupt()`。
- 新增用户态测试 `bug-sched-affinity-pid`：
  - parent 绑定 CPU0。
  - fork child。
  - parent 对 child 调用 `sched_setaffinity(child, CPU1)`。
  - 用 `sched_getaffinity(child)` 检查 child 已绑定 CPU1。
  - 再检查 parent 仍在 CPU0，确认没有误改当前任务。

主要改动文件：

- `os/StarryOS/kernel/src/syscall/task/schedule.rs`
- `test-suit/starryos/normal/bug-sched-affinity-pid/c/src/main.c`
- `test-suit/starryos/normal/bug-sched-affinity-pid/qemu-x86_64.toml`

验证记录：

- `cargo fmt --manifest-path Cargo.toml --all`
- `cargo check -p starry-kernel --all-targets`
- 旧实现下测试失败并打印 `TEST FAILED: get child affinity: Operation not permitted`
- 修复后测试通过并打印 `TEST PASSED`

结果意义：

该 PR 同时属于 bugfix 和 syscall 语义修复。修复后，StarryOS 的 affinity syscall 能正确作用于指定进程，避免用户态看到的调度控制结果与内核状态不一致。

### #475 fix: add procfs stats required by busybox iostat

- 链接：[https://github.com/rcore-os/tgoskits/pull/475](https://github.com/rcore-os/tgoskits/pull/475)
- 状态：已关闭，未合入。
- 创建时间：2026-05-09 16:44:39 UTC+8。
- 关闭时间：2026-05-10 10:50:20 UTC+8。
- 规模：1 个 commit，4 个文件，新增 227 行，删除 2 行。

问题背景：

BusyBox `iostat` 依赖 procfs 中的统计节点。旧 StarryOS 缺少这些节点，运行：

```sh
busybox iostat 1 1
```

会失败并报错无法打开 `/proc/stat`。

修复内容：

- 在 `os/StarryOS/kernel/src/pseudofs/proc.rs` 中补齐最小 procfs 统计节点：
  - `/proc/stat`
  - `/proc/diskstats`
  - `/proc/uptime`
- `/proc/stat` 提供 CPU 总统计和每核统计行。
- `/proc/uptime` 基于系统单调时钟动态生成。
- `/proc/diskstats` 提供可读取的空统计文件，避免工具因节点缺失直接失败。
- 新增 BusyBox 回归测试 `busybox-iostat`。
- 更新 StarryOS bug 文档。

主要改动文件：

- `os/StarryOS/docs/bug-fixes.md`
- `os/StarryOS/kernel/src/pseudofs/proc.rs`
- `test-suit/starryos/normal/qemu-smp1/busybox-iostat/qemu-x86_64.toml`
- `test-suit/starryos/normal/qemu-smp1/busybox-iostat/sh/busybox-iostat.sh`

验证记录：

- `cargo check -p starry-kernel --all-targets`
- `cargo xtask clippy --package starry-kernel`
- `cargo xtask starry test qemu --target x86_64-unknown-none -c busybox-iostat`
- 修复后 QEMU 中出现 `avg-cpu:` 和 `TEST PASSED`

处理结果：

该 PR 未合入。它仍然记录了一个明确的 StarryOS `/proc` 兼容性缺口和对应修复方案，但不能算作 upstream 已落地成果。

### #659 fix: implement sys_sync with real VFS call

- 链接：[https://github.com/rcore-os/tgoskits/pull/659](https://github.com/rcore-os/tgoskits/pull/659)
- 状态：已合入。
- 创建时间：2026-05-16 00:16:57 UTC+8。
- 合入时间：2026-05-18 14:35:41 UTC+8。
- 规模：5 个 commits，8 个文件，新增 235 行，删除 1 行。

问题背景：

StarryOS 的 `sync()` 原先只是 stub，行为上只打印 warning，并没有真正 flush 文件系统。这与 Linux `sync()` 语义不一致，也会影响依赖落盘语义的用户态程序、测试程序和文件系统一致性验证。

修复内容：

- 在 `os/StarryOS/kernel/src/syscall/fs/ctl.rs` 中将 `sys_sync()` 接到真实 VFS 层。
- 通过 `FS_CONTEXT.lock().root_dir().sync(false)` flush 根文件系统。
- 新增 `test-sync` 回归测试，覆盖 syscall 能执行并进入真实同步路径。
- 为 x86_64、aarch64、riscv64、loongarch64 四个架构补充测试配置。

主要改动文件：

- `os/StarryOS/kernel/src/syscall/fs/ctl.rs`
- `test-suit/starryos/normal/qemu-smp1/test-sync/c/src/main.c`
- `test-suit/starryos/normal/qemu-smp1/test-sync/qemu-x86_64.toml`
- `test-suit/starryos/normal/qemu-smp1/test-sync/qemu-aarch64.toml`
- `test-suit/starryos/normal/qemu-smp1/test-sync/qemu-riscv64.toml`
- `test-suit/starryos/normal/qemu-smp1/test-sync/qemu-loongarch64.toml`

结果意义：

该 PR 把 `sync()` 从“接口存在但无真实效果”推进到真实 VFS flush，属于系统调用实现质量补齐。它解决了文件系统同步 syscall 的 Linux 语义缺口。

### #660 fix: implement sys_syncfs with proper filesystem-level sync

- 链接：[https://github.com/rcore-os/tgoskits/pull/660](https://github.com/rcore-os/tgoskits/pull/660)
- 状态：已合入。
- 创建时间：2026-05-16 00:17:28 UTC+8。
- 合入时间：2026-05-18 14:36:19 UTC+8。
- 规模：4 个 commits，8 个文件，新增 247 行，删除 2 行。

问题背景：

`syncfs(fd)` 的 Linux 语义不是同步单个文件，而是同步 `fd` 所在的整个文件系统。StarryOS 原先对该 syscall 也只是 stub，无法满足用户态对文件系统级同步的预期。

修复内容：

- 在 `os/StarryOS/kernel/src/syscall/fs/ctl.rs` 中实现 `sys_syncfs(fd)`。
- 根据传入 fd 解析其所在 mountpoint root。
- 对该文件系统 root 调用 `sync()`，实现文件系统级 flush。
- 新增 `test-syncfs` 回归测试，覆盖 `syncfs(fd)` 路径。
- 为 x86_64、aarch64、riscv64、loongarch64 四个架构补充测试配置。

主要改动文件：

- `os/StarryOS/kernel/src/syscall/fs/ctl.rs`
- `test-suit/starryos/normal/qemu-smp1/test-syncfs/c/src/main.c`
- `test-suit/starryos/normal/qemu-smp1/test-syncfs/qemu-x86_64.toml`
- `test-suit/starryos/normal/qemu-smp1/test-syncfs/qemu-aarch64.toml`
- `test-suit/starryos/normal/qemu-smp1/test-syncfs/qemu-riscv64.toml`
- `test-suit/starryos/normal/qemu-smp1/test-syncfs/qemu-loongarch64.toml`

结果意义：

该 PR 补齐了 `syncfs(fd)` 与 Linux 的核心语义差异，使 StarryOS 可以按文件描述符定位文件系统并执行同步，而不是把它降级成无效果 stub 或单文件 flush。

### #689 feat(starry): add PicoClaw phase 1 and 2 support

- 链接：[https://github.com/rcore-os/tgoskits/pull/689](https://github.com/rcore-os/tgoskits/pull/689)
- 状态：已合入。
- 创建时间：2026-05-16 23:34:38 UTC+8。
- 合入时间：2026-05-18 22:44:15 UTC+8。
- 规模：3 个 commits，10 个文件，新增 1020 行。

纳入本报告的原因：

该 PR 的主体是 PicoClaw 示例和 smoke 支持，不是纯 syscall PR。但它包含一个直接的 StarryOS syscall 兼容补齐：兼容 `setsockopt(SOL_SOCKET, SO_BROADCAST)`，这是 Go DNS 路径在 PicoClaw 在线请求中需要的 socket option。

问题背景：

PicoClaw 是 Go 静态链接程序。在线 agent 路径会走 Go runtime / net 包的 DNS 和 socket 初始化逻辑，其中会调用：

```text
setsockopt(SOL_SOCKET, SO_BROADCAST)
```

StarryOS 原先缺少该 option 的兼容处理，会阻塞 PicoClaw online agent smoke。

修复内容：

- 在 StarryOS socket option syscall 路径中容忍 `SOL_SOCKET + SO_BROADCAST`。
- 增加 PicoClaw Phase 1 offline CLI smoke 和 Phase 2 online agent smoke。
- 添加资产和 rootfs 准备脚本，避免把 release 二进制、rootfs、secret 配置提交进仓库。

主要改动文件：

- `os/StarryOS/kernel/src/syscall/net/opt.rs`
- `examples/starry/picoclaw-cli/README.md`
- `examples/starry/picoclaw-cli/prepare_picoclaw_assets.sh`
- `examples/starry/picoclaw-cli/prepare_picoclaw_rootfs.sh`
- `examples/starry/picoclaw-cli/demo_picoclaw_agent.sh`
- `examples/starry/picoclaw-cli/qemu-x86_64-picoclaw-agent.toml`
- `examples/starry/picoclaw-cli/qemu-x86_64-picoclaw-offline.toml`

验证记录：

- `cargo fmt`
- shell 脚本语法检查。
- `cargo xtask clippy --package starry-kernel`
- Phase 1 offline QEMU smoke 达到 `STARRY_PICOCLAW_OFFLINE_PASSED`
- Phase 2 online QEMU smoke 达到 `STARRY_PICOCLAW_AGENT_PASSED`

结果意义：

这个 PR 体现了“真实用户态程序驱动 syscall 兼容补齐”的路线：不是为了单测单独补 option，而是从 Go/PicoClaw 的实际运行路径倒推出 StarryOS 缺失的 Linux socket option 兼容能力。

### #776 fix(starry-kernel): handle tty cursor position report

- 链接：[https://github.com/rcore-os/tgoskits/pull/776](https://github.com/rcore-os/tgoskits/pull/776)
- 状态：已合入。
- 创建时间：2026-05-19 21:15:02 UTC+8。
- 合入时间：2026-05-21 09:15:23 UTC+8。
- 规模：1 个 commit，9 个文件，新增 141 行，删除 5 行。

问题背景：

PicoClaw 在 StarryOS 上单轮 agent 请求可以工作，但直接运行交互模式时会停在 `Interactive mode` 后不响应按键。通过 `cat | picoclaw agent` 又能输入，说明问题不在 PicoClaw 主循环或网络请求，而在 tty/readline/raw terminal 初始化路径。

根因分析：

readline/TUI 程序在初始化终端时会输出 ANSI 光标位置查询：

```text
ESC[6n
```

然后等待终端回送：

```text
ESC[row;colR
```

StarryOS 的 QEMU 串口 tty 原先只把该查询序列输出到串口，没有生成回送数据，导致 readline 等待响应时阻塞。

修复内容：

- 在 StarryOS tty write 路径中识别 `ESC[6n`。
- 对真实 tty 注入保守响应 `ESC[1;1R`。
- 在 line discipline 中增加 injected input queue，使内核注入的数据能被 `poll()` 和 `read()` 感知。
- 新增 `bug-tty-cursor-report` 回归测试：
  - raw terminal 下写出 `ESC[6n`。
  - 用 `poll()` 等待 stdin 可读。
  - 校验读到 `ESC[1;1R`。
- 将测试加入 bugfix QEMU 配置。
- 顺手修正 `sys_syslog` 中 clippy 提示的同类型 raw pointer cast，行为不变。

主要改动文件：

- `os/StarryOS/kernel/src/pseudofs/dev/tty/mod.rs`
- `os/StarryOS/kernel/src/pseudofs/dev/tty/terminal/ldisc.rs`
- `os/StarryOS/kernel/src/syscall/sys.rs`
- `test-suit/starryos/normal/qemu-smp1/bugfix/bug-tty-cursor-report/c/src/main.c`
- `test-suit/starryos/normal/qemu-smp1/bugfix/qemu-x86_64.toml`
- `test-suit/starryos/normal/qemu-smp1/bugfix/qemu-aarch64.toml`
- `test-suit/starryos/normal/qemu-smp1/bugfix/qemu-riscv64.toml`
- `test-suit/starryos/normal/qemu-smp1/bugfix/qemu-loongarch64.toml`

验证记录：

- `cargo fmt`
- `cargo xtask clippy --package starry-kernel`
- `cargo xtask starry test qemu --arch x86_64 -c bugfix`
- PicoClaw 实测：StarryOS x86_64 QEMU 中直接运行 `picoclaw agent`，可以显示 `You:`、多轮输入输出，并通过 `exit` 正常退出。

结果意义：

该 PR 修复了 tty/readline 兼容性 bug，对 PicoClaw、readline、TUI、终端库类程序都有帮助。它补齐的是终端协议交互语义，不是应用专用 workaround。

### #780 fix(starry-kernel): handle prctl PR_SET_VMA as silent no-op

- 链接：[https://github.com/rcore-os/tgoskits/pull/780](https://github.com/rcore-os/tgoskits/pull/780)
- 状态：已合入。
- 创建时间：2026-05-19 23:16:55 UTC+8。
- 合入时间：2026-05-22 12:10:23 UTC+8。
- 规模：2 个 commits，7 个文件，新增 126 行。

问题背景：

PicoClaw 是 Go 静态链接程序。Go runtime 会调用：

```text
prctl(PR_SET_VMA, PR_SET_VMA_ANON_NAME, ...)
```

为匿名 VMA 命名。StarryOS 原先不识别该 `prctl` option，会打印 warning 并返回 `EINVAL`。虽然 Go runtime 不依赖 StarryOS 真正保存 VMA name，但返回错误和 warning 会影响兼容性和日志质量。

修复内容：

- 在 `sys_prctl()` 中新增 `PR_SET_VMA` 分支。
- 对 `PR_SET_VMA_ANON_NAME` 返回 `Ok(0)`。
- 不存储 VMA name，不验证用户指针。
- 其他 `PR_SET_VMA` 子操作返回 `EINVAL`。
- 去掉该已知兼容路径上的 warning。
- 使用 `linux_raw_sys::prctl::{PR_SET_VMA, PR_SET_VMA_ANON_NAME}` 常量。

语义边界：

这不是完整 Linux `PR_SET_VMA` 实现。它只针对 Go runtime 常见调用提供 silent no-op，满足“调用成功但不需要功能性副作用”的兼容目标。

主要改动文件：

- `os/StarryOS/kernel/src/syscall/task/ctl.rs`
- `test-suit/starryos/normal/qemu-smp1/bugfix/bug-prctl-set-vma-anon-name/c/src/main.c`
- `test-suit/starryos/normal/qemu-smp1/bugfix/qemu-x86_64.toml`
- `test-suit/starryos/normal/qemu-smp1/bugfix/qemu-aarch64.toml`
- `test-suit/starryos/normal/qemu-smp1/bugfix/qemu-riscv64.toml`
- `test-suit/starryos/normal/qemu-smp1/bugfix/qemu-loongarch64.toml`

验证记录：

- `cargo fmt --all -- --check`
- CI x86_64 bugfix 通过。

结果意义：

该 PR 补齐了 Go runtime 在 Linux 上常用但对 StarryOS 暂无实际功能需求的 `prctl` 子功能，避免为了运行 Go 程序而提前引入完整 VMA name 管理。

### #781 feat(starry-kernel): implement waitid syscall

- 链接：[https://github.com/rcore-os/tgoskits/pull/781](https://github.com/rcore-os/tgoskits/pull/781)
- 状态：已合入。
- 创建时间：2026-05-19 23:23:14 UTC+8。
- 合入时间：2026-05-22 15:51:53 UTC+8。
- 规模：2 个 commits，9 个文件，新增 511 行，删除 48 行。

问题背景：

PicoClaw gateway/tool 执行路径会调用 `waitid()`。StarryOS 原先打印：

```text
Unimplemented syscall: waitid
```

并返回 `ENOSYS`。这会影响子进程清理、工具执行和等待子进程状态的 Linux 程序。

实现内容：

- 新增 `sys_waitid()`。
- 基于已有 `sys_waitpid` 体系复用等待子进程的基础逻辑。
- 支持 `idtype`：
  - `P_ALL`
  - `P_PID`
- 支持 options：
  - `WEXITED`
  - `WNOHANG`
  - `WNOWAIT`
- 写入 `siginfo_t`：
  - `si_signo = SIGCHLD`
  - `si_code = CLD_EXITED` / `CLD_KILLED` / `CLD_DUMPED`
  - `si_pid`
  - `si_uid`
  - `si_status`
- `WNOHANG` 无就绪子进程时返回 0，并清零 `siginfo`。
- 无匹配子进程返回 `ECHILD`。
- 默认行为 reap zombie 子进程。
- `WNOWAIT` 只查询，不回收 zombie。

暂不支持的语义：

- `P_PGID`
- `P_PIDFD`
- `WSTOPPED`
- `WCONTINUED`
- rusage

实现细节：

- 扩展 `WaitPid` 和 `WaitOptions`。
- 新增 `WEXITED`、`WNOWAIT` 相关 bitflags。
- `decode_wait_status()` 将 Linux wait status 编码解码成 `CLD_*`。
- 通过 `get_zombie_cred()` 获取 zombie 子进程 UID，避免 task 已被 GC 后丢失 credential。
- 异步等待复用 `child_exit_event` 和 waker recheck。

主要改动文件：

- `os/StarryOS/kernel/src/syscall/mod.rs`
- `os/StarryOS/kernel/src/syscall/task/wait.rs`
- `os/StarryOS/kernel/src/task/ops.rs`
- `test-suit/starryos/normal/qemu-smp1/bugfix/bug-waitid-basic/c/src/main.c`
- `test-suit/starryos/normal/qemu-smp1/bugfix/qemu-x86_64.toml`
- `test-suit/starryos/normal/qemu-smp1/bugfix/qemu-aarch64.toml`
- `test-suit/starryos/normal/qemu-smp1/bugfix/qemu-riscv64.toml`
- `test-suit/starryos/normal/qemu-smp1/bugfix/qemu-loongarch64.toml`

测试覆盖：

- `P_PID + WEXITED`：fork child exit(7)，验证 siginfo 字段和 reap。
- `P_ALL + WEXITED`：fork child exit(3)，验证任意子进程等待。
- `WNOHANG`：child 仍运行时返回 0 且 `si_pid == 0`。
- 非子进程 PID 返回 `ECHILD`。
- 非法 idtype 返回 `EINVAL`。
- 缺少 `WEXITED` 返回 `EINVAL`。

验证记录：

- `cargo fmt --all -- --check`
- 完整 QEMU 回归由 CI 执行。

结果意义：

该 PR 是明确的 syscall 增量，实现了 Linux 常见进程等待接口 `waitid()`，使 StarryOS 对工具执行器、shell wrapper、Go/CLI 程序的子进程管理更加兼容。

### #894 feat(starry-kernel): add inotifywait support

- 链接：[https://github.com/rcore-os/tgoskits/pull/894](https://github.com/rcore-os/tgoskits/pull/894)
- 状态：已合入。
- 创建时间：2026-05-23 12:24:34 UTC+8。
- 合入时间：2026-05-25 12:00:47 UTC+8。
- 规模：2 个 commits，10 个文件，新增 548 行，删除 13 行。

问题背景：

`inotifywait` 依赖 Linux inotify 系统调用创建监听 fd、添加 watch，并通过 `poll()` / `read()` 获取文件事件。StarryOS 原先对 `inotify_init1` 直接返回 unsupported，因此 `inotify-tools` 中的 `inotifywait` 无法运行。

实现内容：

- 新增 `Inotify` file-like 对象。
- 支持 `inotify_init1` 创建匿名 fd。
- 支持 `inotify_add_watch` / `inotify_rm_watch`。
- 支持 `poll()` 和 `read()` 读取 `inotify_event`。
- 支持 `IN_NONBLOCK` / `IN_CLOEXEC`。
- 支持 `ioctl(FIONREAD)` 查询当前事件队列可读字节数。
- 目录 watch 事件携带 `name` 字段。

文件系统事件接入：

- 普通文件 `write` 成功后投递 `IN_MODIFY`。
- `open(O_CREAT)` 新建文件后向父目录投递 `IN_CREATE`。
- 可写文件描述符关闭时投递 `IN_CLOSE_WRITE`。
- `unlinkat` / `rmdir` 成功后投递 `IN_DELETE`。
- 直接 watch 被删除路径时投递 `IN_DELETE_SELF`。

实现逻辑：

- watch 以解析后的绝对路径为 key。
- 普通文件事件同时匹配直接 watch 和父目录 watch。
- 父目录事件把文件名写入 `inotify_event.name`，满足 `inotifywait --format %f` 等目录监听场景。
- 删除路径时清理对应 watch，避免后续继续对已删除路径投递事件。

主要改动文件：

- `os/StarryOS/kernel/src/file/fs.rs`
- `os/StarryOS/kernel/src/file/inotify.rs`
- `os/StarryOS/kernel/src/file/mod.rs`
- `os/StarryOS/kernel/src/syscall/fs/ctl.rs`
- `os/StarryOS/kernel/src/syscall/fs/fd_ops.rs`
- `os/StarryOS/kernel/src/syscall/fs/inotify.rs`
- `os/StarryOS/kernel/src/syscall/fs/mod.rs`
- `os/StarryOS/kernel/src/syscall/mod.rs`
- `test-suit/starryos/normal/qemu-smp1/inotifywait/qemu-x86_64.toml`
- `test-suit/starryos/normal/qemu-smp1/inotifywait/sh/inotifywait-tests.sh`

测试覆盖：

新增 `test-suit/starryos/normal/qemu-smp1/inotifywait`，在 guest 中安装 `inotify-tools`，验证：

- `MODIFY`
- `CREATE`
- `CLOSE_WRITE`
- `DELETE`

验证记录：

- `cargo fmt`
- Docker: `cargo xtask starry test qemu --arch x86_64 -c inotifywait`
- Docker: `cargo xtask clippy --package starry-kernel`

结果意义：

该 PR 是 syscall 和内核文件对象的系统性补齐。它不仅让 `inotifywait` 能运行，还为 StarryOS 提供了基础 inotify 事件模型，为后续更多 Linux 文件监控类程序提供兼容基础。

## 横向分析

### 1. BUG 修复主线

这些 PR 的 BUG 修复集中在三个层面：

- 内核并发语义：#224 修复 signal check block 的全局状态串扰。
- 用户态可见状态：#267 和 #276 让 affinity syscall 与 `/proc` 状态一致；#475 尝试补齐 BusyBox 依赖的 procfs 统计节点。
- 真实程序兼容性：#776 修复 readline/TUI 交互阻塞，#780 处理 Go runtime 的 `prctl` 兼容，#689 处理 Go DNS path 的 socket option。

整体特点是：问题通常由真实用户态程序触发，再反向定位 StarryOS 与 Linux 语义之间的缺口，并用小测试固定回归。

### 2. syscall 增量主线

syscall 相关 PR 覆盖从“stub 变真实实现”到“新增完整接口”：

- `sync()`：#659 从 warning stub 变成 VFS root sync。
- `syncfs(fd)`：#660 从 stub 变成按 fd 所在文件系统 sync。
- `setsockopt(SO_BROADCAST)`：#689 补齐 Go/PicoClaw 需要的 socket option 兼容。
- `prctl(PR_SET_VMA_ANON_NAME)`：#780 用 silent no-op 兼容 Go runtime。
- `waitid()`：#781 新增进程等待 syscall。
- `inotify_*`：#894 新增 inotify file-like 对象、syscall 和文件事件投递。

这些改动不是单纯增加 syscall number，而是围绕 Linux 用户态语义补齐内核对象、fd 行为、poll/read、siginfo、文件系统事件和 VFS flush 等配套逻辑。

### 3. 测试方式演进

报告中的 PR 基本都包含回归测试或真实程序 smoke：

- 内核单元测试：用于证明旧实现错误和新实现正确，如 #224、#267。
- 用户态 C 回归：用于固定 syscall 行为，如 #276、#780、#781。
- Starry QEMU 测试：用于验证 guest 中真实 syscall 和文件系统路径，如 #659、#660、#776、#894。
- 真实应用 smoke：用于验证 Go/PicoClaw/readline/inotifywait 等实际程序链路，如 #689、#776、#894。

这说明 bugfix 和 syscall 增量不是孤立 patch，而是逐步建立了可复现、可回归的验证入口。

## 结论

这些 PR 共同推进了 StarryOS 的 Linux 兼容性：

- 修复了 signal、affinity、procfs、tty 等内核行为 bug。
- 补齐了 `sync`、`syncfs`、`waitid`、inotify、`prctl` option、`setsockopt` option 等用户态程序常用能力。
- 通过 BusyBox、PicoClaw、readline/TUI、inotifywait 等真实程序暴露问题，再用专用测试固定回归。
- 已合入的 10 个 PR 构成了 StarryOS bugfix/syscall 支持的主要 upstream 成果；#225 和 #475 是提交过但未合入的尝试记录，其中 #225 的最终成果已通过 #267 合入。
