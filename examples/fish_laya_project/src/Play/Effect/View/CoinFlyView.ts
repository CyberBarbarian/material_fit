import { call, moveTo, play, scaleTo, seq, show, wait } from "../../../Common/Action";
import { SpriteFont } from "../../../Common/UI/SpriteFont";

const { regClass, property } = Laya;

/**
 * 金币飞行动画视图
 * 挂载到 coin_fly.lh 预制体上
 */
@regClass()
export class CoinFlyView extends Laya.Script {
    @property({ type: Laya.Prefab, caption: "金币预制体" })
    public coinPrefab: Laya.Prefab | null = null;

    @property({ type: Laya.Sprite, caption: "数字节点" })
    public textNode: Laya.Sprite | null = null;

    @property({ type: Number, caption: "金币大小 (px)" })
    public coinSize: number = 56;

    @property({ type: Number, caption: "飞行速度 (px/s)" })
    public flySpeed: number = 600;

    @property({ type: Number, caption: "预览金币数量" })
    public previewCount: number = 8;

    @property({ type: Number, caption: "预览金币数值" })
    public previewGoldCount: number = 8888;

    private _fromX: number = 0;
    private _fromY: number = 0;
    private _toX: number = 0;
    private _toY: number = 0;
    private _coinCount: number = 0;
    private _goldCount: number = 0;
    private _hasSetup: boolean = false;
    private _textBaseScaleX: number = 1;
    private _textBaseScaleY: number = 1;

    public onAwake(): void {
        this._findTextNode();
        this._cacheTextScale();
    }

    /**
     * 由程序调用，在 addChild 之前设置动画参数。
     * 坐标为相对于 owner 父节点的本地坐标。
     */
    public setup(
        fromX: number,
        fromY: number,
        toX: number,
        toY: number,
        coinCount: number,
        goldCount: number
    ): void {
        this._fromX = fromX;
        this._fromY = fromY;
        this._toX = toX;
        this._toY = toY;
        this._coinCount = coinCount;
        this._goldCount = goldCount;
        this._hasSetup = true;
    }

    public onStart(): void {
        if (!this.coinPrefab) {
            return;
        }

        if (this._hasSetup) {
            this._spawnCoins(
                this._fromX,
                this._fromY,
                this._toX,
                this._toY,
                this._coinCount,
                this._goldCount
            );
            return;
        }

        const owner = this.owner as Laya.Sprite;
        const g = owner.localToGlobal(new Laya.Point(0, 0));
        const cx = Laya.stage.width * 0.5 - g.x;
        const cy = Laya.stage.height * 0.5 - g.y;
        this._spawnCoins(cx, cy, cx - 350, cy + 250, this.previewCount, this.previewGoldCount);
    }

    public onDestroy(): void {
        Laya.timer.clearAll(this);
    }

    private _spawnCoins(
        fromX: number,
        fromY: number,
        toX: number,
        toY: number,
        coinCount: number,
        goldCount: number
    ): void {
        const owner = this.owner as Laya.Sprite;
        const coinSize = this.coinSize;
        const cols = coinCount > 5 ? Math.ceil(coinCount * 0.5) : coinCount;
        const rows = coinCount > 5 ? 2 : 1;
        const stageWidth = Laya.stage?.width || 1920;
        const stageHeight = Laya.stage?.height || 1080;

        let x = fromX - coinSize * (cols - 1) * 0.5;
        let y = fromY + coinSize / (coinCount > 6 ? 2 : 1);
        x = Math.max(coinSize, Math.min(x, stageWidth - coinSize * cols));
        y = Math.max(coinSize, Math.min(y, stageHeight));

        const flyTime = Math.sqrt((toX - fromX) ** 2 + (toY - fromY) ** 2) / this.flySpeed;
        let done = 0;

        const textY = y + 40 - coinSize * (rows - 1) * 0.5;
        this._playGoldText(fromX, textY, goldCount);

        for (let i = 0; i < coinCount; i++) {
            const coin = this._createCoin(i);
            if (!coin) {
                continue;
            }

            if (coin.parent !== owner) {
                owner.addChild(coin);
            }

            coin.zOrder = -i;
            coin.visible = false;

            const row = Math.floor(i / cols);
            const col = i % cols;
            const offsetX = coinCount % 2 === 0 || row === 0 ? 0 : coinSize * 0.5;
            const delay = row === 0 ? 0 : cols / 30;
            const xx = x + col * coinSize + offsetX;
            const yy = y - row * coinSize + 20;
            coin.pos(xx, yy);

            play(seq(
                wait(delay + (5 + col * 2) / 30),
                show(),
                seq(
                    moveTo(5 / 30, xx, yy + 60, 0),
                    moveTo(8 / 30, xx, yy - 5, 0, "sineInOut"),
                    moveTo(8 / 30, xx, yy + 40, 0, "sineInOut"),
                    moveTo(8 / 30, xx, yy + 20, 0),
                    wait(2 / 30 - delay),
                    moveTo(flyTime, toX, toY, 0, "quadIn")
                ),
                call(() => {
                    coin.visible = false;
                    if (++done === coinCount) {
                        this.owner?.destroy();
                    }
                })
            ), coin);
        }

        Laya.timer.once(3000, this, () => this.owner?.destroy());
    }

    private _playGoldText(centerX: number, y: number, goldCount: number): void {
        const textNode = this.textNode;
        if (!textNode || goldCount <= 0) {
            return;
        }

        this._setTextValue(String(goldCount));
        textNode.pos(centerX, y);
        textNode.visible = false;
        textNode.scale(this._textBaseScaleX * 0.01, this._textBaseScaleY * 0.01);

        play(seq(
            wait(0.3),
            show(),
            scaleTo(5 / 30, this._textBaseScaleX * 1.2, this._textBaseScaleY * 1.2, 0, "quadOut"),
            scaleTo(3 / 30, this._textBaseScaleX, this._textBaseScaleY),
            wait(1),
            scaleTo(0.2, 0, 0),
            call(() => {
                textNode.visible = false;
            })
        ), textNode);
    }

    private _createCoin(index: number): Laya.Sprite | null {
        if (!this.coinPrefab) {
            return null;
        }

        const coin = this.coinPrefab.create() as Laya.Sprite | null;
        if (!coin) {
            return null;
        }

        if (index === 0) {
            coin.name = coin.name || "coin";
        }

        return coin;
    }

    private _findTextNode(): void {
        const owner = this.owner as Laya.Sprite;
        this.textNode = this.textNode ?? owner.getChildByName("text") as Laya.Sprite;
    }

    private _cacheTextScale(): void {
        if (!this.textNode) {
            return;
        }

        this._textBaseScaleX = this.textNode.scaleX || 1;
        this._textBaseScaleY = this.textNode.scaleY || 1;
    }

    private _setTextValue(value: string): void {
        const textNode = this.textNode;
        if (!textNode) {
            return;
        }

        const spriteFont = textNode.getComponent(SpriteFont) as SpriteFont | null;
        if (spriteFont) {
            spriteFont.text = value;
            return;
        }

        if ("text" in textNode) {
            (textNode as unknown as { text: string }).text = value;
        }
    }
}
