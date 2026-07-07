import {
    AssetSearchMode,
    AssetSearchResultPanel,
    AssetSearchStatusLevel,
    IAssetSearchPanelData,
    IAssetSearchRowData
} from "./AssetSearchResultPanel";
import { AssetDependencyIndex } from "./AssetDependencyIndex";

/**
 * 项目资源查找工具
 */
export class FindDependencies {
    private static readonly FILE_MENU_POSITION: string = "before findReferencesInScene";
    private static readonly FOLDER_MENU_POSITION: string = "before findReferencesInScene";
    private static readonly INDEX_BUILD_PREFIX: string = "正在构建依赖索引...";

    @IEditor.onLoad
    public static onLoad(): void {
        Editor.extensionManager.addMenuItem("Project/查找引用", () => {
            FindDependencies.findReferences();
        }, {
            visibleTest: () => FindDependencies.hasSelectedFilesOnly(),
            position: FindDependencies.FILE_MENU_POSITION
        } as IEditor.ICustomMenuItemOptions);

        Editor.extensionManager.addMenuItem("Project/查找依赖", () => {
            FindDependencies.findDependencies();
        }, {
            visibleTest: () => FindDependencies.hasSelectedFilesOnly(),
            position: FindDependencies.FILE_MENU_POSITION
        } as IEditor.ICustomMenuItemOptions);

        Editor.extensionManager.addMenuItem("Project/查找无用的资源", () => {
            FindDependencies.findByFolder("unused");
        }, {
            visibleTest: () => FindDependencies.isFolderSelected(),
            position: FindDependencies.FOLDER_MENU_POSITION
        } as IEditor.ICustomMenuItemOptions);

        Editor.extensionManager.addMenuItem("Project/查找在用的资源", () => {
            FindDependencies.findByFolder("used");
        }, {
            visibleTest: () => FindDependencies.isFolderSelected(),
            position: FindDependencies.FOLDER_MENU_POSITION
        } as IEditor.ICustomMenuItemOptions);
    }

    private static getSelectedResources(): IEditor.IAssetInfo[] {
        const projectPanel = Editor.panelManager.getPanel("ProjectPanel") as IEditor.IProjectPanel;
        if (!projectPanel) {
            return [];
        }

        const assets = projectPanel.getSelectedResources([]);
        const filteredAssets = assets.filter((asset: IEditor.IAssetInfo | null | undefined) => !!asset?.id);
        if (filteredAssets.length > 0) {
            return filteredAssets;
        }

        const asset = projectPanel.getSelectedResource();
        return asset?.id ? [asset] : [];
    }

    private static getSelectedSearchFileAssets(): IEditor.IAssetInfo[] {
        const assets = FindDependencies.getSelectedResources();
        return assets.length > 0 && assets.every((asset: IEditor.IAssetInfo) => !!asset.ext)
            ? assets
            : [];
    }

    private static getSelectedFolderAsset(): IEditor.IAssetInfo | null {
        const assets = FindDependencies.getSelectedResources();
        return assets.length === 1 && !assets[0].ext
            ? assets[0]
            : null;
    }

    private static hasSelectedFilesOnly(): boolean {
        return FindDependencies.getSelectedSearchFileAssets().length > 0;
    }

    private static isFolderSelected(): boolean {
        return !!FindDependencies.getSelectedFolderAsset();
    }

    private static async findReferences(): Promise<void> {
        const sourceAssets = FindDependencies.getSelectedSearchFileAssets();
        if (sourceAssets.length === 0) {
            return;
        }

        await FindDependencies.runFindReferences(sourceAssets);
    }

    private static async runFindReferences(
        sourceAssets: ReadonlyArray<IEditor.IAssetInfo>
    ): Promise<void> {
        try {
            AssetSearchResultPanel.showState(FindDependencies.createPanelData("reference", sourceAssets, [], {
                statusText: FindDependencies.getIndexBuildStatusText(0, 0),
                statusLevel: "info",
                isLoading: true,
                processedCount: 0,
                totalCount: 0
            }));

            await AssetDependencyIndex.ensureReady({
                onProgress: (processedCount: number, totalCount: number) => {
                    AssetSearchResultPanel.showState(FindDependencies.createPanelData("reference", sourceAssets, [], {
                        statusText: FindDependencies.getIndexBuildStatusText(processedCount, totalCount),
                        statusLevel: "info",
                        isLoading: true,
                        processedCount,
                        totalCount
                    }));
                }
            });

            const leveledRecords = AssetDependencyIndex.getReferenceRecordsByLevel(
                sourceAssets.map((asset: IEditor.IAssetInfo) => asset.id)
            );
            const leveledAssets = leveledRecords.map(
                (records) => records.map((record) => AssetDependencyIndex.createAssetInfo(record))
            );
            const rows = FindDependencies.buildLeveledRows([], leveledAssets, "引用");
            const status = FindDependencies.getReferenceCompletedStatus(rows);
            FindDependencies.showCompleted("reference", sourceAssets, rows, {
                processedCount: sourceAssets.length,
                totalCount: sourceAssets.length,
                statusText: status.text,
                statusLevel: status.level
            });
        } catch (error: unknown) {
            FindDependencies.showError("reference", sourceAssets, error);
            console.error("[FindDependencies] 查找引用失败:", error);
        }
    }

    private static async findDependencies(): Promise<void> {
        const sourceAssets = FindDependencies.getSelectedSearchFileAssets();
        if (sourceAssets.length === 0) {
            return;
        }

        await FindDependencies.runFindDependencies(sourceAssets);
    }

    private static async runFindDependencies(
        sourceAssets: ReadonlyArray<IEditor.IAssetInfo>
    ): Promise<void> {
        const issueRows: IAssetSearchRowData[] = [];

        try {
            AssetSearchResultPanel.showState(FindDependencies.createPanelData("dependency", sourceAssets, [], {
                statusText: FindDependencies.getIndexBuildStatusText(0, 0),
                statusLevel: "info",
                isLoading: true,
                processedCount: 0,
                totalCount: 0
            }));

            await AssetDependencyIndex.ensureReady({
                onProgress: (processedCount: number, totalCount: number) => {
                    AssetSearchResultPanel.showState(FindDependencies.createPanelData("dependency", sourceAssets, [], {
                        statusText: FindDependencies.getIndexBuildStatusText(processedCount, totalCount),
                        statusLevel: "info",
                        isLoading: true,
                        processedCount,
                        totalCount
                    }));
                }
            });

            for (const asset of sourceAssets) {
                const missingRefs = AssetDependencyIndex.getMissingReferences(asset.id);
                if (missingRefs.length > 0) {
                    issueRows.push(...FindDependencies.createMissingReferenceRows(asset, missingRefs));
                }
            }

            const leveledRecords = AssetDependencyIndex.getDependencyRecordsByLevel(
                sourceAssets.map((asset: IEditor.IAssetInfo) => asset.id)
            );

            // 收集各级依赖资源自身的无效引用（依赖的依赖也可能有缺失 UUID）
            for (const levelRecords of leveledRecords) {
                for (const record of levelRecords) {
                    const missingRefs = AssetDependencyIndex.getMissingReferences(record.id);
                    if (missingRefs.length > 0) {
                        issueRows.push(...FindDependencies.createMissingReferenceRows(
                            AssetDependencyIndex.createAssetInfo(record),
                            missingRefs
                        ));
                    }
                }
            }

            const leveledAssets = leveledRecords.map(
                (records) => records.map((record) => AssetDependencyIndex.createAssetInfo(record))
            );
            const rows = FindDependencies.buildLeveledRows(issueRows, leveledAssets, "依赖");
            const status = FindDependencies.getDependencyCompletedStatus(rows, issueRows.length);
            FindDependencies.showCompleted("dependency", sourceAssets, rows, {
                processedCount: sourceAssets.length,
                totalCount: sourceAssets.length,
                statusText: status.text,
                statusLevel: status.level
            });
        } catch (error: unknown) {
            const rows = FindDependencies.buildLeveledRows(issueRows, [], "依赖");
            FindDependencies.showError(
                "dependency",
                sourceAssets,
                error,
                rows,
                0,
                sourceAssets.length
            );
            console.error("[FindDependencies] 查找依赖失败:", error);
        }
    }

    private static async findByFolder(mode: "unused" | "used"): Promise<void> {
        const folder = FindDependencies.getSelectedFolderAsset();
        if (!folder?.id) {
            return;
        }

        await FindDependencies.runFindByFolder(folder, mode);
    }

    private static async runFindByFolder(
        folder: IEditor.IAssetInfo,
        mode: "unused" | "used"
    ): Promise<void> {
        try {
            AssetSearchResultPanel.showState(FindDependencies.createPanelData(mode, [folder], [], {
                statusText: FindDependencies.getIndexBuildStatusText(0, 0),
                statusLevel: "info",
                isLoading: true,
                processedCount: 0,
                totalCount: 0
            }));

            await AssetDependencyIndex.ensureReady({
                onProgress: (processedCount: number, totalCount: number) => {
                    AssetSearchResultPanel.showState(FindDependencies.createPanelData(mode, [folder], [], {
                        statusText: FindDependencies.getIndexBuildStatusText(processedCount, totalCount),
                        statusLevel: "info",
                        isLoading: true,
                        processedCount,
                        totalCount
                    }));
                }
            });

            const resources = AssetDependencyIndex.getFolderRecords(folder.file);
            const resultAssets = resources
                .filter((asset) => {
                    const used = AssetDependencyIndex.hasReferences(asset.id);
                    return (mode === "used" && used) || (mode === "unused" && !used);
                })
                .map((record) => AssetDependencyIndex.createAssetInfo(record));

            FindDependencies.showCompleted(
                mode,
                [folder],
                FindDependencies.createAssetRows(resultAssets),
                {
                    processedCount: resources.length,
                    totalCount: resources.length
                }
            );
        } catch (error: unknown) {
            FindDependencies.showError(
                mode,
                [folder],
                error,
                [],
                0,
                0
            );
            console.error(`[FindDependencies] ${FindDependencies.getPanelTitle(mode)}失败:`, error);
        }
    }

    private static showCompleted(
        mode: AssetSearchMode,
        sources: ReadonlyArray<IEditor.IAssetInfo>,
        rows: ReadonlyArray<IAssetSearchRowData>,
        options?: {
            processedCount?: number;
            totalCount?: number;
            statusText?: string;
            statusLevel?: AssetSearchStatusLevel;
        }
    ): void {
        const resultCount = rows.filter((row: IAssetSearchRowData) => row.kind !== "separator").length;
        AssetSearchResultPanel.showState(FindDependencies.createPanelData(mode, sources, rows, {
            statusText: options?.statusText || (
                resultCount > 0
                    ? `查找完成，找到 ${resultCount} 个结果`
                    : FindDependencies.getEmptyStatusText(mode)
            ),
            statusLevel: options?.statusLevel || (resultCount > 0 ? "success" : "warning"),
            isLoading: false,
            processedCount: options?.processedCount ?? options?.totalCount ?? 0,
            totalCount: options?.totalCount ?? 0
        }));
    }

    private static showError(
        mode: AssetSearchMode,
        sources: ReadonlyArray<IEditor.IAssetInfo>,
        error: unknown,
        rows: ReadonlyArray<IAssetSearchRowData> = [],
        processedCount: number = 0,
        totalCount: number = 0
    ): void {
        AssetSearchResultPanel.showState(FindDependencies.createPanelData(mode, sources, rows, {
            statusText: `查找失败：${FindDependencies.getErrorMessage(error)}`,
            statusLevel: "error",
            isLoading: false,
            processedCount,
            totalCount
        }));
    }

    private static createPanelData(
        mode: AssetSearchMode,
        sources: ReadonlyArray<IEditor.IAssetInfo>,
        rows: ReadonlyArray<IAssetSearchRowData>,
        options: {
            statusText: string;
            statusLevel: AssetSearchStatusLevel;
            isLoading: boolean;
            processedCount?: number;
            totalCount?: number;
        }
    ): IAssetSearchPanelData {
        return {
            mode,
            title: FindDependencies.getPanelTitle(mode),
            sources: [...sources],
            statusText: options.statusText,
            statusLevel: options.statusLevel,
            isLoading: options.isLoading,
            processedCount: options.processedCount ?? 0,
            totalCount: options.totalCount ?? 0,
            resultCount: rows.filter((row: IAssetSearchRowData) => row.kind !== "separator").length,
            emptyText: FindDependencies.getEmptyStatusText(mode),
            rows: [...rows]
        };
    }

    private static buildLeveledRows(
        issueRows: ReadonlyArray<IAssetSearchRowData>,
        leveledAssets: ReadonlyArray<ReadonlyArray<IEditor.IAssetInfo>>,
        levelLabel: string
    ): IAssetSearchRowData[] {
        const rows: IAssetSearchRowData[] = [...FindDependencies.sortIssueRows(issueRows)];

        for (let i = 0; i < leveledAssets.length; i++) {
            rows.push(FindDependencies.createLevelSeparatorRow(i + 1, levelLabel));
            rows.push(...FindDependencies.createAssetRows(leveledAssets[i]));
        }

        return rows;
    }

    private static createLevelSeparatorRow(level: number, label: string): IAssetSearchRowData {
        return {
            key: `separator:level:${level}`,
            kind: "separator",
            asset: null,
            title: `── 第 ${level} 级${label} ──`,
            tooltips: "",
            clickable: false
        };
    }

    private static createAssetRows(assets: ReadonlyArray<IEditor.IAssetInfo>): IAssetSearchRowData[] {
        const sortedAssets = [...assets];
        FindDependencies.sortAssets(sortedAssets);

        return sortedAssets.map((asset: IEditor.IAssetInfo) => FindDependencies.createAssetRow(asset));
    }

    private static createMissingReferenceRows(
        asset: IEditor.IAssetInfo,
        missingRefs: ReadonlyArray<string>
    ): IAssetSearchRowData[] {
        return FindDependencies.normalizeMissingReferences(missingRefs).map((missingRef: string) => {
            return FindDependencies.createMissingReferenceRow(asset, missingRef);
        });
    }

    private static sortIssueRows(rows: ReadonlyArray<IAssetSearchRowData>): IAssetSearchRowData[] {
        return [...rows].sort((left: IAssetSearchRowData, right: IAssetSearchRowData) => {
            const titleCompare = left.title.localeCompare(right.title);
            if (titleCompare !== 0) {
                return titleCompare;
            }

            const leftFile = left.asset?.file || "";
            const rightFile = right.asset?.file || "";
            return leftFile.localeCompare(rightFile);
        });
    }

    private static getDependencyCompletedStatus(
        rows: ReadonlyArray<IAssetSearchRowData>,
        issueCount: number
    ): { text: string; level: AssetSearchStatusLevel } {
        const depCount = rows.filter((row: IAssetSearchRowData) => row.kind === "asset").length;
        const levelCount = rows.filter((row: IAssetSearchRowData) => row.kind === "separator").length;

        if (depCount === 0 && issueCount === 0) {
            return {
                text: FindDependencies.getEmptyStatusText("dependency"),
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

    private static getReferenceCompletedStatus(
        rows: ReadonlyArray<IAssetSearchRowData>
    ): { text: string; level: AssetSearchStatusLevel } {
        const refCount = rows.filter((row: IAssetSearchRowData) => row.kind === "asset").length;
        const levelCount = rows.filter((row: IAssetSearchRowData) => row.kind === "separator").length;

        if (refCount === 0) {
            return {
                text: FindDependencies.getEmptyStatusText("reference"),
                level: "warning"
            };
        }

        let text = `查找完成，找到 ${refCount} 个引用`;
        if (levelCount > 1) {
            text += `（${levelCount} 级）`;
        }

        return { text, level: "success" };
    }

    private static getIndexBuildStatusText(processedCount: number, totalCount: number): string {
        if (totalCount <= 0) {
            return FindDependencies.INDEX_BUILD_PREFIX;
        }

        return `${FindDependencies.INDEX_BUILD_PREFIX} ${processedCount}/${totalCount}`;
    }

    private static getPanelTitle(mode: AssetSearchMode): string {
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

    private static getEmptyStatusText(mode: AssetSearchMode): string {
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

    private static getErrorMessage(error: unknown): string {
        if (error instanceof Error && error.message) {
            return error.message;
        }

        return String(error);
    }

    private static sortAssets(assets: IEditor.IAssetInfo[]): void {
        assets.sort((left: IEditor.IAssetInfo, right: IEditor.IAssetInfo) => {
            return left.file.localeCompare(right.file);
        });
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

    private static createAssetRow(asset: IEditor.IAssetInfo): IAssetSearchRowData {
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

    private static createMissingReferenceRow(
        asset: IEditor.IAssetInfo,
        missingRef: string
    ): IAssetSearchRowData {
        return {
            key: `issue:${asset.id}:${missingRef}`,
            kind: "issue",
            asset,
            title: `[无效/丢失UUID] ${missingRef}`,
            tooltips: `缺失项：${missingRef}\n来源文件：${asset.file}\n点击可复制 UUID`,
            clickable: true,
            copyText: missingRef,
            icon: Editor.assetDb.getAssetIcon(asset)
        };
    }
}
