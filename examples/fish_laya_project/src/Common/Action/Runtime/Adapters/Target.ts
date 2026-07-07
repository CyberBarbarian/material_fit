/**
 * Target Adapter
 * 2D/3D 目标适配器
 */

/**
 * 目标适配器接口
 * 统一 2D 和 3D 对象的属性访问
 */
export interface TargetAdapter {
    /** 是否为 3D 对象 */
    readonly is3D: boolean;

    /** 原始目标对象 */
    readonly raw: any;

    // 位置
    getX(): number;

    getY(): number;

    getZ(): number;

    setX(value: number): void;

    setY(value: number): void;

    setZ(value: number): void;

    // 缩放
    getScaleX(): number;

    getScaleY(): number;

    getScaleZ(): number;

    setScaleX(value: number): void;

    setScaleY(value: number): void;

    setScaleZ(value: number): void;

    // 旋转
    getRotation(): number;

    getRotationX(): number;

    getRotationY(): number;

    getRotationZ(): number;

    setRotation(value: number): void;

    setRotationX(value: number): void;

    setRotationY(value: number): void;

    setRotationZ(value: number): void;

    // 透明度
    getAlpha(): number;

    setAlpha(value: number): void;

    // 可见性
    getVisible(): boolean;

    setVisible(value: boolean): void;

    // 销毁
    destroy(): void;
}

/**
 * 2D 目标适配器 (Laya.Sprite)
 */
export class Target2DAdapter implements TargetAdapter {
    readonly is3D = false;

    constructor(readonly raw: any) {
    }

    getX(): number {
        return this.raw.x || 0;
    }

    getY(): number {
        return this.raw.y || 0;
    }

    getZ(): number {
        return 0;
    }

    setX(value: number): void {
        this.raw.x = value;
    }

    setY(value: number): void {
        this.raw.y = value;
    }

    setZ(value: number): void { /* 2D 忽略 Z */
    }

    getScaleX(): number {
        return this.raw.scaleX ?? 1;
    }

    getScaleY(): number {
        return this.raw.scaleY ?? 1;
    }

    getScaleZ(): number {
        return 1;
    }

    setScaleX(value: number): void {
        this.raw.scaleX = value;
    }

    setScaleY(value: number): void {
        this.raw.scaleY = value;
    }

    setScaleZ(value: number): void { /* 2D 忽略 */
    }

    getRotation(): number {
        return this.raw.rotation || 0;
    }

    getRotationX(): number {
        return 0;
    }

    getRotationY(): number {
        return 0;
    }

    getRotationZ(): number {
        return this.raw.rotation || 0;
    }

    setRotation(value: number): void {
        this.raw.rotation = value;
    }

    setRotationX(value: number): void { /* 2D 忽略 */
    }

    setRotationY(value: number): void { /* 2D 忽略 */
    }

    setRotationZ(value: number): void {
        this.raw.rotation = value;
    }

    getAlpha(): number {
        return this.raw.alpha ?? 1;
    }

    setAlpha(value: number): void {
        this.raw.alpha = value;
    }

    getVisible(): boolean {
        return this.raw.visible !== false;
    }

    setVisible(value: boolean): void {
        this.raw.visible = value;
    }

    destroy(): void {
        if (this.raw.destroy) {
            this.raw.destroy();
        }
    }
}

/**
 * 3D 目标适配器 (Laya.Sprite3D)
 */
export class Target3DAdapter implements TargetAdapter {
    readonly is3D = true;

    constructor(readonly raw: any) {
    }

    private get transform(): any {
        return this.raw.transform;
    }

    getX(): number {
        return this.transform?.localPositionX || 0;
    }

    getY(): number {
        return this.transform?.localPositionY || 0;
    }

    getZ(): number {
        return this.transform?.localPositionZ || 0;
    }

    setX(value: number): void {
        if (this.transform) this.transform.localPositionX = value;
    }

    setY(value: number): void {
        if (this.transform) this.transform.localPositionY = value;
    }

    setZ(value: number): void {
        if (this.transform) this.transform.localPositionZ = value;
    }

    getScaleX(): number {
        return this.transform?.localScaleX ?? 1;
    }

    getScaleY(): number {
        return this.transform?.localScaleY ?? 1;
    }

    getScaleZ(): number {
        return this.transform?.localScaleZ ?? 1;
    }

    setScaleX(value: number): void {
        if (this.transform) this.transform.localScaleX = value;
    }

    setScaleY(value: number): void {
        if (this.transform) this.transform.localScaleY = value;
    }

    setScaleZ(value: number): void {
        if (this.transform) this.transform.localScaleZ = value;
    }

    getRotation(): number {
        return this.getRotationZ();
    }

    getRotationX(): number {
        return this.transform?.localRotationEulerX || 0;
    }

    getRotationY(): number {
        return this.transform?.localRotationEulerY || 0;
    }

    getRotationZ(): number {
        return this.transform?.localRotationEulerZ || 0;
    }

    setRotation(value: number): void {
        this.setRotationZ(value);
    }

    setRotationX(value: number): void {
        if (this.transform) this.transform.localRotationEulerX = value;
    }

    setRotationY(value: number): void {
        if (this.transform) this.transform.localRotationEulerY = value;
    }

    setRotationZ(value: number): void {
        if (this.transform) this.transform.localRotationEulerZ = value;
    }

    getAlpha(): number {
        // 3D 对象可能没有直接的 alpha，尝试从材质获取
        return 1;
    }

    setAlpha(value: number): void {
        // 3D 对象透明度处理较复杂，这里简化处理
    }

    getVisible(): boolean {
        return this.raw.active !== false;
    }

    setVisible(value: boolean): void {
        this.raw.active = value;
    }

    destroy(): void {
        if (this.raw.destroy) {
            this.raw.destroy();
        }
    }
}

/**
 * 检测目标类型并创建适配器
 */
export function createTargetAdapter(target: any): TargetAdapter {
    // 检测是否为 3D 对象（有 transform 属性）
    if (target.transform && typeof target.transform.localPositionX !== "undefined") {
        return new Target3DAdapter(target);
    }
    return new Target2DAdapter(target);
}
