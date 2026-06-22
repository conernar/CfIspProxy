# CfIspProxy — Stage 1.5 优选脚本 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

## Context

Stage 1 已交付单文件 `worker/worker.js`，其 `/sub` 会拉取 `data/preferred-ips.txt` 生成 sing-box 订阅，客户端 `urltest` 据此自动轮换。但那份 IP 列表目前是手维护的。**Stage 1.5 造一个墙内 Python 优选脚本**：采样 Cloudflare 边缘 IP、两阶段（延迟过滤 → 测速）筛出最优的，写回 `data/preferred-ips.txt`，并可选 `--push` 自动提交，闭合"墙内 cron 跑 → push → worker `/sub` 拉取 → 客户端更新订阅"这条零运维轮换链路。完整架构见 `docs/superpowers/specs/2026-06-22-cfispproxy-design.md` §7。

**Goal:** `uv run python tools/preferred_ip/scan.py [--push]` 在墙内跑出 top-N 优选 CF IP，写入 `data/preferred-ips.txt`（格式严格满足 Stage 1 `parseIpList`），可选自动 git push。

**Architecture:** 纯 Python 标准库实现核心。`scanner.py` 放核心：纯函数（采样/排序/格式化/HTTP 构造与解析）+ async I/O（测延迟/测速，用 `asyncio.open_connection(ssl=ctx, server_hostname=sni)`）。`scan.py` 是 CLI 编排（argparse + 两阶段 + `--push`），通过依赖注入把测量函数传入以便无网络测试。

**Tech Stack:** Python 3（标准库 only 运行时：`asyncio`/`ssl`/`ipaddress`/`time`/`random`/`argparse`/`subprocess`/`dataclasses`）。项目与依赖用 **uv** 管理（Python 3.13）；测试用 **pytest**（dev-only 依赖，经 `uv run pytest`）。**脚本运行时零外部依赖**——pytest 只在开发期用。

## Global Constraints

- `tools/preferred_ip/` 运行时 **Python 标准库 only，零外部运行时依赖**（不引 httpx / CloudflareSpeedTest）。
- 项目用 uv：根 `pyproject.toml`，`dependencies = []`（运行时零依赖），`[dependency-groups] dev = ["pytest"]`。
- 测试运行：`uv run pytest`（从仓库根）。`pyproject.toml` 里 `[tool.pytest.ini_options] pythonpath = ["tools/preferred_ip"]` 使 `from scanner import ...` / `import scan` 可用。
- 输出 `data/preferred-ips.txt` 必须满足 Stage 1 `worker/worker.js` 的 `parseIpList`：按行、`#` 开头整行=注释、每行有效内容取 `line.split("#")[0].strip()`。端口默认 443 → 输出裸 `IP`（不写 `:port`），备注放 `#` 之后。
- 测试目标统一用通用 CF 端点：SNI/Host = `speed.cloudflare.com`（延迟用 `/cdn-cgi/trace` 取 colo，测速用 `/__down?bytes=N`）。
- 两阶段：阶段①并发测延迟+丢包留 top-M；阶段②对 top-M 时间盒测速；按 速度→延迟 排序取 top-N。
- **绝不因单个 IP 失败而中断整轮**；好 IP 不足 N 时输出现有并警告。
- `--push` 默认 off；核心 采样/排序/格式化 是纯函数且被测；git 仅在 CLI 边界用 subprocess，无变更则跳过 commit。
- 脚本必须在墙内运行才有意义（优选测的是"从本机到该 IP"的质量）；这是运行约束，非代码约束。

## File Structure

| 文件 | 职责 |
|---|---|
| `pyproject.toml`（仓库根） | uv 项目：运行时零依赖、dev=pytest、pytest pythonpath 配置 |
| `tools/preferred_ip/scanner.py` | 核心：纯函数 + async 测量函数 |
| `tools/preferred_ip/scan.py` | CLI：argparse、两阶段编排、`git_push`、`main()` |
| `tools/preferred_ip/cf_ipv4.txt` | 内置 15 条 CF 官方 IPv4 CIDR |
| `tools/preferred_ip/tests/test_scanner.py` | pytest：对纯函数 + 注入式编排做 TDD |
| `tools/preferred_ip/README.md` | 用法、墙内说明、cron 示例、带宽提示 |

> 运行 `uv run pytest` 时 pythonpath 指向 `tools/preferred_ip`，故测试里 `from scanner import ...` / `import scan` 直接可用。`uv.lock`、新增的 `.venv/`/`__pycache__/`/`.pytest_cache/` 纳入 .gitignore（lock 文件提交）。

---

### Task 1: uv 脚手架 + CIDR 加载 + IP 采样（纯函数，TDD）

**Files:** Create `pyproject.toml`、`tools/preferred_ip/cf_ipv4.txt`、`tools/preferred_ip/scanner.py`、`tools/preferred_ip/tests/test_scanner.py`；Modify `.gitignore`

**Interfaces:**
- Produces:
  - `load_cidrs(text: str) -> list[str]`（去注释/空行）
  - `sample_ips(cidrs: list[str], k: int, rng: random.Random) -> list[str]`（按范围大小加权、去重、给定 rng 确定性）

- [ ] **Step 1: 脚手架**

`pyproject.toml`（仓库根）:
```toml
[project]
name = "cfispproxy-tools"
version = "0.0.0"
description = "CfIspProxy 墙内工具：优选 IP 扫描等"
requires-python = ">=3.10"
dependencies = []

[dependency-groups]
dev = ["pytest>=8"]

[tool.pytest.ini_options]
pythonpath = ["tools/preferred_ip"]
testpaths = ["tools/preferred_ip/tests"]
```
追加到 `.gitignore`:
```
.venv/
__pycache__/
.pytest_cache/
```
`tools/preferred_ip/cf_ipv4.txt`:
```
# Cloudflare 官方 IPv4 段（来源 https://www.cloudflare.com/ips-v4，极少变；--refresh-cidr 可重拉）
173.245.48.0/20
103.21.244.0/22
103.22.200.0/22
103.31.4.0/22
141.101.64.0/18
108.162.192.0/18
190.93.240.0/20
188.114.96.0/20
197.234.240.0/22
198.41.128.0/17
162.158.0.0/15
104.16.0.0/13
104.24.0.0/14
172.64.0.0/13
131.0.72.0/22
```
Run: `uv sync`（创建 .venv 并装 pytest）

- [ ] **Step 2: 写失败测试** — `tools/preferred_ip/tests/test_scanner.py`
```python
import random, ipaddress
from scanner import load_cidrs, sample_ips

CIDR_TEXT = "# c\n104.16.0.0/13\n\n131.0.72.0/22\n"

def test_load_cidrs():
    assert load_cidrs(CIDR_TEXT) == ["104.16.0.0/13", "131.0.72.0/22"]

def test_sample_in_range_and_unique():
    cidrs = load_cidrs(CIDR_TEXT)
    nets = [ipaddress.ip_network(c) for c in cidrs]
    ips = sample_ips(cidrs, 50, random.Random(7))
    assert len(ips) == 50
    assert len(set(ips)) == 50  # 去重
    for ip in ips:
        assert any(ipaddress.ip_address(ip) in n for n in nets)

def test_sample_deterministic():
    cidrs = load_cidrs(CIDR_TEXT)
    assert sample_ips(cidrs, 20, random.Random(1)) == sample_ips(cidrs, 20, random.Random(1))
```

- [ ] **Step 3: 跑测试确认失败**
Run: `uv run pytest tools/preferred_ip/tests/test_scanner.py -q`
Expected: FAIL（collection error：`ModuleNotFoundError: scanner`）

- [ ] **Step 4: 实现** — `tools/preferred_ip/scanner.py`
```python
"""CfIspProxy 优选 IP 扫描核心（Python 标准库 only）。"""
import ipaddress, random

def load_cidrs(text):
    return [s.strip() for s in text.splitlines() if s.strip() and not s.strip().startswith("#")]

def sample_ips(cidrs, k, rng):
    nets = [ipaddress.ip_network(c) for c in cidrs]
    weights = [n.num_addresses for n in nets]
    total = sum(weights)
    seen, out, attempts = set(), [], 0
    while len(out) < k and attempts < k * 50:
        attempts += 1
        r = rng.randrange(total)
        net = nets[-1]
        for n, w in zip(nets, weights):
            if r < w:
                net = n
                break
            r -= w
        ip = str(net.network_address + rng.randrange(net.num_addresses))
        if ip not in seen:
            seen.add(ip)
            out.append(ip)
    return out
```

- [ ] **Step 5: 跑测试确认通过**
Run: `uv run pytest tools/preferred_ip/tests/test_scanner.py -q`
Expected: PASS（3 passed）

- [ ] **Step 6: Commit**
```bash
git add pyproject.toml uv.lock .gitignore tools/preferred_ip/cf_ipv4.txt tools/preferred_ip/scanner.py tools/preferred_ip/tests/test_scanner.py
git commit -m "feat(scan): uv project + CF CIDR loader + weighted IP sampler"
```

---

### Task 2: HTTP 构造/解析 + 测速换算（纯函数，TDD）

**Files:** Modify `scanner.py`；Modify `tests/test_scanner.py`

**Interfaces:**
- Produces:
  - `build_http_request(host: str, path: str) -> bytes`（最小 HTTP/1.1 GET，`Connection: close`）
  - `parse_trace_colo(text: str) -> str | None`（从 `/cdn-cgi/trace` 文本取 `colo=`）
  - `compute_mbps(nbytes: int, seconds: float) -> float`

- [ ] **Step 1: 写失败测试**（追加到 `tests/test_scanner.py`）
```python
from scanner import build_http_request, parse_trace_colo, compute_mbps

def test_build_request():
    req = build_http_request("speed.cloudflare.com", "/cdn-cgi/trace").decode()
    assert req.startswith("GET /cdn-cgi/trace HTTP/1.1\r\n")
    assert "Host: speed.cloudflare.com\r\n" in req
    assert "Connection: close\r\n" in req
    assert req.endswith("\r\n\r\n")

def test_parse_colo():
    assert parse_trace_colo("fl=1\ncolo=LHR\nts=1\n") == "LHR"
    assert parse_trace_colo("no colo here") is None

def test_mbps():
    assert compute_mbps(1_000_000, 1.0) == 8.0
    assert compute_mbps(100, 0) == 0.0
```

- [ ] **Step 2: 跑测试确认失败**
Run: `uv run pytest tools/preferred_ip/tests/test_scanner.py -q` → Expected: FAIL

- [ ] **Step 3: 实现**（追加到 `scanner.py`）
```python
def build_http_request(host, path):
    return (f"GET {path} HTTP/1.1\r\nHost: {host}\r\n"
            f"User-Agent: cfispproxy-scan\r\nConnection: close\r\n\r\n").encode()

def parse_trace_colo(text):
    for line in text.splitlines():
        if line.startswith("colo="):
            return line[5:].strip()
    return None

def compute_mbps(nbytes, seconds):
    return (nbytes * 8) / seconds / 1e6 if seconds > 0 else 0.0
```

- [ ] **Step 4: 跑测试确认通过**
Run: `uv run pytest tools/preferred_ip/tests/test_scanner.py -q` → Expected: PASS

- [ ] **Step 5: Commit**
```bash
git add tools/preferred_ip/scanner.py tools/preferred_ip/tests/test_scanner.py
git commit -m "feat(scan): HTTP request builder, colo parser, mbps calc"
```

---

### Task 3: 结果模型 + 排序 + 输出格式化（纯函数，TDD）

**Files:** Modify `scanner.py`（顶部 import 加 `from dataclasses import dataclass`）；Modify `tests/test_scanner.py`

**Interfaces:**
- Produces:
  - `@dataclass Result(ip: str, ok: bool, rtt_ms: float, colo: str|None=None, mbps: float=0.0)`
  - `rank(results: list[Result]) -> list[Result]`（仅 ok；按 mbps 降序、rtt 升序）
  - `format_ip_list(results: list[Result], now: datetime, top_n: int) -> str`（头部注释 + `IP#COLO-RTTms-SPEEDmbps`）

- [ ] **Step 1: 写失败测试**（追加）
```python
from datetime import datetime
from scanner import Result, rank, format_ip_list

def _parse_iplist(text):  # 复刻 worker parseIpList 规则，验证输出可被消费
    out = []
    for l in text.splitlines():
        l = l.strip()
        if not l or l.startswith("#"):
            continue
        ip = l.split("#")[0].strip()
        if ip:
            out.append(ip)
    return out

def _sample_results():
    return [
        Result("1.1.1.1", True, 50.0, "LHR", 90.0),
        Result("2.2.2.2", True, 30.0, "HKG", 90.0),   # 同速,延迟更低 → 排前
        Result("3.3.3.3", True, 10.0, "NRT", 200.0),  # 速度最高 → 第一
        Result("4.4.4.4", False, float("inf"), None, 0.0),  # 失败 → 剔除
    ]

def test_rank():
    assert [r.ip for r in rank(_sample_results())] == ["3.3.3.3", "2.2.2.2", "1.1.1.1"]

def test_format_and_parseable():
    out = format_ip_list(rank(_sample_results()), datetime(2026, 6, 22, 9, 0, 0), top_n=2)
    assert out.splitlines()[0].startswith("# ")               # 头部注释
    assert _parse_iplist(out) == ["3.3.3.3", "2.2.2.2"]       # 取 top2 且可被 parseIpList 提取
    assert "3.3.3.3#NRT-10ms-200.0mbps" in out
```

- [ ] **Step 2: 跑测试确认失败**
Run: `uv run pytest tools/preferred_ip/tests/test_scanner.py -q` → Expected: FAIL

- [ ] **Step 3: 实现**（追加到 `scanner.py`）
```python
from dataclasses import dataclass

@dataclass
class Result:
    ip: str
    ok: bool
    rtt_ms: float
    colo: "str | None" = None
    mbps: float = 0.0

def rank(results):
    return sorted([r for r in results if r.ok], key=lambda r: (-r.mbps, r.rtt_ms))

def format_ip_list(results, now, top_n):
    top = results[:top_n]
    lines = [
        "# CfIspProxy 优选 IP —— tools/preferred_ip/scan.py 生成，勿手改",
        f"# 生成时间 {now:%Y-%m-%d %H:%M:%S}，共 {len(top)} 个",
        "# 格式 IP#COLO-RTTms-SPEEDmbps",
    ]
    for r in top:
        lines.append(f"{r.ip}#{r.colo or '??'}-{round(r.rtt_ms)}ms-{r.mbps:.1f}mbps")
    return "\n".join(lines) + "\n"
```

- [ ] **Step 4: 跑测试确认通过**
Run: `uv run pytest tools/preferred_ip/tests/test_scanner.py -q` → Expected: PASS

- [ ] **Step 5: Commit**
```bash
git add tools/preferred_ip/scanner.py tools/preferred_ip/tests/test_scanner.py
git commit -m "feat(scan): Result model + rank + parseIpList-compatible formatter"
```

---

### Task 4: 异步测延迟 + 测速（I/O；依赖已测纯函数）

**Files:** Modify `scanner.py`（顶部 import 加 `import asyncio, ssl, time`）

**Interfaces:**
- Consumes: `build_http_request`、`parse_trace_colo`、`compute_mbps`、`Result`
- Produces:
  - `async measure_latency(ip, sni, port=443, timeout=2.0) -> Result`
  - `async measure_speed(ip, sni, seconds=5.0, port=443, want_bytes=50_000_000) -> float`（Mbps）

I/O 函数无确定性单测（依赖网络）；其依赖的纯函数已在 Task 2/3 覆盖，整体由 Task 5 注入式编排测 + Verification 真机 smoke 兜底。

- [ ] **Step 1: 实现**（追加到 `scanner.py`）
```python
import asyncio, ssl, time

def _tls_ctx():
    return ssl.create_default_context()

async def measure_latency(ip, sni, port=443, timeout=2.0):
    start = time.perf_counter()
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host=ip, port=port, ssl=_tls_ctx(), server_hostname=sni), timeout)
        rtt_ms = (time.perf_counter() - start) * 1000.0
        colo = None
        try:
            writer.write(build_http_request(sni, "/cdn-cgi/trace"))
            await writer.drain()
            data = await asyncio.wait_for(reader.read(4096), timeout)
            colo = parse_trace_colo(data.decode("latin1", "ignore"))
        except Exception:
            pass
        writer.close()
        try: await writer.wait_closed()
        except Exception: pass
        return Result(ip=ip, ok=True, rtt_ms=rtt_ms, colo=colo)
    except Exception:
        return Result(ip=ip, ok=False, rtt_ms=float("inf"))

async def measure_speed(ip, sni, seconds=5.0, port=443, want_bytes=50_000_000):
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host=ip, port=port, ssl=_tls_ctx(), server_hostname=sni), 5.0)
        writer.write(build_http_request(sni, f"/__down?bytes={want_bytes}"))
        await writer.drain()
        total, start = 0, time.perf_counter()
        while time.perf_counter() - start < seconds:
            try:
                data = await asyncio.wait_for(reader.read(65536), seconds)
            except asyncio.TimeoutError:
                break
            if not data:
                break
            total += len(data)
        elapsed = time.perf_counter() - start
        writer.close()
        try: await writer.wait_closed()
        except Exception: pass
        return compute_mbps(total, elapsed)
    except Exception:
        return 0.0
```

- [ ] **Step 2: 回归（确保 import/语法无误，纯函数测试仍过）**
Run: `uv run pytest -q` → Expected: 之前全部 PASS

- [ ] **Step 3: Commit**
```bash
git add tools/preferred_ip/scanner.py
git commit -m "feat(scan): async TLS latency + time-boxed speed measurement"
```

---

### Task 5: CLI 编排 `scan.py` + `--push`（注入式集成测）

**Files:** Create `tools/preferred_ip/scan.py`；Modify `tests/test_scanner.py`

**Interfaces:**
- Consumes: `scanner` 全部
- Produces:
  - `parse_args(argv) -> Namespace`
  - `async run_scan(args, latency_fn=measure_latency, speed_fn=measure_speed) -> list[Result]`（注入测量函数以便无网络测试；写出文件）
  - `git_push(out_file: str, repo_root: str) -> bool`（无变更返回 False 且不 commit）

- [ ] **Step 1: 写失败测试**（追加到 `tests/test_scanner.py`）
```python
import asyncio, tempfile, os
from unittest import mock
import scan
from scanner import Result

def test_pipeline_with_injected_measures():
    async def fake_latency(ip, sni, port, timeout):
        return Result(ip, True, rtt_ms=float(int(ip.split(".")[-1])), colo="HKG")
    async def fake_speed(ip, sni, seconds, port):
        return 100.0 - float(int(ip.split(".")[-1]))  # 末位越小越快
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "preferred-ips.txt")
        args = scan.parse_args(["-n", "8", "--seed", "3", "-o", "3",
                                "--top-latency", "5", "--out-file", out])
        ranked = asyncio.run(scan.run_scan(args, fake_latency, fake_speed))
        assert os.path.exists(out)
        assert len(ranked) <= 5
        body = [l for l in open(out, encoding="utf-8").read().splitlines() if not l.startswith("#")]
        assert 1 <= len(body) <= 3  # 写出 top-3

def test_git_push_noop_when_no_change():
    with mock.patch("scan.subprocess.run") as m:
        m.return_value = mock.Mock(stdout="", returncode=0)  # status --porcelain 空 = 无变更
        assert scan.git_push("data/preferred-ips.txt", "/repo") is False
        calls = " ".join(str(c) for c in m.call_args_list)
        assert "commit" not in calls  # 未提交
```

- [ ] **Step 2: 跑测试确认失败**
Run: `uv run pytest tools/preferred_ip/tests/test_scanner.py -q` → Expected: FAIL（`ModuleNotFoundError: scan`）

- [ ] **Step 3: 实现** — `tools/preferred_ip/scan.py`
```python
#!/usr/bin/env python3
"""CfIspProxy 优选 IP 扫描 CLI（墙内运行）。"""
import argparse, asyncio, random, subprocess, sys
from datetime import datetime
from pathlib import Path
from scanner import (load_cidrs, sample_ips, rank, format_ip_list,
                     measure_latency, measure_speed)

REPO_ROOT = Path(__file__).resolve().parents[2]
CIDR_FILE = Path(__file__).resolve().parent / "cf_ipv4.txt"
DEFAULT_OUT = REPO_ROOT / "data" / "preferred-ips.txt"

def parse_args(argv):
    p = argparse.ArgumentParser(description="Cloudflare 优选 IP 扫描")
    p.add_argument("-n", "--count", type=int, default=800)
    p.add_argument("--top-latency", type=int, default=20)
    p.add_argument("-o", "--output", type=int, default=10)
    p.add_argument("--concurrency", type=int, default=100)
    p.add_argument("--timeout", type=float, default=2.0)
    p.add_argument("--sni", default="speed.cloudflare.com")
    p.add_argument("--port", type=int, default=443)
    p.add_argument("--speed-seconds", type=float, default=5.0)
    p.add_argument("--speed-concurrency", type=int, default=4)
    p.add_argument("--no-speedtest", action="store_true")
    p.add_argument("--out-file", default=str(DEFAULT_OUT))
    p.add_argument("--refresh-cidr", action="store_true")
    p.add_argument("--push", action="store_true")
    p.add_argument("--seed", type=int, default=None)
    return p.parse_args(argv)

def _read_cidrs(args):
    return load_cidrs(CIDR_FILE.read_text(encoding="utf-8"))  # --refresh-cidr 为 README 增强,默认读内置

async def run_scan(args, latency_fn=measure_latency, speed_fn=measure_speed):
    rng = random.Random(args.seed)
    ips = sample_ips(_read_cidrs(args), args.count, rng)
    sem = asyncio.Semaphore(args.concurrency)
    async def lat(ip):
        async with sem:
            return await latency_fn(ip, args.sni, args.port, args.timeout)
    results = await asyncio.gather(*[lat(ip) for ip in ips])
    good = sorted([r for r in results if r.ok], key=lambda r: r.rtt_ms)[: args.top_latency]
    print(f"[阶段①] {len(ips)} 采样 → {len(good)} 个连通,进入测速", file=sys.stderr)
    if not args.no_speedtest:
        ssem = asyncio.Semaphore(args.speed_concurrency)
        async def spd(r):
            async with ssem:
                r.mbps = await speed_fn(r.ip, args.sni, args.speed_seconds, args.port)
            return r
        good = list(await asyncio.gather(*[spd(r) for r in good]))
    ranked = rank(good)
    content = format_ip_list(ranked, datetime.now(), args.output)
    Path(args.out_file).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out_file).write_text(content, encoding="utf-8")
    print(f"[完成] 写出 {min(args.output, len(ranked))} 个优选 IP → {args.out_file}", file=sys.stderr)
    return ranked

def git_push(out_file, repo_root):
    subprocess.run(["git", "-C", repo_root, "add", out_file], check=True)
    status = subprocess.run(["git", "-C", repo_root, "status", "--porcelain", out_file],
                            capture_output=True, text=True).stdout
    if not status.strip():
        print("[push] 无变更,跳过", file=sys.stderr)
        return False
    msg = f"chore: refresh preferred IPs ({datetime.now():%Y-%m-%d %H:%M})"
    subprocess.run(["git", "-C", repo_root, "commit", "-m", msg], check=True)
    subprocess.run(["git", "-C", repo_root, "push"], check=True)
    print("[push] 已提交并推送", file=sys.stderr)
    return True

def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    asyncio.run(run_scan(args))
    if args.push:
        git_push(args.out_file, str(REPO_ROOT))

if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 跑测试确认通过**
Run: `uv run pytest -q` → Expected: 全部 PASS（sampling/http/output/run/git）

- [ ] **Step 5: Commit**
```bash
git add tools/preferred_ip/scan.py tools/preferred_ip/tests/test_scanner.py
git commit -m "feat(scan): CLI orchestration (two-phase) + git --push"
```

---

### Task 6: README + cron 示例（文档）

**Files:** Create `tools/preferred_ip/README.md`

- [ ] **Step 1:** 写 `tools/preferred_ip/README.md`，含：
  - 一句话作用 + 数据流图（墙内 scan → push → worker `/sub` → 客户端更新订阅）。
  - **必须墙内运行**说明（优选测的是本机到 IP 的质量；墙外 runner 无意义）。
  - 用法：`uv run python tools/preferred_ip/scan.py`（默认采样 800 / 延迟留 20 / 测速 / 输出 top-10 → `data/preferred-ips.txt`）。
  - 全部 flag 速查表（`-n/--top-latency/-o/--concurrency/--timeout/--sni/--port/--speed-seconds/--speed-concurrency/--no-speedtest/--out-file/--push/--seed`）。
  - **cron 示例**（每周一 4:00 跑并推送）：`0 4 * * 1 cd /home/rias/CfIspProxy && uv run python tools/preferred_ip/scan.py --push >> /tmp/cfscan.log 2>&1`。
  - 带宽提示：测速 ≈ top-latency × (speed-seconds × 线路速度)，周更可控；省流量用 `--no-speedtest`。
  - 输出格式说明 + 它如何被 worker `parseIpList` 消费。
- [ ] **Step 2: 全量回归** `uv run pytest -q` → Expected: PASS
- [ ] **Step 3: Commit**
```bash
git add tools/preferred_ip/README.md
git commit -m "docs(scan): usage, 墙内 note, cron example, bandwidth guide"
```

---

## Self-Review

- **Spec(§7) 覆盖**：拉 CF 段=Task1(cf_ipv4.txt+load_cidrs)；采样=Task1；阶段①延迟+colo=Task4 measure_latency；阶段②测速=Task4 measure_speed；排序+输出=Task3；CLI 两阶段编排=Task5；`--push` 闭环=Task5 git_push；墙内/cron=Task6。
- **占位扫描**：各步含真实代码/命令/期望；`--refresh-cidr` 标为 README 增强（默认读内置文件，不留半成品逻辑）。
- **类型一致**：`Result(ip,ok,rtt_ms,colo,mbps)` 贯穿 Task3/4/5；`measure_latency/speed` 签名与 `run_scan` 注入点一致；`format_ip_list` 输出经 `_parse_iplist`（复刻 worker 规则）验证可被消费。
- **风险**：I/O 函数无纯单测 → 注入式 `run_scan` 测试覆盖编排，真机 smoke 兜底数据通路。

## Verification（端到端）

1. 单元：`uv run pytest -q` 全绿。
2. 真机 smoke（快、省流量）：`uv run python tools/preferred_ip/scan.py -n 80 --no-speedtest --out-file /tmp/ips.txt` → `/tmp/ips.txt` 出现若干 `IP#COLO-RTTms-...`，证明真实 TLS 握手 + colo 抓取通。
3. 完整墙内跑：`uv run python tools/preferred_ip/scan.py` → `data/preferred-ips.txt` 更新为 top-10（按速度）。
4. 闭环：仓库根 `uv run python tools/preferred_ip/scan.py --push` → 自动 commit+push；约 30 分钟后（缓存）worker `/sub` 返回新 IP；客户端"更新订阅"即得。

## Execution Handoff

完成后剩 **Stage 2（`main.py` 个性化 + 混淆器）**，单独 spec→plan→实现。
