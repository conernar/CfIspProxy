"""CfIspProxy Stage2 混淆核心（标准库 only）。只动我们自己模板的顶层符号。"""
import re

TOP_LEVEL_SYMBOLS = [
    "CONFIG", "HEX", "uuidStringify", "parseVlessHeader", "buildSocks5Greeting",
    "buildSocks5Auth", "buildSocks5Connect", "parseSocks5AuthReply",
    "parseSocks5ConnectReply", "parseIpList", "splitAddr", "buildVlessLinks",
    "buildSingboxConfig", "makeReadableWebSocketStream", "makeSocks5Reader",
    "handleProxy", "DISGUISE", "disguise", "getPreferredIPs", "handleSub",
]
# 护栏：以下标识符绝不能被改、且生成后必须仍在
DENYLIST = {
    "connect", "fetch", "import", "from", "export", "default", "async", "function",
    "WebSocketPair", "WebSocket", "Response", "ReadableStream", "WritableStream",
    "URL", "URLSearchParams", "Uint8Array", "TextEncoder", "TextDecoder",
    "Object", "Array", "Number", "String", "JSON", "Boolean", "Error",
    "atob", "btoa", "parseInt", "encodeURIComponent",
}


def strip_named_exports(text):
    return re.sub(r"\bexport\s+(async\s+)?function\b",
                  lambda m: (m.group(1) or "") + "function", text)


_STR_RE = re.compile(r'"(?:[^"\\]|\\.)*"' r"|'(?:[^'\\]|\\.)*'")


def mask_strings(text):
    store = []

    def repl(m):
        store.append(m.group(0))
        return f"\x00S{len(store) - 1}\x00"

    return _STR_RE.sub(repl, text), store


def unmask_strings(text, store):
    return re.sub(r"\x00S(\d+)\x00", lambda m: store[int(m.group(1))], text)


def _new_name(rng):
    return "_z" + "".join(rng.choice("0123456789abcdef") for _ in range(6))


def rename_identifiers(text, rng, names=TOP_LEVEL_SYMBOLS):
    masked, store = mask_strings(text)
    used = set()
    for old in names:
        new = _new_name(rng)
        while new in used:
            new = _new_name(rng)
        used.add(new)
        masked = re.sub(r"\b" + re.escape(old) + r"\b", new, masked)
    return unmask_strings(masked, store)


import json, shutil, subprocess, tempfile, os

_FUNC_RE = re.compile(r"^(?:async\s+)?function\s+\w+\s*\([^)]*\)\s*\{", re.M)


def reorder_functions(text, rng):
    # 提取顶层 function 声明（用花括号配平切块），打乱后按原位置回填
    blocks, spans = [], []
    for m in _FUNC_RE.finditer(text):
        i = text.index("{", m.start())
        depth, j = 0, i
        while j < len(text):
            if text[j] == "{":
                depth += 1
            elif text[j] == "}":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        spans.append((m.start(), j + 1))
        blocks.append(text[m.start():j + 1])
    if len(blocks) < 2:
        return text
    order = list(range(len(blocks)))
    rng.shuffle(order)
    shuffled = [blocks[k] for k in order]
    out, prev = [], 0
    for (s, e), blk in zip(spans, shuffled):
        out.append(text[prev:s])
        out.append(blk)
        prev = e
    out.append(text[prev:])
    return "".join(out)


_DISGUISE_RE = re.compile(r"const DISGUISE = `([^`]*)`;")


def encode_disguise(text, rng):
    def repl(m):
        codes = ",".join(str(ord(ch)) for ch in m.group(1))
        return f"const DISGUISE = String.fromCharCode({codes});"

    return _DISGUISE_RE.sub(repl, text, count=1)


def inject_noise(text, rng):
    n = rng.randint(2, 5)
    decls = "".join(f"const _n{rng.randrange(16**6):06x} = {rng.randrange(1 << 30)};\n"
                    for _ in range(n))
    return decls + text


def strip_comments(text):
    # 字符级扫描：在字符串/模板字面量内的 // 与 /* 不算注释（保护 URL、vless:// 等）
    out, i, n = [], 0, len(text)
    while i < n:
        c = text[i]
        if c in "\"'`":                       # 进入字符串：原样拷贝到闭合引号
            quote = c
            out.append(c)
            i += 1
            while i < n:
                d = text[i]
                out.append(d)
                if d == "\\" and i + 1 < n:    # 转义：连下一个字符一起拷贝
                    out.append(text[i + 1])
                    i += 2
                    continue
                i += 1
                if d == quote:
                    break
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "/":   # 行注释
            while i < n and text[i] != "\n":
                i += 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "*":   # 块注释
            i += 2
            while i < n and not (text[i] == "*" and i + 1 < n and text[i + 1] == "/"):
                i += 1
            i += 2
            continue
        out.append(c)
        i += 1
    return re.sub(r"\n{3,}", "\n\n", "".join(out))


def obfuscate(text, rng):
    text = strip_named_exports(text)
    text = encode_disguise(text, rng)
    text = rename_identifiers(text, rng)
    text = reorder_functions(text, rng)
    text = inject_noise(text, rng)
    text = strip_comments(text)
    return text


def verify(text, cfg):
    if 'from "cloudflare:sockets"' not in text or "connect" not in text:
        raise ValueError("verify: 缺少 cloudflare:sockets connect 导入")
    if "export default" not in text:
        raise ValueError("verify: 缺少 export default")
    for name in ("WebSocketPair", "Response", "fetch", "URL"):
        if name not in text:
            raise ValueError(f"verify: 外部 API {name} 丢失")
    for val in (cfg.uuid, cfg.ws_path, cfg.sub_token, cfg.isp_host,
                cfg.isp_user, cfg.isp_pass, cfg.preferred_ips_url):
        if json.dumps(val)[1:-1] not in text:
            raise ValueError(f"verify: 注入值丢失 {val!r}")
    node = shutil.which("node")
    if node:
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                         encoding="utf-8") as f:
            f.write(text)
            path = f.name
        try:
            r = subprocess.run([node, "--check", path], capture_output=True, text=True)
            if r.returncode != 0:
                raise ValueError("verify: node --check 失败:\n" + r.stderr)
        finally:
            os.unlink(path)
