const { regClass, property } = Laya;

/**
 * 摄像机渲染层级，值越大越置顶（等同于 Unity Camera Depth）。
 */
@regClass()
export class CameraRenderOrder extends Laya.Script3D {
    private _renderingOrder: number = 0;

    @property({ type: Number, caption: "渲染层级" })
    get renderingOrder(): number {
        return this._renderingOrder;
    }

    set renderingOrder(value: number) {
        this._renderingOrder = value;
        if (this.owner) (this.owner as Laya.Camera).renderingOrder = value;
    }

    onAwake(): void {
        (this.owner as Laya.Camera).renderingOrder = this._renderingOrder;
    }
}
