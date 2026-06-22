# worker.js —— 粘贴部署指南

`worker/worker.js` 是 **唯一交付物**：零依赖单文件，把 VLESS-over-WS 流量经 SOCKS5(账密) 转发到你的 ISP 代理出口，并在 `/sub` 生成 sing-box 订阅。

```
客户端 → 优选CF边缘IP → 本Worker → SOCKS5(ISP代理) → 目标网站
                                                      ↑目标看到的是 ISP 出口 IP
```

## 一、部署（复制粘贴，约 3 分钟）

1. 登录 [Cloudflare Dashboard](https://dash.cloudflare.com) → **Workers & Pages** → **Create** → **Create Worker** → 命名 → **Deploy**。
2. 进入该 Worker → **Edit code**，把 `worker/worker.js` **全文**粘贴覆盖。
3. 改文件顶部 `CONFIG` 区，**替换全部占位值**（见文件内逐项注释）：
   - `UUID`、`WS_PATH`、`SUB_TOKEN`
   - `ISP.{host,port,user,pass}` —— 你买的 ISP 代理 SOCKS5 账密
   - `PREFERRED_IPS_URL` —— 指向你自己仓库的 `data/preferred-ips.txt` raw 地址
4. **Deploy**。
5. **Settings → Domains & Routes** 绑定一个自定义域名（不要直接用 `*.workers.dev`，国内基本不通）。该域名就是客户端节点里的 `host`/`sni`。

> ⚠️ ISP 代理须为 **公网非 Cloudflare IP、非 25 端口**，且 **账密认证**（CF Worker 出口 IP 不固定，IP 白名单不可用）。

## 二、取订阅 / 配客户端

浏览器或客户端订阅地址填：

- sing-box 配置：`https://<你的域名>/sub?token=<SUB_TOKEN>`
- v2rayN 通用订阅（base64 vless 链接）：`https://<你的域名>/sub?token=<SUB_TOKEN>&format=links`

订阅返回 N 个节点（每个对应一个优选 IP，`host`/`sni`/`uuid`/`path` 都相同），sing-box 的 `urltest` 会自动测速选最快、某个 IP 被墙时自动跳过。

## 三、优选 IP 自动轮换（闭环）

```
墙内机器 cron 跑优选脚本 → 覆写 data/preferred-ips.txt → git push
        → worker /sub 运行时拉取（带 30 分钟缓存，失败回退 FALLBACK_IPS）
        → 客户端"更新订阅"即得最新优选 IP
```

`data/preferred-ips.txt` 格式：一行一个 `IP[:port][#备注]`，`#` 开头整行为注释。
（墙内优选脚本属 Stage 1.5，单独实现。）

## 四、限制与风险

- **CF 免费额度**：10 万请求/日，足够个人自用。
- **协议**：v1 仅 TCP（VLESS command≠1 拒绝），不含 UDP。
- **ToS**：在 Workers 上跑代理可能违反 Cloudflare ToS，个人小流量自用风险较低，自行承担。

## 五、本地开发 / 测试（可选，不影响粘贴部署）

```bash
npm install
npm test          # vitest + @cloudflare/vitest-pool-workers，全部用例
npm run dev       # wrangler dev，本地 http://127.0.0.1:8787
```

`/` 返回伪装的 nginx 欢迎页；`/sub?token=testtoken` 返回 sing-box 配置（DEV 占位值）。
