const { regClass, property } = Laya;

type CaptureView = {
    id?: string;
    view_id?: string;
    yaw: number;
    pitch?: number;
    file_name?: string;
};

type BrowserScoreReference = {
    id?: string;
    view_id?: string;
    file_name?: string;
    url?: string;
    path?: string;
};

type BrowserScoreConfig = {
    enabled?: boolean;
    metric?: string;
    emit_artifacts?: "never" | "always";
    reference_images?: BrowserScoreReference[];
    rgb_weight?: number;
    alpha_weight?: number;
    residual_grid_size?: number;
};

type BrowserScoreView = {
    view_id: string;
    diff_score: number;
    fit_score: number;
    rgb_mae: number;
    alpha_mae: number;
    mask_iou: number;
    foreground_weight_sum: number;
    residual_grid_size?: number;
    residual_features?: number[];
};

type CaptureCommand = {
    enabled?: boolean;
    nonce: string;
    server_base_url?: string;
    post_url?: string;
    camera_name?: string;
    target_name?: string;
    width?: number;
    height?: number;
    center?: number[];
    target_size?: number[];
    distance_scale?: number;
    min_distance?: number;
    fov?: number;
    capture_mode?: "auto" | "orbit_camera" | "rotate_target";
    yaw_offset?: number;
    pitch_offset?: number;
    target_yaw_sign?: number;
    target_pitch_sign?: number;
    target_base_yaw?: number;
    target_base_pitch?: number;
    transparent_background?: boolean;
    zero_transparent_rgb?: boolean;
    alpha_from_rgb?: boolean;
    alpha_from_rgb_threshold?: number;
    alpha_source?: "silhouette_mask" | "alpha_from_rgb" | "render_alpha";
    visual_background_color?: number[] | string;
    background_color?: number[] | string;
    image_format?: "png" | "raw_rgba";
    settle_frames?: number;
    freeze_animators?: boolean;
    fixed_animation_state?: string;
    fixed_animation_layer?: number;
    fixed_animation_time?: number;
    restore_animators_after_capture?: boolean;
    preserve_artifact_alpha?: boolean;
    mask_alpha_mode?: "binary" | "soft";
    mask_alpha_threshold?: number;
    flip_y?: boolean;
    render_texture_srgb?: boolean;
    browser_score?: BrowserScoreConfig;
    material_patch?: MaterialPatch;
    views?: CaptureView[];
};

type MaterialPatch = {
    target_name?: string;
    values?: { [name: string]: number | number[] | boolean };
    render_states?: { [name: string]: number | boolean };
    defines?: {
        managed?: string[];
        enabled?: string[];
    };
};

type MaterialPatchResult = {
    applied: boolean;
    materialCount: number;
    valueCount: number;
    defineCount: number;
    renderStateCount: number;
    enabledDefines: string[];
    appliedRenderStates: { [name: string]: number | boolean };
    fallback?: string;
    error?: string;
};

type RendererState = {
    source: any;
    enabled: boolean | null;
    materials: Laya.Material[] | null;
};

type AnimatorState = {
    source: any;
    speed: number | null;
    enabled: boolean | null;
    sleep: boolean | null;
};

@regClass()
export class MaterialFitCapture extends Laya.Script3D {
    @property({ type: String, caption: "Server Base URL" })
    public serverBaseUrl: string = "http://127.0.0.1:8787";

    @property({ type: String, caption: "Default Camera Name" })
    public cameraName: string = "";

    @property({ type: String, caption: "Default Target Name" })
    public targetName: string = "";

    @property({ type: Number, caption: "Poll Interval Ms" })
    public pollIntervalMs: number = 500;

    @property({ type: Boolean, caption: "Auto Poll" })
    public autoPoll: boolean = true;

    private _busy: boolean = false;
    private _lastNonce: string = "";
    private _nextPollAt: number = 0;
    private _pollFailureCount: number = 0;
    private _referenceCache: Map<string, Uint8ClampedArray> = new Map();

    public onEnable(): void {
        (Laya.Browser.window as any).__materialFitCapture = (command: CaptureCommand) => this.capture(command);
        if (this.autoPoll) {
            Laya.timer.loop(Math.max(100, this.pollIntervalMs), this, this.pollCommand);
            Laya.timer.once(100, this, this.pollCommand);
        }
    }

    public onDisable(): void {
        Laya.timer.clear(this, this.pollCommand);
    }

    private async pollCommand(): Promise<void> {
        if (this._busy) {
            return;
        }
        if (Date.now() < this._nextPollAt) {
            return;
        }
        try {
            const url = `${this.serverBaseUrl}/material-fit/capture-command?last_nonce=${encodeURIComponent(this._lastNonce)}`;
            const response = await fetch(url);
            if (!response.ok) {
                this.schedulePollRetry();
                return;
            }
            this._pollFailureCount = 0;
            this._nextPollAt = 0;
            const command = await response.json() as CaptureCommand;
            if (!command || command.enabled === false || !command.nonce || command.nonce === this._lastNonce) {
                return;
            }
            this._lastNonce = command.nonce;
            await this.capture(command);
        } catch (error) {
            this.schedulePollRetry();
        }
    }

    private schedulePollRetry(): void {
        this._pollFailureCount = Math.min(this._pollFailureCount + 1, 6);
        const delay = Math.min(10000, 500 * Math.pow(2, this._pollFailureCount));
        this._nextPollAt = Date.now() + delay;
    }

    private async capture(command: CaptureCommand): Promise<void> {
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
            const preFreezeTargetEuler = target ? target.transform.localRotationEuler.clone() : null;
            const frozenAnimators = this.freezeAnimators(command, target || this.sceneRoot());
            if (frozenAnimators.length > 0) {
                await this.waitFrames(1);
                this.pauseAnimators(frozenAnimators);
            }
            const originalTargetEuler = target ? target.transform.localRotationEuler.clone() : preFreezeTargetEuler;
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
                command.render_texture_srgb !== false,
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
                `applied=${patchResult.applied} materials=${patchResult.materialCount} values=${patchResult.valueCount}${patchResult.fallback ? ` fallback=${patchResult.fallback}` : ""}${patchResult.error ? ` error=${patchResult.error}` : ""}`,
            );
            if (frozenAnimators.length > 0) {
                void this.postLog(
                    command,
                    "animation_freeze",
                    `animators=${frozenAnimators.length}${command.fixed_animation_state ? ` state=${command.fixed_animation_state}` : ""}`,
                );
            }

            const views = command.views && command.views.length > 0
                ? command.views
                : [{ yaw: 0, pitch: 0, file_name: "laya_capture.png" }];
            const settleFrames = this.resolveSettleFrames(command);
            const browserScoreEnabled = this.shouldUseBrowserScore(command);
            const emitArtifacts = !browserScoreEnabled || this.shouldEmitArtifacts(command);
            const postTasks: Promise<void>[] = [];
            const browserScoreViews: BrowserScoreView[] = [];
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
                    await this.waitFrames(settleFrames);
                    if (captureMode === "rotate_target" && target && originalTargetEuler) {
                        this.rotateTargetForView(target, originalTargetEuler, view, command);
                        await this.waitFrames(1);
                    }
                    const pixels = await this.readPixels(renderTexture, width, height);
                    const alphaSource = this.resolveAlphaSource(command);
                    if (command.transparent_background !== false && alphaSource === "silhouette_mask" && target) {
                        const maskPixels = await this.renderSilhouetteMask(camera, renderTexture, target, width, height);
                        this.applyMaskAlpha(pixels, maskPixels, command.mask_alpha_mode, command.mask_alpha_threshold);
                    } else if (command.transparent_background !== false && alphaSource === "alpha_from_rgb") {
                        this.liftRgbIntoAlpha(pixels, command.alpha_from_rgb_threshold);
                    }
                    if (command.zero_transparent_rgb !== false) {
                        this.zeroTransparentRgb(pixels);
                    }
                    const outputPixels = this.copyPixelsForOutput(pixels, width, height, command.flip_y === true);
                    if (browserScoreEnabled) {
                        const scorePixels = this.copyPixelsForBrowserScore(outputPixels, command);
                        browserScoreViews.push(await this.scoreBrowserView(command, view, index, scorePixels, width, height));
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
                            false,
                            command,
                        );
                        postTasks.push(this.postImage(command, view, index, dataUrl, width, height, patchResult));
                    }
                }
            } finally {
                if (target && preFreezeTargetEuler) {
                    target.transform.localRotationEuler = preFreezeTargetEuler;
                }
                if (command.restore_animators_after_capture !== false) {
                    this.restoreAnimators(frozenAnimators);
                }
                camera.renderTarget = previousTarget;
                camera.fieldOfView = previousFov;
                if (previousClearColor) {
                    camera.clearColor = previousClearColor;
                }
                renderTexture.destroy();
            }
            await Promise.all(postTasks);
            if (browserScoreEnabled) {
                await this.postBrowserScore(command, this.aggregateBrowserScore(command, browserScoreViews, width, height, patchResult));
            }

            void this.postLog(command, "completed", `Captured ${views.length} views in ${Date.now() - startedAt}ms`);
        } catch (error) {
            await this.postLog(command, "capture_error", String(error));
        } finally {
            this._busy = false;
        }
    }

    private resolveCamera(name: string): Laya.Camera | null {
        if (this.owner instanceof Laya.Camera) {
            return this.owner as Laya.Camera;
        }
        const root = this.sceneRoot();
        const node = name ? this.findNodeByName(root, name) : this.findFirstCamera(root);
        return node instanceof Laya.Camera ? node as Laya.Camera : null;
    }

    private resolveTarget(name: string): Laya.Sprite3D | null {
        if (!name) {
            return null;
        }
        const node = this.findNodeByName(this.sceneRoot(), name);
        return node instanceof Laya.Sprite3D ? node as Laya.Sprite3D : null;
    }

    private sceneRoot(): any {
        let node: any = this.owner;
        while (node && node.parent) {
            node = node.parent;
        }
        return node || this.owner;
    }

    private findNodeByName(root: any, name: string): any {
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

    private findFirstCamera(root: any): Laya.Camera | null {
        if (!root) {
            return null;
        }
        if (root instanceof Laya.Camera) {
            return root as Laya.Camera;
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

    private resolveCaptureMode(command: CaptureCommand, camera: Laya.Camera, target: Laya.Sprite3D | null): "orbit_camera" | "rotate_target" {
        if (command.capture_mode === "orbit_camera" || command.capture_mode === "rotate_target") {
            return command.capture_mode;
        }
        if (target && this.isDescendantOf(target, camera)) {
            return "rotate_target";
        }
        return "orbit_camera";
    }

    private isDescendantOf(node: any, ancestor: any): boolean {
        let current = node ? node.parent : null;
        while (current) {
            if (current === ancestor) {
                return true;
            }
            current = current.parent;
        }
        return false;
    }

    private resolveCenter(command: CaptureCommand, target: Laya.Sprite3D | null): Laya.Vector3 {
        if (command.center && command.center.length >= 3) {
            return new Laya.Vector3(command.center[0], command.center[1], command.center[2]);
        }
        if (target) {
            const p = target.transform.position;
            return new Laya.Vector3(p.x, p.y, p.z);
        }
        return new Laya.Vector3(0, 0, 0);
    }

    private resolveRadius(command: CaptureCommand, target: Laya.Sprite3D | null): number {
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
        return 1.0;
    }

    private tryGetBounds(target: Laya.Sprite3D): Laya.Bounds | null {
        let result: Laya.Bounds | null = null;
        this.walk(target, (node: any) => {
            const renderer = node.meshRenderer || node.skinnedMeshRenderer || node.renderer;
            const bounds = renderer && renderer.bounds ? renderer.bounds as Laya.Bounds : null;
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

    private walk(root: any, visit: (node: any) => void): void {
        if (!root) {
            return;
        }
        visit(root);
        const count = typeof root.numChildren === "number" ? root.numChildren : 0;
        for (let i = 0; i < count; i++) {
            this.walk(root.getChildAt(i), visit);
        }
    }

    private placeCamera(camera: Laya.Camera, center: Laya.Vector3, radius: number, view: CaptureView, command: CaptureCommand): void {
        const yaw = ((view.yaw || 0) + (command.yaw_offset || 0)) * Math.PI / 180.0;
        const pitch = ((view.pitch || 0) + (command.pitch_offset || 0)) * Math.PI / 180.0;
        const distance = Math.max(command.min_distance || 1.0, radius * (command.distance_scale || 2.2));
        const cosPitch = Math.cos(pitch);
        const offset = new Laya.Vector3(
            Math.sin(yaw) * cosPitch * distance,
            Math.sin(pitch) * distance,
            Math.cos(yaw) * cosPitch * distance,
        );
        camera.transform.position = new Laya.Vector3(
            center.x - offset.x,
            center.y - offset.y,
            center.z - offset.z,
        );
        camera.transform.lookAt(center, Laya.Vector3.Up, false, true);
    }

    private rotateTargetForView(target: Laya.Sprite3D, baseEuler: Laya.Vector3, view: CaptureView, command: CaptureCommand): void {
        const yawSign = typeof command.target_yaw_sign === "number" ? command.target_yaw_sign : -1;
        const pitchSign = typeof command.target_pitch_sign === "number" ? command.target_pitch_sign : -1;
        const baseYaw = typeof command.target_base_yaw === "number" ? command.target_base_yaw : 0;
        const basePitch = typeof command.target_base_pitch === "number" ? command.target_base_pitch : 0;
        const yaw = ((view.yaw || 0) + (command.yaw_offset || 0)) * yawSign;
        const pitch = ((view.pitch || 0) + (command.pitch_offset || 0)) * pitchSign;
        target.transform.localRotationEuler = new Laya.Vector3(
            basePitch + pitch,
            baseYaw + yaw,
            baseEuler.z,
        );
    }

    private async waitFrames(count: number): Promise<void> {
        for (let i = 0; i < count; i++) {
            await new Promise<void>((resolve) => Laya.timer.frameOnce(1, this, resolve));
        }
    }

    private freezeAnimators(command: CaptureCommand, root: any): AnimatorState[] {
        if (command.freeze_animators === false) {
            return [];
        }
        const layaAny = Laya as any;
        if (!root || !layaAny.Animator) {
            return [];
        }
        const animators = this.collectComponents(root, layaAny.Animator);
        const configuredStateName = typeof command.fixed_animation_state === "string" && command.fixed_animation_state.length > 0
            ? command.fixed_animation_state
            : "";
        const layerIndex = Number.isFinite(command.fixed_animation_layer as number)
            ? Math.max(0, Math.floor(command.fixed_animation_layer as number))
            : 0;
        const normalizedTime = Number.isFinite(command.fixed_animation_time as number)
            ? Math.max(0, Math.min(1, command.fixed_animation_time as number))
            : 0;
        const states: AnimatorState[] = [];
        for (const animator of animators) {
            const stateName = configuredStateName || this.defaultAnimationStateName(animator, layerIndex);
            const state: AnimatorState = {
                source: animator,
                speed: typeof animator.speed === "number" ? animator.speed : null,
                enabled: typeof animator.enabled === "boolean" ? animator.enabled : null,
                sleep: typeof animator.sleep === "boolean" ? animator.sleep : null,
            };
            states.push(state);
            try {
                if (state.enabled !== null) {
                    animator.enabled = true;
                }
                if (state.sleep !== null) {
                    animator.sleep = false;
                }
                if (stateName && typeof animator.play === "function") {
                    // Laya skips sampling at speed 0. Keep the one-frame pose
                    // evaluation independent of the current frame duration.
                    animator.speed = 1e-6;
                    animator.play(stateName, layerIndex, normalizedTime);
                }
            } catch (error) {
                console.warn(`[MaterialFitCapture] animator freeze failed: ${error}`);
            }
        }
        return states;
    }

    private defaultAnimationStateName(animator: any, layerIndex: number): string {
        try {
            const layer = typeof animator.getControllerLayer === "function"
                ? animator.getControllerLayer(layerIndex)
                : animator._controllerLayers && animator._controllerLayers[layerIndex];
            const state = layer && (
                layer.defaultState || layer._defaultState
                || layer.states && layer.states[0]
                || layer._states && layer._states[0]
            );
            return state && typeof state.name === "string" ? state.name : "";
        } catch {
            return "";
        }
    }

    private pauseAnimators(states: AnimatorState[]): void {
        for (const state of states) {
            if (state.source && typeof state.source.speed === "number") {
                state.source.speed = 0;
            }
        }
    }

    private restoreAnimators(states: AnimatorState[]): void {
        for (const state of states) {
            const animator = state.source;
            try {
                if (state.speed !== null) {
                    animator.speed = state.speed;
                }
                if (state.sleep !== null) {
                    animator.sleep = state.sleep;
                }
                if (state.enabled !== null) {
                    animator.enabled = state.enabled;
                }
            } catch (error) {
                console.warn(`[MaterialFitCapture] animator restore failed: ${error}`);
            }
        }
    }

    private collectComponents(root: any, componentType: any): any[] {
        const components: any[] = [];
        this.walk(root, (node: any) => {
            if (!node || !componentType) {
                return;
            }
            try {
                if (typeof node.getComponents === "function") {
                    const found = node.getComponents(componentType);
                    if (found && typeof found.length === "number") {
                        for (let i = 0; i < found.length; i++) {
                            this.addUniqueComponent(found[i], components);
                        }
                    }
                } else if (typeof node.getComponent === "function") {
                    this.addUniqueComponent(node.getComponent(componentType), components);
                }
            } catch {
                // Some Laya runtimes throw for non-component classes.
            }
        });
        return components;
    }

    private addUniqueComponent(component: any, components: any[]): void {
        if (component && components.indexOf(component) < 0) {
            components.push(component);
        }
    }

    private async readPixels(renderTexture: Laya.RenderTexture, width: number, height: number): Promise<Uint8Array> {
        const pixels = new Uint8Array(width * height * 4);
        const maybePromise = renderTexture.getDataAsync(0, 0, width, height, pixels) as any;
        if (maybePromise && typeof maybePromise.then === "function") {
            await maybePromise;
            return pixels;
        }
        return renderTexture.getData(0, 0, width, height, pixels) as Uint8Array;
    }

    private resolveAlphaSource(command: CaptureCommand): "silhouette_mask" | "alpha_from_rgb" | "render_alpha" {
        if (command.alpha_source === "silhouette_mask" || command.alpha_source === "alpha_from_rgb" || command.alpha_source === "render_alpha") {
            return command.alpha_source;
        }
        if (command.transparent_background === false) {
            return "render_alpha";
        }
        return "render_alpha";
    }

    private resolveSettleFrames(command: CaptureCommand): number {
        if (typeof command.settle_frames === "number" && Number.isFinite(command.settle_frames)) {
            return Math.max(0, Math.floor(command.settle_frames));
        }
        return 2;
    }

    private resolveImageFormat(command: CaptureCommand): "png" | "raw_rgba" {
        return command.image_format === "raw_rgba" ? "raw_rgba" : "png";
    }

    private applyMaterialPatch(command: CaptureCommand, fallbackTarget: Laya.Sprite3D | null): MaterialPatchResult {
        const patch = command.material_patch;
        if (!patch || (!patch.values && !patch.defines && !patch.render_states)) {
            return { applied: false, materialCount: 0, valueCount: 0, defineCount: 0, renderStateCount: 0, enabledDefines: [], appliedRenderStates: {} };
        }
        try {
            const target = patch.target_name ? this.resolveTarget(patch.target_name) : fallbackTarget;
            if (!target) {
                return {
                    applied: false,
                    materialCount: 0,
                    valueCount: 0,
                    defineCount: 0,
                    renderStateCount: 0,
                    enabledDefines: [],
                    appliedRenderStates: {},
                    error: `material_patch target not found: ${patch.target_name || command.target_name || "(empty)"}`,
                };
            }
            const materials: Laya.Material[] = [];
            this.collectPatchMaterials(target, materials);
            let fallback: string | undefined;
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
            let defineCount = 0;
            let renderStateCount = 0;
            const definePatch = this.normalizeMaterialDefinePatch(patch.defines);
            for (const material of materials) {
                defineCount += this.applyMaterialDefines(material, definePatch.managed, definePatch.enabled);
                renderStateCount += this.applyMaterialRenderStates(material, patch.render_states || {});
                for (const key of Object.keys(patch.values || {})) {
                    this.setMaterialValue(material, key, (patch.values || {})[key]);
                    valueCount++;
                }
            }
            return {
                applied: materials.length > 0,
                materialCount: materials.length,
                valueCount,
                defineCount,
                renderStateCount,
                enabledDefines: definePatch.enabled,
                appliedRenderStates: { ...(patch.render_states || {}) },
                ...(fallback ? { fallback } : {}),
            };
        } catch (error) {
            return { applied: false, materialCount: 0, valueCount: 0, defineCount: 0, renderStateCount: 0, enabledDefines: [], appliedRenderStates: {}, error: String(error) };
        }
    }

    private normalizeMaterialDefinePatch(patch: MaterialPatch["defines"]): { managed: string[]; enabled: string[] } {
        if (!patch) {
            return { managed: [], enabled: [] };
        }
        const allowlist = new Set(["NORMALMAP", "NORMALMAP_Y_INVERT", "RIMSMOOTHNESS"]);
        const managed = Array.from(new Set((patch.managed || []).map(String)));
        const enabled = Array.from(new Set((patch.enabled || []).map(String)));
        for (const name of managed.concat(enabled)) {
            if (!allowlist.has(name)) throw new Error(`material define is not allowed: ${name}`);
        }
        for (const name of enabled) {
            if (managed.indexOf(name) < 0) throw new Error(`enabled material define is not managed: ${name}`);
        }
        if (enabled.indexOf("NORMALMAP_Y_INVERT") >= 0 && enabled.indexOf("NORMALMAP") < 0) {
            throw new Error("NORMALMAP_Y_INVERT requires NORMALMAP");
        }
        return { managed, enabled };
    }

    private applyMaterialDefines(material: Laya.Material, managed: string[], enabled: string[]): number {
        const enabledSet = new Set(enabled);
        let changed = 0;
        for (const name of managed) {
            const define = Laya.Shader3D.getDefineByName(name);
            if (!define) throw new Error(`material define is unknown to Laya: ${name}`);
            const shouldEnable = enabledSet.has(name);
            if (material.hasDefine(define) === shouldEnable) continue;
            if (shouldEnable) material.addDefine(define);
            else material.removeDefine(define);
            changed++;
        }
        return changed;
    }

    private applyMaterialRenderStates(material: Laya.Material, states: { [name: string]: number | boolean }): number {
        const properties: { [name: string]: string } = {
            renderQueue: "renderQueue",
            s_Cull: "cull",
            s_Blend: "blend",
            s_BlendSrc: "blendSrc",
            s_BlendDst: "blendDst",
            s_BlendSrcRGB: "blendSrcRGB",
            s_BlendDstRGB: "blendDstRGB",
            s_BlendSrcAlpha: "blendSrcAlpha",
            s_BlendDstAlpha: "blendDstAlpha",
            s_BlendEquation: "blendEquation",
            s_BlendEquationRGB: "blendEquationRGB",
            s_BlendEquationAlpha: "blendEquationAlpha",
            s_DepthTest: "depthTest",
            s_DepthWrite: "depthWrite",
        };
        let applied = 0;
        for (const name of Object.keys(states)) {
            const propertyName = properties[name];
            if (!propertyName) throw new Error(`material render state is not allowed: ${name}`);
            if (!(propertyName in (material as any))) throw new Error(`material render state is unavailable: ${propertyName}`);
            (material as any)[propertyName] = states[name];
            applied++;
        }
        return applied;
    }

    private collectPatchMaterials(target: any, materials: Laya.Material[]): void {
        this.walk(target, (node: any) => {
            const sources: any[] = [];
            this.collectNodeRenderSources(node, sources);
            for (const source of sources) {
                this.collectMaterials(source, materials);
            }
        });
    }

    private setMaterialValue(material: Laya.Material, name: string, value: number | number[] | boolean): void {
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

    private collectMaterials(source: any, materials: Laya.Material[]): void {
        if (!source) {
            return;
        }
        const sharedMaterials = source.sharedMaterials || source.materials || source._materials || null;
        if (sharedMaterials) {
            for (const material of sharedMaterials as Laya.Material[]) {
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

    private async renderSilhouetteMask(camera: Laya.Camera, renderTexture: Laya.RenderTexture, target: Laya.Sprite3D, width: number, height: number): Promise<Uint8Array> {
        const previousClearColor = camera.clearColor ? camera.clearColor.clone() : null;
        const maskMaterial = new Laya.UnlitMaterial();
        maskMaterial.albedoColor = new Laya.Color(1, 1, 1, 1);
        maskMaterial.albedoIntensity = 1;
        const states = this.applyMaskRenderState(target, maskMaterial);
        try {
            camera.clearColor = new Laya.Color(0, 0, 0, 1);
            await this.waitFrames(2);
            return await this.readPixels(renderTexture, width, height);
        } finally {
            this.restoreRenderState(states);
            if (previousClearColor) {
                camera.clearColor = previousClearColor;
            }
            maskMaterial.destroy();
        }
    }

    private applyMaskRenderState(target: Laya.Sprite3D, maskMaterial: Laya.Material): RendererState[] {
        const targetSources = this.collectRenderSources(target);
        const targetSet = new Set<any>(targetSources);
        const allSources = this.collectRenderSources(this.sceneRoot());
        const states: RendererState[] = [];
        for (const source of allSources) {
            const materials = this.getSourceMaterials(source);
            states.push({
                source,
                enabled: typeof source.enabled === "boolean" ? source.enabled : null,
                materials: materials ? materials.slice() : null,
            });
            if (targetSet.has(source)) {
                const count = Math.max(1, materials ? materials.length : 1);
                const maskMaterials: Laya.Material[] = [];
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

    private restoreRenderState(states: RendererState[]): void {
        for (const state of states) {
            if (state.materials) {
                this.setSourceMaterials(state.source, state.materials);
            }
            if (state.enabled !== null) {
                state.source.enabled = state.enabled;
            }
        }
    }

    private collectRenderSources(root: any): any[] {
        const sources: any[] = [];
        this.walk(root, (node: any) => {
            this.collectNodeRenderSources(node, sources);
        });
        return sources;
    }

    private collectNodeRenderSources(node: any, sources: any[]): void {
        const directSources = [node?.meshRenderer, node?.skinnedMeshRenderer, node?.renderer, node?._renderNode];
        for (const source of directSources) {
            this.addRenderSource(source, sources);
        }
        if (node && typeof node.getComponent === "function") {
            const layaAny = Laya as any;
            for (const componentType of [layaAny.MeshRenderer, layaAny.SkinnedMeshRenderer, layaAny.Renderer]) {
                if (!componentType) {
                    continue;
                }
                try {
                    this.addRenderSource(node.getComponent(componentType), sources);
                } catch {
                    // Some Laya runtimes throw for non-component classes.
                }
            }
        }
        const components = node?._components || node?._scripts || null;
        if (components && typeof components.length === "number") {
            for (let i = 0; i < components.length; i++) {
                this.addRenderSource(components[i], sources);
            }
        }
    }

    private addRenderSource(source: any, sources: any[]): void {
        if (!source || sources.indexOf(source) >= 0) {
            return;
        }
        if (this.getSourceMaterials(source) || typeof source.enabled === "boolean") {
            sources.push(source);
        }
    }

    private getSourceMaterials(source: any): Laya.Material[] | null {
        if (!source) {
            return null;
        }
        return (source.sharedMaterials || source.materials || source._materials || (source.sharedMaterial ? [source.sharedMaterial] : null)) as Laya.Material[] | null;
    }

    private setSourceMaterials(source: any, materials: Laya.Material[]): void {
        if (!source) {
            return;
        }
        if (source.sharedMaterials !== undefined) {
            source.sharedMaterials = materials;
        } else if (source.materials !== undefined) {
            source.materials = materials;
        } else if (source._materials !== undefined) {
            source._materials = materials;
        } else if (source.sharedMaterial !== undefined) {
            source.sharedMaterial = materials[0] || null;
        }
    }

    private applyMaskAlpha(pixels: Uint8Array, maskPixels: Uint8Array, mode?: "binary" | "soft", threshold?: number): void {
        const binary = mode !== "soft";
        const minValue = typeof threshold === "number" ? Math.max(0, Math.min(255, threshold)) : 1;
        const count = Math.min(pixels.length, maskPixels.length);
        for (let i = 0; i < count; i += 4) {
            const maskValue = Math.max(maskPixels[i], maskPixels[i + 1], maskPixels[i + 2]);
            pixels[i + 3] = binary ? (maskValue >= minValue ? 255 : 0) : maskValue;
        }
    }

    private zeroTransparentRgb(pixels: Uint8Array): void {
        for (let i = 0; i < pixels.length; i += 4) {
            if (pixels[i + 3] === 0) {
                pixels[i] = 0;
                pixels[i + 1] = 0;
                pixels[i + 2] = 0;
            }
        }
    }

    private liftRgbIntoAlpha(pixels: Uint8Array, threshold?: number): void {
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

    private pixelsToPngDataUrl(pixels: Uint8Array, width: number, height: number, flipY: boolean, command?: CaptureCommand): string {
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
        if (command?.preserve_artifact_alpha !== true) {
            this.applyVisualBackground(target, this.resolveVisualBackgroundColor(command));
        }
        context.putImageData(imageData, 0, 0);
        return canvas.toDataURL("image/png");
    }

    private copyPixelsForBrowserScore(pixels: Uint8Array, command?: CaptureCommand): Uint8Array {
        void command;
        return new Uint8Array(pixels);
    }

    private applyVisualBackground(pixels: Uint8Array | Uint8ClampedArray, color: [number, number, number]): void {
        for (let i = 0; i < pixels.length; i += 4) {
            if (pixels[i + 3] === 0 || (pixels[i] <= 1 && pixels[i + 1] <= 1 && pixels[i + 2] <= 1)) {
                pixels[i] = color[0];
                pixels[i + 1] = color[1];
                pixels[i + 2] = color[2];
                pixels[i + 3] = 255;
            }
        }
    }

    private resolveVisualBackgroundColor(command?: CaptureCommand): [number, number, number] {
        const value = command?.visual_background_color || command?.background_color;
        if (Array.isArray(value) && value.length >= 3) {
            return [this.clampByte(value[0]), this.clampByte(value[1]), this.clampByte(value[2])];
        }
        if (typeof value === "string") {
            const match = value.trim().match(/^#?([0-9a-f]{6})$/i);
            if (match) {
                return [
                    parseInt(match[1].slice(0, 2), 16),
                    parseInt(match[1].slice(2, 4), 16),
                    parseInt(match[1].slice(4, 6), 16),
                ];
            }
        }
        return [255, 255, 255];
    }

    private clampByte(value: any): number {
        return Math.max(0, Math.min(255, Math.round(Number(value) || 0)));
    }

    private copyPixelsForOutput(pixels: Uint8Array, width: number, height: number, flipY: boolean): Uint8Array {
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

    private shouldUseBrowserScore(command: CaptureCommand): boolean {
        const config = command.browser_score;
        return !!(config && config.enabled && Array.isArray(config.reference_images) && config.reference_images.length > 0);
    }

    private shouldEmitArtifacts(command: CaptureCommand): boolean {
        const config = command.browser_score;
        return !!(config && config.emit_artifacts === "always");
    }

    private async scoreBrowserView(command: CaptureCommand, view: CaptureView, index: number, pixels: Uint8Array, width: number, height: number): Promise<BrowserScoreView> {
        const viewId = this.viewId(view, index);
        const reference = this.findReference(command, view, index);
        if (!reference || !reference.url) {
            throw new Error(`browser_score reference image missing for ${viewId}`);
        }
        const referencePixels = await this.loadReferencePixels(reference.url, width, height);
        return this.scorePixels(viewId, pixels, referencePixels, command);
    }

    private findReference(command: CaptureCommand, view: CaptureView, index: number): BrowserScoreReference | null {
        const references = command.browser_score && Array.isArray(command.browser_score.reference_images)
            ? command.browser_score.reference_images
            : [];
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

    private async loadReferencePixels(url: string, width: number, height: number): Promise<Uint8ClampedArray> {
        const cacheKey = `${url}|${width}x${height}`;
        const cached = this._referenceCache.get(cacheKey);
        if (cached) {
            return cached;
        }
        const response = await fetch(url);
        if (!response.ok) {
            throw new Error(`reference image fetch failed: ${response.status} ${url}`);
        }
        const blob = await response.blob();
        const image = await this.decodeImage(blob);
        const canvas = document.createElement("canvas");
        canvas.width = width;
        canvas.height = height;
        const context = canvas.getContext("2d");
        if (!context) {
            throw new Error("2D canvas context is unavailable");
        }
        context.clearRect(0, 0, width, height);
        context.drawImage(image as CanvasImageSource, 0, 0, width, height);
        const pixels = context.getImageData(0, 0, width, height).data;
        if ((image as ImageBitmap).close) {
            (image as ImageBitmap).close();
        }
        this._referenceCache.set(cacheKey, pixels);
        return pixels;
    }

    private async decodeImage(blob: Blob): Promise<ImageBitmap | HTMLImageElement> {
        const createBitmap = (Laya.Browser.window as any).createImageBitmap;
        if (typeof createBitmap === "function") {
            return await createBitmap(blob);
        }
        return await new Promise<HTMLImageElement>((resolve, reject) => {
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
    }

    private scorePixels(viewId: string, candidate: Uint8Array, reference: Uint8ClampedArray, command: CaptureCommand): BrowserScoreView {
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
        const residualGridSize = Math.max(1, Math.min(32, Math.floor(this.numberOrDefault(command.browser_score && command.browser_score.residual_grid_size, 4))));
        const residualSums = new Array(residualGridSize * residualGridSize * 3).fill(0);
        const residualWeights = new Array(residualGridSize * residualGridSize).fill(0);
        const captureWidth = Math.max(1, Math.floor(this.numberOrDefault(command.width, 900)));
        const captureHeight = Math.max(1, Math.floor(this.numberOrDefault(command.height, 700)));
        const candidateUsesAlpha = this.hasForegroundAlpha(candidate);
        const referenceUsesAlpha = this.hasForegroundAlpha(reference);
        for (let i = 0; i < length; i += 4) {
            const candidateAlpha = candidate[i + 3];
            const referenceAlpha = reference[i + 3];
            const candidateForeground = this.foregroundWeightAt(candidate, i, candidateUsesAlpha);
            const referenceForeground = this.foregroundWeightAt(reference, i, referenceUsesAlpha);
            const foregroundWeight = Math.max(candidateForeground, referenceForeground);
            if (foregroundWeight <= 0) {
                continue;
            }
            const rgbDiff = (
                Math.abs(candidate[i] - reference[i])
                + Math.abs(candidate[i + 1] - reference[i + 1])
                + Math.abs(candidate[i + 2] - reference[i + 2])
            ) / (3.0 * 255.0);
            const alphaDiff = Math.abs(candidateAlpha - referenceAlpha) / 255.0;
            weightedDiff += (rgbWeight * rgbDiff + alphaWeight * alphaDiff) * foregroundWeight;
            weightSum += foregroundWeight;
            rgbMaeSum += rgbDiff;
            alphaMaeSum += alphaDiff;
            foregroundCount++;
            const pixelIndex = i / 4;
            const pixelX = pixelIndex % captureWidth;
            const pixelY = Math.floor(pixelIndex / captureWidth);
            const gridX = Math.min(residualGridSize - 1, Math.floor(pixelX * residualGridSize / captureWidth));
            const gridY = Math.min(residualGridSize - 1, Math.floor(pixelY * residualGridSize / captureHeight));
            const cellIndex = gridY * residualGridSize + gridX;
            const featureIndex = cellIndex * 3;
            residualWeights[cellIndex] += foregroundWeight;
            residualSums[featureIndex] += (candidate[i] - reference[i]) / 255.0 * foregroundWeight;
            residualSums[featureIndex + 1] += (candidate[i + 1] - reference[i + 1]) / 255.0 * foregroundWeight;
            residualSums[featureIndex + 2] += (candidate[i + 2] - reference[i + 2]) / 255.0 * foregroundWeight;
            if (candidateForeground > 0 || referenceForeground > 0) {
                unionCount++;
                if (candidateForeground > 0 && referenceForeground > 0) {
                    intersectionCount++;
                }
            }
        }
        const diffScore = weightSum > 0 ? weightedDiff / weightSum : 1.0;
        const fitScore = this.clamp01(1.0 - diffScore);
        const residualFeatures = residualSums.map((value, index) => {
            const weight = residualWeights[Math.floor(index / 3)];
            return weight > 0 ? value / weight : 0;
        });
        return {
            view_id: viewId,
            diff_score: diffScore,
            fit_score: fitScore,
            rgb_mae: foregroundCount > 0 ? rgbMaeSum / foregroundCount : 1.0,
            alpha_mae: foregroundCount > 0 ? alphaMaeSum / foregroundCount : 1.0,
            mask_iou: unionCount > 0 ? intersectionCount / unionCount : 1.0,
            foreground_weight_sum: weightSum,
            residual_grid_size: residualGridSize,
            residual_features: residualFeatures,
        };
    }

    private hasForegroundAlpha(pixels: Uint8Array | Uint8ClampedArray): boolean {
        let hasTransparent = false;
        let hasOpaque = false;
        for (let i = 3; i < pixels.length; i += 4) {
            const alpha = pixels[i];
            hasTransparent = hasTransparent || alpha < 250;
            hasOpaque = hasOpaque || alpha > 5;
            if (hasTransparent && hasOpaque) {
                return true;
            }
        }
        return false;
    }

    private foregroundWeightAt(
        pixels: Uint8Array | Uint8ClampedArray,
        index: number,
        useAlpha: boolean,
    ): number {
        const alpha = pixels[index + 3];
        if (useAlpha) {
            return alpha / 255.0;
        }
        const distanceFromWhite = Math.max(
            Math.abs(pixels[index] - 255),
            Math.abs(pixels[index + 1] - 255),
            Math.abs(pixels[index + 2] - 255),
        );
        return distanceFromWhite > 8 ? 1.0 : 0.0;
    }

    private aggregateBrowserScore(command: CaptureCommand, views: BrowserScoreView[], width: number, height: number, patchResult: MaterialPatchResult): any {
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
        const residualFeatures: number[] = [];
        for (const view of views) {
            if (Array.isArray(view.residual_features)) {
                residualFeatures.push(...view.residual_features);
            }
        }
        const metric = command.browser_score && command.browser_score.metric
            ? command.browser_score.metric
            : "browser_fast_rgba_mae_v1";
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
            structured_residual_features: {
                profile: "signed_rgb_grid_v1",
                grid_size: views.length > 0 ? (views[0].residual_grid_size || 4) : 4,
                feature_count: residualFeatures.length,
                features: residualFeatures,
            },
            material_patch: patchResult,
            summary: {
                mean_diff_score: diffScore,
                mean_fit_score: fitScore,
                optimization_fit_score: fitScore,
                optimization_fit_score_source: "browser_score",
                metric,
            },
        };
    }

    private async postBrowserScore(command: CaptureCommand, score: any): Promise<void> {
        const baseUrl = command.server_base_url || this.serverBaseUrl;
        const response = await fetch(`${baseUrl}/material-fit/capture-score`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                nonce: command.nonce,
                browser_score: score,
            }),
        });
        if (!response.ok) {
            throw new Error(`browser_score post failed: ${response.status}`);
        }
    }

    private viewId(view: CaptureView, index: number): string {
        return view.view_id || view.id || `view_${this.pad(index, 3)}`;
    }

    private numberOrDefault(value: any, fallback: number): number {
        return typeof value === "number" && Number.isFinite(value) ? value : fallback;
    }

    private clamp01(value: number): number {
        return Math.max(0, Math.min(1, value));
    }

    private async postImage(command: CaptureCommand, view: CaptureView, index: number, dataUrl: string, width: number, height: number, patchResult: MaterialPatchResult): Promise<void> {
        const url = command.post_url || `${command.server_base_url || this.serverBaseUrl}/material-fit/capture-result`;
        const viewId = view.view_id || view.id || `view_${this.pad(index, 3)}`;
        await fetch(url, {
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
                png_base64: dataUrl.replace(/^data:image\/png;base64,/, ""),
            }),
        });
    }

    private async postRawImage(command: CaptureCommand, view: CaptureView, index: number, pixels: Uint8Array, width: number, height: number, patchResult: MaterialPatchResult): Promise<void> {
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
            value_count: String(patchResult.valueCount),
        });
        const baseUrl = command.server_base_url || this.serverBaseUrl;
        await fetch(`${baseUrl}/material-fit/capture-raw-rgba?${params.toString()}`, {
            method: "POST",
            headers: { "Content-Type": "application/octet-stream" },
            body: pixels,
        });
    }

    private rawFileName(fileName: string): string {
        if (/\.rgba$/i.test(fileName)) {
            return fileName;
        }
        if (/\.png$/i.test(fileName)) {
            return fileName.replace(/\.png$/i, ".rgba");
        }
        return `${fileName}.rgba`;
    }

    private async postLog(command: CaptureCommand, kind: string, message: string): Promise<void> {
        try {
            const baseUrl = command.server_base_url || this.serverBaseUrl;
            await fetch(`${baseUrl}/material-fit/capture-log`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ kind, message, nonce: this._lastNonce, at: Date.now() }),
            });
        } catch {
            // Logging must never break capture.
        }
    }

    private pad(value: number, width: number): string {
        let text = String(value);
        while (text.length < width) {
            text = "0" + text;
        }
        return text;
    }
}
