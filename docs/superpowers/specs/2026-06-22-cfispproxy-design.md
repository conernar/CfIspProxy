# CfIspProxy 架构设计（蓝图）

- 日期：2026-06-22
- 状态：已与需求方确认架构，待评审 spec
- 类型：架构蓝图（design spec），后续进入实现计划（writing-plans）

## 1. 背景与目标

利用 **一个域名 + 一个 Cloudflare 免费账号** 的 Workers（Compute）能力，搭一条
"穿墙 + 高质量出口 IP" 的代理链路，**用一个已购买的高质量 ISP 代理 IP 替代昂贵的家宽/住宅代理预算**。

核心思路：**职责解耦**

- **CF 边缘**负责「穿墙 + 抗封」：客户端连干净的 CF 边缘 IP，TLS 套在 WebSocket 上过 DPI。
- **ISP 代理**负责「高质量出口 IP」：worker 把流量经 SOCKS5(账密) 转发到 ISP，目标网站看到的是 ISP 出口 IP。
- **客户端 `urltest`**负责「自动轮换防墙」：同一域名下挂 N 个不同 CF 边缘 IP 的节点，某个 IP 被墙时客户端测速自动跳过，**服务端零动作**。

交付物核心是 **「单文件 + 复制粘贴部署」**：用户把一个 `worker.js` 粘进 CF Dashboard 的 Workers 编辑器即可，无构建、无依赖（仅 `import { connect } from "cloudflare:sockets"`）。

### 成功标准

1. 用户把单个 `worker.js` 粘贴进 CF Workers 即可跑通：客户端 → CF 边缘 → worker → SOCKS5(ISP) → 目标，目标侧看到 ISP 出口 IP。
2. 客户端"更新订阅"即可从 worker 的 `/sub` 拿到 N 个优选节点，`urltest` 自动选最优、被墙自动跳。
3. 优选 IP 列表由用户墙内机器周期性生成并 `git push`，worker 运行时从仓库拉取，**轮换零服务端运维**。
4. （Stage 2）`main.py` 能把用户的 ISP 账密/UUID/仓库 URL 烤进模板并混淆，产出**每人指纹唯一**、可直接粘贴的 worker.js。

## 2. 非目标（YAGNI，v1 明确不做）

- **UDP 代理**：v1 只做 TCP CONNECT；UDP / DNS-over-socket 以后再议。
- **CF API / wrangler 自动部署**：交付方式是手动粘贴，不做 API 自动化部署（与"单文件粘贴"定位冲突）。
- **多账号 / 多域名编排**：单域名单账号即可满足（"换节点"只是换 CF 边缘 IP，非换后端）。
- **自建订阅转换服务（subconverter）**：worker 自己直接产出 sing-box 配置 + `vless://` 链接；Clash/mihomo 格式留作可选后续。
- **GUI**：命令行/粘贴即可。
- **把优选探测放进 worker**：物理上不可行（worker 在墙外，测不到墙内封锁），见 §10。

## 3. 整体架构与数据流

```
┌─ 墙内 ─────────────────────────────────────────┐
│  sing-box 客户端                                  │
│   selector: urltest  (自动测延迟选最快、被墙跳过)   │
│   ├─ outbound#1 = VLESS+WS+TLS → server=优选IP_1   │   所有 outbound 共享:
│   ├─ ...                                          │     SNI/Host = your-domain
│   └─ outbound#N = VLESS+WS+TLS → server=优选IP_N   │     path=/<WS_PATH>  uuid=<UUID>
└────────┼──────────────────────────────────────┘
         │ TLS(SNI=your-domain) 连到某个干净的 CF 边缘 IP
         ▼
   Cloudflare 边缘 ──(按 Host=your-domain 路由)──► Worker
         │
   ┌─────▼──── worker.js (edgetunnel 式 VLESS 服务端，单文件) ──────┐
   │ 数据面: WS升级→解析VLESS头→校验UUID→得目标host:port           │
   │         connect(ISP_HOST:ISP_PORT)  [cloudflare:sockets]      │
   │         SOCKS5握手(账密RFC1929)+CONNECT 目标                   │
   │         双向 pipe: 客户端WS ⇄ ISP socket                       │
   │ 控制面: GET /sub?token=SUB_TOKEN                              │
   │         fetch(GitHub raw preferred-ips.txt) → 拼N个节点 → 返回 │
   └─────┼────────────────────────────────────────────────────────┘
         ▼
   ISP 代理(高质量出口IP) ──► 目标网站   （目标看到的是 ISP 出口 IP）
```

**核心原理**：VLESS-over-WS-TLS 里 `address` 与 `host/sni` 是两件事——
`address` 决定客户端 TCP 连到哪个 CF 边缘 IP；`host/sni` 决定 CF 把流量路由到哪个 worker。
只要 `host/sni/uuid/path` 全一致，`address` 换成任意干净 CF 边缘 IP，流量都到同一个 worker。
所以"换节点防墙"在服务端零动作，只是客户端连了不同的 CF 入口 IP。

## 4. 子系统划分

| 子系统 | 是什么 | 物理位置 | 依赖 |
|---|---|---|---|
| **A 数据面** | worker.js 的代理转发逻辑 | CF Worker（墙外） | `cloudflare:sockets` |
| **C 控制面** | worker.js 的 `/sub` 订阅生成（与 A 同处一个单文件） | CF Worker（墙外） | `fetch` GitHub raw |
| **优选脚本** | 墙内 IP 优选扫描器，产出 `preferred-ips.txt` 并 push | 用户墙内机器 | CF IP 段、网络探测 |
| **B Stage2** | `main.py` 个性化 + 混淆生成器 | 用户本地 | 模板 worker.js |

解耦约束：A 不知道优选 IP 存在（只处理一条已到达的连接）；C 不碰部署；优选脚本不碰 worker 运行时；
B 只做"把模板个性化并混淆"。四者通过共享常量组对齐：`{域名, UUID, WS_PATH, SUB_TOKEN, 仓库raw URL, ISP账密}`。

## 5. worker.js 详细设计（单文件，逻辑分区）

物理上一个文件、零依赖、ES module、可直接粘贴。逻辑分区如下：

### ① CONFIG 区（文件顶部常量）
```
UUID            // 代理鉴权；只有正确 UUID 的连接才会被转发（非开放代理）
WS_PATH         // WebSocket 路径，秘密
SUB_TOKEN       // /sub 访问令牌，防止泄露 UUID/ISP 配置
ISP_HOST/PORT/USER/PASS  // 上游 SOCKS5(账密) 出口
PREFERRED_IPS_URL        // GitHub raw 的 preferred-ips.txt 地址
FALLBACK_IPS[]           // 拉取失败时的内置兜底 IP 列表（小）
```
Stage 1：用户手填。Stage 2：`main.py` 烤进来（缺省值随机生成 UUID/WS_PATH/SUB_TOKEN）。

### ② fetch(request) 路由分发
- 是 WebSocket 升级 且 路径 == `WS_PATH` → 走【数据面 ③】
- `GET /sub?token=SUB_TOKEN` → 走【控制面 ④】
- 其它任何路径 → 返回**伪装页**（200，仿 nginx 默认页或空白），不暴露身份

### ③ 数据面（核心代理）
1. 接受 WebSocket，读第一帧 = VLESS 请求头，解析：版本 / 16 字节 UUID（**校验**）/ addons / command（0x01 TCP）/ port / atyp / address。
2. `connect({ hostname: ISP_HOST, port: ISP_PORT })`（`cloudflare:sockets`）。
3. SOCKS5 握手：
   - 方法协商：`05 01 02`（仅账密）→ 期望 `05 02`
   - 账密认证（RFC 1929）：`01 <ulen> user <plen> pass` → 期望 `01 00`
   - CONNECT：`05 01 00 <atyp> <dst.addr> <dst.port>` → 期望 `05 00 ...`
4. 回写 VLESS 响应头（`00 00`）给客户端；把 VLESS 头之后的首包残余数据写入 socket；
   之后双向 pipe：`WS.readable ⇄ socket.writable`、`socket.readable ⇄ WS`。

> 说明：edgetunnel 系（如 cmliu）本就有"worker 出口走 SOCKS5"的成熟实现，本项目把它作为**始终启用的主路径**，
> 区别仅是 `connect()` 连的是 ISP 代理而非目标，再用 SOCKS5 抵达目标。

### ④ 控制面（订阅生成 `/sub`）
1. 校验 `token == SUB_TOKEN`，否则走伪装页。
2. `getPreferredIPs()`：`fetch(PREFERRED_IPS_URL, { cf: { cacheTtl: 1800, cacheEverything: true } })`；
   失败回退 `FALLBACK_IPS`；按行解析，`#` 注释与空行忽略，支持 `IP[:port][#备注]`。
3. 用 `request.host`（=域名）+ UUID + WS_PATH + 每个优选 IP 拼出 N 个 VLESS 节点。
4. 输出格式：
   - 默认 sing-box `config.json`：N 个 `vless+ws+tls` outbound + 一个 `{ "type":"urltest" }` selector 选其全部。
   - `?format=links`：base64 的 `vless://...` 列表，供 v2rayN 兜底。

节点模板（仅 `address` 在 N 个节点间变化）：
```
vless://<UUID>@<优选IP>:443?encryption=none&security=tls&sni=<域名>&type=ws&host=<域名>&path=%2F<WS_PATH>#<备注>
```

## 6. 优选 IP 闭环（控制面数据源）

```
[墙内·用户机器] cron / 手动: 跑优选脚本 → 覆写 data/preferred-ips.txt → git commit && git push
        │ push
        ▼
   GitHub 仓库 (data/preferred-ips.txt)
        ▲ fetch(raw url)  ← 发生在 worker 侧（墙外，畅通）
   worker.js /sub: 拉取 → 解析 → 拼 N 节点 → 返回订阅
        ▼
   客户端"更新订阅" → 拿到本周最新优选 IP，urltest 自动选优
```

关键性质与约束：
- **fetch 发生在 worker（墙外）**，所以即使 `raw.githubusercontent.com` 在国内被墙也无所谓，客户端从不碰 GitHub。
- worker 端**必须缓存**（`cf.cacheTtl≈1800`），避免每次 `/sub` 都打 GitHub。
- 拉取失败**回退 `FALLBACK_IPS`**，保证 `/sub` 永不空。
- CDN 选择：`raw.githubusercontent.com`（push 后数分钟生效，适合周更，**默认**）；`cdn.jsdelivr.net/gh/...`（更快但缓存可达 ~7 天，需 `@commit`/purge 才即时，不默认）。
- 文件格式：一行一个 `IP[:port][#备注]`；亦可直接放 CloudflareSpeedTest 的 CSV，由 worker 按速度列过滤。

## 7. 优选脚本设计（墙内扫描器）

目标：在用户墙内机器上周期性产出 top-N 优选 CF IP。

算法：
1. 拉 CF 官方 IP 段（`https://www.cloudflare.com/ips-v4`，约 15 个 CIDR）。
2. 从中**随机采样** K 个 IP（CF 段巨大，必须采样）。
3. 一阶段·延迟过滤（快、并发）：对 `ip:443` 做 TCP/TLS 握手量 RTT + 丢包，剔除连不上/高延迟/高丢包，留 top M。
4. 二阶段·测速（慢、可选）：对 top M 用 `https://speed.cloudflare.com/__down?bytes=N`（SNI/Host 指向 CF）量真实下载速度，
   抓"握手成功但被限速/QoS"的情况，留 top N。
5. 输出 `data/preferred-ips.txt`（带延迟/速度注释），可选自动 `git commit && git push`。

落地选择：
- **包 CloudflareSpeedTest（XIU2）**：最稳，直接吃其 `result.csv`，推荐起步。
- **Python 自写（asyncio + httpx）**：可融入 `main.py` 工具链、按真实域名 SNI/Host 测得更准，难度中等。

约束：
- **必须墙内运行**（优选测的是"从你这个位置"的延迟/封锁；墙外 runner（含 GitHub Actions）结果对你无意义）。
- 结果会过期，需 cron 周期性重跑（周更即可；可在墙内机器上 cron「跑 + push」全自动）。

## 8. main.py 混淆生成器（Stage 2）

```
输入: ISP_HOST/PORT/USER/PASS、PREFERRED_IPS_URL、(可选)自定义 UUID/WS_PATH/SUB_TOKEN
步骤:
  1. 读 worker/worker.js 模板
  2. 注入用户值到 CONFIG 区（未提供的 UUID/WS_PATH/SUB_TOKEN 随机生成）
  3. （可选）刷新内置 FALLBACK_IPS
  4. 混淆: 标识符重命名 + 字符串编码 + 注入无害噪声 / 控制流变形
          —— 必须保留 `import { connect } from "cloudflare:sockets"` 与 Worker 运行语义
  5. 输出 dist/worker.<随机>.js（每人指纹唯一，规避按代码特征批量封禁）
顺带产出: 对应的 sing-box client 配置 + 部署说明（粘哪、设什么）
```

混淆器实现选择（实现期定夺）：优先**包装 npm `javascript-obfuscator`**（成熟），参数调到不破坏 Workers（保留 import、避免破坏 `self`/全局、控制流变形保持中等以控 CPU）；
或自写轻量混淆。**混淆目的是"指纹唯一化以规避批量识别"，不是密码学保密。**

## 9. 仓库结构

```
worker/worker.js              # Stage1 主交付：手写单文件模板（含占位常量）
worker/README.md              # 粘贴部署说明
tools/main.py                 # Stage2 个性化 + 混淆生成器
tools/obfuscator/             # 混淆实现（包 javascript-obfuscator 或自写）
tools/preferred_ip/scan.py    # 墙内优选脚本
tools/requirements.txt
data/preferred-ips.txt        # 优选 IP 列表（worker 拉取，墙内脚本周更）；本仓库附示例
docs/superpowers/specs/       # 本设计文档
README.md
```

> 说明：`PREFERRED_IPS_URL` 为每个使用者可配置项（指向各自维护的列表）；本仓库附 `data/preferred-ips.txt` 作示例。

## 10. 安全与威胁模型

- **UUID = 代理鉴权**：仅正确 UUID 的连接被转发，避免沦为开放代理。
- **SUB_TOKEN = `/sub` 鉴权**：防止任何人拿到域名即可取走 UUID/ISP 配置。
- **伪装页**：未知路径返回普通 200 页，降低被主动探测识别的概率。
- **ISP 账密位于 worker 代码常量中**：若 worker 源码泄露则暴露。混淆抬高门槛但非真正保密。
  折中：为"粘贴即用"选择常量；**后续可选**把 ISP 账密改为 Worker 环境变量以提升保密性（记为可选增强）。
- **优选 IP 列表是公开 CF IP**，放公共仓库无敏感性（敏感的是 UUID/ISP 账密，不在列表里）。
- **混淆目的**：指纹唯一化以规避批量识别/封禁，非加密。
- **CF ToS 风险**：在 Workers 上跑代理/VPN 可能违反 ToS，个人小流量自用风险较低，需用户自担。

## 11. 关键约束与风险

| 风险/约束 | 说明 | 应对 |
|---|---|---|
| 墙内观测点不可省 | GFW 封锁只能墙内观测；worker/CF/海外 VPS 都看不到 | 优选脚本必须墙内跑；客户端 urltest 做最终选择 |
| `cloudflare:sockets` 限制 | `connect()` 有端口/目标限制（如禁 25） | 实现期验证对 ISP SOCKS5 host:port 可用；多为 443/自定义端口，通常 OK |
| CF 免费额度 | 10 万请求/日、CPU 时间限制、WS 连接 | 个人自用足够；混淆控制流变形保持适度以省 CPU；实现期核对 WS/时长限制 |
| 优选结果过期 | 封锁/分配天天变 | 周更 cron；客户端 urltest 跳过失效 IP |
| GitHub raw 缓存/限速 | 频繁拉取可能被限 | worker 端缓存 30 分钟；失败回退 FALLBACK_IPS |
| IP 白名单认证不可用 | CF 出口 IP 不固定 | 已确定 ISP 用**账密认证**，规避此问题 |

## 12. 技术选型决策记录（含被否方案）

| 决策 | 选择 | 否决的备选与原因 |
|---|---|---|
| 交付方式 | 单文件 + 复制粘贴 | wrangler/CF API 自动部署（与"粘贴即用"定位冲突） |
| 协议 | VLESS | VMess（多余加密开销）/Trojan（生态略弱） |
| 配置载体 | 文件顶部常量 | Worker 环境变量（粘贴步骤更多；ISP 账密入环境变量列为可选增强） |
| 优选观测点 | 客户端 urltest + 墙内自写脚本 | 国内探针 agent / 纯第三方 feed / 被动检测（自写脚本更可控、不依赖第三方） |
| 优选数据源托管 | 自有 GitHub 仓库 `preferred-ips.txt`（worker `fetch`） | jsdelivr（缓存太久）/ R2/自建小服务（GitHub 更简单且带版本） |
| 优选刷新方式 | 墙内 cron 跑脚本 + git push；worker 运行时拉取 | GitHub Actions（runner 墙外，结果无意义） |
| 客户端 | sing-box 为主 + `vless://` 链接兜底 v2rayN | mihomo/Clash YAML（可作后续可选格式） |
| 混淆器 | 包 `javascript-obfuscator`（中等强度） | 重度控制流变形（CPU/体积/可能被特征化） |

## 13. 分阶段交付

- **Stage 1（主要工作）**：手写 `worker/worker.js` —— 数据面(VLESS-WS→SOCKS5→ISP) + 控制面(`/sub` 拉 GitHub 优选 + 缓存 + 回退) + 伪装页。手填常量、粘贴部署、端到端跑通。
- **Stage 1.5**：墙内优选脚本 `tools/preferred_ip/scan.py` + `data/preferred-ips.txt` + cron/push，喂给控制面。
- **Stage 2**：`tools/main.py` 个性化 + 混淆生成器，产出每人唯一、可粘贴的 worker.js。

实现顺序：**先 Stage 1（地基）→ 再优选脚本（喂数据）→ 再 main.py（打包混淆）**。每阶段各自 spec→plan→实现。

## 14. 待实现期确认的开放点

- `cloudflare:sockets` 对所购 ISP SOCKS5 端点的实际可用性（端口/握手）。
- CF 免费版对 WebSocket 长连接 / 请求时长的具体限制。
- 混淆参数集（在"指纹唯一 + 不破坏运行 + 控 CPU"之间取值）。
- 优选脚本采用"包 CloudflareSpeedTest"还是"Python 自写"（建议起步包 CFST，后续可替换）。
