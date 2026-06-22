#!/usr/bin/env python3
"""CfIspProxy Stage2 —— 交互式个性化 + 混淆生成器（标准库 only）。"""
import argparse, getpass, random, secrets, sys
from pathlib import Path
from inject import Config, gen_uuid, gen_ws_path, gen_sub_token, inject_config
from obfuscate import obfuscate, verify

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TEMPLATE = REPO_ROOT / "worker" / "worker.js"


def generate(template, cfg, rng):
    out = obfuscate(inject_config(template, cfg), rng)
    verify(out, cfg)
    return out


def _ask(input_fn, label, default=None, gen=None):
    hint = "（回车=自动生成）" if gen else (f"（默认 {default}）" if default is not None else "")
    while True:
        v = input_fn(f"{label}{hint}: ").strip()
        if v:
            return v
        if gen:
            return gen()
        if default is not None:
            return default
        print("  此项必填。", file=sys.stderr)


def prompt_config(input_fn=input, getpass_fn=getpass.getpass):
    host = _ask(input_fn, "ISP SOCKS5 主机")
    port = int(_ask(input_fn, "ISP SOCKS5 端口", default="1080"))
    user = _ask(input_fn, "ISP SOCKS5 用户名")
    pw = getpass_fn("ISP SOCKS5 密码（输入隐藏）: ").strip()
    url = _ask(input_fn, "优选列表 raw URL")
    uuid_v = _ask(input_fn, "UUID", gen=gen_uuid)
    ws = _ask(input_fn, "WS_PATH", gen=gen_ws_path)
    if not ws.startswith("/"):
        ws = "/" + ws
    tok = _ask(input_fn, "SUB_TOKEN", gen=gen_sub_token)
    return Config(isp_host=host, isp_port=port, isp_user=user, isp_pass=pw,
                  preferred_ips_url=url, uuid=uuid_v, ws_path=ws, sub_token=tok)


def write_output(text, out_dir="dist"):
    d = Path(out_dir)
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"worker.{secrets.token_hex(4)}.js"
    p.write_text(text, encoding="utf-8")
    return p


def print_summary(cfg, out_path):
    print("\n✅ 生成完成 →", out_path)
    print(f"   UUID:      {cfg.uuid}")
    print(f"   WS_PATH:   {cfg.ws_path}")
    print(f"   SUB_TOKEN: {cfg.sub_token}")
    print(f"   订阅URL:    https://<你的Worker域名>/sub?token={cfg.sub_token}")
    print("   提示: 客户端 vless 节点的 uuid/path 必须与上面一致；"
          "域名换成你 CF Worker 绑定的域名。粘贴 dist 文件到 CF Workers 编辑器即可。")


def main(argv=None):
    ap = argparse.ArgumentParser(description="CfIspProxy 个性化+混淆生成器")
    ap.add_argument("--template", default=str(DEFAULT_TEMPLATE))
    ap.add_argument("--out-dir", default=str(REPO_ROOT / "dist"))
    ap.add_argument("--seed", type=int, default=None)
    args = ap.parse_args(sys.argv[1:] if argv is None else argv)
    template = Path(args.template).read_text(encoding="utf-8")
    cfg = prompt_config()
    out = generate(template, cfg, random.Random(args.seed))
    p = write_output(out, args.out_dir)
    print_summary(cfg, p)


if __name__ == "__main__":
    main()
