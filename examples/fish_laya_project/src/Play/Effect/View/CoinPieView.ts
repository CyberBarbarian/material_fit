import { call, moveTo, play, seq, show, wait } from "../../../Common/Action";

const { regClass, property } = Laya;

/**
 * 金币饼动画视图
 * 挂载到 coin_pie.lh 预制体上
 *
 * 参考 GameEffectGoldPie.cs：20 枚金币固定偏移散布，弹跳后飞向炮台。
 *
 * 用法（程序）：setup() → addChild
 * 用法（美术）：直接拖入场景，从屏幕中心播放
 */
@regClass()
export class CoinPieView extends Laya.Script {

    // ============ 可在 IDE 面板调整的参数 ============

    /**
     * 20 枚金币的固定偏移坐标（Laya Y-down，由 GameEffectGoldPie.cs 转换而来）
     * 原始坐标为 Unity Y-up，转换规则：offsetY_laya = -offsetY_unity
     */
    private static readonly OFFSETS: ReadonlyArray<readonly [number, number]> = [
        [-103, -168], [-2, -184], [103, -146],
        [-68, -122], [36, -123],
        [-149, -69], [-87, -41], [6, -67], [149, -87],
        [-166, 26], [-105, 25], [-39, 2], [28, -36], [100, -27], [146, -3],
        [-122, 111], [16, 60], [125, 69],
        [-29, 127], [59, 142],
    ];
    @property({ type: Laya.Prefab, caption: "金币预制体" })
    public coinPrefab: Laya.Prefab | null = null;
    @property({ type: Number, caption: "飞行前延迟 (s)" })
    public runDelayTime: number = 0.5;

    // ============ 私有状态 ============
    @property({ type: Number, caption: "飞行速度 (px/s)" })
    public flySpeed: number = 800;
    private _fromX: number = 0;
    private _fromY: number = 0;
    private _toX: number = 0;
    private _toY: number = 0;

    // ============ 公共接口 ============
    private _hasSetup: boolean = false;

    // ============ 生命周期 ============

    /**
     * 由程序调用，在 addChild 之前设置动画参数。
     * 坐标为相对于 owner 父节点的本地坐标。
     */
    public setup(fromX: number, fromY: number, toX: number, toY: number): void {
        this._fromX = fromX;
        this._fromY = fromY;
        this._toX = toX;
        this._toY = toY;
        this._hasSetup = true;
    }

    public onStart(): void {
        if (!this.coinPrefab) return;

        if (this._hasSetup) {
            this._spawnCoins(this._fromX, this._fromY, this._toX, this._toY);
        } else {
            // 美术预览：从屏幕中心飞向左下
            const g = (this.owner as Laya.Sprite).localToGlobal(new Laya.Point(0, 0));
            const cx = Laya.stage.width * 0.5 - g.x;
            const cy = Laya.stage.height * 0.5 - g.y;
            this._spawnCoins(cx, cy, cx - 350, cy + 250);
        }
    }

    // ============ 私有方法 ============

    public onDestroy(): void {
        Laya.timer.clearAll(this);
    }

    private _spawnCoins(fromX: number, fromY: number, toX: number, toY: number): void {
        const offsets = CoinPieView.OFFSETS;
        const count = offsets.length;
        let maxFlyTime = 0;
        let done = 0;

        for (let i = 0; i < count; i++) {
            const coin = this.coinPrefab!.create() as Laya.Sprite;
            if (!coin) continue;

            (this.owner as Laya.Sprite).addChild(coin);
            coin.zOrder = -i;
            coin.visible = false;

            const jitterX = (Math.random() - 0.5) * 40;
            const jitterY = (Math.random() - 0.5) * 40;
            const xx = fromX + offsets[i][0] + jitterX;
            const yy = fromY + offsets[i][1] + jitterY;
            coin.pos(xx, yy);

            const dx = toX - xx;
            const dy = toY - yy;
            const flyTime = Math.sqrt(dx * dx + dy * dy) / this.flySpeed;
            if (flyTime > maxFlyTime) maxFlyTime = flyTime;

            play(seq(
                wait(this.runDelayTime),
                show(),
                seq(
                    moveTo(5 / 30, xx, yy + 60, 0),
                    moveTo(8 / 30, xx, yy - 5, 0, "sineInOut"),
                    moveTo(8 / 30, xx, yy + 40, 0, "sineInOut"),
                    moveTo(5 / 30, xx, yy + 20, 0),
                    moveTo(flyTime, toX, toY, 0, "quadIn")
                ),
                call(() => {
                    coin.visible = false;
                    if (++done === count) this.owner?.destroy();
                })
            ), coin);
        }

        // 兜底销毁：runDelayTime + 弹跳动画(26/30s) + 最长飞行时间 + 1s 缓冲
        const bounceTime = (5 + 8 + 8 + 5) / 30;
        const destroyDelay = (this.runDelayTime + bounceTime + maxFlyTime + 1) * 1000;
        Laya.timer.once(destroyDelay, this, () => this.owner?.destroy());
    }
}
