const { regClass, property } = Laya;

/** 背景缩放适配器：让面片铺满相机视野 */
@regClass()
export class BackgroundScaler extends Laya.Script {
    private static readonly TEXTURE_PROPERTY_NAMES: readonly string[] = [
        "u_AlbedoTexture",
        "u_MainTex",
        "u_BaseMap",
        "u_BaseTexture",
        "u_DiffuseTexture"
    ];

    @property(Laya.Camera)
    public camera: Laya.Camera = null;

    @property({ type: Boolean, caption: "保持宽高比" })
    public keepAspectRatio: boolean = false;

    private readonly cameraForward: Laya.Vector3 = new Laya.Vector3();
    private readonly cameraToSprite: Laya.Vector3 = new Laya.Vector3();

    public onEnable(): void {
        Laya.stage.on(Laya.Event.RESIZE, this, this.updateSize);
        Laya.timer.callLater(this, this.updateSize);
    }

    public onDisable(): void {
        Laya.stage.off(Laya.Event.RESIZE, this, this.updateSize);
        Laya.timer.clear(this, this.updateSize);
    }

    private updateSize(): void {
        if (!this.camera || Laya.stage.width <= 0 || Laya.stage.height <= 0) {
            return;
        }
        const sprite = this.owner as Laya.Sprite3D;
        if (!sprite) {
            return;
        }

        const cameraAspectRatio = this.camera.aspectRatio;

        let width: number;
        let height: number;

        if (this.camera.orthographic) {
            height = this.camera.orthographicVerticalSize;
            width = height * cameraAspectRatio;
        } else {
            const distance = this.getDistanceToCamera(sprite);
            if (distance <= 0) {
                return;
            }
            const fovRadians = this.camera.fieldOfView * Math.PI / 180;
            height = 2 * distance * Math.tan(fovRadians / 2);
            width = height * cameraAspectRatio;
        }

        if (this.keepAspectRatio) {
            const textureAspectRatio = this.getTextureAspectRatio(sprite);
            if (textureAspectRatio > 0) {
                if (textureAspectRatio < cameraAspectRatio) {
                    height = width / textureAspectRatio;
                } else {
                    width = height * textureAspectRatio;
                }
            }
        }

        const localScale = sprite.transform.localScale;
        sprite.transform.localScale = new Laya.Vector3(width, height, localScale.z);
    }

    private getDistanceToCamera(sprite: Laya.Sprite3D): number {
        this.camera.transform.getForward(this.cameraForward);
        Laya.Vector3.normalize(this.cameraForward, this.cameraForward);
        Laya.Vector3.subtract(sprite.transform.position, this.camera.transform.position, this.cameraToSprite);
        return Math.abs(Laya.Vector3.dot(this.cameraToSprite, this.cameraForward));
    }

    private getTextureAspectRatio(sprite: Laya.Sprite3D): number {
        const renderer = sprite.getComponent(Laya.MeshRenderer);
        const material = renderer?.sharedMaterial;
        if (!material) {
            return 0;
        }

        for (const propertyName of BackgroundScaler.TEXTURE_PROPERTY_NAMES) {
            const texture = material.getTexture(propertyName) as {
                width: number;
                height: number;
                sourceWidth?: number;
                sourceHeight?: number;
            } | null;
            if (!texture) {
                continue;
            }

            const textureWidth = texture.sourceWidth ?? texture.width;
            const textureHeight = texture.sourceHeight ?? texture.height;
            if (textureWidth > 0 && textureHeight > 0) {
                return textureWidth / textureHeight;
            }
        }

        return 0;
    }
}
