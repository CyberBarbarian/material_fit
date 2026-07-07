const { regClass, property } = Laya;

/** 每帧按固定欧拉角旋转节点 */
@regClass()
export class EffectRotate extends Laya.Script3D {

    @property({ type: Laya.Vector3, caption: "每帧旋转角度" })
    public rotate: Laya.Vector3 = new Laya.Vector3(0, 0, 0);

    onUpdate(): void {
        const globalAny = globalThis as any;
        if (globalAny.__MATERIAL_FIT_DISABLE_EFFECT_ROTATE__ !== false) {
            return;
        }
        (this.owner as Laya.Sprite3D).transform.rotate(this.rotate, false, false);
    }
}
