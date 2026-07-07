const { regClass, property } = Laya;

@regClass()
export class ShaderTimeUpdater extends Laya.Script {

    @property({ type: String, label: "Shader 变量名", default: "u_CurrentTime" })
    public shaderPropName: string = "u_CurrentTime";

    @property({ type: Number, label: "时间速度倍率", default: 1 })
    public speed: number = 1;

    private _mat: Laya.Material | null = null;
    private _time: number = 0;
    private _propIndex: number = -1;

    onEnable(): void {
        const sprite = this.owner as any;
        const mat = sprite._renderNode?.sharedMaterials?.[0]
            ?? sprite._renderNode?._materials?.[0]
            ?? null;

        if (!mat) {
            console.warn(`[ShaderTimeUpdater] "${this.owner.name}" 未找到材质`);
            return;
        }

        this._mat = mat;
        this._time = 0;
        this._propIndex = Laya.Shader3D.propertyNameToID(this.shaderPropName);
    }

    onUpdate(): void {
        if (!this._mat || this._propIndex === -1) return;
        this._time += (Laya.timer.delta / 1000) * this.speed;
        this._mat.shaderData?.setNumber(this._propIndex, this._time);
    }

    onDisable(): void {
        this._mat = null;
        this._propIndex = -1;
    }
}