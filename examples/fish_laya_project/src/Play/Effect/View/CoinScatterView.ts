import { moveTo, play, scaleTo, seq, show, spawn, wait } from "../../../Common/Action";

const { regClass, property } = Laya;

/**
 * 金币爆炸动画视图
 * 挂载到 coin_scatter.lh 预制体上
 *
 * 用法（程序）：setup() → addChild
 * 用法（美术）：直接拖入场景，从屏幕中心播放
 */
@regClass()
export class CoinScatterView extends Laya.Script {

    // ============ 可在 IDE 面板调整的参数 ============

    @property({ type: Laya.Prefab, caption: "金币预制体" })
    public coinPrefab: Laya.Prefab | null = null;

    @property({ type: Number, caption: "爆炸半径 (px)" })
    public explodeRadius: number = 1300;

    @property({ type: Number, caption: "金币放大倍数" })
    public scaleFactor: number = 3;

    @property({ type: Number, caption: "动画时长 (s)" })
    public duration: number = 1.5;

    @property({ type: Number, caption: "预览金币数量" })
    public previewCount: number = 20;

    // ============ 私有状态 ============

    private _cx: number = 0;
    private _cy: number = 0;
    private _count: number = 0;
    private _hasSetup: boolean = false;

    // ============ 公共接口 ============

    /**
     * 由程序调用，在 addChild 之前设置动画参数。
     * 坐标为相对于 owner 父节点的本地坐标。
     */
    public setup(centerX: number, centerY: number, count: number): void {
        this._cx = centerX;
        this._cy = centerY;
        this._count = count;
        this._hasSetup = true;
    }

    // ============ 生命周期 ============

    onStart(): void {
        if (!this.coinPrefab) return;

        if (this._hasSetup) {
            this._spawnExplode(this._cx, this._cy, this._count);
        } else {
            // 美术预览：从屏幕中心爆炸
            const g = (this.owner as Laya.Sprite).localToGlobal(new Laya.Point(0, 0));
            const cx = Laya.stage.width * 0.5 - g.x;
            const cy = Laya.stage.height * 0.5 - g.y;
            this._spawnExplode(cx, cy, this.previewCount);
        }
    }

    onDestroy(): void {
        Laya.timer.clearAll(this);
    }

    // ============ 私有方法 ============

    private _spawnExplode(cx: number, cy: number, count: number): void {
        for (let i = 0; i < count; i++) {
            const coin = this.coinPrefab!.create() as Laya.Sprite;
            if (!coin) continue;

            (this.owner as Laya.Sprite).addChild(coin);
            coin.pos(cx, cy);
            coin.visible = false;

            const angle = Math.random() * Math.PI * 2;
            play(seq(
                wait(Math.random()),
                show(),
                spawn(
                    scaleTo(this.duration, this.scaleFactor, this.scaleFactor),
                    moveTo(this.duration,
                        cx + Math.cos(angle) * this.explodeRadius,
                        cy + Math.sin(angle) * this.explodeRadius
                    )
                )
            ), coin);
        }

        Laya.timer.once(4000, this, () => this.owner?.destroy());
    }
}
