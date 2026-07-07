/**
 * Action Executor
 * 基于 RuntimePlan 执行动画
 */

import type { ActionConfig, RuntimeContext } from "../Schema/Types";
import type { RepeatNode, RuntimeNode, RuntimePlan, SeqNode, SpawnNode } from "../Compiler/RuntimePlan";
import type { ExpressionEngine } from "../Expression/Engine";
import type { ActionController } from "./Controller";
import type { TargetAdapter } from "./Adapters/Target";
import { createTargetAdapter } from "./Adapters/Target";
import { createAnimatorAdapter } from "./Adapters/Animator";
import { createEffectRunner, EffectRunner } from "./Adapters/Effect";
import { createTweenRunner, TweenRunner } from "./TweenRunner";
import { registry } from "../Schema/Registry";

/**
 * 执行上下文
 */
export interface ExecuteContext {
    /** 目标适配器 */
    target: TargetAdapter;
    /** 原始目标 */
    rawTarget: any;
    /** 根目标（play 时传入的原始 target，用于绝对路径解析） */
    rootTarget: any;
    /** 表达式引擎 */
    engine: ExpressionEngine;
    /** 控制器 */
    controller: ActionController;
    /** Tween 运行器 */
    tweenRunner: TweenRunner;
    /** 特效运行器 */
    effectRunner: EffectRunner;
    /** 事件派发器 */
    dispatchEvent?: (name: string, data?: any) => void;
    /** target 解析缓存（相同路径只解析一次） */
    targetCache: Map<string, any>;
}

/**
 * 执行运行时计划
 */
export async function execute(
    plan: RuntimePlan,
    target: any,
    engine: ExpressionEngine,
    controller: ActionController,
    dispatchEvent?: (name: string, data?: any) => void
): Promise<void> {
    const adapter = createTargetAdapter(target);
    const tweenRunner = createTweenRunner(controller);
    const effectRunner = createEffectRunner(controller);

    const ctx: ExecuteContext = {
        target: adapter,
        rawTarget: target,
        rootTarget: target,
        engine,
        controller,
        tweenRunner,
        effectRunner,
        dispatchEvent,
        targetCache: new Map(),
    };

    try {
        await executeNode(plan.root, ctx);

        if (!controller.stopped) {
            controller.complete();
        }
    } catch (e) {
        console.error("[Executor] 执行错误:", e);
        if (!controller.stopped) {
            controller.stop();
        }
    }
}

/**
 * 执行单个节点
 */
async function executeNode(node: RuntimeNode, ctx: ExecuteContext): Promise<void> {
    if (ctx.controller.stopped) {
        return;
    }

    // Container 类型需要特殊处理（访问 RuntimeNode 结构）
    switch (node.type) {
        case "seq":
            await executeSeq(node as SeqNode, ctx);
            return;
        case "spawn":
            await executeSpawn(node as SpawnNode, ctx);
            return;
        case "repeat":
            await executeRepeat(node as RepeatNode, ctx);
            return;
    }

    // 叶子节点：解析 target 并可能切换上下文
    const targetPath = (node.config as any).target as string | undefined;
    let nodeCtx = ctx;

    if (targetPath && targetPath !== "" && targetPath !== "/") {
        const resolvedTarget = resolveTarget(targetPath, ctx);
        if (resolvedTarget && resolvedTarget !== ctx.rawTarget) {
            nodeCtx = createContextForTarget(resolvedTarget, ctx);
        }
    } else if (targetPath === "/") {
        // 显式指定根节点
        if (ctx.rootTarget !== ctx.rawTarget) {
            nodeCtx = createContextForTarget(ctx.rootTarget, ctx);
        }
    }

    // 叶子节点使用 Registry 分发
    const definition = registry.get(node.type);
    if (definition) {
        // 构建 RuntimeContext
        const runtimeCtx: RuntimeContext = {
            target: nodeCtx.rawTarget,
            controller: nodeCtx.controller,
            is3D: nodeCtx.target.is3D,
            eval: (value) => nodeCtx.engine.eval(value),
            evalCoord: (value, axis) => nodeCtx.engine.evalCoord(value, axis),
            tweenRunner: nodeCtx.tweenRunner,
            effectRunner: nodeCtx.effectRunner,
            createAnimator: () => createAnimatorAdapter(nodeCtx.rawTarget, nodeCtx.target.is3D),
            dispatchEvent: nodeCtx.dispatchEvent,
            findChild: (path) => findChildByPath(nodeCtx.rawTarget, path),
            executeNode: (childNode) => executeNode(childNode, nodeCtx),
            duration: node.duration,
        };
        await definition.execute(node.config as ActionConfig, runtimeCtx);
    }
}

// ============================================================================
// 容器类型执行
// ============================================================================

async function executeSeq(node: SeqNode, ctx: ExecuteContext): Promise<void> {
    for (const child of node.children) {
        if (ctx.controller.stopped) break;
        await executeNode(child, ctx);
    }
}

async function executeSpawn(node: SpawnNode, ctx: ExecuteContext): Promise<void> {
    // 使用 Promise.all + catch 确保即使某个子任务失败，其他也能完成
    const promises = node.children.map(child => executeNode(child, ctx));
    await Promise.all(promises.map(function (p: Promise<void>): Promise<void | null> {
        return p.catch(function (e: any): null {
            console.error("[Executor] spawn 子任务错误:", e);
            return null;
        });
    }));
}

async function executeRepeat(node: RepeatNode, ctx: ExecuteContext): Promise<void> {
    // 确保 count 为整数（编译阶段已处理，此处为双重保险）
    const count = Math.floor(node.count);
    for (let i = 0; i < count; i++) {
        if (ctx.controller.stopped) break;
        await executeNode(node.child, ctx);
    }
}

// ============================================================================
// 辅助函数
// ============================================================================

/**
 * 按路径查找子节点
 * 支持 "child" 或 "child/grandchild" 格式
 */
function findChildByPath(target: any, path: string): any {
    if (!target || !path) return null;

    const parts = path.split("/").filter(p => p.length > 0);
    let current = target;

    for (const part of parts) {
        if (!current) return null;
        // 尝试 getChildByName
        current = current.getChildByName?.(part) ?? null;
    }

    return current;
}

/**
 * 解析 target 路径
 * - 绝对路径（以 / 开头）：从 rootTarget 开始查找
 * - 相对路径：从当前 rawTarget 开始查找
 * - 使用缓存避免重复解析
 */
function resolveTarget(path: string, ctx: ExecuteContext): any {
    // 检查缓存
    if (ctx.targetCache.has(path)) {
        return ctx.targetCache.get(path);
    }

    // 确定起始节点和清理后的路径
    const isAbsolute = path.startsWith("/");
    const startNode = isAbsolute ? ctx.rootTarget : ctx.rawTarget;
    const cleanPath = isAbsolute ? path.slice(1) : path;

    // 查找目标
    const resolved = cleanPath ? findChildByPath(startNode, cleanPath) : startNode;

    if (!resolved) {
        console.warn(`[Action] Target not found: "${path}", using current target`);
        ctx.targetCache.set(path, ctx.rawTarget);
        return ctx.rawTarget;
    }

    ctx.targetCache.set(path, resolved);
    return resolved;
}

/**
 * 为指定 target 创建执行上下文
 */
function createContextForTarget(newTarget: any, ctx: ExecuteContext): ExecuteContext {
    const newAdapter = createTargetAdapter(newTarget);
    return {
        target: newAdapter,
        rawTarget: newTarget,
        rootTarget: ctx.rootTarget,
        engine: ctx.engine,
        controller: ctx.controller,
        tweenRunner: ctx.tweenRunner,
        effectRunner: ctx.effectRunner,
        dispatchEvent: ctx.dispatchEvent,
        targetCache: ctx.targetCache, // 共享缓存
    };
}
