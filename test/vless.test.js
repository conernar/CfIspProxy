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
