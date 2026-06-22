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
