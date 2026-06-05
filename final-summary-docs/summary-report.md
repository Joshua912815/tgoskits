# BigLab 最终总结报告

**作者**：Joshua912815

**日期**：2026-06-05

## 1. 概述

本报告总结我在本阶段围绕 ArceOS/StarryOS 完成的系统开发、工具建设、上游 PR 和课程展示工作。整体目标不是只完成若干独立实验，而是把 StarryOS 从“能启动、能跑简单测试”的状态，继续推进到能够承载更真实的 Linux 用户态程序、真实 syscall 语义、外设驱动路径和 K230 KPU/NNCase runtime 演示。

我的工作主线可以分成五部分：

```text
任务一：ArceOS 基础实验
  -> printcolor / hashmap / altalloc / ramfs rename / mmap

任务二-1：starry-evolve
  -> Linux Docker vs StarryOS QEMU 对拍、结构化 verifier、状态记录

StarryOS bugfix/syscall upstream PR
  -> signal、procfs affinity、sched affinity、sync/syncfs、waitid、inotify 等

任务二-4：真实应用和工具适配
  -> PicoClaw offline/online agent/gateway/interactive 演示

任务二-4：K230 KPU/NNCase
  -> QEMU K230 启动、/dev/kpu、54 条 KPU command、NNCase runtime
```

详细材料已归档在本目录下：

- [任务一 ArceOS tutorial](task1-arceos-tutorial/report_task1.md)
- [starry-evolve 框架文档](task2-1-starry-evolve/README.md)
- [inotifywait 技术文档](task2-2-inotifywait/pr-894-inotifywait-technical-doc.md)
- [StarryOS bugfix/syscall PR 报告](reports/starryos-bugfix-syscall-pr-report.md)
- [PicoClaw 技术报告](task2-4-picoclaw/PICOCLAW_TECHNICAL_REPORT.md)
- [K230 KPU 适配报告](task2-4-kpu-support-for-starry/k230-kpu-qemu-adaptation.md)
- [K230 NNCase runtime 阶段证据](task2-4-kpu-support-for-starry/k230-kpu-nncase-runtime-evidence.md)

## 2. 任务一：ArceOS 基础实验

任务一的目标是完成 `tg-arceos-tutorial` 中五个基础 exercise。它们覆盖了 ArceOS 的标准库、内存分配、文件系统和系统调用模拟层，是后续 StarryOS 工作的基础。

| 实验 | 主要内容 | 结果 |
| --- | --- | --- |
| `exercise-printcolor` | 在 `println!` 输出中加入 ANSI SGR 转义序列，实现绿色高亮输出 | 四架构通过 |
| `exercise-hashmap` | 通过 Cargo patch 在 `axstd::collections` 中导出 `HashMap`/`HashSet` | 四架构通过 |
| `exercise-altalloc` | 实现双端 bump allocator，字节分配低地址增长，页分配高地址增长 | 四架构通过 |
| `exercise-ramfs-rename` | 在 VFS 层和 ramfs 层补齐 `rename`，处理 mount point 和跨设备检测 | 四架构通过 |
| `exercise-sysmap` | 实现 `SYS_MMAP`，包含参数校验、地址分配、页表映射和文件数据写入 | 四架构通过 |

这部分工作让我先把 ArceOS 的模块化结构串起来：`axstd` 负责面向应用的标准库接口，`axalloc` 通过 trait 抽象分配器，`axfs`/`axfs_ramfs` 通过 VFS 分层处理路径和目录项，`axmm` 封装地址空间和页表操作，syscall emulation 层则把 Linux 用户程序的系统调用接入 ArceOS 内核能力。

验证方式上，我在 Docker 镜像 `starryos-dev:ubuntu-qemu10.2.1` 中完成 riscv64、x86_64、aarch64、loongarch64 四架构测试。loongarch64 曾暴露出 arm64 容器中交叉编译器运行时库不匹配的问题，排查后通过补齐 amd64 libc 运行环境解决。这个过程也让我意识到，系统实验中的失败不一定来自内核代码本身，工具链、QEMU、容器架构也都可能成为真实 blocker。

## 3. 任务二-1：starry-evolve 框架

`starry-evolve` 是我整理的一套面向 StarryOS syscall 持续改进的自动化框架。它的目标不是让 AI 随意修改内核，而是把“发现问题、定义契约、生成测试、Linux 对拍、StarryOS 验证、记录状态”变成可复现的工程流程。

框架的核心原则是：确定性工具负责给出事实，AI 只参与解释、决策和补丁编写。当前框架包含以下关键机制：

- `syscall_audit.py` 扫描 syscall 分发表和 handler，实现 IMPLEMENTED/PARTIAL/STUB 分类。
- `stub_scanner.py` 查找 `warn!("dummy")`、`todo!()`、`ENOSYS` 等桩实现痕迹。
- `test_runner.py` 负责 Linux Docker 与 StarryOS QEMU 的 JSONL 对拍。
- `baseline.json` 按 syscall/target/case 保存上一次通过基线，避免把已知通过项重新误判。
- `reports/latest.json` 记录两端命令、退出码、contract hash、源码 hash、二进制 hash、git diff hash 和 raw log hash。
- `evolve.py record` 只接受 verifier report 派生出的 VERIFIED 状态，防止手写状态污染。

当前可展示闭环是 `syncfs` 在 x86_64 上的 Linux Docker vs StarryOS QEMU 对拍。测试程序在两端输出包含 `run_id`、`case_id`、`ret`、`errno`、`observable`、`checksum` 的 JSONL，verifier 按 case 比较输出，而不是相信终端里出现的 `PASS` 字符串。

这部分工作的收获是：AI 辅助内核开发最重要的不是“让模型更大胆”，而是把信任边界收紧。测试是否通过必须由工具判定，契约和报告必须有 hash 绑定，状态流转必须能回溯到真实命令和真实日志。

## 4. StarryOS bugfix 与 syscall 增量

除了专项任务，我还向 upstream `rcore-os/tgoskits` 提交了一组与 StarryOS BUG 修复和 syscall/兼容能力补齐相关的 PR。按照当前归档报告统计，纳入本报告范围的 PR 共 12 个，其中已合入 10 个，关闭未合入 2 个；关闭项中 #225 后续由 #267 收敛合入，#475 是 BusyBox `/proc` 兼容尝试。

| PR | 状态 | 内容 |
| --- | --- | --- |
| #224 | 已合入 | 修复 signal check 屏蔽位的线程间串扰 |
| #267 | 已合入 | 修复 `/proc/[pid]/status` CPU affinity 固定为 CPU0 |
| #276 | 已合入 | 修复 `sched_getaffinity`/`sched_setaffinity` 对 `pid` 参数的处理 |
| #659 | 已合入 | 将 `sync()` 从 stub 改为真实 VFS flush |
| #660 | 已合入 | 将 `syncfs(fd)` 改为按 fd 所在文件系统执行 sync |
| #689 | 已合入 | 为 PicoClaw/Go DNS 路径兼容 `setsockopt(SO_BROADCAST)` |
| #776 | 已合入 | 修复 readline/TUI 被 `ESC[6n` 光标位置查询阻塞 |
| #780 | 已合入 | 为 `prctl(PR_SET_VMA, PR_SET_VMA_ANON_NAME)` 提供 silent no-op |
| #781 | 已合入 | 实现 `waitid()` syscall |
| #894 | 已合入 | 实现 inotify 基础模型并支持 `inotifywait` |

这些 PR 的共同特点是：它们大多不是“从零实现一个孤立接口”，而是围绕真实用户程序暴露出的 Linux 兼容差异做最小、可验证的内核补齐。例如：

- `/proc/[pid]/status` affinity 修复要求 procfs 输出与调度层真实 `cpumask` 一致。
- `sched_*affinity` 修复要求 `pid == 0` 和指定 pid 两种路径都符合 Linux 语义。
- `sync()`/`syncfs(fd)` 修复把“存在但无效果”的 stub 改成真实 VFS 同步。
- `PR_SET_VMA_ANON_NAME` 采用 silent no-op，是为了兼容 Go runtime 的常见调用路径，而不是提前引入完整 VMA name 管理。
- `waitid()` 补齐了 Go `os/exec` 等工具执行路径对进程等待的依赖。
- TTY cursor report 修复让 readline 能收到 `ESC[1;1R` 形式的光标位置响应，解决 PicoClaw 交互模式阻塞。

其中 #894 的 inotify 支持是 syscall 增量里较完整的一项。它实现了 `inotify_init1`、`inotify_add_watch`、`inotify_rm_watch`，并补齐了 inotify fd 的 `read`、`poll`、`ioctl(FIONREAD)` 行为。文件系统事件通过全局 inotify 实例表投递，当前支持 `IN_MODIFY`、`IN_CREATE`、`IN_CLOSE_WRITE`、`IN_DELETE`、`IN_DELETE_SELF`、`IN_IGNORED` 和 `IN_ISDIR` 等基础事件。验证上新增了 `inotifywait` 测试组，在 StarryOS guest 内安装 `inotify-tools` 并运行真实 `inotifywait` 命令。

这一组 upstream 工作让我对“Linux 兼容”有了更具体的认识：真正困难的地方往往不是 syscall 编号是否存在，而是错误码、阻塞行为、fd 对象语义、procfs 文本格式、终端协议和用户态库隐含假设是否足够接近 Linux。

## 5. 任务二-4：PicoClaw 支持

PicoClaw 支持的目标是验证一个真实 Go/AI CLI 程序能否在 StarryOS x86_64 QEMU 中运行。它不是默认 CI 的一部分，而是一个 opt-in 的真实应用验证样例。工作分成四个 phase：

| Phase | 目标 | 成功标记 |
| --- | --- | --- |
| Phase 1 | 离线 smoke，验证静态 Linux x86_64 PicoClaw 二进制可启动并执行本地 CLI | `STARRY_PICOCLAW_OFFLINE_PASSED` |
| Phase 2 | 在线 agent，注入 API key、代理和 CA 后完成一次模型请求 | `STARRY_PICOCLAW_AGENT_PASSED` |
| Phase 3 | Gateway 服务，在 guest 中启动 HTTP 服务并响应 `/health` | `STARRY_PICOCLAW_GATEWAY_PASSED` |
| Phase 4 | 交互式 agent，修复 TTY/readline 后支持多轮输入和 `exit` 退出 | 手动验证 `picoclaw agent` 多轮对话 |

这项工作实际解决了几类问题：

1. rootfs 注入问题：PicoClaw 二进制、launcher、配置、CA 和安全凭证都需要注入 Alpine rootfs，而不是安装到 Docker 容器本身。
2. 在线请求问题：Go DNS 路径需要 `setsockopt(SOL_SOCKET, SO_BROADCAST)` 返回成功，因此补齐为 no-op 兼容。
3. Gateway 端口转发问题：axbuild 自动补丁 QEMU 参数时不能覆盖已有 `hostfwd`，因此修复了 `-netdev id=net0` 的合并逻辑。
4. readline 交互问题：StarryOS 串口 tty 原本不响应 `ESC[6n`，导致交互式 PicoClaw 卡住；修复后注入合法光标位置响应。
5. Go 子进程等待问题：gateway/tool 执行路径需要 `waitid()`，因此新增了对应 syscall。

PicoClaw 这条线的价值在于，它把 syscall、终端、网络、rootfs、QEMU 参数和真实应用行为串在一起。只跑一个单元测试很难暴露这些问题，但真实 CLI 程序会把多个子系统的缺口连续触发出来。

## 6. 任务二-4：K230 KPU 与 NNCase runtime

K230 KPU/NPU 支持是本阶段技术跨度最大的一条线。它的目标是让 StarryOS 在 QEMU K230 machine 上具备 KPU 设备发现、设备节点、ioctl/mmap、IRQ 等待、真实 command 承载和 NNCase runtime 演示能力。

### 6.1 QEMU K230 与 `/dev/kpu`

第一阶段完成的是 K230 QEMU 基础适配：

- StarryOS 可以在 QEMU `-machine k230` 上启动。
- 通过 FDT/`plat-dyn` 发现 `canaan,k230-kpu` 节点。
- devfs 暴露 `/dev/kpu` 和 `/dev/kpu0`。
- `drivers/npu/k230-kpu` 封装 KPU CFG MMIO、L2 memory、command range、done status 等寄存器级操作。
- 用户态 UAPI 头文件提供 ioctl 常量、mmap offset、寄存器 offset 和 ABI 结构。
- `/dev/kpu` 支持 `KPU_IOC_GET_INFO`、`KPU_IOC_RUN`、`KPU_IOC_WAIT_DONE`、`KPU_IOC_GET_IRQ_COUNT`、CFG/L2 mmap 等接口。
- `kpu-smoke` 可以验证 KPU 信息、MMIO、fake output side effect、runtime arg table、runtime DDR mirror 和 IRQ 计数。

这一步的意义是把 K230 KPU 从 QEMU 设备模型接到 StarryOS 用户态 ABI 上，形成后续 runtime 的基础。

### 6.2 kunOS/RT-Smart 对标与 54 条 command replay

为了明确“达到 zevorn/kunOS 水平”具体意味着什么，我先复现了 kunOS 预构建 big-core RT-Smart 中的 YOLOv8n 路线：`/bin/object_detect_yolov8n/ob_det.elf yolov8n_320.kmodel 0.15 0.2 bus.jpg 0`。在 QEMU K230 中抓到了 54 次 `k230_kpu_start` 和 54 次 `k230_kpu_gnne_summary`，并通过 debug=1 日志确认 `OBDet run`、`OBDet get_output`、`OBDet post_process` 均已完成。

随后我把官方 RT-Smart runtime 运行中每次 KPU submit 前的 low16m/L2/DDR snapshot 转换成 StarryOS 可复放的 `yolov8n-full-sequence-delta.krun`。StarryOS `kpu-smoke` 复放完整 54 条真实 KPU command，观察到 `runtime_image kunos_yolov8n_full_sequence_delta runs=54`、IRQ `0->54` 和 `KPU_SMOKE_PASS`。

这条 replay 路线不是最终目标，但它证明 StarryOS 的 `/dev/kpu`、mmap、IRQ、QEMU KPU 模型和真实 YOLOv8n command 序列之间可以闭环。

### 6.3 StarryOS 原生 NNCase runtime

在 replay 基础上，后续推进到更接近真实运行的 NNCase runtime 路线。当前已经完成：

- 使用官方 K230 SDK/NNCase 静态库构建 riscv64 用户态 demo。
- 使用 Linux riscv64-musl CRT/libc，避免官方 RT-Smart libc syscall ABI 与 Starry/Linux ABI 不兼容。
- 在 StarryOS guest 内加载真实 `yolov8n_320.kmodel`。
- 调用 `interpreter.load_model()` 和 `interpreter.run()`。
- NNCase runtime 在 guest 内现场生成并提交 54 条 KPU command。
- compat shim 将 runtime command 接到 StarryOS `/dev/kpu`，并完成 done/IRQ 等待。
- minimal demo 打印四个 output tensor hash 和 `NNCASE_MINIMAL_PASS`。
- image demo 完成 `bus.jpg` decode、CPU preprocess、run、output 读取、postprocess 路径，并打印 `YOLOV8N_DEMO_PASS`。
- test case 最终打印 `K230_NNCASE_RUNTIME_PASS`。

当前最关键的技术修正是：官方 `gnne_get_l2()` 固定返回 `0x80000000`，因此 Starry/Linux ABI 下必须 identity-map KPU L2 window；但低位 runtime/RDATA/direct I/O window 不能整体 identity-map，否则会破坏用户地址空间或 allocator。最终采用的是只 identity-map L2，低位 runtime 通过受限 mmap、runtime alias mirror 和 arg table patch 接住。

需要明确保留的边界是：当前已经证明 `.kmodel -> NNCase runtime -> 54 条 KPU command -> /dev/kpu -> done/IRQ -> output tensor hash` 发生在 StarryOS guest 内；但 YOLOv8n 检测框语义还没有与官方 RT-Smart reference 完全对齐。image demo 当前输出 tensor 非零，后处理管线可执行，但 `detections=0`，因此不能宣称已经验证最终检测精度。

### 6.4 Starry app 与展示脚本

为了让 K230 NNCase runtime 更适合展示，我还整理了 `apps/starry/k230-kpu-nncase`：

- 提供面向使用者的 README。
- 提供构建预编译 guest 二进制的脚本。
- 支持 `cargo xtask starry app qemu -t k230-kpu-nncase --arch riscv64` 运行。
- 提供 `demo-teacher.sh`，用于现场流式展示日志和证据摘要。

这让 KPU 工作不只停留在测试目录中，也能以 Starry app 的形式被老师或同学复现。

## 7. 实验验证方式

本阶段验证方式主要分成四类：

1. ArceOS 基础实验使用四架构 QEMU 运行，确保每个 exercise 不只在单架构上通过。
2. StarryOS bugfix/syscall PR 使用单元测试、`cargo xtask clippy`、`cargo xtask starry test qemu` 和真实用户态程序 smoke 组合验证。
3. `starry-evolve` 使用 Linux Docker vs StarryOS QEMU 的 JSONL 对拍，避免用肉眼判断终端输出。
4. K230 KPU 使用 QEMU trace、`.krun` replay、`kpu-smoke`、`kpu-nncase-runtime` 和 Starry app 演示脚本分层验证。

这种验证方式的共同点是：尽量让每个结论有可复现命令、可匹配成功标记和可保存日志。对于 KPU 这种复杂路径，我特别注意把“已经完成”和“尚未完成”分开写清楚，避免把 replay、runtime、检测框语义三个层级混在一起。

## 8. 成果总结

本阶段最终产出包括：

- 完成 ArceOS 五个基础 exercise，并通过多架构验证。
- 建立 `starry-evolve` 框架，整理出 syscall 审计、契约、测试、verifier、baseline 和 journal 的闭环。
- 整理并提交 StarryOS bugfix/syscall 相关 upstream PR，其中 10 个已合入。
- 实现并验证 inotify 基础模型，使 `inotifywait` 可以在 StarryOS 中运行。
- 完成 PicoClaw offline、online agent、gateway 和交互式使用路径，并通过真实应用暴露并修复 StarryOS 兼容问题。
- 完成 K230 QEMU/KPU 基础适配，提供 `/dev/kpu`、driver crate、UAPI、smoke test。
- 从 kunOS/RT-Smart reference 提取并在 StarryOS 中复放 54 条真实 YOLOv8n KPU command。
- 在 StarryOS guest 内跑通官方 K230 SDK/NNCase runtime 产物，完成真实 `.kmodel` 加载、54 条 KPU command 现场生成、done/IRQ 和 output tensor hash。
- 归档最终汇报 slide、任务文档、技术报告和 PR 报告。

## 9. 个人反思

这次 BigLab 最大的收获是，我对“系统可用性”的理解从接口层推进到了生态层。一个系统调用返回 `0` 不等于兼容 Linux，一个设备节点存在不等于真实程序能跑，一个模型 command 能复放也不等于 runtime 语义已经完全对齐。用户态程序真正依赖的是一整套隐含契约：fd 行为、errno、procfs 文本、TTY 控制序列、QEMU 参数、rootfs 内容、mmap 地址布局、驱动中断语义都会影响最终结果。

AI 辅助开发方面，我的认识也更务实了。AI 适合做重复执行、检索、补丁草稿和测试补齐；但信任边界必须由确定性工具守住。尤其是在内核开发里，不能让“看起来通过”的输出替代 verifier，不能让手写状态替代真实报告，也不能让模型的解释替代 Linux 对拍和 QEMU 日志。

K230 KPU 这条线让我体会到复杂系统适配中的分层推进价值。先跑通 QEMU K230 启动和 `/dev/kpu`，再做 fake output 和 runtime arg table smoke，再做 kunOS 54 条 command replay，最后推进 NNCase runtime。每一步都不是最终目标，但每一步都缩小了未知范围，也让后续定位问题更有依据。
