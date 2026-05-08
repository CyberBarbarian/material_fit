#!/usr/bin/env node
/*
 * Prototype Laya screenshot capture helper.
 *
 * Usage:
 *   node tools/material_fit/vision/capture_laya.js capture_request.json output.png
 *
 * Request JSON fields:
 *   url: Laya preview/debug scene URL.
 *   viewport: { width, height } optional, default 900x600.
 *   waitUntil: puppeteer goto wait condition, default networkidle2.
 *   waitMs: extra wait time after page load.
 *   readySelector: optional CSS selector that must appear before capture.
 *   readyFunction: optional JS function string returning true when scene is ready.
 *   applyParamsFunction: optional JS function string. It receives params JSON and
 *     can call into the Laya debug scene to apply a material candidate.
 *   paramsPath: optional candidate params JSON path.
 *   screenshotSelector: optional CSS selector to clip; otherwise full viewport.
 */

const fs = require('fs');
const path = require('path');

async function main() {
  const requestPath = process.argv[2];
  const outputPath = process.argv[3];
  if (!requestPath || !outputPath) {
    console.error('Usage: node capture_laya.js <capture_request.json> <output.png>');
    process.exit(2);
  }

  const request = JSON.parse(fs.readFileSync(requestPath, 'utf8'));
  const puppeteer = require(request.puppeteerModule || 'puppeteer');
  const viewport = request.viewport || { width: 900, height: 600 };
  const browser = await puppeteer.launch({
    headless: request.headless !== false,
    args: request.args || ['--disable-gpu', '--no-sandbox'],
  });

  try {
    const page = await browser.newPage();
    await page.setViewport({ width: viewport.width || 900, height: viewport.height || 600 });
    await page.goto(request.url, { waitUntil: request.waitUntil || 'networkidle2', timeout: request.timeoutMs || 60000 });

    if (request.readySelector) {
      await page.waitForSelector(request.readySelector, { timeout: request.timeoutMs || 60000 });
    }
    if (request.readyFunction) {
      await page.waitForFunction(request.readyFunction, { timeout: request.timeoutMs || 60000 });
    }

    if (request.applyParamsFunction && request.paramsPath) {
      const params = JSON.parse(fs.readFileSync(request.paramsPath, 'utf8'));
      await page.evaluate(new Function('params', request.applyParamsFunction), params);
    }

    if (request.waitMs) {
      await new Promise(resolve => setTimeout(resolve, request.waitMs));
    }

    fs.mkdirSync(path.dirname(outputPath), { recursive: true });
    if (request.screenshotSelector) {
      const element = await page.$(request.screenshotSelector);
      if (!element) throw new Error(`screenshotSelector not found: ${request.screenshotSelector}`);
      await element.screenshot({ path: outputPath });
    } else {
      await page.screenshot({ path: outputPath });
    }
  } finally {
    await browser.close();
  }
}

main().catch(error => {
  console.error(error && error.stack ? error.stack : String(error));
  process.exit(1);
});