import { call, moveTo, play, scaleTo, seq, show, wait } from "../../../Common/Action";
import { SpriteFont } from "../../../Common/UI/SpriteFont";

const { regClass, property } = Laya;

@regClass()
export class CoinFlyFakeView extends Laya.Script {
    private static readonly MIN_GOLD_COUNT: number = 100000;
    private static readonly MAX_GOLD_COUNT: number = 200000;
    private static readonly MIN_START_DELAY_MS: number = 1000;
    private static readonly MAX_START_DELAY_MS: number = 3000;

    @property({ type: Laya.Prefab, caption: "金币预制体" })
    public coinPrefab: Laya.Prefab | null = null;

    @property({ type: Laya.Sprite, caption: "数字节点" })
    public textNode: Laya.Sprite | null = null;

    @property({ type: Number, caption: "金币大小(px)" })
    public coinSize: number = 56;

    @property({ type: Number, caption: "飞行速度(px/s)" })
    public flySpeed: number = 600;

    @property({ type: Number, caption: "屏幕边距(px)" })
    public screenPadding: number = 80;

    @property({ type: Number, caption: "落点下偏移(px)" })
    public targetOffsetY: number = 160;

    private _textBaseScaleX: number = 1;
    private _textBaseScaleY: number = 1;
    private _tempPoint: Laya.Point = new Laya.Point();

    public onAwake(): void {
        this._findTextNode();
        this._cacheTextScale();
    }

    public onStart(): void {
        if (!this.coinPrefab) {
            this.owner?.destroy();
            return;
        }

        const delayMs = this._randomRange(
            CoinFlyFakeView.MIN_START_DELAY_MS,
            CoinFlyFakeView.MAX_START_DELAY_MS + 1
        );
        Laya.timer.once(delayMs, this, this._startPlayback);
    }

    public onDestroy(): void {
        Laya.timer.clearAll(this);
    }

    private _startPlayback(): void {
        const owner = this.owner as Laya.Sprite;
        if (!owner || owner.destroyed || !this.coinPrefab) {
            return;
        }

        const startScreen = this._getRandomScreenPoint();
        const targetScreen = this._getTargetScreenPoint();
        const startLocal = this._screenToParentLocal(startScreen.x, startScreen.y);
        const targetLocal = this._screenToParentLocal(targetScreen.x, targetScreen.y);
        const goldCount = this._randomGoldCount();
        const coinCount = this._getCoinCount(goldCount);

        owner.pos(0, 0);
        this._spawnCoins(startLocal.x, startLocal.y, targetLocal.x, targetLocal.y, coinCount, goldCount);
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
        const parentWidth = this._getParentWidth();
        const parentHeight = this._getParentHeight();

        let x = fromX - coinSize * (cols - 1) * 0.5;
        let y = fromY + coinSize / (coinCount > 6 ? 2 : 1);
        x = Math.max(coinSize, Math.min(x, parentWidth - coinSize * cols));
        y = Math.max(coinSize, Math.min(y, parentHeight));

        const flyTime = Math.sqrt((toX - fromX) ** 2 + (toY - fromY) ** 2) / this.flySpeed;
        let done = 0;

        const textY = y + 40 - coinSize * (rows - 1) * 0.5;
        this._playGoldText(fromX, textY, goldCount);

        for (let i = 0; i < coinCount; i++) {
            const coin = this.coinPrefab.create() as Laya.Sprite | null;
            if (!coin) {
                continue;
            }

            owner.addChild(coin);
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
                        owner.destroy();
                    }
                })
            ), coin);
        }

        const destroyDelayMs = Math.max(3000, (flyTime + 2) * 1000);
        Laya.timer.once(destroyDelayMs, this, () => owner.destroy());
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
            spriteFont.forceRefresh();
            return;
        }

        if ("text" in textNode) {
            (textNode as unknown as { text: string }).text = value;
        }
    }

    private _getRandomScreenPoint(): { x: number; y: number } {
        const uiWidth = this._getUIWidth();
        const uiHeight = this._getUIHeight();
        return {
            x: this._randomRange(this.screenPadding, uiWidth - this.screenPadding),
            y: this._randomRange(this.screenPadding, uiHeight - this.screenPadding),
        };
    }

    private _getTargetScreenPoint(): { x: number; y: number } {
        const uiWidth = this._getUIWidth();
        const uiHeight = this._getUIHeight();
        return {
            x: uiWidth * 0.5,
            y: Math.min(uiHeight - this.screenPadding, uiHeight * 0.5 + this.targetOffsetY),
        };
    }

    private _screenToParentLocal(screenX: number, screenY: number): Laya.Point {
        const parent = this.owner?.parent as Laya.Sprite | null;
        if (!parent) {
            return new Laya.Point(screenX, screenY);
        }

        const parentOrigin = parent.localToGlobal(this._tempPoint.setTo(0, 0), false);
        return new Laya.Point(screenX - parentOrigin.x, screenY - parentOrigin.y);
    }

    private _getParentWidth(): number {
        const parent = this.owner?.parent as Laya.Sprite | null;
        return parent?.width || this._getUIWidth();
    }

    private _getParentHeight(): number {
        const parent = this.owner?.parent as Laya.Sprite | null;
        return parent?.height || this._getUIHeight();
    }

    private _getUIWidth(): number {
        return 1136;
    }

    private _getUIHeight(): number {
        return 640;
    }

    private _randomGoldCount(): number {
        return Math.floor(this._randomRange(CoinFlyFakeView.MIN_GOLD_COUNT, CoinFlyFakeView.MAX_GOLD_COUNT + 1));
    }

    private _randomRange(min: number, max: number): number {
        if (max <= min) {
            return min;
        }
        return min + Math.random() * (max - min);
    }

    private _getCoinCount(goldCount: number): number {
        if (goldCount > 250) return 11;
        if (goldCount > 150) return 9;
        if (goldCount > 50) return 8;
        if (goldCount > 20) return 8;
        if (goldCount > 12) return 7;
        if (goldCount > 9) return 8;
        if (goldCount > 6) return 6;
        if (goldCount > 3) return 4;
        return 2;
    }
}
