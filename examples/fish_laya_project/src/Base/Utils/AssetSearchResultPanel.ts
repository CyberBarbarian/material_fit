import { AssetDependencyIndex } from "./AssetDependencyIndex";

export type AssetSearchMode = "reference" | "dependency" | "unused" | "used";
export type AssetSearchStatusLevel = "info" | "success" | "warning" | "error";
export type AssetSearchRowKind = "asset" | "issue" | "separator";

export interface IAssetSearchRowData {
    key: string;
    kind: AssetSearchRowKind;
    asset: IEditor.IAssetInfo | null;
    title: string;
    tooltips: string;
    clickable: boolean;
    copyText?: string;
    icon?: string;
}

export interface IAssetSearchPanelData {
    mode: AssetSearchMode;
    title: string;
    sources: IEditor.IAssetInfo[];
    statusText: string;
    statusLevel: AssetSearchStatusLevel;
    isLoading: boolean;
    processedCount: number;
    totalCount: number;
    resultCount: number;
    emptyText: string;
    rows: IAssetSearchRowData[];
}

@IEditor.panel("AssetSearchResultPanel", {
    title: "资源查找结果",
    location: "popup",
    allowTabs: true,
    showInMenu: false,
    stretchPriorityX: 1,
    stretchPriorityY: 1
})
export class AssetSearchResultPanel extends IEditor.EditorPanel {
    public static readonly PANEL_ID: string = "AssetSearchResultPanel";
    private static readonly PANEL_TITLE_PREFIX: string = "资源查找结果 - ";
    private static readonly FONT_SIZE: number = 12;
    private static readonly PANEL_WIDTH: number = 720;
    private static readonly PANEL_HEIGHT: number = 520;
    private static readonly PADDING: number = 8;
    private static readonly ROW_GAP: number = 4;
    private static readonly TITLE_HEIGHT: number = 22;
    private static readonly INFO_HEIGHT: number = 18;
    private static readonly ITEM_HEIGHT: number = 24;
    private static readonly LIST_ROW_GAP: number = 2;
    private static readonly MIN_LIST_HEIGHT: number = 96;
    private static readonly MAX_VISIBLE_SOURCE_ITEMS: number = 3;
    private static readonly ISSUE_ICON_SIZE: number = 14;
    private static readonly ISSUE_ICON_GAP: number = 4;
    private static readonly ACTION_BUTTON_WIDTH: number = 92;
    private static readonly ACTION_BUTTON_HEIGHT: number = 28;
    private static readonly ACTION_ROW_HEIGHT: number = 28;
    private static readonly ACTION_BUTTON_TEXT: string = "重建索引";
    private static readonly ACTION_BUTTON_LOADING_TEXT: string = "重建中...";
    private static readonly ACTION_STATUS_TEXT: string = "正在重建依赖索引...";
    private static readonly ACTION_CONFIRM_TEXT: string = "重建依赖索引可能耗时较长，是否继续？";

    private static _pendingData: IAssetSearchPanelData | null = null;

    private _root: gui.Box;
    private _titleText: gui.TextField;
    private _sourceHeaderText: gui.TextField;
    private _sourceList: gui.List;
    private _statusText: gui.TextField;
    private _actionButton: gui.Button;
    private _summaryText: gui.TextField;
    private _resultList: gui.List;
    private _state: IAssetSearchPanelData | null = null;
    private _renderedSourceIds: string[] = [];
    private _renderedRowKeys: string[] = [];
    private _renderedPlaceholderText: string = "";
    private _isRebuildingIndex: boolean = false;

    public static showState(data: IAssetSearchPanelData): void {
        AssetSearchResultPanel._pendingData = AssetSearchResultPanel.cloneData(data);
        Editor.panelManager.showPanel(AssetSearchResultPanel.PANEL_ID);

        const panel = Editor.panelManager.getPanel(
            AssetSearchResultPanel.PANEL_ID,
            AssetSearchResultPanel
        );
        panel?.applyPendingState();
    }

    private static cloneData(data: IAssetSearchPanelData): IAssetSearchPanelData {
        return {
            ...data,
            sources: [...data.sources],
            rows: [...data.rows]
        };
    }

    private static createFallbackState(): IAssetSearchPanelData {
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

    public async create(): Promise<void> {
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
    }

    public onDestroy(): void {
        this._root?.offAllCaller(this);
        this._sourceList?.offAllCaller(this);
        this._resultList?.offAllCaller(this);
    }

    public setState(data: IAssetSearchPanelData): void {
        this._state = AssetSearchResultPanel.cloneData(data);
        if (!this._panel) {
            return;
        }

        this.renderState();
    }

    private applyPendingState(): void {
        if (AssetSearchResultPanel._pendingData) {
            this.setState(AssetSearchResultPanel._pendingData);
        }
    }

    private renderState(): void {
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

    private renderSourceList(sources: ReadonlyArray<IEditor.IAssetInfo>): void {
        const sourceIds = sources.map((asset: IEditor.IAssetInfo) => asset.id);
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

    private renderResultList(state: IAssetSearchPanelData): void {
        const placeholderText = this.getPlaceholderText(state);
        const rowKeys = state.rows.map((row: IAssetSearchRowData) => row.key);
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

    private shouldRefreshRows(rowKeys: ReadonlyArray<string>, placeholderText: string): boolean {
        if (rowKeys.length === 0) {
            return this._renderedRowKeys.length !== 0 || this._renderedPlaceholderText !== placeholderText;
        }

        return this.isStringListChanged(this._renderedRowKeys, rowKeys);
    }

    private clearList(list: gui.List): void {
        if (list.numChildren > 0) {
            list.removeChildren(0, list.numChildren - 1, true);
        }
    }

    private createRowItem(row: IAssetSearchRowData): IEditor.ListItem {
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

        if (row.clickable && row.asset?.id) {
            item.on("click", this.onResultItemClick, this);
        } else {
            item.touchable = false;
        }

        return item;
    }

    private createSeparatorItem(row: IAssetSearchRowData): IEditor.ListItem {
        const item = IEditor.GUIUtils.createListItem();
        item.setSize(this._resultList.width, AssetSearchResultPanel.ITEM_HEIGHT);
        item.title = row.title;
        item.titleFontSize = AssetSearchResultPanel.FONT_SIZE;
        item.grayed = true;
        item.touchable = false;
        return item;
    }

    private createIssueRowItem(row: IAssetSearchRowData): IEditor.ListItem {
        const item = new gui.Box() as unknown as IEditor.ListItem;
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

    private createAssetItem(title: string, tooltips: string, asset: IEditor.IAssetInfo): IEditor.ListItem {
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

    private createStaticItem(text: string): IEditor.ListItem {
        const item = IEditor.GUIUtils.createListItem();
        item.setSize(this._resultList.width, AssetSearchResultPanel.ITEM_HEIGHT);
        item.title = text;
        item.titleFontSize = AssetSearchResultPanel.FONT_SIZE;
        item.grayed = true;
        item.touchable = false;
        return item;
    }

    private onRootSizeChanged(): void {
        this.refreshLayout();
    }

    private onSourceItemClick(evt: gui.Event): void {
        const item = evt.sender as IEditor.ListItem;
        const asset = item?.data as IEditor.IAssetInfo;
        if (!asset?.id) {
            return;
        }

        this.locateAsset(asset);
    }

    private onResultItemClick(evt: gui.Event): void {
        const item = evt.sender as IEditor.ListItem;
        const row = item?.data as IAssetSearchRowData;
        if (!row?.clickable) {
            return;
        }

        if (row.copyText) {
            this.copyToClipboard(row.copyText);
            return;
        }

        if (!row.asset?.id) {
            return;
        }

        this.locateAsset(row.asset);
    }

    private async onActionButtonClick(): Promise<void> {
        if (this._isRebuildingIndex) {
            return;
        }

        const confirmed = await Editor.confirm(AssetSearchResultPanel.ACTION_CONFIRM_TEXT);
        if (!confirmed) {
            return;
        }

        await this.rebuildDependencyIndex();
    }

    private locateAsset(asset: IEditor.IAssetInfo): void {
        const projectPanel = Editor.panelManager.getPanel("ProjectPanel") as IEditor.IProjectPanel;
        if (!projectPanel) {
            return;
        }

        Editor.panelManager.showPanel("ProjectPanel");
        projectPanel.select(asset.id, true);
    }

    private copyToClipboard(text: string): void {
        try {
            Editor.clipboard.writeText(text);
        } catch (error: unknown) {
            void Editor.alert(`复制失败：${this.getErrorMessage(error)}`, "error");
            console.error("[AssetSearchResultPanel] 复制文本失败:", error);
        }
    }

    private createTextField(height: number, color?: number, bold: boolean = false): gui.TextField {
        const text = new gui.TextField();
        text.setSize(0, height);
        text.style.fontSize = AssetSearchResultPanel.FONT_SIZE;
        text.style.bold = bold;
        if (color != null) {
            text.color = color;
        }
        return text;
    }

    private createList(initialHeight: number): gui.List {
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

    private canActivateRow(row: IAssetSearchRowData): boolean {
        return row.clickable && (!!row.copyText || !!row.asset?.id);
    }

    private getAssetIcon(asset: IEditor.IAssetInfo | null): string {
        if (!asset) {
            return "";
        }

        return Editor.assetDb.getAssetIcon(asset);
    }

    private getSourceHeaderText(sourceCount: number): string {
        return sourceCount > 1
            ? `目标（${sourceCount}）：`
            : "目标：";
    }

    private getSummaryText(state: IAssetSearchPanelData): string {
        const progressText = state.totalCount > 0
            ? ` | 已处理：${state.processedCount}/${state.totalCount}`
            : "";
        return `结果：${state.resultCount} 项${progressText}`;
    }

    private renderActionButton(): void {
        this._actionButton.visible = true;
        this._actionButton.title = this._isRebuildingIndex
            ? AssetSearchResultPanel.ACTION_BUTTON_LOADING_TEXT
            : AssetSearchResultPanel.ACTION_BUTTON_TEXT;
        this._actionButton.touchable = !this._isRebuildingIndex;
        this._actionButton.grayed = this._isRebuildingIndex;
    }

    private getPlaceholderText(state: IAssetSearchPanelData): string {
        if (state.isLoading) {
            return state.statusText;
        }

        if (state.statusLevel === "error") {
            return state.statusText;
        }

        return state.emptyText;
    }

    private getSourceListHeight(sourceCount: number): number {
        const visibleSourceCount = Math.min(
            Math.max(1, sourceCount),
            AssetSearchResultPanel.MAX_VISIBLE_SOURCE_ITEMS
        );
        return visibleSourceCount * AssetSearchResultPanel.ITEM_HEIGHT
            + Math.max(0, visibleSourceCount - 1) * AssetSearchResultPanel.LIST_ROW_GAP;
    }

    private getErrorMessage(error: unknown): string {
        if (error instanceof Error && error.message) {
            return error.message;
        }

        return String(error);
    }

    private getStatusColor(level: AssetSearchStatusLevel): number {
        switch (level) {
            case "success":
                return 0x2e8b57;
            case "warning":
                return 0xb8860b;
            case "error":
                return 0xc0392b;
            default:
                return IEditor.GUIUtils.textColor.getHex();
        }
    }

    private refreshLayout(): void {
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

    private refreshItemWidths(list: gui.List, width: number): void {
        for (const child of list.children) {
            child.setSize(width, AssetSearchResultPanel.ITEM_HEIGHT);

            const title = child.getChild("issueTitle", gui.TextField);
            if (title) {
                this.resizeIssueTitle(title, width);
            }
        }
    }

    private resizeIssueTitle(title: gui.TextField, width: number): void {
        title.setSize(
            Math.max(
                0,
                width - AssetSearchResultPanel.ISSUE_ICON_SIZE - AssetSearchResultPanel.ISSUE_ICON_GAP
            ),
            AssetSearchResultPanel.ITEM_HEIGHT
        );
    }

    private isStringListChanged(
        renderedValues: ReadonlyArray<string>,
        currentValues: ReadonlyArray<string>
    ): boolean {
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

    private async rebuildDependencyIndex(): Promise<void> {
        const baseState = this._state || AssetSearchResultPanel.createFallbackState();
        this._isRebuildingIndex = true;
        this.updateRebuildState(baseState, AssetSearchResultPanel.ACTION_STATUS_TEXT, "info", true, 0, 0);

        try {
            const indexData = await AssetDependencyIndex.rebuild({
                onProgress: (processedCount: number, totalCount: number) => {
                    const statusText = totalCount > 0
                        ? `${AssetSearchResultPanel.ACTION_STATUS_TEXT} ${processedCount}/${totalCount}`
                        : AssetSearchResultPanel.ACTION_STATUS_TEXT;
                    this.updateRebuildState(baseState, statusText, "info", true, processedCount, totalCount);
                }
            });

            this.updateRebuildState(
                baseState,
                `依赖索引已重建，已索引 ${indexData.assetCount} 个资源`,
                "success",
                false,
                indexData.assetCount,
                indexData.assetCount
            );
        } catch (error: unknown) {
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
    }

    private updateRebuildState(
        baseState: IAssetSearchPanelData,
        statusText: string,
        statusLevel: AssetSearchStatusLevel,
        isLoading: boolean,
        processedCount: number,
        totalCount: number
    ): void {
        this.setState({
            ...baseState,
            statusText,
            statusLevel,
            isLoading,
            processedCount,
            totalCount
        });
    }
}
