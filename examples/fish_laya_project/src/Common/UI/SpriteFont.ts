const {regClass, property} = Laya;

// 常量

/** 垂直对齐枚举 */
const enum VAlign {
    TOP = 0,
    MIDDLE = 1,
    BOTTOM = 2
}

/** 水平对齐枚举 */
const enum HAlign {
    LEFT = 0,
    CENTER = 1,
    RIGHT = 2
}

/** 对齐字符串到枚举的映射 */
const VALIGN_MAP: Record<string, VAlign> = {
    "top": VAlign.TOP,
    "middle": VAlign.MIDDLE,
    "bottom": VAlign.BOTTOM
};

const HALIGN_MAP: Record<string, HAlign> = {
    "left": HAlign.LEFT,
    "center": HAlign.CENTER,
    "right": HAlign.RIGHT
};

// 配置接口

interface IImageCharConfig {
    char: string;
    image: string;
    advance?: number;
    offsetX?: number;
    offsetY?: number;
}

interface IFontClipImageConfig {
    lineHeight?: number;
    chars: IImageCharConfig[];
}

interface ICharRenderInfo {
    texture: Laya.Texture;
    width: number;
    height: number;
    sourceWidth: number;
    sourceHeight: number;
    advance: number;
    offsetX: number;
    offsetY: number;
}

/** 字符映射表类型 */
type CharMapType = Record<string, ICharRenderInfo>;

/**
 * 图片文字组件（自动图集）
 *
 * 使用方式：
 * 1. 推荐挂到纯 Sprite 节点；若挂在 UI2 的 GTextField 上，本组件会在 onEnable 时关闭 textIns 的绘制，
 *    否则子节点 textIns 会叠在父节点 graphics 之上，盖住此处绘制的位图字（与 Laya.Text 共用 graphics 同理）。
 * 2. 设置 fontConfig 为字符配置文件路径
 * 3. 设置 text 显示文字
 */
@regClass()
export class SpriteFont extends Laya.Script {

    /** 字符渲染信息映射：char -> ICharRenderInfo */
    private _charMap: CharMapType = Object.create(null);

    /** 字体配置 */
    private _config: IFontClipImageConfig | null = null;
    /** 是否需要刷新 */
    private _needRefresh: boolean = false;
    /** 是否已加载完成 */
    private _loaded: boolean = false;
    /** 未知字符的默认宽度 */
    private _defaultCharWidth: number = 20;
    /** 加载序号（防止异步覆盖） */
    private _loadId: number = 0;
    /** 上一次渲染的文本 */
    private _lastText: string = "";
    /** 上一次的字符间距 */
    private _lastLetterSpacing: number = 0;
    /** 上一次的水平对齐 */
    private _lastAlignX: HAlign = HAlign.LEFT;
    /** 上一次的垂直对齐 */
    private _lastAlignY: VAlign = VAlign.BOTTOM;

    /** 字体配置路径 */
    private _fontConfig: string = "";

    /**
     * 字体配置文件路径
     */
    @property({
        type: String,
        caption: "字体配置",
        isAsset: true,
        assetTypeFilter: "Json",
        useAssetPath: true
    })
    public get fontConfig(): string {
        return this._fontConfig;
    }

    public set fontConfig(v: string) {
        if (this._fontConfig === v) return;
        this._fontConfig = v;
        if (v) {
            this.loadFont(v);
        } else {
            this._clearFont();
        }
    }

    /** 当前显示的文本 */
    private _text: string = "";

    /**
     * 设置/获取显示的文本
     */
    @property({type: String, caption: "文本"})
    public get text(): string {
        return this._text;
    }

    public set text(v: string) {
        const newValue = v ?? "";
        if (this._text === newValue) return;
        this._text = newValue;
        this._markRefresh();
    }

    /** 字符间额外间距 */
    private _letterSpacing: number = 0;

    /**
     * 设置/获取字符间距
     */
    @property({type: Number, caption: "字符间距"})
    public get letterSpacing(): number {
        return this._letterSpacing;
    }

    public set letterSpacing(v: number) {
        if (this._letterSpacing === v) return;
        this._letterSpacing = v;
        this._markRefresh();
    }

    /** 字符内水平对齐 */
    private _charAlignX: HAlign = HAlign.LEFT;

    /**
     * 设置/获取字符内水平对齐方式
     */
    @property({
        type: String,
        caption: "字符水平对齐",
        enumSource: ["left", "center", "right"]
    })
    public get charAlignX(): string {
        return this._charAlignX === HAlign.LEFT ? "left" :
            this._charAlignX === HAlign.CENTER ? "center" : "right";
    }

    public set charAlignX(v: string) {
        const alignValue = HALIGN_MAP[v] ?? HAlign.LEFT;
        if (this._charAlignX === alignValue) return;
        this._charAlignX = alignValue;
        this._markRefresh();
    }

    /** 字符内垂直对齐 */
    private _charAlignY: VAlign = VAlign.BOTTOM;

    /**
     * 设置/获取字符内垂直对齐方式
     */
    @property({
        type: String,
        caption: "字符垂直对齐",
        enumSource: ["top", "middle", "bottom"]
    })
    public get charAlignY(): string {
        return this._charAlignY === VAlign.TOP ? "top" :
            this._charAlignY === VAlign.MIDDLE ? "middle" : "bottom";
    }

    public set charAlignY(v: string) {
        const alignValue = VALIGN_MAP[v] ?? VAlign.BOTTOM;
        if (this._charAlignY === alignValue) return;
        this._charAlignY = alignValue;
        this._markRefresh();
    }

    /** 缓存的总宽度 */
    private _cachedWidth: number = 0;

    public get cachedWidth(): number {
        return this._cachedWidth;
    }

    /** 缓存的总高度 */
    private _cachedHeight: number = 0;

    public get cachedHeight(): number {
        return this._cachedHeight;
    }

    public get isLoaded(): boolean {
        return this._loaded;
    }

    /**
     * 加载字体配置
     */
    public loadFont(configPath: string): void {
        this._clearPendingRefresh();
        this._fontConfig = configPath;
        this._loaded = false;
        const loadId = ++this._loadId;

        Laya.loader.load(configPath).then((res: any) => {
            // 检查是否已销毁或加载序号不匹配
            if (this.destroyed || this._loadId !== loadId) return null;

            const config: IFontClipImageConfig = res?.data ?? res;
            if (!config || !Array.isArray(config.chars)) {
                console.error("[SpriteFont] 加载配置失败:", configPath);
                return null;
            }

            this._config = config;

            // 收集图片路径
            const imagePaths: string[] = [];

            // 使用对象去重
            const seen: Record<string, boolean> = Object.create(null);
            const chars = config.chars;
            for (let i = 0, len = chars.length; i < len; i++) {
                const charConfig = chars[i];
                const image = charConfig?.image;
                if (image && !seen[image]) {
                    seen[image] = true;
                    imagePaths.push(image);
                }
            }

            if (imagePaths.length === 0) {
                return true;
            }

            return Laya.loader.load(imagePaths);
        }).then(() => {
            // 再次检查状态
            if (this.destroyed || this._loadId !== loadId || !this._config) return;

            this._buildCharMap();
            this._loaded = true;
            this._refresh();
        }).catch((err: any) => {
            if (!this.destroyed) {
                console.error("[SpriteFont] 加载配置异常:", configPath, err);
            }
        });
    }

    /**
     * 获取文本渲染宽度
     */
    public measureWidth(text?: string): number {
        const str = text ?? this._text;
        if (!str || !this._loaded) return 0;

        const charMap = this._charMap;
        const letterSpacing = this._letterSpacing;
        const defaultWidth = this._defaultCharWidth;
        const len = str.length;

        let width = 0;
        for (let i = 0; i < len; i++) {
            const info = charMap[str[i]];
            width += (info ? info.advance : defaultWidth) + letterSpacing;
        }

        // 减去最后一个字符后的间距
        return len > 0 ? width - letterSpacing : 0;
    }

    /**
     * 获取行高
     */
    public getLineHeight(): number {
        return this._config?.lineHeight ?? 0;
    }

    public reset(): void {
        this._clearPendingRefresh();
        this._text = "";
        this._letterSpacing = 0;
        this._charAlignX = HAlign.LEFT;
        this._charAlignY = VAlign.BOTTOM;
        this._lastText = "";

        const sprite = this.owner as Laya.Sprite;
        if (sprite && !sprite.destroyed) {
            sprite.graphics.clear(true);
            sprite.size(0, 0);
        }
    }

    public forceRefresh(): void {
        if (this._loaded) {
            this._refresh(true);
        }
    }

    onEnable(): void {
        this._suppressHostTextOverlay();
        if (this._fontConfig && !this._loaded) {
            this.loadFont(this._fontConfig);
        } else if (this._loaded && this._text) {
            this._markRefresh();
        }
    }

    /**
     * GTextField 用子节点 textIns 绘字，会盖住父节点 graphics；Laya.Text 则与 graphics 同源，typeset 会 clear。
     * 使用 SpriteFont 时应关闭宿主文字绘制，仅保留位图。
     */
    private _suppressHostTextOverlay(): void {
        const owner = this.owner as Laya.Sprite & { textIns?: Laya.Text };
        if (owner && owner.textIns) {
            owner.textIns.text = "";
            owner.textIns.hideText(true);
            return;
        }
        if (this.owner instanceof Laya.Text) {
            this.owner.text = "";
            this.owner.hideText(true);
        }
    }

    onDisable(): void {
        this._clearPendingRefresh();
    }

    onDestroy(): void {
        this._clearPendingRefresh();
        this._clearCharMap();
        this._config = null;
        this._loaded = false;
        this._lastText = "";
    }

    private _clearFont(): void {
        this.reset();
        this._clearCharMap();
        this._config = null;
        this._loaded = false;
    }

    private _clearCharMap(): void {
        const charMap = this._charMap;
        for (const key in charMap) {
            delete charMap[key];
        }
    }

    private _clearPendingRefresh(): void {
        Laya.timer.clearCallLater(this, this._refresh);
        this._needRefresh = false;
    }

    private _buildCharMap(): void {
        this._clearCharMap();

        const config = this._config;
        if (!config) return;

        const charMap = this._charMap;
        const chars = config.chars;
        for (let i = 0, len = chars.length; i < len; i++) {
            const charConfig = chars[i];
            if (!charConfig?.char || !charConfig.image) continue;

            const texture = Laya.loader.getRes(charConfig.image) as Laya.Texture;
            if (!texture) {
                console.warn("[SpriteFont] 找不到图片:", charConfig.image);
                continue;
            }

            charMap[charConfig.char] = this._createCharInfo(charConfig, texture);
        }
    }

    private _createCharInfo(charConfig: IImageCharConfig, texture: Laya.Texture): ICharRenderInfo {
        const sourceWidth = texture.sourceWidth || texture.width;
        const sourceHeight = texture.sourceHeight || texture.height;
        return {
            texture,
            width: texture.width,
            height: texture.height,
            sourceWidth,
            sourceHeight,
            advance: charConfig.advance ?? sourceWidth,
            offsetX: charConfig.offsetX ?? texture.offsetX ?? 0,
            offsetY: charConfig.offsetY ?? texture.offsetY ?? 0
        };
    }

    private _markRefresh(): void {
        if (!this._loaded || this._needRefresh) return;
        this._needRefresh = true;
        Laya.timer.callLater(this, this._refresh);
    }

    private _refresh(force: boolean = false): void {
        this._needRefresh = false;

        const sprite = this.owner as Laya.Sprite;
        if (!sprite || sprite.destroyed) return;

        const text = this._text;
        const g = sprite.graphics;

        if (!text || !this._loaded) {
            if (this._lastText) {
                g.clear(true);
                sprite.size(0, 0);
                this._cachedWidth = 0;
                this._cachedHeight = 0;
                this._lastText = "";
            }
            return;
        }

        const letterSpacing = this._letterSpacing;
        const alignX = this._charAlignX;
        const alignY = this._charAlignY;

        const needRedraw = force ||
            text !== this._lastText ||
            letterSpacing !== this._lastLetterSpacing ||
            alignX !== this._lastAlignX ||
            alignY !== this._lastAlignY;

        if (!needRedraw) return;

        this._lastText = text;
        this._lastLetterSpacing = letterSpacing;
        this._lastAlignX = alignX;
        this._lastAlignY = alignY;

        g.clear(true);

        const charMap = this._charMap;
        const defaultWidth = this._defaultCharWidth;
        const textLength = text.length;
        const configLineHeight = this._config?.lineHeight ?? 0;

        let totalWidth = 0;
        let maxHeight = 0;

        for (let i = 0; i < textLength; i++) {
            const info = charMap[text[i]];
            if (info) {
                totalWidth += info.advance;
                if (info.sourceHeight > maxHeight) {
                    maxHeight = info.sourceHeight;
                }
            } else {
                totalWidth += defaultWidth;
            }
        }

        if (textLength > 1) {
            totalWidth += letterSpacing * (textLength - 1);
        }

        const lineHeight = configLineHeight || maxHeight;

        this._cachedWidth = totalWidth;
        this._cachedHeight = lineHeight;

        sprite.size(totalWidth, lineHeight);

        let x = 0;
        for (let i = 0; i < textLength; i++) {
            const info = charMap[text[i]];
            if (info) {
                let alignOffsetX = 0;
                if (alignX === HAlign.CENTER) {
                    alignOffsetX = (info.advance - info.sourceWidth) * 0.5;
                } else if (alignX === HAlign.RIGHT) {
                    alignOffsetX = info.advance - info.sourceWidth;
                }

                let alignOffsetY = 0;
                if (alignY === VAlign.BOTTOM) {
                    alignOffsetY = lineHeight - info.sourceHeight;
                } else if (alignY === VAlign.MIDDLE) {
                    alignOffsetY = (lineHeight - info.sourceHeight) * 0.5;
                }

                g.drawImage(
                    info.texture,
                    x + alignOffsetX + info.offsetX,
                    alignOffsetY + info.offsetY,
                    info.width,
                    info.height
                );

                x += info.advance + letterSpacing;
            } else {
                x += defaultWidth + letterSpacing;
            }
        }
    }
}
