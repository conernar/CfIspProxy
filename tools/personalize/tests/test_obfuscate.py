import random
from obfuscate import (TOP_LEVEL_SYMBOLS, DENYLIST,
                       strip_named_exports, mask_strings, unmask_strings,
                       rename_identifiers)

def test_strip_named_exports_keeps_default():
    src = ('export function foo(){}\n'
           'export async function bar(){}\n'
           'export default { async fetch(){} };\n')
    out = strip_named_exports(src)
    assert "export function" not in out and "export async function" not in out
    assert "function foo(){}" in out and "async function bar(){}" in out
    assert "export default {" in out          # 默认导出保留

def test_mask_roundtrip():
    src = 'const a = "he\\"llo"; const b = \'x\'; const c = `tpl ${a}`;'
    masked, store = mask_strings(src)
    assert '"' not in masked and "'" not in masked   # 引号串已被掩掉
    assert "`tpl ${a}`" in masked                     # 反引号串不掩（保持可重命名 ${} 内标识符）
    assert unmask_strings(masked, store) == src

def test_rename_consistent_and_safe():
    src = ('const CONFIG = { UUID: "x" };\n'
           'function handleSub(){ return CONFIG.UUID; }\n'
           'const r = handleSub();\n')
    out = rename_identifiers(src, random.Random(1), names=["CONFIG", "handleSub"])
    assert "CONFIG" not in out and "handleSub" not in out   # 两个白名单名全部消失
    # 声明与引用被一致替换：renamed handleSub 同时出现在 function 与调用处
    import re
    m = re.search(r"function (_z[0-9a-f]+)\(", out)
    assert m and out.count(m.group(1)) == 2

def test_rename_protects_user_string_collision():
    # 用户密钥串里恰好含白名单词 "disguise"，绝不能被改
    src = 'const DISGUISE = `html`;\nconst CONFIG = { SUB_TOKEN: "my-disguise-token" };\n'
    out = rename_identifiers(src, random.Random(2), names=["DISGUISE", "CONFIG"])
    assert '"my-disguise-token"' in out        # 字符串内的 disguise 原样保留
    assert "const DISGUISE" not in out          # 代码里的 DISGUISE 已重命名

def test_rename_deterministic():
    src = "const CONFIG = 1; CONFIG;"
    assert (rename_identifiers(src, random.Random(7), ["CONFIG"])
            == rename_identifiers(src, random.Random(7), ["CONFIG"]))

def test_denylist_has_externals():
    for name in ("connect", "fetch", "WebSocketPair", "Response", "URL", "Uint8Array"):
        assert name in DENYLIST
