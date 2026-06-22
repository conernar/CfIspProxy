# personalize —— 个性化 + 混淆生成器（Stage 2）

把 Stage 1 的 `worker/worker.js` 模板烤进你的配置，再做**纯 Python 轻量混淆**，产出每人**指纹唯一**、可直接粘贴的 `dist/worker.<hex>.js`。

```
worker/worker.js (模板) ──┐
                          ├─► main.py: 交互收集 → 注入CONFIG → 混淆 → verify ─► dist/worker.<hex>.js
你的 ISP账密/优选URL/密钥 ─┘                                                    （+ 终端打印密钥摘要）
```

## 为什么要混淆

同一份 worker 代码被很多人部署，容易被按**代码特征批量识别/封禁**。本工具让每次产物的标识符、函数顺序、噪声、伪装页编码都不同，**指纹唯一化**以规避批量匹配。

> ⚠️ 目的是「指纹唯一」**不是**「密码学保密」。ISP 账密被烤进代码常量，源码泄露即暴露；混淆只抬高批量识别门槛（见设计文档 §10）。

## 用法

```bash
uv run python tools/personalize/main.py
```

逐项交互提问：

- **ISP SOCKS5 主机 / 端口 / 用户名** —— 你购买的 ISP 代理（端口默认 1080）。
- **ISP SOCKS5 密码** —— `getpass` 隐藏输入，不回显、不进 shell 历史。
- **优选列表 raw URL** —— 你仓库 `data/preferred-ips.txt` 的 raw 地址。
- **UUID / WS_PATH / SUB_TOKEN** —— **直接回车 = 自动随机生成**（推荐）。

跑完终端打印生成的 `UUID / WS_PATH / SUB_TOKEN / 订阅URL`，**务必抄下自动生成的密钥**（混淆后在文件里不易找回），客户端配置要用到。

## 输出

只产出一个文件：`dist/worker.<hex>.js`（`dist/` 已 gitignore）。把它整段粘进 CF Workers 编辑器即可，无需构建。

客户端订阅由 worker 的 `/sub` 动态生成（`https://<你的域名>/sub?token=<SUB_TOKEN>`），客户端设置见 `worker/README.md`；本工具**不**另产 client 配置。

## 混淆做了什么（保留 Worker 运行语义）

| 变换 | 说明 |
|---|---|
| 去命名导出 | `export function`→`function`（保留 `export default`） |
| 标识符重命名 | 仅重命名**我们模板的顶层符号白名单**（`CONFIG`/`HEX`/各函数…）；字符串先掩码，绝不动用户密钥值与外部 API |
| 函数重排 | 打乱顶层函数声明顺序（函数声明被提升，安全） |
| 伪装页编码 | `DISGUISE` 的 HTML 改为 `String.fromCharCode(...)`，抹去 "Welcome to nginx" 明文特征 |
| 注入噪声 | 插入若干随机命名的未用 `const` |
| 去注释 | 字符串感知地剥离 `//`、`/* */`（保护 URL / `vless://`） |

**始终保留**：`import { connect } from "cloudflare:sockets";`、`export default { fetch }`、所有 Web/Worker API 标识符。生成后 `verify()` 断言这些不变量；**若本机装了 `node`，会额外跑 `node --check` 做真实语法门**（缺 node 自动跳过，不构成依赖）。

## 参数

| 参数 | 默认 | 说明 |
|---|---|---|
| `--template` | `worker/worker.js` | 输入模板路径 |
| `--out-dir` | `dist/` | 输出目录 |
| `--seed` | 随机 | 混淆随机种子（复现/调试用；不传则每次都不同） |

## 开发

```bash
uv run pytest -q     # 全部单测（inject / obfuscate / generate）
```

运行时**仅标准库零依赖**；pytest 为 dev-only。
