/**
 * Expression Context
 * 表达式求值的不可变上下文
 */

/**
 * 世界坐标边界
 */
export interface WorldBounds {
    /** 世界宽度 */
    width: number;
    /** 世界高度 */
    height: number;
    /** 世界深度 (3D) */
    depth?: number;
}

/**
 * 表达式上下文接口
 * 提供表达式求值所需的所有环境信息
 */
export interface ExpressionContext {
    /** 变量表 */
    readonly variables: Readonly<Record<string, number>>;

    /** 世界边界（用于百分比计算） */
    readonly world: Readonly<WorldBounds>;

    /** 随机数种子（用于确定性随机） */
    readonly seed: number;

    /** 是否为 3D 模式 */
    readonly is3D: boolean;
}

/**
 * 创建上下文的选项
 */
export interface CreateContextOptions {
    /** 变量表 */
    variables?: Record<string, number>;

    /** 世界边界 */
    world?: Partial<WorldBounds>;

    /** 随机数种子 */
    seed?: number;

    /** 是否为 3D 模式 */
    is3D?: boolean;
}

/**
 * 默认世界边界
 */
const DEFAULT_WORLD: WorldBounds = {
    width: 1920,
    height: 1080,
    depth: 1000,
};

/**
 * 创建表达式上下文
 * @param options 创建选项
 * @returns 不可变的表达式上下文
 */
export function createContext(options: CreateContextOptions = {}): ExpressionContext {
    const variables = options.variables ? { ...options.variables } : {};
    const world: WorldBounds = {
        width: options.world?.width ?? DEFAULT_WORLD.width,
        height: options.world?.height ?? DEFAULT_WORLD.height,
        depth: options.world?.depth ?? DEFAULT_WORLD.depth,
    };

    return Object.freeze({
        variables: Object.freeze(variables),
        world: Object.freeze(world),
        seed: options.seed ?? Date.now(),
        is3D: options.is3D ?? false,
    });
}

/**
 * 扩展上下文
 * @param base 基础上下文
 * @param newVariables 要合并的变量
 * @returns 扩展后的上下文
 */
export function extendContext(
    base: ExpressionContext,
    newVariables: Record<string, number>
): ExpressionContext {
    return createContext({
        variables: { ...base.variables, ...newVariables },
        world: base.world,
        seed: base.seed,
        is3D: base.is3D,
    });
}

/**
 * 获取轴对应的世界尺寸
 * @param world 世界边界
 * @param axis 轴名称
 * @returns 对应的尺寸值
 */
export function getWorldSize(world: WorldBounds, axis: "x" | "y" | "z"): number {
    switch (axis) {
        case "x":
            return world.width;
        case "y":
            return world.height;
        case "z":
            return world.depth ?? 1000;
    }
}
