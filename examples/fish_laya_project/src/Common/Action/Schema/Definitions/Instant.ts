/**
 * Instant Action Definitions
 * 即时类型: anim, effect, show, hide, destroy, event
 */

import type {
    ActionDefinition,
    AnimConfig,
    DestroyConfig,
    EffectConfig,
    EventConfig,
    Expression,
    FieldDefinition,
    HideConfig,
    RuntimeContext,
    ShowConfig,
    SoundConfig,
} from "../Types";
import { registry } from "../Registry";

/** target 字段定义（所有叶子 Action 共用） */
const targetField: FieldDefinition = { name: "target", type: "string", required: false };

/**
 * anim - 播放动画
 */
export const animDefinition: ActionDefinition<AnimConfig> = {
    type: "anim",
    category: "instant",
    label: "动画",

    fields: [
        targetField,
        { name: "name", type: "string", required: true },
        { name: "duration", type: "expression", required: false, default: 0 },
        { name: "fade", type: "number", required: false, default: 0 },
        { name: "stop", type: "boolean", required: false, default: false },
    ],

    defaults: {
        type: "anim",
        name: "",
    },

    getDuration(config: AnimConfig, evalFn: (v: Expression) => number): number {
        // anim 是瞬时操作，始终返回 0
        // config.duration 参数已废弃，动画持续时长由动画状态机决定
        return 0;
    },

    async execute(config: AnimConfig, ctx: RuntimeContext): Promise<void> {
        const animator = ctx.createAnimator();
        if (config.stop) {
            animator.stop();
        } else {
            animator.play(config.name, config.fade);
        }
    },
};

/**
 * effect - 播放特效
 */
export const effectDefinition: ActionDefinition<EffectConfig> = {
    type: "effect",
    category: "instant",
    label: "特效",

    fields: [
        targetField,
        { name: "path", type: "string", required: true },
        { name: "x", type: "expression", required: false, default: 0 },
        { name: "y", type: "expression", required: false, default: 0 },
        { name: "z", type: "expression", required: false, default: 0 },
        { name: "parent", type: "string", required: false },
        { name: "duration", type: "number", required: false },
    ],

    defaults: {
        type: "effect",
        path: "",
    },

    getDuration(config: EffectConfig, evalFn: (v: Expression) => number): number {
        // 特效是即时触发，不影响复合类型时长
        return 0;
    },

    async execute(config: EffectConfig, ctx: RuntimeContext): Promise<void> {
        let parent = ctx.target;
        if (config.parent && config.parent !== "/") {
            parent = ctx.findChild(config.parent) || ctx.target;
        }
        await ctx.effectRunner.play(
            {
                path: config.path,
                x: config.x !== undefined ? ctx.evalCoord(config.x, "x") : undefined,
                y: config.y !== undefined ? ctx.evalCoord(config.y, "y") : undefined,
                z: config.z !== undefined ? ctx.evalCoord(config.z, "z") : undefined,
                parent,
                duration: config.duration,
            },
            ctx.target
        );
    },
};

/**
 * event - 触发事件
 */
export const eventDefinition: ActionDefinition<EventConfig> = {
    type: "event",
    category: "instant",
    label: "事件",

    fields: [
        targetField,
        { name: "name", type: "string", required: true },
        { name: "data", type: "object", required: false },
    ],

    defaults: {
        type: "event",
        name: "",
    },

    getDuration(config: EventConfig, evalFn: (v: Expression) => number): number {
        return 0;
    },

    async execute(config: EventConfig, ctx: RuntimeContext): Promise<void> {
        if (ctx.dispatchEvent) {
            ctx.dispatchEvent(config.name, config.data);
        } else if (ctx.target.event) {
            ctx.target.event(config.name, config.data);
        }
    },
};

/**
 * show - 显示
 */
export const showDefinition: ActionDefinition<ShowConfig> = {
    type: "show",
    category: "instant",
    label: "显示",

    fields: [targetField],

    defaults: {
        type: "show",
    },

    getDuration(config: ShowConfig, evalFn: (v: Expression) => number): number {
        return 0;
    },

    async execute(config: ShowConfig, ctx: RuntimeContext): Promise<void> {
        if (ctx.target.visible !== undefined) {
            ctx.target.visible = true;
        } else if (ctx.target.active !== undefined) {
            ctx.target.active = true;
        }
    },
};

/**
 * hide - 隐藏
 */
export const hideDefinition: ActionDefinition<HideConfig> = {
    type: "hide",
    category: "instant",
    label: "隐藏",

    fields: [targetField],

    defaults: {
        type: "hide",
    },

    getDuration(config: HideConfig, evalFn: (v: Expression) => number): number {
        return 0;
    },

    async execute(config: HideConfig, ctx: RuntimeContext): Promise<void> {
        if (ctx.target.visible !== undefined) {
            ctx.target.visible = false;
        } else if (ctx.target.active !== undefined) {
            ctx.target.active = false;
        }
    },
};

/**
 * destroy - 销毁
 */
export const destroyDefinition: ActionDefinition<DestroyConfig> = {
    type: "destroy",
    category: "instant",
    label: "销毁",

    fields: [targetField],

    defaults: {
        type: "destroy",
    },

    getDuration(config: DestroyConfig, evalFn: (v: Expression) => number): number {
        return 0;
    },

    async execute(config: DestroyConfig, ctx: RuntimeContext): Promise<void> {
        if (ctx.target.destroy) {
            ctx.target.destroy();
        }
    },
};

/**
 * sound - 播放音效
 */
export const soundDefinition: ActionDefinition<SoundConfig> = {
    type: "sound",
    category: "instant",
    label: "音效",

    fields: [
        targetField,
        { name: "path", type: "string", required: true },
        { name: "volume", type: "number", required: false, default: 1 },
    ],

    defaults: {
        type: "sound",
        path: "",
    },

    getDuration(config: SoundConfig, evalFn: (v: Expression) => number): number {
        return 0;
    },

    async execute(config: SoundConfig, ctx: RuntimeContext): Promise<void> {
        if (ctx.soundPlayer) {
            ctx.soundPlayer.play(config.path, config.volume ?? 1);
        }
    },
};

/**
 * 注册所有即时类型
 */
export function registerInstantDefinitions(): void {
    registry.register(animDefinition);
    registry.register(effectDefinition);
    registry.register(eventDefinition);
    registry.register(showDefinition);
    registry.register(hideDefinition);
    registry.register(destroyDefinition);
    registry.register(soundDefinition);
}
