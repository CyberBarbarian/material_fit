const { regClass, property } = Laya;

/** 屏幕尺寸变化时，正交相机视野按像素比例同步更新。*/
@regClass()
export class OrthoCameraScaler extends Laya.Script {
    @property(Number)
    public pixelsPerUnit: number = 100;

    public onEnable(): void {
        Laya.stage.on(Laya.Event.RESIZE, this, this.refreshCameraSize);
        Laya.timer.callLater(this, this.refreshCameraSize);
    }

    public onDisable(): void {
        Laya.stage.off(Laya.Event.RESIZE, this, this.refreshCameraSize);
        Laya.timer.clear(this, this.refreshCameraSize);
    }

    private refreshCameraSize(): void {
        const camera = this.owner as Laya.Camera;
        if (!camera || !camera.orthographic || this.pixelsPerUnit <= 0) {
            return;
        }

        camera.orthographicVerticalSize = Laya.stage.height / this.pixelsPerUnit;
    }
}
