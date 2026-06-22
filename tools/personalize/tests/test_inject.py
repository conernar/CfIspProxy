import re, uuid as uuidmod
from inject import Config, gen_uuid, gen_ws_path, gen_sub_token, render_config_block, inject_config

TEMPLATE = '''import { connect } from "cloudflare:sockets";
const CONFIG = {
  UUID: "12345678-90ab-cdef-1234-567890abcdef",
  WS_PATH: "/ws-REPLACE",
  SUB_TOKEN: "testtoken",
  ISP: { host: "isp.example.com", port: 1080, user: "USER", pass: "PASS" },
  PREFERRED_IPS_URL: "https://raw.githubusercontent.com/USER/REPO/main/data/preferred-ips.txt",
  FALLBACK_IPS: ["104.16.0.1#fallback"],
  SUB_CACHE_TTL: 1800,
};
const HEX = 1;
'''

def _cfg(**kw):
    base = dict(isp_host="1.2.3.4", isp_port=8443, isp_user="u1", isp_pass='p"x',
                preferred_ips_url="https://raw.example/x.txt",
                uuid="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee", ws_path="/secret",
                sub_token="tok123", fallback_ips=["104.16.0.1#fb"])
    base.update(kw)
    return Config(**base)

def test_gen_shapes():
    assert uuidmod.UUID(gen_uuid())            # 合法 UUID
    assert gen_ws_path().startswith("/") and len(gen_ws_path()) > 8
    assert len(gen_sub_token()) >= 16

def test_inject_replaces_all_values():
    out = inject_config(TEMPLATE, _cfg())
    assert '"aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"' in out
    assert '"/secret"' in out and '"tok123"' in out
    assert 'host: "1.2.3.4"' in out and "port: 8443" in out
    assert 'pass: "p\\"x"' in out                 # 含引号的密码被正确转义
    assert '"https://raw.example/x.txt"' in out
    assert "12345678-90ab-cdef" not in out        # DEV 占位已被覆盖
    assert "isp.example.com" not in out
    assert "const HEX = 1;" in out                # CONFIG 之外原样保留
    assert out.count("const CONFIG = {") == 1     # 只替换一处

def test_inject_idempotent_structure():
    once = inject_config(TEMPLATE, _cfg())
    assert once.startswith('import { connect } from "cloudflare:sockets";')
