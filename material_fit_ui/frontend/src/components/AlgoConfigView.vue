<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { fetchProject, patchProject } from '../api';
import type { AlgorithmConfig, OptimizerKind, ProjectDetail } from '../types';

const props = defineProps<{ projectId: string }>();
const emit = defineEmits<{ (e: 'changed'): void }>();

const project = ref<ProjectDetail | null>(null);
const error = ref<string | null>(null);
const saving = ref(false);
const ok = ref(false);

function defaultConfig(): AlgorithmConfig {
  return {
    max_iterations: 300,
    target_score: 0.9,
    optimizer_preset: 'manual',
    apply_lmat: true,
    capture_screen_after_apply: false,
    use_laya_editor_capture: true,
    laya_editor_capture: {
      reload_scene_after_reimport: true,
      refresh_after_reimport_delay_ms: 800,
      timeout_s: 90,
      capture_mode: 'rotate_target',
    },
    rerender_wait_ms: 900,
    use_capture_contract: false,
    dry_run: false,
    fit_score_mode: 'research',
    auto_adjust_mode: 'fresh_fit',
    optimizer: 'adaptive_response_search',
    analysis_performance: {
      multiview_workers: 'auto',
      evaluation_batch_size: 1,
      evaluation_workers: 1,
      evaluation_parallel_safe: false,
      full_rerank_top_k: 0,
      best_full_validation: false,
      target_full_validation: false,
      snapshot_interval: 50,
      research_metrics_profile: 'tiered',
      keep_last_n_artifacts: 5,
      always_keep_best_artifact: true,
      always_keep_first_artifact: true,
    },
    cma_es: {
      mode: 'warm',
      warm_start_iters: 12,
      warm_start_source: 'elite_archive_first',
      population_size: null,
      sigma: null,
      seed: null,
      hint_bias_mix_ratio: 0.30,
      stagnation_patience: 0,
      stagnation_min_delta: 0.001,
      stagnation_min_evaluations: 0,
      stagnation_max_restarts: 0,
      stagnation_stop_after_restarts: true,
      restart_center_mode: 'best',
      restart_population_multiplier: 1.0,
      restart_population_schedule: 'ipop',
      restart_max_population_size: null,
      initial_design_samples: 0,
      initial_design_method: 'latin_hypercube',
      initial_design_include_current: true,
    },
  };
}

const form = reactive<AlgorithmConfig>(defaultConfig());

const isCma = computed(() => form.optimizer === 'cma_cold' || form.optimizer === 'cma_warm' || form.optimizer === 'subspace_cma_es');

function applyOptimizerPreset(): void {
  if (form.optimizer_preset !== 'cma_mature_default') return;
  form.optimizer = 'cma_warm';
  Object.assign(form.cma_es, {
    warm_start_iters: 12,
    warm_start_source: 'elite_archive_first',
    hint_bias_mix_ratio: 0.30,
    stagnation_patience: 64,
    stagnation_min_delta: 0.001,
    stagnation_min_evaluations: 64,
    stagnation_max_restarts: 8,
    stagnation_stop_after_restarts: false,
    restart_center_mode: 'alternate',
    restart_population_multiplier: 2.0,
    restart_population_schedule: 'bipop',
    restart_max_population_size: null,
    initial_design_samples: 16,
    initial_design_method: 'latin_hypercube',
    initial_design_include_current: true,
  });
  Object.assign(form.analysis_performance, {
    evaluation_batch_size: 8,
    evaluation_workers: 4,
    evaluation_parallel_safe: false,
    full_rerank_top_k: 1,
    best_full_validation: true,
    target_full_validation: true,
    research_metrics_profile: 'tiered',
  });
}

const optimizerHelp: Record<OptimizerKind, string> = {
  heuristic: '旧的固定 stage 反馈控制器。可解释但没有组级回滚，适合作为对照基线。',
  cma_cold: '黑盒 CMA-ES，从初始 .lmat 开始无任何 prior。适合作为 cma_warm 的对照基线；高维下 200 轮以内可能比 random 还差。',
  cma_warm: 'Warm-Started CMA-ES (Nomura et al., AAAI 2021)。把已有迭代的 (params, fit_score) 当 prior 初始化协方差，合成实验中比 cma_cold 快 2~3×。需要 ≥2 轮历史，否则自动降级到 cma_cold。',
  semantic_group: '当前 response-driven 调度器。用 ResponseMap 记录参数-指标响应，并通过预算审计避免单参塌缩。',
  adaptive_response_search: '新主力算法。所有候选从 global best 出发，用真实响应证据排序参数，并只把预算集中给有效参数/参数对。',
  semantic_group_legacy_081: '旧高分复现基线。保留 probe_group / pattern_search / cross_group_combo，不接入 ResponseMap，适合复现 0.8 附近实验。',
  subspace_cma_es: '效果优先的昂贵黑盒路线。在当前 active 子空间内运行 CMA-ES；每轮仍需真实渲染，建议 500+ 轮做对照。',
};

async function load(): Promise<void> {
  if (!props.projectId) return;
  try {
    const data = await fetchProject(props.projectId);
    project.value = data;
    const merged: AlgorithmConfig = {
      ...defaultConfig(),
      ...data.algorithm_config,
      capture_screen_after_apply: false,
      use_laya_editor_capture: true,
      cma_es: { ...defaultConfig().cma_es, ...(data.algorithm_config?.cma_es ?? {}) },
      analysis_performance: {
        ...defaultConfig().analysis_performance,
        ...(data.algorithm_config?.analysis_performance ?? {}),
      },
      laya_editor_capture: {
        ...defaultConfig().laya_editor_capture,
        ...(data.algorithm_config?.laya_editor_capture ?? {}),
      },
    };
    Object.assign(form, merged);
    error.value = null;
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err);
  }
}

watch(() => props.projectId, () => { void load(); });
onMounted(() => { void load(); });

async function save(): Promise<void> {
  if (!project.value) return;
  saving.value = true;
  ok.value = false;
  try {
    const snapshotInterval = Number(form.analysis_performance.snapshot_interval ?? 50);
    const payload: AlgorithmConfig = {
      ...form,
      optimizer_preset: form.optimizer_preset ?? 'manual',
      capture_screen_after_apply: false,
      use_laya_editor_capture: true,
      analysis_performance: {
        multiview_workers: form.analysis_performance.multiview_workers,
        evaluation_batch_size: Number(form.analysis_performance.evaluation_batch_size ?? 1),
        evaluation_workers: Number(form.analysis_performance.evaluation_workers ?? 1),
        evaluation_parallel_safe: Boolean(form.analysis_performance.evaluation_parallel_safe),
        full_rerank_top_k: Number(form.analysis_performance.full_rerank_top_k ?? 0),
        best_full_validation: Boolean(form.analysis_performance.best_full_validation),
        target_full_validation: Boolean(form.analysis_performance.target_full_validation),
        snapshot_interval: snapshotInterval,
        research_metrics_profile: form.analysis_performance.research_metrics_profile ?? 'tiered',
        keep_last_n_artifacts: form.analysis_performance.keep_last_n_artifacts,
        always_keep_best_artifact: form.analysis_performance.always_keep_best_artifact,
        always_keep_first_artifact: form.analysis_performance.always_keep_first_artifact,
      },
      cma_es: { ...form.cma_es, mode: form.optimizer === 'cma_cold' ? 'cold' : 'warm' },
    };
    const result = await patchProject(project.value.id, {
      algorithm_config: payload,
    });
    project.value = result;
    const merged: AlgorithmConfig = {
      ...defaultConfig(),
      ...result.algorithm_config,
      capture_screen_after_apply: false,
      use_laya_editor_capture: true,
      cma_es: { ...defaultConfig().cma_es, ...(result.algorithm_config?.cma_es ?? {}) },
      analysis_performance: {
        ...defaultConfig().analysis_performance,
        ...(result.algorithm_config?.analysis_performance ?? {}),
      },
      laya_editor_capture: {
        ...defaultConfig().laya_editor_capture,
        ...(result.algorithm_config?.laya_editor_capture ?? {}),
      },
    };
    Object.assign(form, merged);
    ok.value = true;
    setTimeout(() => { ok.value = false; }, 1500);
    emit('changed');
    error.value = null;
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err);
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <div class="algo-config">
    <header style="display: flex; align-items: baseline; gap: 12px;">
      <h2 class="section-title" style="margin: 0;">算法配置</h2>
      <span class="muted small">控制 fit_material.py 的核心 CLI 行为</span>
    </header>

    <div v-if="error" class="error-banner">{{ error }}</div>

    <section class="section" v-if="project">
      <table class="cfg-table">
        <tbody>
          <tr>
            <td>
              <label for="cfg-optimizer-preset">optimizer_preset</label>
              <p class="muted small">manual = 手动调参；cma_mature_default = 启用稳健长跑 CMA 组合。</p>
            </td>
            <td>
              <select id="cfg-optimizer-preset" v-model="form.optimizer_preset" @change="applyOptimizerPreset">
                <option value="manual">manual</option>
                <option value="cma_mature_default">cma_mature_default（稳健 CMA 长跑）</option>
              </select>
            </td>
          </tr>
          <tr>
            <td>
              <label for="cfg-optimizer">optimizer</label>
              <p class="muted small">{{ optimizerHelp[form.optimizer] }}</p>
            </td>
            <td>
              <select id="cfg-optimizer" v-model="form.optimizer">
                <option value="adaptive_response_search">adaptive_response_search（新主力 best-centered 响应搜索）</option>
                <option value="semantic_group">semantic_group（当前 response scheduler）</option>
                <option value="semantic_group_legacy_081">semantic_group_legacy_081（旧 0.8 基线复现）</option>
                <option value="subspace_cma_es">subspace_cma_es（昂贵子空间 CMA-ES）</option>
                <option value="heuristic">heuristic（旧 stage 基线）</option>
                <option value="cma_warm">cma_warm（Warm-Started CMA-ES）</option>
                <option value="cma_cold">cma_cold（vanilla CMA-ES）</option>
              </select>
            </td>
          </tr>
          <tr v-if="isCma" class="cma-block">
            <td colspan="2">
              <h3 class="sub">CMA-ES 调参（cma_* / subspace_cma_es 生效）</h3>
              <table class="cfg-subtable">
                <tbody>
                  <tr>
                    <td>
                      <label for="cma-warm-iters">warm_start_iters</label>
                      <p class="muted small">cma_warm 时，最多用多少轮历史 (params, fit_score) 作为 prior。&lt;2 自动降级为 cold。</p>
                    </td>
                    <td>
                      <input id="cma-warm-iters" type="number" min="0" max="200" step="1"
                        v-model.number="form.cma_es.warm_start_iters" :disabled="form.optimizer !== 'cma_warm'" />
                    </td>
                  </tr>
                  <tr>
                    <td>
                      <label for="cma-warm-source">warm_start_source</label>
                      <p class="muted small">prior 来源。elite_archive_first 优先复用 top-K 高分候选；iteration_history 只用旧 iter 目录。</p>
                    </td>
                    <td>
                      <select id="cma-warm-source" v-model="form.cma_es.warm_start_source"
                        :disabled="form.optimizer !== 'cma_warm'">
                        <option value="elite_archive_first">elite_archive_first</option>
                        <option value="elite_archive_only">elite_archive_only</option>
                        <option value="iteration_history">iteration_history</option>
                        <option value="none">none</option>
                      </select>
                    </td>
                  </tr>
                  <tr>
                    <td>
                      <label for="cma-pop">population_size</label>
                      <p class="muted small">每代采样数。空 = 库默认（4 + 3·ln(dim)，d≈30 时约 14）。真实 Laya 跑 ≤8 较合算。</p>
                    </td>
                    <td>
                      <input id="cma-pop" type="number" min="1" max="64" step="1" placeholder="auto"
                        v-model.number="form.cma_es.population_size" />
                    </td>
                  </tr>
                  <tr>
                    <td>
                      <label for="cma-sigma">sigma（normalized）</label>
                      <p class="muted small">初始步长，[0,1] 归一化空间下。空 = 0.30。0.1 太保守，0.5 太发散。</p>
                    </td>
                    <td>
                      <input id="cma-sigma" type="number" min="0.01" max="1" step="0.05" placeholder="0.30"
                        v-model.number="form.cma_es.sigma" />
                    </td>
                  </tr>
                  <tr>
                    <td>
                      <label for="cma-seed">seed</label>
                      <p class="muted small">复现实验时设固定种子；空 = 不固定。</p>
                    </td>
                    <td>
                      <input id="cma-seed" type="number" min="0" max="2147483647" step="1" placeholder="random"
                        v-model.number="form.cma_es.seed" />
                    </td>
                  </tr>
                  <tr>
                    <td>
                      <label for="cma-hint-bias">hint_bias_mix_ratio <span class="badge">E-010</span></label>
                      <p class="muted small">
                        把 image_analysis 给出的"暗部应增/减、emission 应增/减"等 channel 级建议混入 CMA-ES 每轮提议的力度。
                        <strong>0</strong> = 完全不偏置（旧版行为）；
                        <strong>0.30</strong> 推荐起步；
                        <strong>0.50+</strong> 偏置主导，适合快速 sanity check 不适合精细收敛。
                      </p>
                    </td>
                    <td>
                      <input id="cma-hint-bias" type="number" min="0" max="1" step="0.05" placeholder="0.30"
                        v-model.number="form.cma_es.hint_bias_mix_ratio" />
                    </td>
                  </tr>
                  <tr>
                    <td>
                      <label for="cma-stagnation-patience">stagnation_patience</label>
                      <p class="muted small">CMA-ES 专属平台期停止窗口。0 = 关闭；建议长跑时设为 2~4 个 population。</p>
                    </td>
                    <td>
                      <input id="cma-stagnation-patience" type="number" min="0" max="10000" step="1" placeholder="0"
                        v-model.number="form.cma_es.stagnation_patience" />
                    </td>
                  </tr>
                  <tr>
                    <td>
                      <label for="cma-stagnation-delta">stagnation_min_delta</label>
                      <p class="muted small">最近窗口内 best fit_score 至少提升多少才算继续有效探索。0.001 适合 0~1 分数。</p>
                    </td>
                    <td>
                      <input id="cma-stagnation-delta" type="number" min="0" max="1" step="0.001" placeholder="0.001"
                        v-model.number="form.cma_es.stagnation_min_delta" />
                    </td>
                  </tr>
                  <tr>
                    <td>
                      <label for="cma-stagnation-min-evals">stagnation_min_evaluations</label>
                      <p class="muted small">达到多少次真实评估后才允许平台期停止。0 = 不设冷启动保护。</p>
                    </td>
                    <td>
                      <input id="cma-stagnation-min-evals" type="number" min="0" max="100000" step="1" placeholder="0"
                        v-model.number="form.cma_es.stagnation_min_evaluations" />
                    </td>
                  </tr>
                  <tr>
                    <td>
                      <label for="cma-stagnation-restarts">stagnation_max_restarts</label>
                      <p class="muted small">平台期后最多重启几次 CMA-ES 分布。0 = 不重启，直接按 cmaes_stagnation 停止。</p>
                    </td>
                    <td>
                      <input id="cma-stagnation-restarts" type="number" min="0" max="100" step="1" placeholder="0"
                        v-model.number="form.cma_es.stagnation_max_restarts" />
                    </td>
                  </tr>
                  <tr>
                    <td>
                      <label><input type="checkbox" v-model="form.cma_es.stagnation_stop_after_restarts" /> stagnation_stop_after_restarts</label>
                      <p class="muted small">打开时重启预算耗尽后早停；关闭时继续跑到目标分数或最大轮数，适合 1w 轮长跑。</p>
                    </td>
                    <td class="muted small mono">{{ form.cma_es.stagnation_stop_after_restarts ? 'true' : 'false' }}</td>
                  </tr>
                  <tr>
                    <td>
                      <label for="cma-restart-center">restart_center_mode</label>
                      <p class="muted small">best = 从当前最优点继续精修；random = 平台期后做多启动重启；alternate = best/random 交替。</p>
                    </td>
                    <td>
                      <select id="cma-restart-center" v-model="form.cma_es.restart_center_mode">
                        <option value="best">best</option>
                        <option value="random">random</option>
                        <option value="alternate">alternate</option>
                      </select>
                    </td>
                  </tr>
                  <tr>
                    <td>
                      <label for="cma-restart-pop-mult">restart_population_multiplier</label>
                      <p class="muted small">population 增长倍率。1.0 = 不变；2.0 = 大重启按倍数扩张。</p>
                    </td>
                    <td>
                      <input id="cma-restart-pop-mult" type="number" min="1" max="8" step="0.25" placeholder="1.0"
                        v-model.number="form.cma_es.restart_population_multiplier" />
                    </td>
                  </tr>
                  <tr>
                    <td>
                      <label for="cma-restart-pop-schedule">restart_population_schedule</label>
                      <p class="muted small">ipop = 单调增大 population；bipop = 大/小 population 重启交替。</p>
                    </td>
                    <td>
                      <select id="cma-restart-pop-schedule" v-model="form.cma_es.restart_population_schedule">
                        <option value="ipop">ipop</option>
                        <option value="bipop">bipop</option>
                      </select>
                    </td>
                  </tr>
                  <tr>
                    <td>
                      <label for="cma-restart-pop-max">restart_max_population_size</label>
                      <p class="muted small">重启后 population size 上限。空 = 不限制。</p>
                    </td>
                    <td>
                      <input id="cma-restart-pop-max" type="number" min="1" max="1024" step="1" placeholder="auto"
                        v-model.number="form.cma_es.restart_max_population_size" />
                    </td>
                  </tr>
                  <tr>
                    <td>
                      <label for="cma-initial-design-samples">initial_design_samples</label>
                      <p class="muted small">CMA-ES 前先评估多少个覆盖采样候选，再用这些结果 warm-start。0 = 关闭。</p>
                    </td>
                    <td>
                      <input id="cma-initial-design-samples" type="number" min="0" max="512" step="1" placeholder="0"
                        v-model.number="form.cma_es.initial_design_samples" />
                    </td>
                  </tr>
                  <tr>
                    <td>
                      <label for="cma-initial-design-method">initial_design_method</label>
                      <p class="muted small">当前支持 latin_hypercube，用分层覆盖采样减少冷启动只在局部搜索的问题。</p>
                    </td>
                    <td>
                      <select id="cma-initial-design-method" v-model="form.cma_es.initial_design_method">
                        <option value="latin_hypercube">latin_hypercube</option>
                      </select>
                    </td>
                  </tr>
                  <tr>
                    <td>
                      <label><input type="checkbox" v-model="form.cma_es.initial_design_include_current" /> initial_design_include_current</label>
                      <p class="muted small">把当前 .lmat 参数作为第一个初始设计样本，用来保留基线对照。</p>
                    </td>
                    <td class="muted small mono">{{ form.cma_es.initial_design_include_current ? 'true' : 'false' }}</td>
                  </tr>
                </tbody>
              </table>
            </td>
          </tr>
          <tr>
            <td>
              <label for="cfg-max-iter">max_iterations</label>
              <p class="muted small">
                最多迭代多少轮才停止。
                <span v-if="isCma">CMA-ES 模式下相当于评估预算（每轮 = 1 次 ask/render/tell）。</span>
                <span v-else>启发式模式下，阶段切换不会重置计数。</span>
              </p>
            </td>
            <td>
              <input id="cfg-max-iter" type="number" min="1" max="500" v-model.number="form.max_iterations" />
            </td>
          </tr>
          <tr>
            <td>
              <label for="cfg-target">target_score</label>
              <p class="muted small">
                fit_score 达到该值即终止。research 是当前默认目标，直接对应研究总分 / 100；human_accept / perceptual / linear 主要用于诊断对照。
              </p>
            </td>
            <td>
              <input id="cfg-target" type="number" step="0.01" min="0" max="1" v-model.number="form.target_score" />
            </td>
          </tr>
          <tr>
            <td>
              <label for="cfg-mode">fit_score_mode</label>
              <p class="muted small">
                <strong>research</strong>（推荐）：使用新的多视角 research_score / 100，包含 ΔE00、亮度、结构、高光与细节纹理。
                <br/>
                <strong>human_accept</strong>（推荐）：弱化姿态/视角微差带来的像素惩罚，重点比较前景颜色分布和材质统计。
                <br/>
                <strong>perceptual</strong>：更严格的通道加权 MAE + SSIM，用于诊断。
                <br/>
                <strong>linear</strong>（旧逻辑）：<span class="mono">1 - MAE</span>，非常宽松，仅用于对照。
              </p>
            </td>
            <td>
              <select id="cfg-mode" v-model="form.fit_score_mode">
                <option value="research">research（研究指标闭环）</option>
                <option value="human_accept">human_accept</option>
                <option value="perceptual">perceptual</option>
                <option value="linear">linear (legacy)</option>
              </select>
            </td>
          </tr>
          <tr>
            <td>
              <label for="cfg-rerender">rerender_wait_ms</label>
              <p class="muted small">apply 后等待 Laya 编辑器重渲染的毫秒数。</p>
            </td>
            <td>
              <input id="cfg-rerender" type="number" min="0" max="60000" step="100" v-model.number="form.rerender_wait_ms" />
            </td>
          </tr>
          <tr class="analysis-performance-block">
            <td colspan="2">
              <h3 class="sub">分析性能与产物保留</h3>
              <table class="cfg-subtable">
                <tbody>
                  <tr>
                    <td>
                      <label for="perf-workers">multiview_workers</label>
                      <p class="muted small">多视角图像分析并行 worker 数。auto = min(view 数, CPU 核心数)。可手动填 1/2/4/8。</p>
                    </td>
                    <td>
                      <input id="perf-workers" type="text" placeholder="auto" v-model="form.analysis_performance.multiview_workers" />
                    </td>
                  </tr>
                  <tr>
                    <td>
                      <label for="perf-batch">evaluation_batch_size</label>
                      <p class="muted small">CMA 候选评估批量宽度。1 = 当前单候选闭环；大于 1 供后续批量渲染/评分入口使用。</p>
                    </td>
                    <td>
                      <input id="perf-batch" type="number" min="1" max="64" step="1" v-model.number="form.analysis_performance.evaluation_batch_size" />
                    </td>
                  </tr>
                  <tr>
                    <td>
                      <label for="perf-eval-workers">evaluation_workers</label>
                      <p class="muted small">安全路径下同批候选的并发评估 worker 数；共享 .lmat / Editor 截图路径会自动退回 1。</p>
                    </td>
                    <td>
                      <input id="perf-eval-workers" type="number" min="1" max="64" step="1" v-model.number="form.analysis_performance.evaluation_workers" />
                    </td>
                  </tr>
                  <tr>
                    <td>
                      <label><input type="checkbox" v-model="form.analysis_performance.evaluation_parallel_safe" /> evaluation_parallel_safe</label>
                      <p class="muted small">仅当外部 renderer 实例彼此隔离时启用；单 Laya 实例或共享命令文件不要打开。</p>
                    </td>
                    <td class="muted small mono">{{ form.analysis_performance.evaluation_parallel_safe ? 'true' : 'false' }}</td>
                  </tr>
                  <tr>
                    <td>
                      <label for="perf-full-rerank">full_rerank_top_k</label>
                      <p class="muted small">batch 候选先 fast 粗筛，再对 top-k 候选用 full profile 重评估。0 = 关闭。</p>
                    </td>
                    <td>
                      <input id="perf-full-rerank" type="number" min="0" max="64" step="1" v-model.number="form.analysis_performance.full_rerank_top_k" />
                    </td>
                  </tr>
                  <tr>
                    <td>
                      <label><input type="checkbox" v-model="form.analysis_performance.best_full_validation" /> best_full_validation</label>
                      <p class="muted small">fast/proxy 候选会刷新 best 时，先用 full profile 复评，避免 best 被代理指标噪声锁定。</p>
                    </td>
                    <td class="muted small mono">{{ form.analysis_performance.best_full_validation ? 'true' : 'false' }}</td>
                  </tr>
                  <tr>
                    <td>
                      <label><input type="checkbox" v-model="form.analysis_performance.target_full_validation" /> target_full_validation</label>
                      <p class="muted small">fast/proxy 分数达到 target 时，先用 full profile 复评，复评仍达标才停止。</p>
                    </td>
                    <td class="muted small mono">{{ form.analysis_performance.target_full_validation ? 'true' : 'false' }}</td>
                  </tr>
                  <tr>
                    <td>
                      <label for="perf-snapshot">snapshot_interval</label>
                      <p class="muted small">统一快照间隔：P2 指标、diff 图和完整迭代详情都按这个轮数保留；0 = 只保留第 0 轮、best、final 和最近 N 轮。</p>
                    </td>
                    <td>
                      <input id="perf-snapshot" type="number" min="0" max="10000" step="1" v-model.number="form.analysis_performance.snapshot_interval" />
                    </td>
                  </tr>
                  <tr>
                    <td>
                      <label for="perf-research-profile">research_metrics_profile</label>
                      <p class="muted small">tiered = 普通轮 fast proxy，snapshot/best/final 使用 full research metrics。</p>
                    </td>
                    <td>
                      <select id="perf-research-profile" v-model="form.analysis_performance.research_metrics_profile">
                        <option value="tiered">tiered</option>
                        <option value="full">full</option>
                        <option value="fast">fast</option>
                      </select>
                    </td>
                  </tr>
                  <tr>
                    <td>
                      <label>derived intervals</label>
                      <p class="muted small">为避免“有 diff 没截图/有截图没 P2”的错位，P2、diff 和完整产物保留现在统一跟随 snapshot_interval。</p>
                    </td>
                    <td class="muted small mono">p2/diff/artifact = {{ form.analysis_performance.snapshot_interval }}</td>
                  </tr>
                  <tr>
                    <td>
                      <label for="perf-lastn">keep_last_n_artifacts</label>
                      <p class="muted small">始终保留最近 N 轮截图/图像分析，保证前端实时查看和下一轮评分不受影响。</p>
                    </td>
                    <td>
                      <input id="perf-lastn" type="number" min="1" max="200" step="1" v-model.number="form.analysis_performance.keep_last_n_artifacts" />
                    </td>
                  </tr>
                  <tr>
                    <td>
                      <label><input type="checkbox" v-model="form.analysis_performance.always_keep_best_artifact" /> always_keep_best_artifact</label>
                      <p class="muted small">保留 best 轮的可用图像产物，便于复盘最优截图。</p>
                    </td>
                    <td class="muted small mono">{{ form.analysis_performance.always_keep_best_artifact ? 'true' : 'false' }}</td>
                  </tr>
                  <tr>
                    <td>
                      <label><input type="checkbox" v-model="form.analysis_performance.always_keep_first_artifact" /> always_keep_first_artifact</label>
                      <p class="muted small">保留第 0 轮图像产物，便于比较初始状态。</p>
                    </td>
                    <td class="muted small mono">{{ form.analysis_performance.always_keep_first_artifact ? 'true' : 'false' }}</td>
                  </tr>
                </tbody>
              </table>
            </td>
          </tr>
          <tr>
            <td>
              <label><input type="checkbox" v-model="form.apply_lmat" /> apply_lmat</label>
              <p class="muted small">勾选后，每轮真实写入 .lmat 并自动备份 .bak。否则只写候选副本。</p>
            </td>
            <td class="muted small mono">{{ form.apply_lmat ? '--apply-lmat --write-candidate-lmat' : '(不写真 .lmat)' }}</td>
          </tr>
          <tr class="legacy-disabled">
            <td>
              <label><input type="checkbox" :checked="false" disabled /> capture_screen_after_apply（旧屏幕截图，已禁用）</label>
              <p class="muted small">当前自动化工具统一使用 Laya Editor 脚本截图，不再唤醒前端窗口做固定区域截图。</p>
            </td>
            <td class="muted small mono">(disabled)</td>
          </tr>
          <tr>
            <td>
              <label><input type="checkbox" :checked="true" disabled /> use_laya_editor_capture</label>
              <p class="muted small">
                使用 Laya Editor 扩展后台执行 reimport / reload scene / 相机截图 / 多视角 RenderTexture 截图。这是当前唯一维护的截图路径。
              </p>
            </td>
            <td class="muted small mono">laya_editor_capture.enabled=true</td>
          </tr>
          <tr class="editor-capture-block">
            <td colspan="2">
              <h3 class="sub">Laya Editor 后台截图</h3>
              <table class="cfg-subtable">
                <tbody>
                  <tr>
                    <td>
                      <label>
                        <input type="checkbox" v-model="form.laya_editor_capture.reload_scene_after_reimport" />
                        reload_scene_after_reimport
                      </label>
                      <p class="muted small">材质 reimport 后重载当前场景，确保场景实例拿到最新 .lmat。</p>
                    </td>
                    <td class="muted small mono">
                      {{ form.laya_editor_capture.reload_scene_after_reimport ? 'true' : 'false' }}
                    </td>
                  </tr>
                  <tr>
                    <td>
                      <label for="editor-refresh-delay">refresh_after_reimport_delay_ms</label>
                      <p class="muted small">reimport/reload 后等待多少毫秒再截图。Laya 项目大时可提高到 1200~2000。</p>
                    </td>
                    <td>
                      <input
                        id="editor-refresh-delay"
                        type="number"
                        min="0"
                        max="10000"
                        step="100"
                        v-model.number="form.laya_editor_capture.refresh_after_reimport_delay_ms"
                      />
                    </td>
                  </tr>
                  <tr>
                    <td>
                      <label for="editor-timeout">timeout_s</label>
                      <p class="muted small">Python 等待 Laya 写出多视角 report 的最长秒数。</p>
                    </td>
                    <td>
                      <input
                        id="editor-timeout"
                        type="number"
                        min="5"
                        max="600"
                        step="5"
                        v-model.number="form.laya_editor_capture.timeout_s"
                      />
                    </td>
                  </tr>
                </tbody>
              </table>
            </td>
          </tr>
          <tr>
            <td>
              <label><input type="checkbox" v-model="form.use_capture_contract" /> use_capture_contract</label>
              <p class="muted small">使用 RenderDriver 的 capture 契约（Puppeteer 走 capture_laya.js 时启用）。</p>
            </td>
            <td class="muted small mono">{{ form.use_capture_contract ? '--capture' : '(legacy render_candidate)' }}</td>
          </tr>
          <tr>
            <td>
              <label><input type="checkbox" v-model="form.dry_run" /> dry_run</label>
              <p class="muted small">不调外部渲染器，只走分析+写候选；用于不污染 .lmat 的演练。</p>
            </td>
            <td class="muted small mono">{{ form.dry_run ? '--dry-run' : '(真实跑)' }}</td>
          </tr>
        </tbody>
      </table>
      <footer style="display: flex; align-items: center; gap: 12px; margin-top: 8px;">
        <button class="primary" @click="save" :disabled="saving">{{ saving ? '保存中…' : '保存配置' }}</button>
        <span v-if="ok" class="muted small ok">✓ 已保存</span>
      </footer>
    </section>
  </div>
</template>

<style scoped>
.algo-config { display: flex; flex-direction: column; gap: 14px; padding-bottom: 24px; }
.cfg-table { width: 100%; border-collapse: collapse; }
.cfg-table td {
  padding: 10px 8px;
  border-bottom: 1px solid var(--border);
  vertical-align: top;
}
.cfg-table td:first-child { width: 65%; }
.cfg-table td:last-child {
  text-align: right;
  font-family: var(--mono);
  white-space: nowrap;
}
.cfg-table label { font-weight: 600; }
.cfg-table p { margin: 2px 0 0; }
.cfg-table input[type="number"],
.cfg-table input[type="text"] {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  color: var(--text);
  padding: 4px 8px;
  border-radius: 4px;
  font-family: var(--mono);
  width: 120px;
  text-align: right;
}
.cfg-table input[type="checkbox"] { vertical-align: -2px; margin-right: 6px; }
.cfg-table select {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  color: var(--text);
  padding: 4px 8px;
  border-radius: 4px;
  font-family: var(--mono);
  min-width: 240px;
}
.cma-block td,
.editor-capture-block td,
.analysis-performance-block td {
  background: rgba(255, 200, 80, 0.04);
  border-left: 3px solid var(--accent, #c79a3d);
  padding-left: 12px;
}
.sub {
  margin: 0 0 8px;
  font-size: 13px;
  color: var(--accent, #c79a3d);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}
.cfg-subtable { width: 100%; border-collapse: collapse; }
.cfg-subtable td {
  padding: 6px 8px;
  border-bottom: 1px solid var(--border);
  vertical-align: top;
}
.cfg-subtable td:first-child { width: 65%; }
.cfg-subtable td:last-child {
  text-align: right;
  font-family: var(--mono);
  white-space: nowrap;
}
.cfg-subtable input[type="number"],
.cfg-subtable input[type="text"] {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  color: var(--text);
  padding: 4px 8px;
  border-radius: 4px;
  font-family: var(--mono);
  width: 120px;
  text-align: right;
}
.cfg-subtable input[type="number"]:disabled { opacity: 0.5; }
.primary { background: var(--accent-strong); border-color: var(--accent-strong); color: white; }
.primary:disabled { opacity: 0.5; }
.ok { color: var(--good); }
.badge {
  display: inline-block;
  margin-left: 6px;
  padding: 0 6px;
  font-size: 10px;
  border-radius: 999px;
  background: rgba(53, 132, 228, 0.18);
  color: #3584e4;
  vertical-align: middle;
  font-weight: 600;
  letter-spacing: 0.05em;
}
</style>
