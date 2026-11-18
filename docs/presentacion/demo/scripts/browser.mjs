import { chromium } from 'playwright';
import { preview } from 'vite';

export async function withDemo(run) {
  const server = await preview({ preview: { host: '127.0.0.1', port: 0, open: false } });
  const { port } = server.httpServer.address();
  const origin = `http://127.0.0.1:${port}`;
  let browser;
  try {
    browser = await chromium.launch({
      executablePath: process.env.DEMO_CHROMIUM_PATH || undefined,
    });
    const page = await browser.newPage({
      viewport: { width: 1600, height: 900 },
      deviceScaleFactor: 1.2,
      reducedMotion: 'reduce',
    });
    const external = [];
    const pageErrors = [];
    await page.route('**/*', route => {
      const url = route.request().url();
      if (url.startsWith(`${origin}/`)) return route.continue();
      external.push(url);
      return route.abort();
    });
    page.on('pageerror', error => pageErrors.push(error));
    await page.goto(`${origin}/?capture=1`);
    await page.waitForFunction(() => typeof window.demoSeek === 'function');
    await page.evaluate(() => document.fonts.ready.then(() => undefined));
    await run(page);
    if (external.length) throw new Error('La demo intentó hacer solicitudes de red externas.');
    if (pageErrors.length) throw new AggregateError(pageErrors, 'Error durante la reproducción.');
  } finally {
    await browser?.close();
    await new Promise((resolve, reject) => {
      server.httpServer.close(error => error ? reject(error) : resolve());
    });
  }
}

export async function seek(page, time) {
  await page.evaluate(seconds => window.demoSeek(seconds), time);
}
