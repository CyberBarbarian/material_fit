const { chromium } = require('playwright');

const timeout = setTimeout(() => {
  console.error('Playwright Chromium did not become usable within 30 seconds.');
  process.exit(2);
}, 30000);

(async () => {
  let browser;
  try {
    browser = await chromium.launch({ headless: true });
    const page = await browser.newPage({ viewport: { width: 64, height: 64 } });
    const result = await page.evaluate(() => ({
      userAgent: navigator.userAgent,
      webgl2: Boolean(document.createElement('canvas').getContext('webgl2')),
    }));
    if (!result.webgl2) {
      throw new Error('Chromium started but WebGL2 is unavailable.');
    }
    console.log(JSON.stringify({ ok: true, ...result }));
  } finally {
    if (browser) await browser.close();
    clearTimeout(timeout);
  }
})().catch((error) => {
  clearTimeout(timeout);
  console.error(error && error.stack ? error.stack : String(error));
  process.exit(1);
});
