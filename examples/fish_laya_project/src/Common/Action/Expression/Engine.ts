/**
 * Expression Engine
 * 无状态的表达式求值引擎
 */

import type { Expression } from "../Schema/Types";
import type { ExpressionContext } from "./Context";
import { getWorldSize } from "./Context";

/**
 * 编译后的表达式函数
 */
type CompiledExpression = (ctx: ExpressionContext, randomState: RandomState) => number;

/**
 * 表达式编译缓存
 */
const expressionCache: Map<string, CompiledExpression> = new Map();

/**
 * 随机数状态（用于确定性随机）
 */
interface RandomState {
    seed: number;
    index: number;
}

/**
 * 简单的确定性随机数生成器 (Mulberry32)
 */
function mulberry32(seed: number): number {
    let t = (seed + 0x6D2B79F5) | 0;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
}

/**
 * 获取下一个随机数
 */
function nextRandom(state: RandomState, min: number, max: number): number {
    const value = mulberry32(state.seed + state.index);
    state.index++;
    return min + value * (max - min);
}

/**
 * 解析表达式字符串
 * 支持的格式:
 * - 数字: 100, -50, 3.14
 * - 百分比: "50%", "-25%"
 * - 变量: "$speed", "$damage"
 * - 随机: "random(0, 100)", "random(-10, 10)"
 * - 简单运算: "$speed * 2", "100 + $bonus"
 */
function compileExpression(expr: string): CompiledExpression {
    const trimmed = expr.trim();

    // 纯数字
    const numValue = parseFloat(trimmed);
    if (!isNaN(numValue) && trimmed === String(numValue)) {
        return () => numValue;
    }

    // 百分比 (用于坐标，需要 evalCoord 处理)
    if (trimmed.endsWith("%")) {
        const percent = parseFloat(trimmed.slice(0, -1));
        if (!isNaN(percent)) {
            // 返回特殊值，标记为百分比
            return () => percent / 100;
        }
    }

    // 变量引用 $varName
    if (trimmed.startsWith("$")) {
        const varName = trimmed.slice(1);
        return (ctx) => {
            const value = ctx.variables[varName];
            if (value === undefined) {
                console.warn(`[Expression] 未定义的变量: ${varName}`);
                return 0;
            }
            return value;
        };
    }

    // random(min, max) 或 rand(min, max)
    const randomMatch = trimmed.match(/^(?:random|rand)\s*\(\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*\)$/);
    if (randomMatch) {
        const min = parseFloat(randomMatch[1]);
        const max = parseFloat(randomMatch[2]);
        return (ctx, state) => nextRandom(state, min, max);
    }

    // 简单表达式（包含变量和运算符）
    // 支持: $var, +, -, *, /, 数字
    if (trimmed.includes("$") || /[\+\-\*\/]/.test(trimmed)) {
        return compileSimpleExpression(trimmed);
    }

    // 默认尝试解析为数字
    const fallbackNum = parseFloat(trimmed);
    if (!isNaN(fallbackNum)) {
        return () => fallbackNum;
    }

    console.warn(`[Expression] 无法解析表达式: ${expr}`);
    return () => 0;
}

/**
 * 编译简单数学表达式
 * 支持: 变量、数字、四则运算
 */
function compileSimpleExpression(expr: string): CompiledExpression {
    // 分词
    const tokens = tokenize(expr);

    return (ctx, state) => {
        // 替换变量为数值
        const values: number[] = [];
        const ops: string[] = [];

        for (let i = 0; i < tokens.length; i++) {
            const token = tokens[i];

            if (token.startsWith("$")) {
                const varName = token.slice(1);
                const value = ctx.variables[varName];
                if (value === undefined) {
                    console.warn(`[Expression] 未定义的变量: ${varName}`);
                    values.push(0);
                } else {
                    values.push(value);
                }
            } else if (/^-?[\d.]+$/.test(token)) {
                values.push(parseFloat(token));
            } else if (/^[\+\-\*\/]$/.test(token)) {
                ops.push(token);
            }
        }

        // 简单的从左到右计算（先乘除后加减）
        // 第一遍：处理乘除
        let i = 0;
        while (i < ops.length) {
            if (ops[i] === "*" || ops[i] === "/") {
                const left = values[i];
                const right = values[i + 1];
                const result = ops[i] === "*" ? left * right : (right !== 0 ? left / right : 0);
                values.splice(i, 2, result);
                ops.splice(i, 1);
            } else {
                i++;
            }
        }

        // 第二遍：处理加减
        let result = values[0] || 0;
        for (let j = 0; j < ops.length; j++) {
            const right = values[j + 1] || 0;
            result = ops[j] === "+" ? result + right : result - right;
        }

        return result;
    };
}

/**
 * 表达式分词
 */
function tokenize(expr: string): string[] {
    const tokens: string[] = [];
    let current = "";

    for (let i = 0; i < expr.length; i++) {
        const char = expr[i];

        if (char === " ") {
            if (current) {
                tokens.push(current);
                current = "";
            }
            continue;
        }

        if (/[\+\*\/]/.test(char)) {
            if (current) {
                tokens.push(current);
                current = "";
            }
            tokens.push(char);
            continue;
        }

        // 处理减号（可能是负号或减法）
        if (char === "-") {
            if (current) {
                tokens.push(current);
                current = "";
                tokens.push(char);
            } else if (tokens.length === 0 || /[\+\-\*\/]$/.test(tokens[tokens.length - 1])) {
                // 负号
                current = "-";
            } else {
                tokens.push(char);
            }
            continue;
        }

        current += char;
    }

    if (current) {
        tokens.push(current);
    }

    return tokens;
}

/**
 * 获取或编译表达式
 */
function getCompiledExpression(expr: string): CompiledExpression {
    let compiled = expressionCache.get(expr);
    if (!compiled) {
        compiled = compileExpression(expr);
        expressionCache.set(expr, compiled);
    }
    return compiled;
}

/**
 * 创建表达式引擎实例
 * @param ctx 表达式上下文
 * @returns 引擎实例
 */
export function createEngine(ctx: ExpressionContext) {
    // 随机数状态
    const randomState: RandomState = {
        seed: ctx.seed,
        index: 0,
    };

    // 创建可变的变量副本（用于 setVariable）
    const mutableVariables: Record<string, number> = { ...ctx.variables };

    // 创建一个可变的上下文代理
    const mutableCtx: ExpressionContext = {
        get variables() {
            return mutableVariables;
        },
        world: ctx.world,
        seed: ctx.seed,
        is3D: ctx.is3D,
    };

    return {
        /**
         * 求值标量表达式
         * @param value 表达式值
         * @returns 计算结果
         */
        eval(value: Expression): number {
            if (typeof value === "number") {
                return value;
            }
            const compiled = getCompiledExpression(value);
            return compiled(mutableCtx, randomState);
        },

        /**
         * 求值坐标表达式（支持百分比）
         * @param value 表达式值
         * @param axis 坐标轴
         * @returns 计算结果
         */
        evalCoord(value: Expression, axis: "x" | "y" | "z"): number {
            if (typeof value === "number") {
                return value;
            }

            const trimmed = value.trim();

            // 百分比处理
            if (trimmed.endsWith("%")) {
                const percent = parseFloat(trimmed.slice(0, -1));
                if (!isNaN(percent)) {
                    const worldSize = getWorldSize(mutableCtx.world, axis);
                    return (percent / 100) * worldSize;
                }
            }

            // 其他表达式
            const compiled = getCompiledExpression(value);
            return compiled(mutableCtx, randomState);
        },

        /**
         * 重置随机数状态
         */
        resetRandom(): void {
            randomState.index = 0;
        },

        /**
         * 获取当前上下文
         */
        getContext(): ExpressionContext {
            return mutableCtx;
        },

        /**
         * 设置变量值
         * @param name 变量名（不含 $ 前缀）
         * @param value 变量值
         */
        setVariable(name: string, value: number): void {
            mutableVariables[name] = value;
        },

        /**
         * 获取变量值
         * @param name 变量名（不含 $ 前缀）
         * @returns 变量值，如果不存在返回 undefined
         */
        getVariable(name: string): number | undefined {
            return mutableVariables[name];
        },
    };
}

/**
 * 表达式引擎类型
 */
export type ExpressionEngine = ReturnType<typeof createEngine>;

/**
 * 清除表达式缓存（用于测试）
 */
export function clearExpressionCache(): void {
    expressionCache.clear();
}
