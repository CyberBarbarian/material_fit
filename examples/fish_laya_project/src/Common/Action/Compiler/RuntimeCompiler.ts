/**
 * 运行时编译器
 * 将 JSON 配置编译为运行时执行计划
 */

import type { ActionConfig, Diagnostic } from "../Schema/Types";
import { registry } from "../Schema/Registry";
import type { ExpressionEngine } from "../Expression/Engine";
import type { RepeatNode, RuntimeNode, RuntimePlan, SeqNode, SpawnNode } from "./RuntimePlan";

/**
 * 运行时编译选项
 */
export interface RuntimeCompileOptions {
    /** 表达式引擎 */
    engine: ExpressionEngine;
}

/**
 * 运行时编译结果
 */
export interface RuntimeCompileResult {
    /** 运行时计划 */
    plan: RuntimePlan;
    /** 诊断信息 */
    diagnostics: Diagnostic[];
}

/**
 * 编译上下文
 */
interface CompileContext {
    engine: ExpressionEngine;
    diagnostics: Diagnostic[];
    nodeIdCounter: number;
    /** defaults 定义（别名和前缀） */
    defaults: Record<string, string>;
}

/**
 * 简写配置输入类型
 */
type ShorthandConfig = any[] | { [key: string]: any };

/**
 * 完整 JSON 配置
 */
export interface ActionJsonConfig {
    variables?: Record<string, any>;
    defaults?: Record<string, string>;
    action: ShorthandConfig;
}

/**
 * 编译 Action JSON 配置为运行时计划
 * @param json 完整的 JSON 配置（包含 variables、def、action）
 * @param options 编译选项
 * @returns 编译结果
 */
export function compileToRuntime(json: ActionJsonConfig, options: RuntimeCompileOptions): RuntimeCompileResult {
    // 设置变量
    if (json.variables) {
        for (const key of Object.keys(json.variables)) {
            options.engine.setVariable(key, json.variables[key]);
        }
    }

    const ctx: CompileContext = {
        engine: options.engine,
        diagnostics: [],
        nodeIdCounter: 0,
        defaults: json.defaults || {},
    };

    const rootNode = parseAction(json.action, "", ctx);
    const plan: RuntimePlan = {
        root: rootNode,
        totalDuration: rootNode.duration,
        nodeCount: ctx.nodeIdCounter,
    };

    return {
        plan,
        diagnostics: ctx.diagnostics,
    };
}

/**
 * 解析 action 配置（支持简写格式）
 */
function parseAction(config: ShorthandConfig, path: string, ctx: CompileContext): RuntimeNode {
    const nodeId = ctx.nodeIdCounter++;

    // 数组格式
    if (Array.isArray(config) && config.length > 0) {
        // 简写数组 ["type", ...args] - 第一个元素是字符串
        if (typeof config[0] === "string") {
            return parseShorthand(config as any[], path, nodeId, ctx);
        }
        // 否则是 seq（元素可以是数组或对象）
        return compileSeq(config as any[], path, nodeId, ctx);
    }

    // 对象格式
    if (typeof config === "object" && !Array.isArray(config)) {
        // spawn: {"spawn": [...]}
        if ("spawn" in config) {
            return compileSpawn(config.spawn as any[], path, nodeId, ctx);
        }

        // repeat: {"repeat:N": action} 或 {"repeat:$var": action}
        const repeatKey = Object.keys(config).find(k => k.startsWith("repeat:"));
        if (repeatKey) {
            const countStr = repeatKey.slice(7); // "repeat:".length = 7
            const count = countStr.startsWith("$") ? countStr : parseInt(countStr, 10);
            return compileRepeat(config[repeatKey], count, path, nodeId, ctx);
        }
    }

    ctx.diagnostics.push({
        severity: "error",
        message: `Unknown config format: ${JSON.stringify(config)}`,
        path: path || "root",
    });

    return {
        id: nodeId,
        type: "seq",
        config: { type: "seq", actions: [] } as any,
        duration: 0,
        path: path || "root",
        children: [],
    } as SeqNode;
}

/**
 * 编译 seq 节点
 */
function compileSeq(actions: any[], path: string, nodeId: number, ctx: CompileContext): SeqNode {
    const children: RuntimeNode[] = [];
    let totalDuration = 0;

    for (let i = 0; i < actions.length; i++) {
        const childPath = path ? `${path}[${i}]` : `[${i}]`;
        const child = parseAction(actions[i], childPath, ctx);
        children.push(child);
        totalDuration += child.duration;
    }

    return {
        id: nodeId,
        type: "seq",
        config: { type: "seq", actions: [] } as any,
        duration: totalDuration,
        path: path || "root",
        children,
    };
}

/**
 * 编译 spawn 节点
 */
function compileSpawn(actions: any[], path: string, nodeId: number, ctx: CompileContext): SpawnNode {
    const children: RuntimeNode[] = [];
    let maxDuration = 0;

    for (let i = 0; i < actions.length; i++) {
        const childPath = path ? `${path}.spawn[${i}]` : `spawn[${i}]`;
        const child = parseAction(actions[i], childPath, ctx);
        children.push(child);
        maxDuration = Math.max(maxDuration, child.duration);
    }

    return {
        id: nodeId,
        type: "spawn",
        config: { type: "spawn", actions: [] } as any,
        duration: maxDuration,
        path: path || "root",
        children,
    };
}

/**
 * 编译 repeat 节点
 */
function compileRepeat(
    action: ShorthandConfig,
    count: number | string,
    path: string,
    nodeId: number,
    ctx: CompileContext
): RepeatNode {
    // 求值 count（支持变量）
    const countValue = typeof count === "string"
        ? Math.floor(ctx.engine.eval(count))
        : count;

    const childPath = path ? `${path}.repeat` : "repeat";
    const child = parseAction(action, childPath, ctx);

    return {
        id: nodeId,
        type: "repeat",
        config: { type: "repeat", count: countValue, action: {} } as any,
        duration: child.duration * countValue,
        path: path || "root",
        count: countValue,
        child,
    };
}

/**
 * 解析简写数组 ["type", ...args]
 */
function parseShorthand(arr: any[], path: string, nodeId: number, ctx: CompileContext): RuntimeNode {
    let idx = 0;
    let target: string | undefined;

    // 检查 @target 前缀
    if (typeof arr[0] === "string" && arr[0].startsWith("@")) {
        const alias = arr[0].slice(1);
        // 从 def 中查找，如果没有则直接使用路径
        target = ctx.defaults[alias] || alias;
        idx = 1;
    }

    const type = arr[idx];
    const args = arr.slice(idx + 1);

    let config: ActionConfig;

    switch (type) {
        case "wait":
            config = { type: "wait", duration: args[0], target };
            break;

        case "anim":
            if (args[0] === "stop") {
                config = { type: "anim", name: "", stop: true, target };
            } else {
                config = { type: "anim", name: args[0], fade: args[1], target };
            }
            break;

        case "stop":
            config = { type: "anim", name: "", stop: true, target };
            break;

        case "move":
            config = parseMove("moveTo", args, target);
            break;

        case "moveBy":
            config = parseMove("moveBy", args, target);
            break;

        case "toward": {
            // ["toward", [x, y], ratio, duration, ease?]
            const [coord, ratio, duration, ease] = args;
            config = {
                type: "moveToward",
                x: coord[0],
                y: coord[1],
                ratio,
                duration,
                ease,
                target,
            } as any;
            break;
        }

        case "scale":
            config = parseScale(args, target);
            break;

        case "rotate":
            config = {
                type: "rotateTo",
                angle: args[0],
                duration: args[1],
                ease: args[2],
                target,
            } as any;
            break;

        case "fade":
            config = {
                type: "fadeTo",
                alpha: args[0],
                duration: args[1],
                ease: args[2],
                target,
            } as any;
            break;

        case "effect": {
            // effect 路径自动拼接 def.effects 前缀
            const effectPath = ctx.defaults.effects ? ctx.defaults.effects + args[0] : args[0];
            config = {
                type: "effect",
                path: effectPath,
                duration: args[1],
                target,
            } as any;
            break;
        }

        case "event":
            config = { type: "event", name: args[0], target } as any;
            break;

        case "hide":
            config = { type: "hide", target } as any;
            break;

        case "show":
            config = { type: "show", target } as any;
            break;

        case "destroy":
            config = { type: "destroy", target } as any;
            break;

        case "sound": {
            const soundPath = ctx.defaults.sounds ? ctx.defaults.sounds + args[0] : args[0];
            config = {
                type: "sound",
                path: soundPath,
                volume: args[1],
                target,
            } as any;
            break;
        }

        default:
            ctx.diagnostics.push({
                severity: "error",
                message: `Unknown action type: ${type}`,
                path,
            });
            config = { type: "wait", duration: 0 } as any;
    }

    // 获取定义以计算时长
    const definition = registry.get(config.type);
    const duration = definition ? definition.getDuration(config, ctx.engine.eval.bind(ctx.engine)) : 0;

    return {
        id: nodeId,
        type: config.type,
        config,
        duration,
        path: path || "root",
    } as RuntimeNode;
}

/**
 * 解析 move 配置
 */
function parseMove(type: "moveTo" | "moveBy", args: any[], target?: string): ActionConfig {
    // ["move", [x, y] or [x, y, z], duration, ease?]
    const [coord, duration, ease] = args;
    return {
        type,
        x: coord[0],
        y: coord[1],
        z: coord[2],
        duration,
        ease,
        target,
    } as any;
}

/**
 * 解析 scale 配置
 */
function parseScale(args: any[], target?: string): ActionConfig {
    // ["scale", value or [x,y,z], duration, ease?]
    const [value, duration, ease] = args;
    if (Array.isArray(value)) {
        return {
            type: "scaleTo",
            x: value[0],
            y: value[1],
            z: value[2],
            duration,
            ease,
            target,
        } as any;
    }
    return {
        type: "scaleTo",
        x: value,
        y: value,
        z: value,
        duration,
        ease,
        target,
    } as any;
}
