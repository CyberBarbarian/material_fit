const { regClass, property } = Laya;

/**
 * 特效延迟播放组件
 * @description 挂载到特效节点上，启用时隐藏所有子节点、禁用动画器、暂停粒子，延迟 delayTime 秒后统一恢复播放。
 */
@regClass()
export class EffectDelay extends Laya.Script {
    // ============ @property 公共字段 ============

    /** 延迟播放时间（秒）。小于 0.001 时不做延迟处理 */
    @property({ type: Number, caption: "延迟时间（秒）" })
    public delayTime: number = 0;

    // ============ 私有字段 ============

    private _animators: Laya.Animator[] = [];
    private _particle: Laya.ShurikenParticleRenderer = null;

    // ============ 生命周期 ============

    public onEnable(): void {
        this._animators = this.owner.getComponents(Laya.Animator) as Laya.Animator[];
        this._particle = this.owner.getComponent(Laya.ShurikenParticleRenderer);

        if (this.delayTime > 0.001) {
            this._hideEffect();
            Laya.timer.once(this.delayTime * 1000, this, this._playEffect);
        }
    }

    public onDisable(): void {
        if (this.delayTime > 0.001) {
            Laya.timer.clear(this, this._playEffect);
        }
    }

    // ============ 私有方法 ============

    /** 隐藏：所有子节点设为不激活，禁用动画器，暂停粒子 */
    private _hideEffect(): void {
        const count = this.owner.numChildren;
        for (let i = 0; i < count; i++) {
            this.owner.getChildAt(i).active = false;
        }

        for (let i = 0; i < this._animators.length; i++) {
            this._animators[i].enabled = false;
        }

        if (this._particle) {
            this._particle.particleSystem.pause();
        }
    }

    /** 播放：所有子节点设为激活，启用动画器，播放粒子 */
    private _playEffect(): void {
        const count = this.owner.numChildren;
        for (let i = 0; i < count; i++) {
            this.owner.getChildAt(i).active = true;
        }

        for (let i = 0; i < this._animators.length; i++) {
            this._animators[i].enabled = true;
        }

        if (this._particle) {
            this._particle.particleSystem.play();
        }
    }
}
