import { defineWorkersConfig } from "@cloudflare/vitest-pool-workers/config";

export default defineWorkersConfig({
  test: {
    poolOptions: {
      workers: {
        main: "./worker/worker.js",
        // nodejs_compat is required by @cloudflare/vitest-pool-workers itself.
        // The shipped worker.js uses no Node APIs, so the dashboard-paste
        // deployment (and wrangler.toml) intentionally needs no such flag.
        miniflare: {
          compatibilityDate: "2024-09-23",
          compatibilityFlags: ["nodejs_compat"],
        },
      },
    },
  },
});
