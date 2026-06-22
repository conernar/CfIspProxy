"""CfIspProxy Stage2 —— 把用户配置烤进 worker 模板 CONFIG 区（标准库 only）。"""
import json, re, secrets, uuid
from dataclasses import dataclass, field


@dataclass
class Config:
    isp_host: str
    isp_port: int
    isp_user: str
    isp_pass: str
    preferred_ips_url: str
    uuid: str
    ws_path: str
    sub_token: str
    fallback_ips: list = field(default_factory=lambda: ["104.16.0.1#fallback"])
    sub_cache_ttl: int = 1800


def gen_uuid():
    return str(uuid.uuid4())


def gen_ws_path():
    return "/" + secrets.token_urlsafe(12)


def gen_sub_token():
    return secrets.token_urlsafe(16)


def render_config_block(cfg):
    j = json.dumps
    fb = "[" + ", ".join(j(x) for x in cfg.fallback_ips) + "]"
    return (
        "const CONFIG = {\n"
        f"  UUID: {j(cfg.uuid)},\n"
        f"  WS_PATH: {j(cfg.ws_path)},\n"
        f"  SUB_TOKEN: {j(cfg.sub_token)},\n"
        f"  ISP: {{ host: {j(cfg.isp_host)}, port: {int(cfg.isp_port)}, "
        f"user: {j(cfg.isp_user)}, pass: {j(cfg.isp_pass)} }},\n"
        f"  PREFERRED_IPS_URL: {j(cfg.preferred_ips_url)},\n"
        f"  FALLBACK_IPS: {fb},\n"
        f"  SUB_CACHE_TTL: {int(cfg.sub_cache_ttl)},\n"
        "};"
    )


_CONFIG_RE = re.compile(r"const CONFIG = \{.*?\n\};", re.S)


def inject_config(template, cfg):
    new = render_config_block(cfg)
    out, n = _CONFIG_RE.subn(lambda _: new, template, count=1)
    if n != 1:
        raise ValueError("模板中未找到唯一的 CONFIG 块")
    return out
