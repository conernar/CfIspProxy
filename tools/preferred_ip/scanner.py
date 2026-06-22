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
