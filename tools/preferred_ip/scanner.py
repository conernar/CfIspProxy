"""CfIspProxy 优选 IP 扫描核心（Python 标准库 only）。"""
import ipaddress, random
from dataclasses import dataclass

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
