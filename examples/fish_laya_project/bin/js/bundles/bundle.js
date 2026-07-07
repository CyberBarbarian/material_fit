"use strict";
(() => {
  var __defProp = Object.defineProperty;
  var __defProps = Object.defineProperties;
  var __getOwnPropDesc = Object.getOwnPropertyDescriptor;
  var __getOwnPropDescs = Object.getOwnPropertyDescriptors;
  var __getOwnPropSymbols = Object.getOwnPropertySymbols;
  var __hasOwnProp = Object.prototype.hasOwnProperty;
  var __propIsEnum = Object.prototype.propertyIsEnumerable;
  var __pow = Math.pow;
  var __defNormalProp = (obj, key, value) => key in obj ? __defProp(obj, key, { enumerable: true, configurable: true, writable: true, value }) : obj[key] = value;
  var __spreadValues = (a, b) => {
    for (var prop in b || (b = {}))
      if (__hasOwnProp.call(b, prop))
        __defNormalProp(a, prop, b[prop]);
    if (__getOwnPropSymbols)
      for (var prop of __getOwnPropSymbols(b)) {
        if (__propIsEnum.call(b, prop))
          __defNormalProp(a, prop, b[prop]);
      }
    return a;
  };
  var __spreadProps = (a, b) => __defProps(a, __getOwnPropDescs(b));
  var __name = (target, value) => __defProp(target, "name", { value, configurable: true });
  var __decorateClass = (decorators, target, key, kind) => {
    var result = kind > 1 ? void 0 : kind ? __getOwnPropDesc(target, key) : target;
    for (var i = decorators.length - 1, decorator; i >= 0; i--)
      if (decorator = decorators[i])
        result = (kind ? decorator(target, key, result) : decorator(result)) || result;
    if (kind && result) __defProp(target, key, result);
    return result;
  };
  var __async = (__this, __arguments, generator) => {
    return new Promise((resolve, reject) => {
      var fulfilled = (value) => {
        try {
          step(generator.next(value));
        } catch (e) {
          reject(e);
        }
      };
      var rejected = (value) => {
        try {
          step(generator.throw(value));
        } catch (e) {
          reject(e);
        }
      };
      var step = (x) => x.done ? resolve(x.value) : Promise.resolve(x.value).then(fulfilled, rejected);
      step((generator = generator.apply(__this, __arguments)).next());
    });
  };

  // src/Base/Node/EffectDelay.ts
  var { regClass, property } = Laya;
  var EffectDelay = class extends Laya.Script {
    constructor() {
      super(...arguments);
      this.delayTime = 0;
      // ============ 私有字段 ============
      this._animators = [];
      this._particle = null;
    }
    // ============ 生命周期 ============
    onEnable() {
      this._animators = this.owner.getComponents(Laya.Animator);
      this._particle = this.owner.getComponent(Laya.ShurikenParticleRenderer);
      if (this.delayTime > 1e-3) {
        this._hideEffect();
        Laya.timer.once(this.delayTime * 1e3, this, this._playEffect);
      }
    }
    onDisable() {
      if (this.delayTime > 1e-3) {
        Laya.timer.clear(this, this._playEffect);
      }
    }
    // ============ 私有方法 ============
    /** 隐藏：所有子节点设为不激活，禁用动画器，暂停粒子 */
    _hideEffect() {
      const count = this.owner.numChildren;
      for (let i = 0; i < count; i++) {
        this.owner.getChildAt(i).active = false;
      }
      for (let i = 0; i < this._animators.length; i++) {
        this._animators[i].enabled = false;
      }
      if (this._particle) {
        this._particle.particleSystem.pause();
      }
    }
    /** 播放：所有子节点设为激活，启用动画器，播放粒子 */
    _playEffect() {
      const count = this.owner.numChildren;
      for (let i = 0; i < count; i++) {
        this.owner.getChildAt(i).active = true;
      }
      for (let i = 0; i < this._animators.length; i++) {
        this._animators[i].enabled = true;
      }
      if (this._particle) {
        this._particle.particleSystem.play();
      }
    }
  };
  __name(EffectDelay, "EffectDelay");
  __decorateClass([
    property({ type: Number, caption: "延迟时间（秒）" })
  ], EffectDelay.prototype, "delayTime", 2);
  EffectDelay = __decorateClass([
    regClass("94769df1-b0e3-4bb7-a952-b448fbf037c6", "../src/Base/Node/EffectDelay.ts")
  ], EffectDelay);

  // src/Base/Utils/CameraRenderOrder.ts
  var { regClass: regClass2, property: property2 } = Laya;
  var CameraRenderOrder = class extends Laya.Script3D {
    constructor() {
      super(...arguments);
      this._renderingOrder = 0;
    }
    get renderingOrder() {
      return this._renderingOrder;
    }
    set renderingOrder(value) {
      this._renderingOrder = value;
      if (this.owner) this.owner.renderingOrder = value;
    }
    onAwake() {
      this.owner.renderingOrder = this._renderingOrder;
    }
  };
  __name(CameraRenderOrder, "CameraRenderOrder");
  __decorateClass([
    property2({ type: Number, caption: "渲染层级" })
  ], CameraRenderOrder.prototype, "renderingOrder", 1);
  CameraRenderOrder = __decorateClass([
    regClass2("12d85eac-88a2-4915-8f61-8b349fb8c65c", "../src/Base/Utils/CameraRenderOrder.ts")
  ], CameraRenderOrder);

  // src/Common/Action/Schema/Registry.ts
  var _ActionRegistry = class _ActionRegistry {
    constructor() {
      this.definitions = /* @__PURE__ */ new Map();
    }
    /**
     * 注册 Action 类型定义
     * @param definition Action 类型定义
     */
    register(definition) {
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
    get(type) {
      return this.definitions.get(type);
    }
    /**
     * 获取所有已注册的类型定义
     * @returns 所有类型定义的数组
     */
    getAll() {
      return Array.from(this.definitions.values());
    }
    /**
     * 按分类获取类型定义
     * @param category 分类
     * @returns 该分类下的所有类型定义
     */
    getByCategory(category) {
      return this.getAll().filter((def) => def.category === category);
    }
    /**
     * 检查类型是否已注册
     * @param type Action 类型名
     * @returns 是否已注册
     */
    has(type) {
      return this.definitions.has(type);
    }
    /**
     * 获取所有已注册的类型名
     * @returns 类型名数组
     */
    getTypes() {
      return Array.from(this.definitions.keys());
    }
    /**
     * 清空注册表（用于测试）
     */
    clear() {
      this.definitions.clear();
    }
  };
  __name(_ActionRegistry, "ActionRegistry");
  var ActionRegistry = _ActionRegistry;
  var registry = new ActionRegistry();

  // src/Common/Action/Compiler/RuntimeCompiler.ts
  function compileToRuntime(json, options) {
    if (json.variables) {
      for (const key of Object.keys(json.variables)) {
        options.engine.setVariable(key, json.variables[key]);
      }
    }
    const ctx = {
      engine: options.engine,
      diagnostics: [],
      nodeIdCounter: 0,
      defaults: json.defaults || {}
    };
    const rootNode = parseAction(json.action, "", ctx);
    const plan = {
      root: rootNode,
      totalDuration: rootNode.duration,
      nodeCount: ctx.nodeIdCounter
    };
    return {
      plan,
      diagnostics: ctx.diagnostics
    };
  }
  __name(compileToRuntime, "compileToRuntime");
  function parseAction(config, path, ctx) {
    const nodeId = ctx.nodeIdCounter++;
    if (Array.isArray(config) && config.length > 0) {
      if (typeof config[0] === "string") {
        return parseShorthand(config, path, nodeId, ctx);
      }
      return compileSeq(config, path, nodeId, ctx);
    }
    if (typeof config === "object" && !Array.isArray(config)) {
      if ("spawn" in config) {
        return compileSpawn(config.spawn, path, nodeId, ctx);
      }
      const repeatKey = Object.keys(config).find((k) => k.startsWith("repeat:"));
      if (repeatKey) {
        const countStr = repeatKey.slice(7);
        const count = countStr.startsWith("$") ? countStr : parseInt(countStr, 10);
        return compileRepeat(config[repeatKey], count, path, nodeId, ctx);
      }
    }
    ctx.diagnostics.push({
      severity: "error",
      message: `Unknown config format: ${JSON.stringify(config)}`,
      path: path || "root"
    });
    return {
      id: nodeId,
      type: "seq",
      config: { type: "seq", actions: [] },
      duration: 0,
      path: path || "root",
      children: []
    };
  }
  __name(parseAction, "parseAction");
  function compileSeq(actions, path, nodeId, ctx) {
    const children = [];
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
      config: { type: "seq", actions: [] },
      duration: totalDuration,
      path: path || "root",
      children
    };
  }
  __name(compileSeq, "compileSeq");
  function compileSpawn(actions, path, nodeId, ctx) {
    const children = [];
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
      config: { type: "spawn", actions: [] },
      duration: maxDuration,
      path: path || "root",
      children
    };
  }
  __name(compileSpawn, "compileSpawn");
  function compileRepeat(action, count, path, nodeId, ctx) {
    const countValue = typeof count === "string" ? Math.floor(ctx.engine.eval(count)) : count;
    const childPath = path ? `${path}.repeat` : "repeat";
    const child = parseAction(action, childPath, ctx);
    return {
      id: nodeId,
      type: "repeat",
      config: { type: "repeat", count: countValue, action: {} },
      duration: child.duration * countValue,
      path: path || "root",
      count: countValue,
      child
    };
  }
  __name(compileRepeat, "compileRepeat");
  function parseShorthand(arr, path, nodeId, ctx) {
    let idx = 0;
    let target;
    if (typeof arr[0] === "string" && arr[0].startsWith("@")) {
      const alias = arr[0].slice(1);
      target = ctx.defaults[alias] || alias;
      idx = 1;
    }
    const type = arr[idx];
    const args = arr.slice(idx + 1);
    let config;
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
        const [coord, ratio, duration2, ease] = args;
        config = {
          type: "moveToward",
          x: coord[0],
          y: coord[1],
          ratio,
          duration: duration2,
          ease,
          target
        };
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
          target
        };
        break;
      case "fade":
        config = {
          type: "fadeTo",
          alpha: args[0],
          duration: args[1],
          ease: args[2],
          target
        };
        break;
      case "effect": {
        const effectPath = ctx.defaults.effects ? ctx.defaults.effects + args[0] : args[0];
        config = {
          type: "effect",
          path: effectPath,
          duration: args[1],
          target
        };
        break;
      }
      case "event":
        config = { type: "event", name: args[0], target };
        break;
      case "hide":
        config = { type: "hide", target };
        break;
      case "show":
        config = { type: "show", target };
        break;
      case "destroy":
        config = { type: "destroy", target };
        break;
      case "sound": {
        const soundPath = ctx.defaults.sounds ? ctx.defaults.sounds + args[0] : args[0];
        config = {
          type: "sound",
          path: soundPath,
          volume: args[1],
          target
        };
        break;
      }
      default:
        ctx.diagnostics.push({
          severity: "error",
          message: `Unknown action type: ${type}`,
          path
        });
        config = { type: "wait", duration: 0 };
    }
    const definition = registry.get(config.type);
    const duration = definition ? definition.getDuration(config, ctx.engine.eval.bind(ctx.engine)) : 0;
    return {
      id: nodeId,
      type: config.type,
      config,
      duration,
      path: path || "root"
    };
  }
  __name(parseShorthand, "parseShorthand");
  function parseMove(type, args, target) {
    const [coord, duration, ease] = args;
    return {
      type,
      x: coord[0],
      y: coord[1],
      z: coord[2],
      duration,
      ease,
      target
    };
  }
  __name(parseMove, "parseMove");
  function parseScale(args, target) {
    const [value, duration, ease] = args;
    if (Array.isArray(value)) {
      return {
        type: "scaleTo",
        x: value[0],
        y: value[1],
        z: value[2],
        duration,
        ease,
        target
      };
    }
    return {
      type: "scaleTo",
      x: value,
      y: value,
      z: value,
      duration,
      ease,
      target
    };
  }
  __name(parseScale, "parseScale");

  // src/Common/Action/Expression/Context.ts
  var DEFAULT_WORLD = {
    width: 1920,
    height: 1080,
    depth: 1e3
  };
  function createContext(options = {}) {
    var _a, _b, _c, _d, _e, _f, _g, _h;
    const variables = options.variables ? __spreadValues({}, options.variables) : {};
    const world = {
      width: (_b = (_a = options.world) == null ? void 0 : _a.width) != null ? _b : DEFAULT_WORLD.width,
      height: (_d = (_c = options.world) == null ? void 0 : _c.height) != null ? _d : DEFAULT_WORLD.height,
      depth: (_f = (_e = options.world) == null ? void 0 : _e.depth) != null ? _f : DEFAULT_WORLD.depth
    };
    return Object.freeze({
      variables: Object.freeze(variables),
      world: Object.freeze(world),
      seed: (_g = options.seed) != null ? _g : Date.now(),
      is3D: (_h = options.is3D) != null ? _h : false
    });
  }
  __name(createContext, "createContext");
  function getWorldSize(world, axis) {
    var _a;
    switch (axis) {
      case "x":
        return world.width;
      case "y":
        return world.height;
      case "z":
        return (_a = world.depth) != null ? _a : 1e3;
    }
  }
  __name(getWorldSize, "getWorldSize");

  // src/Common/Action/Expression/Engine.ts
  var expressionCache = /* @__PURE__ */ new Map();
  function mulberry32(seed) {
    let t = seed + 1831565813 | 0;
    t = Math.imul(t ^ t >>> 15, t | 1);
    t ^= t + Math.imul(t ^ t >>> 7, t | 61);
    return ((t ^ t >>> 14) >>> 0) / 4294967296;
  }
  __name(mulberry32, "mulberry32");
  function nextRandom(state, min, max) {
    const value = mulberry32(state.seed + state.index);
    state.index++;
    return min + value * (max - min);
  }
  __name(nextRandom, "nextRandom");
  function compileExpression(expr) {
    const trimmed = expr.trim();
    const numValue = parseFloat(trimmed);
    if (!isNaN(numValue) && trimmed === String(numValue)) {
      return () => numValue;
    }
    if (trimmed.endsWith("%")) {
      const percent = parseFloat(trimmed.slice(0, -1));
      if (!isNaN(percent)) {
        return () => percent / 100;
      }
    }
    if (trimmed.startsWith("$")) {
      const varName = trimmed.slice(1);
      return (ctx) => {
        const value = ctx.variables[varName];
        if (value === void 0) {
          console.warn(`[Expression] 未定义的变量: ${varName}`);
          return 0;
        }
        return value;
      };
    }
    const randomMatch = trimmed.match(/^(?:random|rand)\s*\(\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*\)$/);
    if (randomMatch) {
      const min = parseFloat(randomMatch[1]);
      const max = parseFloat(randomMatch[2]);
      return (ctx, state) => nextRandom(state, min, max);
    }
    if (trimmed.includes("$") || /[\+\-\*\/]/.test(trimmed)) {
      return compileSimpleExpression(trimmed);
    }
    const fallbackNum = parseFloat(trimmed);
    if (!isNaN(fallbackNum)) {
      return () => fallbackNum;
    }
    console.warn(`[Expression] 无法解析表达式: ${expr}`);
    return () => 0;
  }
  __name(compileExpression, "compileExpression");
  function compileSimpleExpression(expr) {
    const tokens = tokenize(expr);
    return (ctx, state) => {
      const values = [];
      const ops = [];
      for (let i2 = 0; i2 < tokens.length; i2++) {
        const token = tokens[i2];
        if (token.startsWith("$")) {
          const varName = token.slice(1);
          const value = ctx.variables[varName];
          if (value === void 0) {
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
      let i = 0;
      while (i < ops.length) {
        if (ops[i] === "*" || ops[i] === "/") {
          const left = values[i];
          const right = values[i + 1];
          const result2 = ops[i] === "*" ? left * right : right !== 0 ? left / right : 0;
          values.splice(i, 2, result2);
          ops.splice(i, 1);
        } else {
          i++;
        }
      }
      let result = values[0] || 0;
      for (let j = 0; j < ops.length; j++) {
        const right = values[j + 1] || 0;
        result = ops[j] === "+" ? result + right : result - right;
      }
      return result;
    };
  }
  __name(compileSimpleExpression, "compileSimpleExpression");
  function tokenize(expr) {
    const tokens = [];
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
      if (char === "-") {
        if (current) {
          tokens.push(current);
          current = "";
          tokens.push(char);
        } else if (tokens.length === 0 || /[\+\-\*\/]$/.test(tokens[tokens.length - 1])) {
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
  __name(tokenize, "tokenize");
  function getCompiledExpression(expr) {
    let compiled = expressionCache.get(expr);
    if (!compiled) {
      compiled = compileExpression(expr);
      expressionCache.set(expr, compiled);
    }
    return compiled;
  }
  __name(getCompiledExpression, "getCompiledExpression");
  function createEngine(ctx) {
    const randomState = {
      seed: ctx.seed,
      index: 0
    };
    const mutableVariables = __spreadValues({}, ctx.variables);
    const mutableCtx = {
      get variables() {
        return mutableVariables;
      },
      world: ctx.world,
      seed: ctx.seed,
      is3D: ctx.is3D
    };
    return {
      /**
       * 求值标量表达式
       * @param value 表达式值
       * @returns 计算结果
       */
      eval(value) {
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
      evalCoord(value, axis) {
        if (typeof value === "number") {
          return value;
        }
        const trimmed = value.trim();
        if (trimmed.endsWith("%")) {
          const percent = parseFloat(trimmed.slice(0, -1));
          if (!isNaN(percent)) {
            const worldSize = getWorldSize(mutableCtx.world, axis);
            return percent / 100 * worldSize;
          }
        }
        const compiled = getCompiledExpression(value);
        return compiled(mutableCtx, randomState);
      },
      /**
       * 重置随机数状态
       */
      resetRandom() {
        randomState.index = 0;
      },
      /**
       * 获取当前上下文
       */
      getContext() {
        return mutableCtx;
      },
      /**
       * 设置变量值
       * @param name 变量名（不含 $ 前缀）
       * @param value 变量值
       */
      setVariable(name, value) {
        mutableVariables[name] = value;
      },
      /**
       * 获取变量值
       * @param name 变量名（不含 $ 前缀）
       * @returns 变量值，如果不存在返回 undefined
       */
      getVariable(name) {
        return mutableVariables[name];
      }
    };
  }
  __name(createEngine, "createEngine");

  // src/Common/Action/Runtime/Controller.ts
  var _ActionController = class _ActionController {
    constructor() {
      /** 停止回调列表 */
      this._stopCallbacks = [];
      /** 完成 Promise 的 resolve 函数 */
      this._doneResolve = null;
      /** 是否已停止 */
      this._stopped = false;
      /** 是否已完成 */
      this._completed = false;
      this.done = new Promise((resolve) => {
        this._doneResolve = resolve;
      });
    }
    /**
     * 是否已停止
     */
    get stopped() {
      return this._stopped;
    }
    /**
     * 是否已完成
     */
    get completed() {
      return this._completed;
    }
    /**
     * 是否正在运行
     */
    get running() {
      return !this._stopped && !this._completed;
    }
    /**
     * 注册停止回调
     * @param callback 停止时调用的回调
     * @returns 取消注册的函数
     */
    onStop(callback) {
      if (this._stopped) {
        callback();
        return () => {
        };
      }
      this._stopCallbacks.push(callback);
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
    stop() {
      if (this._stopped || this._completed) {
        return;
      }
      this._stopped = true;
      for (const callback of this._stopCallbacks) {
        try {
          callback();
        } catch (e) {
          console.error("[ActionController] 停止回调执行错误:", e);
        }
      }
      this._stopCallbacks.length = 0;
      if (this._doneResolve) {
        this._doneResolve();
        this._doneResolve = null;
      }
    }
    /**
     * 标记完成
     */
    complete() {
      if (this._stopped || this._completed) {
        return;
      }
      this._completed = true;
      this._stopCallbacks.length = 0;
      if (this._doneResolve) {
        this._doneResolve();
        this._doneResolve = null;
      }
    }
    /**
     * 创建子控制器
     * 当父控制器停止时，子控制器也会停止
     */
    createChild() {
      const child = new _ActionController();
      this.onStop(() => {
        child.stop();
      });
      return child;
    }
  };
  __name(_ActionController, "ActionController");
  var ActionController = _ActionController;
  function createController() {
    return new ActionController();
  }
  __name(createController, "createController");

  // src/Common/Action/Runtime/Adapters/Target.ts
  var _Target2DAdapter = class _Target2DAdapter {
    constructor(raw) {
      this.raw = raw;
      this.is3D = false;
    }
    getX() {
      return this.raw.x || 0;
    }
    getY() {
      return this.raw.y || 0;
    }
    getZ() {
      return 0;
    }
    setX(value) {
      this.raw.x = value;
    }
    setY(value) {
      this.raw.y = value;
    }
    setZ(value) {
    }
    getScaleX() {
      var _a;
      return (_a = this.raw.scaleX) != null ? _a : 1;
    }
    getScaleY() {
      var _a;
      return (_a = this.raw.scaleY) != null ? _a : 1;
    }
    getScaleZ() {
      return 1;
    }
    setScaleX(value) {
      this.raw.scaleX = value;
    }
    setScaleY(value) {
      this.raw.scaleY = value;
    }
    setScaleZ(value) {
    }
    getRotation() {
      return this.raw.rotation || 0;
    }
    getRotationX() {
      return 0;
    }
    getRotationY() {
      return 0;
    }
    getRotationZ() {
      return this.raw.rotation || 0;
    }
    setRotation(value) {
      this.raw.rotation = value;
    }
    setRotationX(value) {
    }
    setRotationY(value) {
    }
    setRotationZ(value) {
      this.raw.rotation = value;
    }
    getAlpha() {
      var _a;
      return (_a = this.raw.alpha) != null ? _a : 1;
    }
    setAlpha(value) {
      this.raw.alpha = value;
    }
    getVisible() {
      return this.raw.visible !== false;
    }
    setVisible(value) {
      this.raw.visible = value;
    }
    destroy() {
      if (this.raw.destroy) {
        this.raw.destroy();
      }
    }
  };
  __name(_Target2DAdapter, "Target2DAdapter");
  var Target2DAdapter = _Target2DAdapter;
  var _Target3DAdapter = class _Target3DAdapter {
    constructor(raw) {
      this.raw = raw;
      this.is3D = true;
    }
    get transform() {
      return this.raw.transform;
    }
    getX() {
      var _a;
      return ((_a = this.transform) == null ? void 0 : _a.localPositionX) || 0;
    }
    getY() {
      var _a;
      return ((_a = this.transform) == null ? void 0 : _a.localPositionY) || 0;
    }
    getZ() {
      var _a;
      return ((_a = this.transform) == null ? void 0 : _a.localPositionZ) || 0;
    }
    setX(value) {
      if (this.transform) this.transform.localPositionX = value;
    }
    setY(value) {
      if (this.transform) this.transform.localPositionY = value;
    }
    setZ(value) {
      if (this.transform) this.transform.localPositionZ = value;
    }
    getScaleX() {
      var _a, _b;
      return (_b = (_a = this.transform) == null ? void 0 : _a.localScaleX) != null ? _b : 1;
    }
    getScaleY() {
      var _a, _b;
      return (_b = (_a = this.transform) == null ? void 0 : _a.localScaleY) != null ? _b : 1;
    }
    getScaleZ() {
      var _a, _b;
      return (_b = (_a = this.transform) == null ? void 0 : _a.localScaleZ) != null ? _b : 1;
    }
    setScaleX(value) {
      if (this.transform) this.transform.localScaleX = value;
    }
    setScaleY(value) {
      if (this.transform) this.transform.localScaleY = value;
    }
    setScaleZ(value) {
      if (this.transform) this.transform.localScaleZ = value;
    }
    getRotation() {
      return this.getRotationZ();
    }
    getRotationX() {
      var _a;
      return ((_a = this.transform) == null ? void 0 : _a.localRotationEulerX) || 0;
    }
    getRotationY() {
      var _a;
      return ((_a = this.transform) == null ? void 0 : _a.localRotationEulerY) || 0;
    }
    getRotationZ() {
      var _a;
      return ((_a = this.transform) == null ? void 0 : _a.localRotationEulerZ) || 0;
    }
    setRotation(value) {
      this.setRotationZ(value);
    }
    setRotationX(value) {
      if (this.transform) this.transform.localRotationEulerX = value;
    }
    setRotationY(value) {
      if (this.transform) this.transform.localRotationEulerY = value;
    }
    setRotationZ(value) {
      if (this.transform) this.transform.localRotationEulerZ = value;
    }
    getAlpha() {
      return 1;
    }
    setAlpha(value) {
    }
    getVisible() {
      return this.raw.active !== false;
    }
    setVisible(value) {
      this.raw.active = value;
    }
    destroy() {
      if (this.raw.destroy) {
        this.raw.destroy();
      }
    }
  };
  __name(_Target3DAdapter, "Target3DAdapter");
  var Target3DAdapter = _Target3DAdapter;
  function createTargetAdapter(target) {
    if (target.transform && typeof target.transform.localPositionX !== "undefined") {
      return new Target3DAdapter(target);
    }
    return new Target2DAdapter(target);
  }
  __name(createTargetAdapter, "createTargetAdapter");

  // src/Common/Action/Runtime/Adapters/Animator.ts
  function findComponentRecursive(target, componentClass) {
    var _a, _b, _c, _d, _e, _f, _g;
    if (!target || !componentClass) return null;
    const component = (_a = target.getComponent) == null ? void 0 : _a.call(target, componentClass);
    if (component) return component;
    const numChildren = (_d = (_c = target.numChildren) != null ? _c : (_b = target._children) == null ? void 0 : _b.length) != null ? _d : 0;
    for (let i = 0; i < numChildren; i++) {
      const child = (_g = (_e = target.getChildAt) == null ? void 0 : _e.call(target, i)) != null ? _g : (_f = target._children) == null ? void 0 : _f[i];
      if (child) {
        const found = findComponentRecursive(child, componentClass);
        if (found) return found;
      }
    }
    return null;
  }
  __name(findComponentRecursive, "findComponentRecursive");
  function findComponentInParents(target, componentClass) {
    var _a;
    if (!target || !componentClass) return null;
    let current = target;
    while (current) {
      const component = (_a = current.getComponent) == null ? void 0 : _a.call(current, componentClass);
      if (component) return component;
      current = current.parent;
    }
    return null;
  }
  __name(findComponentInParents, "findComponentInParents");
  var _Animator2DAdapter = class _Animator2DAdapter {
    constructor(target) {
      const Laya2 = window.Laya;
      if (Laya2 == null ? void 0 : Laya2.Animator2D) {
        this.animator = findComponentInParents(target, Laya2.Animator2D);
        if (!this.animator) {
          this.animator = findComponentRecursive(target, Laya2.Animator2D);
        }
      }
      if (!this.animator) {
        this.animator = target.animator2D || null;
      }
    }
    play(name, fade) {
      var _a, _b, _c, _d;
      if (!this.animator) return;
      if (this.animator.speed === 0) {
        this.animator.speed = 1;
      }
      if (fade && fade > 0) {
        (_b = (_a = this.animator).crossFade) == null ? void 0 : _b.call(_a, name, fade);
      } else {
        (_d = (_c = this.animator).play) == null ? void 0 : _d.call(_c, name);
      }
    }
    stop() {
      var _a;
      if (((_a = this.animator) == null ? void 0 : _a.speed) !== void 0) {
        this.animator.speed = 0;
      }
    }
    hasAnimation(name) {
      return true;
    }
  };
  __name(_Animator2DAdapter, "Animator2DAdapter");
  var Animator2DAdapter = _Animator2DAdapter;
  var _Animator3DAdapter = class _Animator3DAdapter {
    constructor(target) {
      const Laya2 = window.Laya;
      if (Laya2 == null ? void 0 : Laya2.Animator) {
        this.animator = findComponentInParents(target, Laya2.Animator);
        if (!this.animator) {
          this.animator = findComponentRecursive(target, Laya2.Animator);
        }
      }
      if (!this.animator) {
        this.animator = target.animator || null;
      }
    }
    play(name, fade) {
      var _a, _b, _c, _d;
      if (!this.animator) return;
      if (this.animator.speed === 0) {
        this.animator.speed = 1;
      }
      if (fade && fade > 0) {
        (_b = (_a = this.animator).crossFade) == null ? void 0 : _b.call(_a, name, fade);
      } else {
        (_d = (_c = this.animator).play) == null ? void 0 : _d.call(_c, name);
      }
    }
    stop() {
      var _a;
      if (((_a = this.animator) == null ? void 0 : _a.speed) !== void 0) {
        this.animator.speed = 0;
      }
    }
    hasAnimation(name) {
      return true;
    }
  };
  __name(_Animator3DAdapter, "Animator3DAdapter");
  var Animator3DAdapter = _Animator3DAdapter;
  function createAnimatorAdapter(target, is3D2) {
    if (is3D2) {
      return new Animator3DAdapter(target);
    }
    return new Animator2DAdapter(target);
  }
  __name(createAnimatorAdapter, "createAnimatorAdapter");

  // src/Common/Action/Runtime/Adapters/Effect.ts
  var _EffectRunner = class _EffectRunner {
    constructor(controller) {
      /** 活跃的特效实例 */
      this.activeEffects = [];
      this.controller = controller;
      controller.onStop(() => {
        this.stopAll();
      });
    }
    /**
     * 播放特效
     */
    play(options, defaultParent) {
      return __async(this, null, function* () {
        if (this.controller.stopped) {
          return;
        }
        try {
          const effectNode = yield this.loadEffect(options.path);
          if (!effectNode || this.controller.stopped) {
            return;
          }
          if (effectNode.transform) {
            if (options.x !== void 0) effectNode.transform.localPositionX = options.x;
            if (options.y !== void 0) effectNode.transform.localPositionY = options.y;
            if (options.z !== void 0) effectNode.transform.localPositionZ = options.z;
          } else {
            if (options.x !== void 0) effectNode.x = options.x;
            if (options.y !== void 0) effectNode.y = options.y;
          }
          const parent = options.parent || defaultParent;
          if (parent && parent.addChild) {
            parent.addChild(effectNode);
          }
          const instance = {
            node: effectNode,
            stop: /* @__PURE__ */ __name(() => {
              if (effectNode.particleSystem) {
                effectNode.particleSystem.stop();
              }
            }, "stop"),
            destroy: /* @__PURE__ */ __name(() => {
              if (effectNode.destroy) {
                effectNode.destroy();
              }
            }, "destroy")
          };
          this.activeEffects.push(instance);
          if (options.duration && options.duration > 0) {
            setTimeout(() => {
              this.removeEffect(instance);
            }, options.duration * 1e3);
          }
        } catch (e) {
          console.error(`[EffectRunner] 播放特效失败: ${options.path}`, e);
        }
      });
    }
    /**
     * 停止所有特效
     */
    stopAll() {
      for (const effect2 of this.activeEffects) {
        effect2.stop();
        effect2.destroy();
      }
      this.activeEffects.length = 0;
    }
    /**
     * 获取活跃特效数量
     */
    getActiveCount() {
      return this.activeEffects.length;
    }
    /**
     * 加载特效资源
     */
    loadEffect(path) {
      return __async(this, null, function* () {
        try {
          return yield Laya.Prefab.instantiate(path);
        } catch (e) {
          console.error(`[EffectRunner] 加载特效失败: ${path}`, e);
          return null;
        }
      });
    }
    /**
     * 移除特效实例
     */
    removeEffect(instance) {
      const index = this.activeEffects.indexOf(instance);
      if (index !== -1) {
        this.activeEffects.splice(index, 1);
        instance.destroy();
      }
    }
  };
  __name(_EffectRunner, "EffectRunner");
  var EffectRunner = _EffectRunner;
  function createEffectRunner(controller) {
    return new EffectRunner(controller);
  }
  __name(createEffectRunner, "createEffectRunner");

  // src/Common/Action/Runtime/TweenRunner.ts
  var EASE_FUNCTIONS = {
    linear: null,
    // 将在运行时获取 Laya.Ease
    sineIn: null,
    sineOut: null,
    sineInOut: null,
    quadIn: null,
    quadOut: null,
    quadInOut: null,
    cubicIn: null,
    cubicOut: null,
    cubicInOut: null,
    quartIn: null,
    quartOut: null,
    quartInOut: null,
    quintIn: null,
    quintOut: null,
    quintInOut: null,
    expoIn: null,
    expoOut: null,
    expoInOut: null,
    circIn: null,
    circOut: null,
    circInOut: null,
    backIn: null,
    backOut: null,
    backInOut: null,
    elasticIn: null,
    elasticOut: null,
    elasticInOut: null,
    bounceIn: null,
    bounceOut: null,
    bounceInOut: null
  };
  function getEaseFunction(ease) {
    const Laya2 = window.Laya;
    if (!Laya2 || !Laya2.Ease) {
      return null;
    }
    if (EASE_FUNCTIONS.linear === null) {
      EASE_FUNCTIONS.linear = Laya2.Ease.linearNone;
      EASE_FUNCTIONS.sineIn = Laya2.Ease.sineIn;
      EASE_FUNCTIONS.sineOut = Laya2.Ease.sineOut;
      EASE_FUNCTIONS.sineInOut = Laya2.Ease.sineInOut;
      EASE_FUNCTIONS.quadIn = Laya2.Ease.quadIn;
      EASE_FUNCTIONS.quadOut = Laya2.Ease.quadOut;
      EASE_FUNCTIONS.quadInOut = Laya2.Ease.quadInOut;
      EASE_FUNCTIONS.cubicIn = Laya2.Ease.cubicIn;
      EASE_FUNCTIONS.cubicOut = Laya2.Ease.cubicOut;
      EASE_FUNCTIONS.cubicInOut = Laya2.Ease.cubicInOut;
      EASE_FUNCTIONS.quartIn = Laya2.Ease.quartIn;
      EASE_FUNCTIONS.quartOut = Laya2.Ease.quartOut;
      EASE_FUNCTIONS.quartInOut = Laya2.Ease.quartInOut;
      EASE_FUNCTIONS.quintIn = Laya2.Ease.quintIn;
      EASE_FUNCTIONS.quintOut = Laya2.Ease.quintOut;
      EASE_FUNCTIONS.quintInOut = Laya2.Ease.quintInOut;
      EASE_FUNCTIONS.expoIn = Laya2.Ease.expoIn;
      EASE_FUNCTIONS.expoOut = Laya2.Ease.expoOut;
      EASE_FUNCTIONS.expoInOut = Laya2.Ease.expoInOut;
      EASE_FUNCTIONS.circIn = Laya2.Ease.circIn;
      EASE_FUNCTIONS.circOut = Laya2.Ease.circOut;
      EASE_FUNCTIONS.circInOut = Laya2.Ease.circInOut;
      EASE_FUNCTIONS.backIn = Laya2.Ease.backIn;
      EASE_FUNCTIONS.backOut = Laya2.Ease.backOut;
      EASE_FUNCTIONS.backInOut = Laya2.Ease.backInOut;
      EASE_FUNCTIONS.elasticIn = Laya2.Ease.elasticIn;
      EASE_FUNCTIONS.elasticOut = Laya2.Ease.elasticOut;
      EASE_FUNCTIONS.elasticInOut = Laya2.Ease.elasticInOut;
      EASE_FUNCTIONS.bounceIn = Laya2.Ease.bounceIn;
      EASE_FUNCTIONS.bounceOut = Laya2.Ease.bounceOut;
      EASE_FUNCTIONS.bounceInOut = Laya2.Ease.bounceInOut;
    }
    return EASE_FUNCTIONS[ease] || EASE_FUNCTIONS.linear;
  }
  __name(getEaseFunction, "getEaseFunction");
  var _TweenRunner = class _TweenRunner {
    constructor(controller) {
      /** 活跃的 Tween 列表 */
      this.activeTweens = [];
      this.controller = controller;
      controller.onStop(() => {
        this.clearAll();
      });
    }
    /**
     * 执行缓动
     * @param target 目标对象
     * @param options 缓动选项，duration 单位为毫秒
     */
    tween(target, options) {
      return __async(this, null, function* () {
        if (this.controller.stopped) {
          return;
        }
        const durationMs = options.duration;
        const Laya2 = window.Laya;
        if (!Laya2 || !Laya2.Tween) {
          for (const key in options.props) {
            target[key] = options.props[key];
          }
          yield this.delayMs(durationMs);
          return;
        }
        return new Promise((resolve) => {
          const ease = getEaseFunction(options.ease || "linear");
          const tween = Laya2.Tween.to(
            target,
            options.props,
            durationMs,
            ease,
            Laya2.Handler.create(null, () => {
              this.removeTween(tween);
              resolve();
            })
          );
          if (tween) {
            this.activeTweens.push(tween);
          } else {
            resolve();
          }
        });
      });
    }
    /**
     * 等待指定时间（毫秒）
     * @param ms 等待时间（毫秒）
     */
    delay(ms) {
      return __async(this, null, function* () {
        return this.delayMs(ms);
      });
    }
    /**
     * 清除所有 Tween
     */
    clearAll() {
      const Laya2 = window.Laya;
      for (const tween of this.activeTweens) {
        if (Laya2 && Laya2.Tween) {
          Laya2.Tween.clear(tween);
        }
      }
      this.activeTweens.length = 0;
    }
    /**
     * 获取活跃 Tween 数量
     */
    getActiveCount() {
      return this.activeTweens.length;
    }
    /**
     * 等待指定时间（毫秒）- 内部方法
     */
    delayMs(ms) {
      return __async(this, null, function* () {
        if (this.controller.stopped || ms <= 0) {
          return;
        }
        return new Promise((resolve) => {
          const timer = setTimeout(() => {
            resolve();
          }, ms);
          this.controller.onStop(() => {
            clearTimeout(timer);
            resolve();
          });
        });
      });
    }
    /**
     * 移除 Tween
     */
    removeTween(tween) {
      const index = this.activeTweens.indexOf(tween);
      if (index !== -1) {
        this.activeTweens.splice(index, 1);
      }
    }
  };
  __name(_TweenRunner, "TweenRunner");
  var TweenRunner = _TweenRunner;
  function createTweenRunner(controller) {
    return new TweenRunner(controller);
  }
  __name(createTweenRunner, "createTweenRunner");

  // src/Common/Action/Runtime/Executor.ts
  function execute(plan, target, engine, controller, dispatchEvent) {
    return __async(this, null, function* () {
      const adapter = createTargetAdapter(target);
      const tweenRunner = createTweenRunner(controller);
      const effectRunner = createEffectRunner(controller);
      const ctx = {
        target: adapter,
        rawTarget: target,
        rootTarget: target,
        engine,
        controller,
        tweenRunner,
        effectRunner,
        dispatchEvent,
        targetCache: /* @__PURE__ */ new Map()
      };
      try {
        yield executeNode(plan.root, ctx);
        if (!controller.stopped) {
          controller.complete();
        }
      } catch (e) {
        console.error("[Executor] 执行错误:", e);
        if (!controller.stopped) {
          controller.stop();
        }
      }
    });
  }
  __name(execute, "execute");
  function executeNode(node, ctx) {
    return __async(this, null, function* () {
      if (ctx.controller.stopped) {
        return;
      }
      switch (node.type) {
        case "seq":
          yield executeSeq(node, ctx);
          return;
        case "spawn":
          yield executeSpawn(node, ctx);
          return;
        case "repeat":
          yield executeRepeat(node, ctx);
          return;
      }
      const targetPath = node.config.target;
      let nodeCtx = ctx;
      if (targetPath && targetPath !== "" && targetPath !== "/") {
        const resolvedTarget = resolveTarget(targetPath, ctx);
        if (resolvedTarget && resolvedTarget !== ctx.rawTarget) {
          nodeCtx = createContextForTarget(resolvedTarget, ctx);
        }
      } else if (targetPath === "/") {
        if (ctx.rootTarget !== ctx.rawTarget) {
          nodeCtx = createContextForTarget(ctx.rootTarget, ctx);
        }
      }
      const definition = registry.get(node.type);
      if (definition) {
        const runtimeCtx = {
          target: nodeCtx.rawTarget,
          controller: nodeCtx.controller,
          is3D: nodeCtx.target.is3D,
          eval: /* @__PURE__ */ __name((value) => nodeCtx.engine.eval(value), "eval"),
          evalCoord: /* @__PURE__ */ __name((value, axis) => nodeCtx.engine.evalCoord(value, axis), "evalCoord"),
          tweenRunner: nodeCtx.tweenRunner,
          effectRunner: nodeCtx.effectRunner,
          createAnimator: /* @__PURE__ */ __name(() => createAnimatorAdapter(nodeCtx.rawTarget, nodeCtx.target.is3D), "createAnimator"),
          dispatchEvent: nodeCtx.dispatchEvent,
          findChild: /* @__PURE__ */ __name((path) => findChildByPath(nodeCtx.rawTarget, path), "findChild"),
          executeNode: /* @__PURE__ */ __name((childNode) => executeNode(childNode, nodeCtx), "executeNode"),
          duration: node.duration
        };
        yield definition.execute(node.config, runtimeCtx);
      }
    });
  }
  __name(executeNode, "executeNode");
  function executeSeq(node, ctx) {
    return __async(this, null, function* () {
      for (const child of node.children) {
        if (ctx.controller.stopped) break;
        yield executeNode(child, ctx);
      }
    });
  }
  __name(executeSeq, "executeSeq");
  function executeSpawn(node, ctx) {
    return __async(this, null, function* () {
      const promises = node.children.map((child) => executeNode(child, ctx));
      yield Promise.all(promises.map(function(p) {
        return p.catch(function(e) {
          console.error("[Executor] spawn 子任务错误:", e);
          return null;
        });
      }));
    });
  }
  __name(executeSpawn, "executeSpawn");
  function executeRepeat(node, ctx) {
    return __async(this, null, function* () {
      const count = Math.floor(node.count);
      for (let i = 0; i < count; i++) {
        if (ctx.controller.stopped) break;
        yield executeNode(node.child, ctx);
      }
    });
  }
  __name(executeRepeat, "executeRepeat");
  function findChildByPath(target, path) {
    var _a, _b;
    if (!target || !path) return null;
    const parts = path.split("/").filter((p) => p.length > 0);
    let current = target;
    for (const part of parts) {
      if (!current) return null;
      current = (_b = (_a = current.getChildByName) == null ? void 0 : _a.call(current, part)) != null ? _b : null;
    }
    return current;
  }
  __name(findChildByPath, "findChildByPath");
  function resolveTarget(path, ctx) {
    if (ctx.targetCache.has(path)) {
      return ctx.targetCache.get(path);
    }
    const isAbsolute = path.startsWith("/");
    const startNode = isAbsolute ? ctx.rootTarget : ctx.rawTarget;
    const cleanPath = isAbsolute ? path.slice(1) : path;
    const resolved = cleanPath ? findChildByPath(startNode, cleanPath) : startNode;
    if (!resolved) {
      console.warn(`[Action] Target not found: "${path}", using current target`);
      ctx.targetCache.set(path, ctx.rawTarget);
      return ctx.rawTarget;
    }
    ctx.targetCache.set(path, resolved);
    return resolved;
  }
  __name(resolveTarget, "resolveTarget");
  function createContextForTarget(newTarget, ctx) {
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
      targetCache: ctx.targetCache
      // 共享缓存
    };
  }
  __name(createContextForTarget, "createContextForTarget");

  // src/Common/Action/Schema/Definitions/Instant.ts
  var targetField = { name: "target", type: "string", required: false };
  var animDefinition = {
    type: "anim",
    category: "instant",
    label: "动画",
    fields: [
      targetField,
      { name: "name", type: "string", required: true },
      { name: "duration", type: "expression", required: false, default: 0 },
      { name: "fade", type: "number", required: false, default: 0 },
      { name: "stop", type: "boolean", required: false, default: false }
    ],
    defaults: {
      type: "anim",
      name: ""
    },
    getDuration(config, evalFn) {
      return 0;
    },
    execute(config, ctx) {
      return __async(this, null, function* () {
        const animator = ctx.createAnimator();
        if (config.stop) {
          animator.stop();
        } else {
          animator.play(config.name, config.fade);
        }
      });
    }
  };
  var effectDefinition = {
    type: "effect",
    category: "instant",
    label: "特效",
    fields: [
      targetField,
      { name: "path", type: "string", required: true },
      { name: "x", type: "expression", required: false, default: 0 },
      { name: "y", type: "expression", required: false, default: 0 },
      { name: "z", type: "expression", required: false, default: 0 },
      { name: "parent", type: "string", required: false },
      { name: "duration", type: "number", required: false }
    ],
    defaults: {
      type: "effect",
      path: ""
    },
    getDuration(config, evalFn) {
      return 0;
    },
    execute(config, ctx) {
      return __async(this, null, function* () {
        let parent = ctx.target;
        if (config.parent && config.parent !== "/") {
          parent = ctx.findChild(config.parent) || ctx.target;
        }
        yield ctx.effectRunner.play(
          {
            path: config.path,
            x: config.x !== void 0 ? ctx.evalCoord(config.x, "x") : void 0,
            y: config.y !== void 0 ? ctx.evalCoord(config.y, "y") : void 0,
            z: config.z !== void 0 ? ctx.evalCoord(config.z, "z") : void 0,
            parent,
            duration: config.duration
          },
          ctx.target
        );
      });
    }
  };
  var eventDefinition = {
    type: "event",
    category: "instant",
    label: "事件",
    fields: [
      targetField,
      { name: "name", type: "string", required: true },
      { name: "data", type: "object", required: false }
    ],
    defaults: {
      type: "event",
      name: ""
    },
    getDuration(config, evalFn) {
      return 0;
    },
    execute(config, ctx) {
      return __async(this, null, function* () {
        if (ctx.dispatchEvent) {
          ctx.dispatchEvent(config.name, config.data);
        } else if (ctx.target.event) {
          ctx.target.event(config.name, config.data);
        }
      });
    }
  };
  var showDefinition = {
    type: "show",
    category: "instant",
    label: "显示",
    fields: [targetField],
    defaults: {
      type: "show"
    },
    getDuration(config, evalFn) {
      return 0;
    },
    execute(config, ctx) {
      return __async(this, null, function* () {
        if (ctx.target.visible !== void 0) {
          ctx.target.visible = true;
        } else if (ctx.target.active !== void 0) {
          ctx.target.active = true;
        }
      });
    }
  };
  var hideDefinition = {
    type: "hide",
    category: "instant",
    label: "隐藏",
    fields: [targetField],
    defaults: {
      type: "hide"
    },
    getDuration(config, evalFn) {
      return 0;
    },
    execute(config, ctx) {
      return __async(this, null, function* () {
        if (ctx.target.visible !== void 0) {
          ctx.target.visible = false;
        } else if (ctx.target.active !== void 0) {
          ctx.target.active = false;
        }
      });
    }
  };
  var destroyDefinition = {
    type: "destroy",
    category: "instant",
    label: "销毁",
    fields: [targetField],
    defaults: {
      type: "destroy"
    },
    getDuration(config, evalFn) {
      return 0;
    },
    execute(config, ctx) {
      return __async(this, null, function* () {
        if (ctx.target.destroy) {
          ctx.target.destroy();
        }
      });
    }
  };
  var soundDefinition = {
    type: "sound",
    category: "instant",
    label: "音效",
    fields: [
      targetField,
      { name: "path", type: "string", required: true },
      { name: "volume", type: "number", required: false, default: 1 }
    ],
    defaults: {
      type: "sound",
      path: ""
    },
    getDuration(config, evalFn) {
      return 0;
    },
    execute(config, ctx) {
      return __async(this, null, function* () {
        var _a;
        if (ctx.soundPlayer) {
          ctx.soundPlayer.play(config.path, (_a = config.volume) != null ? _a : 1);
        }
      });
    }
  };
  function registerInstantDefinitions() {
    registry.register(animDefinition);
    registry.register(effectDefinition);
    registry.register(eventDefinition);
    registry.register(showDefinition);
    registry.register(hideDefinition);
    registry.register(destroyDefinition);
    registry.register(soundDefinition);
  }
  __name(registerInstantDefinitions, "registerInstantDefinitions");

  // src/Common/Action/Schema/Definitions/Tween.ts
  var targetField2 = { name: "target", type: "string", required: false };
  var moveToDefinition = {
    type: "moveTo",
    category: "tween",
    label: "移动到",
    fields: [
      targetField2,
      { name: "x", type: "expression", required: true, default: 0 },
      { name: "y", type: "expression", required: true, default: 0 },
      { name: "z", type: "expression", required: false, default: 0 },
      { name: "duration", type: "expression", required: true, default: 1 },
      { name: "ease", type: "string", required: false, default: "linear" }
    ],
    defaults: {
      type: "moveTo",
      x: 0,
      y: 0,
      duration: 1
    },
    getDuration(config, evalFn) {
      return evalFn(config.duration) * 1e3;
    },
    execute(config, ctx) {
      return __async(this, null, function* () {
        const x = ctx.evalCoord(config.x, "x");
        const y = ctx.evalCoord(config.y, "y");
        const props = {};
        if (ctx.is3D) {
          const transform = ctx.target.transform;
          if (transform) {
            props.localPositionX = x;
            props.localPositionY = y;
            if (config.z !== void 0) {
              props.localPositionZ = ctx.evalCoord(config.z, "z");
            }
            yield ctx.tweenRunner.tween(transform, { props, duration: ctx.duration, ease: config.ease });
          }
        } else {
          props.x = x;
          props.y = y;
          yield ctx.tweenRunner.tween(ctx.target, { props, duration: ctx.duration, ease: config.ease });
        }
      });
    }
  };
  var moveByDefinition = {
    type: "moveBy",
    category: "tween",
    label: "移动",
    fields: [
      targetField2,
      { name: "x", type: "expression", required: true, default: 0 },
      { name: "y", type: "expression", required: true, default: 0 },
      { name: "z", type: "expression", required: false, default: 0 },
      { name: "duration", type: "expression", required: true, default: 1 },
      { name: "ease", type: "string", required: false, default: "linear" }
    ],
    defaults: {
      type: "moveBy",
      x: 0,
      y: 0,
      duration: 1
    },
    getDuration(config, evalFn) {
      return evalFn(config.duration) * 1e3;
    },
    execute(config, ctx) {
      return __async(this, null, function* () {
        const dx = ctx.eval(config.x);
        const dy = ctx.eval(config.y);
        const dz = config.z !== void 0 ? ctx.eval(config.z) : 0;
        const props = {};
        if (ctx.is3D) {
          const transform = ctx.target.transform;
          if (transform) {
            props.localPositionX = transform.localPositionX + dx;
            props.localPositionY = transform.localPositionY + dy;
            props.localPositionZ = transform.localPositionZ + dz;
            yield ctx.tweenRunner.tween(transform, { props, duration: ctx.duration, ease: config.ease });
          }
        } else {
          props.x = ctx.target.x + dx;
          props.y = ctx.target.y + dy;
          yield ctx.tweenRunner.tween(ctx.target, { props, duration: ctx.duration, ease: config.ease });
        }
      });
    }
  };
  var moveTowardDefinition = {
    type: "moveToward",
    category: "tween",
    label: "朝向移动",
    fields: [
      targetField2,
      { name: "x", type: "expression", required: true, default: 0 },
      { name: "y", type: "expression", required: true, default: 0 },
      { name: "ratio", type: "expression", required: true, default: 1 },
      { name: "duration", type: "expression", required: true, default: 1 },
      { name: "ease", type: "string", required: false, default: "linear" }
    ],
    defaults: {
      type: "moveToward",
      x: 0,
      y: 0,
      ratio: 1,
      duration: 1
    },
    getDuration(config, evalFn) {
      return evalFn(config.duration) * 1e3;
    },
    execute(config, ctx) {
      return __async(this, null, function* () {
        var _a, _b, _c, _d, _e, _f;
        const targetX = ctx.evalCoord(config.x, "x");
        const targetY = ctx.evalCoord(config.y, "y");
        const ratio = ctx.eval(config.ratio);
        const currentX = ctx.is3D ? (_b = (_a = ctx.target.transform) == null ? void 0 : _a.localPositionX) != null ? _b : 0 : (_c = ctx.target.x) != null ? _c : 0;
        const currentY = ctx.is3D ? (_e = (_d = ctx.target.transform) == null ? void 0 : _d.localPositionY) != null ? _e : 0 : (_f = ctx.target.y) != null ? _f : 0;
        const finalX = currentX + (targetX - currentX) * ratio;
        const finalY = currentY + (targetY - currentY) * ratio;
        const props = {};
        if (ctx.is3D) {
          const transform = ctx.target.transform;
          if (transform) {
            props.localPositionX = finalX;
            props.localPositionY = finalY;
            yield ctx.tweenRunner.tween(transform, { props, duration: ctx.duration, ease: config.ease });
          }
        } else {
          props.x = finalX;
          props.y = finalY;
          yield ctx.tweenRunner.tween(ctx.target, { props, duration: ctx.duration, ease: config.ease });
        }
      });
    }
  };
  var scaleToDefinition = {
    type: "scaleTo",
    category: "tween",
    label: "缩放到",
    fields: [
      targetField2,
      { name: "x", type: "expression", required: true, default: 1 },
      { name: "y", type: "expression", required: true, default: 1 },
      { name: "z", type: "expression", required: false, default: 1 },
      { name: "duration", type: "expression", required: true, default: 1 },
      { name: "ease", type: "string", required: false, default: "linear" }
    ],
    defaults: {
      type: "scaleTo",
      x: 1,
      y: 1,
      duration: 1
    },
    getDuration(config, evalFn) {
      return evalFn(config.duration) * 1e3;
    },
    execute(config, ctx) {
      return __async(this, null, function* () {
        const x = ctx.eval(config.x);
        const y = ctx.eval(config.y);
        const props = {};
        if (ctx.is3D) {
          const transform = ctx.target.transform;
          if (transform) {
            props.localScaleX = x;
            props.localScaleY = y;
            if (config.z !== void 0) {
              props.localScaleZ = ctx.eval(config.z);
            }
            yield ctx.tweenRunner.tween(transform, { props, duration: ctx.duration, ease: config.ease });
          }
        } else {
          props.scaleX = x;
          props.scaleY = y;
          yield ctx.tweenRunner.tween(ctx.target, { props, duration: ctx.duration, ease: config.ease });
        }
      });
    }
  };
  var scaleByDefinition = {
    type: "scaleBy",
    category: "tween",
    label: "缩放",
    fields: [
      targetField2,
      { name: "x", type: "expression", required: true, default: 1 },
      { name: "y", type: "expression", required: true, default: 1 },
      { name: "z", type: "expression", required: false, default: 1 },
      { name: "duration", type: "expression", required: true, default: 1 },
      { name: "ease", type: "string", required: false, default: "linear" }
    ],
    defaults: {
      type: "scaleBy",
      x: 1,
      y: 1,
      duration: 1
    },
    getDuration(config, evalFn) {
      return evalFn(config.duration) * 1e3;
    },
    execute(config, ctx) {
      return __async(this, null, function* () {
        var _a, _b;
        const fx = ctx.eval(config.x);
        const fy = ctx.eval(config.y);
        const props = {};
        if (ctx.is3D) {
          const transform = ctx.target.transform;
          if (transform) {
            props.localScaleX = transform.localScaleX * fx;
            props.localScaleY = transform.localScaleY * fy;
            if (config.z !== void 0) {
              props.localScaleZ = transform.localScaleZ * ctx.eval(config.z);
            }
            yield ctx.tweenRunner.tween(transform, { props, duration: ctx.duration, ease: config.ease });
          }
        } else {
          props.scaleX = ((_a = ctx.target.scaleX) != null ? _a : 1) * fx;
          props.scaleY = ((_b = ctx.target.scaleY) != null ? _b : 1) * fy;
          yield ctx.tweenRunner.tween(ctx.target, { props, duration: ctx.duration, ease: config.ease });
        }
      });
    }
  };
  var rotateToDefinition = {
    type: "rotateTo",
    category: "tween",
    label: "旋转到",
    fields: [
      targetField2,
      { name: "angle", type: "expression", required: true, default: 0 },
      { name: "axis", type: "string", required: false, default: "z" },
      { name: "duration", type: "expression", required: true, default: 1 },
      { name: "ease", type: "string", required: false, default: "linear" }
    ],
    defaults: {
      type: "rotateTo",
      angle: 0,
      duration: 1
    },
    getDuration(config, evalFn) {
      return evalFn(config.duration) * 1e3;
    },
    execute(config, ctx) {
      return __async(this, null, function* () {
        const angle = ctx.eval(config.angle);
        const axis = config.axis || "z";
        const props = {};
        if (ctx.is3D) {
          const transform = ctx.target.transform;
          if (transform) {
            const propName = `localRotationEuler${axis.toUpperCase()}`;
            props[propName] = angle;
            yield ctx.tweenRunner.tween(transform, { props, duration: ctx.duration, ease: config.ease });
          }
        } else {
          props.rotation = angle;
          yield ctx.tweenRunner.tween(ctx.target, { props, duration: ctx.duration, ease: config.ease });
        }
      });
    }
  };
  var rotateByDefinition = {
    type: "rotateBy",
    category: "tween",
    label: "旋转",
    fields: [
      targetField2,
      { name: "angle", type: "expression", required: true, default: 0 },
      { name: "axis", type: "string", required: false, default: "z" },
      { name: "duration", type: "expression", required: true, default: 1 },
      { name: "ease", type: "string", required: false, default: "linear" }
    ],
    defaults: {
      type: "rotateBy",
      angle: 0,
      duration: 1
    },
    getDuration(config, evalFn) {
      return evalFn(config.duration) * 1e3;
    },
    execute(config, ctx) {
      return __async(this, null, function* () {
        const deltaAngle = ctx.eval(config.angle);
        const axis = config.axis || "z";
        const props = {};
        if (ctx.is3D) {
          const transform = ctx.target.transform;
          if (transform) {
            const propName = `localRotationEuler${axis.toUpperCase()}`;
            props[propName] = transform[propName] + deltaAngle;
            yield ctx.tweenRunner.tween(transform, { props, duration: ctx.duration, ease: config.ease });
          }
        } else {
          props.rotation = (ctx.target.rotation || 0) + deltaAngle;
          yield ctx.tweenRunner.tween(ctx.target, { props, duration: ctx.duration, ease: config.ease });
        }
      });
    }
  };
  var fadeToDefinition = {
    type: "fadeTo",
    category: "tween",
    label: "淡入淡出",
    fields: [
      targetField2,
      { name: "alpha", type: "expression", required: true, default: 1 },
      { name: "duration", type: "expression", required: true, default: 1 },
      { name: "ease", type: "string", required: false, default: "linear" }
    ],
    defaults: {
      type: "fadeTo",
      alpha: 1,
      duration: 1
    },
    getDuration(config, evalFn) {
      return evalFn(config.duration) * 1e3;
    },
    execute(config, ctx) {
      return __async(this, null, function* () {
        const alpha = ctx.eval(config.alpha);
        yield ctx.tweenRunner.tween(ctx.target, {
          props: { alpha },
          duration: ctx.duration,
          ease: config.ease
        });
      });
    }
  };
  var waitDefinition = {
    type: "wait",
    category: "tween",
    label: "等待",
    fields: [
      targetField2,
      { name: "duration", type: "expression", required: true, default: 1 }
    ],
    defaults: {
      type: "wait",
      duration: 1
    },
    getDuration(config, evalFn) {
      return evalFn(config.duration) * 1e3;
    },
    execute(config, ctx) {
      return __async(this, null, function* () {
        yield ctx.tweenRunner.delay(ctx.duration);
      });
    }
  };
  function registerTweenDefinitions() {
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
  __name(registerTweenDefinitions, "registerTweenDefinitions");

  // src/Common/Action/ActionPlayer.ts
  registerTweenDefinitions();
  registerInstantDefinitions();
  var { regClass: regClass3, property: property3 } = Laya;
  var ActionPlayer = class extends Laya.Script {
    constructor() {
      super(...arguments);
      this.json = "";
      this._controller = null;
      this._variables = {};
      this._playToken = 0;
    }
    onEnable() {
      void this.play();
    }
    onDisable() {
      this.stop();
    }
    onDestroy() {
      this.stop();
    }
    /**
     * 设置变量（覆盖 JSON 内同名变量）
     */
    setVariables(variables) {
      this._variables = __spreadValues({}, variables);
    }
    /**
     * 获取当前控制器
     */
    get controller() {
      return this._controller;
    }
    /**
     * 是否正在播放
     */
    get isPlaying() {
      var _a, _b;
      return (_b = (_a = this._controller) == null ? void 0 : _a.running) != null ? _b : false;
    }
    /**
     * 播放
     */
    play(variables) {
      return __async(this, null, function* () {
        var _a;
        if (!this.owner) {
          console.warn("[ActionPlayer] owner 不存在");
          return null;
        }
        const jsonPath = (_a = this.json) == null ? void 0 : _a.trim();
        if (!jsonPath) {
          console.warn("[ActionPlayer] json 为空");
          return null;
        }
        if (variables) {
          this._variables = __spreadValues(__spreadValues({}, this._variables), variables);
        }
        this.stop();
        const playToken = ++this._playToken;
        let jsonData;
        try {
          const res = yield Laya.loader.load(jsonPath, Laya.Loader.JSON);
          if (!(res == null ? void 0 : res.data)) {
            throw new Error("JSON 数据为空");
          }
          jsonData = res.data;
        } catch (err) {
          console.error(`[ActionPlayer] JSON 加载失败: ${jsonPath}`, err);
          return null;
        }
        if (playToken !== this._playToken) {
          return null;
        }
        const mergedVariables = __spreadValues(__spreadValues({}, jsonData.variables), this._variables);
        const context = createContext({
          variables: mergedVariables,
          world: this._getWorldBounds(),
          seed: Date.now(),
          is3D: this._is3DTarget()
        });
        const engine = createEngine(context);
        const { plan, diagnostics } = compileToRuntime(__spreadProps(__spreadValues({}, jsonData), { variables: mergedVariables }), { engine });
        if (diagnostics.length > 0) {
          console.warn("[ActionPlayer] 编译警告:", diagnostics);
        }
        const controller = createController();
        this._controller = controller;
        void execute(plan, this.owner, engine, controller, (name, data) => {
          var _a2, _b;
          (_b = (_a2 = this.owner) == null ? void 0 : _a2.event) == null ? void 0 : _b.call(_a2, name, data);
        });
        return controller;
      });
    }
    /**
     * 停止
     */
    stop() {
      if (this._controller) {
        this._controller.stop();
        this._controller = null;
      }
      this._playToken++;
    }
    _getWorldBounds() {
      var _a, _b;
      const stage = Laya.stage;
      return {
        width: (_a = stage == null ? void 0 : stage.width) != null ? _a : 1920,
        height: (_b = stage == null ? void 0 : stage.height) != null ? _b : 1080,
        depth: 1e3
      };
    }
    _is3DTarget() {
      const owner = this.owner;
      return !!(owner == null ? void 0 : owner.transform) && typeof owner.transform.localPosition !== "undefined";
    }
  };
  __name(ActionPlayer, "ActionPlayer");
  __decorateClass([
    property3({
      type: String,
      caption: "Action JSON",
      tips: "拖拽 JSON 文件到此处",
      isAsset: true,
      assetTypeFilter: "Json",
      useAssetPath: true
    })
  ], ActionPlayer.prototype, "json", 2);
  ActionPlayer = __decorateClass([
    regClass3("3d1f1f83-81f1-4360-bbe5-28a124ee7d44", "../src/Common/Action/ActionPlayer.ts")
  ], ActionPlayer);

  // src/Common/Adapter/BackgroundScaler.ts
  var { regClass: regClass4, property: property4 } = Laya;
  var BackgroundScaler = class extends Laya.Script {
    constructor() {
      super(...arguments);
      this.camera = null;
      this.keepAspectRatio = false;
      this.cameraForward = new Laya.Vector3();
      this.cameraToSprite = new Laya.Vector3();
    }
    onEnable() {
      Laya.stage.on(Laya.Event.RESIZE, this, this.updateSize);
      Laya.timer.callLater(this, this.updateSize);
    }
    onDisable() {
      Laya.stage.off(Laya.Event.RESIZE, this, this.updateSize);
      Laya.timer.clear(this, this.updateSize);
    }
    updateSize() {
      if (!this.camera || Laya.stage.width <= 0 || Laya.stage.height <= 0) {
        return;
      }
      const sprite = this.owner;
      if (!sprite) {
        return;
      }
      const cameraAspectRatio = this.camera.aspectRatio;
      let width;
      let height;
      if (this.camera.orthographic) {
        height = this.camera.orthographicVerticalSize;
        width = height * cameraAspectRatio;
      } else {
        const distance = this.getDistanceToCamera(sprite);
        if (distance <= 0) {
          return;
        }
        const fovRadians = this.camera.fieldOfView * Math.PI / 180;
        height = 2 * distance * Math.tan(fovRadians / 2);
        width = height * cameraAspectRatio;
      }
      if (this.keepAspectRatio) {
        const textureAspectRatio = this.getTextureAspectRatio(sprite);
        if (textureAspectRatio > 0) {
          if (textureAspectRatio < cameraAspectRatio) {
            height = width / textureAspectRatio;
          } else {
            width = height * textureAspectRatio;
          }
        }
      }
      const localScale = sprite.transform.localScale;
      sprite.transform.localScale = new Laya.Vector3(width, height, localScale.z);
    }
    getDistanceToCamera(sprite) {
      this.camera.transform.getForward(this.cameraForward);
      Laya.Vector3.normalize(this.cameraForward, this.cameraForward);
      Laya.Vector3.subtract(sprite.transform.position, this.camera.transform.position, this.cameraToSprite);
      return Math.abs(Laya.Vector3.dot(this.cameraToSprite, this.cameraForward));
    }
    getTextureAspectRatio(sprite) {
      var _a, _b;
      const renderer = sprite.getComponent(Laya.MeshRenderer);
      const material = renderer == null ? void 0 : renderer.sharedMaterial;
      if (!material) {
        return 0;
      }
      for (const propertyName of BackgroundScaler.TEXTURE_PROPERTY_NAMES) {
        const texture = material.getTexture(propertyName);
        if (!texture) {
          continue;
        }
        const textureWidth = (_a = texture.sourceWidth) != null ? _a : texture.width;
        const textureHeight = (_b = texture.sourceHeight) != null ? _b : texture.height;
        if (textureWidth > 0 && textureHeight > 0) {
          return textureWidth / textureHeight;
        }
      }
      return 0;
    }
  };
  __name(BackgroundScaler, "BackgroundScaler");
  BackgroundScaler.TEXTURE_PROPERTY_NAMES = [
    "u_AlbedoTexture",
    "u_MainTex",
    "u_BaseMap",
    "u_BaseTexture",
    "u_DiffuseTexture"
  ];
  __decorateClass([
    property4(Laya.Camera)
  ], BackgroundScaler.prototype, "camera", 2);
  __decorateClass([
    property4({ type: Boolean, caption: "保持宽高比" })
  ], BackgroundScaler.prototype, "keepAspectRatio", 2);
  BackgroundScaler = __decorateClass([
    regClass4("d8d355b3-023a-4fe6-a2d7-e0dc596f0aa5", "../src/Common/Adapter/BackgroundScaler.ts")
  ], BackgroundScaler);

  // src/Common/Adapter/FillParent.ts
  var { regClass: regClass5, property: property5 } = Laya;
  var FillParent = class extends Laya.Script {
    constructor() {
      super(...arguments);
      this._fillParent = false;
      this._keepAspectRatio = false;
    }
    get fillParent() {
      return this._fillParent;
    }
    set fillParent(value) {
      this._fillParent = value;
      if (value) {
        this.scheduleApplyFillParent();
        this._fillParent = false;
      }
    }
    get keepAspectRatio() {
      return this._keepAspectRatio;
    }
    set keepAspectRatio(value) {
      if (this._keepAspectRatio === value) {
        return;
      }
      this._keepAspectRatio = value;
      this.scheduleApplyFillParent();
    }
    onEnable() {
      Laya.stage.on(Laya.Event.RESIZE, this, this.scheduleApplyFillParent);
      this.owner.on(Laya.Event.LOADED, this, this.scheduleApplyFillParent);
      this.scheduleApplyFillParent();
    }
    onDisable() {
      Laya.stage.off(Laya.Event.RESIZE, this, this.scheduleApplyFillParent);
      this.owner.off(Laya.Event.LOADED, this, this.scheduleApplyFillParent);
      Laya.timer.clear(this, this.applyFillParent);
    }
    scheduleApplyFillParent() {
      Laya.timer.callLater(this, this.applyFillParent);
    }
    applyFillParent() {
      var _a, _b;
      const owner = this.owner;
      if (!owner) {
        return;
      }
      const parent = owner.parent;
      if (!parent) {
        return;
      }
      const parentWidth = this.getContainerWidth(parent);
      const parentHeight = this.getContainerHeight(parent);
      if (parentWidth <= 0 || parentHeight <= 0) {
        return;
      }
      let newWidth = parentWidth;
      let newHeight = parentHeight;
      let offsetX = 0;
      let offsetY = 0;
      if (this._keepAspectRatio) {
        const texture = owner.texture;
        const textureWidth = texture ? (_a = texture.sourceWidth) != null ? _a : texture.width : 0;
        const textureHeight = texture ? (_b = texture.sourceHeight) != null ? _b : texture.height : 0;
        const sourceWidth = textureWidth > 0 ? textureWidth : owner.width;
        const sourceHeight = textureHeight > 0 ? textureHeight : owner.height;
        if (sourceWidth <= 0 || sourceHeight <= 0) {
          return;
        }
        const originalRatio = sourceWidth / sourceHeight;
        const parentRatio = parentWidth / parentHeight;
        if (originalRatio < parentRatio) {
          newHeight = parentWidth / originalRatio;
        } else {
          newWidth = parentHeight * originalRatio;
        }
        offsetX = (parentWidth - newWidth) / 2;
        offsetY = (parentHeight - newHeight) / 2;
      }
      owner.width = newWidth;
      owner.height = newHeight;
      owner.x = offsetX;
      owner.y = offsetY;
      owner.anchorX = 0;
      owner.anchorY = 0;
      owner.scaleX = 1;
      owner.scaleY = 1;
    }
    getContainerWidth(parent) {
      const parentSprite = parent;
      return parentSprite.width > 0 ? parentSprite.width : Laya.stage.width || Laya.stage.designWidth;
    }
    getContainerHeight(parent) {
      const parentSprite = parent;
      return parentSprite.height > 0 ? parentSprite.height : Laya.stage.height || Laya.stage.designHeight;
    }
  };
  __name(FillParent, "FillParent");
  __decorateClass([
    property5({ type: Boolean, caption: "铺满父节点" })
  ], FillParent.prototype, "fillParent", 1);
  __decorateClass([
    property5({ type: Boolean, caption: "保持宽高比" })
  ], FillParent.prototype, "keepAspectRatio", 1);
  FillParent = __decorateClass([
    regClass5("c35ca088-0557-4d92-9c1f-2d9be6622030", "../src/Common/Adapter/FillParent.ts")
  ], FillParent);

  // src/Common/Adapter/OrthoCameraScaler.ts
  var { regClass: regClass6, property: property6 } = Laya;
  var OrthoCameraScaler = class extends Laya.Script {
    constructor() {
      super(...arguments);
      this.pixelsPerUnit = 100;
    }
    onEnable() {
      Laya.stage.on(Laya.Event.RESIZE, this, this.refreshCameraSize);
      Laya.timer.callLater(this, this.refreshCameraSize);
    }
    onDisable() {
      Laya.stage.off(Laya.Event.RESIZE, this, this.refreshCameraSize);
      Laya.timer.clear(this, this.refreshCameraSize);
    }
    refreshCameraSize() {
      const camera = this.owner;
      if (!camera || !camera.orthographic || this.pixelsPerUnit <= 0) {
        return;
      }
      camera.orthographicVerticalSize = Laya.stage.height / this.pixelsPerUnit;
    }
  };
  __name(OrthoCameraScaler, "OrthoCameraScaler");
  __decorateClass([
    property6(Number)
  ], OrthoCameraScaler.prototype, "pixelsPerUnit", 2);
  OrthoCameraScaler = __decorateClass([
    regClass6("302ddf39-08f2-4926-bbe3-974b431cfdae", "../src/Common/Adapter/OrthoCameraScaler.ts")
  ], OrthoCameraScaler);

  // src/Common/UI/SpriteFont.ts
  var { regClass: regClass7, property: property7 } = Laya;
  var VALIGN_MAP = {
    "top": 0 /* TOP */,
    "middle": 1 /* MIDDLE */,
    "bottom": 2 /* BOTTOM */
  };
  var HALIGN_MAP = {
    "left": 0 /* LEFT */,
    "center": 1 /* CENTER */,
    "right": 2 /* RIGHT */
  };
  var SpriteFont = class extends Laya.Script {
    constructor() {
      super(...arguments);
      /** 字符渲染信息映射：char -> ICharRenderInfo */
      this._charMap = /* @__PURE__ */ Object.create(null);
      /** 字体配置 */
      this._config = null;
      /** 是否需要刷新 */
      this._needRefresh = false;
      /** 是否已加载完成 */
      this._loaded = false;
      /** 未知字符的默认宽度 */
      this._defaultCharWidth = 20;
      /** 加载序号（防止异步覆盖） */
      this._loadId = 0;
      /** 上一次渲染的文本 */
      this._lastText = "";
      /** 上一次的字符间距 */
      this._lastLetterSpacing = 0;
      /** 上一次的水平对齐 */
      this._lastAlignX = 0 /* LEFT */;
      /** 上一次的垂直对齐 */
      this._lastAlignY = 2 /* BOTTOM */;
      /** 字体配置路径 */
      this._fontConfig = "";
      /** 当前显示的文本 */
      this._text = "";
      /** 字符间额外间距 */
      this._letterSpacing = 0;
      /** 字符内水平对齐 */
      this._charAlignX = 0 /* LEFT */;
      /** 字符内垂直对齐 */
      this._charAlignY = 2 /* BOTTOM */;
      /** 缓存的总宽度 */
      this._cachedWidth = 0;
      /** 缓存的总高度 */
      this._cachedHeight = 0;
    }
    get fontConfig() {
      return this._fontConfig;
    }
    set fontConfig(v) {
      if (this._fontConfig === v) return;
      this._fontConfig = v;
      if (v) {
        this.loadFont(v);
      } else {
        this._clearFont();
      }
    }
    get text() {
      return this._text;
    }
    set text(v) {
      const newValue = v != null ? v : "";
      if (this._text === newValue) return;
      this._text = newValue;
      this._markRefresh();
    }
    get letterSpacing() {
      return this._letterSpacing;
    }
    set letterSpacing(v) {
      if (this._letterSpacing === v) return;
      this._letterSpacing = v;
      this._markRefresh();
    }
    get charAlignX() {
      return this._charAlignX === 0 /* LEFT */ ? "left" : this._charAlignX === 1 /* CENTER */ ? "center" : "right";
    }
    set charAlignX(v) {
      var _a;
      const alignValue = (_a = HALIGN_MAP[v]) != null ? _a : 0 /* LEFT */;
      if (this._charAlignX === alignValue) return;
      this._charAlignX = alignValue;
      this._markRefresh();
    }
    get charAlignY() {
      return this._charAlignY === 0 /* TOP */ ? "top" : this._charAlignY === 1 /* MIDDLE */ ? "middle" : "bottom";
    }
    set charAlignY(v) {
      var _a;
      const alignValue = (_a = VALIGN_MAP[v]) != null ? _a : 2 /* BOTTOM */;
      if (this._charAlignY === alignValue) return;
      this._charAlignY = alignValue;
      this._markRefresh();
    }
    get cachedWidth() {
      return this._cachedWidth;
    }
    get cachedHeight() {
      return this._cachedHeight;
    }
    get isLoaded() {
      return this._loaded;
    }
    /**
     * 加载字体配置
     */
    loadFont(configPath) {
      this._clearPendingRefresh();
      this._fontConfig = configPath;
      this._loaded = false;
      const loadId = ++this._loadId;
      Laya.loader.load(configPath).then((res) => {
        var _a;
        if (this.destroyed || this._loadId !== loadId) return null;
        const config = (_a = res == null ? void 0 : res.data) != null ? _a : res;
        if (!config || !Array.isArray(config.chars)) {
          console.error("[SpriteFont] 加载配置失败:", configPath);
          return null;
        }
        this._config = config;
        const imagePaths = [];
        const seen = /* @__PURE__ */ Object.create(null);
        const chars = config.chars;
        for (let i = 0, len = chars.length; i < len; i++) {
          const charConfig = chars[i];
          const image = charConfig == null ? void 0 : charConfig.image;
          if (image && !seen[image]) {
            seen[image] = true;
            imagePaths.push(image);
          }
        }
        if (imagePaths.length === 0) {
          return true;
        }
        return Laya.loader.load(imagePaths);
      }).then(() => {
        if (this.destroyed || this._loadId !== loadId || !this._config) return;
        this._buildCharMap();
        this._loaded = true;
        this._refresh();
      }).catch((err) => {
        if (!this.destroyed) {
          console.error("[SpriteFont] 加载配置异常:", configPath, err);
        }
      });
    }
    /**
     * 获取文本渲染宽度
     */
    measureWidth(text) {
      const str = text != null ? text : this._text;
      if (!str || !this._loaded) return 0;
      const charMap = this._charMap;
      const letterSpacing = this._letterSpacing;
      const defaultWidth = this._defaultCharWidth;
      const len = str.length;
      let width = 0;
      for (let i = 0; i < len; i++) {
        const info = charMap[str[i]];
        width += (info ? info.advance : defaultWidth) + letterSpacing;
      }
      return len > 0 ? width - letterSpacing : 0;
    }
    /**
     * 获取行高
     */
    getLineHeight() {
      var _a, _b;
      return (_b = (_a = this._config) == null ? void 0 : _a.lineHeight) != null ? _b : 0;
    }
    reset() {
      this._clearPendingRefresh();
      this._text = "";
      this._letterSpacing = 0;
      this._charAlignX = 0 /* LEFT */;
      this._charAlignY = 2 /* BOTTOM */;
      this._lastText = "";
      const sprite = this.owner;
      if (sprite && !sprite.destroyed) {
        sprite.graphics.clear(true);
        sprite.size(0, 0);
      }
    }
    forceRefresh() {
      if (this._loaded) {
        this._refresh(true);
      }
    }
    onEnable() {
      this._suppressHostTextOverlay();
      if (this._fontConfig && !this._loaded) {
        this.loadFont(this._fontConfig);
      } else if (this._loaded && this._text) {
        this._markRefresh();
      }
    }
    /**
     * GTextField 用子节点 textIns 绘字，会盖住父节点 graphics；Laya.Text 则与 graphics 同源，typeset 会 clear。
     * 使用 SpriteFont 时应关闭宿主文字绘制，仅保留位图。
     */
    _suppressHostTextOverlay() {
      const owner = this.owner;
      if (owner && owner.textIns) {
        owner.textIns.text = "";
        owner.textIns.hideText(true);
        return;
      }
      if (this.owner instanceof Laya.Text) {
        this.owner.text = "";
        this.owner.hideText(true);
      }
    }
    onDisable() {
      this._clearPendingRefresh();
    }
    onDestroy() {
      this._clearPendingRefresh();
      this._clearCharMap();
      this._config = null;
      this._loaded = false;
      this._lastText = "";
    }
    _clearFont() {
      this.reset();
      this._clearCharMap();
      this._config = null;
      this._loaded = false;
    }
    _clearCharMap() {
      const charMap = this._charMap;
      for (const key in charMap) {
        delete charMap[key];
      }
    }
    _clearPendingRefresh() {
      Laya.timer.clearCallLater(this, this._refresh);
      this._needRefresh = false;
    }
    _buildCharMap() {
      this._clearCharMap();
      const config = this._config;
      if (!config) return;
      const charMap = this._charMap;
      const chars = config.chars;
      for (let i = 0, len = chars.length; i < len; i++) {
        const charConfig = chars[i];
        if (!(charConfig == null ? void 0 : charConfig.char) || !charConfig.image) continue;
        const texture = Laya.loader.getRes(charConfig.image);
        if (!texture) {
          console.warn("[SpriteFont] 找不到图片:", charConfig.image);
          continue;
        }
        charMap[charConfig.char] = this._createCharInfo(charConfig, texture);
      }
    }
    _createCharInfo(charConfig, texture) {
      var _a, _b, _c, _d, _e;
      const sourceWidth = texture.sourceWidth || texture.width;
      const sourceHeight = texture.sourceHeight || texture.height;
      return {
        texture,
        width: texture.width,
        height: texture.height,
        sourceWidth,
        sourceHeight,
        advance: (_a = charConfig.advance) != null ? _a : sourceWidth,
        offsetX: (_c = (_b = charConfig.offsetX) != null ? _b : texture.offsetX) != null ? _c : 0,
        offsetY: (_e = (_d = charConfig.offsetY) != null ? _d : texture.offsetY) != null ? _e : 0
      };
    }
    _markRefresh() {
      if (!this._loaded || this._needRefresh) return;
      this._needRefresh = true;
      Laya.timer.callLater(this, this._refresh);
    }
    _refresh(force = false) {
      var _a, _b;
      this._needRefresh = false;
      const sprite = this.owner;
      if (!sprite || sprite.destroyed) return;
      const text = this._text;
      const g = sprite.graphics;
      if (!text || !this._loaded) {
        if (this._lastText) {
          g.clear(true);
          sprite.size(0, 0);
          this._cachedWidth = 0;
          this._cachedHeight = 0;
          this._lastText = "";
        }
        return;
      }
      const letterSpacing = this._letterSpacing;
      const alignX = this._charAlignX;
      const alignY = this._charAlignY;
      const needRedraw = force || text !== this._lastText || letterSpacing !== this._lastLetterSpacing || alignX !== this._lastAlignX || alignY !== this._lastAlignY;
      if (!needRedraw) return;
      this._lastText = text;
      this._lastLetterSpacing = letterSpacing;
      this._lastAlignX = alignX;
      this._lastAlignY = alignY;
      g.clear(true);
      const charMap = this._charMap;
      const defaultWidth = this._defaultCharWidth;
      const textLength = text.length;
      const configLineHeight = (_b = (_a = this._config) == null ? void 0 : _a.lineHeight) != null ? _b : 0;
      let totalWidth = 0;
      let maxHeight = 0;
      for (let i = 0; i < textLength; i++) {
        const info = charMap[text[i]];
        if (info) {
          totalWidth += info.advance;
          if (info.sourceHeight > maxHeight) {
            maxHeight = info.sourceHeight;
          }
        } else {
          totalWidth += defaultWidth;
        }
      }
      if (textLength > 1) {
        totalWidth += letterSpacing * (textLength - 1);
      }
      const lineHeight = configLineHeight || maxHeight;
      this._cachedWidth = totalWidth;
      this._cachedHeight = lineHeight;
      sprite.size(totalWidth, lineHeight);
      let x = 0;
      for (let i = 0; i < textLength; i++) {
        const info = charMap[text[i]];
        if (info) {
          let alignOffsetX = 0;
          if (alignX === 1 /* CENTER */) {
            alignOffsetX = (info.advance - info.sourceWidth) * 0.5;
          } else if (alignX === 2 /* RIGHT */) {
            alignOffsetX = info.advance - info.sourceWidth;
          }
          let alignOffsetY = 0;
          if (alignY === 2 /* BOTTOM */) {
            alignOffsetY = lineHeight - info.sourceHeight;
          } else if (alignY === 1 /* MIDDLE */) {
            alignOffsetY = (lineHeight - info.sourceHeight) * 0.5;
          }
          g.drawImage(
            info.texture,
            x + alignOffsetX + info.offsetX,
            alignOffsetY + info.offsetY,
            info.width,
            info.height
          );
          x += info.advance + letterSpacing;
        } else {
          x += defaultWidth + letterSpacing;
        }
      }
    }
  };
  __name(SpriteFont, "SpriteFont");
  __decorateClass([
    property7({
      type: String,
      caption: "字体配置",
      isAsset: true,
      assetTypeFilter: "Json",
      useAssetPath: true
    })
  ], SpriteFont.prototype, "fontConfig", 1);
  __decorateClass([
    property7({ type: String, caption: "文本" })
  ], SpriteFont.prototype, "text", 1);
  __decorateClass([
    property7({ type: Number, caption: "字符间距" })
  ], SpriteFont.prototype, "letterSpacing", 1);
  __decorateClass([
    property7({
      type: String,
      caption: "字符水平对齐",
      enumSource: ["left", "center", "right"]
    })
  ], SpriteFont.prototype, "charAlignX", 1);
  __decorateClass([
    property7({
      type: String,
      caption: "字符垂直对齐",
      enumSource: ["top", "middle", "bottom"]
    })
  ], SpriteFont.prototype, "charAlignY", 1);
  SpriteFont = __decorateClass([
    regClass7("05e47252-26f1-4398-8c39-eb6be70d580b", "../src/Common/UI/SpriteFont.ts")
  ], SpriteFont);

  // src/Main.ts
  var { regClass: regClass8 } = Laya;
  var Main = class extends Laya.Script {
    onAwake() {
      return __async(this, null, function* () {
        Laya.stage.addChild(this.owner);
      });
    }
    onUpdate() {
    }
  };
  __name(Main, "Main");
  Main = __decorateClass([
    regClass8("55a5ed52-ed81-4244-a49c-92dc0ed001ba", "../src/Main.ts")
  ], Main);

  // src/MaterialFitCapture.ts
  var { regClass: regClass9, property: property8 } = Laya;
  var MaterialFitCapture = class extends Laya.Script3D {
    constructor() {
      super(...arguments);
      this.serverBaseUrl = "http://127.0.0.1:8787";
      this.cameraName = "";
      this.targetName = "";
      this.pollIntervalMs = 500;
      this.autoPoll = true;
      this._busy = false;
      this._lastNonce = "";
      this._nextPollAt = 0;
      this._pollFailureCount = 0;
      this._referenceCache = /* @__PURE__ */ new Map();
    }
    onEnable() {
      Laya.Browser.window.__materialFitCapture = (command) => this.capture(command);
      if (this.autoPoll) {
        Laya.timer.loop(Math.max(100, this.pollIntervalMs), this, this.pollCommand);
        Laya.timer.once(100, this, this.pollCommand);
      }
    }
    onDisable() {
      Laya.timer.clear(this, this.pollCommand);
    }
    pollCommand() {
      return __async(this, null, function* () {
        if (this._busy) {
          return;
        }
        if (Date.now() < this._nextPollAt) {
          return;
        }
        try {
          const url = `${this.serverBaseUrl}/material-fit/capture-command?last_nonce=${encodeURIComponent(this._lastNonce)}`;
          const response = yield fetch(url);
          if (!response.ok) {
            this.schedulePollRetry();
            return;
          }
          this._pollFailureCount = 0;
          this._nextPollAt = 0;
          const command = yield response.json();
          if (!command || command.enabled === false || !command.nonce || command.nonce === this._lastNonce) {
            return;
          }
          this._lastNonce = command.nonce;
          yield this.capture(command);
        } catch (error) {
          this.schedulePollRetry();
        }
      });
    }
    schedulePollRetry() {
      this._pollFailureCount = Math.min(this._pollFailureCount + 1, 6);
      const delay = Math.min(1e4, 500 * Math.pow(2, this._pollFailureCount));
      this._nextPollAt = Date.now() + delay;
    }
    capture(command) {
      return __async(this, null, function* () {
        if (this._busy) {
          return;
        }
        this._busy = true;
        if (command.nonce) {
          this._lastNonce = command.nonce;
        }
        const startedAt = Date.now();
        try {
          const width = Math.max(1, Math.floor(command.width || 900));
          const height = Math.max(1, Math.floor(command.height || 700));
          const camera = this.resolveCamera(command.camera_name || this.cameraName);
          const target = this.resolveTarget(command.target_name || this.targetName);
          if (!camera) {
            throw new Error(`Camera not found: ${command.camera_name || this.cameraName || "(owner/default)"}`);
          }
          if (!target && !command.center) {
            throw new Error(`Target not found and command.center missing: ${command.target_name || this.targetName || "(empty)"}`);
          }
          const center = this.resolveCenter(command, target);
          const radius = this.resolveRadius(command, target);
          const captureMode = this.resolveCaptureMode(command, camera, target);
          const originalTargetEuler = target ? target.transform.localRotationEuler.clone() : null;
          const previousTarget = camera.renderTarget;
          const previousFov = camera.fieldOfView;
          const previousClearColor = camera.clearColor ? camera.clearColor.clone() : null;
          const renderTexture = new Laya.RenderTexture(
            width,
            height,
            Laya.RenderTargetFormat.R8G8B8A8,
            Laya.RenderTargetFormat.DEPTH_16,
            false,
            1,
            false,
            command.render_texture_srgb !== false
          );
          camera.renderTarget = renderTexture;
          if (typeof command.fov === "number" && command.fov > 0) {
            camera.fieldOfView = command.fov;
          }
          if (command.transparent_background !== false) {
            camera.clearColor = new Laya.Color(0, 0, 0, this.resolveAlphaSource(command) === "render_alpha" ? 0 : 1);
          }
          const patchResult = this.applyMaterialPatch(command, target);
          void this.postLog(
            command,
            "material_patch",
            `applied=${patchResult.applied} materials=${patchResult.materialCount} values=${patchResult.valueCount}${patchResult.fallback ? ` fallback=${patchResult.fallback}` : ""}${patchResult.error ? ` error=${patchResult.error}` : ""}`
          );
          const views = command.views && command.views.length > 0 ? command.views : [{ yaw: 0, pitch: 0, file_name: "laya_capture.png" }];
          const settleFrames = this.resolveSettleFrames(command);
          const browserScoreEnabled = this.shouldUseBrowserScore(command);
          const emitArtifacts = !browserScoreEnabled || this.shouldEmitArtifacts(command);
          const postTasks = [];
          const browserScoreViews = [];
          try {
            for (let index = 0; index < views.length; index++) {
              const view = views[index];
              if (captureMode === "rotate_target") {
                if (!target || !originalTargetEuler) {
                  throw new Error("rotate_target mode requires target_name");
                }
                this.rotateTargetForView(target, originalTargetEuler, view, command);
              } else {
                this.placeCamera(camera, center, radius, view, command);
              }
              yield this.waitFrames(settleFrames);
              const pixels = yield this.readPixels(renderTexture, width, height);
              const alphaSource = this.resolveAlphaSource(command);
              if (command.transparent_background !== false && alphaSource === "silhouette_mask" && target) {
                const maskPixels = yield this.renderSilhouetteMask(camera, renderTexture, target, width, height);
                this.applyMaskAlpha(pixels, maskPixels, command.mask_alpha_mode, command.mask_alpha_threshold);
              } else if (command.transparent_background !== false && alphaSource === "alpha_from_rgb") {
                this.liftRgbIntoAlpha(pixels, command.alpha_from_rgb_threshold);
              }
              if (command.zero_transparent_rgb !== false) {
                this.zeroTransparentRgb(pixels);
              }
              const outputPixels = this.copyPixelsForOutput(pixels, width, height, command.flip_y === true);
              if (browserScoreEnabled) {
                browserScoreViews.push(yield this.scoreBrowserView(command, view, index, outputPixels, width, height));
              }
              if (!emitArtifacts) {
                continue;
              }
              if (this.resolveImageFormat(command) === "raw_rgba") {
                postTasks.push(this.postRawImage(command, view, index, outputPixels, width, height, patchResult));
              } else {
                const dataUrl = this.pixelsToPngDataUrl(
                  outputPixels,
                  width,
                  height,
                  false
                );
                postTasks.push(this.postImage(command, view, index, dataUrl, width, height, patchResult));
              }
            }
          } finally {
            if (target && originalTargetEuler) {
              target.transform.localRotationEuler = originalTargetEuler;
            }
            camera.renderTarget = previousTarget;
            camera.fieldOfView = previousFov;
            if (previousClearColor) {
              camera.clearColor = previousClearColor;
            }
            renderTexture.destroy();
          }
          yield Promise.all(postTasks);
          if (browserScoreEnabled) {
            yield this.postBrowserScore(command, this.aggregateBrowserScore(command, browserScoreViews, width, height, patchResult));
          }
          void this.postLog(command, "completed", `Captured ${views.length} views in ${Date.now() - startedAt}ms`);
        } catch (error) {
          yield this.postLog(command, "capture_error", String(error));
        } finally {
          this._busy = false;
        }
      });
    }
    resolveCamera(name) {
      if (this.owner instanceof Laya.Camera) {
        return this.owner;
      }
      const root = this.sceneRoot();
      const node = name ? this.findNodeByName(root, name) : this.findFirstCamera(root);
      return node instanceof Laya.Camera ? node : null;
    }
    resolveTarget(name) {
      if (!name) {
        return null;
      }
      const node = this.findNodeByName(this.sceneRoot(), name);
      return node instanceof Laya.Sprite3D ? node : null;
    }
    sceneRoot() {
      let node = this.owner;
      while (node && node.parent) {
        node = node.parent;
      }
      return node || this.owner;
    }
    findNodeByName(root, name) {
      if (!root || !name) {
        return null;
      }
      if (root.name === name) {
        return root;
      }
      const count = typeof root.numChildren === "number" ? root.numChildren : 0;
      for (let i = 0; i < count; i++) {
        const found = this.findNodeByName(root.getChildAt(i), name);
        if (found) {
          return found;
        }
      }
      return null;
    }
    findFirstCamera(root) {
      if (!root) {
        return null;
      }
      if (root instanceof Laya.Camera) {
        return root;
      }
      const count = typeof root.numChildren === "number" ? root.numChildren : 0;
      for (let i = 0; i < count; i++) {
        const found = this.findFirstCamera(root.getChildAt(i));
        if (found) {
          return found;
        }
      }
      return null;
    }
    resolveCaptureMode(command, camera, target) {
      if (command.capture_mode === "orbit_camera" || command.capture_mode === "rotate_target") {
        return command.capture_mode;
      }
      if (target && this.isDescendantOf(target, camera)) {
        return "rotate_target";
      }
      return "orbit_camera";
    }
    isDescendantOf(node, ancestor) {
      let current = node ? node.parent : null;
      while (current) {
        if (current === ancestor) {
          return true;
        }
        current = current.parent;
      }
      return false;
    }
    resolveCenter(command, target) {
      if (command.center && command.center.length >= 3) {
        return new Laya.Vector3(command.center[0], command.center[1], command.center[2]);
      }
      if (target) {
        const p = target.transform.position;
        return new Laya.Vector3(p.x, p.y, p.z);
      }
      return new Laya.Vector3(0, 0, 0);
    }
    resolveRadius(command, target) {
      if (command.target_size && command.target_size.length >= 3) {
        const sx = command.target_size[0];
        const sy = command.target_size[1];
        const sz = command.target_size[2];
        return Math.max(0.1, Math.sqrt(sx * sx + sy * sy + sz * sz) * 0.5);
      }
      const bounds = target ? this.tryGetBounds(target) : null;
      if (bounds) {
        const ext = bounds.getExtent();
        return Math.max(0.1, Math.sqrt(ext.x * ext.x + ext.y * ext.y + ext.z * ext.z));
      }
      return 1;
    }
    tryGetBounds(target) {
      let result = null;
      this.walk(target, (node) => {
        const renderer = node.meshRenderer || node.skinnedMeshRenderer || node.renderer;
        const bounds = renderer && renderer.bounds ? renderer.bounds : null;
        if (!bounds) {
          return;
        }
        if (!result) {
          result = bounds.clone();
        } else {
          Laya.Bounds.merge(result, bounds, result);
        }
      });
      return result;
    }
    walk(root, visit) {
      if (!root) {
        return;
      }
      visit(root);
      const count = typeof root.numChildren === "number" ? root.numChildren : 0;
      for (let i = 0; i < count; i++) {
        this.walk(root.getChildAt(i), visit);
      }
    }
    placeCamera(camera, center, radius, view, command) {
      const yaw = ((view.yaw || 0) + (command.yaw_offset || 0)) * Math.PI / 180;
      const pitch = ((view.pitch || 0) + (command.pitch_offset || 0)) * Math.PI / 180;
      const distance = Math.max(command.min_distance || 1, radius * (command.distance_scale || 2.2));
      const cosPitch = Math.cos(pitch);
      const offset = new Laya.Vector3(
        Math.sin(yaw) * cosPitch * distance,
        Math.sin(pitch) * distance,
        Math.cos(yaw) * cosPitch * distance
      );
      camera.transform.position = new Laya.Vector3(
        center.x - offset.x,
        center.y - offset.y,
        center.z - offset.z
      );
      camera.transform.lookAt(center, Laya.Vector3.Up, false, true);
    }
    rotateTargetForView(target, baseEuler, view, command) {
      const yawSign = typeof command.target_yaw_sign === "number" ? command.target_yaw_sign : -1;
      const pitchSign = typeof command.target_pitch_sign === "number" ? command.target_pitch_sign : -1;
      const baseYaw = typeof command.target_base_yaw === "number" ? command.target_base_yaw : 0;
      const basePitch = typeof command.target_base_pitch === "number" ? command.target_base_pitch : 0;
      const yaw = ((view.yaw || 0) + (command.yaw_offset || 0)) * yawSign;
      const pitch = ((view.pitch || 0) + (command.pitch_offset || 0)) * pitchSign;
      target.transform.localRotationEuler = new Laya.Vector3(
        basePitch + pitch,
        baseYaw + yaw,
        baseEuler.z
      );
    }
    waitFrames(count) {
      return __async(this, null, function* () {
        for (let i = 0; i < count; i++) {
          yield new Promise((resolve) => Laya.timer.frameOnce(1, this, resolve));
        }
      });
    }
    readPixels(renderTexture, width, height) {
      return __async(this, null, function* () {
        const pixels = new Uint8Array(width * height * 4);
        const maybePromise = renderTexture.getDataAsync(0, 0, width, height, pixels);
        if (maybePromise && typeof maybePromise.then === "function") {
          yield maybePromise;
          return pixels;
        }
        return renderTexture.getData(0, 0, width, height, pixels);
      });
    }
    resolveAlphaSource(command) {
      if (command.alpha_source === "silhouette_mask" || command.alpha_source === "alpha_from_rgb" || command.alpha_source === "render_alpha") {
        return command.alpha_source;
      }
      if (command.transparent_background === false) {
        return "render_alpha";
      }
      return "render_alpha";
    }
    resolveSettleFrames(command) {
      if (typeof command.settle_frames === "number" && Number.isFinite(command.settle_frames)) {
        return Math.max(0, Math.floor(command.settle_frames));
      }
      return 2;
    }
    resolveImageFormat(command) {
      return command.image_format === "raw_rgba" ? "raw_rgba" : "png";
    }
    applyMaterialPatch(command, fallbackTarget) {
      const patch = command.material_patch;
      if (!patch || !patch.values) {
        return { applied: false, materialCount: 0, valueCount: 0 };
      }
      try {
        const target = patch.target_name ? this.resolveTarget(patch.target_name) : fallbackTarget;
        if (!target) {
          return {
            applied: false,
            materialCount: 0,
            valueCount: 0,
            error: `material_patch target not found: ${patch.target_name || command.target_name || "(empty)"}`
          };
        }
        const materials = [];
        this.collectPatchMaterials(target, materials);
        let fallback;
        if (materials.length === 0) {
          const root = this.sceneRoot();
          if (root && root !== target) {
            this.collectPatchMaterials(root, materials);
            if (materials.length > 0) {
              fallback = "scene_root_no_target_materials";
            }
          }
        }
        let valueCount = 0;
        for (const material of materials) {
          for (const key of Object.keys(patch.values)) {
            this.setMaterialValue(material, key, patch.values[key]);
            valueCount++;
          }
        }
        return { applied: materials.length > 0, materialCount: materials.length, valueCount, ...(fallback ? { fallback } : {}) };
      } catch (error) {
        return { applied: false, materialCount: 0, valueCount: 0, error: String(error) };
      }
    }
    collectPatchMaterials(target, materials) {
      this.walk(target, (node) => {
        const sources = [];
        this.collectNodeRenderSources(node, sources);
        for (const source of sources) {
          this.collectMaterials(source, materials);
        }
      });
    }
    setMaterialValue(material, name, value) {
      if (typeof value === "number") {
        material.setFloat(name, value);
        return;
      }
      if (typeof value === "boolean") {
        material.setBool(name, value);
        return;
      }
      if (!Array.isArray(value)) {
        return;
      }
      if (value.length === 4) {
        if (name.toLowerCase().indexOf("color") >= 0) {
          material.setColor(name, new Laya.Color(value[0], value[1], value[2], value[3]));
        } else {
          material.setVector4(name, new Laya.Vector4(value[0], value[1], value[2], value[3]));
        }
      } else if (value.length === 3) {
        material.setVector3(name, new Laya.Vector3(value[0], value[1], value[2]));
      } else if (value.length === 2) {
        material.setVector2(name, new Laya.Vector2(value[0], value[1]));
      }
    }
    collectMaterials(source, materials) {
      if (!source) {
        return;
      }
      const sharedMaterials = source.sharedMaterials || source.materials || source._materials || null;
      if (sharedMaterials) {
        for (const material of sharedMaterials) {
          if (material && materials.indexOf(material) < 0) {
            materials.push(material);
          }
        }
        return;
      }
      if (source.sharedMaterial && materials.indexOf(source.sharedMaterial) < 0) {
        materials.push(source.sharedMaterial);
      }
    }
    renderSilhouetteMask(camera, renderTexture, target, width, height) {
      return __async(this, null, function* () {
        const previousClearColor = camera.clearColor ? camera.clearColor.clone() : null;
        const maskMaterial = new Laya.UnlitMaterial();
        maskMaterial.albedoColor = new Laya.Color(1, 1, 1, 1);
        maskMaterial.albedoIntensity = 1;
        const states = this.applyMaskRenderState(target, maskMaterial);
        try {
          camera.clearColor = new Laya.Color(0, 0, 0, 1);
          yield this.waitFrames(2);
          return yield this.readPixels(renderTexture, width, height);
        } finally {
          this.restoreRenderState(states);
          if (previousClearColor) {
            camera.clearColor = previousClearColor;
          }
          maskMaterial.destroy();
        }
      });
    }
    applyMaskRenderState(target, maskMaterial) {
      const targetSources = this.collectRenderSources(target);
      const targetSet = new Set(targetSources);
      const allSources = this.collectRenderSources(this.sceneRoot());
      const states = [];
      for (const source of allSources) {
        const materials = this.getSourceMaterials(source);
        states.push({
          source,
          enabled: typeof source.enabled === "boolean" ? source.enabled : null,
          materials: materials ? materials.slice() : null
        });
        if (targetSet.has(source)) {
          const count = Math.max(1, materials ? materials.length : 1);
          const maskMaterials = [];
          for (let i = 0; i < count; i++) {
            maskMaterials.push(maskMaterial);
          }
          this.setSourceMaterials(source, maskMaterials);
          if (typeof source.enabled === "boolean") {
            source.enabled = true;
          }
        } else if (typeof source.enabled === "boolean") {
          source.enabled = false;
        }
      }
      return states;
    }
    restoreRenderState(states) {
      for (const state of states) {
        if (state.materials) {
          this.setSourceMaterials(state.source, state.materials);
        }
        if (state.enabled !== null) {
          state.source.enabled = state.enabled;
        }
      }
    }
    collectRenderSources(root) {
      const sources = [];
      this.walk(root, (node) => {
        this.collectNodeRenderSources(node, sources);
      });
      return sources;
    }
    collectNodeRenderSources(node, sources) {
      const directSources = [node == null ? void 0 : node.meshRenderer, node == null ? void 0 : node.skinnedMeshRenderer, node == null ? void 0 : node.renderer, node == null ? void 0 : node._renderNode];
      for (const source of directSources) {
        this.addRenderSource(source, sources);
      }
      if (node && typeof node.getComponent === "function") {
        const layaAny = Laya;
        for (const componentType of [layaAny.MeshRenderer, layaAny.SkinnedMeshRenderer, layaAny.Renderer]) {
          if (!componentType) {
            continue;
          }
          try {
            this.addRenderSource(node.getComponent(componentType), sources);
          } catch {
          }
        }
      }
      const components = (node == null ? void 0 : node._components) || (node == null ? void 0 : node._scripts) || null;
      if (components && typeof components.length === "number") {
        for (let i = 0; i < components.length; i++) {
          this.addRenderSource(components[i], sources);
        }
      }
    }
    addRenderSource(source, sources) {
      if (!source || sources.indexOf(source) >= 0) {
        return;
      }
      if (this.getSourceMaterials(source) || typeof source.enabled === "boolean") {
        sources.push(source);
      }
    }
    getSourceMaterials(source) {
      if (!source) {
        return null;
      }
      return source.sharedMaterials || source.materials || source._materials || (source.sharedMaterial ? [source.sharedMaterial] : null);
    }
    setSourceMaterials(source, materials) {
      if (!source) {
        return;
      }
      if (source.sharedMaterials !== void 0) {
        source.sharedMaterials = materials;
      } else if (source.materials !== void 0) {
        source.materials = materials;
      } else if (source._materials !== void 0) {
        source._materials = materials;
      } else if (source.sharedMaterial !== void 0) {
        source.sharedMaterial = materials[0] || null;
      }
    }
    applyMaskAlpha(pixels, maskPixels, mode, threshold) {
      const binary = mode !== "soft";
      const minValue = typeof threshold === "number" ? Math.max(0, Math.min(255, threshold)) : 1;
      const count = Math.min(pixels.length, maskPixels.length);
      for (let i = 0; i < count; i += 4) {
        const maskValue = Math.max(maskPixels[i], maskPixels[i + 1], maskPixels[i + 2]);
        pixels[i + 3] = binary ? maskValue >= minValue ? 255 : 0 : maskValue;
      }
    }
    zeroTransparentRgb(pixels) {
      for (let i = 0; i < pixels.length; i += 4) {
        if (pixels[i + 3] === 0) {
          pixels[i] = 0;
          pixels[i + 1] = 0;
          pixels[i + 2] = 0;
        }
      }
    }
    liftRgbIntoAlpha(pixels, threshold) {
      const minValue = typeof threshold === "number" ? Math.max(0, Math.min(255, threshold)) : 1;
      for (let i = 0; i < pixels.length; i += 4) {
        if (pixels[i + 3] !== 0) {
          continue;
        }
        const maxRgb = Math.max(pixels[i], pixels[i + 1], pixels[i + 2]);
        if (maxRgb < minValue) {
          continue;
        }
        pixels[i + 3] = maxRgb;
        const scale = 255 / maxRgb;
        pixels[i] = Math.min(255, Math.round(pixels[i] * scale));
        pixels[i + 1] = Math.min(255, Math.round(pixels[i + 1] * scale));
        pixels[i + 2] = Math.min(255, Math.round(pixels[i + 2] * scale));
      }
    }
    pixelsToPngDataUrl(pixels, width, height, flipY) {
      const canvas = document.createElement("canvas");
      canvas.width = width;
      canvas.height = height;
      const context = canvas.getContext("2d");
      if (!context) {
        throw new Error("2D canvas context is unavailable");
      }
      const imageData = context.createImageData(width, height);
      const target = imageData.data;
      for (let y = 0; y < height; y++) {
        const sourceY = flipY ? height - 1 - y : y;
        const sourceOffset = sourceY * width * 4;
        const targetOffset = y * width * 4;
        target.set(pixels.subarray(sourceOffset, sourceOffset + width * 4), targetOffset);
      }
      context.putImageData(imageData, 0, 0);
      return canvas.toDataURL("image/png");
    }
    copyPixelsForOutput(pixels, width, height, flipY) {
      if (!flipY) {
        return pixels;
      }
      const output = new Uint8Array(pixels.length);
      for (let y = 0; y < height; y++) {
        const sourceY = height - 1 - y;
        const sourceOffset = sourceY * width * 4;
        const targetOffset = y * width * 4;
        output.set(pixels.subarray(sourceOffset, sourceOffset + width * 4), targetOffset);
      }
      return output;
    }
    shouldUseBrowserScore(command) {
      const config = command.browser_score;
      return !!(config && config.enabled && Array.isArray(config.reference_images) && config.reference_images.length > 0);
    }
    shouldEmitArtifacts(command) {
      const config = command.browser_score;
      return !!(config && config.emit_artifacts === "always");
    }
    scoreBrowserView(command, view, index, pixels, width, height) {
      return __async(this, null, function* () {
        const viewId = this.viewId(view, index);
        const reference = this.findReference(command, view, index);
        if (!reference || !reference.url) {
          throw new Error(`browser_score reference image missing for ${viewId}`);
        }
        const referencePixels = yield this.loadReferencePixels(reference.url, width, height);
        return this.scorePixels(viewId, pixels, referencePixels, command);
      });
    }
    findReference(command, view, index) {
      const references = command.browser_score && Array.isArray(command.browser_score.reference_images) ? command.browser_score.reference_images : [];
      const viewId = this.viewId(view, index);
      const fileName = view.file_name || "";
      for (const reference of references) {
        if (!reference) {
          continue;
        }
        if (reference.view_id === viewId || reference.id === viewId) {
          return reference;
        }
        if (fileName && reference.file_name === fileName) {
          return reference;
        }
      }
      return references[index] || null;
    }
    loadReferencePixels(url, width, height) {
      return __async(this, null, function* () {
        const cacheKey = `${url}|${width}x${height}`;
        const cached = this._referenceCache.get(cacheKey);
        if (cached) {
          return cached;
        }
        const response = yield fetch(url);
        if (!response.ok) {
          throw new Error(`reference image fetch failed: ${response.status} ${url}`);
        }
        const blob = yield response.blob();
        const image = yield this.decodeImage(blob);
        const canvas = document.createElement("canvas");
        canvas.width = width;
        canvas.height = height;
        const context = canvas.getContext("2d");
        if (!context) {
          throw new Error("2D canvas context is unavailable");
        }
        context.clearRect(0, 0, width, height);
        context.drawImage(image, 0, 0, width, height);
        const pixels = context.getImageData(0, 0, width, height).data;
        if (image.close) {
          image.close();
        }
        this._referenceCache.set(cacheKey, pixels);
        return pixels;
      });
    }
    decodeImage(blob) {
      return __async(this, null, function* () {
        const createBitmap = Laya.Browser.window.createImageBitmap;
        if (typeof createBitmap === "function") {
          return yield createBitmap(blob);
        }
        return yield new Promise((resolve, reject) => {
          const url = URL.createObjectURL(blob);
          const image = new Image();
          image.onload = () => {
            URL.revokeObjectURL(url);
            resolve(image);
          };
          image.onerror = () => {
            URL.revokeObjectURL(url);
            reject(new Error("reference image decode failed"));
          };
          image.src = url;
        });
      });
    }
    scorePixels(viewId, candidate, reference, command) {
      const rgbWeight = this.numberOrDefault(command.browser_score && command.browser_score.rgb_weight, 0.85);
      const alphaWeight = this.numberOrDefault(command.browser_score && command.browser_score.alpha_weight, 0.15);
      const length = Math.min(candidate.length, reference.length);
      let weightedDiff = 0;
      let weightSum = 0;
      let rgbMaeSum = 0;
      let alphaMaeSum = 0;
      let foregroundCount = 0;
      let unionCount = 0;
      let intersectionCount = 0;
      for (let i = 0; i < length; i += 4) {
        const candidateAlpha = candidate[i + 3];
        const referenceAlpha = reference[i + 3];
        const foregroundWeight = Math.max(candidateAlpha, referenceAlpha) / 255;
        if (foregroundWeight <= 0) {
          continue;
        }
        const rgbDiff = (Math.abs(candidate[i] - reference[i]) + Math.abs(candidate[i + 1] - reference[i + 1]) + Math.abs(candidate[i + 2] - reference[i + 2])) / (3 * 255);
        const alphaDiff = Math.abs(candidateAlpha - referenceAlpha) / 255;
        weightedDiff += (rgbWeight * rgbDiff + alphaWeight * alphaDiff) * foregroundWeight;
        weightSum += foregroundWeight;
        rgbMaeSum += rgbDiff;
        alphaMaeSum += alphaDiff;
        foregroundCount++;
        if (candidateAlpha > 0 || referenceAlpha > 0) {
          unionCount++;
          if (candidateAlpha > 0 && referenceAlpha > 0) {
            intersectionCount++;
          }
        }
      }
      const diffScore = weightSum > 0 ? weightedDiff / weightSum : 1;
      const fitScore = this.clamp01(1 - diffScore);
      return {
        view_id: viewId,
        diff_score: diffScore,
        fit_score: fitScore,
        rgb_mae: foregroundCount > 0 ? rgbMaeSum / foregroundCount : 1,
        alpha_mae: foregroundCount > 0 ? alphaMaeSum / foregroundCount : 1,
        mask_iou: unionCount > 0 ? intersectionCount / unionCount : 1,
        foreground_weight_sum: weightSum
      };
    }
    aggregateBrowserScore(command, views, width, height, patchResult) {
      const viewCount = Math.max(1, views.length);
      let diffSum = 0;
      let fitSum = 0;
      let worstDiff = 0;
      for (const view of views) {
        diffSum += view.diff_score;
        fitSum += view.fit_score;
        worstDiff = Math.max(worstDiff, view.diff_score);
      }
      const diffScore = diffSum / viewCount;
      const fitScore = fitSum / viewCount;
      const metric = command.browser_score && command.browser_score.metric ? command.browser_score.metric : "browser_fast_rgba_mae_v1";
      return {
        enabled: true,
        metric,
        width,
        height,
        view_count: views.length,
        fit_score: fitScore,
        diff_score: diffScore,
        score: fitScore,
        worst_diff_score: worstDiff,
        views,
        material_patch: patchResult,
        summary: {
          mean_diff_score: diffScore,
          mean_fit_score: fitScore,
          optimization_fit_score: fitScore,
          optimization_fit_score_source: "browser_score",
          metric
        }
      };
    }
    postBrowserScore(command, score) {
      return __async(this, null, function* () {
        const baseUrl = command.server_base_url || this.serverBaseUrl;
        const response = yield fetch(`${baseUrl}/material-fit/capture-score`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            nonce: command.nonce,
            browser_score: score
          })
        });
        if (!response.ok) {
          throw new Error(`browser_score post failed: ${response.status}`);
        }
      });
    }
    viewId(view, index) {
      return view.view_id || view.id || `view_${this.pad(index, 3)}`;
    }
    numberOrDefault(value, fallback) {
      return typeof value === "number" && Number.isFinite(value) ? value : fallback;
    }
    clamp01(value) {
      return Math.max(0, Math.min(1, value));
    }
    postImage(command, view, index, dataUrl, width, height, patchResult) {
      return __async(this, null, function* () {
        const url = command.post_url || `${command.server_base_url || this.serverBaseUrl}/material-fit/capture-result`;
        const viewId = view.view_id || view.id || `view_${this.pad(index, 3)}`;
        yield fetch(url, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            nonce: command.nonce,
            view_id: viewId,
            file_name: view.file_name || `${viewId}.png`,
            width,
            height,
            yaw: view.yaw,
            pitch: view.pitch || 0,
            transparent_background: command.transparent_background !== false,
            alpha_source: this.resolveAlphaSource(command),
            material_patch: patchResult,
            png_base64: dataUrl.replace(/^data:image\/png;base64,/, "")
          })
        });
      });
    }
    postRawImage(command, view, index, pixels, width, height, patchResult) {
      return __async(this, null, function* () {
        const viewId = view.view_id || view.id || `view_${this.pad(index, 3)}`;
        const fileName = this.rawFileName(view.file_name || `${viewId}.png`);
        const params = new URLSearchParams({
          nonce: command.nonce || "",
          view_id: viewId,
          file_name: fileName,
          width: String(width),
          height: String(height),
          yaw: String(view.yaw),
          pitch: String(view.pitch || 0),
          transparent_background: String(command.transparent_background !== false),
          alpha_source: this.resolveAlphaSource(command),
          material_patch_applied: String(patchResult.applied),
          material_count: String(patchResult.materialCount),
          value_count: String(patchResult.valueCount)
        });
        const baseUrl = command.server_base_url || this.serverBaseUrl;
        yield fetch(`${baseUrl}/material-fit/capture-raw-rgba?${params.toString()}`, {
          method: "POST",
          headers: { "Content-Type": "application/octet-stream" },
          body: pixels
        });
      });
    }
    rawFileName(fileName) {
      if (/\.rgba$/i.test(fileName)) {
        return fileName;
      }
      if (/\.png$/i.test(fileName)) {
        return fileName.replace(/\.png$/i, ".rgba");
      }
      return `${fileName}.rgba`;
    }
    postLog(command, kind, message) {
      return __async(this, null, function* () {
        try {
          const baseUrl = command.server_base_url || this.serverBaseUrl;
          yield fetch(`${baseUrl}/material-fit/capture-log`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ kind, message, nonce: this._lastNonce, at: Date.now() })
          });
        } catch (e) {
        }
      });
    }
    pad(value, width) {
      let text = String(value);
      while (text.length < width) {
        text = "0" + text;
      }
      return text;
    }
  };
  __decorateClass([
    property8({ type: String, caption: "Server Base URL" })
  ], MaterialFitCapture.prototype, "serverBaseUrl", 2);
  __decorateClass([
    property8({ type: String, caption: "Default Camera Name" })
  ], MaterialFitCapture.prototype, "cameraName", 2);
  __decorateClass([
    property8({ type: String, caption: "Default Target Name" })
  ], MaterialFitCapture.prototype, "targetName", 2);
  __decorateClass([
    property8({ type: Number, caption: "Poll Interval Ms" })
  ], MaterialFitCapture.prototype, "pollIntervalMs", 2);
  __decorateClass([
    property8({ type: Boolean, caption: "Auto Poll" })
  ], MaterialFitCapture.prototype, "autoPoll", 2);
  MaterialFitCapture = __decorateClass([
    regClass9("6610f67d-602e-4f03-af59-29460829b477", "../src/MaterialFitCapture.ts")
  ], MaterialFitCapture);
  MaterialFitCapture = __decorateClass([
    regClass9("ZhD2fWAuTwOvWSlGCCm0dw", "../src/MaterialFitCapture.ts")
  ], MaterialFitCapture);
  // src/Play/Effect/View/CoinExplodeView.ts
  var { regClass: regClass10, property: property9 } = Laya;
  var CoinExplodeView = class extends Laya.Script3D {
    constructor() {
      super(...arguments);
      this.duration = 1500;
      // ============ 私有状态 ============
      this._cx = 0;
      this._cy = 0;
      this._hasSetup = false;
    }
    // ============ 公共接口 ============
    /**
     * 由程序调用，在 addChild 之前设置显示坐标。
     * 坐标为游戏世界坐标（resolveLockPoint 输出，已 mirror）。
     */
    setup(cx, cy) {
      this._cx = cx;
      this._cy = cy;
      this._hasSetup = true;
    }
    // ============ 生命周期 ============
    onStart() {
      if (this._hasSetup) {
        this.owner.transform.localPosition = new Laya.Vector3(this._cx, this._cy, 0);
      }
      Laya.timer.once(this.duration, this, () => {
        var _a;
        return (_a = this.owner) == null ? void 0 : _a.destroy();
      });
    }
    onDestroy() {
      Laya.timer.clearAll(this);
    }
  };
  __name(CoinExplodeView, "CoinExplodeView");
  __decorateClass([
    property9({ type: Number, caption: "动画时长 (ms)" })
  ], CoinExplodeView.prototype, "duration", 2);
  CoinExplodeView = __decorateClass([
    regClass10("19ce3d93-f678-4dc1-8df2-ab6891d5cc88", "../src/Play/Effect/View/CoinExplodeView.ts")
  ], CoinExplodeView);

  // src/Common/Action/Compat/Compat.ts
  var _Controller = class _Controller {
    constructor() {
      this.stopped = false;
      this._stopCallbacks = /* @__PURE__ */ new Set();
      this.done = new Promise((resolve) => {
        this._resolve = resolve;
      });
    }
    stop() {
      if (this.stopped) return;
      this.stopped = true;
      for (const fn of this._stopCallbacks) {
        fn();
      }
      this._stopCallbacks.clear();
    }
    _complete() {
      this._resolve();
    }
    _onStop(fn) {
      if (this.stopped) {
        fn();
        return () => {
        };
      }
      this._stopCallbacks.add(fn);
      return () => this._stopCallbacks.delete(fn);
    }
  };
  __name(_Controller, "Controller");
  var Controller = _Controller;
  function play(action, target, options) {
    const ctrl = new Controller();
    if (options == null ? void 0 : options.animator) {
      ctrl.animator = options.animator;
    }
    if (!target || target.destroyed) {
      ctrl._complete();
      return ctrl;
    }
    action.play(target, ctrl).then(() => ctrl._complete()).catch((e) => {
      console.error("[Action.Compat]", e);
      ctrl._complete();
    });
    return ctrl;
  }
  __name(play, "play");
  function seq(...actions) {
    return {
      play(target, ctrl) {
        return __async(this, null, function* () {
          for (const action of actions) {
            if (ctrl.stopped) break;
            yield action.play(target, ctrl);
          }
        });
      }
    };
  }
  __name(seq, "seq");
  function spawn(...actions) {
    return {
      play(target, ctrl) {
        return __async(this, null, function* () {
          yield Promise.all(actions.map((a) => a.play(target, ctrl).catch((e) => {
            console.error("[Action.Compat] spawn error:", e);
          })));
        });
      }
    };
  }
  __name(spawn, "spawn");
  function is3D(target) {
    var _a;
    return target && "transform" in target && !!((_a = target.transform) == null ? void 0 : _a.localPosition);
  }
  __name(is3D, "is3D");
  function runTween(ctrl, tweenTarget, owner, duration, property16, endValue, ease) {
    return new Promise((resolve) => {
      let finished = false;
      const finish = /* @__PURE__ */ __name(() => {
        if (finished) return;
        finished = true;
        off();
        resolve();
      }, "finish");
      const tween = Laya.Tween.create(tweenTarget, owner).duration(duration * 1e3).to(property16, endValue);
      if (ease) tween.ease(ease);
      tween.then(finish);
      const off = ctrl._onStop(() => {
        tween.kill(false);
        finish();
      });
    });
  }
  __name(runTween, "runTween");
  function runTween2D(ctrl, target, duration, props, ease) {
    return new Promise((resolve) => {
      let finished = false;
      const finish = /* @__PURE__ */ __name(() => {
        if (finished) return;
        finished = true;
        off();
        resolve();
      }, "finish");
      const tween = Laya.Tween.create(target, target).duration(duration * 1e3);
      for (const key of Object.keys(props)) {
        tween.to(key, props[key]);
      }
      if (ease) tween.ease(ease);
      tween.then(finish);
      const off = ctrl._onStop(() => {
        tween.kill(false);
        finish();
      });
    });
  }
  __name(runTween2D, "runTween2D");
  function moveTo(duration, x, y, z = 0, ease) {
    return {
      play(target, ctrl) {
        if (ctrl.stopped || !target) return Promise.resolve();
        if (is3D(target)) {
          const transform = target.transform;
          const end = new Laya.Vector3(x, y, z);
          if (!isFinite(duration) || duration <= 0) {
            transform.localPosition = end;
            return Promise.resolve();
          }
          return runTween(ctrl, transform, target, duration, "localPosition", end, ease);
        } else {
          if (!isFinite(duration) || duration <= 0) {
            target.x = x;
            target.y = y;
            return Promise.resolve();
          }
          return runTween2D(ctrl, target, duration, { x, y }, ease);
        }
      }
    };
  }
  __name(moveTo, "moveTo");
  function scaleTo(duration, x, y, z, ease) {
    return {
      play(target, ctrl) {
        if (ctrl.stopped || !target) return Promise.resolve();
        if (is3D(target)) {
          const transform = target.transform;
          const end = new Laya.Vector3(x, y, z != null ? z : 1);
          if (!isFinite(duration) || duration <= 0) {
            transform.localScale = end;
            return Promise.resolve();
          }
          return runTween(ctrl, transform, target, duration, "localScale", end, ease);
        } else {
          if (!isFinite(duration) || duration <= 0) {
            target.scaleX = x;
            target.scaleY = y;
            return Promise.resolve();
          }
          return runTween2D(ctrl, target, duration, { scaleX: x, scaleY: y }, ease);
        }
      }
    };
  }
  __name(scaleTo, "scaleTo");
  function wait(duration) {
    return {
      play(target, ctrl) {
        if (ctrl.stopped || !isFinite(duration) || duration <= 0) {
          return Promise.resolve();
        }
        return new Promise((resolve) => {
          const timer = setTimeout(() => resolve(), duration * 1e3);
          ctrl._onStop(() => {
            clearTimeout(timer);
            resolve();
          });
        });
      }
    };
  }
  __name(wait, "wait");
  function call(fn) {
    return {
      play(target, ctrl) {
        return __async(this, null, function* () {
          if (ctrl.stopped) return;
          yield fn(target, ctrl);
        });
      }
    };
  }
  __name(call, "call");
  function show() {
    return {
      play(target, ctrl) {
        if (ctrl.stopped || !target) return Promise.resolve();
        if (is3D(target)) {
          target.active = true;
        } else {
          target.visible = true;
        }
        return Promise.resolve();
      }
    };
  }
  __name(show, "show");

  // src/Play/Effect/View/CoinFlyFakeView.ts
  var { regClass: regClass11, property: property10 } = Laya;
  var CoinFlyFakeView = class extends Laya.Script {
    constructor() {
      super(...arguments);
      this.coinPrefab = null;
      this.textNode = null;
      this.coinSize = 56;
      this.flySpeed = 600;
      this.screenPadding = 80;
      this.targetOffsetY = 160;
      this._textBaseScaleX = 1;
      this._textBaseScaleY = 1;
      this._tempPoint = new Laya.Point();
    }
    onAwake() {
      this._findTextNode();
      this._cacheTextScale();
    }
    onStart() {
      var _a;
      if (!this.coinPrefab) {
        (_a = this.owner) == null ? void 0 : _a.destroy();
        return;
      }
      const delayMs = this._randomRange(
        CoinFlyFakeView.MIN_START_DELAY_MS,
        CoinFlyFakeView.MAX_START_DELAY_MS + 1
      );
      Laya.timer.once(delayMs, this, this._startPlayback);
    }
    onDestroy() {
      Laya.timer.clearAll(this);
    }
    _startPlayback() {
      const owner = this.owner;
      if (!owner || owner.destroyed || !this.coinPrefab) {
        return;
      }
      const startScreen = this._getRandomScreenPoint();
      const targetScreen = this._getTargetScreenPoint();
      const startLocal = this._screenToParentLocal(startScreen.x, startScreen.y);
      const targetLocal = this._screenToParentLocal(targetScreen.x, targetScreen.y);
      const goldCount = this._randomGoldCount();
      const coinCount = this._getCoinCount(goldCount);
      owner.pos(0, 0);
      this._spawnCoins(startLocal.x, startLocal.y, targetLocal.x, targetLocal.y, coinCount, goldCount);
    }
    _spawnCoins(fromX, fromY, toX, toY, coinCount, goldCount) {
      const owner = this.owner;
      const coinSize = this.coinSize;
      const cols = coinCount > 5 ? Math.ceil(coinCount * 0.5) : coinCount;
      const rows = coinCount > 5 ? 2 : 1;
      const parentWidth = this._getParentWidth();
      const parentHeight = this._getParentHeight();
      let x = fromX - coinSize * (cols - 1) * 0.5;
      let y = fromY + coinSize / (coinCount > 6 ? 2 : 1);
      x = Math.max(coinSize, Math.min(x, parentWidth - coinSize * cols));
      y = Math.max(coinSize, Math.min(y, parentHeight));
      const flyTime = Math.sqrt(__pow(toX - fromX, 2) + __pow(toY - fromY, 2)) / this.flySpeed;
      let done = 0;
      const textY = y + 40 - coinSize * (rows - 1) * 0.5;
      this._playGoldText(fromX, textY, goldCount);
      for (let i = 0; i < coinCount; i++) {
        const coin = this.coinPrefab.create();
        if (!coin) {
          continue;
        }
        owner.addChild(coin);
        coin.zOrder = -i;
        coin.visible = false;
        const row = Math.floor(i / cols);
        const col = i % cols;
        const offsetX = coinCount % 2 === 0 || row === 0 ? 0 : coinSize * 0.5;
        const delay = row === 0 ? 0 : cols / 30;
        const xx = x + col * coinSize + offsetX;
        const yy = y - row * coinSize + 20;
        coin.pos(xx, yy);
        play(seq(
          wait(delay + (5 + col * 2) / 30),
          show(),
          seq(
            moveTo(5 / 30, xx, yy + 60, 0),
            moveTo(8 / 30, xx, yy - 5, 0, "sineInOut"),
            moveTo(8 / 30, xx, yy + 40, 0, "sineInOut"),
            moveTo(8 / 30, xx, yy + 20, 0),
            wait(2 / 30 - delay),
            moveTo(flyTime, toX, toY, 0, "quadIn")
          ),
          call(() => {
            coin.visible = false;
            if (++done === coinCount) {
              owner.destroy();
            }
          })
        ), coin);
      }
      const destroyDelayMs = Math.max(3e3, (flyTime + 2) * 1e3);
      Laya.timer.once(destroyDelayMs, this, () => owner.destroy());
    }
    _playGoldText(centerX, y, goldCount) {
      const textNode = this.textNode;
      if (!textNode || goldCount <= 0) {
        return;
      }
      this._setTextValue(String(goldCount));
      textNode.pos(centerX, y);
      textNode.visible = false;
      textNode.scale(this._textBaseScaleX * 0.01, this._textBaseScaleY * 0.01);
      play(seq(
        wait(0.3),
        show(),
        scaleTo(5 / 30, this._textBaseScaleX * 1.2, this._textBaseScaleY * 1.2, 0, "quadOut"),
        scaleTo(3 / 30, this._textBaseScaleX, this._textBaseScaleY),
        wait(1),
        scaleTo(0.2, 0, 0),
        call(() => {
          textNode.visible = false;
        })
      ), textNode);
    }
    _findTextNode() {
      var _a;
      const owner = this.owner;
      this.textNode = (_a = this.textNode) != null ? _a : owner.getChildByName("text");
    }
    _cacheTextScale() {
      if (!this.textNode) {
        return;
      }
      this._textBaseScaleX = this.textNode.scaleX || 1;
      this._textBaseScaleY = this.textNode.scaleY || 1;
    }
    _setTextValue(value) {
      const textNode = this.textNode;
      if (!textNode) {
        return;
      }
      const spriteFont = textNode.getComponent(SpriteFont);
      if (spriteFont) {
        spriteFont.text = value;
        spriteFont.forceRefresh();
        return;
      }
      if ("text" in textNode) {
        textNode.text = value;
      }
    }
    _getRandomScreenPoint() {
      const uiWidth = this._getUIWidth();
      const uiHeight = this._getUIHeight();
      return {
        x: this._randomRange(this.screenPadding, uiWidth - this.screenPadding),
        y: this._randomRange(this.screenPadding, uiHeight - this.screenPadding)
      };
    }
    _getTargetScreenPoint() {
      const uiWidth = this._getUIWidth();
      const uiHeight = this._getUIHeight();
      return {
        x: uiWidth * 0.5,
        y: Math.min(uiHeight - this.screenPadding, uiHeight * 0.5 + this.targetOffsetY)
      };
    }
    _screenToParentLocal(screenX, screenY) {
      var _a;
      const parent = (_a = this.owner) == null ? void 0 : _a.parent;
      if (!parent) {
        return new Laya.Point(screenX, screenY);
      }
      const parentOrigin = parent.localToGlobal(this._tempPoint.setTo(0, 0), false);
      return new Laya.Point(screenX - parentOrigin.x, screenY - parentOrigin.y);
    }
    _getParentWidth() {
      var _a;
      const parent = (_a = this.owner) == null ? void 0 : _a.parent;
      return (parent == null ? void 0 : parent.width) || this._getUIWidth();
    }
    _getParentHeight() {
      var _a;
      const parent = (_a = this.owner) == null ? void 0 : _a.parent;
      return (parent == null ? void 0 : parent.height) || this._getUIHeight();
    }
    _getUIWidth() {
      return 1136;
    }
    _getUIHeight() {
      return 640;
    }
    _randomGoldCount() {
      return Math.floor(this._randomRange(CoinFlyFakeView.MIN_GOLD_COUNT, CoinFlyFakeView.MAX_GOLD_COUNT + 1));
    }
    _randomRange(min, max) {
      if (max <= min) {
        return min;
      }
      return min + Math.random() * (max - min);
    }
    _getCoinCount(goldCount) {
      if (goldCount > 250) return 11;
      if (goldCount > 150) return 9;
      if (goldCount > 50) return 8;
      if (goldCount > 20) return 8;
      if (goldCount > 12) return 7;
      if (goldCount > 9) return 8;
      if (goldCount > 6) return 6;
      if (goldCount > 3) return 4;
      return 2;
    }
  };
  __name(CoinFlyFakeView, "CoinFlyFakeView");
  CoinFlyFakeView.MIN_GOLD_COUNT = 1e5;
  CoinFlyFakeView.MAX_GOLD_COUNT = 2e5;
  CoinFlyFakeView.MIN_START_DELAY_MS = 1e3;
  CoinFlyFakeView.MAX_START_DELAY_MS = 3e3;
  __decorateClass([
    property10({ type: Laya.Prefab, caption: "金币预制体" })
  ], CoinFlyFakeView.prototype, "coinPrefab", 2);
  __decorateClass([
    property10({ type: Laya.Sprite, caption: "数字节点" })
  ], CoinFlyFakeView.prototype, "textNode", 2);
  __decorateClass([
    property10({ type: Number, caption: "金币大小(px)" })
  ], CoinFlyFakeView.prototype, "coinSize", 2);
  __decorateClass([
    property10({ type: Number, caption: "飞行速度(px/s)" })
  ], CoinFlyFakeView.prototype, "flySpeed", 2);
  __decorateClass([
    property10({ type: Number, caption: "屏幕边距(px)" })
  ], CoinFlyFakeView.prototype, "screenPadding", 2);
  __decorateClass([
    property10({ type: Number, caption: "落点下偏移(px)" })
  ], CoinFlyFakeView.prototype, "targetOffsetY", 2);
  CoinFlyFakeView = __decorateClass([
    regClass11("31895d50-05f7-43a5-a7d7-8ddc34fb2c9c", "../src/Play/Effect/View/CoinFlyFakeView.ts")
  ], CoinFlyFakeView);

  // src/Play/Effect/View/CoinFlyView.ts
  var { regClass: regClass12, property: property11 } = Laya;
  var CoinFlyView = class extends Laya.Script {
    constructor() {
      super(...arguments);
      this.coinPrefab = null;
      this.textNode = null;
      this.coinSize = 56;
      this.flySpeed = 600;
      this.previewCount = 8;
      this.previewGoldCount = 8888;
      this._fromX = 0;
      this._fromY = 0;
      this._toX = 0;
      this._toY = 0;
      this._coinCount = 0;
      this._goldCount = 0;
      this._hasSetup = false;
      this._textBaseScaleX = 1;
      this._textBaseScaleY = 1;
    }
    onAwake() {
      this._findTextNode();
      this._cacheTextScale();
    }
    /**
     * 由程序调用，在 addChild 之前设置动画参数。
     * 坐标为相对于 owner 父节点的本地坐标。
     */
    setup(fromX, fromY, toX, toY, coinCount, goldCount) {
      this._fromX = fromX;
      this._fromY = fromY;
      this._toX = toX;
      this._toY = toY;
      this._coinCount = coinCount;
      this._goldCount = goldCount;
      this._hasSetup = true;
    }
    onStart() {
      if (!this.coinPrefab) {
        return;
      }
      if (this._hasSetup) {
        this._spawnCoins(
          this._fromX,
          this._fromY,
          this._toX,
          this._toY,
          this._coinCount,
          this._goldCount
        );
        return;
      }
      const owner = this.owner;
      const g = owner.localToGlobal(new Laya.Point(0, 0));
      const cx = Laya.stage.width * 0.5 - g.x;
      const cy = Laya.stage.height * 0.5 - g.y;
      this._spawnCoins(cx, cy, cx - 350, cy + 250, this.previewCount, this.previewGoldCount);
    }
    onDestroy() {
      Laya.timer.clearAll(this);
    }
    _spawnCoins(fromX, fromY, toX, toY, coinCount, goldCount) {
      var _a, _b;
      const owner = this.owner;
      const coinSize = this.coinSize;
      const cols = coinCount > 5 ? Math.ceil(coinCount * 0.5) : coinCount;
      const rows = coinCount > 5 ? 2 : 1;
      const stageWidth = ((_a = Laya.stage) == null ? void 0 : _a.width) || 1920;
      const stageHeight = ((_b = Laya.stage) == null ? void 0 : _b.height) || 1080;
      let x = fromX - coinSize * (cols - 1) * 0.5;
      let y = fromY + coinSize / (coinCount > 6 ? 2 : 1);
      x = Math.max(coinSize, Math.min(x, stageWidth - coinSize * cols));
      y = Math.max(coinSize, Math.min(y, stageHeight));
      const flyTime = Math.sqrt(__pow(toX - fromX, 2) + __pow(toY - fromY, 2)) / this.flySpeed;
      let done = 0;
      const textY = y + 40 - coinSize * (rows - 1) * 0.5;
      this._playGoldText(fromX, textY, goldCount);
      for (let i = 0; i < coinCount; i++) {
        const coin = this._createCoin(i);
        if (!coin) {
          continue;
        }
        if (coin.parent !== owner) {
          owner.addChild(coin);
        }
        coin.zOrder = -i;
        coin.visible = false;
        const row = Math.floor(i / cols);
        const col = i % cols;
        const offsetX = coinCount % 2 === 0 || row === 0 ? 0 : coinSize * 0.5;
        const delay = row === 0 ? 0 : cols / 30;
        const xx = x + col * coinSize + offsetX;
        const yy = y - row * coinSize + 20;
        coin.pos(xx, yy);
        play(seq(
          wait(delay + (5 + col * 2) / 30),
          show(),
          seq(
            moveTo(5 / 30, xx, yy + 60, 0),
            moveTo(8 / 30, xx, yy - 5, 0, "sineInOut"),
            moveTo(8 / 30, xx, yy + 40, 0, "sineInOut"),
            moveTo(8 / 30, xx, yy + 20, 0),
            wait(2 / 30 - delay),
            moveTo(flyTime, toX, toY, 0, "quadIn")
          ),
          call(() => {
            var _a2;
            coin.visible = false;
            if (++done === coinCount) {
              (_a2 = this.owner) == null ? void 0 : _a2.destroy();
            }
          })
        ), coin);
      }
      Laya.timer.once(3e3, this, () => {
        var _a2;
        return (_a2 = this.owner) == null ? void 0 : _a2.destroy();
      });
    }
    _playGoldText(centerX, y, goldCount) {
      const textNode = this.textNode;
      if (!textNode || goldCount <= 0) {
        return;
      }
      this._setTextValue(String(goldCount));
      textNode.pos(centerX, y);
      textNode.visible = false;
      textNode.scale(this._textBaseScaleX * 0.01, this._textBaseScaleY * 0.01);
      play(seq(
        wait(0.3),
        show(),
        scaleTo(5 / 30, this._textBaseScaleX * 1.2, this._textBaseScaleY * 1.2, 0, "quadOut"),
        scaleTo(3 / 30, this._textBaseScaleX, this._textBaseScaleY),
        wait(1),
        scaleTo(0.2, 0, 0),
        call(() => {
          textNode.visible = false;
        })
      ), textNode);
    }
    _createCoin(index) {
      if (!this.coinPrefab) {
        return null;
      }
      const coin = this.coinPrefab.create();
      if (!coin) {
        return null;
      }
      if (index === 0) {
        coin.name = coin.name || "coin";
      }
      return coin;
    }
    _findTextNode() {
      var _a;
      const owner = this.owner;
      this.textNode = (_a = this.textNode) != null ? _a : owner.getChildByName("text");
    }
    _cacheTextScale() {
      if (!this.textNode) {
        return;
      }
      this._textBaseScaleX = this.textNode.scaleX || 1;
      this._textBaseScaleY = this.textNode.scaleY || 1;
    }
    _setTextValue(value) {
      const textNode = this.textNode;
      if (!textNode) {
        return;
      }
      const spriteFont = textNode.getComponent(SpriteFont);
      if (spriteFont) {
        spriteFont.text = value;
        return;
      }
      if ("text" in textNode) {
        textNode.text = value;
      }
    }
  };
  __name(CoinFlyView, "CoinFlyView");
  __decorateClass([
    property11({ type: Laya.Prefab, caption: "金币预制体" })
  ], CoinFlyView.prototype, "coinPrefab", 2);
  __decorateClass([
    property11({ type: Laya.Sprite, caption: "数字节点" })
  ], CoinFlyView.prototype, "textNode", 2);
  __decorateClass([
    property11({ type: Number, caption: "金币大小 (px)" })
  ], CoinFlyView.prototype, "coinSize", 2);
  __decorateClass([
    property11({ type: Number, caption: "飞行速度 (px/s)" })
  ], CoinFlyView.prototype, "flySpeed", 2);
  __decorateClass([
    property11({ type: Number, caption: "预览金币数量" })
  ], CoinFlyView.prototype, "previewCount", 2);
  __decorateClass([
    property11({ type: Number, caption: "预览金币数值" })
  ], CoinFlyView.prototype, "previewGoldCount", 2);
  CoinFlyView = __decorateClass([
    regClass12("c13d435d-20c5-483e-a21c-0bd2752344a9", "../src/Play/Effect/View/CoinFlyView.ts")
  ], CoinFlyView);

  // src/Play/Effect/View/CoinPieView.ts
  var { regClass: regClass13, property: property12 } = Laya;
  var CoinPieView = class extends Laya.Script {
    constructor() {
      super(...arguments);
      this.coinPrefab = null;
      this.runDelayTime = 0.5;
      this.flySpeed = 800;
      this._fromX = 0;
      this._fromY = 0;
      this._toX = 0;
      this._toY = 0;
      // ============ 公共接口 ============
      this._hasSetup = false;
    }
    // ============ 生命周期 ============
    /**
     * 由程序调用，在 addChild 之前设置动画参数。
     * 坐标为相对于 owner 父节点的本地坐标。
     */
    setup(fromX, fromY, toX, toY) {
      this._fromX = fromX;
      this._fromY = fromY;
      this._toX = toX;
      this._toY = toY;
      this._hasSetup = true;
    }
    onStart() {
      if (!this.coinPrefab) return;
      if (this._hasSetup) {
        this._spawnCoins(this._fromX, this._fromY, this._toX, this._toY);
      } else {
        const g = this.owner.localToGlobal(new Laya.Point(0, 0));
        const cx = Laya.stage.width * 0.5 - g.x;
        const cy = Laya.stage.height * 0.5 - g.y;
        this._spawnCoins(cx, cy, cx - 350, cy + 250);
      }
    }
    // ============ 私有方法 ============
    onDestroy() {
      Laya.timer.clearAll(this);
    }
    _spawnCoins(fromX, fromY, toX, toY) {
      const offsets = CoinPieView.OFFSETS;
      const count = offsets.length;
      let maxFlyTime = 0;
      let done = 0;
      for (let i = 0; i < count; i++) {
        const coin = this.coinPrefab.create();
        if (!coin) continue;
        this.owner.addChild(coin);
        coin.zOrder = -i;
        coin.visible = false;
        const jitterX = (Math.random() - 0.5) * 40;
        const jitterY = (Math.random() - 0.5) * 40;
        const xx = fromX + offsets[i][0] + jitterX;
        const yy = fromY + offsets[i][1] + jitterY;
        coin.pos(xx, yy);
        const dx = toX - xx;
        const dy = toY - yy;
        const flyTime = Math.sqrt(dx * dx + dy * dy) / this.flySpeed;
        if (flyTime > maxFlyTime) maxFlyTime = flyTime;
        play(seq(
          wait(this.runDelayTime),
          show(),
          seq(
            moveTo(5 / 30, xx, yy + 60, 0),
            moveTo(8 / 30, xx, yy - 5, 0, "sineInOut"),
            moveTo(8 / 30, xx, yy + 40, 0, "sineInOut"),
            moveTo(5 / 30, xx, yy + 20, 0),
            moveTo(flyTime, toX, toY, 0, "quadIn")
          ),
          call(() => {
            var _a;
            coin.visible = false;
            if (++done === count) (_a = this.owner) == null ? void 0 : _a.destroy();
          })
        ), coin);
      }
      const bounceTime = (5 + 8 + 8 + 5) / 30;
      const destroyDelay = (this.runDelayTime + bounceTime + maxFlyTime + 1) * 1e3;
      Laya.timer.once(destroyDelay, this, () => {
        var _a;
        return (_a = this.owner) == null ? void 0 : _a.destroy();
      });
    }
  };
  __name(CoinPieView, "CoinPieView");
  // ============ 可在 IDE 面板调整的参数 ============
  /**
   * 20 枚金币的固定偏移坐标（Laya Y-down，由 GameEffectGoldPie.cs 转换而来）
   * 原始坐标为 Unity Y-up，转换规则：offsetY_laya = -offsetY_unity
   */
  CoinPieView.OFFSETS = [
    [-103, -168],
    [-2, -184],
    [103, -146],
    [-68, -122],
    [36, -123],
    [-149, -69],
    [-87, -41],
    [6, -67],
    [149, -87],
    [-166, 26],
    [-105, 25],
    [-39, 2],
    [28, -36],
    [100, -27],
    [146, -3],
    [-122, 111],
    [16, 60],
    [125, 69],
    [-29, 127],
    [59, 142]
  ];
  __decorateClass([
    property12({ type: Laya.Prefab, caption: "金币预制体" })
  ], CoinPieView.prototype, "coinPrefab", 2);
  __decorateClass([
    property12({ type: Number, caption: "飞行前延迟 (s)" })
  ], CoinPieView.prototype, "runDelayTime", 2);
  __decorateClass([
    property12({ type: Number, caption: "飞行速度 (px/s)" })
  ], CoinPieView.prototype, "flySpeed", 2);
  CoinPieView = __decorateClass([
    regClass13("7c205909-958e-4696-826d-209004309aac", "../src/Play/Effect/View/CoinPieView.ts")
  ], CoinPieView);

  // src/Play/Effect/View/CoinScatterView.ts
  var { regClass: regClass14, property: property13 } = Laya;
  var CoinScatterView = class extends Laya.Script {
    constructor() {
      super(...arguments);
      this.coinPrefab = null;
      this.explodeRadius = 1300;
      this.scaleFactor = 3;
      this.duration = 1.5;
      this.previewCount = 20;
      // ============ 私有状态 ============
      this._cx = 0;
      this._cy = 0;
      this._count = 0;
      this._hasSetup = false;
    }
    // ============ 公共接口 ============
    /**
     * 由程序调用，在 addChild 之前设置动画参数。
     * 坐标为相对于 owner 父节点的本地坐标。
     */
    setup(centerX, centerY, count) {
      this._cx = centerX;
      this._cy = centerY;
      this._count = count;
      this._hasSetup = true;
    }
    // ============ 生命周期 ============
    onStart() {
      if (!this.coinPrefab) return;
      if (this._hasSetup) {
        this._spawnExplode(this._cx, this._cy, this._count);
      } else {
        const g = this.owner.localToGlobal(new Laya.Point(0, 0));
        const cx = Laya.stage.width * 0.5 - g.x;
        const cy = Laya.stage.height * 0.5 - g.y;
        this._spawnExplode(cx, cy, this.previewCount);
      }
    }
    onDestroy() {
      Laya.timer.clearAll(this);
    }
    // ============ 私有方法 ============
    _spawnExplode(cx, cy, count) {
      for (let i = 0; i < count; i++) {
        const coin = this.coinPrefab.create();
        if (!coin) continue;
        this.owner.addChild(coin);
        coin.pos(cx, cy);
        coin.visible = false;
        const angle = Math.random() * Math.PI * 2;
        play(seq(
          wait(Math.random()),
          show(),
          spawn(
            scaleTo(this.duration, this.scaleFactor, this.scaleFactor),
            moveTo(
              this.duration,
              cx + Math.cos(angle) * this.explodeRadius,
              cy + Math.sin(angle) * this.explodeRadius
            )
          )
        ), coin);
      }
      Laya.timer.once(4e3, this, () => {
        var _a;
        return (_a = this.owner) == null ? void 0 : _a.destroy();
      });
    }
  };
  __name(CoinScatterView, "CoinScatterView");
  __decorateClass([
    property13({ type: Laya.Prefab, caption: "金币预制体" })
  ], CoinScatterView.prototype, "coinPrefab", 2);
  __decorateClass([
    property13({ type: Number, caption: "爆炸半径 (px)" })
  ], CoinScatterView.prototype, "explodeRadius", 2);
  __decorateClass([
    property13({ type: Number, caption: "金币放大倍数" })
  ], CoinScatterView.prototype, "scaleFactor", 2);
  __decorateClass([
    property13({ type: Number, caption: "动画时长 (s)" })
  ], CoinScatterView.prototype, "duration", 2);
  __decorateClass([
    property13({ type: Number, caption: "预览金币数量" })
  ], CoinScatterView.prototype, "previewCount", 2);
  CoinScatterView = __decorateClass([
    regClass14("046a77bf-3db4-450a-9502-ddfb5afa9849", "../src/Play/Effect/View/CoinScatterView.ts")
  ], CoinScatterView);

  // src/Play/Effect/View/EffectRotate.ts
  var { regClass: regClass15, property: property14 } = Laya;
  var EffectRotate = class extends Laya.Script3D {
    constructor() {
      super(...arguments);
      this.rotate = new Laya.Vector3(0, 0, 0);
    }
    onUpdate() {
      this.owner.transform.rotate(this.rotate, false, false);
    }
  };
  __name(EffectRotate, "EffectRotate");
  __decorateClass([
    property14({ type: Laya.Vector3, caption: "每帧旋转角度" })
  ], EffectRotate.prototype, "rotate", 2);
  EffectRotate = __decorateClass([
    regClass15("29af30f1-4b94-4c1e-ae08-9407213ed1b4", "../src/Play/Effect/View/EffectRotate.ts")
  ], EffectRotate);

  // src/TAEffect/ShaderTimeUpdater.ts
  var { regClass: regClass16, property: property15 } = Laya;
  var ShaderTimeUpdater = class extends Laya.Script {
    constructor() {
      super(...arguments);
      this.shaderPropName = "u_CurrentTime";
      this.speed = 1;
      this._mat = null;
      this._time = 0;
      this._propIndex = -1;
    }
    onEnable() {
      var _a, _b, _c, _d, _e, _f;
      const sprite = this.owner;
      const mat = (_f = (_e = (_b = (_a = sprite._renderNode) == null ? void 0 : _a.sharedMaterials) == null ? void 0 : _b[0]) != null ? _e : (_d = (_c = sprite._renderNode) == null ? void 0 : _c._materials) == null ? void 0 : _d[0]) != null ? _f : null;
      if (!mat) {
        console.warn(`[ShaderTimeUpdater] "${this.owner.name}" 未找到材质`);
        return;
      }
      this._mat = mat;
      this._time = 0;
      this._propIndex = Laya.Shader3D.propertyNameToID(this.shaderPropName);
    }
    onUpdate() {
      var _a;
      if (!this._mat || this._propIndex === -1) return;
      this._time += Laya.timer.delta / 1e3 * this.speed;
      (_a = this._mat.shaderData) == null ? void 0 : _a.setNumber(this._propIndex, this._time);
    }
    onDisable() {
      this._mat = null;
      this._propIndex = -1;
    }
  };
  __name(ShaderTimeUpdater, "ShaderTimeUpdater");
  __decorateClass([
    property15({ type: String, label: "Shader 变量名", default: "u_CurrentTime" })
  ], ShaderTimeUpdater.prototype, "shaderPropName", 2);
  __decorateClass([
    property15({ type: Number, label: "时间速度倍率", default: 1 })
  ], ShaderTimeUpdater.prototype, "speed", 2);
  ShaderTimeUpdater = __decorateClass([
    regClass16("4166d2dc-37ae-42c7-b2d0-8ac88ade4f53", "../src/TAEffect/ShaderTimeUpdater.ts")
  ], ShaderTimeUpdater);
})();
//# sourceMappingURL=bundle.js.map
