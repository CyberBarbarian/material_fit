/**
 * 动作系统 - 基于 LayaAir Tween 的声明式动画系统
 *
 * 支持 2D (Laya.Sprite) 和 3D (Laya.Sprite3D) 对象，自动检测目标类型并选择合适的 API。
 *
 * @example 基本用法
 * ```typescript
 * import { play, seq, spawn, moveTo, scaleTo, fadeTo, anim, wait } from "./Common/Action";
 *
 * // 创建动作序列：先播放动画，然后同时移动和缩放，最后淡出
 * const action = seq(
 *     anim("idle"),                                    // 播放动画
 *     spawn(                                           // 并行执行
 *         moveTo(1, 10, 5, 0, "sineOut"),            // 移动到 (10, 5, 0)
 *         scaleTo(0.5, 2, 2)                          // 缩放到 2 倍
 *     ),
 *     wait(0.5),                                       // 等待 0.5 秒
 *     fadeTo(0.3, 0)                                   // 淡出
 * );
 *
 * // 播放动作
 * const ctrl = play(action, mySprite3D, { animator: myAnimator });
 *
 * // 控制播放
 * ctrl.stop();        // 停止播放
 * await ctrl.done;    // 等待完成
 * ```
 *
 * @example 容器动作
 * ```typescript
 * // 顺序执行
 * seq(action1, action2, action3);
 *
 * // 并行执行
 * spawn(action1, action2, action3);
 *
 * // 重复执行
 * repeat(3, action);  // 重复 3 次
 * ```
 *
 * @example 缓动动作（支持 2D/3D）
 * ```typescript
 * // 移动
 * moveTo(1, 100, 200, 0, "sineOut");      // 移动到绝对位置
 * moveBy(1, 50, 0, 0, "quadIn");          // 相对移动
 * moveToward(1, 200, 300, 0.5, "linear"); // 向目标移动 50%
 *
 * // 缩放
 * scaleTo(0.5, 2, 2);                     // 缩放到 2 倍
 * scaleBy(0.5, 1.5, 1.5);                 // 相对缩放 1.5 倍
 *
 * // 旋转
 * rotateTo(1, 90, "z", "backOut");        // 旋转到 90 度（z 轴）
 * rotateBy(1, 180, "z");                  // 相对旋转 180 度
 *
 * // 透明度
 * fadeTo(0.3, 0);                         // 淡出到透明
 * ```
 *
 * @example 即时动作
 * ```typescript
 * anim("attack", 0.2);                    // 播放动画，0.2 秒融合时间
 * anim("idle", 0, true);                  // 停止动画
 * effect("res/effects/hit.lh", { duration: 2 }); // 播放特效，2 秒后销毁
 * sound("res/audio/hit.mp3", 0.8);        // 播放音效，音量 0.8
 * event("onHit", { damage: 10 });         // 派发事件
 * call((target, ctrl) => { console.log("自定义逻辑"); }); // 执行回调
 * show();                                 // 显示节点
 * hide();                                 // 隐藏节点
 * destroy();                              // 销毁节点
 * ```
 *
 */

export {
    // 核心 API
    play,
    Controller,
    EaseType,

    // 类型
    type IPlayable,
    type PlayOptions,
    type AnimTarget,

    // 容器动作
    seq,
    spawn,
    repeat,

    // 缓动动作
    wait,
    moveTo,
    moveBy,
    moveToward,
    scaleTo,
    scaleBy,
    rotateTo,
    rotateBy,
    fadeTo,
    valueTo,

    // 即时动作
    anim,
    effect,
    sound,
    show,
    hide,
    destroy,
    call,
    event,
} from "./Compat/Compat";
