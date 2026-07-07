/**
 * Action Controller
 * 控制 Action 的停止、完成状态
 */

/**
 * 停止回调类型
 */
export type StopCallback = () => void;

/**
 * Action 控制器
 * 管理单次 Action 执行的生命周期
 */
export class ActionController {
    /** 完成 Promise */
    readonly done: Promise<void>;
    /** 停止回调列表 */
    private _stopCallbacks: StopCallback[] = [];
    /** 完成 Promise 的 resolve 函数 */
    private _doneResolve: (() => void) | null = null;

    constructor() {
        this.done = new Promise<void>((resolve) => {
            this._doneResolve = resolve;
        });
    }

    /** 是否已停止 */
    private _stopped: boolean = false;

    /**
     * 是否已停止
     */
    get stopped(): boolean {
        return this._stopped;
    }

    /** 是否已完成 */
    private _completed: boolean = false;

    /**
     * 是否已完成
     */
    get completed(): boolean {
        return this._completed;
    }

    /**
     * 是否正在运行
     */
    get running(): boolean {
        return !this._stopped && !this._completed;
    }

    /**
     * 注册停止回调
     * @param callback 停止时调用的回调
     * @returns 取消注册的函数
     */
    onStop(callback: StopCallback): () => void {
        if (this._stopped) {
            // 已停止，立即调用
            callback();
            return () => {
            };
        }

        this._stopCallbacks.push(callback);

        // 返回取消注册函数
        return () => {
            const index = this._stopCallbacks.indexOf(callback);
            if (index !== -1) {
                this._stopCallbacks.splice(index, 1);
            }
        };
    }

    /**
     * 停止执行
     */
    stop(): void {
        if (this._stopped || this._completed) {
            return;
        }

        this._stopped = true;

        // 调用所有停止回调
        for (const callback of this._stopCallbacks) {
            try {
                callback();
            } catch (e) {
                console.error("[ActionController] 停止回调执行错误:", e);
            }
        }

        // 清空回调列表
        this._stopCallbacks.length = 0;

        // 解决 done Promise
        if (this._doneResolve) {
            this._doneResolve();
            this._doneResolve = null;
        }
    }

    /**
     * 标记完成
     */
    complete(): void {
        if (this._stopped || this._completed) {
            return;
        }

        this._completed = true;

        // 清空停止回调（不调用）
        this._stopCallbacks.length = 0;

        // 解决 done Promise
        if (this._doneResolve) {
            this._doneResolve();
            this._doneResolve = null;
        }
    }

    /**
     * 创建子控制器
     * 当父控制器停止时，子控制器也会停止
     */
    createChild(): ActionController {
        const child = new ActionController();

        // 当父停止时，停止子
        this.onStop(() => {
            child.stop();
        });

        return child;
    }
}

/**
 * 创建控制器
 */
export function createController(): ActionController {
    return new ActionController();
}
