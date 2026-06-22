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
