export type CaseKind = 'project' | 'auto_adjust' | 'probe' | 'diff_only' | 'empty';

export interface CaseSummary {
  id: string;
  output_dir: string;
  kind: CaseKind;
  kind_label: string;
  iterations_count: number;
  summary: string;
  last_modified: string | null;
  has_auto_adjust: boolean;
  has_report: boolean;
  best_fit_score?: number | null;
  best_score?: number | null;
  target_score?: number | null;
  auto_adjust_status?: string | null;
  root_diff_score?: number | null;
}

export interface AutoAdjustResultSummary {
  status?: string;
  target_score?: number;
  best_score?: number;
  best_fit_score?: number;
  best_params?: Record<string, unknown>;
  state_path?: string;
}

export interface CaseOverviewPayload extends CaseSummary {
  auto_adjust_result: AutoAdjustResultSummary | null;
  stage_plan: StageInfo[] | null;
  adjustment_policies: AdjustmentPolicy[] | null;
  laya_shader_params: ShaderInfoPayload | null;
  laya_material_params: Record<string, unknown> | null;
  initial_params: Record<string, unknown> | null;
  unity_shader_params: ShaderInfoPayload | null;
  unity_material_params: Record<string, unknown> | null;
  report_path: string | null;
  root_diff_analysis: DiffAnalysis | null;
}

export interface StageInfo {
  name: string;
  params: string[];
  description?: string;
}

export interface AdjustmentPolicy {
  name: string;
  description: string;
  channels: string[];
  params: string[];
  max_iterations: number;
  target_score: number;
}

export interface ShaderInfoPayload {
  path: string;
  name: string;
  params: Array<{
    name: string;
    param_type: string;
    default: unknown;
    range_min: number | null;
    range_max: number | null;
    hidden: string | null;
  }>;
  defines: Array<{
    name: string;
    define_type: string;
    default: unknown;
    position: string | null;
  }>;
}

export type IterationKind = 'auto_adjust' | 'probe' | 'diff_only';

export interface IterationSummary {
  iter_id: string;
  iteration: number;
  kind: IterationKind;
  selected_stage: string | null;
  diff_score_before: number | null;
  fit_score_before: number | null;
  target_score: number | null;
  stop_reason: string | null;
  iteration_gain: number | null;
  changes_count: number;
  applied_lmat: string | null;
  diff_image_url: string | null;
}

export interface ParamChange {
  param: string;
  old: unknown;
  new: unknown;
  reason?: string;
  new_before_unity_anchor?: unknown;
}

export interface IterationDecision {
  iteration?: number;
  input_pair?: { reference?: string; candidate?: string; mask?: string };
  diff_score_before?: number;
  fit_score_before?: number;
  target_score?: number;
  selected_stage?: string;
  decision?: {
    stage?: AdjustmentPolicy;
    iteration_gain?: number;
    score?: number;
    changes?: ParamChange[];
    stop_reason?: string;
    applied_lmat?: string;
    backup_lmat?: string;
  };
  params_path?: string;
  candidate_lmat_path?: string;
  render_result?: Record<string, unknown>;
  screen_capture_after_apply?: Record<string, unknown> | null;
}

export interface MaterialChannel {
  name: string;
  valid: boolean;
  severity: 'none' | 'low' | 'medium' | 'high';
  rgb_mae: number;
  luma_bias_candidate_minus_reference: number;
  saturation_bias_candidate_minus_reference: number;
  contrast_bias_candidate_minus_reference: number;
  rgb_bias_candidate_minus_reference: [number, number, number];
  related_params: string[];
}

export interface CenterEdgeBalance {
  valid: boolean;
  center_luma_signed: number;
  edge_luma_signed: number;
  edge_minus_center_luma_bias: number;
  related_params: string[];
}

export interface AdjustmentHint {
  channel: string;
  severity: string;
  direction: string;
  reason: string;
  related_params: string[];
}

export interface DiffAnalysis {
  status: string;
  metric: string;
  score: number;
  image_size: [number, number];
  reference_path: string;
  candidate_path: string;
  mask_path: string;
  diff_image_path: string;
  global: Record<string, unknown>;
  regions: Record<string, Record<string, unknown>>;
  material_channels: Record<string, MaterialChannel | CenterEdgeBalance>;
  adjustment_hints?: AdjustmentHint[];
  report_path?: string;
}

export interface IterationDetail {
  case_id: string;
  iter_id: string;
  kind: IterationKind;
  decision: IterationDecision | null;
  diff_analysis: DiffAnalysis | null;
  candidate_params: Record<string, unknown> | null;
  candidate_lmat_text: string | null;
  capture_request?: Record<string, unknown> | null;
  images: {
    reference: string | null;
    candidate: string | null;
    diff: string | null;
  };
  _note?: string;
}

export const OVERVIEW_VIEW_ID = '__overview__';
export const REPORT_VIEW_ID = '__report__';
export const COMPARE_VIEW_ID = '__compare__';
export const PROJECT_CONFIG_VIEW_ID = '__project_config__';
export const PREANALYSIS_VIEW_ID = '__preanalysis__';
export const ALGO_CONFIG_VIEW_ID = '__algo_config__';
export const RUN_VIEW_ID = '__run__';
export const LLM_VIEW_ID = '__llm__';

export type SyntheticViewId =
  | typeof OVERVIEW_VIEW_ID
  | typeof REPORT_VIEW_ID
  | typeof COMPARE_VIEW_ID
  | typeof PROJECT_CONFIG_VIEW_ID
  | typeof PREANALYSIS_VIEW_ID
  | typeof ALGO_CONFIG_VIEW_ID
  | typeof RUN_VIEW_ID
  | typeof LLM_VIEW_ID;

const SYNTHETIC_VIEW_IDS: ReadonlySet<string> = new Set<string>([
  OVERVIEW_VIEW_ID,
  REPORT_VIEW_ID,
  COMPARE_VIEW_ID,
  PROJECT_CONFIG_VIEW_ID,
  PREANALYSIS_VIEW_ID,
  ALGO_CONFIG_VIEW_ID,
  RUN_VIEW_ID,
  LLM_VIEW_ID,
]);

export function isSyntheticView(value: string): value is SyntheticViewId {
  return SYNTHETIC_VIEW_IDS.has(value);
}

// ============================================================================
// Project / Job / Preanalysis types
// ============================================================================

export interface CaptureRegion {
  x: number;
  y: number;
  width: number;
  height: number;
}

// E-007: how the pipeline locates and focuses the Laya editor window
// before each .lmat write and each capture. Without this, Laya pauses
// rendering whenever its window is in the background, freezing the
// optimizer on stale frames.
export interface LayaWindowConfig {
  process_pattern: string;
  title_pattern: string;
  settle_ms: number;
}

// E-008 follow-up: capture region anchored to the Laya editor
// window's top-left corner. Survives the user dragging or resizing
// the Laya window between auto-adjust runs. ``offset_x/y`` and
// ``width/height`` are populated when the user picks a region; the
// backend computes them from (region - laya_window_rect.topLeft) at
// pick time. ``enabled`` defaults to true on new projects.
export interface LayaCaptureAnchor {
  enabled: boolean;
  offset_x: number;
  offset_y: number;
  width: number;
  height: number;
}

export interface ProjectInputs {
  unity_shader_path: string | null;
  unity_material_params_path: string | null;
  unity_reference_image_path: string | null;
  laya_shader_path: string | null;
  laya_material_lmat_path: string | null;
  laya_capture_region: CaptureRegion | null;
  laya_capture_dir: string | null;
  laya_capture_state_file: string | null;
  laya_capture_prefix: string;
  laya_window?: LayaWindowConfig;
  laya_capture_anchor?: LayaCaptureAnchor;
}

export type FitScoreMode = 'linear' | 'perceptual';

// E-007 (ExperimentLog.md): magenta-probe preflight result.
// Mirrors ProbeResult.to_dict() in tools/material_fit/laya/refresh_probe.py.
export interface FocusLogEntry {
  step: string;
  success: boolean;
  reason: string;
  hwnd?: number | null;
  title?: string | null;
  process_name?: string | null;
  platform?: string;
  candidates_sample?: Array<Record<string, unknown>>;
}

export interface PreflightResult {
  success: boolean;
  detected_change: boolean;
  detected_restore: boolean;
  reason: string;
  // Primary signals (added in E-007 follow-up): mean per-pixel L1 color
  // distance, in [0, 255]. Robust on textured surfaces where the legacy
  // magenta_ratio detector under-reports.
  mean_diff_baseline_probe?: number;
  mean_diff_baseline_restored?: number;
  mean_diff_probe_restored?: number;
  mean_diff_change_threshold?: number;
  mean_diff_restore_threshold?: number;
  // Secondary signals (kept for diagnostics).
  magenta_ratio_baseline: number;
  magenta_ratio_probe: number;
  magenta_ratio_restored: number;
  captures: { baseline?: string; probe?: string; restored?: string; [k: string]: string | undefined };
  probe_param: string;
  focus_log?: FocusLogEntry[];
  probe_value: number[];
  rerender_wait_ms: number;
  detection_threshold: number;
  notes: string[];
  error: string | null;
  last_path?: string;
}

export type OptimizerKind = 'heuristic' | 'cma_cold' | 'cma_warm';

export interface CmaEsConfig {
  // mode is informational; the active mode is encoded by OptimizerKind
  // ("cma_cold" / "cma_warm"). Kept here so the UI can show a single
  // panel of CMA-ES tunables regardless of which CMA mode is active.
  mode: 'warm' | 'cold';
  warm_start_iters: number;
  population_size: number | null;
  sigma: number | null;
  seed: number | null;
  /**
   * E-010: blend ratio for `analysis.adjustment_hints` into each
   * CMA-ES proposal. 0 disables (legacy), 0.30 is the recommended
   * default, > 0.5 is heavy expert-driven exploration. See
   * `tools/material_fit/docs/ExperimentLog.md` E-010.
   */
  hint_bias_mix_ratio: number;
}

export interface AlgorithmConfig {
  max_iterations: number;
  target_score: number;
  apply_lmat: boolean;
  capture_screen_after_apply: boolean;
  rerender_wait_ms: number;
  use_capture_contract: boolean;
  dry_run: boolean;
  fit_score_mode: FitScoreMode;
  optimizer: OptimizerKind;
  cma_es: CmaEsConfig;
}

export interface LlmConfig {
  enabled: boolean;
  provider: string | null;
  note?: string;
}

export interface ProjectSummary {
  id: string;
  name: string;
  description: string;
  created_at: string;
  updated_at: string;
  inputs_required_filled: boolean;
  inputs_optional_filled: number;
  preanalysis_present: boolean;
  iterations_count: number;
  active_job_id: string | null;
  last_job_id: string | null;
  output_dir: string;
}

export interface ProjectDetail {
  schema_version: number;
  id: string;
  name: string;
  description: string;
  created_at: string;
  updated_at: string;
  inputs: ProjectInputs;
  algorithm_config: AlgorithmConfig;
  llm_config: LlmConfig;
  preanalysis_path: string | null;
  active_job_id: string | null;
  last_job_id: string | null;
  manual_param_mapping?: Record<string, string>;
  _summary?: ProjectSummary;
}

export type ParamMappingStatus =
  | 'manual'
  | 'manual_skip'
  | 'curated'
  | 'exact'
  | 'fuzzy'
  | 'unity_only'
  | 'laya_only';

export interface ParamMappingRow {
  unity_name: string | null;
  unity_type: string | null;
  laya_name: string | null;
  laya_type: string | null;
  status: ParamMappingStatus;
  score: number;
  reason: string;
}

export interface PreanalysisCoverage {
  unity_total: number;
  unity_mapped: number;
  unity_unmapped: number;
  laya_total: number;
  laya_only: number;
  ratio: number;
  by_status?: Partial<Record<ParamMappingStatus, number>>;
}

export interface ParamRecommendation {
  laya_param: string;
  unity_param: string;
  current_laya_value: unknown;
  suggested_value: unknown;
  status: 'exact' | 'fuzzy';
  type: string | null;
  range: [number | null, number | null];
}

export interface PreanalysisPayload {
  project_id: string;
  ran_at: string;
  unity_shader: ShaderInfoPayload | null;
  laya_shader: ShaderInfoPayload;
  laya_material_params: Record<string, unknown>;
  unity_material_params: Record<string, unknown>;
  param_mapping: ParamMappingRow[];
  stage_plan: AdjustmentPolicy[];
  coverage: PreanalysisCoverage;
  initial_recommendations: ParamRecommendation[];
  warnings: string[];
}

export interface JobDecisionSummary {
  iteration: number | null;
  selected_stage: string | null;
  fit_score_before: number | null;
  diff_score_before: number | null;
  stop_reason: string | null;
  changes_count: number;
}

export interface JobState {
  job_id: string;
  project_id: string;
  pid: number | null;
  status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled' | 'cancelling';
  started_at: string | null;
  ended_at: string | null;
  return_code: number | null;
  error: string | null;
  args: string[];
  iterations_observed: number;
  last_iter_id: string | null;
  last_decision_summary: JobDecisionSummary | null;
}

export interface FilePickResult {
  path: string;
  error?: string;
}

export interface FileInfo {
  path: string;
  exists: boolean;
  is_file?: boolean;
  is_dir?: boolean;
  size?: number;
  mtime?: number;
  name?: string;
  suffix?: string;
  error?: string;
}
