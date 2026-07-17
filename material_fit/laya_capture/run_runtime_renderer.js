let playwright;
try {
  playwright = require('playwright');
} catch (error) {
  playwright = require('playwright-chromium');
}
const { chromium } = playwright;
const path = require('path');
const fs = require('fs');
const http = require('http');
const { spawnSync } = require('child_process');

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const repoRoot = path.resolve(__dirname, '..', '..');
  const vendoredEngineRoot = path.join(repoRoot, 'vendor', 'layaair-3.4.0', 'libs');
  const ideEngineRoot = process.env.LOCALAPPDATA
    ? path.join(process.env.LOCALAPPDATA, 'Programs', 'LayaAirIDE', 'resources', 'engine', 'libs')
    : '';
  const defaultEngineRoot = fs.existsSync(vendoredEngineRoot) ? vendoredEngineRoot : ideEngineRoot;
  const engineRoot = path.resolve(args.engineRoot || process.env.LAYA_ENGINE_LIBS || defaultEngineRoot || 'resources/engine/libs');
  const pagePath = args.page || path.resolve(__dirname, 'runtime_renderer.html');
  const profilePath = args.assetProfile ? path.resolve(args.assetProfile) : '';
  const assetProfile = profilePath ? loadAssetProfile(profilePath) : {};
  const profileDir = profilePath ? path.dirname(profilePath) : repoRoot;
  const defaultProjectRoot = path.resolve(repoRoot, 'examples', 'fish_laya_project');
  const profileProjectRoot = resolveProfilePath(assetProfile.project_root, profileDir);
  const projectRoot = path.resolve(args.projectRoot || profileProjectRoot || (fs.existsSync(defaultProjectRoot) ? defaultProjectRoot : ''));
  const defaultScene = projectRoot ? path.resolve(projectRoot, 'assets', 'resources', 'game.ls') : '';
  const profileScene = resolveProjectAssetPath(assetProfile.scene, projectRoot, profileDir);
  const scene = args.scene || profileScene || (defaultScene && fs.existsSync(defaultScene) ? defaultScene : '');
  const environmentScene = resolveEnvironmentScene({
    requested: args.environmentScene,
    profile: assetProfile,
    profileDir,
    engineRoot,
  });
  const environmentRoot = environmentScene ? path.dirname(environmentScene) : '';
  const server = args.server || 'http://127.0.0.1:8787';
  const width = Number(args.width || assetProfile.width || 320);
  const height = Number(args.height || assetProfile.height || 240);
  const headed = args.headed === '1' || args.headed === 'true';
  if (projectRoot && args.prepareBrowserAssets !== 'false') {
    prepareBrowserAssets(projectRoot);
  }
  const staticServer = await startStaticServer({
    repoRoot,
    engineRoot,
    projectRoot,
    environmentRoot,
    assetProfile,
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
  if (projectRoot) query.set('projectRoot', `${assetBase}/project`);
  if (scene) query.set('scene', toRootUrl(assetBase, '/project/', projectRoot, scene));
  if (environmentScene) query.set('environmentScene', toRootUrl(assetBase, '/environment/', environmentRoot, environmentScene));
  if (projectRoot) query.set('assetManifest', `${assetBase}/asset-manifest.json`);
  if (profilePath) query.set('assetProfile', `${assetBase}/asset-profile.json`);
  if (args.debugMaterial === '1' || args.debugMaterial === 'true') query.set('debugMaterial', 'true');
  const url = toRootUrl(assetBase, '/repo/', repoRoot, pagePath) + '?' + query.toString();
  const launchOptions = {
    headless: !headed,
    args: [
      '--no-sandbox',
      '--disable-dev-shm-usage',
      '--use-angle=default',
      ...splitChromiumArgs(args.chromiumArgs || process.env.MATERIAL_FIT_CHROMIUM_ARGS || ''),
    ],
  };
  const chromiumExecutable = args.chromiumExecutable || process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || '';
  if (chromiumExecutable) {
    launchOptions.executablePath = chromiumExecutable;
  }
  console.log(JSON.stringify({
    chromiumExecutable,
    chromiumArgs: launchOptions.args,
    cudaVisibleDevices: process.env.CUDA_VISIBLE_DEVICES || '',
  }));
  const browser = await chromium.launch(launchOptions);
  const page = await browser.newPage({ viewport: { width, height } });
  let fatalExitStarted = false;
  const exitOnFatalPageError = async (error) => {
    if (fatalExitStarted) return;
    fatalExitStarted = true;
    console.error('[runtime-renderer:fatal]', error && error.stack || error);
    await browser.close().catch(() => {});
    await staticServer.close().catch(() => {});
    process.exit(1);
  };
  page.on('console', msg => console.log(`[runtime-renderer:${msg.type()}] ${msg.text()}`));
  page.on('pageerror', err => {
    console.error('[runtime-renderer:pageerror]', err && err.stack || err);
    void exitOnFatalPageError(err);
  });
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

function toRootUrl(assetBase, prefix, root, inputPath) {
  const relative = path.relative(root, path.resolve(inputPath)).replace(/\\/g, '/');
  if (relative.startsWith('..')) {
    throw new Error(`path is outside served root ${root}: ${inputPath}`);
  }
  const normalizedPrefix = prefix.startsWith('/') ? prefix : `/${prefix}`;
  return `${assetBase}${normalizedPrefix}${relative.split('/').map(encodeURIComponent).join('/')}`;
}

function loadAssetProfile(profilePath) {
  if (!fs.existsSync(profilePath)) throw new Error(`asset profile not found: ${profilePath}`);
  const profile = JSON.parse(fs.readFileSync(profilePath, 'utf8'));
  if (!profile || typeof profile !== 'object' || Array.isArray(profile)) {
    throw new Error(`asset profile must be a JSON object: ${profilePath}`);
  }
  if (Number(profile.schema_version || 1) !== 1) {
    throw new Error(`unsupported asset profile schema_version: ${profile.schema_version}`);
  }
  profile.capture_defaults = Object.assign({
    animation_mode: 'disabled',
    freeze_animators: true,
    settle_frames: 0,
    animation_freeze_settle_frames: 0,
  }, profile.capture_defaults || {});
  return profile;
}

function resolveProfilePath(value, profileDir) {
  if (!value) return '';
  return path.resolve(profileDir, String(value));
}

function resolveProjectAssetPath(value, projectRoot, profileDir) {
  if (!value) return '';
  const text = String(value);
  if (path.isAbsolute(text)) return path.resolve(text);
  const projectCandidate = projectRoot ? path.resolve(projectRoot, text) : '';
  if (projectCandidate && fs.existsSync(projectCandidate)) return projectCandidate;
  return path.resolve(profileDir, text);
}

function resolveEnvironmentScene({ requested, profile, profileDir, engineRoot }) {
  if (requested) return path.resolve(requested);
  const runtime = profile && profile.runtime && typeof profile.runtime === 'object' ? profile.runtime : {};
  const environment = runtime.environment && typeof runtime.environment === 'object' ? runtime.environment : {};
  if (environment.scene) return resolveProfilePath(environment.scene, profileDir);
  if (environment.preset === 'laya_prefab_editor') {
    const candidate = path.resolve(engineRoot, '..', '..', 'internal', 'DefaultPrefabEditEnv.ls');
    if (!fs.existsSync(candidate)) {
      throw new Error(`Laya prefab editor environment is unavailable: ${candidate}`);
    }
    return candidate;
  }
  return '';
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

async function startStaticServer({ repoRoot, engineRoot, projectRoot, environmentRoot, assetProfile, host, port }) {
  const roots = {
    '/repo/': path.resolve(repoRoot),
    '/engine/': path.resolve(engineRoot),
  };
  if (projectRoot) roots['/project/'] = path.resolve(projectRoot);
  if (environmentRoot) roots['/environment/'] = path.resolve(environmentRoot);
  const assetRoots = [];
  if (projectRoot) assetRoots.push({ root: path.resolve(projectRoot), prefix: '/project/' });
  if (environmentRoot) assetRoots.push({ root: path.resolve(environmentRoot), prefix: '/environment/' });
  const runtimeProfile = assetProfile && assetProfile.runtime && typeof assetProfile.runtime === 'object'
    ? assetProfile.runtime
    : {};
  const manifest = buildAssetManifest(assetRoots, {
    preferImportedLibraryAssets: runtimeProfile.prefer_imported_library_assets === true,
  });
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
      if (url.pathname === '/asset-profile.json') {
        res.writeHead(200, {
          'Content-Type': 'application/json; charset=utf-8',
          'Access-Control-Allow-Origin': '*',
          'Cache-Control': 'no-store',
        });
        res.end(JSON.stringify(assetProfile || {}));
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
  await listenOnSafePort(server, host, port);
  const address = server.address();
  return {
    host,
    port: address.port,
    close: () => new Promise(resolve => server.close(resolve)),
  };
}

async function listenOnSafePort(server, host, port) {
  const requested = Number(port || 0);
  const candidates = requested > 0
    ? [requested]
    : Array.from({ length: 64 }, (_, i) => 18080 + i);
  let lastError = null;
  for (const candidate of candidates) {
    if (isChromiumUnsafePort(candidate)) continue;
    try {
      await new Promise((resolve, reject) => {
        const onError = error => {
          server.off('listening', onListening);
          reject(error);
        };
        const onListening = () => {
          server.off('error', onError);
          resolve();
        };
        server.once('error', onError);
        server.once('listening', onListening);
        server.listen(candidate, host);
      });
      return;
    } catch (error) {
      lastError = error;
      if (error && error.code !== 'EADDRINUSE') throw error;
    }
  }
  throw lastError || new Error('could not bind a safe static asset port');
}

function isChromiumUnsafePort(port) {
  const unsafe = new Set([
    1, 7, 9, 11, 13, 15, 17, 19, 20, 21, 22, 23, 25, 37, 42, 43, 53, 69,
    77, 79, 87, 95, 101, 102, 103, 104, 109, 110, 111, 113, 115, 117, 119,
    123, 135, 137, 139, 143, 161, 179, 389, 427, 465, 512, 513, 514, 515,
    526, 530, 531, 532, 540, 548, 554, 556, 563, 587, 601, 636, 989, 990,
    993, 995, 1719, 1720, 1723, 2049, 3659, 4045, 5060, 5061, 6000, 6566,
    6665, 6666, 6667, 6668, 6669, 6697, 10080,
  ]);
  return unsafe.has(Number(port));
}

function buildAssetManifest(assetRoots, options = {}) {
  const uuidMap = {};
  const shaderNameMap = {};
  const sourceExtensionByUuid = {};
  for (const assetRoot of assetRoots || []) {
    const files = listFiles(assetRoot.root);
    for (const file of files) {
      if (file.endsWith('.meta')) {
        try {
          const meta = JSON.parse(fs.readFileSync(file, 'utf8'));
          const uuid = meta && meta.uuid;
          const assetPath = file.slice(0, -'.meta'.length);
          if (uuid && fs.existsSync(assetPath)) {
            const browserAsset = browserAssetPath(assetRoot.root, assetPath);
            uuidMap[uuid] = toRootUrl('', assetRoot.prefix, assetRoot.root, browserAsset || assetPath);
            sourceExtensionByUuid[uuid] = path.extname(assetPath).toLowerCase();
          }
        } catch {
          // Ignore non-JSON meta files.
        }
      } else if (file.endsWith('.shader')) {
        const text = fs.readFileSync(file, 'utf8');
        const match = /name\s*:\s*"([^"]+)"/.exec(text);
        if (match) {
          shaderNameMap[match[1]] = toRootUrl('', assetRoot.prefix, assetRoot.root, file);
        }
      }
    }
    const libraryRoot = path.join(assetRoot.root, 'library');
    if (fs.existsSync(libraryRoot)) {
      for (const metadataPath of listFiles(libraryRoot).filter(file => file.endsWith('.json'))) {
        const uuid = path.basename(metadataPath, '.json');
        if (!/^[0-9a-fA-F-]{36}$/.test(uuid)) continue;
        try {
          const metadata = JSON.parse(fs.readFileSync(metadataPath, 'utf8'));
          const importedTexture = preferredImportedTexture(metadataPath, uuid, metadata);
          const mustUseImported = options.preferImportedLibraryAssets === true
            || Number(metadata && metadata.shape) === 1
            || sourceExtensionByUuid[uuid] === '.exr';
          if (mustUseImported && importedTexture) {
            uuidMap[uuid] = toRootUrl('', assetRoot.prefix, assetRoot.root, importedTexture);
          }
        } catch {
          // Ignore stale or non-texture library metadata.
        }
      }
      for (const file of listFiles(libraryRoot)) {
        const base = path.basename(file);
        const match = /^([0-9a-fA-F-]{36})(?:@[^.]+)?\.[^.]+$/.exec(base);
        if (match && !uuidMap[match[1]]) {
          uuidMap[match[1]] = toRootUrl('', assetRoot.prefix, assetRoot.root, file);
        }
      }
    }
  }
  return { uuidMap, shaderNameMap };
}

function preferredImportedTexture(metadataPath, uuid, metadata) {
  const directory = path.dirname(metadataPath);
  const files = Array.isArray(metadata && metadata.files) ? metadata.files : [];
  const platformIndex = Number(metadata && metadata.platforms && metadata.platforms['0']);
  const preferred = Number.isInteger(platformIndex) && files[platformIndex] ? files[platformIndex] : files[0];
  const candidates = [];
  if (preferred && preferred.ext) {
    const suffix = preferred.file === '' ? '' : `@${preferred.file}`;
    candidates.push(path.join(directory, `${uuid}${suffix}.${preferred.ext}`));
  }
  candidates.push(...fs.readdirSync(directory)
    .filter(name => name.startsWith(`${uuid}@`) && /\.(ktx|ltcb)$/i.test(name))
    .map(name => path.join(directory, name)));
  return candidates.find(candidate => fs.existsSync(candidate) && fs.statSync(candidate).isFile()) || '';
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

function splitChromiumArgs(value) {
  if (!value) return [];
  const text = String(value).trim();
  if (!text) return [];
  if (text.startsWith('[')) {
    try {
      const parsed = JSON.parse(text);
      if (Array.isArray(parsed)) return parsed.map(item => String(item)).filter(Boolean);
    } catch (_) {
      return [];
    }
  }
  return text.split(/[,\s]+/).map(item => item.trim()).filter(Boolean);
}

main().catch(error => {
  console.error(error && error.stack || error);
  process.exit(1);
});
