const { regClass, property } = Laya;

/** 铺满父节点脚本，支持拉伸模式和保持宽高比模式（cover） */
@regClass()
export class FillParent extends Laya.Script {
    private _fillParent: boolean = false;

    /** 点击后执行铺满父节点操作 */
    @property({ type: Boolean, caption: "铺满父节点" })
    public get fillParent(): boolean {
        return this._fillParent;
    }

    public set fillParent(value: boolean) {
        this._fillParent = value;
        if (value) {
            this.scheduleApplyFillParent();
            this._fillParent = false;
        }
    }

    private _keepAspectRatio: boolean = false;

    /** 保持原始宽高比，使用 cover 模式铺满 */
    @property({ type: Boolean, caption: "保持宽高比" })
    public get keepAspectRatio(): boolean {
        return this._keepAspectRatio;
    }

    public set keepAspectRatio(value: boolean) {
        if (this._keepAspectRatio === value) {
            return;
        }
        this._keepAspectRatio = value;
        this.scheduleApplyFillParent();
    }

    public onEnable(): void {
        Laya.stage.on(Laya.Event.RESIZE, this, this.scheduleApplyFillParent);
        this.owner.on(Laya.Event.LOADED, this, this.scheduleApplyFillParent);
        this.scheduleApplyFillParent();
    }

    public onDisable(): void {
        Laya.stage.off(Laya.Event.RESIZE, this, this.scheduleApplyFillParent);
        this.owner.off(Laya.Event.LOADED, this, this.scheduleApplyFillParent);
        Laya.timer.clear(this, this.applyFillParent);
    }

    private scheduleApplyFillParent(): void {
        Laya.timer.callLater(this, this.applyFillParent);
    }

    private applyFillParent(): void {
        const owner = this.owner as Laya.Sprite;
        if (!owner) {
            return;
        }

        const parent = owner.parent;
        if (!parent) {
            return;
        }

        const parentWidth = this.getContainerWidth(parent);
        const parentHeight = this.getContainerHeight(parent);
        if (parentWidth <= 0 || parentHeight <= 0) {
            return;
        }

        let newWidth = parentWidth;
        let newHeight = parentHeight;
        let offsetX = 0;
        let offsetY = 0;

        if (this._keepAspectRatio) {
            const texture = owner.texture as {
                width: number;
                height: number;
                sourceWidth?: number;
                sourceHeight?: number;
            } | null;
            const textureWidth = texture ? (texture.sourceWidth ?? texture.width) : 0;
            const textureHeight = texture ? (texture.sourceHeight ?? texture.height) : 0;
            const sourceWidth = textureWidth > 0 ? textureWidth : owner.width;
            const sourceHeight = textureHeight > 0 ? textureHeight : owner.height;
            if (sourceWidth <= 0 || sourceHeight <= 0) {
                return;
            }

            const originalRatio = sourceWidth / sourceHeight;
            const parentRatio = parentWidth / parentHeight;

            if (originalRatio < parentRatio) {
                newHeight = parentWidth / originalRatio;
            } else {
                newWidth = parentHeight * originalRatio;
            }

            offsetX = (parentWidth - newWidth) / 2;
            offsetY = (parentHeight - newHeight) / 2;
        }

        owner.width = newWidth;
        owner.height = newHeight;
        owner.x = offsetX;
        owner.y = offsetY;
        owner.anchorX = 0;
        owner.anchorY = 0;
        owner.scaleX = 1;
        owner.scaleY = 1;
    }

    private getContainerWidth(parent: Laya.Node): number {
        const parentSprite = parent as Laya.Sprite;
        return parentSprite.width > 0 ? parentSprite.width : (Laya.stage.width || Laya.stage.designWidth);
    }

    private getContainerHeight(parent: Laya.Node): number {
        const parentSprite = parent as Laya.Sprite;
        return parentSprite.height > 0 ? parentSprite.height : (Laya.stage.height || Laya.stage.designHeight);
    }
}
