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
