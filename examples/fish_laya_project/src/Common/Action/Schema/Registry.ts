/**
 * Action Registry
 * 统一的 Action 类型注册表
 */

import type { ActionCategory, ActionConfig, ActionDefinition, ActionType } from "./Types";

/**
 * Action 类型注册表
 * 作为所有 Action 类型定义的单一来源
 */
class ActionRegistry {
    private definitions: Map<ActionType, ActionDefinition<any>> = new Map();

    /**
     * 注册 Action 类型定义
     * @param definition Action 类型定义
     */
    register<TConfig extends ActionConfig>(definition: ActionDefinition<TConfig>): void {
        if (this.definitions.has(definition.type)) {
            return;
        }
        this.definitions.set(definition.type, definition);
    }

    /**
     * 获取指定类型的定义
     * @param type Action 类型名
     * @returns 类型定义，不存在返回 undefined
     */
    get<TConfig extends ActionConfig>(type: TConfig["type"]): ActionDefinition<TConfig> | undefined {
        return this.definitions.get(type) as ActionDefinition<TConfig> | undefined;
    }

    /**
     * 获取所有已注册的类型定义
     * @returns 所有类型定义的数组
     */
    getAll(): ActionDefinition<any>[] {
        return Array.from(this.definitions.values());
    }

    /**
     * 按分类获取类型定义
     * @param category 分类
     * @returns 该分类下的所有类型定义
     */
    getByCategory(category: ActionCategory): ActionDefinition<any>[] {
        return this.getAll().filter(def => def.category === category);
    }

    /**
     * 检查类型是否已注册
     * @param type Action 类型名
     * @returns 是否已注册
     */
    has(type: string): boolean {
        return this.definitions.has(type as ActionType);
    }

    /**
     * 获取所有已注册的类型名
     * @returns 类型名数组
     */
    getTypes(): ActionType[] {
        return Array.from(this.definitions.keys());
    }

    /**
     * 清空注册表（用于测试）
     */
    clear(): void {
        this.definitions.clear();
    }
}

/**
 * 全局 Action 注册表实例
 */
export const registry = new ActionRegistry();

/**
 * 便捷函数：注册 Action 类型
 */
export function registerAction<TConfig extends ActionConfig>(
    definition: ActionDefinition<TConfig>
): void {
    registry.register(definition);
}

/**
 * 便捷函数：获取 Action 类型定义
 */
export function getActionDefinition<TConfig extends ActionConfig>(
    type: TConfig["type"]
): ActionDefinition<TConfig> | undefined {
    return registry.get(type);
}

/**
 * 便捷函数：获取所有 Action 类型定义
 */
export function getAllActionDefinitions(): ActionDefinition<any>[] {
    return registry.getAll();
}
