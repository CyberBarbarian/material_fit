/**
 * Runtime Plan
 * 运行时执行计划（树结构）
 */

import type { ActionConfig, ActionType } from "../Schema/Types";

/**
 * 运行时节点基础接口
 */
export interface RuntimeNodeBase {
    /** 节点 ID */
    id: number;
    /** Action 类型 */
    type: ActionType | "seq" | "spawn" | "repeat";
    /** 原始配置 */
    config: ActionConfig;
    /** 计算后的时长 (ms) */
    duration: number;
    /** 配置路径（用于错误定位） */
    path: string;
}

/**
 * 容器节点 - seq
 */
export interface SeqNode extends RuntimeNodeBase {
    type: "seq";
    children: RuntimeNode[];
}

/**
 * 容器节点 - spawn
 */
export interface SpawnNode extends RuntimeNodeBase {
    type: "spawn";
    children: RuntimeNode[];
}

/**
 * 容器节点 - repeat
 */
export interface RepeatNode extends RuntimeNodeBase {
    type: "repeat";
    count: number;
    child: RuntimeNode;
}

/**
 * 缓动节点
 */
export interface TweenNode extends RuntimeNodeBase {
    type: "moveTo" | "moveBy" | "moveToward" | "scaleTo" | "scaleBy" | "rotateTo" | "rotateBy" | "fadeTo" | "wait";
}

/**
 * 即时节点
 */
export interface InstantNode extends RuntimeNodeBase {
    type: "anim" | "effect" | "event" | "show" | "hide" | "destroy";
}

/**
 * 运行时节点联合类型
 */
export type RuntimeNode = SeqNode | SpawnNode | RepeatNode | TweenNode | InstantNode;

/**
 * 运行时计划
 */
export interface RuntimePlan {
    /** 根节点 */
    root: RuntimeNode;
    /** 总时长 (ms) */
    totalDuration: number;
    /** 节点总数 */
    nodeCount: number;
}

/**
 * 检查节点是否为容器类型
 */
export function isContainerNode(node: RuntimeNode): node is SeqNode | SpawnNode | RepeatNode {
    return node.type === "seq" || node.type === "spawn" || node.type === "repeat";
}

/**
 * 检查节点是否为缓动类型
 */
export function isTweenNode(node: RuntimeNode): node is TweenNode {
    const tweenTypes: Record<string, boolean> = {
        moveTo: true, moveBy: true, moveToward: true,
        scaleTo: true, scaleBy: true,
        rotateTo: true, rotateBy: true,
        fadeTo: true, wait: true,
    };
    return tweenTypes[node.type] === true;
}

/**
 * 检查节点是否为即时类型
 */
export function isInstantNode(node: RuntimeNode): node is InstantNode {
    const instantTypes: Record<string, boolean> = {
        anim: true, effect: true, event: true,
        show: true, hide: true, destroy: true,
    };
    return instantTypes[node.type] === true;
}

/**
 * 遍历运行时计划的所有节点
 */
export function traverseRuntimePlan(
    node: RuntimeNode,
    callback: (node: RuntimeNode, depth: number) => void,
    depth: number = 0
): void {
    callback(node, depth);

    if (node.type === "seq" || node.type === "spawn") {
        for (const child of node.children) {
            traverseRuntimePlan(child, callback, depth + 1);
        }
    } else if (node.type === "repeat") {
        traverseRuntimePlan(node.child, callback, depth + 1);
    }
}
