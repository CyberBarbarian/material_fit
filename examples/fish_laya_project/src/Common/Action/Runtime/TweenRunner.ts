/**
 * Tween Runner
 * 封装 Laya.Tween API
 */

import type { ActionController } from "./Controller";
import type { EaseType } from "../Schema/Types";

/**
 * 缓动函数映射
 */
const EASE_FUNCTIONS: Record<EaseType, any> = {
    linear: null, // 将在运行时获取 Laya.Ease
    sineIn: null,
    sineOut: null,
    sineInOut: null,
    quadIn: null,
    quadOut: null,
    quadInOut: null,
    cubicIn: null,
    cubicOut: null,
    cubicInOut: null,
    quartIn: null,
    quartOut: null,
    quartInOut: null,
    quintIn: null,
    quintOut: null,
    quintInOut: null,
    expoIn: null,
    expoOut: null,
    expoInOut: null,
    circIn: null,
    circOut: null,
    circInOut: null,
    backIn: null,
    backOut: null,
    backInOut: null,
    elasticIn: null,
    elasticOut: null,
    elasticInOut: null,
    bounceIn: null,
    bounceOut: null,
    bounceInOut: null,
};

/**
 * 获取缓动函数
 */
function getEaseFunction(ease: EaseType): any {
    const Laya = (window as any).Laya;
    if (!Laya || !Laya.Ease) {
        return null;
    }

    // 懒加载缓动函数
    if (EASE_FUNCTIONS.linear === null) {
        EASE_FUNCTIONS.linear = Laya.Ease.linearNone;
        EASE_FUNCTIONS.sineIn = Laya.Ease.sineIn;
        EASE_FUNCTIONS.sineOut = Laya.Ease.sineOut;
        EASE_FUNCTIONS.sineInOut = Laya.Ease.sineInOut;
        EASE_FUNCTIONS.quadIn = Laya.Ease.quadIn;
        EASE_FUNCTIONS.quadOut = Laya.Ease.quadOut;
        EASE_FUNCTIONS.quadInOut = Laya.Ease.quadInOut;
        EASE_FUNCTIONS.cubicIn = Laya.Ease.cubicIn;
        EASE_FUNCTIONS.cubicOut = Laya.Ease.cubicOut;
        EASE_FUNCTIONS.cubicInOut = Laya.Ease.cubicInOut;
        EASE_FUNCTIONS.quartIn = Laya.Ease.quartIn;
        EASE_FUNCTIONS.quartOut = Laya.Ease.quartOut;
        EASE_FUNCTIONS.quartInOut = Laya.Ease.quartInOut;
        EASE_FUNCTIONS.quintIn = Laya.Ease.quintIn;
        EASE_FUNCTIONS.quintOut = Laya.Ease.quintOut;
        EASE_FUNCTIONS.quintInOut = Laya.Ease.quintInOut;
        EASE_FUNCTIONS.expoIn = Laya.Ease.expoIn;
        EASE_FUNCTIONS.expoOut = Laya.Ease.expoOut;
        EASE_FUNCTIONS.expoInOut = Laya.Ease.expoInOut;
        EASE_FUNCTIONS.circIn = Laya.Ease.circIn;
        EASE_FUNCTIONS.circOut = Laya.Ease.circOut;
        EASE_FUNCTIONS.circInOut = Laya.Ease.circInOut;
        EASE_FUNCTIONS.backIn = Laya.Ease.backIn;
        EASE_FUNCTIONS.backOut = Laya.Ease.backOut;
        EASE_FUNCTIONS.backInOut = Laya.Ease.backInOut;
        EASE_FUNCTIONS.elasticIn = Laya.Ease.elasticIn;
        EASE_FUNCTIONS.elasticOut = Laya.Ease.elasticOut;
        EASE_FUNCTIONS.elasticInOut = Laya.Ease.elasticInOut;
        EASE_FUNCTIONS.bounceIn = Laya.Ease.bounceIn;
        EASE_FUNCTIONS.bounceOut = Laya.Ease.bounceOut;
        EASE_FUNCTIONS.bounceInOut = Laya.Ease.bounceInOut;
    }

    return EASE_FUNCTIONS[ease] || EASE_FUNCTIONS.linear;
}

/**
 * 缓动选项
 */
export interface TweenOptions {
    /** 目标属性值 */
    props: Record<string, number>;
    /** 持续时间 (毫秒) */
    duration: number;
    /** 缓动类型 */
    ease?: EaseType;
}

/**
 * Tween 运行器
 */
export class TweenRunner {
    /** 活跃的 Tween 列表 */
    private activeTweens: any[] = [];

    /** 控制器 */
    private controller: ActionController;

    constructor(controller: ActionController) {
        this.controller = controller;

        // 注册停止回调
        controller.onStop(() => {
            this.clearAll();
        });
    }

    /**
     * 执行缓动
     * @param target 目标对象
     * @param options 缓动选项，duration 单位为毫秒
     */
    async tween(target: any, options: TweenOptions): Promise<void> {
        if (this.controller.stopped) {
            return;
        }

        // duration 已经是毫秒，直接使用
        const durationMs = options.duration;

        const Laya = (window as any).Laya;
        if (!Laya || !Laya.Tween) {
            // 没有 Laya，直接设置属性并等待
            for (const key in options.props) {
                target[key] = options.props[key];
            }
            await this.delayMs(durationMs);
            return;
        }

        return new Promise<void>((resolve) => {
            const ease = getEaseFunction(options.ease || "linear");

            const tween = Laya.Tween.to(
                target,
                options.props,
                durationMs,
                ease,
                Laya.Handler.create(null, () => {
                    this.removeTween(tween);
                    resolve();
                })
            );

            if (tween) {
                this.activeTweens.push(tween);
            } else {
                resolve();
            }
        });
    }

    /**
     * 等待指定时间（毫秒）
     * @param ms 等待时间（毫秒）
     */
    async delay(ms: number): Promise<void> {
        // 已经是毫秒，直接使用
        return this.delayMs(ms);
    }

    /**
     * 清除所有 Tween
     */
    clearAll(): void {
        const Laya = (window as any).Laya;

        for (const tween of this.activeTweens) {
            if (Laya && Laya.Tween) {
                Laya.Tween.clear(tween);
            }
        }

        this.activeTweens.length = 0;
    }

    /**
     * 获取活跃 Tween 数量
     */
    getActiveCount(): number {
        return this.activeTweens.length;
    }

    /**
     * 等待指定时间（毫秒）- 内部方法
     */
    private async delayMs(ms: number): Promise<void> {
        if (this.controller.stopped || ms <= 0) {
            return;
        }

        return new Promise<void>((resolve) => {
            const timer = setTimeout(() => {
                resolve();
            }, ms);

            // 注册停止时清除定时器
            this.controller.onStop(() => {
                clearTimeout(timer);
                resolve();
            });
        });
    }

    /**
     * 移除 Tween
     */
    private removeTween(tween: any): void {
        const index = this.activeTweens.indexOf(tween);
        if (index !== -1) {
            this.activeTweens.splice(index, 1);
        }
    }
}

/**
 * 创建 Tween 运行器
 */
export function createTweenRunner(controller: ActionController): TweenRunner {
    return new TweenRunner(controller);
}
