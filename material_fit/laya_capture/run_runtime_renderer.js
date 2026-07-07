const { chromium } = require('playwright-chromium');
const path = require('path');
const fs = require('fs');
const http = require('http');
const { spawnSync } = require('child_process');

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const repoRoot = path.resolve(__dirname, '..', '..');
  const defaultEngineRoot = process.env.LOCALAPPDATA
    ? path.join(process.env.LOCALAPPDATA, 'Programs', 'LayaAirIDE', 'resources', 'engine', 'libs')
    : '';
  const engineRoot = args.engineRoot || path.resolve(process.env.LAYA_ENGINE_LIBS || defaultEngineRoot || 'resources/engine/libs');
  const pagePath = args.page || path.resolve(__dirname, 'runtime_renderer.html');
  const defaultProjectRoot = path.resolve(repoRoot, 'examples', 'fish_laya_project');
  const projectRoot = args.projectRoot || (fs.existsSync(defaultProjectRoot) ? defaultProjectRoot : '');
  const defaultScene = projectRoot ? path.resolve(projectRoot, 'assets', 'resources', 'game.ls') : '';
  const scene = args.scene || (defaultScene && fs.existsSync(defaultScene) ? defaultScene : '');
  const server = args.server || 'http://127.0.0.1:8787';
  const width = Number(args.width || 320);
  const height = Number(args.height || 240);
  const headed = args.headed === '1' || args.headed === 'true';
  if (projectRoot && args.prepareBrowserAssets !== 'false') {
    prepareBrowserAssets(projectRoot);
  }
  const staticServer = await startStaticServer({
    repoRoot,
    engineRoot,
    projectRoot,
    host: args.assetHost || '127.0.0.1',
    port: Number(args.assetPort || 0),
  });
  const assetBase = `http://${staticServer.host}:${staticServer.port}`;
  const query = new URLSearchParams({
    server,
    width: String(width),
    height: String(height),
    engineRoot: `${assetBase}/engine`,
  });
  if (projectRoot) query.set('projectRoot', toStaticUrl(assetBase, repoRoot, projectRoot));
  if (scene) query.set('scene', toStaticUrl(assetBase, repoRoot, scene));
  if (projectRoot) query.set('assetManifest', `${assetBase}/asset-manifest.json`);
  if (args.debugMaterial === '1' || args.debugMaterial === 'true') query.set('debugMaterial', 'true');
  const url = toStaticUrl(assetBase, repoRoot, pagePath) + '?' + query.toString();
  const browser = await chromium.launch({
    headless: !headed,
    args: ['--no-sandbox', '--disable-dev-shm-usage', '--use-angle=default'],
  });
  const page = await browser.newPage({ viewport: { width, height } });
  page.on('console', msg => console.log(`[runtime-renderer:${msg.type()}] ${msg.text()}`));
  page.on('pageerror', err => console.error('[runtime-renderer:pageerror]', err && err.stack || err));
  await page.goto(url, { waitUntil: 'load', timeout: 30000 });
  await page.waitForFunction('window.__MATERIAL_FIT_READY__ === true', { timeout: 30000 });
  const readyPath = args.readyFile ? path.resolve(args.readyFile) : '';
  if (readyPath) {
    const rendererState = await page
      .evaluate(() => window.__MATERIAL_FIT_RENDERER__ || null)
      .catch(() => null);
    fs.mkdirSync(path.dirname(readyPath), { recursive: true });
    fs.writeFileSync(
      readyPath,
      JSON.stringify({ ok: true, url, pid: process.pid, renderer: rendererState }, null, 2),
    );
  }
  const holdMs = Number(args.holdMs || 0);
  if (holdMs > 0) {
    await new Promise(resolve => setTimeout(resolve, holdMs));
    await browser.close();
    await staticServer.close();
    return;
  }
  process.on('SIGTERM', async () => {
    await browser.close().catch(() => {});
    await staticServer.close().catch(() => {});
    process.exit(0);
  });
  await new Promise(() => {});
}

function toStaticUrl(assetBase, repoRoot, inputPath) {
  const relative = path.relative(repoRoot, path.resolve(inputPath)).replace(/\\/g, '/');
  if (relative.startsWith('..')) {
    throw new Error(`path is outside repo root: ${inputPath}`);
  }
  return `${assetBase}/repo/${relative.split('/').map(encodeURIComponent).join('/')}`;
}

function prepareBrowserAssets(projectRoot) {
  const python = process.env.PYTHON || 'python';
  const result = spawnSync(
    python,
    ['-m', 'material_fit.laya_capture.prepare_browser_assets', '--project-root', projectRoot],
    { cwd: path.resolve(__dirname, '..', '..'), encoding: 'utf8' },
  );
  if (result.stdout) process.stdout.write(result.stdout);
  if (result.stderr) process.stderr.write(result.stderr);
  if (result.status !== 0) {
    throw new Error(`browser asset preparation failed with exit code ${result.status}`);
  }
}

async function startStaticServer({ repoRoot, engineRoot, projectRoot, host, port }) {
  const roots = {
    '/repo/': path.resolve(repoRoot),
    '/engine/': path.resolve(engineRoot),
  };
  const manifest = projectRoot ? buildAssetManifest(repoRoot, projectRoot) : { uuidMap: {} };
  const server = http.createServer((req, res) => {
    try {
      const url = new URL(req.url, `http://${host}`);
      if (url.pathname === '/asset-manifest.json') {
        res.writeHead(200, {
          'Content-Type': 'application/json; charset=utf-8',
          'Access-Control-Allow-Origin': '*',
          'Cache-Control': 'no-store',
        });
        res.end(JSON.stringify(manifest));
        return;
      }
      const match = Object.keys(roots).find(prefix => url.pathname === prefix.slice(0, -1) || url.pathname.startsWith(prefix));
      if (!match) {
        res.writeHead(404);
        res.end('not found');
        return;
      }
      const suffix = decodeURIComponent(url.pathname.slice(match.length));
      const root = roots[match];
      const target = path.resolve(root, suffix);
      if (target !== root && !target.startsWith(root + path.sep)) {
        res.writeHead(403);
        res.end('forbidden');
        return;
      }
      if (!fs.existsSync(target) || !fs.statSync(target).isFile()) {
        res.writeHead(404);
        res.end('not found');
        return;
      }
      res.writeHead(200, {
        'Content-Type': mimeType(target),
        'Access-Control-Allow-Origin': '*',
        'Cache-Control': 'no-store',
      });
      fs.createReadStream(target).pipe(res);
    } catch (error) {
      res.writeHead(500);
      res.end(String(error && error.stack || error));
    }
  });
  await new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(port, host, resolve);
  });
  const address = server.address();
  return {
    host,
    port: address.port,
    close: () => new Promise(resolve => server.close(resolve)),
  };
}

function buildAssetManifest(repoRoot, projectRoot) {
  const uuidMap = {};
  const shaderNameMap = {};
  const files = listFiles(projectRoot);
  for (const file of files) {
    if (file.endsWith('.meta')) {
      try {
        const meta = JSON.parse(fs.readFileSync(file, 'utf8'));
        const uuid = meta && meta.uuid;
        const assetPath = file.slice(0, -'.meta'.length);
        if (uuid && fs.existsSync(assetPath)) {
          const browserAsset = browserAssetPath(projectRoot, assetPath);
          uuidMap[uuid] = toStaticUrl('', repoRoot, browserAsset || assetPath).replace(/^\/?/, '/');
        }
      } catch {
        // Ignore non-JSON meta files.
      }
    } else if (file.endsWith('.shader')) {
      const text = fs.readFileSync(file, 'utf8');
      const match = /name\s*:\s*"([^"]+)"/.exec(text);
      if (match) {
        shaderNameMap[match[1]] = toStaticUrl('', repoRoot, file).replace(/^\/?/, '/');
      }
    }
  }
  const libraryRoot = path.join(projectRoot, 'library');
  if (fs.existsSync(libraryRoot)) {
    for (const file of listFiles(libraryRoot)) {
      const base = path.basename(file);
      const match = /^([0-9a-fA-F-]{36})(?:@[^.]+)?\.[^.]+$/.exec(base);
      if (match && !uuidMap[match[1]]) {
        uuidMap[match[1]] = toStaticUrl('', repoRoot, file).replace(/^\/?/, '/');
      }
    }
  }
  return { uuidMap, shaderNameMap };
}

function browserAssetPath(projectRoot, assetPath) {
  const ext = path.extname(assetPath).toLowerCase();
  if (ext !== '.tga') return null;
  const relative = path.relative(projectRoot, assetPath);
  if (relative.startsWith('..')) return null;
  const candidate = path.join(projectRoot, '.material_fit_browser_assets', relative + '.png');
  return fs.existsSync(candidate) ? candidate : null;
}

function listFiles(root) {
  const out = [];
  const stack = [root];
  while (stack.length) {
    const current = stack.pop();
    for (const entry of fs.readdirSync(current, { withFileTypes: true })) {
      const full = path.join(current, entry.name);
      if (entry.isDirectory()) {
        stack.push(full);
      } else if (entry.isFile()) {
        out.push(full);
      }
    }
  }
  return out;
}

function mimeType(filePath) {
  const ext = path.extname(filePath).toLowerCase();
  if (ext === '.html') return 'text/html; charset=utf-8';
  if (ext === '.js') return 'application/javascript; charset=utf-8';
  if (ext === '.json' || ext === '.ls' || ext === '.lh' || ext === '.lmat') return 'application/json; charset=utf-8';
  if (ext === '.png') return 'image/png';
  if (ext === '.jpg' || ext === '.jpeg') return 'image/jpeg';
  if (ext === '.ktx') return 'image/ktx';
  if (ext === '.shader') return 'text/plain; charset=utf-8';
  return 'application/octet-stream';
}

function parseArgs(argv) {
  const out = {};
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (!arg.startsWith('--')) continue;
    const key = arg.slice(2);
    const next = argv[i + 1];
    if (!next || next.startsWith('--')) {
      out[key] = 'true';
    } else {
      out[key] = next;
      i += 1;
    }
  }
  return out;
}

main().catch(error => {
  console.error(error && error.stack || error);
  process.exit(1);
});
