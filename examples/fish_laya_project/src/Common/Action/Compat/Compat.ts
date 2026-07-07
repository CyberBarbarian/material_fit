/**
 * Action 函数式 API
 *
 * @example
 * ```typescript
 * import { play, seq, moveTo, wait, call } from "../../Common/Action";
 *
 * const ctrl = play(seq(
 *     moveTo(1, 100, 200),
 *     wait(0.5),
 *     call(() => console.log("done"))
 * ), sprite);
 *
 * ctrl.stop();
 * await ctrl.done;
 * ```
 */


// ============================================================================
// 类型定义
// ============================================================================

/** 动画目标类型（支持 2D 和 3D） */
export type AnimTarget = Laya.Sprite | Laya.Sprite3D;

/** 可播放单元接口 */
export interface IPlayable {
    play(target: AnimTarget, ctrl: Controller): Promise<void>;
}

/** 播放选项 */
export interface PlayOptions {
    animator?: Laya.Animator;
}

/**
 * 缓动常量表
 */
export const EaseType = {
    linear: "linear",
    sineIn: "sineIn",
    sineOut: "sineOut",
    sineInOut: "sineInOut",
    quadIn: "quadIn",
    quadOut: "quadOut",
    quadInOut: "quadInOut",
    cubicIn: "cubicIn",
    cubicOut: "cubicOut",
    cubicInOut: "cubicInOut",
    quartIn: "quartIn",
    quartOut: "quartOut",
    quartInOut: "quartInOut",
    quintIn: "quintIn",
    quintOut: "quintOut",
    quintInOut: "quintInOut",
    expoIn: "expoIn",
    expoOut: "expoOut",
    expoInOut: "expoInOut",
    circIn: "circIn",
    circOut: "circOut",
    circInOut: "circInOut",
    elasticIn: "elasticIn",
    elasticOut: "elasticOut",
    elasticInOut: "elasticInOut",
    backIn: "backIn",
    backOut: "backOut",
    backInOut: "backInOut",
    bounceIn: "bounceIn",
    bounceOut: "bounceOut",
    bounceInOut: "bounceInOut"
} as const;

export type EaseType = typeof EaseType[keyof typeof EaseType];

/**
 * 播放控制器
 */
export class Controller {
    public stopped = false;
    public done: Promise<void>;
    public animator?: Laya.Animator;

    private _resolve!: () => void;
    private _stopCallbacks = new Set<() => void>();

    constructor() {
        this.done = new Promise(resolve => {
            this._resolve = resolve;
        });
    }

    public stop(): void {
        if (this.stopped) return;
        this.stopped = true;

        for (const fn of this._stopCallbacks) {
            fn();
        }
        this._stopCallbacks.clear();
    }

    public _complete(): void {
        this._resolve();
    }

    public _onStop(fn: () => void): () => void {
        if (this.stopped) {
            fn();
            return () => {
            };
        }
        this._stopCallbacks.add(fn);
        return () => this._stopCallbacks.delete(fn);
    }
}

// ============================================================================
// play() - 兼容入口
// ============================================================================

/**
 * 播放动画
 * @param action 可播放单元
 * @param target 目标节点
 * @param options 选项
 * @returns Controller
 */
export function play(action: IPlayable, target: AnimTarget, options?: PlayOptions): Controller {
    const ctrl = new Controller();

    if (options?.animator) {
        ctrl.animator = options.animator;
    }

    if (!target || (target as any).destroyed) {
        ctrl._complete();
        return ctrl;
    }

    action.play(target, ctrl)
        .then(() => ctrl._complete())
        .catch(e => {
            console.error("[Action.Compat]", e);
            ctrl._complete();
        });

    return ctrl;
}

// ============================================================================
// 容器动作
// ============================================================================

/** 顺序执行 */
export function seq(...actions: IPlayable[]): IPlayable {
    return {
        async play(target, ctrl) {
            for (const action of actions) {
                if (ctrl.stopped) break;
                await action.play(target, ctrl);
            }
        }
    };
}

/** 并行执行 */
export function spawn(...actions: IPlayable[]): IPlayable {
    return {
        async play(target, ctrl) {
            await Promise.all(actions.map(a => a.play(target, ctrl).catch(e => {
                console.error("[Action.Compat] spawn error:", e);
            })));
        }
    };
}

/** 重复执行 */
export function repeat(count: number, action: IPlayable): IPlayable {
    return {
        async play(target, ctrl) {
            for (let i = 0; i < count; i++) {
                if (ctrl.stopped) break;
                await action.play(target, ctrl);
            }
        }
    };
}

// ============================================================================
// 辅助函数
// ============================================================================

/** 判断是否为 3D 对象 */
function is3D(target: AnimTarget): target is Laya.Sprite3D {
    return target && "transform" in target && !!(target as any).transform?.localPosition;
}

/** 获取缓动函数 */
function getEaseFunction(ease?: EaseType): any {
    if (!ease) return null;
    const Ease = Laya.Ease;
    if (!Ease) return null;

    const map: Record<string, any> = {
        linear: Ease.linear,
        sineIn: Ease.sineIn,
        sineOut: Ease.sineOut,
        sineInOut: Ease.sineInOut,
        quadIn: Ease.quadIn,
        quadOut: Ease.quadOut,
        quadInOut: Ease.quadInOut,
        cubicIn: Ease.cubicIn,
        cubicOut: Ease.cubicOut,
        cubicInOut: Ease.cubicInOut,
        quartIn: Ease.quartIn,
        quartOut: Ease.quartOut,
        quartInOut: Ease.quartInOut,
        quintIn: Ease.quintIn,
        quintOut: Ease.quintOut,
        quintInOut: Ease.quintInOut,
        expoIn: Ease.expoIn,
        expoOut: Ease.expoOut,
        expoInOut: Ease.expoInOut,
        circIn: Ease.circIn,
        circOut: Ease.circOut,
        circInOut: Ease.circInOut,
        backIn: Ease.backIn,
        backOut: Ease.backOut,
        backInOut: Ease.backInOut,
        elasticIn: Ease.elasticIn,
        elasticOut: Ease.elasticOut,
        elasticInOut: Ease.elasticInOut,
        bounceIn: Ease.bounceIn,
        bounceOut: Ease.bounceOut,
        bounceInOut: Ease.bounceInOut,
    };

    return map[ease] || null;
}

/** 执行 Tween */
function runTween(
    ctrl: Controller,
    tweenTarget: object,
    owner: AnimTarget,
    duration: number,
    property: string,
    endValue: any,
    ease?: EaseType
): Promise<void> {
    return new Promise<void>(resolve => {
        let finished = false;
        const finish = () => {
            if (finished) return;
            finished = true;
            off();
            resolve();
        };

        // duration 单位是秒，Laya.Tween 期望毫秒
        const tween = Laya.Tween.create(tweenTarget, owner)
            .duration(duration * 1000)
            .to(property, endValue);

        if (ease) tween.ease(ease);
        tween.then(finish);

        const off = ctrl._onStop(() => {
            tween.kill(false);
            finish();
        });
    });
}

/** 执行 2D 多属性 Tween */
function runTween2D(
    ctrl: Controller,
    target: Laya.Sprite,
    duration: number,
    props: Record<string, number>,
    ease?: EaseType
): Promise<void> {
    return new Promise<void>(resolve => {
        let finished = false;
        const finish = () => {
            if (finished) return;
            finished = true;
            off();
            resolve();
        };

        // duration 单位是秒，Laya.Tween 期望毫秒
        const tween = Laya.Tween.create(target, target).duration(duration * 1000);
        for (const key of Object.keys(props)) {
            tween.to(key, props[key]);
        }

        if (ease) tween.ease(ease);
        tween.then(finish);

        const off = ctrl._onStop(() => {
            tween.kill(false);
            finish();
        });
    });
}

// ============================================================================
// Tween 动作
// ============================================================================

/** 移动到绝对坐标 */
export function moveTo(
    duration: number,
    x: number,
    y: number,
    z: number = 0,
    ease?: EaseType
): IPlayable {
    return {
        play(target, ctrl) {
            if (ctrl.stopped || !target) return Promise.resolve();

            if (is3D(target)) {
                const transform = target.transform;
                const end = new Laya.Vector3(x, y, z);

                if (!isFinite(duration) || duration <= 0) {
                    transform.localPosition = end;
                    return Promise.resolve();
                }
                return runTween(ctrl, transform, target, duration, "localPosition", end, ease);
            } else {
                if (!isFinite(duration) || duration <= 0) {
                    target.x = x;
                    target.y = y;
                    return Promise.resolve();
                }
                return runTween2D(ctrl, target, duration, { x, y }, ease);
            }
        }
    };
}

/** 相对移动 */
export function moveBy(
    duration: number,
    x: number,
    y: number,
    z: number = 0,
    ease?: EaseType
): IPlayable {
    return {
        play(target, ctrl) {
            if (ctrl.stopped || !target) return Promise.resolve();

            if (is3D(target)) {
                const pos = target.transform.localPosition;
                return moveTo(duration, pos.x + x, pos.y + y, pos.z + z, ease).play(target, ctrl);
            } else {
                return moveTo(duration, target.x + x, target.y + y, 0, ease).play(target, ctrl);
            }
        }
    };
}

/** 朝向目标移动 */
export function moveToward(
    duration: number,
    targetX: number,
    targetY: number,
    ratio: number,
    ease?: EaseType
): IPlayable {
    return {
        play(target, ctrl) {
            if (ctrl.stopped || !target) return Promise.resolve();

            if (is3D(target)) {
                const pos = target.transform.localPosition;
                const endX = pos.x + (targetX - pos.x) * ratio;
                const endY = pos.y + (targetY - pos.y) * ratio;
                return moveTo(duration, endX, endY, pos.z, ease).play(target, ctrl);
            } else {
                const endX = target.x + (targetX - target.x) * ratio;
                const endY = target.y + (targetY - target.y) * ratio;
                return moveTo(duration, endX, endY, 0, ease).play(target, ctrl);
            }
        }
    };
}

/** 缩放到 */
export function scaleTo(
    duration: number,
    x: number,
    y: number,
    z?: number,
    ease?: EaseType
): IPlayable {
    return {
        play(target, ctrl) {
            if (ctrl.stopped || !target) return Promise.resolve();

            if (is3D(target)) {
                const transform = target.transform;
                const end = new Laya.Vector3(x, y, z ?? 1);

                if (!isFinite(duration) || duration <= 0) {
                    transform.localScale = end;
                    return Promise.resolve();
                }
                return runTween(ctrl, transform, target, duration, "localScale", end, ease);
            } else {
                if (!isFinite(duration) || duration <= 0) {
                    target.scaleX = x;
                    target.scaleY = y;
                    return Promise.resolve();
                }
                return runTween2D(ctrl, target, duration, { scaleX: x, scaleY: y }, ease);
            }
        }
    };
}

/** 相对缩放 */
export function scaleBy(
    duration: number,
    x: number,
    y: number,
    z?: number,
    ease?: EaseType
): IPlayable {
    return {
        play(target, ctrl) {
            if (ctrl.stopped || !target) return Promise.resolve();

            if (is3D(target)) {
                const scale = target.transform.localScale;
                return scaleTo(duration, scale.x * x, scale.y * y, scale.z * (z ?? 1), ease).play(target, ctrl);
            } else {
                return scaleTo(duration, (target.scaleX ?? 1) * x, (target.scaleY ?? 1) * y, undefined, ease).play(target, ctrl);
            }
        }
    };
}

/** 旋转到 */
export function rotateTo(
    duration: number,
    angle: number,
    axis: "x" | "y" | "z" = "z",
    ease?: EaseType
): IPlayable {
    return {
        play(target, ctrl) {
            if (ctrl.stopped || !target) return Promise.resolve();

            if (is3D(target)) {
                const transform = target.transform;
                const euler = transform.localRotationEuler.clone();

                if (axis === "x") euler.x = angle;
                else if (axis === "y") euler.y = angle;
                else euler.z = angle;

                if (!isFinite(duration) || duration <= 0) {
                    transform.localRotationEuler = euler;
                    return Promise.resolve();
                }
                return runTween(ctrl, transform, target, duration, "localRotationEuler", euler, ease);
            } else {
                if (!isFinite(duration) || duration <= 0) {
                    target.rotation = angle;
                    return Promise.resolve();
                }
                return runTween2D(ctrl, target, duration, { rotation: angle }, ease);
            }
        }
    };
}

/** 相对旋转 */
export function rotateBy(
    duration: number,
    angle: number,
    axis: "x" | "y" | "z" = "z",
    ease?: EaseType
): IPlayable {
    return {
        play(target, ctrl) {
            if (ctrl.stopped || !target) return Promise.resolve();

            if (is3D(target)) {
                const euler = target.transform.localRotationEuler;
                let current = 0;
                if (axis === "x") current = euler.x;
                else if (axis === "y") current = euler.y;
                else current = euler.z;
                return rotateTo(duration, current + angle, axis, ease).play(target, ctrl);
            } else {
                return rotateTo(duration, (target.rotation || 0) + angle, axis, ease).play(target, ctrl);
            }
        }
    };
}

/** 淡入淡出 */
export function fadeTo(
    duration: number,
    alpha: number,
    ease?: EaseType
): IPlayable {
    return {
        play(target, ctrl) {
            if (ctrl.stopped || !target) return Promise.resolve();

            if (!isFinite(duration) || duration <= 0) {
                (target as any).alpha = alpha;
                return Promise.resolve();
            }

            return runTween2D(ctrl, target as Laya.Sprite, duration, { alpha }, ease);
        }
    };
}

/** 等待 */
export function wait(duration: number): IPlayable {
    return {
        play(target, ctrl) {
            if (ctrl.stopped || !isFinite(duration) || duration <= 0) {
                return Promise.resolve();
            }

            return new Promise<void>(resolve => {
                // duration 单位是秒，setTimeout 期望毫秒
                const timer = setTimeout(() => resolve(), duration * 1000);
                ctrl._onStop(() => {
                    clearTimeout(timer);
                    resolve();
                });
            });
        }
    };
}

/** 数值动画 */
export function valueTo(
    duration: number,
    from: number,
    to: number,
    onUpdate: (value: number) => void,
    ease?: EaseType
): IPlayable {
    return {
        play(target, ctrl) {
            if (ctrl.stopped || !target) return Promise.resolve();

            if (!isFinite(duration) || duration <= 0) {
                onUpdate(to);
                return Promise.resolve();
            }

            const proxy = { value: from };
            const updateTick = () => onUpdate(proxy.value);
            let stopped = false;

            const offFlag = ctrl._onStop(() => {
                stopped = true;
            });

            Laya.timer.frameLoop(1, target, updateTick);
            onUpdate(from);

            const cleanup = () => {
                offFlag();
                Laya.timer.clear(target, updateTick);
            };

            return runTween(ctrl, proxy, target, duration, "value", to, ease).then(
                () => {
                    if (!stopped) onUpdate(to);
                    cleanup();
                },
                (err) => {
                    cleanup();
                    throw err;
                }
            );
        }
    };
}

// ============================================================================
// 即时动作
// ============================================================================

/** 播放动画 */
export function anim(name: string, fade?: number, stop?: boolean): IPlayable {
    return {
        play(target, ctrl) {
            if (ctrl.stopped || !target) return Promise.resolve();

            // 查找 Animator
            let animator: Laya.Animator | null = ctrl.animator || null;
            if (!animator) {
                animator = findAnimator(target);
            }

            if (!animator) return Promise.resolve();

            if (stop) {
                animator.speed = 0;
            } else if (fade && fade > 0) {
                animator.crossFade?.(name, fade);
            } else {
                animator.play?.(name);
            }

            return Promise.resolve();
        }
    };
}

/** 播放特效 */
export function effect(
    path: string,
    options?: {
        duration?: number;
        parent?: string;
        position?: [number, number, number];
    }
): IPlayable {
    return {
        play(target, ctrl) {
            if (ctrl.stopped) return Promise.resolve();

            const duration = options?.duration ?? 0;
            const parentPath = options?.parent ?? "/";
            const position = options?.position ?? [0, 0, 0];

            let effectNode: Laya.Sprite3D | null = null;
            let timerHandler: (() => void) | null = null;

            const destroyEffect = () => {
                if (timerHandler) {
                    Laya.timer.clear(null, timerHandler);
                    timerHandler = null;
                }
                if (effectNode && !effectNode.destroyed) {
                    effectNode.destroy();
                }
                effectNode = null;
            };

            const off = ctrl._onStop(destroyEffect);

            return new Promise<void>(async resolve => {
                try {
                    const parent = findParentNode(target, parentPath);
                    if (!parent || (parent as any).destroyed) {
                        off();
                        resolve();
                        return;
                    }

                    const prefab = await Laya.loader.load(path, Laya.Loader.HIERARCHY) as Laya.Prefab;
                    const instance = prefab?.create() as Laya.Sprite3D ?? null;
                    if (instance) {
                        instance.transform.localPosition = new Laya.Vector3(...position);
                        parent.addChild(instance);
                    }

                    if (ctrl.stopped || !instance) {
                        off();
                        resolve();
                        return;
                    }

                    effectNode = instance;

                    if (duration > 0) {
                        timerHandler = () => {
                            destroyEffect();
                            off();
                        };
                        // duration 单位是秒
                        Laya.timer.once(duration * 1000, null, timerHandler);
                    }

                    resolve();
                } catch {
                    off();
                    resolve();
                }
            });
        }
    };
}

/** 执行回调 */
export function call(fn: (target: AnimTarget, ctrl: Controller) => void | Promise<void>): IPlayable {
    return {
        async play(target, ctrl) {
            if (ctrl.stopped) return;
            await fn(target, ctrl);
        }
    };
}

/** 触发事件 */
export function event(name: string, data?: any): IPlayable {
    return {
        play(target, ctrl) {
            if (ctrl.stopped || !target) return Promise.resolve();

            if ((target as any).event) {
                (target as any).event(name, data);
            }

            return Promise.resolve();
        }
    };
}

/** 显示 */
export function show(): IPlayable {
    return {
        play(target, ctrl) {
            if (ctrl.stopped || !target) return Promise.resolve();

            if (is3D(target)) {
                target.active = true;
            } else {
                target.visible = true;
            }

            return Promise.resolve();
        }
    };
}

/** 隐藏 */
export function hide(): IPlayable {
    return {
        play(target, ctrl) {
            if (ctrl.stopped || !target) return Promise.resolve();

            if (is3D(target)) {
                target.active = false;
            } else {
                target.visible = false;
            }

            return Promise.resolve();
        }
    };
}

/** 销毁 */
export function destroy(): IPlayable {
    return {
        play(target, ctrl) {
            if (ctrl.stopped || !target) return Promise.resolve();
            target.destroy();
            return Promise.resolve();
        }
    };
}

/** 播放音效 */
export function sound(path: string, volume: number = 1): IPlayable {
    return {
        play(_target, ctrl) {
            if (ctrl.stopped) return Promise.resolve();
            const channel = Laya.SoundManager.playSound(path, 1);
            if (channel && volume !== 1) channel.volume = volume;
            return Promise.resolve();
        }
    };
}

// ============================================================================
// 辅助函数
// ============================================================================

/** 查找 Animator 组件 */
function findAnimator(node: AnimTarget): Laya.Animator | null {
    if (is3D(node)) {
        const animator = node.getComponent(Laya.Animator);
        if (animator) return animator;

        for (let i = 0; i < node.numChildren; i++) {
            const child = node.getChildAt(i) as Laya.Sprite3D;
            const result = findAnimator(child);
            if (result) return result;
        }
    }
    return null;
}

/** 查找父节点 */
function findParentNode(target: AnimTarget, path: string): AnimTarget | null {
    if (path === "/") return target;

    let node: Laya.Node = target;
    const parts = path.split("/").filter(p => p.length > 0);

    for (const part of parts) {
        node = node.getChildByName(part) as Laya.Node;
        if (!node) return null;
    }

    return node as AnimTarget;
}
