from __future__ import annotations

import json
from pathlib import Path


def test_runtime_renderer_material_patch_preserves_vector_uniform_types() -> None:
    renderer = Path(__file__).resolve().parents[1] / "laya_capture" / "runtime_renderer.html"
    text = renderer.read_text(encoding="utf-8")

    assert "setVector4" in text
    assert "COLOR_PARAM_NAMES" in text
    assert "COLOR_PARAM_NAMES.has(name)" in text


def test_runtime_renderer_does_not_inject_experimental_ambient_lighting() -> None:
    renderer = Path(__file__).resolve().parents[1] / "laya_capture" / "runtime_renderer.html"
    text = renderer.read_text(encoding="utf-8")

    assert "ambient_sh_coefficients" not in text
    assert "ibl_material_texture" not in text
    assert "MATERIAL_FIT_AMBIENT_DIFFUSE" not in text


def test_runtime_renderer_material_patch_supports_strict_define_variants() -> None:
    renderer = Path(__file__).resolve().parents[1] / "laya_capture" / "runtime_renderer.html"
    text = renderer.read_text(encoding="utf-8")

    assert "MATERIAL_DEFINE_ALLOWLIST" in text
    assert '"NORMALMAP"' in text
    assert '"NORMALMAP_Y_INVERT"' in text
    assert '"RIMSMOOTHNESS"' in text
    assert "standalone source-material state is a valid no-op" in text
    assert "NORMALMAP_Y_INVERT requires NORMALMAP" not in text
    assert "material.addDefine(define)" in text
    assert "material.removeDefine(define)" in text
    assert "material.hasDefine(define)" in text
    assert "if (isEnabled === shouldEnable) continue;" in text
    assert "material_patch: materialPatch" in text


def test_runtime_renderer_material_patch_supports_hard_render_states() -> None:
    renderer = Path(__file__).resolve().parents[1] / "laya_capture" / "runtime_renderer.html"
    text = renderer.read_text(encoding="utf-8")

    assert "MATERIAL_RENDER_STATE_PROPERTIES" in text
    assert 's_BlendSrc: "blendSrc"' in text
    assert 's_DepthWrite: "depthWrite"' in text
    assert "applyMaterialRenderStates(material, renderStates)" in text
    assert "render_state_count: renderStateCount" in text


def test_runtime_renderer_supports_score_only_downsampled_readback() -> None:
    renderer = Path(__file__).resolve().parents[1] / "laya_capture" / "runtime_renderer.html"
    text = renderer.read_text(encoding="utf-8")

    assert "scoreReadbackDimensions" in text
    assert "browserScore.readback_width" in text
    assert "browserScore.readback_height" in text
    assert "render_width: width" in text
    assert "readback_width: scoreReadbackDimensions(command).width" in text


def test_component_browser_scores_skip_unused_full_alpha_scans() -> None:
    renderer = Path(__file__).resolve().parents[1] / "laya_capture" / "runtime_renderer.html"
    text = renderer.read_text(encoding="utf-8")

    assert "useMaterialComponents ? false : hasForegroundAlpha(candidate)" in text
    assert "useMaterialComponents ? false : hasForegroundAlpha(reference)" in text


def test_runtime_renderer_does_not_silently_fallback_when_scene_url_fails() -> None:
    renderer = Path(__file__).resolve().parents[1] / "laya_capture" / "runtime_renderer.html"
    text = renderer.read_text(encoding="utf-8")

    assert "allowFallbackScene" in text
    assert "window.__MATERIAL_FIT_READY__ = { ok: false" in text
    assert "scene load failed, falling back to cube" not in text
    assert "capture-result rejected" in text


def test_runtime_renderer_auto_frames_skinned_mesh_local_bounds() -> None:
    renderer = Path(__file__).resolve().parents[1] / "laya_capture" / "runtime_renderer.html"
    text = renderer.read_text(encoding="utf-8")

    assert "renderer.localBounds || renderer._localBounds" in text
    assert "function boundsCenterExtent(bounds)" in text
    assert "function transformLocalBounds(parts, transform)" in text
    assert "transform.worldMatrix || transform._worldMatrix" in text
    assert "command && command.camera_center" in text
    assert "profile.center" in text


def test_runtime_renderer_patches_scene_materials_before_scene_ready() -> None:
    renderer = Path(__file__).resolve().parents[1] / "laya_capture" / "runtime_renderer.html"
    text = renderer.read_text(encoding="utf-8")

    scene_patch = "ensureRuntimeMaterialCompatibility(sceneRoot);"
    prefab_patch = "ensureRuntimeMaterialCompatibility(prefab);"

    assert scene_patch in text
    assert prefab_patch in text
    assert text.index(scene_patch) < text.index("await waitFrames(4);")
    assert text.index(scene_patch) < text.index('console.log("[material-fit] loaded scene: " + sceneUrl);')


def test_runtime_renderer_disables_or_samples_animation_for_each_view() -> None:
    renderer = Path(__file__).resolve().parents[1] / "laya_capture" / "runtime_renderer.html"
    text = renderer.read_text(encoding="utf-8")

    assert "function freezeAnimators(command, root)" in text
    assert "function applyFixedAnimation(command, animator)" in text
    assert "function defaultAnimationStateName(animator, layerIndex)" in text
    assert "command.fixed_animation_time" in text
    assert "const FIXED_ANIMATION_SAMPLE_SPEED = 1e-6;" in text
    assert "animator.speed = FIXED_ANIMATION_SAMPLE_SPEED;" in text
    assert "animator.speed = 1;" not in text
    disabled_branch = text[
        text.index('if (animationMode === "disabled")') :
        text.index("return;", text.index('if (animationMode === "disabled")'))
    ]
    assert "animator.speed = 0;" in disabled_branch
    assert "animator.sleep = true" in disabled_branch
    assert "animator.enabled = false" in disabled_branch
    assert "animator.play(" not in disabled_branch
    scene_open = text.index("const scene = await Laya.Scene.open(sceneUrl, false);")
    startup_disable = text.index("prepareStartupAnimators(sceneRoot);", scene_open)
    startup_settle = text.index("await waitFrames(4);", scene_open)
    assert scene_open < startup_disable < startup_settle
    assert "resolveAnimationFreezeSettleFrames(command)" in text
    assert "const frozenAnimators = freezeAnimators(command, runtime.target || runtime.scene);" in text

    render_body = text[text.index("async function renderAndScore(command)") :]
    assert render_body.index("drawView(command, view);") < render_body.index("stageCanvas(command);")
    assert render_body.index("applyFixedAnimations(command, frozenAnimators);") < render_body.index("stageCanvas(command);")


def test_laya_capture_uses_frame_time_independent_animation_sampling() -> None:
    capture = (
        Path(__file__).resolve().parents[1]
        / "laya_capture"
        / "laya"
        / "MaterialFitCapture.ts"
    )
    text = capture.read_text(encoding="utf-8")

    assert "animator.speed = 1e-6;" in text
    assert "animator.speed = 1;" not in text


def test_runtime_renderer_preserves_explicit_zero_settle_frames() -> None:
    renderer = Path(__file__).resolve().parents[1] / "laya_capture" / "runtime_renderer.html"
    text = renderer.read_text(encoding="utf-8")

    assert "Math.max(0, Math.floor(Number(count)))" in text
    assert "resolveSettleFrames(command)" in text
    assert "command.settle_frames || 2" not in text


def test_runtime_renderer_skips_iteration_pngs_when_browser_score_is_enabled() -> None:
    renderer = Path(__file__).resolve().parents[1] / "laya_capture" / "runtime_renderer.html"
    text = renderer.read_text(encoding="utf-8")

    assert "function shouldEmitCaptureArtifacts(command)" in text
    assert 'browserScore.emit_artifacts === "always"' in text
    assert "if (shouldEmitCaptureArtifacts(command))" in text


def test_runtime_renderer_white_artifacts_use_the_scored_pixel_buffer() -> None:
    renderer = Path(__file__).resolve().parents[1] / "laya_capture" / "runtime_renderer.html"
    text = renderer.read_text(encoding="utf-8")

    assert "canvasFromPixels(scoreCandidatePixels, staged.width, staged.height)" in text
    assert "canvasOnBackground(staged.canvas, background)" not in text


def test_runtime_renderer_supports_frozen_stage2_candidate_registration() -> None:
    renderer = Path(__file__).resolve().parents[1] / "laya_capture" / "runtime_renderer.html"
    text = renderer.read_text(encoding="utf-8")
    render_body = text[text.index("async function renderAndScore(command)") :]

    assert "function candidateRegistrationForView" in text
    assert 'registration.mode !== "frozen_per_view_similarity"' in text
    assert "browserScore.candidate_registration" in text
    assert "transform.dx, 0) * pixelWidth / sourceWidth" in text
    assert "transform.dy, 0) * pixelHeight / sourceHeight" in text
    assert "function registerCandidatePixelsBicubic" in text
    assert 'registration.interpolation === "bicubic"' in text
    assert "function registerCandidatePixels" in text
    assert 'context.imageSmoothingQuality = "high"' in text
    assert "const registeredCandidate = registerCandidatePixels(" in render_body
    assert "const scoreCandidatePixels = registeredCandidate.pixels;" in render_body
    assert "candidate_registration: registeredCandidate.registration" in render_body


def test_runtime_renderer_background_composite_preserves_opaque_black_pixels() -> None:
    renderer = Path(__file__).resolve().parents[1] / "laya_capture" / "runtime_renderer.html"
    text = renderer.read_text(encoding="utf-8")
    function_body = text[
        text.index("function canvasOnBackground") : text.index("async function canvasToPngBase64")
    ]

    assert "ctx.fillStyle" in function_body
    assert "ctx.fillRect(0, 0, out.width, out.height)" in function_body
    assert "ctx.drawImage(canvas, 0, 0)" in function_body
    assert "data[i] <= 1" not in function_body


def test_runtime_renderer_caches_references_and_scores_one_pixel_buffer() -> None:
    renderer = Path(__file__).resolve().parents[1] / "laya_capture" / "runtime_renderer.html"
    text = renderer.read_text(encoding="utf-8")
    render_body = text[text.index("async function renderAndScore(command)") :]

    assert "const referencePixelCache = new Map();" in text
    assert "const referenceV2FeatureCache = new WeakMap();" in text
    assert "const referenceV4FeatureCache = new WeakMap();" in text
    assert "referencePixelCache.get(cacheKey)" in text
    assert "referencePixelCache.set(cacheKey, pixels)" in text
    assert "function prepareMaterialReference(reference)" in text
    assert "const preparedReference = useMaterialComponents ? prepareMaterialReference(reference) : null;" in text
    assert "let scoreReadbackCanvas = null;" in text
    assert "scoreReadbackContext.clearRect(0, 0, dimensions.width, dimensions.height);" in text
    assert "? scorePixels(" in render_body
    assert "const scoreCandidatePixels = registeredCandidate.pixels;" in render_body
    assert "canvasPixels(whiteArtifactCanvas)" not in render_body
    assert "canvasPixels(visualCanvas)" not in render_body


def test_runtime_renderer_retries_transient_perceptual_score_posts() -> None:
    renderer = Path(__file__).resolve().parents[1] / "laya_capture" / "runtime_renderer.html"
    text = renderer.read_text(encoding="utf-8")
    function_body = text[
        text.index("async function postPerceptualScore") :
        text.index("function shouldEmitCaptureArtifacts")
    ]

    assert "for (let attempt = 0; attempt < 3; attempt += 1)" in function_body
    assert "response.status < 500" in function_body
    assert "50 * (attempt + 1)" in function_body


def test_runtime_renderer_routes_perceptual_metrics_to_server_scorer() -> None:
    renderer = Path(__file__).resolve().parents[1] / "laya_capture" / "runtime_renderer.html"
    text = renderer.read_text(encoding="utf-8")

    assert text.count('metric === "foreground_dists_v1"') == 2
    assert text.count('metric === "foreground_dists_material_v1"') == 2
    assert "foreground_aligned_pyramid_dists_v1" not in text


def test_runtime_renderer_dists_skips_legacy_browser_pixel_score() -> None:
    renderer = Path(__file__).resolve().parents[1] / "laya_capture" / "runtime_renderer.html"
    text = renderer.read_text(encoding="utf-8")
    render_body = text[text.index("async function renderAndScore(command)") :]

    assert "const referencePixels = usePerceptualScore" in render_body
    assert "let score = !usePerceptualScore && referencePixels" in render_body
    assert "score = perceptual;" in render_body
    assert "residual_fit_score" not in render_body
    assert "signed_dists_feature_means_and_std_v1" in render_body


def test_runtime_renderer_retries_transient_json_posts() -> None:
    renderer = Path(__file__).resolve().parents[1] / "laya_capture" / "runtime_renderer.html"
    text = renderer.read_text(encoding="utf-8")
    function_body = text[
        text.index("async function postJsonWithRetry") :
        text.index("function shouldEmitCaptureArtifacts")
    ]

    assert "for (let attempt = 0; attempt < 3; attempt += 1)" in function_body
    assert "response.status < 500" in function_body
    assert "await response.text()" in function_body
    poll_body = text[text.index("async function pollOnce") :]
    assert '"capture-score"' in poll_body
    assert '"capture-log"' in poll_body
    assert 'message.includes("stale capture nonce")' in poll_body
    assert "{ nonce: command.nonce, level: \"error\", message }" in poll_body


def test_runtime_renderer_serializes_polling_and_consumes_post_responses() -> None:
    renderer = Path(__file__).resolve().parents[1] / "laya_capture" / "runtime_renderer.html"
    text = renderer.read_text(encoding="utf-8")
    start = text.index("async function pollOnce")
    function_body = text[start : text.index("window.__MATERIAL_FIT_READY__", start)]

    assert function_body.index("busy = true") < function_body.index("capture-command")
    assert "catch (_)" in function_body
    assert "await postJsonWithRetry(" in function_body
    assert '"capture-score"' in function_body
    assert '"capture-log"' in function_body


def test_runtime_renderer_browser_score_uses_foreground_weighted_rgba_objective() -> None:
    renderer = Path(__file__).resolve().parents[1] / "laya_capture" / "runtime_renderer.html"
    text = renderer.read_text(encoding="utf-8")
    score_body = text[text.index("function scorePixels(candidate, reference") :]
    render_body = text[text.index("async function renderAndScore(command)") :]

    assert "rgb_weight" in score_body
    assert "alpha_weight" in score_body
    assert "function foregroundWeightAt(pixels, index, useAlpha)" in text
    assert "function hasForegroundAlpha(pixels)" in text
    assert "cachedSilhouetteAlpha(command, view)" in text
    assert "distanceFromWhite > 8" in text
    assert "foregroundWeight" in score_body
    assert "Math.max(candidateForeground, referenceForeground)" in score_body
    assert "Math.max(candidateAlpha, referenceAlpha)" not in score_body
    assert "foreground_weight_sum" in score_body
    assert "mask_iou" in score_body
    assert "material_components" in score_body
    assert "foreground_overlap_coefficient" in score_body
    assert "0.70 * meanFitScore + 0.20 * p10Score + 0.10 * orderedScores[0]" in render_body
    assert "const p10Score = linearQuantile(orderedScores, 0.10);" in render_body
    assert render_body.index("const background = visualBackgroundColor(command)") < render_body.index("? scorePixels(")
    assert "cross_engine_components_v2_raw_rgba_white_composite_v2" in render_body
    assert "cross_engine_components_v3_raw_rgba_white_composite_v3" in render_body
    assert "cross_engine_components_v4_python_parity_v1" in render_body
    assert "cross_engine_components_v5_strict_canvas_core_v1" in render_body
    assert "cross_engine_components_v6_frozen_confidence_v1" in render_body
    assert "cross_engine_components_v7_frozen_confidence_blend_v1" in render_body
    assert "cross_engine_components_v8_texture_detail_v1" in render_body
    assert "cross_engine_components_v9_spatial_luminance_v1" in render_body
    assert "cross_engine_components_v10_spatial_hue_v1" in render_body
    assert "cross_engine_components_v11_dark_chroma_v1" in render_body
    assert "cross_engine_components_v12_chromaticity_v1" in render_body
    assert "cross_engine_components_v13_radiance_v1" in render_body
    assert "cross_engine_components_v14_highlight_energy_v1" in render_body
    assert "cross_engine_components_v15_balanced_v1" in render_body
    assert "cross_engine_components_v16_conservative_v1" in render_body
    assert 'metric === "cross_engine_foreground_components_v3"' in score_body
    assert 'metric === "cross_engine_foreground_components_v4"' in score_body
    assert 'metric === "cross_engine_foreground_components_v5_strict_core"' in score_body
    assert 'metric === "cross_engine_foreground_components_v6_frozen_confidence"' in score_body
    assert 'metric === "cross_engine_foreground_components_v7_frozen_confidence_blend"' in score_body
    assert 'metric === "cross_engine_foreground_components_v8_texture_detail"' in score_body
    assert 'metric === "cross_engine_foreground_components_v9_spatial_luminance"' in score_body
    assert 'metric === "cross_engine_foreground_components_v10_spatial_hue"' in score_body
    assert 'metric === "cross_engine_foreground_components_v11_dark_chroma"' in score_body
    assert 'metric === "cross_engine_foreground_components_v12_chromaticity"' in score_body
    assert 'metric === "cross_engine_foreground_components_v13_radiance"' in score_body
    assert 'metric === "cross_engine_foreground_components_v14_highlight_energy"' in score_body
    assert 'metric === "cross_engine_foreground_components_v15_balanced"' in score_body
    assert 'metric === "cross_engine_foreground_components_v16_conservative"' in score_body
    assert "componentMean - Math.sqrt(componentVariance)" in text
    assert "materialComponents.chroma_hue" in score_body
    assert "function scoreMaterialComponentsV4" in text
    assert "if (useMaterialComponentsV4) {" in score_body
    assert "const frozenScore = scoreMaterialComponentsV4(" in score_body
    assert "const residualSums = new Float64Array" in text
    assert "textureDetailResiduals" in text
    assert "function exactTextureDetailDescriptor" in text
    assert "materialComponents.texture_detail_distribution" in text
    assert "function exactSpatialLuminanceDescriptor" in text
    assert "materialComponents.spatial_luminance_layout" in text
    assert "function exactSpatialHueMassDescriptor" in text
    assert "materialComponents.spatial_hue_mass" in text
    assert "function exactSpatialDarkChromaDescriptor" in text
    assert "materialComponents.spatial_dark_chroma" in text
    assert "function exactSpatialChromaticityDescriptor" in text
    assert "materialComponents.spatial_chromaticity" in text
    assert "function exactSpatialRadianceDescriptor" in text
    assert "materialComponents.spatial_radiance" in text
    assert "function exactSpatialHighlightDescriptor" in text
    assert "materialComponents.spatial_highlight_energy" in text
    assert "function exactColorDistributionError" in text
    assert "function exactMultiscaleLuminanceError" in text
    assert "function exactDetailError" in text
    assert "function exactHighlightError" in text
    assert (
        "const minimumForegroundPixels = Math.min("
        in text
    )
    assert "const minimumCoreBasisPixels = frozenConfidencePixels" in text
    assert "? frozenConfidenceCount" in text
    assert "? pixelCount" in text
    assert ": minimumForegroundPixels" in text
    assert "Math.floor(0.02 * minimumCoreBasisPixels)" in text
    assert "candidateConfidenceCoverage < minimumFrozenCoverage" in text
    assert "minimum_trusted_core_pixels: minimumCorePixels" in text
    assert '"frozen_confidence"' in text
    assert "minimum_core_basis_pixels: minimumCoreBasisPixels" in text
    assert "minimum_foreground_pixels: minimumForegroundPixels" in text
    assert "fit_score: 0" in text
    assert "geometry_valid: false" in text
    assert "function loadConfidenceMaskPixels" in text
    assert "function prepareMaskedExactMaterialPixels" in text
    assert "confidence_mask_url" in text
    assert "const frozenWeight = 0.75;" in text
    assert "const fullWeight = 0.25;" in text
    assert "return Math.round(channel * weight + 255 * (1 - weight));" in text


def test_runtime_renderer_browser_score_emits_signed_grid_residuals() -> None:
    renderer = Path(__file__).resolve().parents[1] / "laya_capture" / "runtime_renderer.html"
    text = renderer.read_text(encoding="utf-8")
    score_body = text[text.index("function scorePixels(candidate, reference") :]

    assert "residual_grid_size" in score_body
    assert "residual_sketch_size" in score_body
    assert "signed_rgb_grid_sketch_v2" in text
    assert "signed_rgb_grid_sketch_chroma_v3" in text
    assert "residual_features: residualFeatures.concat(residualSketchFeatures, chromaOpponentResiduals)" in score_body
    assert "structured_residual_features" in score_body
    assert ': "signed_rgb_grid_sketch_chroma_v3")' in score_body
    assert '"signed_rgb_grid_sketch_chroma_v4_python_parity"' in score_body
    assert ': "signed_rgb_grid_sketch_v2"' in score_body


def test_laya_ide_capture_browser_score_uses_visual_white_background_pixels() -> None:
    capture = Path(__file__).resolve().parents[1] / "laya_capture" / "laya" / "MaterialFitCapture.ts"
    text = capture.read_text(encoding="utf-8")
    score_body = text[text.index("private scorePixels(") :]

    assert "copyPixelsForBrowserScore(outputPixels, command)" in text
    assert "private foregroundWeightAt(" in text
    assert "distanceFromWhite > 8" in text
    assert "Math.max(candidateForeground, referenceForeground)" in score_body
    assert "Math.max(candidateAlpha, referenceAlpha)" not in score_body
    assert "residual_grid_size" in score_body
    assert "structured_residual_features" in score_body


def test_runtime_renderer_node_exits_on_pageerror() -> None:
    runner = Path(__file__).resolve().parents[1] / "laya_capture" / "run_runtime_renderer.js"
    text = runner.read_text(encoding="utf-8")

    assert "exitOnFatalPageError" in text
    assert "page.on('pageerror'" in text
    assert "process.exit(1);" in text


def test_runtime_renderer_uses_asset_profile_without_hardcoded_model_contract() -> None:
    renderer = Path(__file__).resolve().parents[1] / "laya_capture" / "runtime_renderer.html"
    runner = Path(__file__).resolve().parents[1] / "laya_capture" / "run_runtime_renderer.js"
    renderer_text = renderer.read_text(encoding="utf-8")
    runner_text = runner.read_text(encoding="utf-8")

    assert 'params.get("assetProfile")' in renderer_text
    assert 'runtimeProfile.target_name || "model"' in renderer_text
    assert "runtime.materialTarget || runtime.target" in renderer_text
    assert "commandWithProfileDefaults" in renderer_text
    assert "preserve_target_transform" in renderer_text
    assert "args.assetProfile" in runner_text
    assert "'/project/'" in runner_text
    assert "'/environment/'" in runner_text
    assert "preferredImportedTexture" in runner_text
    assert "Number(metadata && metadata.shape) === 1" in runner_text
    assert "sourceExtensionByUuid[uuid] === '.exr'" in runner_text


def test_profile_driven_runtime_disables_animation_before_startup_settle() -> None:
    renderer = Path(__file__).resolve().parents[1] / "laya_capture" / "runtime_renderer.html"
    text = renderer.read_text(encoding="utf-8")

    assert 'configuredAnimationMode(null) !== "disabled"' in text
    assert "prepareStartupAnimators(prefab);" in text
    assert 'if (animationMode === "disabled")' in text
    assert 'runtimeProfile.animation_mode || "disabled"' in text
    assert 'startup animators disabled count=' in text
    assert 'globalThis.__MATERIAL_FIT_HEADLESS_RUNTIME__ = true;' in text
    assert text.index("prepareStartupAnimators(prefab);") < text.index("await waitFrames(runtimeProfile.startup_settle_frames")


def test_packaged_capture_bundles_skip_headless_pose_presets() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    bundles = [
        repo_root / "examples/fish_laya_project/bin/js/bundles/bundle.js",
        repo_root / "examples/fish_laya_project/bin/js/bundles/bundle.scene.js",
        repo_root / "examples/crocodile_laya_project/bin/js/bundles/bundle.js",
    ]

    for bundle in bundles:
        text = bundle.read_text(encoding="utf-8")
        assert "__MATERIAL_FIT_HEADLESS_RUNTIME__ === true" in text
        assert 'animation_mode: "disabled"' in text


def test_maintained_profiles_do_not_sample_asset_specific_animation_poses() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    profile_paths = [
        repo_root / "material_fit/assets/profiles/crocodile_1503.json",
        repo_root / "material_fit/assets/profiles/turtle_1506.json",
    ]

    for profile_path in profile_paths:
        profile = json.loads(profile_path.read_text(encoding="utf-8-sig"))
        defaults = profile["capture_defaults"]
        assert defaults["animation_mode"] == "disabled"
        assert "fixed_animation_state" not in defaults
        assert "fixed_animation_time" not in defaults
