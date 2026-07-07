const { regClass, property } = Laya;

/**
 * 金币爆开动画视图
 * 挂载到 coin_explode.lh 预制体上（3D prefab）
 *
 * 预制体自带爆开动画，本脚本负责定位和定时销毁。
 *
 * 用法（程序）：setup(cx, cy) → addChild
 * 用法（美术）：直接拖入场景，从 (0, 0) 播放
 */
@regClass()
export class CoinExplodeView extends Laya.Script3D {

    // ============ 可在 IDE 面板调整的参数 ============

    @property({ type: Number, caption: "动画时长 (ms)" })
    public duration: number = 1500;

    // ============ 私有状态 ============

    private _cx: number = 0;
    private _cy: number = 0;
    private _hasSetup: boolean = false;

    // ============ 公共接口 ============

    /**
     * 由程序调用，在 addChild 之前设置显示坐标。
     * 坐标为游戏世界坐标（resolveLockPoint 输出，已 mirror）。
     */
    public setup(cx: number, cy: number): void {
        this._cx = cx;
        this._cy = cy;
        this._hasSetup = true;
    }

    // ============ 生命周期 ============

    public onStart(): void {
        if (this._hasSetup) {
            (this.owner as Laya.Sprite3D).transform.localPosition = new Laya.Vector3(this._cx, this._cy, 0);
        }
        Laya.timer.once(this.duration, this, () => this.owner?.destroy());
    }

    public onDestroy(): void {
        Laya.timer.clearAll(this);
    }
}
