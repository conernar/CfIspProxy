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


import re as _re
from obfuscate import (reorder_functions, encode_disguise, inject_noise,
                       strip_comments, obfuscate, verify)
from inject import Config, inject_config

def test_reorder_preserves_functions():
    src = "function a(){}\nfunction b(){}\nfunction c(){}\nexport default {};\n"
    out = reorder_functions(src, random.Random(3))
    assert sorted(_re.findall(r"function (\w)\(", out)) == ["a", "b", "c"]
    assert out.rstrip().endswith("export default {};")   # 默认导出仍在末尾

def test_encode_disguise_hides_literal():
    src = 'const DISGUISE = `<h1>Welcome to nginx!</h1>`;\n'
    out = encode_disguise(src, random.Random(4))
    assert "Welcome to nginx" not in out          # 明文消失
    assert "String.fromCharCode(" in out
    codes = [int(x) for x in _re.findall(r"\d+", out.split("fromCharCode(")[1].split(")")[0])]
    assert "".join(chr(c) for c in codes) == "<h1>Welcome to nginx!</h1>"  # 解码等价

def test_inject_noise_adds_unused_const():
    src = "const HEX = 1;\n"
    out = inject_noise(src, random.Random(5))
    assert out.count("const ") > src.count("const ")

def test_strip_comments():
    src = "// hi\nconst a=1; /* blk */\nconst b=2;\n"
    out = strip_comments(src)
    assert "hi" not in out and "blk" not in out and "const a=1;" in out

DEV = open("worker/worker.js", encoding="utf-8").read()
CFG = Config(isp_host="1.2.3.4", isp_port=8443, isp_user="u", isp_pass="p",
             preferred_ips_url="https://raw.example/x.txt",
             uuid="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee", ws_path="/secret",
             sub_token="tok123", fallback_ips=["104.16.0.1#fb"])

def test_verify_passes_on_good_output():
    out = obfuscate(inject_config(DEV, CFG), random.Random(11))
    verify(out, CFG)        # 不抛异常即通过

def test_verify_rejects_broken():
    import pytest
    with pytest.raises(Exception):
        verify('const x = 1;', CFG)   # 缺 import/export default/注入值

def test_obfuscate_deterministic_and_unique():
    a = obfuscate(inject_config(DEV, CFG), random.Random(11))
    b = obfuscate(inject_config(DEV, CFG), random.Random(11))
    c = obfuscate(inject_config(DEV, CFG), random.Random(22))
    assert a == b and a != c
