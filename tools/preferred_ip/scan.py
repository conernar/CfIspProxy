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
