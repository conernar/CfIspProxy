# CfIspProxy — Stage 1 (worker.js) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

## Context

CfIspProxy 用一个域名 + 一个 Cloudflare 免费账号的 Worker，搭一条「穿墙 + 高质量出口 IP」代理链路：客户端连干净的 CF 边缘 IP → Worker → 经 SOCKS5(账密) 转发到用户已购买的 ISP 代理 → 目标网站（目标看到 ISP 出口 IP）。本计划只覆盖 **Stage 1 = 单文件 `worker.js`**（数据面 + 控制面 `/sub`），是后续优选脚本与 `main.py` 混淆器的地基。完整架构见 `docs/superpowers/specs/2026-06-22-cfispproxy-design.md`。

**Goal:** 产出一个零依赖、可直接粘贴进 CF Workers 的单文件 `worker.js`：把 VLESS-over-WS 流量经 SOCKS5(账密) 转发到 ISP 出口，并在 `/sub` 用 GitHub 上的优选 IP 列表生成 sing-box 订阅（客户端 `urltest` 自动轮换）。

**Architecture:** 单文件 ES module。文件顶部 `CONFIG` 常量；纯逻辑（VLESS 头解析、SOCKS5 字节构造、IP 列表解析、订阅拼接）抽成**命名导出函数**便于单测（Workers 运行时只用 `export default`，忽略其余命名导出）；`fetch` 是瘦路由器，分发到数据面 / 控制面 / 伪装页。

**Tech Stack:** Cloudflare Workers（`cloudflare:sockets`）、JavaScript(ESM)；开发期：vitest + `@cloudflare/vitest-pool-workers` + wrangler（仅 devDependencies，不进交付物）。

## Global Constraints

- 交付物 `worker/worker.js` **单文件、零运行时依赖**，唯一 import 为 `import { connect } from "cloudflare:sockets"`；可直接粘贴进 CF Dashboard。
- 协议固定 **VLESS**，传输 **ws + tls**；**v1 仅 TCP**（VLESS command≠1 一律拒绝，不做 UDP）。
- 配置经**文件顶部 `CONFIG` 常量**（非环境变量）。仓库提交版用明显的 DEV 占位值，且占位值需让测试可断言。
- 上游 ISP 为 **SOCKS5 + 账密认证（RFC 1929）**；ISP 端点须为公网非 CF IP、非 25 端口（`cloudflare:sockets` 限制）。
- `/sub` 必须校验 `?token == CONFIG.SUB_TOKEN`；校验失败与任何未知路径一律返回**伪装页**（普通 200），不暴露身份。
- 优选 IP 经 `fetch(CONFIG.PREFERRED_IPS_URL, { cf: { cacheTtl: 1800, cacheEverything: true } })` 拉取；失败回退 `CONFIG.FALLBACK_IPS`，保证 `/sub` 永不空。
- N 个订阅节点仅 `address` 不同，`uuid/host/sni/path` 全等于本 worker 的域名与配置。
- `compatibility_date` ≥ `2024-09-23`（`cloudflare:sockets` 可用）。
- 纯函数命名导出仅供 dev/test；不得依赖 Workers 专有全局在 import 期执行。

## File Structure

| 文件 | 职责 |
|---|---|
| `worker/worker.js` | **唯一交付物**：CONFIG + 纯逻辑命名导出 + 数据面 + 控制面 + `fetch` 路由 + 伪装页 |
| `worker/README.md` | 粘贴部署指南（填哪些常量、CF 操作步骤、配客户端） |
| `data/preferred-ips.txt` | 示例优选 IP 列表（被 `/sub` 拉取，墙内脚本周更）；格式 `IP[:port][#备注]` |
| `vitest.config.js` | `defineWorkersConfig`，`main: ./worker/worker.js` |
| `wrangler.toml` | dev 用：`main`、`compatibility_date`（本地 `wrangler dev` / 可选 `wrangler deploy`） |
| `package.json` | devDeps：vitest、@cloudflare/vitest-pool-workers、wrangler；scripts.test |
| `.gitignore` | `node_modules/`、`dist/` |
| `test/vless.test.js` | VLESS 头解析单测 |
| `test/socks5.test.js` | SOCKS5 字节构造 / 回复解析单测 |
| `test/iplist.test.js` | `parseIpList` 单测 |
| `test/subscription.test.js` | `buildVlessLinks` / `buildSingboxConfig` 单测 |
| `test/routing.test.js` | `fetch` 路由 + `/sub` 集成测（`SELF.fetch` + `fetchMock`） |

> `worker.js` 用 `export default { fetch }`（CF 必需）+ 额外命名导出纯函数（被测试 import；CF 运行时忽略）。

---

### Task 1: 项目脚手架 + VLESS 头解析（含工具链落地）

**Files:**
- Create: `package.json`, `vitest.config.js`, `wrangler.toml`, `.gitignore`
- Create: `worker/worker.js`（先放 CONFIG + `uuidStringify` + `parseVlessHeader`）
- Test: `test/vless.test.js`

**Interfaces:**
- Produces:
  - `uuidStringify(bytes: Uint8Array, offset=0): string`（小写带连字符 UUID）
  - `parseVlessHeader(buffer: ArrayBuffer|Uint8Array, expectedUuid: string): { hasError: true, message } | { hasError: false, version, addressType: 1|2|3, address: string, port: number, rawDataIndex: number }`

- [ ] **Step 1: 脚手架文件**

`package.json`:
```json
{
  "name": "cfispproxy",
  "private": true,
  "type": "module",
  "scripts": { "test": "vitest run", "dev": "wrangler dev" },
  "devDependencies": {
    "@cloudflare/vitest-pool-workers": "^0.5.0",
    "vitest": "^2.1.0",
    "wrangler": "^3.80.0"
  }
}
```
`vitest.config.js`:
```js
import { defineWorkersConfig } from "@cloudflare/vitest-pool-workers/config";
export default defineWorkersConfig({
  test: {
    poolOptions: {
      workers: { main: "./worker/worker.js", miniflare: { compatibilityDate: "2024-09-23" } },
    },
  },
});
```
`wrangler.toml`:
```toml
name = "cfispproxy"
main = "worker/worker.js"
compatibility_date = "2024-09-23"
```
`.gitignore`:
```
node_modules/
dist/
```
Run: `npm install`

- [ ] **Step 2: 写失败测试** — `test/vless.test.js`

```js
import { describe, it, expect } from "vitest";
import { uuidStringify, parseVlessHeader } from "../worker/worker.js";

const UUID = "12345678-90ab-cdef-1234-567890abcdef";
function uuidBytes(u) { return Uint8Array.from(u.replace(/-/g, "").match(/../g).map(h => parseInt(h, 16))); }

// version(0) | uuid(16) | optLen(0) | cmd(1=TCP) | port(0x01bb=443) | atyp(2=domain) | len | "example.com"
function tcpDomainHeader(uuid, host, port) {
  const h = new TextEncoder().encode(host);
  const out = [0x00, ...uuidBytes(uuid), 0x00, 0x01, port >> 8, port & 0xff, 0x02, h.length, ...h, 0xAA, 0xBB];
  return new Uint8Array(out).buffer;
}

describe("parseVlessHeader", () => {
  it("解析 TCP + 域名目标", () => {
    const r = parseVlessHeader(tcpDomainHeader(UUID, "example.com", 443), UUID);
    expect(r.hasError).toBe(false);
    expect(r.addressType).toBe(2);
    expect(r.address).toBe("example.com");
    expect(r.port).toBe(443);
    // rawDataIndex 指向头之后的 payload(0xAA,0xBB)
    expect(new Uint8Array(tcpDomainHeader(UUID, "example.com", 443).slice(r.rawDataIndex))).toEqual(new Uint8Array([0xAA, 0xBB]));
  });
  it("UUID 不匹配 → hasError", () => {
    const r = parseVlessHeader(tcpDomainHeader(UUID, "a.com", 80), "00000000-0000-0000-0000-000000000000");
    expect(r.hasError).toBe(true);
  });
  it("UDP(command=2) → 拒绝", () => {
    const b = new Uint8Array(tcpDomainHeader(UUID, "a.com", 80)); b[18] = 0x02; // cmd byte
    expect(parseVlessHeader(b.buffer, UUID).hasError).toBe(true);
  });
});
```

- [ ] **Step 3: 跑测试确认失败**
Run: `npm test -- test/vless.test.js`
Expected: FAIL（`parseVlessHeader` 未定义 / 未导出）

- [ ] **Step 4: 实现** — `worker/worker.js`

```js
import { connect } from "cloudflare:sockets";

// ===== ① CONFIG（DEV 占位；部署前替换 / Stage2 由 main.py 烤入）=====
const CONFIG = {
  UUID: "12345678-90ab-cdef-1234-567890abcdef",
  WS_PATH: "/ws-REPLACE",
  SUB_TOKEN: "testtoken",
  ISP: { host: "isp.example.com", port: 1080, user: "USER", pass: "PASS" },
  PREFERRED_IPS_URL: "https://raw.githubusercontent.com/USER/REPO/main/data/preferred-ips.txt",
  FALLBACK_IPS: ["104.16.0.1#fallback"],
  SUB_CACHE_TTL: 1800,
};

const HEX = Array.from({ length: 256 }, (_, i) => (i + 256).toString(16).slice(1));
export function uuidStringify(b, o = 0) {
  return (HEX[b[o]]+HEX[b[o+1]]+HEX[b[o+2]]+HEX[b[o+3]]+"-"+HEX[b[o+4]]+HEX[b[o+5]]+"-"+
    HEX[b[o+6]]+HEX[b[o+7]]+"-"+HEX[b[o+8]]+HEX[b[o+9]]+"-"+
    HEX[b[o+10]]+HEX[b[o+11]]+HEX[b[o+12]]+HEX[b[o+13]]+HEX[b[o+14]]+HEX[b[o+15]]).toLowerCase();
}

export function parseVlessHeader(buffer, expectedUuid) {
  const bytes = buffer instanceof Uint8Array ? buffer : new Uint8Array(buffer);
  if (bytes.byteLength < 24) return { hasError: true, message: "header too short" };
  const version = bytes[0];
  if (uuidStringify(bytes, 1) !== expectedUuid.toLowerCase()) return { hasError: true, message: "invalid user" };
  const optLength = bytes[17];
  const command = bytes[18 + optLength];
  if (command !== 1) return { hasError: true, message: `unsupported command ${command} (TCP only)` };
  let i = 18 + optLength + 1;
  const port = (bytes[i] << 8) | bytes[i + 1]; i += 2;
  const addressType = bytes[i++];
  let address = "";
  if (addressType === 1) { address = bytes.slice(i, i + 4).join("."); i += 4; }
  else if (addressType === 2) { const len = bytes[i++]; address = new TextDecoder().decode(bytes.slice(i, i + len)); i += len; }
  else if (addressType === 3) { const s = []; for (let j = 0; j < 8; j++) { s.push(((bytes[i] << 8) | bytes[i + 1]).toString(16)); i += 2; } address = s.join(":"); }
  else return { hasError: true, message: `invalid addressType ${addressType}` };
  return { hasError: false, version, addressType, address, port, rawDataIndex: i };
}

export default { async fetch() { return new Response("ok"); } }; // 占位，Task 5/6 替换
```

- [ ] **Step 5: 跑测试确认通过**
Run: `npm test -- test/vless.test.js`
Expected: PASS（3/3）

- [ ] **Step 6: Commit**
```bash
git add package.json vitest.config.js wrangler.toml .gitignore worker/worker.js test/vless.test.js
git commit -m "feat(worker): scaffold + VLESS header parser with tests"
```

---

### Task 2: SOCKS5 字节构造与回复解析

**Files:** Modify `worker/worker.js`（追加导出）；Test `test/socks5.test.js`

**Interfaces:**
- Produces:
  - `buildSocks5Greeting(): Uint8Array` → `[0x05,0x01,0x02]`
  - `buildSocks5Auth(user: string, pass: string): Uint8Array`（RFC1929：`0x01|ulen|user|plen|pass`）
  - `buildSocks5Connect(addressType: 1|2|3, address: string, port: number): Uint8Array`（VLESS atyp→SOCKS5 atyp：1→1, 2→3, 3→4）
  - `parseSocks5AuthReply(bytes: Uint8Array): { ok: boolean }`
  - `parseSocks5ConnectReply(bytes: Uint8Array): { ok: boolean, consumed: number }`

- [ ] **Step 1: 写失败测试** — `test/socks5.test.js`

```js
import { describe, it, expect } from "vitest";
import { buildSocks5Greeting, buildSocks5Auth, buildSocks5Connect, parseSocks5AuthReply, parseSocks5ConnectReply } from "../worker/worker.js";

describe("socks5", () => {
  it("greeting = 05 01 02", () => { expect([...buildSocks5Greeting()]).toEqual([0x05, 0x01, 0x02]); });
  it("auth 编码 user/pass", () => {
    expect([...buildSocks5Auth("ab", "xyz")]).toEqual([0x01, 2, 0x61, 0x62, 3, 0x78, 0x79, 0x7a]);
  });
  it("connect 域名 → atyp 3", () => {
    const b = buildSocks5Connect(2, "a.cn", 443);
    expect([...b.slice(0, 4)]).toEqual([0x05, 0x01, 0x00, 0x03]); // CONNECT, atyp=domain
    expect(b[4]).toBe(4);                                          // len "a.cn"
    expect([...b.slice(-2)]).toEqual([0x01, 0xbb]);                // port 443
  });
  it("connect IPv4 → atyp 1", () => {
    const b = buildSocks5Connect(1, "1.2.3.4", 80);
    expect([...b.slice(0, 4)]).toEqual([0x05, 0x01, 0x00, 0x01]);
    expect([...b.slice(4, 8)]).toEqual([1, 2, 3, 4]);
  });
  it("auth reply 00 = ok", () => { expect(parseSocks5AuthReply(Uint8Array.from([0x01, 0x00])).ok).toBe(true); });
  it("connect reply 解析 consumed(IPv4)", () => {
    const r = parseSocks5ConnectReply(Uint8Array.from([0x05, 0x00, 0x00, 0x01, 0, 0, 0, 0, 0, 0]));
    expect(r.ok).toBe(true); expect(r.consumed).toBe(10);
  });
  it("connect reply rep!=0 → fail", () => { expect(parseSocks5ConnectReply(Uint8Array.from([0x05, 0x01, 0x00, 0x01])).ok).toBe(false); });
});
```

- [ ] **Step 2: 跑测试确认失败**
Run: `npm test -- test/socks5.test.js`  → Expected: FAIL（函数未定义）

- [ ] **Step 3: 实现**（追加到 `worker/worker.js`）
```js
export function buildSocks5Greeting() { return new Uint8Array([0x05, 0x01, 0x02]); }

export function buildSocks5Auth(user, pass) {
  const e = new TextEncoder(), u = e.encode(user), p = e.encode(pass);
  const out = new Uint8Array(3 + u.length + p.length);
  out[0] = 0x01; out[1] = u.length; out.set(u, 2); out[2 + u.length] = p.length; out.set(p, 3 + u.length);
  return out;
}

export function buildSocks5Connect(addressType, address, port) {
  let atyp, addr;
  if (addressType === 1) { atyp = 0x01; addr = Uint8Array.from(address.split(".").map(Number)); }
  else if (addressType === 2) { atyp = 0x03; const d = new TextEncoder().encode(address); addr = new Uint8Array(1 + d.length); addr[0] = d.length; addr.set(d, 1); }
  else { atyp = 0x04; addr = new Uint8Array(16); address.split(":").forEach((h, k) => { const v = parseInt(h || "0", 16); addr[k * 2] = v >> 8; addr[k * 2 + 1] = v & 0xff; }); }
  const out = new Uint8Array(4 + addr.length + 2);
  out[0] = 0x05; out[1] = 0x01; out[2] = 0x00; out[3] = atyp; out.set(addr, 4);
  out[4 + addr.length] = port >> 8; out[5 + addr.length] = port & 0xff;
  return out;
}

export function parseSocks5AuthReply(b) { return { ok: b.length >= 2 && b[1] === 0x00 }; }

export function parseSocks5ConnectReply(b) {
  if (b.length < 4 || b[1] !== 0x00) return { ok: false, consumed: 0 };
  const atyp = b[3];
  const addrLen = atyp === 0x01 ? 4 : atyp === 0x04 ? 16 : atyp === 0x03 ? 1 + b[4] : -1;
  if (addrLen < 0) return { ok: false, consumed: 0 };
  return { ok: true, consumed: 4 + addrLen + 2 };
}
```

- [ ] **Step 4: 跑测试确认通过**
Run: `npm test -- test/socks5.test.js` → Expected: PASS（7/7）

- [ ] **Step 5: Commit**
```bash
git add worker/worker.js test/socks5.test.js
git commit -m "feat(worker): SOCKS5 greeting/auth/connect builders + reply parsers"
```

---

### Task 3: 优选 IP 列表解析

**Files:** Modify `worker/worker.js`；Create `data/preferred-ips.txt`；Test `test/iplist.test.js`

**Interfaces:**
- Produces: `parseIpList(text: string): string[]`（去空行/`#`整行注释/行内`#备注`，保留 `IP` 或 `IP:port`）

- [ ] **Step 1: 写失败测试** — `test/iplist.test.js`
```js
import { describe, it, expect } from "vitest";
import { parseIpList } from "../worker/worker.js";
describe("parseIpList", () => {
  it("过滤注释与空行、剥离行内备注", () => {
    const txt = "# header\n104.16.0.1\n\n 104.17.0.2:8443 # hk\n#all comment\n104.18.0.3#jp\n";
    expect(parseIpList(txt)).toEqual(["104.16.0.1", "104.17.0.2:8443", "104.18.0.3"]);
  });
});
```

- [ ] **Step 2: 跑测试确认失败**
Run: `npm test -- test/iplist.test.js` → Expected: FAIL

- [ ] **Step 3: 实现**（追加）+ 示例数据
```js
export function parseIpList(text) {
  return text.split(/\r?\n/).map(l => l.trim()).filter(l => l && !l.startsWith("#"))
    .map(l => l.split("#")[0].trim()).filter(Boolean);
}
```
`data/preferred-ips.txt`:
```
# CfIspProxy 优选 IP 列表（墙内脚本周更后 git push；worker /sub 拉取）
# 格式：IP[:port][#备注]
104.16.0.1#示例-请替换为你优选脚本产出的IP
104.17.0.2
104.18.0.3
```

- [ ] **Step 4: 跑测试确认通过**
Run: `npm test -- test/iplist.test.js` → Expected: PASS

- [ ] **Step 5: Commit**
```bash
git add worker/worker.js test/iplist.test.js data/preferred-ips.txt
git commit -m "feat(worker): preferred-ip list parser + sample data"
```

---

### Task 4: 订阅生成（vless 链接 + sing-box 配置）

**Files:** Modify `worker/worker.js`；Test `test/subscription.test.js`

**Interfaces:**
- Produces:
  - `buildVlessLinks({ host, uuid, wsPath, ips }): string`（base64 of `vless://...` 多行）
  - `buildSingboxConfig({ host, uuid, wsPath, ips }): object`（含 `urltest` 的完整最小 sing-box 配置；N 个 vless outbound 仅 `server` 不同）

- [ ] **Step 1: 写失败测试** — `test/subscription.test.js`
```js
import { describe, it, expect } from "vitest";
import { buildVlessLinks, buildSingboxConfig } from "../worker/worker.js";
const args = { host: "h.com", uuid: "u", wsPath: "/p", ips: ["1.1.1.1", "2.2.2.2:8443"] };

describe("subscription", () => {
  it("vless 链接：每 IP 一条，仅 address 变化", () => {
    const lines = atob(buildVlessLinks(args)).split("\n");
    expect(lines.length).toBe(2);
    expect(lines[0]).toContain("@1.1.1.1:443");
    expect(lines[1]).toContain("@2.2.2.2:8443");
    expect(lines[0]).toContain("sni=h.com");
    expect(lines[0]).toContain("type=ws");
    expect(lines[0]).toContain("host=h.com");
  });
  it("sing-box：N 个 vless outbound + 一个 urltest", () => {
    const cfg = buildSingboxConfig(args);
    const vless = cfg.outbounds.filter(o => o.type === "vless");
    const urltest = cfg.outbounds.find(o => o.type === "urltest");
    expect(vless.length).toBe(2);
    expect(vless[0].server).toBe("1.1.1.1");
    expect(vless[1].server_port).toBe(8443);
    expect(vless[0].tls.server_name).toBe("h.com");
    expect(vless[0].transport).toEqual({ type: "ws", path: "/p", headers: { Host: "h.com" } });
    expect(urltest.outbounds).toEqual(vless.map(o => o.tag));
  });
});
```

- [ ] **Step 2: 跑测试确认失败**
Run: `npm test -- test/subscription.test.js` → Expected: FAIL

- [ ] **Step 3: 实现**（追加）
```js
function splitAddr(entry) { const [addr, port = "443"] = entry.split(":"); return { addr, port }; }

export function buildVlessLinks({ host, uuid, wsPath, ips }) {
  const lines = ips.map((e, i) => {
    const { addr, port } = splitAddr(e);
    const q = new URLSearchParams({ encryption: "none", security: "tls", sni: host, type: "ws", host, path: wsPath });
    return `vless://${uuid}@${addr}:${port}?${q}#${encodeURIComponent(`${host}-${i + 1}`)}`;
  });
  return btoa(lines.join("\n"));
}

export function buildSingboxConfig({ host, uuid, wsPath, ips }) {
  const nodes = ips.map((e, i) => {
    const { addr, port } = splitAddr(e);
    return { type: "vless", tag: `node-${i + 1}`, server: addr, server_port: Number(port), uuid,
      tls: { enabled: true, server_name: host },
      transport: { type: "ws", path: wsPath, headers: { Host: host } } };
  });
  const tags = nodes.map(n => n.tag);
  return {
    log: { level: "warn" },
    inbounds: [{ type: "mixed", tag: "in", listen: "127.0.0.1", listen_port: 2080 }],
    outbounds: [
      { type: "urltest", tag: "auto", outbounds: tags, url: "https://www.gstatic.com/generate_204", interval: "3m", tolerance: 50 },
      ...nodes,
      { type: "selector", tag: "proxy", outbounds: ["auto", ...tags] },
      { type: "direct", tag: "direct" },
    ],
    route: { final: "proxy" },
  };
}
```

- [ ] **Step 4: 跑测试确认通过**
Run: `npm test -- test/subscription.test.js` → Expected: PASS

- [ ] **Step 5: Commit**
```bash
git add worker/worker.js test/subscription.test.js
git commit -m "feat(worker): vless-link + sing-box subscription builders"
```

---

### Task 5: 数据面 —— WS → SOCKS5(ISP) → 目标 转发

**Files:** Modify `worker/worker.js`（加 `makeReadableWebSocketStream`、`Socks5Reader`、`handleProxy`）

**Interfaces:**
- Consumes: `parseVlessHeader`、`buildSocks5Greeting/Auth/Connect`、`parseSocks5AuthReply/ConnectReply`、`connect`
- Produces: `async handleProxy(request: Request): Promise<Response>`（返回 `101` + client WebSocket）

本任务的字节逻辑已被 Task 1/2 单测覆盖；编排（WS↔socket 管道、SOCKS5 握手时序、回复粘包）以 **routing 集成测（Task 6）+ 手动 e2e（Verification）** 为准。

- [ ] **Step 1: 实现**（追加到 `worker/worker.js`）
```js
function makeReadableWebSocketStream(ws, earlyHeader) {
  let cancelled = false;
  return new ReadableStream({
    start(c) {
      ws.addEventListener("message", e => { if (!cancelled) c.enqueue(e.data); });
      ws.addEventListener("close", () => { if (!cancelled) try { c.close(); } catch {} });
      ws.addEventListener("error", e => c.error(e));
      if (earlyHeader) { // 0-RTT early data: base64url in sec-websocket-protocol
        try { const s = atob(earlyHeader.replace(/-/g, "+").replace(/_/g, "/")); const u = Uint8Array.from(s, ch => ch.charCodeAt(0)); if (u.length) c.enqueue(u.buffer); } catch {}
      }
    },
    cancel() { cancelled = true; try { ws.close(); } catch {} },
  });
}

// 缓冲读取：处理 SOCKS5 各步回复可能粘包/拆包
function makeSocks5Reader(reader) {
  let buf = new Uint8Array(0);
  const pull = async () => { const { value, done } = await reader.read(); if (done) return false; const n = new Uint8Array(buf.length + value.byteLength); n.set(buf); n.set(new Uint8Array(value), buf.length); buf = n; return true; };
  return {
    async readAtLeast(n) { while (buf.length < n) { if (!await pull()) throw new Error("socks5: eof"); } const out = buf.slice(0, n); buf = buf.slice(n); return out; },
    async readConnectReply() {
      while (buf.length < 5) { if (!await pull()) throw new Error("socks5: eof"); }
      const r = parseSocks5ConnectReply(buf);
      if (!r.ok && buf.length >= (r.consumed || 5)) return { ok: false };
      while (buf.length < r.consumed) { if (!await pull()) throw new Error("socks5: eof"); }
      buf = buf.slice(r.consumed); return { ok: true };
    },
    leftover() { return buf; },
  };
}

async function handleProxy(request) {
  const [client, server] = Object.values(new WebSocketPair());
  server.accept();
  const wsStream = makeReadableWebSocketStream(server, request.headers.get("sec-websocket-protocol") || "");
  const wsReader = wsStream.getReader();
  try {
    const first = await wsReader.read();
    if (first.done) { server.close(); return new Response(null, { status: 101, webSocket: client }); }
    const firstBytes = new Uint8Array(first.value);
    const h = parseVlessHeader(firstBytes, CONFIG.UUID);
    if (h.hasError) { server.close(1011, h.message); return new Response(null, { status: 101, webSocket: client }); }

    const socket = connect({ hostname: CONFIG.ISP.host, port: CONFIG.ISP.port });
    await socket.opened;
    const sWriter = socket.writable.getWriter();
    const sReader = makeSocks5Reader(socket.readable.getReader());

    await sWriter.write(buildSocks5Greeting());
    const g = await sReader.readAtLeast(2);
    if (!(g[0] === 0x05 && g[1] === 0x02)) throw new Error("socks5: method rejected");
    await sWriter.write(buildSocks5Auth(CONFIG.ISP.user, CONFIG.ISP.pass));
    if (!parseSocks5AuthReply(await sReader.readAtLeast(2)).ok) throw new Error("socks5: auth failed");
    await sWriter.write(buildSocks5Connect(h.addressType, h.address, h.port));
    if (!(await sReader.readConnectReply()).ok) throw new Error("socks5: connect failed");

    server.send(new Uint8Array([h.version, 0]));                       // VLESS 响应头
    const initial = firstBytes.slice(h.rawDataIndex);
    if (initial.length) await sWriter.write(initial);
    const carry = sReader.leftover();
    if (carry.length) server.send(carry);                             // 极少见的早到目标数据
    sWriter.releaseLock();

    // 双向 pipe
    socket.readable.pipeTo(new WritableStream({ write: c => server.send(c), close: () => server.close(), abort: () => server.close() })).catch(() => server.close());
    (async () => {
      const w = socket.writable.getWriter();
      try { for (;;) { const { value, done } = await wsReader.read(); if (done) break; await w.write(new Uint8Array(value)); } } catch {} finally { try { await w.close(); } catch {} }
    })();
  } catch (e) {
    server.close(1011, String(e));
  }
  return new Response(null, { status: 101, webSocket: client });
}
```
> 注：`socket.writable` 在 pipe 阶段重新 `getWriter()`（握手阶段已 `releaseLock`）。

- [ ] **Step 2: 全量单测回归**（确保未破坏纯函数导出）
Run: `npm test` → Expected: 之前所有用例仍 PASS（数据面无独立单测，靠 Task 6 + 手动 e2e）

- [ ] **Step 3: Commit**
```bash
git add worker/worker.js
git commit -m "feat(worker): data plane — WS to SOCKS5(ISP) tunnel"
```

---

### Task 6: 控制面 `/sub` + `fetch` 路由 + 伪装页（集成测）

**Files:** Modify `worker/worker.js`（加 `getPreferredIPs`、`handleSub`、替换 `export default fetch`、`disguise`）；Test `test/routing.test.js`

**Interfaces:**
- Consumes: `parseIpList`、`buildSingboxConfig`、`buildVlessLinks`、`handleProxy`
- Produces:
  - `async getPreferredIPs(): Promise<string[]>`（fetch 带 `cf.cacheTtl`，失败回退 `CONFIG.FALLBACK_IPS`）
  - `default.fetch(request)`：WS 升级且路径==WS_PATH→`handleProxy`；`GET /sub?token=SUB_TOKEN`→`handleSub`；否则 `disguise()`

- [ ] **Step 1: 写失败测试** — `test/routing.test.js`
```js
import { describe, it, expect, beforeAll } from "vitest";
import { SELF, fetchMock } from "cloudflare:test";

beforeAll(() => { fetchMock.activate(); fetchMock.disableNetConnect(); });

describe("routing", () => {
  it("未知路径 → 伪装页 200，且不含订阅特征", async () => {
    const res = await SELF.fetch("https://x.com/");
    expect(res.status).toBe(200);
    expect(await res.text()).not.toContain("vless://");
  });
  it("/sub 错误 token → 伪装页（不泄露）", async () => {
    const res = await SELF.fetch("https://x.com/sub?token=wrong");
    expect(res.status).toBe(200);
    expect(await res.text()).not.toContain("outbounds");
  });
  it("/sub 正确 token → sing-box 配置（含 urltest）", async () => {
    fetchMock.get("https://raw.githubusercontent.com").intercept({ path: /preferred-ips/ }).reply(200, "1.1.1.1\n2.2.2.2:8443");
    const res = await SELF.fetch("https://x.com/sub?token=testtoken");
    const cfg = await res.json();
    expect(cfg.outbounds.some(o => o.type === "urltest")).toBe(true);
    expect(cfg.outbounds.filter(o => o.type === "vless").length).toBe(2);
  });
  it("/sub?format=links → base64 vless 链接", async () => {
    fetchMock.get("https://raw.githubusercontent.com").intercept({ path: /preferred-ips/ }).reply(200, "1.1.1.1");
    const res = await SELF.fetch("https://x.com/sub?token=testtoken&format=links");
    expect(atob(await res.text())).toContain("vless://");
  });
});
```
> `CONFIG.PREFERRED_IPS_URL` 的 host 须为 `https://raw.githubusercontent.com`，与 mock 对齐（占位值已满足）。

- [ ] **Step 2: 跑测试确认失败**
Run: `npm test -- test/routing.test.js` → Expected: FAIL（默认 fetch 仍是占位 `"ok"`）

- [ ] **Step 3: 实现**（追加并替换 `export default`）
```js
const DISGUISE = `<!DOCTYPE html><html><head><title>Welcome to nginx!</title></head><body><h1>Welcome to nginx!</h1></body></html>`;
function disguise() { return new Response(DISGUISE, { status: 200, headers: { "content-type": "text/html; charset=utf-8" } }); }

export async function getPreferredIPs() {
  try {
    const r = await fetch(CONFIG.PREFERRED_IPS_URL, { cf: { cacheTtl: CONFIG.SUB_CACHE_TTL, cacheEverything: true } });
    if (!r.ok) return CONFIG.FALLBACK_IPS;
    const ips = parseIpList(await r.text());
    return ips.length ? ips : CONFIG.FALLBACK_IPS;
  } catch { return CONFIG.FALLBACK_IPS; }
}

async function handleSub(request) {
  const url = new URL(request.url);
  if (url.searchParams.get("token") !== CONFIG.SUB_TOKEN) return disguise();
  const ips = await getPreferredIPs();
  const args = { host: url.hostname, uuid: CONFIG.UUID, wsPath: CONFIG.WS_PATH, ips };
  if (url.searchParams.get("format") === "links") {
    return new Response(buildVlessLinks(args), { headers: { "content-type": "text/plain; charset=utf-8" } });
  }
  return new Response(JSON.stringify(buildSingboxConfig(args), null, 2), { headers: { "content-type": "application/json; charset=utf-8" } });
}

export default {
  async fetch(request) {
    const url = new URL(request.url);
    if (request.headers.get("Upgrade") === "websocket" && url.pathname === CONFIG.WS_PATH) return handleProxy(request);
    if (request.method === "GET" && url.pathname === "/sub") return handleSub(request);
    return disguise();
  },
};
```
（删除 Task 1 的占位 `export default`。）

- [ ] **Step 4: 跑测试确认通过**
Run: `npm test` → Expected: 全部 PASS（vless/socks5/iplist/subscription/routing）

- [ ] **Step 5: Commit**
```bash
git add worker/worker.js test/routing.test.js
git commit -m "feat(worker): /sub control plane + fetch router + disguise page"
```

---

### Task 7: 部署文档 + 占位常量收尾

**Files:** Create `worker/README.md`；Modify `worker/worker.js`（CONFIG 顶部加填写说明注释，保持 DEV 占位可被测试断言）

- [ ] **Step 1:** 在 `worker/worker.js` 的 CONFIG 上方加注释块，逐项说明：`UUID`(生成方式)、`WS_PATH`(保密、以 `/` 开头)、`SUB_TOKEN`、`ISP.{host,port,user,pass}`、`PREFERRED_IPS_URL`(指向你 repo 的 raw 地址)、`FALLBACK_IPS`。强调"部署前替换全部占位值"。
- [ ] **Step 2:** 写 `worker/README.md`：
  - 部署：CF Dashboard → Workers & Pages → Create Worker → 粘贴 `worker/worker.js` 全文 → 改顶部 CONFIG → Deploy → 绑定自定义域名。
  - 客户端：浏览器访问 `https://你的域名/sub?token=<SUB_TOKEN>` 得 sing-box 配置；`&format=links` 得 v2rayN 订阅。
  - 优选闭环：墙内跑优选脚本 → 覆写 `data/preferred-ips.txt` → `git push` → `/sub` 自动取新 IP（Stage 1.5 单独做）。
  - 限制：ISP 须公网非 CF IP、非 25 端口；CF 免费版额度；ToS 风险自担。
- [ ] **Step 3:** 全量回归 `npm test` → Expected: PASS
- [ ] **Step 4: Commit**
```bash
git add worker/worker.js worker/README.md
git commit -m "docs(worker): config comments + paste-to-deploy guide"
```

---

## Self-Review

- **Spec 覆盖**：数据面(§5③)=Task1/2/5；控制面 `/sub`(§5④,§6)=Task3/4/6；伪装页/SUB_TOKEN/UUID 鉴权(§10)=Task1/6；fallback+缓存(§6)=Task6；非目标 UDP=Task1 拒绝；优选脚本(§7)/main.py(§8)=非本计划（Stage 1.5/2）。
- **占位扫描**：各步均含真实代码/命令/期望输出，无 TBD。
- **类型一致**：`parseVlessHeader` 返回的 `addressType/address/port/rawDataIndex` 被 Task5 使用；`buildSocks5Connect(addressType,...)` 直接吃 VLESS atyp；`buildSingboxConfig/buildVlessLinks` 参数 `{host,uuid,wsPath,ips}` 在 Task4/6 一致；`getPreferredIPs`→`string[]`→builders 一致。
- **风险**：数据面 pipe/SOCKS5 时序无纯单测覆盖 → 由 Task6 集成测（`SELF.fetch`+`fetchMock`）覆盖路由/`/sub`，数据通路由下方手动 e2e 兜底。

## Verification（端到端，人工）

1. `npm test` 全绿（5 个测试文件）。
2. 本地：`npx wrangler dev`，浏览器开 `http://127.0.0.1:8787/`(伪装页)、`/sub?token=testtoken`(JSON 配置)。
3. 真部署：CF Dashboard 粘贴 `worker.js`，填入真实 UUID/WS_PATH/SUB_TOKEN/ISP 账密/你的 `PREFERRED_IPS_URL`，Deploy，绑定域名。
4. 取订阅：`https://域名/sub?token=<SUB_TOKEN>` 导入 sing-box；客户端 `urltest` 选中节点。
5. 连通性：客户端开启代理后访问 `https://api.ipify.org` → **返回的出口 IP 应为你的 ISP 代理 IP**（证明链路 客户端→CF→worker→SOCKS5→ISP→目标 全通）。
6. 轮换：改 `data/preferred-ips.txt` 后 `git push`，约 30 分钟后（或换缓存）`/sub` 节点列表更新；客户端更新订阅即得新 IP。

## Execution Handoff

Stage 1 完成后，下一步是 Stage 1.5（墙内优选脚本 + cron/push）与 Stage 2（`main.py` 混淆生成器），各自独立 spec→plan→实现。
