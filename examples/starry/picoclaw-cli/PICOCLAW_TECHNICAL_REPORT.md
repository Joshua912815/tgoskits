# StarryOS PicoClaw 移植支持技术文档

> 本文档基于 tgoskits 仓库中的实际文件、PR、commit 和测试记录整理，适合作为课程报告或答辩材料使用。

---

## 一、PicoClaw 功能演示命令

本节整理从零开始演示 StarryOS 上 PicoClaw 功能的完整命令流程，分为 Mac host、Docker 容器、StarryOS QEMU guest 三层。

### 1.1 进入隔离仓库

```bash
cd /Users/joshua/tmp/tgoskits-picoclaw
git status
# 确认在 codex/picoclaw-latest-support 分支上
```

### 1.2 启动 Docker 开发环境

StarryOS 构建和 QEMU 运行需要在 Linux 环境中进行。Mac 用户通过 Docker 容器完成：

```bash
docker run -it --rm \
  -v "$(pwd)":/mnt \
  -w /mnt \
  starryos-dev:ubuntu-qemu10.2.1
```

容器内需确认以下工具可用：

```bash
command -v debugfs        # ext4 rootfs 文件注入
command -v qemu-system-x86_64  # QEMU 模拟器
command -v cargo           # Rust 构建工具
```

### 1.3 准备 PicoClaw rootfs

#### 1.3.1 离线 rootfs

离线 rootfs 仅包含 PicoClaw 二进制，不需要 API key：

```bash
examples/starry/picoclaw-cli/prepare_picoclaw_rootfs.sh
```

脚本会自动：
- 下载 PicoClaw `v0.2.8` Linux x86_64 release tarball（`sipeed/picoclaw` GitHub release）
- 校验 SHA-256（`e35aea853711db829e0d1969d875f2efcca9cfeec92a43dedb84b46a56b890be`）
- 将 `picoclaw` 和 `picoclaw-launcher` 注入到 Alpine rootfs 的 `/usr/local/bin/`
- 输出：`tmp/axbuild/rootfs/rootfs-x86_64-picoclaw.img`

#### 1.3.2 在线 rootfs

在线 rootfs 额外包含 API 配置、安全凭证和代理设置：

```bash
PICOCLAW_API_KEY=sk-... \
examples/starry/picoclaw-cli/prepare_picoclaw_rootfs.sh \
  --output-rootfs tmp/axbuild/rootfs/rootfs-x86_64-picoclaw-online.img \
  --proxy http://10.0.2.2:7890
```

**Mimo API 配置说明：**

默认在线配置使用 Mimo OpenAI-compatible 端点：

| 配置项 | 值 |
|--------|-----|
| model_name | mimo-v25 |
| provider | openai |
| model | mimo-v2.5 |
| api_base | https://token-plan-cn.xiaomimimo.com/v1 |
| enable_thinking | false |

**`enable_thinking=false` 的原因：** `mimo-v2.5` 默认进入 thinking/reasoning 模式，返回 `reasoning_content` 字段。PicoClaw 当前的 OpenAI-compatible 调用链没有回传该字段，导致请求失败（400 错误）。脚本会自动在 `config.json` 中注入：

```json
"extra_body": {
  "chat_template_kwargs": {
    "enable_thinking": false
  }
}
```

**API key 注入方式：**

脚本按优先级读取：`PICOCLAW_API_KEY` > `--api-key` 参数 > `OPENAI_API_KEY` > `ANTHROPIC_AUTH_TOKEN`。当使用 `ANTHROPIC_AUTH_TOKEN` 时，脚本默认生成 Anthropic Messages 配置，并读取 `ANTHROPIC_BASE_URL` 作为 `api_base`。

**注意：不要把真实 API key 写入文档或提交到仓库。rootfs 镜像中包含密钥，需保持本地。**

### 1.4 离线 smoke 演示

```bash
cargo xtask starry qemu \
  --arch x86_64 \
  --qemu-config examples/starry/picoclaw-cli/qemu-x86_64-picoclaw-offline.toml \
  --rootfs tmp/axbuild/rootfs/rootfs-x86_64-picoclaw.img
```

Guest 内自动执行：`picoclaw version`、`picoclaw --help`、`picoclaw onboard`、`picoclaw status`。

**成功标记：**

```
STARRY_PICOCLAW_OFFLINE_PASSED
```

### 1.5 在线 Agent smoke 演示

```bash
cargo xtask starry qemu \
  --arch x86_64 \
  --qemu-config examples/starry/picoclaw-cli/qemu-x86_64-picoclaw-agent.toml \
  --rootfs tmp/axbuild/rootfs/rootfs-x86_64-picoclaw-online.img
```

Guest 内自动执行 `picoclaw agent -m 'Reply with exactly: STARRY_PICOCLAW_AGENT_OK'`，以及多轮中文闲聊。

**成功标记：**

```
STARRY_PICOCLAW_AGENT_OK
STARRY_PICOCLAW_AGENT_PASSED
```

### 1.6 Gateway smoke 演示

```bash
cargo xtask starry qemu \
  --arch x86_64 \
  --qemu-config examples/starry/picoclaw-cli/qemu-x86_64-picoclaw-gateway.toml \
  --rootfs tmp/axbuild/rootfs/rootfs-x86_64-picoclaw-online.img
```

Guest 内自动启动 `picoclaw gateway --allow-empty --host 127.0.0.1`，然后用 `curl` 请求 `/health`。

**成功标记：**

```
STARRY_PICOCLAW_GATEWAY_PASSED
```

**Health 响应示例：**

```json
{"status":"ok","uptime":"55.827136ms","pid":15}
```

### 1.7 交互式长期使用

```bash
PICOCLAW_API_KEY=... examples/starry/picoclaw-cli/run_picoclaw_interactive.sh
```

脚本默认创建或复用 `tmp/axbuild/rootfs/rootfs-x86_64-picoclaw-user.img`，启动不带自动退出条件的 StarryOS shell。

进入 StarryOS 后可执行：

```bash
# 查看 PicoClaw 状态
picoclaw status

# 查看当前模型
picoclaw model

# 单轮请求
picoclaw agent -m "你好，请用一句话介绍你自己"

# 进入交互模式（支持多轮对话，输入 exit 退出）
picoclaw agent

# 启动 gateway 服务
picoclaw gateway --allow-empty --host 127.0.0.1 --port 18790
```

交互式 QEMU 默认把 guest 的 `18790` 端口转发到宿主机。启动 gateway 后，宿主机可以访问：

```bash
curl http://127.0.0.1:18790/health
```

退出 QEMU 使用 `Ctrl-a x`。

### 1.8 便捷演示脚本

如果要从 Docker 环境开始，逐步演示 PicoClaw 在线对话全过程：

```bash
PICOCLAW_API_KEY=... examples/starry/picoclaw-cli/demo_picoclaw_agent.sh
```

脚本会逐步暂停展示：
1. Docker 检查
2. 在线配置展示
3. rootfs 准备
4. StarryOS QEMU 启动
5. 一次可验收请求 + 多次 PicoClaw agent 闲聊

**成功时看到：**

```
STARRY_PICOCLAW_AGENT_OK
STARRY_PICOCLAW_AGENT_PASSED
```

### 1.9 微信 Gateway 演示流程

> 注意：以下流程基于 PicoClaw CLI 已有命令整理，不要写入真实账号、二维码、token 或 API key。

1. 在交互式 StarryOS 中启动 gateway：
   ```bash
   picoclaw gateway --allow-empty --host 127.0.0.1 --port 18790
   ```

2. PicoClaw 支持通过微信 channel 接收和回复消息。登录流程涉及：
   - 在 PicoClaw 配置中设置微信 channel
   - 启动 gateway 后通过微信扫码或账号登录
   - 登录成功后，微信消息会触发 PicoClaw agent 进行回复

3. 由于 StarryOS 当前环境限制（网络、长时间运行稳定性等），微信 channel 的完整演示仍需进一步验证。

---

## 二、四个 Phase 做了什么

### Phase 1：离线 Smoke

**目标：** 验证静态 Linux x86_64 PicoClaw 二进制能在 StarryOS x86_64 QEMU 中启动、写入配置并执行本地 CLI 命令。

**新增文件：**

| 文件 | 作用 |
|------|------|
| `prepare_picoclaw_assets.sh` | 下载/复用 PicoClaw release 资产，校验 SHA-256 |
| `prepare_picoclaw_rootfs.sh` | 构建 rootfs，注入 PicoClaw 二进制和可选配置 |
| `qemu-x86_64-picoclaw-offline.toml` | 离线 smoke QEMU 配置 |
| `qemu-x86_64-picoclaw-agent.toml` | 在线 agent smoke QEMU 配置（Phase 2 使用） |
| `qemu-x86_64-picoclaw-gateway.toml` | Gateway smoke QEMU 配置（Phase 3 使用） |
| `README.md` | 使用文档 |

**验证命令：**

```bash
cargo xtask starry qemu \
  --arch x86_64 \
  --qemu-config examples/starry/picoclaw-cli/qemu-x86_64-picoclaw-offline.toml \
  --rootfs tmp/axbuild/rootfs/rootfs-x86_64-picoclaw.img
```

**成功标记：** `STARRY_PICOCLAW_OFFLINE_PASSED`

**解决的问题：**

1. **QEMU config schema 不匹配**：`success_regex` 和 `fail_regex` 必须是数组格式，单个字符串会导致 TOML 解析失败。
2. **rootfs 注入 debugfs 临时文件**：`debugfs.cmds` 原先放在 overlay 目录内，被误注入为 guest 文件。已移到 overlay 外。
3. **PicoClaw 二进制被注入为 FIFO**：debugfs mode 命令使用 `010%s` 产生 `010755`（FIFO），改为 `0100%s` 产生 `0100755`（regular file）。
4. **Non-blocking 警告**：`sys_prctl: unsupported option` 和 `Unsupported ioctl command: 21505` 不阻塞离线操作，留作后续 phase 观察点。

---

### Phase 2：在线 Agent

**目标：** 注入 API key、代理和 CA 后，验证 `picoclaw agent -m ...` 能完成一次真实模型请求。

**Mimo API 配置：**

默认使用 OpenAI-compatible 端点：

```text
provider  = openai
model     = mimo-v2.5
api_base  = https://token-plan-cn.xiaomimimo.com/v1
```

**`enable_thinking=false` 的原因：**

`mimo-v2.5` 默认进入 thinking/reasoning 模式，返回 `reasoning_content` 字段。PicoClaw 的 OpenAI-compatible 调用链没有回传该字段，服务端收到不完整的 reasoning 响应后返回 400 错误。通过在 `extra_body` 中设置 `enable_thinking: false`，告知模型不进入推理模式。

**API key / CA / proxy 注入方式：**

- API key：通过环境变量 `PICOCLAW_API_KEY` 传入，脚本生成 `/root/.picoclaw/.security.yml`（权限 0600）
- CA 证书：注入 host 的 `SSL_CERT_FILE` 或默认 `/etc/ssl/certs/ca-certificates.crt` 到 rootfs
- 代理：通过 `--proxy` 参数注入 `http_proxy`/`https_proxy`/`all_proxy` 环境文件到 `/root/.picoclaw/starry-online-env`

**验证命令：**

```bash
cargo xtask starry qemu \
  --arch x86_64 \
  --qemu-config examples/starry/picoclaw-cli/qemu-x86_64-picoclaw-agent.toml \
  --rootfs tmp/axbuild/rootfs/rootfs-x86_64-picoclaw-online.img
```

**成功标记：** `STARRY_PICOCLAW_AGENT_OK` 和 `STARRY_PICOCLAW_AGENT_PASSED`

**遇到的问题及定位：**

1. **成功标记误触发**：Guest shell 回显命令时包含 `echo STARRY_PICOCLAW_AGENT_PASSED`，在 agent 请求完成前就匹配了 `success_regex`。修复：改用 `printf 'STARRY_%s\n' PICOCLAW_AGENT_PASSED`，使回显不包含完整 token。
2. **`tee` 掩盖退出码**：agent 命令通过 `tee` 管道输出时，管道退出码可能是 `tee` 的成功而非 `picoclaw agent` 的失败。修复：改为先写文件再检查退出码。
3. **Go DNS `setsockopt` 失败**：`dial udp 10.0.2.3:53: setsockopt: protocol not available`。Go 在 DNS 设置时启用 `SO_BROADCAST`，StarryOS 原先返回 `ENOPROTOOPT`。修复：在 `sys_setsockopt` 中接受 `SOL_SOCKET/SO_BROADCAST` 作为 no-op。
4. **Anthropic 端点不适用**：`provider = "anthropic"` 使用了 `/chat/completions` 路径收到 404；`provider = "anthropic-messages"` 请求可达但默认 Claude 模型不受支持。最终确认使用 OpenAI-compatible 根路径 `/v1` 配合 `mimo-v2.5` 模型。

**内核改动：**

- `os/StarryOS/kernel/src/syscall/net/opt.rs`：接受 `SO_BROADCAST` 为 no-op

---

### Phase 3：Gateway 服务

**目标：** 验证 `picoclaw gateway` 能在 StarryOS guest 中启动长时间运行的 HTTP 服务，并响应本地健康检查。

**`picoclaw gateway` 在 StarryOS 中的启动方式：**

```bash
picoclaw gateway --allow-empty --host 127.0.0.1 > /tmp/picoclaw-smoke/gateway.log 2>&1 &
gateway_pid=$!
```

`--allow-empty` 允许在无 channel 配置时启动，`--host 127.0.0.1` 绑定本地地址。

**`/health` 验证方式：**

```bash
curl -fsS http://127.0.0.1:18790/health
# 返回: {"status":"ok","uptime":"55.827136ms","pid":15}
```

如果 guest 中没有 `curl`，也支持 `busybox wget`。

**hostfwd / QEMU netdev 问题：**

Gateway 配置需要 `hostfwd=tcp::18790-:18790` 将 guest 端口转发到宿主机。但 axbuild 的 rootfs QEMU 参数补丁逻辑在检测到需要 netdev 时会生成默认 `-netdev user,id=net0`，与 gateway 配置中已有的 `hostfwd` 参数冲突，导致 QEMU 启动时报 duplicate netdev。

**修复：** `scripts/axbuild/src/rootfs/qemu.rs` 中，当检测到已有 `-netdev` 包含 `id=net0` 时，保留其所有选项（包括 `hostfwd`），仅补丁 drive 路径。

**交互式 rootfs 和长期使用脚本：**

- `qemu-x86_64-picoclaw-interactive.toml`：`timeout = 0`，不设成功/失败 regex，保持 QEMU 持续运行
- `run_picoclaw_interactive.sh`：自动创建/复用 `rootfs-x86_64-picoclaw-user.img`，启动交互式 shell

**验证命令：**

```bash
cargo xtask starry qemu \
  --arch x86_64 \
  --qemu-config examples/starry/picoclaw-cli/qemu-x86_64-picoclaw-gateway.toml \
  --rootfs tmp/axbuild/rootfs/rootfs-x86_64-picoclaw-online.img
```

**成功标记：** `STARRY_PICOCLAW_GATEWAY_PASSED`

---

### Phase 4：TTY/readline 交互修复

**目标：** 让裸 `picoclaw agent` 能直接读取键盘输入，完成多轮对话并用 `exit` 退出。

**裸 `picoclaw agent` 为什么会卡住：**

PicoClaw 的 readline 层在初始化交互终端时输出 ANSI 光标位置查询 `ESC[6n`（Device Status Report），并等待终端回送形如 `ESC[row;colR` 的响应。StarryOS 的 QEMU 串口 tty 原先只把该序列输出到串口，没有生成回送数据，导致 readline 等待响应时阻塞。

**`cat | picoclaw agent` 为什么能工作：**

管道模式下，stdin 不是 tty，PicoClaw 不会进入 readline/raw terminal 初始化路径，而是直接从管道读取。这绕过了 ANSI 查询问题，但无法进行交互式输入。

**readline 为什么需要 ANSI cursor position response：**

readline 库在初始化 raw terminal 模式后，需要确定当前光标位置来管理行编辑缓冲区。它发送 `ESC[6n` 查询，等待终端回送 `ESC[row;colR`。如果永远收不到响应，readline 就会一直等待。

**StarryOS 具体修复了什么：**

1. **tty write 路径识别光标查询**（`os/StarryOS/kernel/src/pseudofs/dev/tty/mod.rs`）：
   - 定义常量 `ANSI_CURSOR_POSITION_REQUEST = b"\x1b[6n"` 和 `ANSI_CURSOR_POSITION_RESPONSE = b"\x1b[1;1R"`
   - 在 `write_at()` 中，当输出包含 `ESC[6n` 时，调用 `ldisc.inject_input(ANSI_CURSOR_POSITION_RESPONSE)` 注入响应
   - 新增 `contains_bytes()` 辅助函数用于字节序列搜索

2. **line discipline 注入输入队列**（`os/StarryOS/kernel/src/pseudofs/dev/tty/terminal/ldisc.rs`）：
   - 新增 `injected_input: VecDeque<u8>` 字段
   - `inject_input()` 方法：向队列追加字节并唤醒 `input_ready`
   - `read()` 方法：优先读取注入字节（在 ring buffer 之前）
   - `poll_read()` 方法：`injected_input` 非空时立即返回可读
   - `drain_input()` 方法：同时清空注入队列
   - 新增单元测试 `injected_input_is_readable_immediately`

**修复后如何验证：**

1. 自动化回归测试：
   ```bash
   cargo xtask starry test qemu --arch x86_64 -c bugfix
   ```
   新增 `bug-tty-cursor-report` 测试：C 程序在 raw terminal 模式下写出 `ESC[6n`，用 `poll()` 等待 stdin 可读，校验读到 `ESC[1;1R`。

2. 手动 PicoClaw 交互：
   - 运行 `picoclaw agent` 进入交互模式
   - 出现 `You:` 提示
   - 输入多轮消息并收到模型回复
   - 输入 `exit` 后打印 `Goodbye!` 并回到 shell

**当前边界：** 仅修复 `ESC[6n` 光标位置查询的最小响应。不是完整的终端模拟器。后续可扩展 arrow keys、Ctrl+C、Ctrl+D、多行编辑、长输出滚动等更丰富的终端行为。

---

## 三、相关 PR 和每个 PR 的内容

> 根据仓库和 GitHub 核对后的结果：Phase 1/2 实际是 PR #689，Phase 3 是 PR #775，Phase 4 是 PR #776。

---

### PR #689 — PicoClaw Phase 1/2 支持

- **链接：** https://github.com/rcore-os/tgoskits/pull/689
- **标题：** `feat(starry): add PicoClaw phase 1 and 2 support`
- **分支：** `codex/support-picoclaw` → `dev`
- **状态：** 已合并（2026-05-18）
- **主要 commit：**
  1. `chore: initialize picoclaw support branch`
  2. `feat(starry): add picoclaw phase 1 and 2 support`
  3. `ci: re-trigger`

#### 解决了什么问题

PicoClaw 是一个由 Go 语言编写的 AI 助手客户端，提供离线 CLI 和在线 agent 两种使用模式。在此 PR 之前，StarryOS 从未运行过 PicoClaw，完全不清楚它的 Linux ABI 依赖能不能被 StarryOS 满足。这个 PR 的核心目标是**建立第一条验证路径**：从下载 PicoClaw 二进制、注入 rootfs、到在 StarryOS QEMU 中实际运行——先用离线命令确认二进制能启动，再用在线 agent 确认网络请求能完成。

#### 具体是怎么解决的

**问题 1：rootfs 里根本没有 PicoClaw，怎么让它进去？**

StarryOS 的 rootfs 是一个 Alpine Linux 最小 ext4 镜像，里面只有 busybox。PicoClaw 的二进制和配置必须从外部注入。做法是编写 `prepare_picoclaw_rootfs.sh`，该脚本的核心流程：

1. 调用 `prepare_picoclaw_assets.sh` 下载 PicoClaw `v0.2.8` 的 Linux x86_64 release tarball，校验 SHA-256
2. 复制一份基础 Alpine rootfs 作为输出镜像
3. 在 overlay 临时目录中组装要注入的文件树：`/usr/local/bin/picoclaw`、`/usr/local/bin/picoclaw-launcher`、`/root/.picoclaw/config.json`、`/root/.picoclaw/.security.yml` 等
4. 生成 `debugfs` 命令脚本（先 `mkdir` 创建目录，再 `write` 写入文件，最后 `sif mode` 设置权限）
5. 用 `debugfs -w -f <cmds>` 将 overlay 原子写入 ext4 镜像

过程中踩了两个坑：
- **二进制被注入为 FIFO**：最初 `sif mode` 的格式串用 `010%s`，对于权限 `755` 产生 `010755`——在 ext4 inode 中这是一个 FIFO（命名管道），不是 regular file。Guest 中执行 `picoclaw` 直接 `Permission denied`。排查后改为 `0100%s`，产生 `0100755`（regular file + executable）。
- **临时命令文件被误注入**：`debugfs.cmds` 文件原先放在 overlay 目录内部，被通用文件遍历逻辑一起注入成了 guest 里的 `/debugfs.cmds`。修复：把临时文件移到 overlay 目录外部。

**问题 2：离线 smoke 的 QEMU 自动化怎么判断"成功"？**

需要让 QEMU 自动执行一系列 `picoclaw` 命令，然后通过 stdout 正则匹配判断通过与否。编写 `qemu-x86_64-picoclaw-offline.toml`，其中 `shell_init_cmd` 按顺序执行 `picoclaw version`、`picoclaw --help`、`picoclaw onboard`、`picoclaw status`，每步用 `tee` 记录输出并用 `grep -F` 检查关键字。全部通过后打印 `STARRY_PICOCLAW_OFFLINE_PASSED` 作为成功标记。

踩的坑：`success_regex` 和 `fail_regex` 在仓库的 ostool QEMU 配置格式中**必须是数组**。写成单个字符串会导致 TOML 解析失败，QEMU 根本不会启动。

**问题 3：在线 agent 第一次请求就失败了——Go DNS 直接崩溃**

离线 smoke 通过后，尝试在线 agent。`picoclaw agent -m '...'` 运行后立即报错：

```
dial udp 10.0.2.3:53: setsockopt: protocol not available
```

定位过程：Go 在做 DNS 解析前会对 UDP socket 调用 `setsockopt(SOL_SOCKET, SO_BROADCAST)`，这是 Go 标准库的固定行为。StarryOS 的 `sys_setsockopt` 不认识 `SO_BROADCAST` 这个选项，直接返回 `ENOPROTOOPT`（protocol not available）。Go 拿到错误后认为 socket 不可用，整个 DNS 解析流程终止。

修复方式：在 `os/StarryOS/kernel/src/syscall/net/opt.rs` 的 `setsockopt` 处理中，新增对 `SOL_SOCKET/SO_BROADCAST` 的识别。QEMU 用户态网络没有真正的广播需求，因此将其作为 **no-op** 处理——验证 int option value 合法后直接返回成功，不做任何实际操作。

**问题 4：API 配置试了好几种 provider 都不行**

初始尝试用 Anthropic 端点：
- `provider = "anthropic"`：PicoClaw 发请求到 `/chat/completions` 路径（OpenAI-style），但 Anthropic base URL 没有 这个路径，返回 404。
- `provider = "anthropic-messages"`：请求路径对了（`/messages`），但默认 Claude 模型不在 key 的可用范围内。

排查后确认该 key 的实际可用路径是 Mimo 的 OpenAI-compatible 根 `/v1`，模型 `mimo-v2.5`。但 mimo-v2.5 默认启用 thinking 模式，响应包含 `reasoning_content` 字段，PicoClaw 不会回传，导致 400 错误。最终方案：在 `config.json` 的 `extra_body.chat_template_kwargs` 中注入 `enable_thinking: false`，脚本通过 `should_disable_thinking()` 自动判断是否需要注入。

**问题 5：成功标记被 shell 回显误触发**

在线 agent 的 smoke 脚本中，`echo STARRY_PICOCLAW_AGENT_PASSED` 这条命令在 shell 回显（echo command）阶段就已经包含了完整的成功 token。ostool 的 `success_regex` 匹配到回显就认为通过了——实际上 agent 请求还没开始。修复：改用 `printf 'STARRY_%s\n' PICOCLAW_AGENT_PASSED`，回显只显示 `printf` 命令本身，不含完整 token。

#### 核心文件改动

- `examples/starry/picoclaw-cli/` 下所有初始文件（assets 脚本、rootfs 脚本、3 个 QEMU 配置、demo 脚本、README）
- `os/StarryOS/kernel/src/syscall/net/opt.rs`：`SO_BROADCAST` setsockopt no-op

#### 测试/验证结果

- Phase 1 offline QEMU smoke → `STARRY_PICOCLAW_OFFLINE_PASSED`
- Phase 2 online QEMU smoke → `STARRY_PICOCLAW_AGENT_PASSED`
- clippy 10/10 checks passed

---

### PR #775 — PicoClaw Phase 3 Gateway 支持

- **链接：** https://github.com/rcore-os/tgoskits/pull/775
- **标题：** `feat(starry): add PicoClaw gateway smoke`
- **分支：** `codex/phase3-picoclaw-gateway` → `dev`
- **状态：** 已合并（2026-05-21）
- **主要 commit：**
  1. `chore: initialize picoclaw support branch`
  2. `ci: re-trigger`
  3. `feat(starry): add picoclaw gateway smoke`

#### 解决了什么问题

Phase 1/2 验证了 PicoClaw 作为"一次性命令行工具"能在 StarryOS 中运行。但 PicoClaw 的核心使用场景之一是作为 **gateway 服务**长时间运行、接收外部消息、触发 AI agent 回复。Phase 3 要验证 `picoclaw gateway` 能在 StarryOS guest 中启动 HTTP 服务并正确响应健康检查。同时为当面演示提供交互式长期使用环境。

#### 具体是怎么解决的

**问题 1：QEMU 启动失败——两个 net0 互相冲突**

Gateway 需要把 guest 的 18790 端口通过 QEMU hostfwd 暴露给宿主机，这样宿主机能直接 `curl http://127.0.0.1:18790/health`。QEMU 配置中通过 `-netdev user,id=net0,hostfwd=tcp::18790-:18790` 实现。

但问题在于：axbuild 的 rootfs QEMU 参数补丁逻辑（`scripts/axbuild/src/rootfs/qemu.rs`）在检测到需要网络设备时，会**无条件追加**一个默认的 `-netdev user,id=net0`。这和 gateway 配置中自带的 `-netdev user,id=net0,hostfwd=...` 冲突——QEMU 启动时发现两个 netdev 都叫 `net0`，直接报错退出。

排查过程：QEMU 报错信息是 `Duplicate netdev id 'net0'`。查看 axbuild 生成的完整 QEMU 命令行，发现 `-netdev` 参数确实出现了两次。

修复方式：修改 `qemu.rs` 中的 `ensure_disk_boot_net_args()` 函数。该函数原先只检测 `-drive` 和 `-device` 参数是否存在，对 `-netdev` 要么追加要么忽略。修复后新增 `netdev_matches()` 辅助函数：遍历已有 QEMU args，如果某个 `-netdev` 参数的 comma-separated 部分中包含 `id=net0`，就认为 netdev 已存在，**保留其所有选项**（包括 `hostfwd`），只补丁 drive 路径。同时新增回归测试 `ensure_disk_boot_net_preserves_existing_netdev_options` 验证 hostfwd 在补丁后不被丢失。

**问题 2：gateway smoke 如何在 guest 中验证 HTTP 服务**

Gateway 启动后需要等待 HTTP 端口就绪。Smoke 脚本的做法是：

1. 在后台启动 `picoclaw gateway --allow-empty --host 127.0.0.1`，记录 PID
2. 用 `kill -0 $gateway_pid` 检查进程是否还活着（如果 gateway 启动失败立即报告）
3. 循环最多 60 秒，每秒尝试 `curl -fsS http://127.0.0.1:18790/health`
4. `curl` 成功后检查响应包含 `"status":"ok"`
5. 用 `kill` + `wait` 清理 gateway 进程
6. 打印 `STARRY_PICOCLAW_GATEWAY_PASSED`

`--allow-empty` 参数是关键：PicoClaw gateway 正常启动需要配置至少一个消息 channel（微信等），但 smoke 测试只需要验证 HTTP 层可用，不需要真实 channel。这个参数允许 gateway 在无 channel 配置时也启动 HTTP 监听。

**问题 3：交互式环境需要不同的 QEMU 行为**

离线/agent/gateway smoke 都是自动化测试，QEMU 在匹配成功标记后自动退出。但当面演示需要 QEMU 持续运行，用户自己输入命令。为此新增 `qemu-x86_64-picoclaw-interactive.toml`：设置 `timeout = 0`（永不超时）、`success_regex = []` 和 `fail_regex = []`（不匹配任何退出条件）。同时 `run_picoclaw_interactive.sh` 脚本支持 `--rebuild-rootfs` / `--no-prepare` / `--prepare-only` 三种 rootfs 管理模式，方便重复使用。

#### 核心文件改动

- `scripts/axbuild/src/rootfs/qemu.rs`：netdev 冲突修复 + 回归测试
- `examples/starry/picoclaw-cli/qemu-x86_64-picoclaw-gateway.toml`：gateway smoke 配置
- `examples/starry/picoclaw-cli/qemu-x86_64-picoclaw-interactive.toml`：交互式配置（timeout=0）
- `examples/starry/picoclaw-cli/run_picoclaw_interactive.sh`：交互式长期使用脚本
- `examples/starry/picoclaw-cli/PHASE3_GATEWAY_SMOKE.md`

#### 测试/验证结果

- Gateway QEMU smoke → `STARRY_PICOCLAW_GATEWAY_PASSED`，`/health` 返回 `{"status":"ok","uptime":"55.827136ms","pid":15}`
- clippy 4/4 checks passed (axbuild)

---

### PR #776 — Phase 4 TTY/readline 修复

- **链接：** https://github.com/rcore-os/tgoskits/pull/776
- **标题：** `fix(starry-kernel): handle tty cursor position report`
- **分支：** `codex/phase4-starry-tty-readline` → `dev`
- **状态：** 已合并（2026-05-21）
- **主要 commit：**
  1. `fix(starry-kernel): handle tty cursor position report`

#### 解决了什么问题

Phase 3 之后，`picoclaw agent -m "消息"` 可以正常完成单轮请求，但直接运行 `picoclaw agent`（不带 `-m`）进入交互模式后，键盘输入完全无响应——程序停在 `Interactive mode (Ctrl+C to exit)`，无论怎么按键都没有反应。这意味着 PicoClaw 在 StarryOS 中只能作为"一次性问答工具"使用，无法进行多轮交互对话。

一个重要的线索是：`echo "消息" | picoclaw agent` 和 `cat | picoclaw agent` 都可以正常工作。这说明 PicoClaw 的 agent 主循环和网络请求路径没问题，问题出在 **tty/readline 层**——只有当 stdin 是 tty 时才触发的初始化路径有 bug。

#### 具体是怎么解决的

**诊断：readline 初始化卡在等待光标位置响应**

PicoClaw 使用 readline 库处理交互式输入。readline 初始化时进入 raw terminal 模式（关闭 ICANON/ECHO），然后发送 ANSI Device Status Report 查询 `ESC[6n`（"终端，告诉我光标在哪"），等待终端回送形如 `ESC[row;colR` 的响应。收到响应后 readline 才能确定光标位置、初始化行编辑缓冲区。

在 StarryOS 的 QEMU 串口环境中，`ESC[6n` 被写出后：
- 字节通过 tty `write_at()` → `write_output_bytes()` → 串口设备 → QEMU nographic 输出
- 但**没有任何回环路径**：QEMU 串口不是真正的终端模拟器，不会自动回送 cursor position response
- readline 的 `read()` 调用永远等不到响应数据，整个线程阻塞在 read 上

这解释了为什么管道模式可以工作：`cat | picoclaw agent` 中 stdin 是 pipe 而非 tty，PicoClaw 检测到 `!isatty(stdin)` 后跳过 readline 初始化，直接从管道读取。

**修复思路：在内核 tty 层注入虚拟响应**

考虑到 StarryOS QEMU 环境没有真实的终端模拟器来响应 ANSI 查询，修复的核心思路是在**内核 tty 驱动层**拦截光标位置查询并注入虚拟响应。具体做法分两部分：

**第一部分：tty write 路径检测 + 注入（`tty/mod.rs`）**

```rust
const ANSI_CURSOR_POSITION_REQUEST: &[u8] = b"\x1b[6n";
const ANSI_CURSOR_POSITION_RESPONSE: &[u8] = b"\x1b[1;1R";
```

在 `Tty::write_at()` 中，先正常调用 `write_output_bytes()` 将输出字节写入串口，然后检查输出缓冲区是否包含 `ESC[6n`：

```rust
if contains_bytes(buf, ANSI_CURSOR_POSITION_REQUEST) {
    self.ldisc.lock().inject_input(ANSI_CURSOR_POSITION_RESPONSE);
}
```

`contains_bytes()` 是新增的简单辅助函数，用滑动窗口在字节序列中搜索子序列。

注入的响应是固定的 `ESC[1;1R`（光标在第 1 行第 1 列）。这对于 PicoClaw 的 readline 来说足够了——它只需要知道一个合法的光标位置来初始化。

**第二部分：line discipline 注入输入队列（`tty/terminal/ldisc.rs`）**

tty 的正常输入路径是从串口硬件 → ring buffer → `read()`。但内核注入的字节不是从硬件来的，需要一个旁路通道。新增 `injected_input: VecDeque<u8>` 字段：

- `inject_input(&mut self, bytes: &[u8])`：将字节追加到 `injected_input` 尾部，然后唤醒 `input_ready`（让阻塞在 `poll()` 的线程知道有数据可读）
- `read(&mut self, buf: &mut [u8])`：**优先读取 injected_input**（在 ring buffer 之前），确保内核注入的响应比用户输入先被读到
- `poll_read(&self) -> bool`：`injected_input` 非空时立即返回 `true`，确保 `poll()` 不会误报不可读
- `drain_input(&mut self)`：同时清空 ring buffer 和 injected_input（处理 `TCSETSF` 等 flush 操作）

新增单元测试 `injected_input_is_readable_immediately` 验证注入 `ESC[1;1R` 后立即可以被 `read()` 读出。

**回归测试：C 语言级别验证**

新增 `test-suit/starryos/normal/qemu-smp1/bugfix/bug-tty-cursor-report`：
1. 保存原始终端属性
2. 进入 raw terminal 模式（关闭 ICANON/ECHO，设置 VMIN=1/VTIME=0）
3. 向 STDOUT 写出 `ESC[6n`
4. 用 `poll(STDIN_FILENO, POLLIN, 1000)` 等待最多 1 秒
5. 从 STDIN 读取响应
6. 校验读到了完整的 `ESC[1;1R`（6 字节）
7. 恢复终端属性

该测试不依赖 PicoClaw，纯 C 程序直接验证内核行为，已加入全部 4 个架构的 bugfix TOML。

#### 核心文件改动

- `os/StarryOS/kernel/src/pseudofs/dev/tty/mod.rs`：ANSI 查询检测 + 注入响应 + `contains_bytes()` 辅助函数
- `os/StarryOS/kernel/src/pseudofs/dev/tty/terminal/ldisc.rs`：`injected_input` 队列 + 优先读取逻辑 + 单元测试
- `test-suit/starryos/normal/qemu-smp1/bugfix/bug-tty-cursor-report/`：C 回归测试 + 4 架构 TOML

#### 测试/验证结果

- clippy 11/11 checks passed
- `bug-tty-cursor-report` 回归测试通过（4 架构）
- 手动 PicoClaw 交互验证：`picoclaw agent` → 出现 `You:` 提示 → 多轮对话 → `exit` → `Goodbye!` → 回到 shell

---

### PR #780 — PR_SET_VMA 兼容性修复

- **链接：** https://github.com/rcore-os/tgoskits/pull/780
- **标题：** `fix(starry-kernel): handle prctl PR_SET_VMA as silent no-op`
- **分支：** `fix/starry-prctl-set-vma` → `dev`
- **状态：** 已合并（2026-05-22）
- **主要 commit：**
  1. `fix(starry-kernel): handle prctl PR_SET_VMA as silent no-op`
  2. `ci: re-trigger`

#### 解决了什么问题

从 Phase 1 开始，每次运行 PicoClaw 都会在 StarryOS 内核日志中看到大量重复 warning：

```
sys_prctl: unsupported option 1398164801
```

这个数字 `1398164801` = `0x53564d41` = `PR_SET_VMA`。PicoClaw 由 Go 编写，Go runtime 在分配匿名内存时会调用 `prctl(PR_SET_VMA, PR_SET_VMA_ANON_NAME, addr, len, name)` 给 VMA 起一个可读的名字（用于 `/proc/self/maps` 调试）。StarryOS 不识别此 option，每次都打印 warning 并返回 `EINVAL`。

虽然 Go runtime 不会因为 `EINVAL` 而崩溃（它只是忽略错误继续执行），但大量 warning 会淹没真正有用的日志，而且在评审/演示场景下显得不够专业。

#### 具体是怎么解决的

在 StarryOS 的 `sys_prctl()` 实现中新增 `PR_SET_VMA` 分支：

1. 用 `linux_raw_sys::prctl::PR_SET_VMA` 和 `PR_SET_VMA_ANON_NAME` 常量做匹配（不硬编码数字）
2. 当 `option == PR_SET_VMA` 且子操作为 `PR_SET_VMA_ANON_NAME` 时，直接返回 `Ok(0)`——**silent no-op**，不打印任何日志，不验证 addr/len/name 指针，不保存 VMA name
3. 当子操作不是 `PR_SET_VMA_ANON_NAME` 时，返回 `EINVAL`
4. 不做完整的 Linux `PR_SET_VMA` 语义：不验证指针有效性，不在 VMA 上存储 name

为什么选择 no-op 而不是完整实现：
- Go runtime 调用 `PR_SET_VMA` 纯粹是为了调试便利（给 `/proc/self/maps` 里的匿名段起名字），不影响运行时行为
- Go 对返回值不做功能性依赖——即使返回错误，Go 也只是忽略
- 完整实现需要在 StarryOS 的 VMA 结构上增加 name 字段、拷贝用户空间字符串、处理生命周期，复杂度远超收益

**回归测试：**

新增 `bug-prctl-set-vma-anon-name`，用 C 程序直接调用：
- `prctl(PR_SET_VMA, PR_SET_VMA_ANON_NAME, ...)` → 期望返回 0
- `prctl(PR_SET_VMA, <未知子操作>, ...)` → 期望返回 -1 + errno=EINVAL

测试已加入 4 个架构的 bugfix TOML。

#### 核心文件改动

- StarryOS `sys_prctl()` 新增 `PR_SET_VMA` 分支（使用 `linux_raw_sys` 常量）
- 新增回归测试 `bug-prctl-set-vma-anon-name`（4 架构 TOML）

#### 测试/验证结果

- CI x86_64 bugfix 通过
- PicoClaw 运行时不再出现 `sys_prctl: unsupported option` warning

---

### PR #781 — waitid 系统调用实现

- **链接：** https://github.com/rcore-os/tgoskits/pull/781
- **标题：** `feat(starry-kernel): implement waitid syscall`
- **分支：** `fix/starry-waitid` → `dev`
- **状态：** 已合并（2026-05-22）
- **主要 commit：**
  1. `feat(starry-kernel): implement waitid syscall`
  2. `fix(starry): refactor waitid for NULL infop and shared decode`

#### 解决了什么问题

PicoClaw gateway 在执行工具（tool）时，通过 Go 的 `os/exec` 包 fork 子进程执行外部命令。Go 在等待子进程退出时使用 `waitid()` 系统调用（而不是老式的 `waitpid()`）。StarryOS 原先没有实现 `waitid`，每次调用都打印：

```
Unimplemented syscall: waitid
```

并返回 `ENOSYS`。这导致 Go 的 `os/exec` 无法正确获取子进程退出状态，子进程变成僵尸进程（zombie）无法被回收。对于 PicoClaw gateway 这种需要频繁执行工具的场景，僵尸进程会不断积累，最终耗尽进程表资源。

#### 具体是怎么解决的

**实现策略：复用已有 waitpid 框架**

StarryOS 已经有 `sys_waitpid` 的完整实现，包括进程状态跟踪、zombie 回收、父进程异步等待（通过 `child_exit_event` + waker）。`waitid` 的语义和 `waitpid` 高度重叠，区别在于：
- `waitid` 用 `idtype + id` 指定等待目标（`P_ALL`=任意子进程、`P_PID`=指定 PID），而 `waitpid` 用单个 `pid` 参数
- `waitid` 将结果写入 `siginfo_t` 结构（包含 `si_signo`、`si_code`、`si_pid`、`si_status`），而 `waitpid` 返回整数 status
- `waitid` 支持 `WNOWAIT` 选项（只查询不回收）

实现步骤：

1. **扩展类型定义**：复用 `WaitPid` 枚举（新增 `P_ALL` 和 `P_PID` 对应的变体），扩展 `WaitOptions` bitflags 新增 `WEXITED` 和 `WNOWAIT`

2. **核心逻辑**：`sys_waitid()` 首先解码 `idtype`/`id`/`options` 参数，然后调用与 `sys_waitpid` 相同的子进程查找和状态等待逻辑。当子进程就绪时：
   - 用 `decode_wait_status()` 将 Linux wait-status 编码（`(_status >> 8) & 0xff` 得退出码等）解码为 `CLD_EXITED`/`CLD_KILLED`/`CLD_DUMPED` 等 si_code
   - 通过 `get_zombie_cred()` 获取子进程的 UID（zombie 的 task 可能已被 GC，需要从 credentials 中读取）
   - 写入 `siginfo_t` 结构到用户空间
   - 如果不是 `WNOWAIT`，reap zombie 子进程

3. **处理 NULL infop**：第二个 commit `fix(starry): refactor waitid for NULL infop and shared decode` 修复了一个边界情况——Linux 允许 `infop` 为 NULL（此时只 reap 不写 siginfo），初始实现没有处理这种情况。

4. **WNOHANG 无就绪子进程时返回 0**：这是 `waitid` 的标准语义，表示"没有子进程退出"。此时需要把 `siginfo_t` 清零写入，特别是 `si_pid = 0`。

**回归测试：**

新增 `bug-waitid-basic`，覆盖 6 个用例：
1. `P_PID + WEXITED`：fork 子进程 → `exit(7)` → `waitid` 返回 → 校验 `si_code=CLD_EXITED`、`si_status=7`、子进程被 reap
2. `P_ALL + WEXITED`：fork 子进程 → `exit(3)` → 校验 `si_pid` 和 `si_status`
3. `WNOHANG`：子进程仍在运行时，`waitid` 返回 0、`si_pid=0`（不阻塞）
4. `ECHILD`：对非子进程 PID 调用 `waitid`，期望返回 -1 + `ECHILD`
5. `EINVAL`：非法 `idtype` 参数
6. `EINVAL`：缺少 `WEXITED` 选项

测试已加入 4 个架构的 bugfix TOML。

#### 暂不支持

- `P_PGID`（等待指定进程组）和 `P_PIDFD`（等待 pidfd）：返回 `EINVAL`
- `WSTOPPED`（等待子进程被停止）和 `WCONTINUED`（等待子进程恢复）：返回 `EINVAL`
- resource usage (rusage) 信息

这些暂不影响 PicoClaw。Go 的 `os/exec` 只使用 `P_PID + WEXITED + WNOHANG` 组合。

#### 核心文件改动

- 新增 `sys_waitid()` 系统调用实现
- 扩展 `WaitPid` 枚举和 `WaitOptions` bitflags
- 新增 `decode_wait_status()` 和 `get_zombie_cred()` 辅助函数
- 新增回归测试 `bug-waitid-basic`（6 个用例，4 架构 TOML）

#### 测试/验证结果

- 回归测试覆盖全部 6 个用例
- PR 已合并（2026-05-22），成功返回值已修正为 0

---

## 四、PicoClaw 支持过程中遇到的挑战及解决方式

### 4.1 rootfs 注入问题

**为什么普通 StarryOS rootfs 里没有 `/root/.picoclaw`：**

StarryOS 默认的 Alpine rootfs 是一个最小 Linux 文件系统镜像，只包含 busybox 和基础目录结构。PicoClaw 不是 Linux 发行版的标准软件包，需要手动将其二进制和配置注入到 rootfs 中。

**什么是 rootfs：**

rootfs（root filesystem）是 Linux 内核启动后挂载的第一个文件系统。在 StarryOS QEMU 测试中，rootfs 是一个 ext4 格式的磁盘镜像文件，包含用户态程序和文件。StarryOS 内核启动后通过 virtio-blk 设备挂载该镜像。

**为什么必须启动注入过 PicoClaw 的 x86_64 rootfs：**

PicoClaw release 当前只提供 Linux x86_64 静态二进制。StarryOS 在 QEMU 中模拟 x86_64 架构时，guest 中的用户态程序是原生 Linux ELF 二进制。必须使用注入了 `picoclaw` 和 `picoclaw-launcher` 的 x86_64 rootfs 才能在 StarryOS shell 中执行 PicoClaw 命令。

注入通过 `debugfs` 工具完成：将文件放入 overlay 临时目录，生成 debugfs 命令脚本（`write`、`sif mode`），然后应用到 ext4 镜像。过程中修复了 mode 编码错误（`010755` → `0100755`）和临时文件误注入问题。

---

### 4.2 架构问题

**PicoClaw release 当前优先使用 Linux x86_64 静态二进制：**

PicoClaw 由 Go 语言编写，通过静态链接生成独立的 ELF 二进制。GitHub release 提供 `picoclaw_Linux_x86_64.tar.gz`，包含 `picoclaw` 和 `picoclaw-launcher` 两个可执行文件。

**为什么不能直接用 `riscv64gc-unknown-none-elf` 启动 PicoClaw：**

`riscv64gc-unknown-none-elf` 是 Rust 的 bare-metal 目标三元组，用于编译内核代码。PicoClaw 是 Linux 用户态程序（ELF 格式，依赖 Linux syscall 接口），无法在 bare-metal 环境或不同架构的模拟器中直接运行。要在 RISC-V 上运行 PicoClaw，需要：
1. PicoClaw 提供 `linux/riscv64` 静态二进制
2. StarryOS 在 RISC-V QEMU 上提供完整的 Linux ABI 兼容层

目前只有 x86_64 路径经过验证。

---

### 4.3 在线 API 配置问题

**Mimo endpoint 的 model/provider/api_base 配置：**

PicoClaw 的 `config.json` 中 `model_list` 定义模型提供者。Mimo 使用 OpenAI-compatible API，因此 `provider` 设为 `openai`，`api_base` 指向 Mimo 的 `/v1` 端点。

**400 reasoning_content 错误：**

`mimo-v2.5` 模型默认启用 thinking/reasoning 模式，响应中包含 `reasoning_content` 字段。PicoClaw 的 OpenAI-compatible 调用链不会回传该字段，导致服务端认为响应异常。通过在 `extra_body.chat_template_kwargs` 中设置 `enable_thinking: false` 解决。

**401 Invalid API Key 错误：**

API key 通过 `.security.yml` 文件注入到 rootfs，文件权限为 0600。如果 key 格式错误或未正确注入，PicoClaw 发送请求时会在 Authorization header 中携带无效 key，服务端返回 401。

**修正方式：**
- 确认 `PICOCLAW_API_KEY` 环境变量在 rootfs 生成时正确设置
- 检查 `.security.yml` 中 `api_keys` 列表的缩进和引号
- 可通过 `--api-key` 参数显式传入

---

### 4.4 Gateway 服务问题

**长时间运行服务、端口监听、health check：**

`picoclaw gateway` 启动后监听 `127.0.0.1:18790`。Smoke 测试在后台启动 gateway，轮询最多 60 秒等待 `/health` 返回 `{"status":"ok"}`。同时监控 gateway 进程是否存活，如果进程退出则立即报告失败。

**QEMU hostfwd 和 netdev 参数冲突：**

axbuild 在构建 rootfs QEMU 命令时，会自动添加 `-netdev user,id=net0`。Gateway 配置文件中需要 `hostfwd=tcp::18790-:18790`，也通过 `-netdev user,id=net0,hostfwd=...` 指定。两者合并后产生两个 `id=net0` 的 netdev 定义，QEMU 拒绝启动。

**修复：** `scripts/axbuild/src/rootfs/qemu.rs` 中 `netdev_matches()` 函数检测已有 `-netdev` 参数是否包含 `id=net0`，如果是则保留其完整选项（含 hostfwd），仅补丁 drive 路径。新增了回归测试验证 hostfwd 保留行为。

**微信 channel 登录和实际收发消息：**

PicoClaw 支持微信作为消息 channel，通过 gateway 接收微信消息并触发 agent 回复。在 StarryOS 环境中，微信 channel 的完整流程（扫码登录、消息收发、长时间连接保持）仍需进一步验证，主要受限于：
- StarryOS 网络栈的长时间连接稳定性
- 微信协议可能依赖的特定 syscall 或 DNS 行为
- QEMU 用户态网络的限制（NAT、端口转发）

---

### 4.5 TTY/readline 问题

**裸 `picoclaw agent` 卡住：**

PicoClaw 的 readline 库在初始化交互模式时发送 `ESC[6n`（ANSI Device Status Report - Cursor Position），等待终端回送 `ESC[row;colR`。StarryOS 的 tty 驱动只将输出字节传递给串口设备，没有生成回送数据，readline 永远等不到响应。

**`cat | picoclaw agent` 正常：**

管道模式下 stdin 不是 tty，PicoClaw 检测到非 tty stdin 后跳过 readline 初始化，直接从管道读取。这绕过了 ANSI 查询问题，但失去了行编辑、光标移动等交互功能。

**StarryOS 缺少 ANSI cursor position response：**

Linux 内核的 tty/terminal 层在收到 `ESC[6n` 查询时，终端模拟器（如 VT100/xterm）会回送光标位置。StarryOS 的 QEMU 串口没有完整的终端模拟器，串口输出直接发送给 QEMU 的 nographic 模式，没有回环路径。

**注入 `ESC[1;1R` 后解决：**

在 StarryOS tty 的 `write_at()` 方法中：
1. 检测输出是否包含 `ESC[6n`（通过 `contains_bytes()` 辅助函数）
2. 如果包含，调用 `ldisc.inject_input(ANSI_CURSOR_POSITION_RESPONSE)` 注入固定响应 `ESC[1;1R`（光标在第 1 行第 1 列）
3. line discipline 中的 `injected_input` 队列确保注入字节优先被 `read()` 读取，且对 `poll()` 可见

---

### 4.6 Syscall / ABI 兼容性问题

**`sys_prctl: unsupported option ...`（option 1398164801）：**

PicoClaw 由 Go 编写，Go runtime 在设置匿名内存区域名称时调用 `prctl(PR_SET_VMA, PR_SET_VMA_ANON_NAME, addr, len, name)`。`PR_SET_VMA` 的数值为 `0x53564d41`（即 1398164801），StarryOS 不识别此 option，每次调用都打印 warning。

**影响：** 不影响功能（Go 对返回值不做功能性依赖），但大量 warning 日志影响可读性。

**修复（PR #780）：** 在 `sys_prctl()` 中新增 `PR_SET_VMA` 分支，`PR_SET_VMA_ANON_NAME` 返回 `Ok(0)` 作为 silent no-op，不存储 VMA name。

**`Unimplemented syscall: waitid`：**

PicoClaw gateway/tool 执行路径通过 Go 的 `os/exec` 包调用 `waitid()` 系统监听子进程状态。StarryOS 原先未实现此 syscall，返回 ENOSYS。

**影响：** 子进程无法被正确回收，可能导致僵尸进程积累，影响 gateway 的工具执行功能。

**修复（PR #781）：** 实现 `sys_waitid()` 系统调用，支持 `P_ALL`/`P_PID` idtype 和 `WEXITED`/`WNOHANG`/`WNOWAIT` options。`WNOWAIT` 只查询不回收，`WNOHANG` 无就绪子进程时返回 0。

**当前修复程度和剩余风险：**

| 兼容性问题 | 修复状态 | 剩余风险 |
|-----------|---------|---------|
| `SO_BROADCAST` setsockopt | 已修复（no-op） | 无已知风险 |
| `PR_SET_VMA_ANON_NAME` prctl | 已修复（silent no-op） | 不保存 VMA name，Go 不依赖 |
| `waitid` syscall | 已修复（P_ALL/P_PID + 基本选项） | 不支持 P_PGID/P_PIDFD/WSTOPPED/WCONTINUED |
| ANSI cursor position query | 已修复（ESC[1;1R 注入） | 不是完整终端模拟器 |
| `ioctl(TIOCGWINSZ)` 等 terminal ioctl | 部分支持 | 复杂 TUI 程序可能需要更多 ioctl |
| `PR_SET_VMA` 非 ANON_NAME 子操作 | 返回 EINVAL | 无已知调用者 |

---

## 附录：文件清单

### 新增文件

```
examples/starry/picoclaw-cli/
├── README.md                              # 总体使用文档
├── PHASE1_OFFLINE_SMOKE.md                # Phase 1 记录
├── PHASE2_AGENT_SMOKE.md                  # Phase 2 记录
├── PHASE3_GATEWAY_SMOKE.md                # Phase 3 记录
├── PHASE4_TTY_READLINE.md                 # Phase 4 记录
├── prepare_picoclaw_assets.sh             # 下载 PicoClaw release 资产
├── prepare_picoclaw_rootfs.sh             # 构建注入 PicoClaw 的 rootfs
├── demo_picoclaw_agent.sh                 # 逐步演示脚本
├── run_picoclaw_interactive.sh            # 交互式长期使用脚本
├── qemu-x86_64-picoclaw-offline.toml      # 离线 smoke QEMU 配置
├── qemu-x86_64-picoclaw-agent.toml        # 在线 agent smoke QEMU 配置
├── qemu-x86_64-picoclaw-gateway.toml      # Gateway smoke QEMU 配置
└── qemu-x86_64-picoclaw-interactive.toml  # 交互式 QEMU 配置
```

### 修改的内核/工具文件

```
os/StarryOS/kernel/src/syscall/net/opt.rs              # SO_BROADCAST no-op
os/StarryOS/kernel/src/pseudofs/dev/tty/mod.rs         # ANSI cursor response 注入
os/StarryOS/kernel/src/pseudofs/dev/tty/terminal/ldisc.rs  # 注入输入队列
os/StarryOS/kernel/src/syscall/sys.rs                   # clippy cleanup
scripts/axbuild/src/rootfs/qemu.rs                      # hostfwd 保留逻辑
```

### 回归测试

```
test-suit/starryos/normal/qemu-smp1/bugfix/bug-tty-cursor-report/     # TTY 光标报告
test-suit/starryos/normal/qemu-smp1/bugfix/bug-prctl-set-vma-anon-name/  # PR_SET_VMA
test-suit/starryos/normal/qemu-smp1/bugfix/bug-waitid-basic/           # waitid 基本功能
```

### PR 合并时间线

| PR | 标题 | 合并时间 |
|----|------|---------|
| #689 | Phase 1/2 支持 | 2026-05-18 |
| #776 | Phase 4 TTY 修复 | 2026-05-21 |
| #775 | Phase 3 Gateway | 2026-05-21 |
| #780 | PR_SET_VMA 兼容 | 2026-05-22 |
| #781 | waitid 实现 | 2026-05-22 |
