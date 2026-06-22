import { describe, it, expect } from "vitest";
import { parseIpList } from "../worker/worker.js";

describe("parseIpList", () => {
  it("过滤注释与空行、剥离行内备注", () => {
    const txt = "# header\n104.16.0.1\n\n 104.17.0.2:8443 # hk\n#all comment\n104.18.0.3#jp\n";
    expect(parseIpList(txt)).toEqual(["104.16.0.1", "104.17.0.2:8443", "104.18.0.3"]);
  });
});
