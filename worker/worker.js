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
  return (HEX[b[o]] + HEX[b[o + 1]] + HEX[b[o + 2]] + HEX[b[o + 3]] + "-" + HEX[b[o + 4]] + HEX[b[o + 5]] + "-" +
    HEX[b[o + 6]] + HEX[b[o + 7]] + "-" + HEX[b[o + 8]] + HEX[b[o + 9]] + "-" +
    HEX[b[o + 10]] + HEX[b[o + 11]] + HEX[b[o + 12]] + HEX[b[o + 13]] + HEX[b[o + 14]] + HEX[b[o + 15]]).toLowerCase();
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

export function buildSocks5Greeting() { return new Uint8Array([0x05, 0x01, 0x02]); }

export function buildSocks5Auth(user, pass) {
  const e = new TextEncoder(), u = e.encode(user), p = e.encode(pass);
  const out = new Uint8Array(3 + u.length + p.length);
  out[0] = 0x01; out[1] = u.length; out.set(u, 2); out[2 + u.length] = p.length; out.set(p, 3 + u.length);
  return out;
}

// VLESS addressType (1=IPv4,2=domain,3=IPv6) → SOCKS5 atyp (1=IPv4,3=domain,4=IPv6)
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

export function parseIpList(text) {
  return text.split(/\r?\n/).map(l => l.trim()).filter(l => l && !l.startsWith("#"))
    .map(l => l.split("#")[0].trim()).filter(Boolean);
}

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
    return {
      type: "vless", tag: `node-${i + 1}`, server: addr, server_port: Number(port), uuid,
      tls: { enabled: true, server_name: host },
      transport: { type: "ws", path: wsPath, headers: { Host: host } },
    };
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

// ===== ③ 数据面 =====
function makeReadableWebSocketStream(ws, earlyHeader) {
  let cancelled = false;
  return new ReadableStream({
    start(c) {
      ws.addEventListener("message", e => { if (!cancelled) c.enqueue(e.data); });
      ws.addEventListener("close", () => { if (!cancelled) { try { c.close(); } catch {} } });
      ws.addEventListener("error", e => c.error(e));
      if (earlyHeader) { // 0-RTT early data: base64url in sec-websocket-protocol
        try {
          const s = atob(earlyHeader.replace(/-/g, "+").replace(/_/g, "/"));
          const u = Uint8Array.from(s, ch => ch.charCodeAt(0));
          if (u.length) c.enqueue(u.buffer);
        } catch {}
      }
    },
    cancel() { cancelled = true; try { ws.close(); } catch {} },
  });
}

// 缓冲读取：处理 SOCKS5 各步回复可能粘包/拆包
function makeSocks5Reader(reader) {
  let buf = new Uint8Array(0);
  const pull = async () => {
    const { value, done } = await reader.read();
    if (done) return false;
    const n = new Uint8Array(buf.length + value.byteLength);
    n.set(buf); n.set(new Uint8Array(value), buf.length); buf = n;
    return true;
  };
  return {
    async readAtLeast(n) {
      while (buf.length < n) { if (!await pull()) throw new Error("socks5: eof"); }
      const out = buf.slice(0, n); buf = buf.slice(n); return out;
    },
    async readConnectReply() {
      while (buf.length < 5) { if (!await pull()) throw new Error("socks5: eof"); }
      const r = parseSocks5ConnectReply(buf);
      if (!r.ok) return { ok: false };
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
    socket.readable.pipeTo(new WritableStream({
      write: c => server.send(c),
      close: () => { try { server.close(); } catch {} },
      abort: () => { try { server.close(); } catch {} },
    })).catch(() => { try { server.close(); } catch {} });
    (async () => {
      const w = socket.writable.getWriter();
      try {
        for (;;) { const { value, done } = await wsReader.read(); if (done) break; await w.write(new Uint8Array(value)); }
      } catch {} finally { try { await w.close(); } catch {} }
    })();
  } catch (e) {
    server.close(1011, String(e));
  }
  return new Response(null, { status: 101, webSocket: client });
}

// ===== ④ 控制面 + 伪装页 =====
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

// ===== ② fetch 路由分发 =====
export default {
  async fetch(request) {
    const url = new URL(request.url);
    if (request.headers.get("Upgrade") === "websocket" && url.pathname === CONFIG.WS_PATH) return handleProxy(request);
    if (request.method === "GET" && url.pathname === "/sub") return handleSub(request);
    return disguise();
  },
};
