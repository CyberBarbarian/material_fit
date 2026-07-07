/**
 * ActionPlayer - 运行时 Action JSON 播放器
 *
 * 使用方式：
 * 1. 将此脚本挂载到节点上
 * 2. 在 IDE 中拖拽 JSON 文件到 json 属性
 * 3. 通过代码调用 play() 播放
 */

import type { ActionJsonConfig } from "./Compiler/RuntimeCompiler";
import { compileToRuntime } from "./Compiler/RuntimeCompiler";
import { createContext } from "./Expression/Context";
import { createEngine } from "./Expression/Engine";
import type { ActionController } from "./Runtime/Controller";
import { createController } from "./Runtime/Controller";
import { execute } from "./Runtime/Executor";

// 确保定义已注册
import { registerInstantDefinitions } from "./Schema/Definitions/Instant";
import { registerTweenDefinitions } from "./Schema/Definitions/Tween";

registerTweenDefinitions();
registerInstantDefinitions();

const { regClass, property } = Laya;

export type ActionVariables = Record<string, number>;

/**
 * 运行时 Action JSON 播放器
 */
@regClass()
export class ActionPlayer extends Laya.Script {
    @property({
        type: String,
        caption: "Action JSON",
        tips: "拖拽 JSON 文件到此处",
        isAsset: true,
        assetTypeFilter: "Json",
        useAssetPath: true,
    })
    public json: string = "";

    private _controller: ActionController | null = null;
    private _variables: ActionVariables = {};
    private _playToken: number = 0;

    public onEnable(): void {
        void this.play();
    }

    public onDisable(): void {
        this.stop();
    }

    public onDestroy(): void {
        this.stop();
    }

    /**
     * 设置变量（覆盖 JSON 内同名变量）
     */
    public setVariables(variables: ActionVariables): void {
        this._variables = { ...variables };
    }

    /**
     * 获取当前控制器
     */
    public get controller(): ActionController | null {
        return this._controller;
    }

    /**
     * 是否正在播放
     */
    public get isPlaying(): boolean {
        return this._controller?.running ?? false;
    }

    /**
     * 播放
     */
    public async play(variables?: ActionVariables): Promise<ActionController | null> {
        if (!this.owner) {
            console.warn("[ActionPlayer] owner 不存在");
            return null;
        }

        const jsonPath = this.json?.trim();
        if (!jsonPath) {
            console.warn("[ActionPlayer] json 为空");
            return null;
        }

        if (variables) {
            this._variables = { ...this._variables, ...variables };
        }

        this.stop();
        const playToken = ++this._playToken;

        // 加载 JSON
        let jsonData: ActionJsonConfig;
        try {
            const res = await Laya.loader.load(jsonPath, Laya.Loader.JSON) as Laya.TextResource;
            if (!res?.data) {
                throw new Error("JSON 数据为空");
            }
            jsonData = res.data as ActionJsonConfig;
        } catch (err) {
            console.error(`[ActionPlayer] JSON 加载失败: ${jsonPath}`, err);
            return null;
        }

        if (playToken !== this._playToken) {
            return null;
        }

        // 合并变量
        const mergedVariables: ActionVariables = {
            ...(jsonData.variables as ActionVariables | undefined),
            ...this._variables,
        };

        // 创建上下文和引擎
        const context = createContext({
            variables: mergedVariables,
            world: this._getWorldBounds(),
            seed: Date.now(),
            is3D: this._is3DTarget(),
        });
        const engine = createEngine(context);

        // 编译
        const { plan, diagnostics } = compileToRuntime({ ...jsonData, variables: mergedVariables }, { engine });
        if (diagnostics.length > 0) {
            console.warn("[ActionPlayer] 编译警告:", diagnostics);
        }

        // 执行
        const controller = createController();
        this._controller = controller;

        void execute(plan, this.owner, engine, controller, (name, data) => {
            (this.owner as any)?.event?.(name, data);
        });

        return controller;
    }

    /**
     * 停止
     */
    public stop(): void {
        if (this._controller) {
            this._controller.stop();
            this._controller = null;
        }
        this._playToken++;
    }

    private _getWorldBounds(): { width: number; height: number; depth: number } {
        const stage = Laya.stage;
        return {
            width: stage?.width ?? 1920,
            height: stage?.height ?? 1080,
            depth: 1000,
        };
    }

    private _is3DTarget(): boolean {
        const owner = this.owner as any;
        return !!owner?.transform && typeof owner.transform.localPosition !== "undefined";
    }
}
