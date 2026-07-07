/**
 * Tween Action Definitions
 * 缓动类型: moveTo, moveBy, moveToward, scaleTo, scaleBy, rotateTo, rotateBy, fadeTo, wait
 */

import type {
    ActionDefinition,
    Expression,
    FadeToConfig,
    FieldDefinition,
    MoveByConfig,
    MoveToConfig,
    MoveTowardConfig,
    RotateByConfig,
    RotateToConfig,
    RuntimeContext,
    ScaleByConfig,
    ScaleToConfig,
    WaitConfig,
} from "../Types";
import { registry } from "../Registry";

/** target 字段定义（所有叶子 Action 共用） */
const targetField: FieldDefinition = { name: "target", type: "string", required: false };

/**
 * moveTo - 移动到绝对坐标
 */
export const moveToDefinition: ActionDefinition<MoveToConfig> = {
    type: "moveTo",
    category: "tween",
    label: "移动到",

    fields: [
        targetField,
        { name: "x", type: "expression", required: true, default: 0 },
        { name: "y", type: "expression", required: true, default: 0 },
        { name: "z", type: "expression", required: false, default: 0 },
        { name: "duration", type: "expression", required: true, default: 1 },
        { name: "ease", type: "string", required: false, default: "linear" },
    ],

    defaults: {
        type: "moveTo",
        x: 0,
        y: 0,
        duration: 1,
    },

    getDuration(config: MoveToConfig, evalFn: (v: Expression) => number): number {
        // 返回毫秒：配置中 duration 为秒，转换为毫秒
        return evalFn(config.duration) * 1000;
    },

    async execute(config: MoveToConfig, ctx: RuntimeContext): Promise<void> {
        const x = ctx.evalCoord(config.x, "x");
        const y = ctx.evalCoord(config.y, "y");
        const props: Record<string, number> = {};

        if (ctx.is3D) {
            const transform = ctx.target.transform;
            if (transform) {
                props.localPositionX = x;
                props.localPositionY = y;
                if (config.z !== undefined) {
                    props.localPositionZ = ctx.evalCoord(config.z, "z");
                }
                await ctx.tweenRunner.tween(transform, { props, duration: ctx.duration, ease: config.ease });
            }
        } else {
            props.x = x;
            props.y = y;
            await ctx.tweenRunner.tween(ctx.target, { props, duration: ctx.duration, ease: config.ease });
        }
    },
};

/**
 * moveBy - 相对移动
 */
export const moveByDefinition: ActionDefinition<MoveByConfig> = {
    type: "moveBy",
    category: "tween",
    label: "移动",

    fields: [
        targetField,
        { name: "x", type: "expression", required: true, default: 0 },
        { name: "y", type: "expression", required: true, default: 0 },
        { name: "z", type: "expression", required: false, default: 0 },
        { name: "duration", type: "expression", required: true, default: 1 },
        { name: "ease", type: "string", required: false, default: "linear" },
    ],

    defaults: {
        type: "moveBy",
        x: 0,
        y: 0,
        duration: 1,
    },

    getDuration(config: MoveByConfig, evalFn: (v: Expression) => number): number {
        // 返回毫秒：配置中 duration 为秒，转换为毫秒
        return evalFn(config.duration) * 1000;
    },

    async execute(config: MoveByConfig, ctx: RuntimeContext): Promise<void> {
        const dx = ctx.eval(config.x);
        const dy = ctx.eval(config.y);
        const dz = config.z !== undefined ? ctx.eval(config.z) : 0;
        const props: Record<string, number> = {};

        if (ctx.is3D) {
            const transform = ctx.target.transform;
            if (transform) {
                props.localPositionX = transform.localPositionX + dx;
                props.localPositionY = transform.localPositionY + dy;
                props.localPositionZ = transform.localPositionZ + dz;
                await ctx.tweenRunner.tween(transform, { props, duration: ctx.duration, ease: config.ease });
            }
        } else {
            props.x = ctx.target.x + dx;
            props.y = ctx.target.y + dy;
            await ctx.tweenRunner.tween(ctx.target, { props, duration: ctx.duration, ease: config.ease });
        }
    },
};

/**
 * moveToward - 朝向目标移动
 */
export const moveTowardDefinition: ActionDefinition<MoveTowardConfig> = {
    type: "moveToward",
    category: "tween",
    label: "朝向移动",

    fields: [
        targetField,
        { name: "x", type: "expression", required: true, default: 0 },
        { name: "y", type: "expression", required: true, default: 0 },
        { name: "ratio", type: "expression", required: true, default: 1 },
        { name: "duration", type: "expression", required: true, default: 1 },
        { name: "ease", type: "string", required: false, default: "linear" },
    ],

    defaults: {
        type: "moveToward",
        x: 0,
        y: 0,
        ratio: 1,
        duration: 1,
    },

    getDuration(config: MoveTowardConfig, evalFn: (v: Expression) => number): number {
        // 返回毫秒：配置中 duration 为秒，转换为毫秒
        return evalFn(config.duration) * 1000;
    },

    async execute(config: MoveTowardConfig, ctx: RuntimeContext): Promise<void> {
        const targetX = ctx.evalCoord(config.x, "x");
        const targetY = ctx.evalCoord(config.y, "y");
        const ratio = ctx.eval(config.ratio);

        const currentX = ctx.is3D ? ctx.target.transform?.localPositionX ?? 0 : ctx.target.x ?? 0;
        const currentY = ctx.is3D ? ctx.target.transform?.localPositionY ?? 0 : ctx.target.y ?? 0;
        const finalX = currentX + (targetX - currentX) * ratio;
        const finalY = currentY + (targetY - currentY) * ratio;

        const props: Record<string, number> = {};
        if (ctx.is3D) {
            const transform = ctx.target.transform;
            if (transform) {
                props.localPositionX = finalX;
                props.localPositionY = finalY;
                await ctx.tweenRunner.tween(transform, { props, duration: ctx.duration, ease: config.ease });
            }
        } else {
            props.x = finalX;
            props.y = finalY;
            await ctx.tweenRunner.tween(ctx.target, { props, duration: ctx.duration, ease: config.ease });
        }
    },
};

/**
 * scaleTo - 缩放到
 */
export const scaleToDefinition: ActionDefinition<ScaleToConfig> = {
    type: "scaleTo",
    category: "tween",
    label: "缩放到",

    fields: [
        targetField,
        { name: "x", type: "expression", required: true, default: 1 },
        { name: "y", type: "expression", required: true, default: 1 },
        { name: "z", type: "expression", required: false, default: 1 },
        { name: "duration", type: "expression", required: true, default: 1 },
        { name: "ease", type: "string", required: false, default: "linear" },
    ],

    defaults: {
        type: "scaleTo",
        x: 1,
        y: 1,
        duration: 1,
    },

    getDuration(config: ScaleToConfig, evalFn: (v: Expression) => number): number {
        // 返回毫秒：配置中 duration 为秒，转换为毫秒
        return evalFn(config.duration) * 1000;
    },

    async execute(config: ScaleToConfig, ctx: RuntimeContext): Promise<void> {
        const x = ctx.eval(config.x);
        const y = ctx.eval(config.y);
        const props: Record<string, number> = {};

        if (ctx.is3D) {
            const transform = ctx.target.transform;
            if (transform) {
                props.localScaleX = x;
                props.localScaleY = y;
                if (config.z !== undefined) {
                    props.localScaleZ = ctx.eval(config.z);
                }
                await ctx.tweenRunner.tween(transform, { props, duration: ctx.duration, ease: config.ease });
            }
        } else {
            props.scaleX = x;
            props.scaleY = y;
            await ctx.tweenRunner.tween(ctx.target, { props, duration: ctx.duration, ease: config.ease });
        }
    },
};

/**
 * scaleBy - 相对缩放
 */
export const scaleByDefinition: ActionDefinition<ScaleByConfig> = {
    type: "scaleBy",
    category: "tween",
    label: "缩放",

    fields: [
        targetField,
        { name: "x", type: "expression", required: true, default: 1 },
        { name: "y", type: "expression", required: true, default: 1 },
        { name: "z", type: "expression", required: false, default: 1 },
        { name: "duration", type: "expression", required: true, default: 1 },
        { name: "ease", type: "string", required: false, default: "linear" },
    ],

    defaults: {
        type: "scaleBy",
        x: 1,
        y: 1,
        duration: 1,
    },

    getDuration(config: ScaleByConfig, evalFn: (v: Expression) => number): number {
        // 返回毫秒：配置中 duration 为秒，转换为毫秒
        return evalFn(config.duration) * 1000;
    },

    async execute(config: ScaleByConfig, ctx: RuntimeContext): Promise<void> {
        const fx = ctx.eval(config.x);
        const fy = ctx.eval(config.y);
        const props: Record<string, number> = {};

        if (ctx.is3D) {
            const transform = ctx.target.transform;
            if (transform) {
                props.localScaleX = transform.localScaleX * fx;
                props.localScaleY = transform.localScaleY * fy;
                if (config.z !== undefined) {
                    props.localScaleZ = transform.localScaleZ * ctx.eval(config.z);
                }
                await ctx.tweenRunner.tween(transform, { props, duration: ctx.duration, ease: config.ease });
            }
        } else {
            props.scaleX = (ctx.target.scaleX ?? 1) * fx;
            props.scaleY = (ctx.target.scaleY ?? 1) * fy;
            await ctx.tweenRunner.tween(ctx.target, { props, duration: ctx.duration, ease: config.ease });
        }
    },
};

/**
 * rotateTo - 旋转到
 */
export const rotateToDefinition: ActionDefinition<RotateToConfig> = {
    type: "rotateTo",
    category: "tween",
    label: "旋转到",

    fields: [
        targetField,
        { name: "angle", type: "expression", required: true, default: 0 },
        { name: "axis", type: "string", required: false, default: "z" },
        { name: "duration", type: "expression", required: true, default: 1 },
        { name: "ease", type: "string", required: false, default: "linear" },
    ],

    defaults: {
        type: "rotateTo",
        angle: 0,
        duration: 1,
    },

    getDuration(config: RotateToConfig, evalFn: (v: Expression) => number): number {
        // 返回毫秒：配置中 duration 为秒，转换为毫秒
        return evalFn(config.duration) * 1000;
    },

    async execute(config: RotateToConfig, ctx: RuntimeContext): Promise<void> {
        const angle = ctx.eval(config.angle);
        const axis = config.axis || "z";
        const props: Record<string, number> = {};

        if (ctx.is3D) {
            const transform = ctx.target.transform;
            if (transform) {
                const propName = `localRotationEuler${axis.toUpperCase()}`;
                props[propName] = angle;
                await ctx.tweenRunner.tween(transform, { props, duration: ctx.duration, ease: config.ease });
            }
        } else {
            props.rotation = angle;
            await ctx.tweenRunner.tween(ctx.target, { props, duration: ctx.duration, ease: config.ease });
        }
    },
};

/**
 * rotateBy - 相对旋转
 */
export const rotateByDefinition: ActionDefinition<RotateByConfig> = {
    type: "rotateBy",
    category: "tween",
    label: "旋转",

    fields: [
        targetField,
        { name: "angle", type: "expression", required: true, default: 0 },
        { name: "axis", type: "string", required: false, default: "z" },
        { name: "duration", type: "expression", required: true, default: 1 },
        { name: "ease", type: "string", required: false, default: "linear" },
    ],

    defaults: {
        type: "rotateBy",
        angle: 0,
        duration: 1,
    },

    getDuration(config: RotateByConfig, evalFn: (v: Expression) => number): number {
        // 返回毫秒：配置中 duration 为秒，转换为毫秒
        return evalFn(config.duration) * 1000;
    },

    async execute(config: RotateByConfig, ctx: RuntimeContext): Promise<void> {
        const deltaAngle = ctx.eval(config.angle);
        const axis = config.axis || "z";
        const props: Record<string, number> = {};

        if (ctx.is3D) {
            const transform = ctx.target.transform;
            if (transform) {
                const propName = `localRotationEuler${axis.toUpperCase()}`;
                props[propName] = transform[propName] + deltaAngle;
                await ctx.tweenRunner.tween(transform, { props, duration: ctx.duration, ease: config.ease });
            }
        } else {
            props.rotation = (ctx.target.rotation || 0) + deltaAngle;
            await ctx.tweenRunner.tween(ctx.target, { props, duration: ctx.duration, ease: config.ease });
        }
    },
};

/**
 * fadeTo - 淡入淡出
 */
export const fadeToDefinition: ActionDefinition<FadeToConfig> = {
    type: "fadeTo",
    category: "tween",
    label: "淡入淡出",

    fields: [
        targetField,
        { name: "alpha", type: "expression", required: true, default: 1 },
        { name: "duration", type: "expression", required: true, default: 1 },
        { name: "ease", type: "string", required: false, default: "linear" },
    ],

    defaults: {
        type: "fadeTo",
        alpha: 1,
        duration: 1,
    },

    getDuration(config: FadeToConfig, evalFn: (v: Expression) => number): number {
        // 返回毫秒：配置中 duration 为秒，转换为毫秒
        return evalFn(config.duration) * 1000;
    },

    async execute(config: FadeToConfig, ctx: RuntimeContext): Promise<void> {
        const alpha = ctx.eval(config.alpha);
        await ctx.tweenRunner.tween(ctx.target, {
            props: { alpha },
            duration: ctx.duration,
            ease: config.ease,
        });
    },
};

/**
 * wait - 等待
 */
export const waitDefinition: ActionDefinition<WaitConfig> = {
    type: "wait",
    category: "tween",
    label: "等待",

    fields: [
        targetField,
        { name: "duration", type: "expression", required: true, default: 1 },
    ],

    defaults: {
        type: "wait",
        duration: 1,
    },

    getDuration(config: WaitConfig, evalFn: (v: Expression) => number): number {
        // 返回毫秒：配置中 duration 为秒，转换为毫秒
        return evalFn(config.duration) * 1000;
    },

    async execute(config: WaitConfig, ctx: RuntimeContext): Promise<void> {
        await ctx.tweenRunner.delay(ctx.duration);
    },
};

/**
 * 注册所有缓动类型
 */
export function registerTweenDefinitions(): void {
    registry.register(moveToDefinition);
    registry.register(moveByDefinition);
    registry.register(moveTowardDefinition);
    registry.register(scaleToDefinition);
    registry.register(scaleByDefinition);
    registry.register(rotateToDefinition);
    registry.register(rotateByDefinition);
    registry.register(fadeToDefinition);
    registry.register(waitDefinition);
}
