/**
 * Effect Adapter
 * 特效播放适配器
 */

import type { ActionController } from "../Controller";

/**
 * 特效实例
 */
export interface EffectInstance {
    /** 特效节点 */
    node: any;

    /** 停止特效 */
    stop(): void;

    /** 销毁特效 */
    destroy(): void;
}

/**
 * 特效选项
 */
export interface EffectOptions {
    /** 特效资源路径 */
    path: string;
    /** X 坐标 */
    x?: number;
    /** Y 坐标 */
    y?: number;
    /** Z 坐标 */
    z?: number;
    /** 父节点（默认为目标节点） */
    parent?: any;
    /** 持续时间（秒，0 表示跟随特效本身时长） */
    duration?: number;
}

/**
 * 特效运行器
 */
export class EffectRunner {
    /** 活跃的特效实例 */
    private activeEffects: EffectInstance[] = [];

    /** 控制器 */
    private controller: ActionController;

    constructor(controller: ActionController) {
        this.controller = controller;

        // 注册停止回调
        controller.onStop(() => {
            this.stopAll();
        });
    }

    /**
     * 播放特效
     */
    async play(options: EffectOptions, defaultParent: any): Promise<void> {
        if (this.controller.stopped) {
            return;
        }

        try {
            // 加载特效资源
            const effectNode = await this.loadEffect(options.path);
            if (!effectNode || this.controller.stopped) {
                return;
            }

            // 设置位置（3D 使用 transform.localPosition）
            if (effectNode.transform) {
                // 3D 节点
                if (options.x !== undefined) effectNode.transform.localPositionX = options.x;
                if (options.y !== undefined) effectNode.transform.localPositionY = options.y;
                if (options.z !== undefined) effectNode.transform.localPositionZ = options.z;
            } else {
                // 2D 节点
                if (options.x !== undefined) effectNode.x = options.x;
                if (options.y !== undefined) effectNode.y = options.y;
            }

            // 添加到父节点
            const parent = options.parent || defaultParent;
            if (parent && parent.addChild) {
                parent.addChild(effectNode);
            }

            // 创建实例
            const instance: EffectInstance = {
                node: effectNode,
                stop: () => {
                    // 停止粒子等
                    if (effectNode.particleSystem) {
                        effectNode.particleSystem.stop();
                    }
                },
                destroy: () => {
                    if (effectNode.destroy) {
                        effectNode.destroy();
                    }
                },
            };

            this.activeEffects.push(instance);

            // 如果有持续时间，设置自动销毁（duration 单位为秒，需要转换为毫秒）
            if (options.duration && options.duration > 0) {
                setTimeout(() => {
                    this.removeEffect(instance);
                }, options.duration * 1000);
            }
        } catch (e) {
            console.error(`[EffectRunner] 播放特效失败: ${options.path}`, e);
        }
    }

    /**
     * 停止所有特效
     */
    stopAll(): void {
        for (const effect of this.activeEffects) {
            effect.stop();
            effect.destroy();
        }
        this.activeEffects.length = 0;
    }

    /**
     * 获取活跃特效数量
     */
    getActiveCount(): number {
        return this.activeEffects.length;
    }

    /**
     * 加载特效资源
     */
    private async loadEffect(path: string): Promise<any> {
        try {
            return await Laya.Prefab.instantiate(path);
        } catch (e) {
            console.error(`[EffectRunner] 加载特效失败: ${path}`, e);
            return null;
        }
    }

    /**
     * 移除特效实例
     */
    private removeEffect(instance: EffectInstance): void {
        const index = this.activeEffects.indexOf(instance);
        if (index !== -1) {
            this.activeEffects.splice(index, 1);
            instance.destroy();
        }
    }
}

/**
 * 创建特效运行器
 */
export function createEffectRunner(controller: ActionController): EffectRunner {
    return new EffectRunner(controller);
}
