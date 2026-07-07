"use strict";
(() => {
  var __defProp = Object.defineProperty;
  var __defProps = Object.defineProperties;
  var __getOwnPropDesc = Object.getOwnPropertyDescriptor;
  var __getOwnPropDescs = Object.getOwnPropertyDescriptors;
  var __getOwnPropSymbols = Object.getOwnPropertySymbols;
  var __hasOwnProp = Object.prototype.hasOwnProperty;
  var __propIsEnum = Object.prototype.propertyIsEnumerable;
  var __defNormalProp = (obj, key, value) => key in obj ? __defProp(obj, key, { enumerable: true, configurable: true, writable: true, value }) : obj[key] = value;
  var __spreadValues = (a, b) => {
    for (var prop in b || (b = {}))
      if (__hasOwnProp.call(b, prop))
        __defNormalProp(a, prop, b[prop]);
    if (__getOwnPropSymbols)
      for (var prop of __getOwnPropSymbols(b)) {
        if (__propIsEnum.call(b, prop))
          __defNormalProp(a, prop, b[prop]);
      }
    return a;
  };
  var __spreadProps = (a, b) => __defProps(a, __getOwnPropDescs(b));
  var __name = (target, value) => __defProp(target, "name", { value, configurable: true });
  var __decorateClass = (decorators, target, key, kind) => {
    var result = kind > 1 ? void 0 : kind ? __getOwnPropDesc(target, key) : target;
    for (var i = decorators.length - 1, decorator; i >= 0; i--)
      if (decorator = decorators[i])
        result = (kind ? decorator(target, key, result) : decorator(result)) || result;
    if (kind && result) __defProp(target, key, result);
    return result;
  };
  var __async = (__this, __arguments, generator) => {
    return new Promise((resolve, reject) => {
      var fulfilled = (value) => {
        try {
          step(generator.next(value));
        } catch (e) {
          reject(e);
        }
      };
      var rejected = (value) => {
        try {
          step(generator.throw(value));
        } catch (e) {
          reject(e);
        }
      };
      var step = (x) => x.done ? resolve(x.value) : Promise.resolve(x.value).then(fulfilled, rejected);
      step((generator = generator.apply(__this, __arguments)).next());
    });
  };

  // assets/Editor/CameraCapture.ts
  console.log("[CameraCapture] CameraCapture.ts loaded");
  var CameraCapture = class {
    static onLoad() {
      console.log("[CameraCapture] onLoad start");
      try {
        Editor.extensionManager.addMenuItem(
          "App/tools/screenshotViewport",
          () => {
            console.log("[CameraCapture] >>> VIEWPORT menu clicked");
            CameraCapture.runViewport();
          },
          { label: "截图当前场景视口" }
        );
        console.log("[CameraCapture] addMenuItem ok: screenshotViewport");
      } catch (e) {
        console.error("[CameraCapture] addMenuItem screenshotViewport failed:", e);
      }
      try {
        Editor.extensionManager.addMenuItem(
          "App/tools/screenshotSelectedCamera",
          () => {
            console.log("[CameraCapture] >>> SELECTED CAMERA menu clicked");
            CameraCapture.runSelectedCamera();
          },
          { label: "按选中相机截图" }
        );
        console.log("[CameraCapture] addMenuItem ok: screenshotSelectedCamera");
      } catch (e) {
        console.error("[CameraCapture] addMenuItem screenshotSelectedCamera failed:", e);
      }
      try {
        Editor.extensionManager.addMenuItem(
          "App/tools/screenshotMaterialFitMultiview",
          () => {
            console.log("[CameraCapture] >>> MATERIAL FIT MULTIVIEW menu clicked");
            CameraCapture.runMaterialFitMultiview();
          },
          { label: "按命令多视角截图" }
        );
        console.log("[CameraCapture] addMenuItem ok: screenshotMaterialFitMultiview");
      } catch (e) {
        console.error("[CameraCapture] addMenuItem screenshotMaterialFitMultiview failed:", e);
      }
      CameraCapture._startAutoCapturePolling();
    }
    static runViewport() {
      return __async(this, null, function* () {
        yield CameraCapture._invoke("CameraCaptureEnv.captureToFile", "视口截图");
      });
    }
    static runSelectedCamera() {
      return __async(this, null, function* () {
        yield CameraCapture._invoke("CameraCaptureEnv.captureFromSelectedCamera", "选中相机截图");
      });
    }
    static runMaterialFitMultiview() {
      return __async(this, null, function* () {
        yield CameraCapture._invoke("CameraCaptureEnv.captureMultiviewFromCommand", "多视角截图");
      });
    }
    static _startAutoCapturePolling() {
      if (CameraCapture._autoTimer) {
        return;
      }
      CameraCapture._autoTimer = setInterval(() => {
        CameraCapture._pollAutoCapture();
      }, 1e3);
      console.log("[CameraCapture] auto capture polling started");
    }
    static _pollAutoCapture() {
      return __async(this, null, function* () {
        if (CameraCapture._autoBusy) {
          return;
        }
        try {
          const fs = IEditor.require("fs");
          const commandPath = CameraCapture._resolveCommandPath();
          if (!commandPath || !fs.existsSync(commandPath)) {
            return;
          }
          const command = JSON.parse(fs.readFileSync(commandPath, "utf8"));
          if (!command.auto_capture || !command.nonce || command.nonce === CameraCapture._lastAutoNonce) {
            return;
          }
          CameraCapture._autoBusy = true;
          CameraCapture._lastAutoNonce = command.nonce;
          console.log(`[CameraCapture] auto capture triggered: ${command.nonce}`);
          yield CameraCapture._runMaterialFitCommand(command);
        } catch (e) {
          console.error("[CameraCapture] auto capture error:", e);
        } finally {
          CameraCapture._autoBusy = false;
        }
      });
    }
    static _runMaterialFitCommand(command) {
      return __async(this, null, function* () {
        yield CameraCapture._reimportAssets(command.refresh_assets || []);
        if (command.reload_scene_after_reimport) {
          yield CameraCapture._reloadActiveScene();
        }
        const delayMs = Math.max(0, command.refresh_after_reimport_delay_ms || 500);
        if (delayMs > 0) {
          yield new Promise((resolve) => setTimeout(resolve, delayMs));
        }
        const script = command.capture_kind === "selected_camera" ? "CameraCaptureEnv.captureSelectedCameraFromCommand" : "CameraCaptureEnv.captureMultiviewFromCommand";
        const label = command.capture_kind === "selected_camera" ? "自动相机截图" : "自动多视角截图";
        yield CameraCapture._invoke(script, label);
      });
    }
    static _reimportAssets(assetPaths) {
      return __async(this, null, function* () {
        if (!assetPaths.length) {
          return;
        }
        const assets = [];
        for (const assetPath of assetPaths) {
          const asset = yield Editor.assetDb.getAsset(assetPath, true);
          if (!asset) {
            throw new Error(`刷新资源失败，未找到资源: ${assetPath}`);
          }
          assets.push(asset);
        }
        console.log(`[CameraCapture] reimport assets: ${assetPaths.join(", ")}`);
        Editor.assetDb.reimport(assets);
        yield Editor.assetDb.flushChanges();
      });
    }
    static _reloadActiveScene() {
      return __async(this, null, function* () {
        const scene = Editor.sceneManager.activeScene;
        if (!scene) {
          return;
        }
        console.log(`[CameraCapture] reload active scene: ${scene.sceneId}`);
        yield Editor.sceneManager.reloadScene(scene.sceneId);
      });
    }
    static _resolveCommandPath() {
      const fs = IEditor.require("fs");
      for (const candidate of CameraCapture._commandPathCandidates()) {
        if (fs.existsSync(candidate)) {
          return candidate;
        }
      }
      return null;
    }
    static _commandPathCandidates() {
      const pathMod = IEditor.require("path");
      const projectPath = Editor.projectPath;
      return [
        pathMod.join(projectPath, CameraCapture.COMMAND_FILE),
        pathMod.join(projectPath, "assets", CameraCapture.COMMAND_FILE),
        pathMod.join(pathMod.dirname(projectPath), CameraCapture.COMMAND_FILE),
        pathMod.join(pathMod.dirname(projectPath), "assets", CameraCapture.COMMAND_FILE)
      ];
    }
    static _invoke(script, label) {
      return __async(this, null, function* () {
        console.log(`[CameraCapture] invoke ${script}`);
        Editor.showToast(`${label}开始...`, "info", void 0, 1500);
        let result;
        try {
          result = yield Editor.scene.runScript(script);
          console.log(`[CameraCapture] ${script} result:`, result);
        } catch (e) {
          console.error(`[CameraCapture] ${script} threw:`, e);
          Editor.showToast(`${label}失败: ${e.message}`, "error", void 0, 5e3);
          return;
        }
        if (result && result.ok) {
          Editor.showToast(`${label}已保存: ${result.path}`, "info", void 0, 5e3);
        } else {
          Editor.showToast(`${label}失败: ${result && result.error || "未知错误"}`, "error", void 0, 5e3);
        }
      });
    }
  };
  __name(CameraCapture, "CameraCapture");
  CameraCapture.COMMAND_FILE = "material_fit_capture_command.json";
  CameraCapture._autoTimer = null;
  CameraCapture._autoBusy = false;
  CameraCapture._lastAutoNonce = "";
  __decorateClass([
    IEditor.onLoad
  ], CameraCapture, "onLoad", 1);
  CameraCapture = __decorateClass([
    IEditor.regClass("2ae63619-4925-4dde-a329-058511a6331f", "Editor/CameraCapture.ts")
  ], CameraCapture);

  // src/Base/Utils/AssetDependencyIndex.ts
  var _AssetDependencyIndex = class _AssetDependencyIndex {
    static onLoad() {
      _AssetDependencyIndex.ensureListeners();
    }
    static ensureReady(options) {
      return __async(this, null, function* () {
        _AssetDependencyIndex.ensureListeners();
        if (!(options == null ? void 0 : options.forceRebuild) && _AssetDependencyIndex._indexData && !_AssetDependencyIndex._isDirty) {
          return _AssetDependencyIndex._indexData;
        }
        if (_AssetDependencyIndex._buildPromise) {
          return _AssetDependencyIndex._buildPromise;
        }
        if (!(options == null ? void 0 : options.forceRebuild) && _AssetDependencyIndex._indexData) {
          _AssetDependencyIndex.triggerBackgroundRebuild();
          return _AssetDependencyIndex._indexData;
        }
        _AssetDependencyIndex._buildPromise = _AssetDependencyIndex.loadOrBuildIndex(options);
        try {
          const indexData = yield _AssetDependencyIndex._buildPromise;
          _AssetDependencyIndex._indexData = indexData;
          _AssetDependencyIndex._isDirty = false;
          return indexData;
        } finally {
          _AssetDependencyIndex._buildPromise = null;
        }
      });
    }
    static markDirty() {
      _AssetDependencyIndex._isDirty = true;
    }
    static rebuild(options) {
      return __async(this, null, function* () {
        return _AssetDependencyIndex.ensureReady(__spreadProps(__spreadValues({}, options), {
          forceRebuild: true
        }));
      });
    }
    static getDependencyRecords(assetIds) {
      const indexData = _AssetDependencyIndex.requireIndex();
      const result = /* @__PURE__ */ new Map();
      const excludedIds = new Set(assetIds);
      for (const assetId of assetIds) {
        const record = indexData.recordsById.get(assetId);
        if (!record) {
          continue;
        }
        for (const dependencyId of record.dependencies) {
          if (excludedIds.has(dependencyId) || result.has(dependencyId)) {
            continue;
          }
          const dependencyRecord = indexData.recordsById.get(dependencyId);
          if (dependencyRecord) {
            result.set(dependencyId, dependencyRecord);
          }
        }
      }
      return _AssetDependencyIndex.sortRecords([...result.values()]);
    }
    static getDependencyRecordsByLevel(assetIds, maxDepth = 20) {
      const indexData = _AssetDependencyIndex.requireIndex();
      const result = [];
      const visitedIds = new Set(assetIds);
      let currentLevelIds = [...assetIds];
      for (let depth = 0; depth < maxDepth && currentLevelIds.length > 0; depth++) {
        const levelMap = /* @__PURE__ */ new Map();
        for (const assetId of currentLevelIds) {
          const record = indexData.recordsById.get(assetId);
          if (!record) {
            continue;
          }
          for (const depId of record.dependencies) {
            if (visitedIds.has(depId) || levelMap.has(depId)) {
              continue;
            }
            const depRecord = indexData.recordsById.get(depId);
            if (depRecord) {
              levelMap.set(depId, depRecord);
            }
          }
        }
        if (levelMap.size === 0) {
          break;
        }
        const levelRecords = _AssetDependencyIndex.sortRecords([...levelMap.values()]);
        result.push(levelRecords);
        currentLevelIds = [];
        for (const id of levelMap.keys()) {
          visitedIds.add(id);
          currentLevelIds.push(id);
        }
      }
      return result;
    }
    static getReferenceRecordsByLevel(assetIds, maxDepth = 20) {
      const indexData = _AssetDependencyIndex.requireIndex();
      const result = [];
      const visitedIds = new Set(assetIds);
      let currentLevelIds = [...assetIds];
      for (let depth = 0; depth < maxDepth && currentLevelIds.length > 0; depth++) {
        const levelMap = /* @__PURE__ */ new Map();
        for (const assetId of currentLevelIds) {
          const refs = indexData.reverseReferencesById.get(assetId);
          if (!refs) {
            continue;
          }
          for (const refId of refs) {
            if (visitedIds.has(refId) || levelMap.has(refId)) {
              continue;
            }
            const refRecord = indexData.recordsById.get(refId);
            if (refRecord) {
              levelMap.set(refId, refRecord);
            }
          }
        }
        if (levelMap.size === 0) {
          break;
        }
        const levelRecords = _AssetDependencyIndex.sortRecords([...levelMap.values()]);
        result.push(levelRecords);
        currentLevelIds = [];
        for (const id of levelMap.keys()) {
          visitedIds.add(id);
          currentLevelIds.push(id);
        }
      }
      return result;
    }
    static getMissingReferences(assetId) {
      const indexData = _AssetDependencyIndex.requireIndex();
      return indexData.missingRefsByAssetId.get(assetId) || [];
    }
    static getFolderRecords(folderFile) {
      const indexData = _AssetDependencyIndex.requireIndex();
      let prefix = folderFile.length > 0 ? `${folderFile}/` : "";
      if (prefix.length > 0) {
        const hasKnownRoot = _AssetDependencyIndex.SCAN_DIRS.some(
          (dir) => prefix.startsWith(`${dir}/`)
        );
        if (!hasKnownRoot) {
          prefix = `assets/${prefix}`;
        }
      }
      const result = [];
      for (const record of indexData.recordsByPrefix) {
        if (prefix.length === 0 || record.file.startsWith(prefix)) {
          result.push(record);
        }
      }
      return result;
    }
    static hasReferences(assetId) {
      const indexData = _AssetDependencyIndex.requireIndex();
      return (indexData.reverseReferenceCountById.get(assetId) || 0) > 0;
    }
    static createAssetInfo(record) {
      const path = IEditor.require("path");
      const fileName = path.basename(record.file);
      const ext = record.ext || "";
      const name = ext.length > 0 && fileName.endsWith(`.${ext}`) ? fileName.substring(0, fileName.length - ext.length - 1) : fileName;
      return {
        id: record.id,
        name,
        fileName,
        file: record.file,
        ext,
        type: 0,
        subType: "",
        ver: 0,
        parentId: "",
        hasChild: false,
        flags: 0,
        scriptType: 0,
        children: []
      };
    }
    static triggerBackgroundRebuild() {
      if (_AssetDependencyIndex._buildPromise || _AssetDependencyIndex._backgroundBuildPromise) {
        return;
      }
      _AssetDependencyIndex._backgroundBuildPromise = _AssetDependencyIndex.loadOrBuildIndex().then((indexData) => {
        _AssetDependencyIndex._indexData = indexData;
        _AssetDependencyIndex._isDirty = false;
        _AssetDependencyIndex._backgroundBuildPromise = null;
      }).catch((error) => {
        console.warn("[AssetDependencyIndex] 后台重建索引失败:", error);
        _AssetDependencyIndex._backgroundBuildPromise = null;
      });
    }
    static ensureListeners() {
      if (_AssetDependencyIndex._isListening) {
        return;
      }
      Editor.assetDb.onAssetChanged.add(_AssetDependencyIndex.onAssetChanged, _AssetDependencyIndex);
      Editor.assetDb.onPackagesChanged.add(_AssetDependencyIndex.onPackagesChanged, _AssetDependencyIndex);
      _AssetDependencyIndex._isListening = true;
    }
    static onAssetChanged() {
      _AssetDependencyIndex.markDirty();
    }
    static onPackagesChanged() {
      _AssetDependencyIndex.markDirty();
    }
    static requireIndex() {
      if (!_AssetDependencyIndex._indexData) {
        throw new Error("依赖索引尚未准备完成");
      }
      return _AssetDependencyIndex._indexData;
    }
    static loadOrBuildIndex(options) {
      return __async(this, null, function* () {
        var _a;
        const snapshot = _AssetDependencyIndex.scanProjectSnapshot();
        if (!(options == null ? void 0 : options.forceRebuild) && !_AssetDependencyIndex._isDirty) {
          const cachedData = _AssetDependencyIndex.tryLoadCache(snapshot);
          if (cachedData) {
            (_a = options == null ? void 0 : options.onProgress) == null ? void 0 : _a.call(options, snapshot.assetCount, snapshot.assetCount);
            return cachedData;
          }
        }
        const scanResult = _AssetDependencyIndex.scanProjectAssets();
        return _AssetDependencyIndex.buildIndex(scanResult, options == null ? void 0 : options.onProgress);
      });
    }
    static tryLoadCache(snapshot) {
      const fs = IEditor.require("fs");
      const cachePath = _AssetDependencyIndex.getCacheFilePath();
      if (!fs.existsSync(cachePath)) {
        return null;
      }
      try {
        const content = fs.readFileSync(cachePath, "utf-8");
        const cache = JSON.parse(content);
        if (!_AssetDependencyIndex.isCacheValid(cache, snapshot)) {
          return null;
        }
        return _AssetDependencyIndex.createIndexData(cache.records, cache.builtAt, cache.latestModifiedMs);
      } catch (error) {
        console.warn("[AssetDependencyIndex] 读取缓存失败，将重建索引:", error);
        return null;
      }
    }
    static isCacheValid(cache, snapshot) {
      if (!cache || cache.version !== _AssetDependencyIndex.CACHE_VERSION) {
        return false;
      }
      return cache.assetCount === snapshot.assetCount && cache.latestModifiedMs === snapshot.latestModifiedMs;
    }
    static buildIndex(scanResult, onProgress) {
      return __async(this, null, function* () {
        const records = scanResult.records.map((record) => {
          return {
            id: record.id,
            file: record.file,
            ext: record.ext,
            dependencies: [],
            missingRefs: []
          };
        });
        const totalCount = records.length;
        let processedCount = 0;
        const shaderNameMap = _AssetDependencyIndex.buildShaderNameMap(records);
        onProgress == null ? void 0 : onProgress(0, totalCount);
        yield _AssetDependencyIndex.runWithConcurrency(records, _AssetDependencyIndex.QUERY_CONCURRENCY, (record) => __async(null, null, function* () {
          const [dependencies, notFound] = yield IEditor.AssetDependencyTool.queryDependency([record.id], false, true);
          record.dependencies = _AssetDependencyIndex.extractDependencyIds(record.id, dependencies);
          record.missingRefs = _AssetDependencyIndex.normalizeMissingReferences(notFound);
          if (record.ext === "lmat") {
            const shaderId = _AssetDependencyIndex.extractMaterialShaderDepId(record, shaderNameMap);
            if (shaderId && record.dependencies.indexOf(shaderId) === -1) {
              record.dependencies.push(shaderId);
              record.dependencies.sort((a, b) => a.localeCompare(b));
            }
          }
          processedCount++;
          onProgress == null ? void 0 : onProgress(processedCount, totalCount);
        }));
        const builtAt = Date.now();
        _AssetDependencyIndex.writeCache({
          version: _AssetDependencyIndex.CACHE_VERSION,
          builtAt,
          assetCount: totalCount,
          latestModifiedMs: scanResult.latestModifiedMs,
          records
        });
        return _AssetDependencyIndex.createIndexData(records, builtAt, scanResult.latestModifiedMs);
      });
    }
    static buildShaderNameMap(records) {
      const map = /* @__PURE__ */ new Map();
      for (const record of records) {
        if (record.ext !== "shader") {
          continue;
        }
        const shaderName = _AssetDependencyIndex.extractShaderName(record);
        if (shaderName) {
          map.set(shaderName, record.id);
        }
      }
      return map;
    }
    static extractShaderName(record) {
      const fs = IEditor.require("fs");
      const path = IEditor.require("path");
      const filePath = path.join(_AssetDependencyIndex.getProjectRootPath(), record.file);
      try {
        const content = fs.readFileSync(filePath, "utf-8");
        const match = content.match(/\bname\s*:\s*"([^"]+)"/);
        return match ? match[1] : null;
      } catch (e) {
        return null;
      }
    }
    static extractMaterialShaderDepId(record, shaderNameMap) {
      var _a;
      const fs = IEditor.require("fs");
      const path = IEditor.require("path");
      const filePath = path.join(_AssetDependencyIndex.getProjectRootPath(), record.file);
      try {
        const content = fs.readFileSync(filePath, "utf-8");
        const json = JSON.parse(content);
        const shaderName = (_a = json == null ? void 0 : json.props) == null ? void 0 : _a.type;
        if (!shaderName) {
          return null;
        }
        return shaderNameMap.get(shaderName) || null;
      } catch (e) {
        return null;
      }
    }
    static createIndexData(records, builtAt, latestModifiedMs) {
      const recordsById = /* @__PURE__ */ new Map();
      const missingRefsByAssetId = /* @__PURE__ */ new Map();
      const reverseReferenceCountById = /* @__PURE__ */ new Map();
      const reverseReferencesById = /* @__PURE__ */ new Map();
      const sortedRecords = _AssetDependencyIndex.sortRecords([...records]);
      for (const record of sortedRecords) {
        recordsById.set(record.id, record);
        if (record.missingRefs.length > 0) {
          missingRefsByAssetId.set(record.id, record.missingRefs);
        }
        for (const dependencyId of record.dependencies) {
          reverseReferenceCountById.set(
            dependencyId,
            (reverseReferenceCountById.get(dependencyId) || 0) + 1
          );
          let refs = reverseReferencesById.get(dependencyId);
          if (!refs) {
            refs = [];
            reverseReferencesById.set(dependencyId, refs);
          }
          refs.push(record.id);
        }
      }
      return {
        assetCount: sortedRecords.length,
        builtAt,
        latestModifiedMs,
        missingRefsByAssetId,
        recordsById,
        recordsByPrefix: sortedRecords,
        reverseReferenceCountById,
        reverseReferencesById
      };
    }
    static extractDependencyIds(sourceAssetId, dependencies) {
      const result = [];
      const visitedIds = /* @__PURE__ */ new Set();
      for (const dependency of dependencies) {
        if (!(dependency == null ? void 0 : dependency.id) || dependency.id === sourceAssetId || visitedIds.has(dependency.id)) {
          continue;
        }
        visitedIds.add(dependency.id);
        result.push(dependency.id);
      }
      result.sort((left, right) => left.localeCompare(right));
      return result;
    }
    static normalizeMissingReferences(missingRefs) {
      const normalizedRefs = [...new Set(
        missingRefs.map((missingRef) => missingRef.trim()).filter((missingRef) => missingRef.length > 0)
      )];
      normalizedRefs.sort((left, right) => left.localeCompare(right));
      return normalizedRefs;
    }
    static writeCache(cache) {
      const fs = IEditor.require("fs");
      const path = IEditor.require("path");
      const cachePath = _AssetDependencyIndex.getCacheFilePath();
      fs.mkdirSync(path.dirname(cachePath), { recursive: true });
      fs.writeFileSync(cachePath, JSON.stringify(cache), "utf-8");
    }
    static getCacheFilePath() {
      const path = IEditor.require("path");
      return path.join(Editor.projectPath, _AssetDependencyIndex.CACHE_RELATIVE_PATH);
    }
    static scanProjectAssets() {
      const path = IEditor.require("path");
      const projectRoot = _AssetDependencyIndex.getProjectRootPath();
      const records = [];
      let latestModifiedMs = 0;
      for (const dir of _AssetDependencyIndex.SCAN_DIRS) {
        _AssetDependencyIndex.scanDirectory(path.join(projectRoot, dir), records, (mtimeMs) => {
          if (mtimeMs > latestModifiedMs) {
            latestModifiedMs = mtimeMs;
          }
        });
      }
      records.sort((left, right) => left.file.localeCompare(right.file));
      return {
        assetCount: records.length,
        latestModifiedMs,
        records
      };
    }
    static scanProjectSnapshot() {
      const path = IEditor.require("path");
      const fs = IEditor.require("fs");
      const projectRoot = _AssetDependencyIndex.getProjectRootPath();
      let assetCount = 0;
      let latestModifiedMs = 0;
      for (const dir of _AssetDependencyIndex.SCAN_DIRS) {
        const dirPath = path.join(projectRoot, dir);
        if (!fs.existsSync(dirPath)) {
          continue;
        }
        _AssetDependencyIndex.scanDirectoryFast(dirPath, (mtimeMs) => {
          if (mtimeMs > latestModifiedMs) {
            latestModifiedMs = mtimeMs;
          }
        }, () => {
          assetCount++;
        });
      }
      return {
        assetCount,
        latestModifiedMs
      };
    }
    static scanDirectory(dirPath, out, onModified) {
      const fs = IEditor.require("fs");
      const path = IEditor.require("path");
      let entries = [];
      try {
        entries = fs.readdirSync(dirPath, { withFileTypes: true });
      } catch (e) {
        return;
      }
      for (const entry of entries) {
        const fullPath = path.join(dirPath, entry.name);
        if (entry.isDirectory()) {
          try {
            const stat = fs.statSync(fullPath);
            onModified(stat.mtimeMs);
          } catch (e) {
          }
          _AssetDependencyIndex.scanDirectory(fullPath, out, onModified);
          continue;
        }
        if (!entry.isFile() || entry.name.endsWith(_AssetDependencyIndex.META_EXT)) {
          continue;
        }
        const relativeFile = _AssetDependencyIndex.toAssetRelativePath(fullPath);
        const metaPath = `${fullPath}${_AssetDependencyIndex.META_EXT}`;
        if (!relativeFile || !fs.existsSync(metaPath)) {
          continue;
        }
        try {
          const fileStat = fs.statSync(fullPath);
          const metaStat = fs.statSync(metaPath);
          onModified(fileStat.mtimeMs);
          onModified(metaStat.mtimeMs);
        } catch (e) {
        }
        const meta = _AssetDependencyIndex.readJsonFile(metaPath);
        if (!(meta == null ? void 0 : meta.uuid)) {
          continue;
        }
        out.push({
          id: meta.uuid,
          file: relativeFile,
          ext: path.extname(relativeFile).replace(/^\./, "")
        });
      }
    }
    static scanDirectoryFast(dirPath, onModified, onAsset) {
      const fs = IEditor.require("fs");
      const path = IEditor.require("path");
      let entries = [];
      try {
        entries = fs.readdirSync(dirPath, { withFileTypes: true });
      } catch (e) {
        return;
      }
      for (const entry of entries) {
        const fullPath = path.join(dirPath, entry.name);
        if (entry.isDirectory()) {
          try {
            const stat = fs.statSync(fullPath);
            onModified(stat.mtimeMs);
          } catch (e) {
          }
          _AssetDependencyIndex.scanDirectoryFast(fullPath, onModified, onAsset);
          continue;
        }
        if (!entry.isFile() || entry.name.endsWith(_AssetDependencyIndex.META_EXT)) {
          continue;
        }
        const metaPath = `${fullPath}${_AssetDependencyIndex.META_EXT}`;
        if (!fs.existsSync(metaPath)) {
          continue;
        }
        try {
          const fileStat = fs.statSync(fullPath);
          const metaStat = fs.statSync(metaPath);
          onModified(fileStat.mtimeMs);
          onModified(metaStat.mtimeMs);
        } catch (e) {
        }
        onAsset();
      }
    }
    static toAssetRelativePath(fullPath) {
      const path = IEditor.require("path");
      const projectRoot = _AssetDependencyIndex.getProjectRootPath();
      const relativePath = path.relative(projectRoot, fullPath);
      if (!relativePath || relativePath.startsWith("..")) {
        return "";
      }
      return relativePath.split(path.sep).join("/");
    }
    static getProjectRootPath() {
      return Editor.projectPath;
    }
    static readJsonFile(filePath) {
      const fs = IEditor.require("fs");
      if (!fs.existsSync(filePath)) {
        return null;
      }
      try {
        return JSON.parse(fs.readFileSync(filePath, "utf-8"));
      } catch (e) {
        return null;
      }
    }
    static sortRecords(records) {
      records.sort((left, right) => left.file.localeCompare(right.file));
      return records;
    }
    static runWithConcurrency(items, concurrency, worker) {
      return __async(this, null, function* () {
        if (items.length === 0) {
          return;
        }
        let nextIndex = 0;
        const workerCount = Math.max(1, Math.min(concurrency, items.length));
        const runners = [];
        const runNext = /* @__PURE__ */ __name(() => __async(null, null, function* () {
          while (nextIndex < items.length) {
            const currentIndex = nextIndex;
            nextIndex++;
            yield worker(items[currentIndex], currentIndex);
          }
        }), "runNext");
        for (let i = 0; i < workerCount; i++) {
          runners.push(runNext());
        }
        yield Promise.all(runners);
      });
    }
  };
  __name(_AssetDependencyIndex, "AssetDependencyIndex");
  _AssetDependencyIndex.CACHE_VERSION = 2;
  _AssetDependencyIndex.CACHE_RELATIVE_PATH = "library/editor/asset_dependency_index.json";
  _AssetDependencyIndex.QUERY_CONCURRENCY = 24;
  _AssetDependencyIndex.SCAN_DIRS = ["assets", "src"];
  _AssetDependencyIndex.META_EXT = ".meta";
  _AssetDependencyIndex._buildPromise = null;
  _AssetDependencyIndex._backgroundBuildPromise = null;
  _AssetDependencyIndex._indexData = null;
  _AssetDependencyIndex._isDirty = false;
  _AssetDependencyIndex._isListening = false;
  __decorateClass([
    IEditor.onLoad
  ], _AssetDependencyIndex, "onLoad", 1);
  var AssetDependencyIndex = _AssetDependencyIndex;

  // src/Base/Utils/AssetSearchResultPanel.ts
  var AssetSearchResultPanel = class extends IEditor.EditorPanel {
    constructor() {
      super(...arguments);
      this._state = null;
      this._renderedSourceIds = [];
      this._renderedRowKeys = [];
      this._renderedPlaceholderText = "";
      this._isRebuildingIndex = false;
    }
    static showState(data) {
      AssetSearchResultPanel._pendingData = AssetSearchResultPanel.cloneData(data);
      Editor.panelManager.showPanel(AssetSearchResultPanel.PANEL_ID);
      const panel = Editor.panelManager.getPanel(
        AssetSearchResultPanel.PANEL_ID,
        AssetSearchResultPanel
      );
      panel == null ? void 0 : panel.applyPendingState();
    }
    static cloneData(data) {
      return __spreadProps(__spreadValues({}, data), {
        sources: [...data.sources],
        rows: [...data.rows]
      });
    }
    static createFallbackState() {
      return {
        mode: "dependency",
        title: "资源查找结果",
        sources: [],
        statusText: "",
        statusLevel: "info",
        isLoading: false,
        processedCount: 0,
        totalCount: 0,
        resultCount: 0,
        emptyText: "当前没有查询结果",
        rows: []
      };
    }
    create() {
      return __async(this, null, function* () {
        const defaultTextColor = IEditor.GUIUtils.textColor.getHex();
        this._root = new gui.Box();
        this._root.setSize(
          AssetSearchResultPanel.PANEL_WIDTH,
          AssetSearchResultPanel.PANEL_HEIGHT
        );
        this._root.on("size_changed", this.onRootSizeChanged, this);
        this._actionButton = IEditor.GUIUtils.createButton();
        this._actionButton.title = AssetSearchResultPanel.ACTION_BUTTON_TEXT;
        this._actionButton.onClick(() => this.onActionButtonClick());
        this._root.addChild(this._actionButton);
        this._titleText = this.createTextField(
          AssetSearchResultPanel.TITLE_HEIGHT,
          defaultTextColor,
          true
        );
        this._root.addChild(this._titleText);
        this._sourceHeaderText = this.createTextField(
          AssetSearchResultPanel.INFO_HEIGHT,
          defaultTextColor
        );
        this._root.addChild(this._sourceHeaderText);
        this._sourceList = this.createList(AssetSearchResultPanel.ITEM_HEIGHT);
        this._root.addChild(this._sourceList);
        this._statusText = this.createTextField(AssetSearchResultPanel.INFO_HEIGHT);
        this._root.addChild(this._statusText);
        this._summaryText = this.createTextField(
          AssetSearchResultPanel.INFO_HEIGHT,
          defaultTextColor
        );
        this._root.addChild(this._summaryText);
        this._resultList = this.createList(AssetSearchResultPanel.MIN_LIST_HEIGHT);
        this._root.addChild(this._resultList);
        this._panel = this._root;
        this.refreshLayout();
        this.applyPendingState();
      });
    }
    onDestroy() {
      var _a, _b, _c;
      (_a = this._root) == null ? void 0 : _a.offAllCaller(this);
      (_b = this._sourceList) == null ? void 0 : _b.offAllCaller(this);
      (_c = this._resultList) == null ? void 0 : _c.offAllCaller(this);
    }
    setState(data) {
      this._state = AssetSearchResultPanel.cloneData(data);
      if (!this._panel) {
        return;
      }
      this.renderState();
    }
    applyPendingState() {
      if (AssetSearchResultPanel._pendingData) {
        this.setState(AssetSearchResultPanel._pendingData);
      }
    }
    renderState() {
      if (!this._state) {
        return;
      }
      const state = this._state;
      const sourceAssets = state.sources || [];
      this._titleText.text = state.title;
      this._sourceHeaderText.text = this.getSourceHeaderText(sourceAssets.length);
      this._statusText.text = `状态：${state.statusText}`;
      this._statusText.color = this.getStatusColor(state.statusLevel);
      this.renderActionButton();
      this._summaryText.text = this.getSummaryText(state);
      this.renderSourceList(sourceAssets);
      this.renderResultList(state);
      this.refreshLayout();
      Editor.panelManager.setPanelTitle(
        this.panelId,
        `${AssetSearchResultPanel.PANEL_TITLE_PREFIX}${state.title}`
      );
    }
    renderSourceList(sources) {
      const sourceIds = sources.map((asset) => asset.id);
      if (!this.isStringListChanged(this._renderedSourceIds, sourceIds)) {
        return;
      }
      this.clearList(this._sourceList);
      this._renderedSourceIds = sourceIds;
      if (sources.length === 0) {
        this._sourceList.addChild(this.createStaticItem("当前选择"));
        return;
      }
      for (const asset of sources) {
        this._sourceList.addChild(this.createAssetItem(asset.file, asset.file, asset));
      }
    }
    renderResultList(state) {
      const placeholderText = this.getPlaceholderText(state);
      const rowKeys = state.rows.map((row) => row.key);
      if (!this.shouldRefreshRows(rowKeys, placeholderText)) {
        return;
      }
      this.clearList(this._resultList);
      this._renderedRowKeys = rowKeys;
      this._renderedPlaceholderText = placeholderText;
      if (state.rows.length > 0) {
        for (const row of state.rows) {
          this._resultList.addChild(this.createRowItem(row));
        }
        return;
      }
      this._resultList.addChild(this.createStaticItem(placeholderText));
    }
    shouldRefreshRows(rowKeys, placeholderText) {
      if (rowKeys.length === 0) {
        return this._renderedRowKeys.length !== 0 || this._renderedPlaceholderText !== placeholderText;
      }
      return this.isStringListChanged(this._renderedRowKeys, rowKeys);
    }
    clearList(list) {
      if (list.numChildren > 0) {
        list.removeChildren(0, list.numChildren - 1, true);
      }
    }
    createRowItem(row) {
      var _a;
      if (row.kind === "separator") {
        return this.createSeparatorItem(row);
      }
      if (row.kind === "issue") {
        return this.createIssueRowItem(row);
      }
      const item = IEditor.GUIUtils.createIconListItem();
      item.setSize(this._resultList.width, AssetSearchResultPanel.ITEM_HEIGHT);
      item.title = row.title;
      item.titleFontSize = AssetSearchResultPanel.FONT_SIZE;
      item.icon = row.icon || this.getAssetIcon(row.asset);
      item.tooltips = row.tooltips;
      item.data = row;
      if (row.clickable && ((_a = row.asset) == null ? void 0 : _a.id)) {
        item.on("click", this.onResultItemClick, this);
      } else {
        item.touchable = false;
      }
      return item;
    }
    createSeparatorItem(row) {
      const item = IEditor.GUIUtils.createListItem();
      item.setSize(this._resultList.width, AssetSearchResultPanel.ITEM_HEIGHT);
      item.title = row.title;
      item.titleFontSize = AssetSearchResultPanel.FONT_SIZE;
      item.grayed = true;
      item.touchable = false;
      return item;
    }
    createIssueRowItem(row) {
      const item = new gui.Box();
      item.setSize(this._resultList.width, AssetSearchResultPanel.ITEM_HEIGHT);
      item.tooltips = row.tooltips;
      item.data = row;
      const icon = new gui.Loader();
      icon.name = "issueIcon";
      icon.setLeftTop(0, Math.floor((AssetSearchResultPanel.ITEM_HEIGHT - AssetSearchResultPanel.ISSUE_ICON_SIZE) / 2));
      icon.setSize(AssetSearchResultPanel.ISSUE_ICON_SIZE, AssetSearchResultPanel.ISSUE_ICON_SIZE);
      icon.icon = row.icon || this.getAssetIcon(row.asset);
      icon.touchable = false;
      item.addChild(icon);
      const title = new gui.TextField();
      title.name = "issueTitle";
      title.setLeftTop(
        AssetSearchResultPanel.ISSUE_ICON_SIZE + AssetSearchResultPanel.ISSUE_ICON_GAP,
        0
      );
      title.setSize(
        Math.max(
          0,
          item.width - AssetSearchResultPanel.ISSUE_ICON_SIZE - AssetSearchResultPanel.ISSUE_ICON_GAP
        ),
        AssetSearchResultPanel.ITEM_HEIGHT
      );
      title.style.fontSize = AssetSearchResultPanel.FONT_SIZE;
      title.color = this.getStatusColor("warning");
      title.text = row.title;
      title.touchable = false;
      item.addChild(title);
      if (this.canActivateRow(row)) {
        item.cursor = "pointer";
        item.on("click", this.onResultItemClick, this);
      }
      return item;
    }
    createAssetItem(title, tooltips, asset) {
      const item = IEditor.GUIUtils.createIconListItem();
      item.setSize(this._sourceList.width, AssetSearchResultPanel.ITEM_HEIGHT);
      item.title = title;
      item.titleFontSize = AssetSearchResultPanel.FONT_SIZE;
      item.icon = this.getAssetIcon(asset);
      item.tooltips = tooltips;
      item.data = asset;
      item.on("click", this.onSourceItemClick, this);
      return item;
    }
    createStaticItem(text) {
      const item = IEditor.GUIUtils.createListItem();
      item.setSize(this._resultList.width, AssetSearchResultPanel.ITEM_HEIGHT);
      item.title = text;
      item.titleFontSize = AssetSearchResultPanel.FONT_SIZE;
      item.grayed = true;
      item.touchable = false;
      return item;
    }
    onRootSizeChanged() {
      this.refreshLayout();
    }
    onSourceItemClick(evt) {
      const item = evt.sender;
      const asset = item == null ? void 0 : item.data;
      if (!(asset == null ? void 0 : asset.id)) {
        return;
      }
      this.locateAsset(asset);
    }
    onResultItemClick(evt) {
      var _a;
      const item = evt.sender;
      const row = item == null ? void 0 : item.data;
      if (!(row == null ? void 0 : row.clickable)) {
        return;
      }
      if (row.copyText) {
        this.copyToClipboard(row.copyText);
        return;
      }
      if (!((_a = row.asset) == null ? void 0 : _a.id)) {
        return;
      }
      this.locateAsset(row.asset);
    }
    onActionButtonClick() {
      return __async(this, null, function* () {
        if (this._isRebuildingIndex) {
          return;
        }
        const confirmed = yield Editor.confirm(AssetSearchResultPanel.ACTION_CONFIRM_TEXT);
        if (!confirmed) {
          return;
        }
        yield this.rebuildDependencyIndex();
      });
    }
    locateAsset(asset) {
      const projectPanel = Editor.panelManager.getPanel("ProjectPanel");
      if (!projectPanel) {
        return;
      }
      Editor.panelManager.showPanel("ProjectPanel");
      projectPanel.select(asset.id, true);
    }
    copyToClipboard(text) {
      try {
        Editor.clipboard.writeText(text);
      } catch (error) {
        void Editor.alert(`复制失败：${this.getErrorMessage(error)}`, "error");
        console.error("[AssetSearchResultPanel] 复制文本失败:", error);
      }
    }
    createTextField(height, color, bold = false) {
      const text = new gui.TextField();
      text.setSize(0, height);
      text.style.fontSize = AssetSearchResultPanel.FONT_SIZE;
      text.style.bold = bold;
      if (color != null) {
        text.color = color;
      }
      return text;
    }
    createList(initialHeight) {
      const list = new gui.List();
      list.setSize(0, initialHeight);
      list.layout.type = gui.LayoutType.SingleColumn;
      list.layout.rowGap = AssetSearchResultPanel.LIST_ROW_GAP;
      list.layout.stretchX = gui.StretchMode.Stretch;
      list.scroller = new gui.Scroller();
      list.scroller.direction = gui.ScrollDirection.Vertical;
      list.scroller.barDisplay = gui.ScrollBarDisplay.OnOverflow;
      list.selectionMode = gui.SelectionMode.Disabled;
      return list;
    }
    canActivateRow(row) {
      var _a;
      return row.clickable && (!!row.copyText || !!((_a = row.asset) == null ? void 0 : _a.id));
    }
    getAssetIcon(asset) {
      if (!asset) {
        return "";
      }
      return Editor.assetDb.getAssetIcon(asset);
    }
    getSourceHeaderText(sourceCount) {
      return sourceCount > 1 ? `目标（${sourceCount}）：` : "目标：";
    }
    getSummaryText(state) {
      const progressText = state.totalCount > 0 ? ` | 已处理：${state.processedCount}/${state.totalCount}` : "";
      return `结果：${state.resultCount} 项${progressText}`;
    }
    renderActionButton() {
      this._actionButton.visible = true;
      this._actionButton.title = this._isRebuildingIndex ? AssetSearchResultPanel.ACTION_BUTTON_LOADING_TEXT : AssetSearchResultPanel.ACTION_BUTTON_TEXT;
      this._actionButton.touchable = !this._isRebuildingIndex;
      this._actionButton.grayed = this._isRebuildingIndex;
    }
    getPlaceholderText(state) {
      if (state.isLoading) {
        return state.statusText;
      }
      if (state.statusLevel === "error") {
        return state.statusText;
      }
      return state.emptyText;
    }
    getSourceListHeight(sourceCount) {
      const visibleSourceCount = Math.min(
        Math.max(1, sourceCount),
        AssetSearchResultPanel.MAX_VISIBLE_SOURCE_ITEMS
      );
      return visibleSourceCount * AssetSearchResultPanel.ITEM_HEIGHT + Math.max(0, visibleSourceCount - 1) * AssetSearchResultPanel.LIST_ROW_GAP;
    }
    getErrorMessage(error) {
      if (error instanceof Error && error.message) {
        return error.message;
      }
      return String(error);
    }
    getStatusColor(level) {
      switch (level) {
        case "success":
          return 3050327;
        case "warning":
          return 12092939;
        case "error":
          return 12597547;
        default:
          return IEditor.GUIUtils.textColor.getHex();
      }
    }
    refreshLayout() {
      if (!this._root) {
        return;
      }
      const panelWidth = this._root.width || AssetSearchResultPanel.PANEL_WIDTH;
      const panelHeight = this._root.height || AssetSearchResultPanel.PANEL_HEIGHT;
      const contentWidth = Math.max(0, panelWidth - AssetSearchResultPanel.PADDING * 2);
      const sourceListHeight = this.getSourceListHeight(this._sourceList.numChildren);
      let posY = AssetSearchResultPanel.PADDING;
      this._actionButton.setPos(AssetSearchResultPanel.PADDING, posY);
      this._actionButton.setSize(
        AssetSearchResultPanel.ACTION_BUTTON_WIDTH,
        AssetSearchResultPanel.ACTION_BUTTON_HEIGHT
      );
      posY += AssetSearchResultPanel.ACTION_ROW_HEIGHT + AssetSearchResultPanel.ROW_GAP;
      this._titleText.setLeftTop(AssetSearchResultPanel.PADDING, posY);
      this._titleText.setSize(contentWidth, AssetSearchResultPanel.TITLE_HEIGHT);
      posY += AssetSearchResultPanel.TITLE_HEIGHT + AssetSearchResultPanel.ROW_GAP;
      this._sourceHeaderText.setLeftTop(AssetSearchResultPanel.PADDING, posY);
      this._sourceHeaderText.setSize(contentWidth, AssetSearchResultPanel.INFO_HEIGHT);
      posY += AssetSearchResultPanel.INFO_HEIGHT + AssetSearchResultPanel.LIST_ROW_GAP;
      this._sourceList.setLeftTop(AssetSearchResultPanel.PADDING, posY);
      this._sourceList.setSize(contentWidth, sourceListHeight);
      this.refreshItemWidths(this._sourceList, contentWidth);
      posY += sourceListHeight + AssetSearchResultPanel.ROW_GAP;
      this._statusText.setLeftTop(AssetSearchResultPanel.PADDING, posY);
      this._statusText.setSize(contentWidth, AssetSearchResultPanel.INFO_HEIGHT);
      posY += AssetSearchResultPanel.INFO_HEIGHT + AssetSearchResultPanel.ROW_GAP;
      this._summaryText.setLeftTop(AssetSearchResultPanel.PADDING, posY);
      this._summaryText.setSize(contentWidth, AssetSearchResultPanel.INFO_HEIGHT);
      posY += AssetSearchResultPanel.INFO_HEIGHT + AssetSearchResultPanel.ROW_GAP;
      const listHeight = Math.max(
        AssetSearchResultPanel.MIN_LIST_HEIGHT,
        panelHeight - posY - AssetSearchResultPanel.PADDING
      );
      this._resultList.setLeftTop(AssetSearchResultPanel.PADDING, posY);
      this._resultList.setSize(contentWidth, listHeight);
      this.refreshItemWidths(this._resultList, contentWidth);
    }
    refreshItemWidths(list, width) {
      for (const child of list.children) {
        child.setSize(width, AssetSearchResultPanel.ITEM_HEIGHT);
        const title = child.getChild("issueTitle", gui.TextField);
        if (title) {
          this.resizeIssueTitle(title, width);
        }
      }
    }
    resizeIssueTitle(title, width) {
      title.setSize(
        Math.max(
          0,
          width - AssetSearchResultPanel.ISSUE_ICON_SIZE - AssetSearchResultPanel.ISSUE_ICON_GAP
        ),
        AssetSearchResultPanel.ITEM_HEIGHT
      );
    }
    isStringListChanged(renderedValues, currentValues) {
      if (renderedValues.length !== currentValues.length) {
        return true;
      }
      for (let i = 0; i < currentValues.length; i++) {
        if (renderedValues[i] !== currentValues[i]) {
          return true;
        }
      }
      return false;
    }
    rebuildDependencyIndex() {
      return __async(this, null, function* () {
        const baseState = this._state || AssetSearchResultPanel.createFallbackState();
        this._isRebuildingIndex = true;
        this.updateRebuildState(baseState, AssetSearchResultPanel.ACTION_STATUS_TEXT, "info", true, 0, 0);
        try {
          const indexData = yield AssetDependencyIndex.rebuild({
            onProgress: /* @__PURE__ */ __name((processedCount, totalCount) => {
              const statusText = totalCount > 0 ? `${AssetSearchResultPanel.ACTION_STATUS_TEXT} ${processedCount}/${totalCount}` : AssetSearchResultPanel.ACTION_STATUS_TEXT;
              this.updateRebuildState(baseState, statusText, "info", true, processedCount, totalCount);
            }, "onProgress")
          });
          this.updateRebuildState(
            baseState,
            `依赖索引已重建，已索引 ${indexData.assetCount} 个资源`,
            "success",
            false,
            indexData.assetCount,
            indexData.assetCount
          );
        } catch (error) {
          this.updateRebuildState(
            baseState,
            `重建索引失败：${this.getErrorMessage(error)}`,
            "error",
            false,
            0,
            0
          );
          console.error("[AssetSearchResultPanel] 重建依赖索引失败:", error);
        } finally {
          this._isRebuildingIndex = false;
          this.renderActionButton();
        }
      });
    }
    updateRebuildState(baseState, statusText, statusLevel, isLoading, processedCount, totalCount) {
      this.setState(__spreadProps(__spreadValues({}, baseState), {
        statusText,
        statusLevel,
        isLoading,
        processedCount,
        totalCount
      }));
    }
  };
  __name(AssetSearchResultPanel, "AssetSearchResultPanel");
  AssetSearchResultPanel.PANEL_ID = "AssetSearchResultPanel";
  AssetSearchResultPanel.PANEL_TITLE_PREFIX = "资源查找结果 - ";
  AssetSearchResultPanel.FONT_SIZE = 12;
  AssetSearchResultPanel.PANEL_WIDTH = 720;
  AssetSearchResultPanel.PANEL_HEIGHT = 520;
  AssetSearchResultPanel.PADDING = 8;
  AssetSearchResultPanel.ROW_GAP = 4;
  AssetSearchResultPanel.TITLE_HEIGHT = 22;
  AssetSearchResultPanel.INFO_HEIGHT = 18;
  AssetSearchResultPanel.ITEM_HEIGHT = 24;
  AssetSearchResultPanel.LIST_ROW_GAP = 2;
  AssetSearchResultPanel.MIN_LIST_HEIGHT = 96;
  AssetSearchResultPanel.MAX_VISIBLE_SOURCE_ITEMS = 3;
  AssetSearchResultPanel.ISSUE_ICON_SIZE = 14;
  AssetSearchResultPanel.ISSUE_ICON_GAP = 4;
  AssetSearchResultPanel.ACTION_BUTTON_WIDTH = 92;
  AssetSearchResultPanel.ACTION_BUTTON_HEIGHT = 28;
  AssetSearchResultPanel.ACTION_ROW_HEIGHT = 28;
  AssetSearchResultPanel.ACTION_BUTTON_TEXT = "重建索引";
  AssetSearchResultPanel.ACTION_BUTTON_LOADING_TEXT = "重建中...";
  AssetSearchResultPanel.ACTION_STATUS_TEXT = "正在重建依赖索引...";
  AssetSearchResultPanel.ACTION_CONFIRM_TEXT = "重建依赖索引可能耗时较长，是否继续？";
  AssetSearchResultPanel._pendingData = null;
  AssetSearchResultPanel = __decorateClass([
    IEditor.panel("AssetSearchResultPanel", {
      title: "资源查找结果",
      location: "popup",
      allowTabs: true,
      showInMenu: false,
      stretchPriorityX: 1,
      stretchPriorityY: 1
    })
  ], AssetSearchResultPanel);

  // src/Base/Utils/FindDependencies.ts
  var _FindDependencies = class _FindDependencies {
    static onLoad() {
      Editor.extensionManager.addMenuItem("Project/查找引用", () => {
        _FindDependencies.findReferences();
      }, {
        visibleTest: /* @__PURE__ */ __name(() => _FindDependencies.hasSelectedFilesOnly(), "visibleTest"),
        position: _FindDependencies.FILE_MENU_POSITION
      });
      Editor.extensionManager.addMenuItem("Project/查找依赖", () => {
        _FindDependencies.findDependencies();
      }, {
        visibleTest: /* @__PURE__ */ __name(() => _FindDependencies.hasSelectedFilesOnly(), "visibleTest"),
        position: _FindDependencies.FILE_MENU_POSITION
      });
      Editor.extensionManager.addMenuItem("Project/查找无用的资源", () => {
        _FindDependencies.findByFolder("unused");
      }, {
        visibleTest: /* @__PURE__ */ __name(() => _FindDependencies.isFolderSelected(), "visibleTest"),
        position: _FindDependencies.FOLDER_MENU_POSITION
      });
      Editor.extensionManager.addMenuItem("Project/查找在用的资源", () => {
        _FindDependencies.findByFolder("used");
      }, {
        visibleTest: /* @__PURE__ */ __name(() => _FindDependencies.isFolderSelected(), "visibleTest"),
        position: _FindDependencies.FOLDER_MENU_POSITION
      });
    }
    static getSelectedResources() {
      const projectPanel = Editor.panelManager.getPanel("ProjectPanel");
      if (!projectPanel) {
        return [];
      }
      const assets = projectPanel.getSelectedResources([]);
      const filteredAssets = assets.filter((asset2) => !!(asset2 == null ? void 0 : asset2.id));
      if (filteredAssets.length > 0) {
        return filteredAssets;
      }
      const asset = projectPanel.getSelectedResource();
      return (asset == null ? void 0 : asset.id) ? [asset] : [];
    }
    static getSelectedSearchFileAssets() {
      const assets = _FindDependencies.getSelectedResources();
      return assets.length > 0 && assets.every((asset) => !!asset.ext) ? assets : [];
    }
    static getSelectedFolderAsset() {
      const assets = _FindDependencies.getSelectedResources();
      return assets.length === 1 && !assets[0].ext ? assets[0] : null;
    }
    static hasSelectedFilesOnly() {
      return _FindDependencies.getSelectedSearchFileAssets().length > 0;
    }
    static isFolderSelected() {
      return !!_FindDependencies.getSelectedFolderAsset();
    }
    static findReferences() {
      return __async(this, null, function* () {
        const sourceAssets = _FindDependencies.getSelectedSearchFileAssets();
        if (sourceAssets.length === 0) {
          return;
        }
        yield _FindDependencies.runFindReferences(sourceAssets);
      });
    }
    static runFindReferences(sourceAssets) {
      return __async(this, null, function* () {
        try {
          AssetSearchResultPanel.showState(_FindDependencies.createPanelData("reference", sourceAssets, [], {
            statusText: _FindDependencies.getIndexBuildStatusText(0, 0),
            statusLevel: "info",
            isLoading: true,
            processedCount: 0,
            totalCount: 0
          }));
          yield AssetDependencyIndex.ensureReady({
            onProgress: /* @__PURE__ */ __name((processedCount, totalCount) => {
              AssetSearchResultPanel.showState(_FindDependencies.createPanelData("reference", sourceAssets, [], {
                statusText: _FindDependencies.getIndexBuildStatusText(processedCount, totalCount),
                statusLevel: "info",
                isLoading: true,
                processedCount,
                totalCount
              }));
            }, "onProgress")
          });
          const leveledRecords = AssetDependencyIndex.getReferenceRecordsByLevel(
            sourceAssets.map((asset) => asset.id)
          );
          const leveledAssets = leveledRecords.map(
            (records) => records.map((record) => AssetDependencyIndex.createAssetInfo(record))
          );
          const rows = _FindDependencies.buildLeveledRows([], leveledAssets, "引用");
          const status = _FindDependencies.getReferenceCompletedStatus(rows);
          _FindDependencies.showCompleted("reference", sourceAssets, rows, {
            processedCount: sourceAssets.length,
            totalCount: sourceAssets.length,
            statusText: status.text,
            statusLevel: status.level
          });
        } catch (error) {
          _FindDependencies.showError("reference", sourceAssets, error);
          console.error("[FindDependencies] 查找引用失败:", error);
        }
      });
    }
    static findDependencies() {
      return __async(this, null, function* () {
        const sourceAssets = _FindDependencies.getSelectedSearchFileAssets();
        if (sourceAssets.length === 0) {
          return;
        }
        yield _FindDependencies.runFindDependencies(sourceAssets);
      });
    }
    static runFindDependencies(sourceAssets) {
      return __async(this, null, function* () {
        const issueRows = [];
        try {
          AssetSearchResultPanel.showState(_FindDependencies.createPanelData("dependency", sourceAssets, [], {
            statusText: _FindDependencies.getIndexBuildStatusText(0, 0),
            statusLevel: "info",
            isLoading: true,
            processedCount: 0,
            totalCount: 0
          }));
          yield AssetDependencyIndex.ensureReady({
            onProgress: /* @__PURE__ */ __name((processedCount, totalCount) => {
              AssetSearchResultPanel.showState(_FindDependencies.createPanelData("dependency", sourceAssets, [], {
                statusText: _FindDependencies.getIndexBuildStatusText(processedCount, totalCount),
                statusLevel: "info",
                isLoading: true,
                processedCount,
                totalCount
              }));
            }, "onProgress")
          });
          for (const asset of sourceAssets) {
            const missingRefs = AssetDependencyIndex.getMissingReferences(asset.id);
            if (missingRefs.length > 0) {
              issueRows.push(..._FindDependencies.createMissingReferenceRows(asset, missingRefs));
            }
          }
          const leveledRecords = AssetDependencyIndex.getDependencyRecordsByLevel(
            sourceAssets.map((asset) => asset.id)
          );
          for (const levelRecords of leveledRecords) {
            for (const record of levelRecords) {
              const missingRefs = AssetDependencyIndex.getMissingReferences(record.id);
              if (missingRefs.length > 0) {
                issueRows.push(..._FindDependencies.createMissingReferenceRows(
                  AssetDependencyIndex.createAssetInfo(record),
                  missingRefs
                ));
              }
            }
          }
          const leveledAssets = leveledRecords.map(
            (records) => records.map((record) => AssetDependencyIndex.createAssetInfo(record))
          );
          const rows = _FindDependencies.buildLeveledRows(issueRows, leveledAssets, "依赖");
          const status = _FindDependencies.getDependencyCompletedStatus(rows, issueRows.length);
          _FindDependencies.showCompleted("dependency", sourceAssets, rows, {
            processedCount: sourceAssets.length,
            totalCount: sourceAssets.length,
            statusText: status.text,
            statusLevel: status.level
          });
        } catch (error) {
          const rows = _FindDependencies.buildLeveledRows(issueRows, [], "依赖");
          _FindDependencies.showError(
            "dependency",
            sourceAssets,
            error,
            rows,
            0,
            sourceAssets.length
          );
          console.error("[FindDependencies] 查找依赖失败:", error);
        }
      });
    }
    static findByFolder(mode) {
      return __async(this, null, function* () {
        const folder = _FindDependencies.getSelectedFolderAsset();
        if (!(folder == null ? void 0 : folder.id)) {
          return;
        }
        yield _FindDependencies.runFindByFolder(folder, mode);
      });
    }
    static runFindByFolder(folder, mode) {
      return __async(this, null, function* () {
        try {
          AssetSearchResultPanel.showState(_FindDependencies.createPanelData(mode, [folder], [], {
            statusText: _FindDependencies.getIndexBuildStatusText(0, 0),
            statusLevel: "info",
            isLoading: true,
            processedCount: 0,
            totalCount: 0
          }));
          yield AssetDependencyIndex.ensureReady({
            onProgress: /* @__PURE__ */ __name((processedCount, totalCount) => {
              AssetSearchResultPanel.showState(_FindDependencies.createPanelData(mode, [folder], [], {
                statusText: _FindDependencies.getIndexBuildStatusText(processedCount, totalCount),
                statusLevel: "info",
                isLoading: true,
                processedCount,
                totalCount
              }));
            }, "onProgress")
          });
          const resources = AssetDependencyIndex.getFolderRecords(folder.file);
          const resultAssets = resources.filter((asset) => {
            const used = AssetDependencyIndex.hasReferences(asset.id);
            return mode === "used" && used || mode === "unused" && !used;
          }).map((record) => AssetDependencyIndex.createAssetInfo(record));
          _FindDependencies.showCompleted(
            mode,
            [folder],
            _FindDependencies.createAssetRows(resultAssets),
            {
              processedCount: resources.length,
              totalCount: resources.length
            }
          );
        } catch (error) {
          _FindDependencies.showError(
            mode,
            [folder],
            error,
            [],
            0,
            0
          );
          console.error(`[FindDependencies] ${_FindDependencies.getPanelTitle(mode)}失败:`, error);
        }
      });
    }
    static showCompleted(mode, sources, rows, options) {
      var _a, _b, _c;
      const resultCount = rows.filter((row) => row.kind !== "separator").length;
      AssetSearchResultPanel.showState(_FindDependencies.createPanelData(mode, sources, rows, {
        statusText: (options == null ? void 0 : options.statusText) || (resultCount > 0 ? `查找完成，找到 ${resultCount} 个结果` : _FindDependencies.getEmptyStatusText(mode)),
        statusLevel: (options == null ? void 0 : options.statusLevel) || (resultCount > 0 ? "success" : "warning"),
        isLoading: false,
        processedCount: (_b = (_a = options == null ? void 0 : options.processedCount) != null ? _a : options == null ? void 0 : options.totalCount) != null ? _b : 0,
        totalCount: (_c = options == null ? void 0 : options.totalCount) != null ? _c : 0
      }));
    }
    static showError(mode, sources, error, rows = [], processedCount = 0, totalCount = 0) {
      AssetSearchResultPanel.showState(_FindDependencies.createPanelData(mode, sources, rows, {
        statusText: `查找失败：${_FindDependencies.getErrorMessage(error)}`,
        statusLevel: "error",
        isLoading: false,
        processedCount,
        totalCount
      }));
    }
    static createPanelData(mode, sources, rows, options) {
      var _a, _b;
      return {
        mode,
        title: _FindDependencies.getPanelTitle(mode),
        sources: [...sources],
        statusText: options.statusText,
        statusLevel: options.statusLevel,
        isLoading: options.isLoading,
        processedCount: (_a = options.processedCount) != null ? _a : 0,
        totalCount: (_b = options.totalCount) != null ? _b : 0,
        resultCount: rows.filter((row) => row.kind !== "separator").length,
        emptyText: _FindDependencies.getEmptyStatusText(mode),
        rows: [...rows]
      };
    }
    static buildLeveledRows(issueRows, leveledAssets, levelLabel) {
      const rows = [..._FindDependencies.sortIssueRows(issueRows)];
      for (let i = 0; i < leveledAssets.length; i++) {
        rows.push(_FindDependencies.createLevelSeparatorRow(i + 1, levelLabel));
        rows.push(..._FindDependencies.createAssetRows(leveledAssets[i]));
      }
      return rows;
    }
    static createLevelSeparatorRow(level, label) {
      return {
        key: `separator:level:${level}`,
        kind: "separator",
        asset: null,
        title: `── 第 ${level} 级${label} ──`,
        tooltips: "",
        clickable: false
      };
    }
    static createAssetRows(assets) {
      const sortedAssets = [...assets];
      _FindDependencies.sortAssets(sortedAssets);
      return sortedAssets.map((asset) => _FindDependencies.createAssetRow(asset));
    }
    static createMissingReferenceRows(asset, missingRefs) {
      return _FindDependencies.normalizeMissingReferences(missingRefs).map((missingRef) => {
        return _FindDependencies.createMissingReferenceRow(asset, missingRef);
      });
    }
    static sortIssueRows(rows) {
      return [...rows].sort((left, right) => {
        var _a, _b;
        const titleCompare = left.title.localeCompare(right.title);
        if (titleCompare !== 0) {
          return titleCompare;
        }
        const leftFile = ((_a = left.asset) == null ? void 0 : _a.file) || "";
        const rightFile = ((_b = right.asset) == null ? void 0 : _b.file) || "";
        return leftFile.localeCompare(rightFile);
      });
    }
    static getDependencyCompletedStatus(rows, issueCount) {
      const depCount = rows.filter((row) => row.kind === "asset").length;
      const levelCount = rows.filter((row) => row.kind === "separator").length;
      if (depCount === 0 && issueCount === 0) {
        return {
          text: _FindDependencies.getEmptyStatusText("dependency"),
          level: "warning"
        };
      }
      let text = `查找完成，找到 ${depCount} 个依赖`;
      if (levelCount > 1) {
        text += `（${levelCount} 级）`;
      }
      if (issueCount > 0) {
        text += `，${issueCount} 个无效/丢失 UUID`;
      }
      return {
        text,
        level: issueCount > 0 ? "warning" : "success"
      };
    }
    static getReferenceCompletedStatus(rows) {
      const refCount = rows.filter((row) => row.kind === "asset").length;
      const levelCount = rows.filter((row) => row.kind === "separator").length;
      if (refCount === 0) {
        return {
          text: _FindDependencies.getEmptyStatusText("reference"),
          level: "warning"
        };
      }
      let text = `查找完成，找到 ${refCount} 个引用`;
      if (levelCount > 1) {
        text += `（${levelCount} 级）`;
      }
      return { text, level: "success" };
    }
    static getIndexBuildStatusText(processedCount, totalCount) {
      if (totalCount <= 0) {
        return _FindDependencies.INDEX_BUILD_PREFIX;
      }
      return `${_FindDependencies.INDEX_BUILD_PREFIX} ${processedCount}/${totalCount}`;
    }
    static getPanelTitle(mode) {
      switch (mode) {
        case "reference":
          return "查找引用";
        case "dependency":
          return "查找依赖";
        case "unused":
          return "查找无用的资源";
        case "used":
          return "查找在用的资源";
      }
    }
    static getEmptyStatusText(mode) {
      switch (mode) {
        case "reference":
          return "未找到引用";
        case "dependency":
          return "未找到依赖";
        case "unused":
          return "未找到无用资源";
        case "used":
          return "未找到在用资源";
      }
    }
    static getErrorMessage(error) {
      if (error instanceof Error && error.message) {
        return error.message;
      }
      return String(error);
    }
    static sortAssets(assets) {
      assets.sort((left, right) => {
        return left.file.localeCompare(right.file);
      });
    }
    static normalizeMissingReferences(missingRefs) {
      const normalizedRefs = [...new Set(
        missingRefs.map((missingRef) => missingRef.trim()).filter((missingRef) => missingRef.length > 0)
      )];
      normalizedRefs.sort((left, right) => left.localeCompare(right));
      return normalizedRefs;
    }
    static createAssetRow(asset) {
      return {
        key: `asset:${asset.id}`,
        kind: "asset",
        asset,
        title: asset.file,
        tooltips: asset.file,
        clickable: true,
        icon: Editor.assetDb.getAssetIcon(asset)
      };
    }
    static createMissingReferenceRow(asset, missingRef) {
      return {
        key: `issue:${asset.id}:${missingRef}`,
        kind: "issue",
        asset,
        title: `[无效/丢失UUID] ${missingRef}`,
        tooltips: `缺失项：${missingRef}
来源文件：${asset.file}
点击可复制 UUID`,
        clickable: true,
        copyText: missingRef,
        icon: Editor.assetDb.getAssetIcon(asset)
      };
    }
  };
  __name(_FindDependencies, "FindDependencies");
  _FindDependencies.FILE_MENU_POSITION = "before findReferencesInScene";
  _FindDependencies.FOLDER_MENU_POSITION = "before findReferencesInScene";
  _FindDependencies.INDEX_BUILD_PREFIX = "正在构建依赖索引...";
  __decorateClass([
    IEditor.onLoad
  ], _FindDependencies, "onLoad", 1);
  var FindDependencies = _FindDependencies;

  // src/Base/Utils/FindNodesByComponentType.ts
  var _FindNodesByComponentType = class _FindNodesByComponentType {
    static onLoad() {
      for (const label of Object.keys(this.filters)) {
        const filterText = this.filters[label];
        Editor.extensionManager.addMenuItem(`Hierarchy-Tool/${label}`, () => {
          Editor.panelManager.postMessage("HierarchyPanel", "findNodes", filterText);
        }, {
          position: "after findScripts"
        });
      }
    }
  };
  __name(_FindNodesByComponentType, "FindNodesByComponentType");
  _FindNodesByComponentType.filters = {
    "查找SkinnedMeshRenderer": "t:SkinnedMeshRenderer",
    "查找MeshRenderer": "t:MeshRenderer",
    "查找2D粒子": "t:ShurikenParticle2DRenderer",
    "查找3D粒子": "t:ShurikenParticleRenderer",
    "查找Animator": "t:Animator"
  };
  __decorateClass([
    IEditor.onLoad
  ], _FindNodesByComponentType, "onLoad", 1);
  var FindNodesByComponentType = _FindNodesByComponentType;

  // src/Base/Utils/OpenFile.ts
  var _OpenFile = class _OpenFile {
    static onLoad() {
      Editor.extensionManager.addMenuItem("Project/打开", () => {
        _OpenFile.openSelectedFile();
      }, {
        visibleTest: /* @__PURE__ */ __name(() => _OpenFile.canOpenSelectedFile(), "visibleTest"),
        position: "after create"
      });
      const commonExts = [
        "png",
        "jpg",
        "jpeg",
        "tga",
        "gif",
        "bmp",
        "webp",
        "svg",
        "ico",
        "txt",
        "json",
        "xml",
        "csv",
        "md",
        "log",
        "mp3",
        "mp4",
        "wav",
        "ogg",
        "avi",
        "mov",
        "pdf",
        "doc",
        "docx",
        "xls",
        "xlsx",
        "ppt",
        "pptx",
        "zip",
        "rar",
        "7z",
        "tar",
        "gz",
        "html",
        "htm",
        "css",
        "js",
        "ts",
        "jsx",
        "tsx",
        "lmat",
        "lh",
        "lani",
        "ls",
        "lprefab",
        "lscene"
      ];
      Editor.extensionManager.addFileActions(commonExts, {
        onOpen: /* @__PURE__ */ __name((asset) => __async(null, null, function* () {
          _OpenFile.openFile(asset);
        }), "onOpen")
      });
    }
    static openSelectedFile() {
      const projectPanel = Editor.panelManager.getPanel("ProjectPanel");
      const asset = projectPanel == null ? void 0 : projectPanel.getSelectedResource();
      if (!asset) {
        console.log("未选中任何资源");
        return;
      }
      _OpenFile.openFile(asset);
    }
    static canOpenSelectedFile() {
      const projectPanel = Editor.panelManager.getPanel("ProjectPanel");
      const asset = projectPanel == null ? void 0 : projectPanel.getSelectedResource();
      if (!asset) {
        return false;
      }
      const fs = IEditor.require("fs");
      const fullPath = Editor.assetDb.getFullPath(asset);
      if (!fs.existsSync(fullPath)) {
        return false;
      }
      const stat = fs.statSync(fullPath);
      return !stat.isDirectory();
    }
    static openFile(asset) {
      if (asset.ext === "ls") {
        const activeScene = Editor.sceneManager.activeScene;
        if (activeScene && activeScene.asset && activeScene.asset.id === asset.id) {
          Editor.sceneManager.reloadScene(activeScene.sceneId);
        } else {
          Editor.openFile(asset.file);
        }
        return;
      }
      const fs = IEditor.require("fs");
      const fullPath = Editor.assetDb.getFullPath(asset);
      if (!fs.existsSync(fullPath)) {
        console.log("文件不存在:", fullPath);
        return;
      }
      const stat = fs.statSync(fullPath);
      if (stat.isDirectory()) {
        return;
      }
      const electron = IEditor.require("electron");
      electron.shell.openPath(fullPath).then(() => {
      }).catch((error) => {
        console.warn("打开文件失败:", error);
      });
    }
  };
  __name(_OpenFile, "OpenFile");
  __decorateClass([
    IEditor.onLoad
  ], _OpenFile, "onLoad", 1);
  var OpenFile = _OpenFile;

  // src/Base/Utils/SelectSceneAsset.ts
  var _SelectSceneAsset = class _SelectSceneAsset {
    static onLoad() {
      Editor.extensionManager.addMenuItem("Hierarchy/选择场景资源", () => {
        _SelectSceneAsset.selectSceneAsset();
      }, {
        visibleTest: /* @__PURE__ */ __name(() => _SelectSceneAsset.canSelectSceneAsset(), "visibleTest"),
        position: "first"
      });
      Editor.extensionManager.addMenuItem("Hierarchy/撤销场景修改", () => {
        _SelectSceneAsset.reloadCurrentScene();
      }, {
        visibleTest: /* @__PURE__ */ __name(() => _SelectSceneAsset.canReloadCurrentScene(), "visibleTest")
      });
    }
    /**
     * 检查是否可以选择场景资源
     * 只有当前场景已保存时才允许执行
     */
    static canSelectSceneAsset() {
      const scene = Editor.sceneManager.activeScene;
      if (!scene) {
        return false;
      }
      const asset = scene.asset;
      return !!asset && !!asset.id;
    }
    static canReloadCurrentScene() {
      const scene = Editor.sceneManager.activeScene;
      return !!scene && !!scene.sceneId;
    }
    /**
     * 在项目资源面板中选中当前场景资源
     */
    static selectSceneAsset() {
      const scene = Editor.sceneManager.activeScene;
      if (!scene) {
        console.log("[SelectSceneAsset] 没有打开的场景");
        return;
      }
      const asset = scene.asset;
      if (!asset || !asset.id) {
        console.log("[SelectSceneAsset] 当前场景尚未保存");
        Editor.alert("当前场景尚未保存，无法定位场景资源文件", "info");
        return;
      }
      const projectPanel = Editor.panelManager.getPanel("ProjectPanel");
      if (!projectPanel) {
        console.error("[SelectSceneAsset] 无法获取项目资源面板");
        return;
      }
      projectPanel.select(asset.id, true);
      console.log(`[SelectSceneAsset] 已定位到场景资源: ${asset.file}`);
    }
    static reloadCurrentScene() {
      const scene = Editor.sceneManager.activeScene;
      if (!scene) {
        console.log("[SelectSceneAsset] 没有打开的场景");
        return;
      }
      Editor.sceneManager.reloadScene(scene.sceneId).catch((error) => {
        console.error("[SelectSceneAsset] 还原当前场景修改失败:", error);
      });
    }
  };
  __name(_SelectSceneAsset, "SelectSceneAsset");
  __decorateClass([
    IEditor.onLoad
  ], _SelectSceneAsset, "onLoad", 1);
  var SelectSceneAsset = _SelectSceneAsset;
})();
//# sourceMappingURL=bundle.editor.js.map
