/**
 * Animator Adapter
 * 动画播放适配器（2D + 3D）
 */

/**
 * 递归查找节点及其子节点上的组件
 * @param target 目标节点
 * @param componentClass 组件类
 * @returns 找到的组件或 null
 */
function findComponentRecursive(target: any, componentClass: any): any {
    if (!target || !componentClass) return null;

    // 先在当前节点查找
    const component = target.getComponent?.(componentClass);
    if (component) return component;

    // 递归查找子节点
    const numChildren = target.numChildren ?? target._children?.length ?? 0;
    for (let i = 0; i < numChildren; i++) {
        const child = target.getChildAt?.(i) ?? target._children?.[i];
        if (child) {
            const found = findComponentRecursive(child, componentClass);
            if (found) return found;
        }
    }

    return null;
}

/**
 * 向上查找父节点上的组件
 * 当 target 指定的节点没有 Animator 时，向上遍历父节点查找
 * @param target 起始节点
 * @param componentClass 组件类
 * @returns 找到的组件或 null
 */
function findComponentInParents(target: any, componentClass: any): any {
    if (!target || !componentClass) return null;

    let current = target;
    while (current) {
        const component = current.getComponent?.(componentClass);
        if (component) return component;
        current = current.parent;
    }

    return null;
}

/**
 * 动画适配器接口
 */
export interface AnimatorAdapter {
    /**
     * 播放动画
     * @param name 动画名称
     * @param fade 淡入时间（秒）
     */
    play(name: string, fade?: number): void;

    /**
     * 停止动画
     */
    stop(): void;

    /**
     * 是否有指定动画
     */
    hasAnimation(name: string): boolean;
}

/**
 * 2D 动画适配器 (Animator2D)
 */
export class Animator2DAdapter implements AnimatorAdapter {
    private animator: any;

    constructor(target: any) {
        const Laya = (window as any).Laya;
        if (Laya?.Animator2D) {
            // 1. 先向上查找（当前节点 → 父节点 → 祖父节点...）
            this.animator = findComponentInParents(target, Laya.Animator2D);
            // 2. 找不到再向下查找（子节点递归）
            if (!this.animator) {
                this.animator = findComponentRecursive(target, Laya.Animator2D);
            }
        }
        // 回退到直接属性
        if (!this.animator) {
            this.animator = target.animator2D || null;
        }
    }

    play(name: string, fade?: number): void {
        if (!this.animator) return;

        // 播放前恢复 speed（stop 后 speed 为 0）
        if (this.animator.speed === 0) {
            this.animator.speed = 1;
        }

        if (fade && fade > 0) {
            this.animator.crossFade?.(name, fade);
        } else {
            this.animator.play?.(name);
        }
    }

    stop(): void {
        // Animator2D 没有直接的 stop，使用空状态或暂停
        if (this.animator?.speed !== undefined) {
            this.animator.speed = 0;
        }
    }

    hasAnimation(name: string): boolean {
        // 简化实现，假设有
        return true;
    }
}

/**
 * 3D 动画适配器 (Animator)
 */
export class Animator3DAdapter implements AnimatorAdapter {
    private animator: any;

    constructor(target: any) {
        const Laya = (window as any).Laya;
        if (Laya?.Animator) {
            // 1. 先向上查找（当前节点 → 父节点 → 祖父节点...）
            this.animator = findComponentInParents(target, Laya.Animator);
            // 2. 找不到再向下查找（子节点递归）
            if (!this.animator) {
                this.animator = findComponentRecursive(target, Laya.Animator);
            }
        }
        // 回退到直接属性
        if (!this.animator) {
            this.animator = target.animator || null;
        }
    }

    play(name: string, fade?: number): void {
        if (!this.animator) return;

        // 播放前恢复 speed（stop 后 speed 为 0）
        if (this.animator.speed === 0) {
            this.animator.speed = 1;
        }

        if (fade && fade > 0) {
            this.animator.crossFade?.(name, fade);
        } else {
            this.animator.play?.(name);
        }
    }

    stop(): void {
        if (this.animator?.speed !== undefined) {
            this.animator.speed = 0;
        }
    }

    hasAnimation(name: string): boolean {
        // 简化实现
        return true;
    }
}

/**
 * 创建动画适配器
 */
export function createAnimatorAdapter(target: any, is3D: boolean): AnimatorAdapter {
    if (is3D) {
        return new Animator3DAdapter(target);
    }
    return new Animator2DAdapter(target);
}
