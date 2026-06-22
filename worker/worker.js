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

export default { async fetch() { return new Response("ok"); } }; // 占位，Task 5/6 替换
