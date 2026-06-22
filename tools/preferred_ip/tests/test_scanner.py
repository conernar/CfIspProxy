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
