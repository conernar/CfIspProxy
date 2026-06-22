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
