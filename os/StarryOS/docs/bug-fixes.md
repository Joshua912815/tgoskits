# StarryOS Bug 修复记录

本文档用于记录 `os/StarryOS` 中已经发现、完成修复并已合入上游 `dev` 分支的 bug。

当前已对应 3 个已 merge 的 PR：

- PR [#224](https://github.com/rcore-os/tgoskits/pull/224)：修复 signal check 屏蔽位的线程间串扰问题
- PR [#267](https://github.com/rcore-os/tgoskits/pull/267)：修复 `/proc/[pid]/status` 中 CPU affinity 固定为 CPU0 的错误
- PR [#276](https://github.com/rcore-os/tgoskits/pull/276)：修复 `sched_getaffinity` / `sched_setaffinity` 未正确处理 `pid` 参数的问题

## Bug 1：signal check 屏蔽位使用全局状态，导致线程间串扰

- 类型：并发、语义、正确性
- 对应 PR：[#224](https://github.com/rcore-os/tgoskits/pull/224)
- 参考：
  `os/StarryOS-REF/docs/starry_smp_ultimate_integrated.md`
- 修复前相关代码：
  `kernel/src/task/signal.rs`
- 修复后相关代码：
  `kernel/src/task/mod.rs`
  `kernel/src/task/signal.rs`

### 问题现象

修复前，StarryOS 用一个全局 `AtomicBool` 保存“跳过下一次 signal check”的状态。

这个状态本来应该只影响“当前线程在 `rt_sigreturn` 之后的下一次返回用户态前的 signal check”，但全局实现会让多个线程共享同一个一次性标记：

- 线程 A 设置了“跳过下一次 signal check”
- 线程 B 先执行到 signal check
- 线程 B 把这个全局标记消费掉
- 线程 A 反而失去自己本应保留的跳过机会

更具体地说，signal return 路径中的这一步本来是在“线程自己的控制流”里完成的：某个线程从信号处理函数返回后，内核需要在它下一次准备返回用户态时跳过一次常规 signal check，避免同一轮返回路径被重新打断。这个“一次性跳过”天然应该和具体线程绑定。

但旧实现把它做成了整个系统共享的一个全局布尔位。这样一来，在 SMP 或多线程并发执行时，这个位既没有记录“是谁设置的”，也没有记录“应该由谁消费”，只表示“系统里有某个线程想跳过下一次检查”。结果就是，只要另外一个线程恰好更早走到 signal check，它就可能把这个全局位清掉。

从用户态可见效果上看，这会表现为非常隐蔽的不稳定行为：

- 有时线程从信号处理函数返回后，下一次路径是正常的
- 有时同样的线程明明设置了跳过标记，却仍然再次触发 signal check
- 问题只会在多线程或多核调度交错下出现，单线程测试往往不容易直接暴露

这也是一个典型的“单核上不明显、并发下才稳定暴露”的 SMP 语义错误。

### 为什么这是 bug

- 该状态的语义本来就是线程私有的一次性状态，不应该跨线程共享。
- 在 SMP 或多线程场景下，全局原子变量会直接引入跨线程串扰。
- 这会导致 signal return 路径与预期 Linux 语义不一致，属于典型的并发 + 语义错误。

进一步看，这个问题不只是“实现不够优雅”，而是会破坏内核对 signal 控制流的基本约束：

- `rt_sigreturn` 影响的是当前线程自己的用户态返回路径，而不是进程内其他线程
- 该状态是一次性的控制标记，不是全局开关
- 谁设置，谁消费，这个对应关系必须严格保持

旧实现虽然用了原子变量，避免了数据竞争意义上的未定义行为，但并没有保证“语义上的隔离”。也就是说，它在线程安全的最底层层面上没有崩，但在线程语义的更高层面上已经错了。

因此，这个问题同时属于三类 bug：

- 并发 bug：多个线程会竞争同一个本不该共享的状态
- 语义 bug：`rt_sigreturn` 的影响范围从“当前线程”错误扩大成了“系统里任意一个先到达检查点的线程”
- 正确性 bug：最终行为不再满足接口和控制流设计的预期

### 修复方式

- 将“下次跳过 signal check”的状态从全局 `AtomicBool` 改为 `Thread` 私有字段。
- 在 `Thread` 上新增对应的设置/消费逻辑。
- `block_next_signal()` / `unblock_next_signal()` 改为通过当前线程访问该状态，不再共享全局变量。
- 补充回归测试，分别验证：
  旧实现确实会在线程之间泄漏该状态
  修复后该状态在线程之间隔离

修复的核心思想很直接：既然这个状态描述的是“某个线程的下一次 signal check 是否需要跳过”，那它就必须存放在该线程自己的控制块里，而不能放在全局。

因此实现上做了两件事：

- 把状态下沉到 `Thread` 结构里，让每个线程拥有自己的“一次性跳过位”
- 把原先访问全局位的逻辑改成“访问当前线程的状态”，从而恢复“设置者和消费者是同一个线程”的关系

这样修改后，不同线程之间即使并发执行，也只能读写自己的那一份状态：

- 线程 A 设置的标记，只会被线程 A 的 signal check 消费
- 线程 B 无法再提前消费线程 A 的状态
- 标记仍然保持“一次性”语义，但作用范围被正确限制在线程内部

此外，回归测试也不是只验证“现在能跑通”，而是同时覆盖了：

- 旧模型为什么会错
- 新模型为什么不会再错

这样后续如果有人再次尝试把这类线程私有状态改回全局共享，实现会被测试第一时间拦住。

### Docker 验证

验证使用 `starryos-dev:ubuntu-qemu10.2.1` 镜像完成。

```bash
docker run -d --name starry-signal-validate -v "$PWD":/workspace -w /workspace \
  starryos-dev:ubuntu-qemu10.2.1 sh -lc 'sleep infinity'

docker exec starry-signal-validate sh -lc '
set -e
export PATH=/opt/rustup/toolchains/nightly-2026-02-25-aarch64-unknown-linux-gnu/bin:$PATH
export RUSTUP_TOOLCHAIN=nightly-2026-02-25-aarch64-unknown-linux-gnu
cargo fmt --manifest-path /workspace/os/StarryOS/Cargo.toml --all -- --check
tmp=/tmp/starryos-kernel-tests
rm -rf "$tmp"
mkdir -p "$tmp"
cp -R /workspace/os/StarryOS/kernel "$tmp"/kernel
cp /workspace/os/StarryOS/Cargo.toml "$tmp"/Cargo.toml
sed -i "s/members = [\"starryos\", \"kernel\"]/members = [\"kernel\"]/" "$tmp"/Cargo.toml
sed -i "/starry-kernel = { path = \"kernel\", version = \"0.5.0\" }/d" "$tmp"/Cargo.toml
cd "$tmp"
cargo test -p starry-kernel old_global_signal_check_block_leaks_between_threads -- --nocapture
cargo test -p starry-kernel per_thread_signal_check_block_is_isolated -- --nocapture
cargo check -p starry-kernel --all-targets
'
```

预期结果：

- `old_global_signal_check_block_leaks_between_threads` 通过，用来证明旧实现中的 bug 确实存在。
- `per_thread_signal_check_block_is_isolated` 通过，用来证明修复后线程间不再串扰。
- `cargo check -p starry-kernel --all-targets` 通过。

## Bug 2：`/proc/[pid]/status` 把 CPU affinity 固定伪装成“只允许 CPU0”

- 类型：语义、正确性、可观测性
- 对应 PR：[#267](https://github.com/rcore-os/tgoskits/pull/267)
- 参考：
  `os/StarryOS-REF/docs/starry_smp_ultimate_integrated.md` 第 18.3、23.4 节
- 修复前相关代码：
  `kernel/src/pseudofs/proc.rs`
- 修复后相关代码：
  `kernel/src/pseudofs/proc.rs`
  `scripts/axbuild/src/starry/mod.rs`
  `scripts/axbuild/src/starry/rootfs.rs`
  `test-suit/starryos/normal/bug-proc-status-affinity`

### 问题现象

修复前，`kernel/src/pseudofs/proc.rs` 中的 `task_status()` 直接把下面两个字段写死：

- `Cpus_allowed:\t1`
- `Cpus_allowed_list:\t0`

这意味着无论线程真实的 affinity 是什么，用户态通过 `/proc/[pid]/status` 看到的永远都是“只能在 CPU0 上运行”。

这类错误在单纯查看代码时不一定显眼，但在实际系统行为上很容易造成误判。因为 StarryOS 内部其实已经维护了线程真实的 `cpumask`，并且 affinity 相关 syscall 也会读写这个状态。也就是说，内核内部的 CPU 绑定状态和 `/proc` 对外暴露的状态从一开始就是“两套不一致的答案”。

例如，一个线程如果已经通过 `sched_setaffinity()` 被绑定到 CPU1，或者允许在多个 CPU 上运行，那么：

- `sched_getaffinity()` 看到的是修改后的真实 mask
- `/proc/[pid]/status` 看到的却仍然是 `1` 和 `0`

这种差异会直接导致用户态程序、调试工具或测试脚本得出错误结论，以为 affinity 根本没有生效，或者以为系统只支持 CPU0。

更严重的是，这不是“格式小问题”，而是“状态对外报告错误”：

- 内核内部真实状态是对的
- `/proc` 导出的状态是假的
- 用户态只能看到假的那一份

因此只要依赖 `/proc/[pid]/status` 做检查，旧实现就会稳定地产生误导。

### 为什么这是 bug

- StarryOS 已经实现了线程 CPU affinity 的内部状态，`sched_getaffinity` 也会读取线程的 `cpumask`。
- 但 `/proc/[pid]/status` 却始终返回固定值，导致用户态观测面和内核真实状态不一致。
- 在 SMP 场景下，这会直接误导调试和验证工作：即使线程允许在多个 CPU 上运行，`/proc` 仍然会谎报成单核绑定。

`/proc/[pid]/status` 的职责之一，就是把任务当前的一部分内核状态稳定、可读地暴露给用户态。对 Linux 兼容系统来说，这不是“可有可无的调试输出”，而是很多程序和测试天然依赖的接口。

因此，旧实现的问题在于它破坏了两个关键约束：

- 观测一致性：内核内部状态和对外导出状态必须一致
- 接口语义一致性：同一个任务的 affinity，不应该在 syscall 接口和 `/proc` 接口上出现两套互相矛盾的结果

一旦这两个约束被破坏，影响会超出单个字段本身：

- 用户态无法信任 `/proc/[pid]/status`
- affinity 相关测试无法判断是内核没改对，还是 `/proc` 谎报
- 后续排查 SMP 调度问题时，调试信息本身会成为噪声

所以这个问题既是语义 bug，也是正确性 bug，同时还是一个“可观测性错误”：系统真实状态存在，但导出的观测面是错误的。

### 修复方式

- 将 `task_status()` 改为读取线程真实的 `cpumask`。
- 新增格式化逻辑，把 affinity 渲染为：
  `Cpus_allowed` 的十六进制位图形式
  `Cpus_allowed_list` 的 CPU 编号/区间形式
- 在 `test-suit/starryos/normal/bug-proc-status-affinity` 中补充用户态 C 测例。
- 在 `scripts/axbuild` 中补充 Starry normal case 对 `qemu-<arch>.toml` 里 `-smp` 参数的同步支持，使该测例可以通过标准 `cargo xtask starry test qemu` 入口运行。

修复时没有采用“把硬编码值改成另一个常量”这种局部补丁，而是把整条信息生成链路改成真正依赖线程当前状态：

- 先从线程对象读取真实 `cpumask`
- 再根据这个 mask 生成 `Cpus_allowed`
- 同时把同一份 mask 转换成 `Cpus_allowed_list`

这样可以保证两个字段来自同一份真实状态，而不是分别拼出来的两套结果。

另外，这个 bug 的 PR 之所以还修改了 `scripts/axbuild` 和 test-suit，不是为了“顺手整理代码”，而是为了满足课程对 fixbug PR 的要求：必须给出真正能在标准测试入口下复现和验证的用户态测例。

因此这次修复是成体系完成的：

- 内核 patch 负责修正 `/proc` 的状态导出逻辑
- 用户态 C 测例负责从真实使用场景复现问题
- `xtask` 适配负责让这个多核测例能通过标准方式跑起来

这样后续任何人只要跑标准测试，就能同时看到：

- 旧实现为什么错
- 修复后为什么对
- `/proc` 输出、syscall 行为和多核执行环境三者已经对齐

### Docker 验证

验证使用 `starryos-dev:ubuntu-qemu10.2.1` 镜像完成。

```bash
docker run -d --name starry-proc-status-validate -v "$PWD":/workspace -w /workspace \
  starryos-dev:ubuntu-qemu10.2.1 sh -lc 'sleep infinity'

docker exec starry-proc-status-validate sh -lc '
set -e
export PATH=/opt/rustup/toolchains/nightly-2026-02-25-aarch64-unknown-linux-gnu/bin:$PATH
export RUSTUP_TOOLCHAIN=nightly-2026-02-25-aarch64-unknown-linux-gnu
cargo fmt --manifest-path /workspace/Cargo.toml --all
cargo test -p axbuild smp_from_qemu_arg -- --nocapture
cargo test -p axbuild apply_smp_qemu_arg_ -- --nocapture
cargo test -p starry-kernel old_hardcoded_status_lies_about_non_cpu0_affinity -- --nocapture
cargo test -p starry-kernel task_status_reports_real_affinity_instead_of_cpu0_only -- --nocapture
cargo test -p starry-kernel cpus_allowed_hex_matches_actual_affinity_bits -- --nocapture
cargo test -p starry-kernel cpus_allowed_hex_orders_32bit_words_from_high_to_low -- --nocapture
cargo test -p starry-kernel cpus_allowed_list_compacts_contiguous_ranges -- --nocapture
cargo check -p starry-kernel --all-targets
cargo xtask clippy --package axbuild
cargo xtask starry test qemu -t x86_64 -c bug-proc-status-affinity
'
```

预期结果：

- 旧实现下，用户态测例会失败，能够真实复现该 bug。
- 修复后，`bug-proc-status-affinity` 输出 `TEST PASSED`。
- 相关 host 测试和 `cargo check` 通过。

## Bug 3：`sched_getaffinity` / `sched_setaffinity` 没有正确处理 `pid` 参数

- 类型：语义、正确性
- 对应 PR：[#276](https://github.com/rcore-os/tgoskits/pull/276)
- 修复前相关代码：
  `kernel/src/syscall/task.rs`
- 修复后相关代码：
  `kernel/src/syscall/task.rs`
  `test-suit/starryos/normal/bug-sched-affinity-pid`

### 问题现象

修复前，StarryOS 在 affinity 相关 syscall 上没有正确处理传入的 `pid`：

- `sched_getaffinity(pid != 0)` 直接返回错误，无法查询其他任务的 CPU affinity
- `sched_setaffinity(pid)` 忽略传入的 `pid`，总是修改当前任务的 affinity

这意味着用户态虽然传入了目标任务 pid，但内核没有按语义操作对应任务。

从行为上看，这个问题会让用户态程序遇到两种明显异常：

- 想查询子进程或其他线程的 affinity 时，`sched_getaffinity()` 明明给了合法 pid，却直接失败
- 想修改指定任务 affinity 时，调用表面上看似成功，但真正被修改的是当前任务自己

这两种异常组合在一起，会让用户态完全无法正确使用“跨任务设置/查询 affinity”这组接口。

例如，一个父进程 `fork()` 出子进程后，希望：

- 把父进程固定在 CPU0
- 把子进程固定在 CPU1
- 再分别验证父子进程的 affinity 是否不同

旧实现下，这个流程会被破坏：

- 对 child 调用 `sched_setaffinity(child_pid, ...)` 实际改的是 parent 自己
- 随后对 child 调用 `sched_getaffinity(child_pid, ...)` 又直接报错

结果就是，接口参数虽然写着“目标 pid”，但系统的真实行为既不能查询目标任务，也不能修改目标任务。

### 为什么这是 bug

- 按 Linux 语义，`pid == 0` 表示当前任务；`pid != 0` 时应作用于指定目标任务。
- 原实现把“当前任务”和“指定任务”混为一谈，导致接口语义错误。
- 这不仅会让用户态读到错误结果，还会把 affinity 改到错误的任务上。

这类错误的严重性在于，它破坏的不是某个边角行为，而是 syscall 最核心的参数语义。

对 `sched_getaffinity()` / `sched_setaffinity()` 来说，`pid` 就是接口中最重要的选择目标参数：

- `pid == 0` 是特殊约定，表示“当前任务”
- `pid != 0` 则表示“显式指定的另一个任务”

如果内核忽略或错误处理这个参数，那么整个 syscall 表面上还存在，实际却已经不再满足其定义。

这会带来三方面问题：

- 语义错误：接口名和参数含义与 Linux 不一致
- 正确性错误：修改和查询落到了错误对象上
- 可测试性错误：用户态测例无法构造“父子任务不同 affinity”的基本场景

换句话说，这不是“支持得不完整”，而是“接口对外承诺和实际行为不一致”。

### 修复方式

- 根据 `pid` 查找目标任务，`pid == 0` 仍表示当前任务。
- `sched_getaffinity()` 返回目标任务真实 `cpumask`。
- `sched_setaffinity()` 将非空 CPU mask 设置到目标任务。
- 对当前任务仍使用 `set_current_affinity()`，保留现有迁移逻辑。
- 对其他任务则直接更新其 `cpumask` 并触发 `interrupt()`。
- 在 `test-suit/starryos/normal/bug-sched-affinity-pid` 中补充用户态 C 测例。

修复时，核心原则是先把“目标任务选择”这一步做对，再分别处理“当前任务”和“其他任务”的更新路径。

具体来说：

- 先统一解析 `pid`
- 如果 `pid == 0`，沿用当前任务路径
- 如果 `pid != 0`，先查找到对应目标任务，再对该任务执行 get/set 操作

这样修改后，`get` 和 `set` 两个 syscall 都重新获得了正确的目标选择语义。

之所以对当前任务和其他任务采用不同更新策略，是因为两者的运行语境不同：

- 当前任务修改 affinity 时，可能需要立刻处理与当前执行 CPU 相关的迁移逻辑，因此继续复用现有的 `set_current_affinity()`
- 其他任务并不在当前控制流上运行，可以直接更新其 `cpumask`，再通过 `interrupt()` 触发后续调度响应

这使修复既保持了原有当前任务路径的调度语义，又把指定 pid 的行为补齐到正确状态。

同时，用户态测例也专门构造了“父进程和子进程 affinity 不同”的场景，确保测试不是只覆盖“当前任务”这个最简单分支，而是真正覆盖：

- 指定目标任务的 `set`
- 指定目标任务的 `get`
- 当前任务不应被误修改

### Docker 验证

验证使用 `starryos-dev:ubuntu-qemu10.2.1` 镜像完成。

```bash
docker run -d --name starry-affinity-pid-validate -v "$PWD":/workspace -w /workspace \
  starryos-dev:ubuntu-qemu10.2.1 sh -lc 'sleep infinity'

docker exec starry-affinity-pid-validate sh -lc '
set -e
export PATH=/opt/rustup/toolchains/nightly-2026-02-25-aarch64-unknown-linux-gnu/bin:$PATH
export RUSTUP_TOOLCHAIN=nightly-2026-02-25-aarch64-unknown-linux-gnu
cargo fmt --manifest-path /workspace/Cargo.toml --all
cargo check -p starry-kernel --all-targets
cargo xtask starry test qemu -t x86_64 -c bug-sched-affinity-pid
'
```

预期结果：

- 旧实现下，同一测例失败，并打印：
  `TEST FAILED: get child affinity: Operation not permitted`
- 修复后，同一测例通过，并打印：
  `TEST PASSED`

## 附加说明

- 以上 3 个 bug 均已对应上游 `rcore-os/tgoskits` 的已 merge PR。
- 其中 Bug 2 和 Bug 3 都补充了符合课程要求的用户态 C 测例。
- 若后续继续修复新的 StarryOS bug，应继续按“一个小 PR + 可复现用户态测例 + base fail / PR pass 验证”的方式追加记录。
