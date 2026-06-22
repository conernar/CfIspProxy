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
