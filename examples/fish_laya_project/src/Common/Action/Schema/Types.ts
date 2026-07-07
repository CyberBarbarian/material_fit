/**
 * Action Schema Types
 * 统一的配置类型定义
 */

// ============================================================================
// 基础类型
// ============================================================================

/**
 * 表达式类型 - 支持数字或字符串表达式
 * - 数字: 100
 * - 百分比: "50%"
 * - 变量: "$speed"
 * - 随机: "random(0, 100)"
 */
export type Expression = number | string;

/**
 * 缓动类型
 */
export type EaseType =
    | "linear"
    | "sineIn" | "sineOut" | "sineInOut"
    | "quadIn" | "quadOut" | "quadInOut"
    | "cubicIn" | "cubicOut" | "cubicInOut"
    | "quartIn" | "quartOut" | "quartInOut"
    | "quintIn" | "quintOut" | "quintInOut"
    | "expoIn" | "expoOut" | "expoInOut"
    | "circIn" | "circOut" | "circInOut"
    | "backIn" | "backOut" | "backInOut"
    | "elasticIn" | "elasticOut" | "elasticInOut"
    | "bounceIn" | "bounceOut" | "bounceInOut";

/**
 * 旋转轴
 */
export type RotationAxis = "x" | "y" | "z";

/**
 * Action 类型分类
 */
export type ActionCategory = "container" | "tween" | "instant";

/**
 * 叶子 Action 基础配置
 * 包含所有叶子 Action（非容器类型）共有的可选字段
 */
export interface LeafActionConfig {
    /**
     * 目标节点路径
     * - 不指定：使用当前上下文的 target
     * - "/"：根节点（play 时传入的 target）
     * - "child"：当前 target 的子节点
     * - "child/grandchild"：相对路径
     * - "/child/grandchild"：绝对路径（从根开始）
     */
    target?: string;
}

// ============================================================================
// 缓动类型配置
// ============================================================================

/**
 * moveTo - 移动到绝对坐标
 */
export interface MoveToConfig extends LeafActionConfig {
    type: "moveTo";
    x: Expression;
    y: Expression;
    z?: Expression;
    duration: Expression;
    ease?: EaseType;
}

/**
 * moveBy - 相对移动
 */
export interface MoveByConfig extends LeafActionConfig {
    type: "moveBy";
    x: Expression;
    y: Expression;
    z?: Expression;
    duration: Expression;
    ease?: EaseType;
}

/**
 * moveToward - 朝向目标移动
 */
export interface MoveTowardConfig extends LeafActionConfig {
    type: "moveToward";
    x: Expression;
    y: Expression;
    ratio: Expression;
    duration: Expression;
    ease?: EaseType;
}

/**
 * scaleTo - 缩放到
 */
export interface ScaleToConfig extends LeafActionConfig {
    type: "scaleTo";
    x: Expression;
    y: Expression;
    z?: Expression;
    duration: Expression;
    ease?: EaseType;
}

/**
 * scaleBy - 相对缩放
 */
export interface ScaleByConfig extends LeafActionConfig {
    type: "scaleBy";
    x: Expression;
    y: Expression;
    z?: Expression;
    duration: Expression;
    ease?: EaseType;
}

/**
 * rotateTo - 旋转到
 */
export interface RotateToConfig extends LeafActionConfig {
    type: "rotateTo";
    angle: Expression;
    axis?: RotationAxis;
    duration: Expression;
    ease?: EaseType;
}

/**
 * rotateBy - 相对旋转
 */
export interface RotateByConfig extends LeafActionConfig {
    type: "rotateBy";
    angle: Expression;
    axis?: RotationAxis;
    duration: Expression;
    ease?: EaseType;
}

/**
 * fadeTo - 淡入淡出
 */
export interface FadeToConfig extends LeafActionConfig {
    type: "fadeTo";
    alpha: Expression;
    duration: Expression;
    ease?: EaseType;
}

/**
 * wait - 等待
 */
export interface WaitConfig extends LeafActionConfig {
    type: "wait";
    duration: Expression;
}

// ============================================================================
// 即时类型配置
// ============================================================================

/**
 * anim - 播放动画
 */
export interface AnimConfig extends LeafActionConfig {
    type: "anim";
    name: string;
    /** 动画持续时间（秒），用于时间轴显示 */
    duration?: Expression;
    fade?: number;
    stop?: boolean;
}

/**
 * effect - 播放特效
 */
export interface EffectConfig extends LeafActionConfig {
    type: "effect";
    path: string;
    x?: Expression;
    y?: Expression;
    z?: Expression;
    /** 特效实例的父节点路径（与 target 不同：target 决定位置坐标系，parent 决定层级） */
    parent?: string;
    duration?: number;
}

/**
 * event - 触发事件
 */
export interface EventConfig extends LeafActionConfig {
    type: "event";
    name: string;
    data?: Record<string, any>;
}

/**
 * show - 显示
 */
export interface ShowConfig extends LeafActionConfig {
    type: "show";
}

/**
 * hide - 隐藏
 */
export interface HideConfig extends LeafActionConfig {
    type: "hide";
}

/**
 * destroy - 销毁
 */
export interface DestroyConfig extends LeafActionConfig {
    type: "destroy";
}

/**
 * sound - 播放音效
 */
export interface SoundConfig extends LeafActionConfig {
    type: "sound";
    /** 音效文件路径 */
    path: string;
    /** 音量 (0-1) */
    volume?: number;
}

// ============================================================================
// 联合类型
// ============================================================================

/**
 * 缓动配置联合类型
 */
export type TweenConfig =
    | MoveToConfig
    | MoveByConfig
    | MoveTowardConfig
    | ScaleToConfig
    | ScaleByConfig
    | RotateToConfig
    | RotateByConfig
    | FadeToConfig
    | WaitConfig;

/**
 * 即时配置联合类型
 */
export type InstantConfig =
    | AnimConfig
    | EffectConfig
    | EventConfig
    | ShowConfig
    | HideConfig
    | DestroyConfig
    | SoundConfig;

/**
 * 所有 Action 配置联合类型（叶子节点配置，容器类型由编译器内部处理）
 */
export type ActionConfig = TweenConfig | InstantConfig;

/**
 * Action 类型名称
 */
export type ActionType = ActionConfig["type"];

// ============================================================================
// Action 定义接口
// ============================================================================

/**
 * 字段定义
 */
export interface FieldDefinition {
    name: string;
    type: "number" | "string" | "boolean" | "expression" | "object" | "array" | "action";
    required: boolean;
    default?: any;
}

/**
 * 诊断信息
 */
export interface Diagnostic {
    severity: "error" | "warning" | "info";
    message: string;
    path: string;
}

/**
 * 运行时上下文
 */
export interface RuntimeContext {
    /** 原始目标对象 */
    target: any;
    /** Action 控制器 */
    controller: any;
    /** 是否为 3D 模式 */
    is3D: boolean;
    /** 表达式求值 */
    eval: (value: Expression) => number;
    /** 坐标表达式求值（支持百分比） */
    evalCoord: (value: Expression, axis: "x" | "y" | "z") => number;
    /** Tween 运行器 */
    tweenRunner: any;
    /** 特效运行器 */
    effectRunner: any;
    /** 音效播放器 */
    soundPlayer?: any;
    /** 动画适配器工厂 */
    createAnimator: () => any;
    /** 事件派发器 */
    dispatchEvent?: (name: string, data?: any) => void;
    /** 查找子节点 */
    findChild: (path: string) => any;
    /** 执行子节点 */
    executeNode: (node: any) => Promise<void>;
    /** 当前节点时长（毫秒） */
    duration: number;
}

/**
 * Action 类型定义（运行时）
 */
export interface ActionDefinition<TConfig extends ActionConfig = ActionConfig> {
    /** 类型标识 */
    type: TConfig["type"];

    /** 分类 */
    category: ActionCategory;

    /** 显示名称 */
    label: string;

    /** 字段定义 */
    fields: FieldDefinition[];

    /** 默认值 */
    defaults: Partial<TConfig>;

    /** 是否为容器类型 */
    isContainer?: boolean;

    /** 子 Action 字段名（容器类型专用） */
    childrenField?: "actions" | "action";

    /** 计算时长 */
    getDuration(config: TConfig, evalFn: (v: Expression) => number): number;

    /** 运行时执行 */
    execute(config: TConfig, ctx: RuntimeContext): Promise<void>;
}
