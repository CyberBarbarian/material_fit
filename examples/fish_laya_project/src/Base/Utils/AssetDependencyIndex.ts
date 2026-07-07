interface IIndexedAssetRecord {
    id: string;
    file: string;
    ext: string;
    dependencies: string[];
    missingRefs: string[];
}

interface IAssetDependencyIndexCache {
    version: number;
    builtAt: number;
    assetCount: number;
    latestModifiedMs: number;
    records: IIndexedAssetRecord[];
}

interface IAssetSourceRecord {
    id: string;
    file: string;
    ext: string;
}

interface IAssetScanResult {
    assetCount: number;
    latestModifiedMs: number;
    records: IAssetSourceRecord[];
}

interface IAssetProjectSnapshot {
    assetCount: number;
    latestModifiedMs: number;
}

interface IAssetDependencyIndexData {
    assetCount: number;
    builtAt: number;
    latestModifiedMs: number;
    missingRefsByAssetId: ReadonlyMap<string, readonly string[]>;
    recordsById: ReadonlyMap<string, Readonly<IIndexedAssetRecord>>;
    recordsByPrefix: ReadonlyArray<Readonly<IIndexedAssetRecord>>;
    reverseReferenceCountById: ReadonlyMap<string, number>;
    reverseReferencesById: ReadonlyMap<string, readonly string[]>;
}

interface IEnsureIndexOptions {
    forceRebuild?: boolean;
    onProgress?: (processedCount: number, totalCount: number) => void;
}

export class AssetDependencyIndex {
    private static readonly CACHE_VERSION: number = 2;
    private static readonly CACHE_RELATIVE_PATH: string = "library/editor/asset_dependency_index.json";
    private static readonly QUERY_CONCURRENCY: number = 24;
    private static readonly SCAN_DIRS: readonly string[] = ["assets", "src"];
    private static readonly META_EXT: string = ".meta";

    private static _buildPromise: Promise<IAssetDependencyIndexData> | null = null;
    private static _backgroundBuildPromise: Promise<void> | null = null;
    private static _indexData: IAssetDependencyIndexData | null = null;
    private static _isDirty: boolean = false;
    private static _isListening: boolean = false;

    @IEditor.onLoad
    public static onLoad(): void {
        AssetDependencyIndex.ensureListeners();
    }

    public static async ensureReady(options?: IEnsureIndexOptions): Promise<IAssetDependencyIndexData> {
        AssetDependencyIndex.ensureListeners();

        if (!options?.forceRebuild && AssetDependencyIndex._indexData && !AssetDependencyIndex._isDirty) {
            return AssetDependencyIndex._indexData;
        }

        if (AssetDependencyIndex._buildPromise) {
            return AssetDependencyIndex._buildPromise;
        }

        // 有旧数据时直接返回，后台悄悄重建，不阻塞查询
        if (!options?.forceRebuild && AssetDependencyIndex._indexData) {
            AssetDependencyIndex.triggerBackgroundRebuild();
            return AssetDependencyIndex._indexData;
        }

        // 首次构建或强制重建
        AssetDependencyIndex._buildPromise = AssetDependencyIndex.loadOrBuildIndex(options);
        try {
            const indexData = await AssetDependencyIndex._buildPromise;
            AssetDependencyIndex._indexData = indexData;
            AssetDependencyIndex._isDirty = false;
            return indexData;
        } finally {
            AssetDependencyIndex._buildPromise = null;
        }
    }

    public static markDirty(): void {
        AssetDependencyIndex._isDirty = true;
        // 保留内存索引供后续查询立即使用，后台会异步更新
    }

    public static async rebuild(options?: Omit<IEnsureIndexOptions, "forceRebuild">): Promise<IAssetDependencyIndexData> {
        return AssetDependencyIndex.ensureReady({
            ...options,
            forceRebuild: true
        });
    }

    public static getDependencyRecords(assetIds: ReadonlyArray<string>): IIndexedAssetRecord[] {
        const indexData = AssetDependencyIndex.requireIndex();
        const result = new Map<string, IIndexedAssetRecord>();
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
                    result.set(dependencyId, dependencyRecord as IIndexedAssetRecord);
                }
            }
        }

        return AssetDependencyIndex.sortRecords([...result.values()]);
    }

    public static getDependencyRecordsByLevel(
        assetIds: ReadonlyArray<string>,
        maxDepth: number = 20
    ): IIndexedAssetRecord[][] {
        const indexData = AssetDependencyIndex.requireIndex();
        const result: IIndexedAssetRecord[][] = [];
        const visitedIds = new Set<string>(assetIds);
        let currentLevelIds = [...assetIds];

        for (let depth = 0; depth < maxDepth && currentLevelIds.length > 0; depth++) {
            const levelMap = new Map<string, IIndexedAssetRecord>();

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
                        levelMap.set(depId, depRecord as IIndexedAssetRecord);
                    }
                }
            }

            if (levelMap.size === 0) {
                break;
            }

            const levelRecords = AssetDependencyIndex.sortRecords([...levelMap.values()]);
            result.push(levelRecords);

            currentLevelIds = [];
            for (const id of levelMap.keys()) {
                visitedIds.add(id);
                currentLevelIds.push(id);
            }
        }

        return result;
    }

    public static getReferenceRecordsByLevel(
        assetIds: ReadonlyArray<string>,
        maxDepth: number = 20
    ): IIndexedAssetRecord[][] {
        const indexData = AssetDependencyIndex.requireIndex();
        const result: IIndexedAssetRecord[][] = [];
        const visitedIds = new Set<string>(assetIds);
        let currentLevelIds = [...assetIds];

        for (let depth = 0; depth < maxDepth && currentLevelIds.length > 0; depth++) {
            const levelMap = new Map<string, IIndexedAssetRecord>();

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
                        levelMap.set(refId, refRecord as IIndexedAssetRecord);
                    }
                }
            }

            if (levelMap.size === 0) {
                break;
            }

            const levelRecords = AssetDependencyIndex.sortRecords([...levelMap.values()]);
            result.push(levelRecords);

            currentLevelIds = [];
            for (const id of levelMap.keys()) {
                visitedIds.add(id);
                currentLevelIds.push(id);
            }
        }

        return result;
    }

    public static getMissingReferences(assetId: string): readonly string[] {
        const indexData = AssetDependencyIndex.requireIndex();
        return indexData.missingRefsByAssetId.get(assetId) || [];
    }

    public static getFolderRecords(folderFile: string): IIndexedAssetRecord[] {
        const indexData = AssetDependencyIndex.requireIndex();
        let prefix = folderFile.length > 0 ? `${folderFile}/` : "";

        // 编辑器返回的 folder.file 是 assets 内的相对路径（如 "resources/play"）
        // 索引存储的是项目根相对路径（如 "assets/resources/play/xxx.png"）
        // 若前缀不以已知扫描目录开头，自动补全 "assets/"
        if (prefix.length > 0) {
            const hasKnownRoot = AssetDependencyIndex.SCAN_DIRS.some(
                (dir: string) => prefix.startsWith(`${dir}/`)
            );
            if (!hasKnownRoot) {
                prefix = `assets/${prefix}`;
            }
        }

        const result: IIndexedAssetRecord[] = [];

        for (const record of indexData.recordsByPrefix) {
            if (prefix.length === 0 || record.file.startsWith(prefix)) {
                result.push(record as IIndexedAssetRecord);
            }
        }

        return result;
    }

    public static hasReferences(assetId: string): boolean {
        const indexData = AssetDependencyIndex.requireIndex();
        return (indexData.reverseReferenceCountById.get(assetId) || 0) > 0;
    }

    public static createAssetInfo(record: Pick<IIndexedAssetRecord, "id" | "file" | "ext">): IEditor.IAssetInfo {
        const path = IEditor.require("path");
        const fileName = path.basename(record.file);
        const ext = record.ext || "";
        const name = ext.length > 0 && fileName.endsWith(`.${ext}`)
            ? fileName.substring(0, fileName.length - ext.length - 1)
            : fileName;

        return {
            id: record.id,
            name,
            fileName,
            file: record.file,
            ext,
            type: 0 as IEditor.AssetType,
            subType: "",
            ver: 0,
            parentId: "",
            hasChild: false,
            flags: 0,
            scriptType: 0 as IEditor.AssetScriptType,
            children: []
        } as IEditor.IAssetInfo;
    }

    private static triggerBackgroundRebuild(): void {
        if (AssetDependencyIndex._buildPromise || AssetDependencyIndex._backgroundBuildPromise) {
            return;
        }

        AssetDependencyIndex._backgroundBuildPromise = AssetDependencyIndex.loadOrBuildIndex()
            .then((indexData) => {
                AssetDependencyIndex._indexData = indexData;
                AssetDependencyIndex._isDirty = false;
                AssetDependencyIndex._backgroundBuildPromise = null;
            })
            .catch((error: unknown) => {
                console.warn("[AssetDependencyIndex] 后台重建索引失败:", error);
                AssetDependencyIndex._backgroundBuildPromise = null;
            });
    }

    private static ensureListeners(): void {
        if (AssetDependencyIndex._isListening) {
            return;
        }

        Editor.assetDb.onAssetChanged.add(AssetDependencyIndex.onAssetChanged, AssetDependencyIndex);
        Editor.assetDb.onPackagesChanged.add(AssetDependencyIndex.onPackagesChanged, AssetDependencyIndex);
        AssetDependencyIndex._isListening = true;
    }

    private static onAssetChanged(): void {
        AssetDependencyIndex.markDirty();
    }

    private static onPackagesChanged(): void {
        AssetDependencyIndex.markDirty();
    }

    private static requireIndex(): IAssetDependencyIndexData {
        if (!AssetDependencyIndex._indexData) {
            throw new Error("依赖索引尚未准备完成");
        }

        return AssetDependencyIndex._indexData;
    }

    private static async loadOrBuildIndex(options?: IEnsureIndexOptions): Promise<IAssetDependencyIndexData> {
        const snapshot = AssetDependencyIndex.scanProjectSnapshot();
        if (!options?.forceRebuild && !AssetDependencyIndex._isDirty) {
            const cachedData = AssetDependencyIndex.tryLoadCache(snapshot);
            if (cachedData) {
                options?.onProgress?.(snapshot.assetCount, snapshot.assetCount);
                return cachedData;
            }
        }

        const scanResult = AssetDependencyIndex.scanProjectAssets();
        return AssetDependencyIndex.buildIndex(scanResult, options?.onProgress);
    }

    private static tryLoadCache(snapshot: IAssetProjectSnapshot): IAssetDependencyIndexData | null {
        const fs = IEditor.require("fs");
        const cachePath = AssetDependencyIndex.getCacheFilePath();
        if (!fs.existsSync(cachePath)) {
            return null;
        }

        try {
            const content = fs.readFileSync(cachePath, "utf-8");
            const cache = JSON.parse(content) as IAssetDependencyIndexCache;
            if (!AssetDependencyIndex.isCacheValid(cache, snapshot)) {
                return null;
            }

            return AssetDependencyIndex.createIndexData(cache.records, cache.builtAt, cache.latestModifiedMs);
        } catch (error) {
            console.warn("[AssetDependencyIndex] 读取缓存失败，将重建索引:", error);
            return null;
        }
    }

    private static isCacheValid(cache: IAssetDependencyIndexCache, snapshot: IAssetProjectSnapshot): boolean {
        if (!cache || cache.version !== AssetDependencyIndex.CACHE_VERSION) {
            return false;
        }

        return cache.assetCount === snapshot.assetCount
            && cache.latestModifiedMs === snapshot.latestModifiedMs;
    }

    private static async buildIndex(
        scanResult: IAssetScanResult,
        onProgress?: (processedCount: number, totalCount: number) => void
    ): Promise<IAssetDependencyIndexData> {
        const records: IIndexedAssetRecord[] = scanResult.records.map((record: IAssetSourceRecord) => {
            return {
                id: record.id,
                file: record.file,
                ext: record.ext,
                dependencies: [] as string[],
                missingRefs: [] as string[]
            };
        });
        const totalCount = records.length;
        let processedCount = 0;

        // 先建立 shader 名字 → UUID 映射，用于补充材质的 shader 依赖
        const shaderNameMap = AssetDependencyIndex.buildShaderNameMap(records);

        onProgress?.(0, totalCount);
        await AssetDependencyIndex.runWithConcurrency(records, AssetDependencyIndex.QUERY_CONCURRENCY, async (record: IIndexedAssetRecord) => {
            const [dependencies, notFound] = await IEditor.AssetDependencyTool.queryDependency([record.id], false, true);
            record.dependencies = AssetDependencyIndex.extractDependencyIds(record.id, dependencies);
            record.missingRefs = AssetDependencyIndex.normalizeMissingReferences(notFound);

            // 材质文件补充 shader 依赖（材质以名字引用 shader，queryDependency 无法感知）
            if (record.ext === "lmat") {
                const shaderId = AssetDependencyIndex.extractMaterialShaderDepId(record, shaderNameMap);
                if (shaderId && record.dependencies.indexOf(shaderId) === -1) {
                    record.dependencies.push(shaderId);
                    record.dependencies.sort((a: string, b: string) => a.localeCompare(b));
                }
            }

            processedCount++;
            onProgress?.(processedCount, totalCount);
        });

        const builtAt = Date.now();
        AssetDependencyIndex.writeCache({
            version: AssetDependencyIndex.CACHE_VERSION,
            builtAt,
            assetCount: totalCount,
            latestModifiedMs: scanResult.latestModifiedMs,
            records
        });

        return AssetDependencyIndex.createIndexData(records, builtAt, scanResult.latestModifiedMs);
    }

    private static buildShaderNameMap(records: ReadonlyArray<IIndexedAssetRecord>): Map<string, string> {
        const map = new Map<string, string>();
        for (const record of records) {
            if (record.ext !== "shader") {
                continue;
            }

            const shaderName = AssetDependencyIndex.extractShaderName(record);
            if (shaderName) {
                map.set(shaderName, record.id);
            }
        }
        return map;
    }

    private static extractShaderName(record: IIndexedAssetRecord): string | null {
        const fs = IEditor.require("fs");
        const path = IEditor.require("path");
        const filePath = path.join(AssetDependencyIndex.getProjectRootPath(), record.file);

        try {
            const content = fs.readFileSync(filePath, "utf-8") as string;
            // shader 文件格式: name: "Custom/ShaderName" 或 name:"Custom/ShaderName"
            const match = content.match(/\bname\s*:\s*"([^"]+)"/);
            return match ? match[1] : null;
        } catch {
            return null;
        }
    }

    private static extractMaterialShaderDepId(
        record: IIndexedAssetRecord,
        shaderNameMap: ReadonlyMap<string, string>
    ): string | null {
        const fs = IEditor.require("fs");
        const path = IEditor.require("path");
        const filePath = path.join(AssetDependencyIndex.getProjectRootPath(), record.file);

        try {
            const content = fs.readFileSync(filePath, "utf-8");
            const json = JSON.parse(content) as { props?: { type?: string } };
            const shaderName = json?.props?.type;
            if (!shaderName) {
                return null;
            }
            return shaderNameMap.get(shaderName) || null;
        } catch {
            return null;
        }
    }

    private static createIndexData(
        records: ReadonlyArray<IIndexedAssetRecord>,
        builtAt: number,
        latestModifiedMs: number
    ): IAssetDependencyIndexData {
        const recordsById = new Map<string, IIndexedAssetRecord>();
        const missingRefsByAssetId = new Map<string, readonly string[]>();
        const reverseReferenceCountById = new Map<string, number>();
        const reverseReferencesById = new Map<string, string[]>();
        const sortedRecords = AssetDependencyIndex.sortRecords([...records]);

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

    private static extractDependencyIds(
        sourceAssetId: string,
        dependencies: ReadonlyArray<IEditor.IAssetInfo>
    ): string[] {
        const result: string[] = [];
        const visitedIds = new Set<string>();

        for (const dependency of dependencies) {
            if (!dependency?.id || dependency.id === sourceAssetId || visitedIds.has(dependency.id)) {
                continue;
            }

            visitedIds.add(dependency.id);
            result.push(dependency.id);
        }

        result.sort((left: string, right: string) => left.localeCompare(right));
        return result;
    }

    private static normalizeMissingReferences(missingRefs: ReadonlyArray<string>): string[] {
        const normalizedRefs = [...new Set(
            missingRefs
                .map((missingRef: string) => missingRef.trim())
                .filter((missingRef: string) => missingRef.length > 0)
        )];
        normalizedRefs.sort((left: string, right: string) => left.localeCompare(right));
        return normalizedRefs;
    }

    private static writeCache(cache: IAssetDependencyIndexCache): void {
        const fs = IEditor.require("fs");
        const path = IEditor.require("path");
        const cachePath = AssetDependencyIndex.getCacheFilePath();
        fs.mkdirSync(path.dirname(cachePath), { recursive: true });
        fs.writeFileSync(cachePath, JSON.stringify(cache), "utf-8");
    }

    private static getCacheFilePath(): string {
        const path = IEditor.require("path");
        return path.join(Editor.projectPath, AssetDependencyIndex.CACHE_RELATIVE_PATH);
    }

    private static scanProjectAssets(): IAssetScanResult {
        const path = IEditor.require("path");
        const projectRoot = AssetDependencyIndex.getProjectRootPath();
        const records: IAssetSourceRecord[] = [];
        let latestModifiedMs = 0;

        for (const dir of AssetDependencyIndex.SCAN_DIRS) {
            AssetDependencyIndex.scanDirectory(path.join(projectRoot, dir), records, (mtimeMs: number) => {
                if (mtimeMs > latestModifiedMs) {
                    latestModifiedMs = mtimeMs;
                }
            });
        }

        records.sort((left: IAssetSourceRecord, right: IAssetSourceRecord) => left.file.localeCompare(right.file));

        return {
            assetCount: records.length,
            latestModifiedMs,
            records
        };
    }

    private static scanProjectSnapshot(): IAssetProjectSnapshot {
        const path = IEditor.require("path");
        const fs = IEditor.require("fs");
        const projectRoot = AssetDependencyIndex.getProjectRootPath();

        let assetCount = 0;
        let latestModifiedMs = 0;

        for (const dir of AssetDependencyIndex.SCAN_DIRS) {
            const dirPath = path.join(projectRoot, dir);
            if (!fs.existsSync(dirPath)) {
                continue;
            }

            AssetDependencyIndex.scanDirectoryFast(dirPath, (mtimeMs: number) => {
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

    private static scanDirectory(
        dirPath: string,
        out: IAssetSourceRecord[],
        onModified: (mtimeMs: number) => void
    ): void {
        const fs = IEditor.require("fs");
        const path = IEditor.require("path");
        let entries: any[] = [];

        try {
            entries = fs.readdirSync(dirPath, { withFileTypes: true });
        } catch {
            return;
        }

        for (const entry of entries) {
            const fullPath = path.join(dirPath, entry.name);
            if (entry.isDirectory()) {
                try {
                    const stat = fs.statSync(fullPath);
                    onModified(stat.mtimeMs);
                } catch {
                    // ignore
                }
                AssetDependencyIndex.scanDirectory(fullPath, out, onModified);
                continue;
            }

            if (!entry.isFile() || entry.name.endsWith(AssetDependencyIndex.META_EXT)) {
                continue;
            }

            const relativeFile = AssetDependencyIndex.toAssetRelativePath(fullPath);
            const metaPath = `${fullPath}${AssetDependencyIndex.META_EXT}`;
            if (!relativeFile || !fs.existsSync(metaPath)) {
                continue;
            }

            try {
                const fileStat = fs.statSync(fullPath);
                const metaStat = fs.statSync(metaPath);
                onModified(fileStat.mtimeMs);
                onModified(metaStat.mtimeMs);
            } catch {
                // ignore
            }

            const meta = AssetDependencyIndex.readJsonFile<{ uuid?: string }>(metaPath);
            if (!meta?.uuid) {
                continue;
            }

            out.push({
                id: meta.uuid,
                file: relativeFile,
                ext: path.extname(relativeFile).replace(/^\./, "")
            });
        }
    }

    private static scanDirectoryFast(
        dirPath: string,
        onModified: (mtimeMs: number) => void,
        onAsset: () => void
    ): void {
        const fs = IEditor.require("fs");
        const path = IEditor.require("path");
        let entries: any[] = [];

        try {
            entries = fs.readdirSync(dirPath, { withFileTypes: true });
        } catch {
            return;
        }

        for (const entry of entries) {
            const fullPath = path.join(dirPath, entry.name);
            if (entry.isDirectory()) {
                try {
                    const stat = fs.statSync(fullPath);
                    onModified(stat.mtimeMs);
                } catch {
                    // ignore
                }
                AssetDependencyIndex.scanDirectoryFast(fullPath, onModified, onAsset);
                continue;
            }

            if (!entry.isFile() || entry.name.endsWith(AssetDependencyIndex.META_EXT)) {
                continue;
            }

            const metaPath = `${fullPath}${AssetDependencyIndex.META_EXT}`;
            if (!fs.existsSync(metaPath)) {
                continue;
            }

            try {
                const fileStat = fs.statSync(fullPath);
                const metaStat = fs.statSync(metaPath);
                onModified(fileStat.mtimeMs);
                onModified(metaStat.mtimeMs);
            } catch {
                // ignore
            }

            onAsset();
        }
    }

    private static toAssetRelativePath(fullPath: string): string {
        const path = IEditor.require("path");
        const projectRoot = AssetDependencyIndex.getProjectRootPath();
        const relativePath = path.relative(projectRoot, fullPath);
        if (!relativePath || relativePath.startsWith("..")) {
            return "";
        }

        return relativePath.split(path.sep).join("/");
    }

    private static getProjectRootPath(): string {
        return Editor.projectPath;
    }

    private static readJsonFile<T>(filePath: string): T | null {
        const fs = IEditor.require("fs");
        if (!fs.existsSync(filePath)) {
            return null;
        }

        try {
            return JSON.parse(fs.readFileSync(filePath, "utf-8")) as T;
        } catch {
            return null;
        }
    }

    private static sortRecords(records: IIndexedAssetRecord[]): IIndexedAssetRecord[] {
        records.sort((left: IIndexedAssetRecord, right: IIndexedAssetRecord) => left.file.localeCompare(right.file));
        return records;
    }

    private static async runWithConcurrency<T>(
        items: ReadonlyArray<T>,
        concurrency: number,
        worker: (item: T, index: number) => Promise<void>
    ): Promise<void> {
        if (items.length === 0) {
            return;
        }

        let nextIndex = 0;
        const workerCount = Math.max(1, Math.min(concurrency, items.length));
        const runners: Promise<void>[] = [];

        const runNext = async (): Promise<void> => {
            while (nextIndex < items.length) {
                const currentIndex = nextIndex;
                nextIndex++;
                await worker(items[currentIndex], currentIndex);
            }
        };

        for (let i = 0; i < workerCount; i++) {
            runners.push(runNext());
        }

        await Promise.all(runners);
    }
}
