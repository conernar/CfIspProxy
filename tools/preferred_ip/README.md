# preferred_ip —— 墙内优选 IP 扫描器

采样 Cloudflare 边缘 IP，两阶段（延迟过滤 → 测速）筛出最优的，写入 `data/preferred-ips.txt`，可选 `--push` 自动提交，闭合优选 IP 自动轮换链路。

```
[墙内·你的机器] cron 跑 scan.py → 覆写 data/preferred-ips.txt → git push
        │
        ▼  (worker /sub 墙外 fetch，带缓存)
   worker.js /sub → 拼 N 个同 worker 节点 → 客户端"更新订阅" → urltest 自动选优/避墙
```

## ⚠️ 必须在墙内运行

优选测的是"**从你这台机器**到该 CF IP"的延迟/连通/速度。在墙外 VPS（含 GitHub Actions runner）跑出来的结果对你家宽毫无意义。`git push` 只是发布动作，**扫描本身必须墙内**。

## 用法

```bash
# 默认：采样 800 → 延迟过滤留 20 → 测速 → 输出 top-10 → data/preferred-ips.txt
uv run python tools/preferred_ip/scan.py

# 扫完自动提交并推送（cron 用）
uv run python tools/preferred_ip/scan.py --push

# 快速、省流量（只测延迟，不测速）
uv run python tools/preferred_ip/scan.py --no-speedtest
```

## 参数

| 参数 | 默认 | 说明 |
|---|---|---|
| `-n, --count` | 800 | 采样多少个候选 IP |
| `--top-latency` | 20 | 阶段①延迟过滤后保留多少个进测速 |
| `-o, --output` | 10 | 最终写出多少个优选 IP |
| `--concurrency` | 100 | 阶段①测延迟并发数 |
| `--timeout` | 2.0 | 单个 IP 测延迟超时（秒） |
| `--sni` | speed.cloudflare.com | 测试用 SNI/Host（通用 CF 端点） |
| `--port` | 443 | 测试端口 |
| `--speed-seconds` | 5.0 | 单个 IP 测速时间盒（秒） |
| `--speed-concurrency` | 4 | 测速并发数（不宜高，避免占满线路） |
| `--no-speedtest` | off | 跳过阶段②，只按延迟排序 |
| `--out-file` | data/preferred-ips.txt | 输出文件 |
| `--refresh-cidr` | off | 重新拉取 CF 官方 IP 段（默认读内置 cf_ipv4.txt） |
| `--push` | off | 扫完后 git add/commit/push（无变更则跳过） |
| `--seed` | 随机 | 采样随机种子（复现/测试用） |

## cron 示例（每周一 4:00 跑并推送）

```cron
0 4 * * 1 cd /home/rias/CfIspProxy && uv run python tools/preferred_ip/scan.py --push >> /tmp/cfscan.log 2>&1
```

## 带宽提示

测速阶段总流量 ≈ `top-latency × (speed-seconds × 你的线路速度)`。例如 20 个 IP × 5s × 100Mbps ≈ 1.25 GB/次（峰值，实际取决于各 IP 真实速度）。周更场景可接受；想省流量用 `--no-speedtest`，或调小 `--top-latency` / `--speed-seconds`。

## 输出格式

每行 `IP#COLO-RTTms-SPEEDmbps`，`#` 开头为注释行：

```
# CfIspProxy 优选 IP —— tools/preferred_ip/scan.py 生成，勿手改
# 生成时间 2026-06-22 09:00:00，共 10 个
# 格式 IP#COLO-RTTms-SPEEDmbps
104.16.123.45#NRT-28ms-180.4mbps
...
```

worker.js 的 `parseIpList` 会忽略 `#` 注释、对每行取 `split("#")[0]`，因此只消费裸 IP（端口默认 443，故不写 `:port`），`#` 后的 COLO/延迟/速度仅供人读。

## 开发

```bash
uv sync             # 创建 .venv 并装 pytest（dev-only；脚本运行时零依赖）
uv run pytest -q    # 跑全部单测
```
