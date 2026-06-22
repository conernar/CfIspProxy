import random
from pathlib import Path
from inject import Config
import main as m

DEV = Path("worker/worker.js").read_text(encoding="utf-8")
CFG = Config(isp_host="1.2.3.4", isp_port=8443, isp_user="u", isp_pass="p",
             preferred_ips_url="https://raw.example/x.txt",
             uuid="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee", ws_path="/secret",
             sub_token="tok123", fallback_ips=["104.16.0.1#fb"])

def test_generate_end_to_end_invariants():
    out = m.generate(DEV, CFG, random.Random(11))
    assert 'from "cloudflare:sockets"' in out and "export default" in out
    assert '"/secret"' in out and '"tok123"' in out
    assert "handleProxy" not in out and "buildSingboxConfig" not in out  # 顶层名已混淆
    assert "Welcome to nginx" not in out                                 # 伪装页已编码

def test_generate_unique_per_seed():
    a = m.generate(DEV, CFG, random.Random(1))
    b = m.generate(DEV, CFG, random.Random(2))
    assert a != b and len(a) > 1000 and len(b) > 1000

def test_prompt_config_autogen_on_blank(monkeypatch):
    answers = iter(["1.2.3.4", "8443", "myuser", "https://raw.example/x.txt", "", "", ""])
    cfg = m.prompt_config(input_fn=lambda _="": next(answers),
                          getpass_fn=lambda _="": "secretpass")
    assert cfg.isp_host == "1.2.3.4" and cfg.isp_port == 8443
    assert cfg.isp_pass == "secretpass"
    assert cfg.uuid and cfg.ws_path.startswith("/") and cfg.sub_token  # 空输入→自动生成

def test_write_output(tmp_path):
    p = m.write_output("// hi\n", out_dir=str(tmp_path))
    assert p.exists() and p.read_text().startswith("// hi")
    assert p.name.startswith("worker.") and p.name.endswith(".js")
