// @ts-check
import { defineConfig } from 'astro/config';
import node from '@astrojs/node';

// On-demand server rendering, not static: the archive changes the moment a
// page is archived, so a static build would go stale. The Node adapter runs
// the SSR server the backend's sibling container launches. This tier only
// ever speaks HTTP to the Arciv API; it never opens the database or reads
// saved/ directly.
export default defineConfig({
  output: 'server',
  adapter: node({ mode: 'standalone' }),
  server: { host: true, port: Number(process.env.PORT ?? 4321) },
});
