<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import type { IterationDetail } from '../types';
import ImageComparison from './ImageComparison.vue';
import MultiviewImageGrid from './MultiviewImageGrid.vue';
import ParamChangesTable from './ParamChangesTable.vue';
import ChannelMetricsTable from './ChannelMetricsTable.vue';
import ResearchMetricsPanel from './ResearchMetricsPanel.vue';

const props = defineProps<{ detail: IterationDetail }>();

type TabKey = 'decision' | 'agenda' | 'channels' | 'params' | 'lmat' | 'capture';
const activeTab = ref<TabKey>('decision');

const tabs = computed<Array<{ key: TabKey; label: string }>>(() => {
  const list: Array<{ key: TabKey; label: string }> = [];
  if (props.detail.kind === 'auto_adjust') {
    list.push({ key: 'decision', label: '决策与变化' });
    list.push({ key: 'agenda', label: '参数优先级' });
  }
  if (props.detail.diff_analysis) {
    list.push({ key: 'channels', label: '通道分析' });
  }
  if (props.detail.candidate_params) {
    list.push({ key: 'params', label: '本轮参数' });
  }
  if (props.detail.candidate_lmat_text) {
    list.push({ key: 'lmat', label: '候选 .lmat' });
  }
  if (props.detail.capture_request) {
    list.push({ key: 'capture', label: 'capture request' });
  }
  return list;
});

watch(
  () => props.detail.iter_id,
  () => {
    const first = tabs.value[0]?.key;
    if (first) activeTab.value = first;
  },
  { immediate: true },
);

const decision = computed(() => props.detail.decision);
const innerDecision = computed(() => decision.value?.decision ?? null);
const changes = computed(() => innerDecision.value?.changes ?? []);
const stage = computed(() => innerDecision.value?.stage ?? null);
const showAllParamRanking = ref(false);

const fitScore = computed(() => decision.value?.fit_score_before ?? null);
const diffScore = computed(() => decision.value?.diff_score_before ?? null);
const targetScore = computed(() => decision.value?.target_score ?? null);
const gain = computed(() => innerDecision.value?.iteration_gain ?? null);

// E-009: surface the per-iteration perceptual signals so the user can
// see what's driving fit_score (channel-weighted MAE / SSIM / mask
// coverage) instead of trusting a single composite scalar.
const perceptualSignals = computed(() => {
  const value = (decision.value as Record<string, unknown> | null | undefined)?.perceptual_signals;
  return value && typeof value === 'object' ? (value as Record<string, unknown>) : null;
});
const perceptualWeightedMae = computed(() => {
  const v = perceptualSignals.value?.weighted_mae;
  return typeof v === 'number' ? v : null;
});
const perceptualSsim = computed(() => {
  const v = perceptualSignals.value?.ssim;
  return typeof v === 'number' ? v : null;
});
const perceptualForegroundRatio = computed(() => {
  const am = perceptualSignals.value?.auto_mask as Record<string, unknown> | undefined;
  const v = am?.foreground_ratio;
  return typeof v === 'number' ? v : null;
});
const humanAcceptSignals = computed(() => {
  const value = perceptualSignals.value?.human_accept;
  return value && typeof value === 'object' ? (value as Record<string, unknown>) : null;
});
const humanAcceptScore = computed(() => {
  const v = humanAcceptSignals.value?.score;
  return typeof v === 'number' ? v : null;
});
const humanAcceptComponents = computed(() => {
  const value = humanAcceptSignals.value?.components;
  return value && typeof value === 'object' ? (value as Record<string, unknown>) : null;
});
const multiviewSummary = computed(() => decision.value?.multiview_analysis?.summary ?? null);
const multiviewViews = computed(() => decision.value?.multiview_analysis?.views ?? []);
const multiviewCount = computed(() => decision.value?.multiview_analysis?.pair_count ?? props.detail.multiview_images?.length ?? 0);
const researchSignals = computed(() => {
  const fromDecision = perceptualSignals.value?.research_metrics;
  if (fromDecision && typeof fromDecision === 'object') return fromDecision as Record<string, unknown>;
  const fromAnalysis = props.detail.diff_analysis?.research_metrics;
  return fromAnalysis && typeof fromAnalysis === 'object' ? fromAnalysis as Record<string, unknown> : null;
});

const candidateParamsJson = computed(() => {
  if (!props.detail.candidate_params) return '';
  return JSON.stringify(props.detail.candidate_params, null, 2);
});

const captureRequestJson = computed(() => {
  if (!props.detail.capture_request) return '';
  return JSON.stringify(props.detail.capture_request, null, 2);
});

const screenCapture = computed(() => {
  const value = decision.value?.screen_capture_after_apply;
  return value && typeof value === 'object' ? (value as Record<string, unknown>) : null;
});

const diffAnalysisOnly = computed(() => {
  return !!props.detail.diff_analysis && !decision.value;
});

const diffScoreFromAnalysis = computed(() => {
  const score = props.detail.diff_analysis?.score;
  return typeof score === 'number' ? score : null;
});

function fmt(value: unknown, digits = 4): string {
  if (typeof value !== 'number' || Number.isNaN(value)) return '—';
  return value.toFixed(digits);
}

const headerStage = computed(() => {
  if (props.detail.kind === 'probe') return 'probe candidate';
  if (props.detail.kind === 'diff_only') return 'root diff';
  return decision.value?.selected_stage ?? '—';
});

const headerNote = computed(() => props.detail._note ?? null);

type ParamAgendaRow = {
  param: string;
  group: string | null;
  role: string | null;
  reason: string | null;
  blocked_by: string[];
  priority: number | null;
  semantic_relevance: number | null;
  attempts: number | null;
  accepted: number | null;
  fit_gain_ema: number | null;
  risk_ema: number | null;
  recent_failures: number | null;
  component_ema: Record<string, unknown> | null;
};

const scheduler = computed(() => {
  const value = (innerDecision.value as Record<string, unknown> | null | undefined)?.scheduler;
  return value && typeof value === 'object' ? (value as Record<string, unknown>) : null;
});

const paramRankingRows = computed<ParamAgendaRow[]>(() => {
  const raw = Array.isArray(scheduler.value?.param_ranking)
    ? scheduler.value?.param_ranking
    : scheduler.value?.param_agenda;
  return normalizeParamRows(raw);
});

const paramCandidatePoolRows = computed<ParamAgendaRow[]>(() => {
  const raw = Array.isArray(scheduler.value?.param_candidate_pool)
    ? scheduler.value?.param_candidate_pool
    : scheduler.value?.param_agenda;
  return normalizeParamRows(raw);
});

const gatedParamRows = computed<ParamAgendaRow[]>(() => normalizeParamRows(scheduler.value?.gated_params));

const activationCandidateRows = computed<ParamAgendaRow[]>(() => normalizeParamRows(scheduler.value?.activation_candidates));

const visibleParamRankingRows = computed(() => {
  return showAllParamRanking.value ? paramRankingRows.value : paramRankingRows.value.slice(0, 5);
});

const paramCandidatePoolSize = computed(() => {
  const value = scheduler.value?.param_candidate_pool_size;
  return typeof value === 'number' && Number.isFinite(value) ? value : paramCandidatePoolRows.value.length;
});

const searchParamCount = computed(() => {
  const value = scheduler.value?.search_param_count;
  return typeof value === 'number' && Number.isFinite(value) ? value : paramRankingRows.value.length;
});

const allSearchableParamCount = computed(() => {
  const value = scheduler.value?.all_searchable_param_count;
  return typeof value === 'number' && Number.isFinite(value) ? value : searchParamCount.value + gatedParamRows.value.length;
});

const gatedParamCount = computed(() => {
  const value = scheduler.value?.gated_param_count;
  return typeof value === 'number' && Number.isFinite(value) ? value : gatedParamRows.value.length;
});

const paramSelectionRule = computed(() => {
  const value = scheduler.value?.param_selection_rule;
  return typeof value === 'string' ? value : '全量可搜索参数按当前瓶颈、历史收益、探索次数、风险和失败惩罚排序；分组只作为语义约束与覆盖度保护。';
});

function normalizeParamRows(raw: unknown): ParamAgendaRow[] {
  if (!Array.isArray(raw)) return [];
  return raw
    .filter((item): item is Record<string, unknown> => !!item && typeof item === 'object')
    .map((item) => ({
      param: String(item.param ?? ''),
      group: typeof item.group === 'string' ? item.group : null,
      role: typeof item.role === 'string' ? item.role : null,
      reason: typeof item.reason === 'string' ? item.reason : null,
      blocked_by: Array.isArray(item.blocked_by) ? item.blocked_by.map(String) : [],
      priority: numberOrNull(item.priority),
      semantic_relevance: numberOrNull(item.semantic_relevance),
      attempts: numberOrNull(item.attempts),
      accepted: numberOrNull(item.accepted),
      fit_gain_ema: numberOrNull(item.fit_gain_ema),
      risk_ema: numberOrNull(item.risk_ema),
      recent_failures: numberOrNull(item.recent_failures),
      component_ema: item.component_ema && typeof item.component_ema === 'object'
        ? item.component_ema as Record<string, unknown>
        : null,
    }))
    .filter((item) => item.param);
}

function numberOrNull(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function fmtSigned(value: unknown, digits = 4): string {
  if (typeof value !== 'number' || Number.isNaN(value)) return '—';
  return `${value >= 0 ? '+' : ''}${value.toFixed(digits)}`;
}

function topComponentGain(row: ParamAgendaRow): string {
  if (!row.component_ema) return '—';
  const entries = Object.entries(row.component_ema)
    .filter(([, value]) => typeof value === 'number' && Number.isFinite(value))
    .map(([key, value]) => [key, value as number] as const)
    .sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]));
  if (!entries.length) return '—';
  return entries.slice(0, 2).map(([key, value]) => `${key} ${fmtSigned(value, 3)}`).join(' · ');
}
</script>

<template>
  <div>
    <MultiviewImageGrid
      v-if="detail.multiview_images?.length"
      :items="detail.multiview_images"
      :title="`${detail.iter_id} · 多视角图像对比 · ${detail.multiview_images.length} views`"
    />
    <ImageComparison v-else :images="detail.images" />

    <section class="section">
      <h3 class="section-title">本轮 · {{ detail.iter_id }} · {{ headerStage }}</h3>

      <!-- auto_adjust full summary -->
      <div v-if="detail.kind === 'auto_adjust'" class="iter-summary">
        <span class="stat-pill">fit before <strong>{{ fmt(fitScore) }}</strong></span>
        <span class="stat-pill">RGB MAE <strong>{{ fmt(diffScore) }}</strong></span>
        <span class="stat-pill">target <strong>{{ fmt(targetScore, 3) }}</strong></span>
        <span class="stat-pill">gain <strong>{{ fmt(gain, 3) }}</strong></span>
        <span class="stat-pill">stop <strong>{{ innerDecision?.stop_reason ?? '—' }}</strong></span>
      </div>

      <div v-if="detail.kind === 'auto_adjust' && multiviewSummary" class="iter-summary perceptual">
        <span class="stat-pill stat-pill--muted small">多视角聚合 · {{ multiviewCount }} views</span>
        <span class="stat-pill">mean fit <strong>{{ fmt(multiviewSummary.mean_fit_score) }}</strong></span>
        <span class="stat-pill">worst <strong>{{ multiviewSummary.worst_view_id ?? '—' }}</strong></span>
        <span class="stat-pill">worst fit <strong>{{ fmt(multiviewSummary.worst_fit_score) }}</strong></span>
        <span class="stat-pill">p90 loss <strong>{{ fmt(multiviewSummary.p90_loss) }}</strong></span>
      </div>

      <ResearchMetricsPanel
        :metrics="researchSignals"
        :multiview-summary="multiviewSummary"
        :multiview-views="multiviewViews"
        :multiview-count="multiviewCount"
      />

      <!-- E-009 perceptual signals: only present once a run has executed
           with the new metric. Older decision.json entries don't have this
           block and the row gracefully hides itself. -->
      <div v-if="detail.kind === 'auto_adjust' && perceptualSignals" class="iter-summary perceptual">
        <span v-if="humanAcceptScore != null" class="stat-pill stat-pill--accent" title="人类可接受度评分：当前默认优化目标">
          human <strong>{{ fmt(humanAcceptScore) }}</strong>
        </span>
        <span class="stat-pill stat-pill--accent" title="加权 MAE = sum(channel_w * channel_mae)，去背景后的 model 像素 MAE">
          weighted MAE <strong>{{ fmt(perceptualWeightedMae) }}</strong>
        </span>
        <span class="stat-pill stat-pill--accent" title="结构相似性，对 1px 位移有容忍">
          SSIM <strong>{{ fmt(perceptualSsim, 3) }}</strong>
        </span>
        <span
          class="stat-pill stat-pill--accent"
          :title="`auto-mask 识别出的前景占比（candidate bg 占 ${fmt((perceptualSignals.auto_mask as any)?.candidate_bg_ratio, 3)}）`"
        >
          fg ratio <strong>{{ fmt(perceptualForegroundRatio, 3) }}</strong>
        </span>
        <span class="stat-pill stat-pill--muted small">E-009 指标</span>
      </div>

      <div v-if="detail.kind === 'auto_adjust' && humanAcceptComponents" class="iter-summary perceptual">
        <span class="stat-pill stat-pill--muted small">human components</span>
        <span
          v-for="(value, key) in humanAcceptComponents"
          :key="String(key)"
          class="stat-pill stat-pill--accent"
        >
          {{ key }} <strong>{{ fmt(value) }}</strong>
        </span>
      </div>

      <!-- diff_only summary -->
      <div v-else-if="detail.kind === 'diff_only'" class="iter-summary">
        <span class="stat-pill">RGB MAE <strong>{{ fmt(diffScoreFromAnalysis) }}</strong></span>
        <span v-if="diffScoreFromAnalysis != null" class="stat-pill">
          fit (=1−MAE) <strong>{{ fmt(1 - diffScoreFromAnalysis) }}</strong>
        </span>
      </div>

      <!-- probe summary -->
      <div v-else-if="detail.kind === 'probe'" class="iter-summary">
        <span class="stat-pill">仅 candidate params，<strong>无截图无评分</strong></span>
      </div>

      <p v-if="headerNote" class="muted small" style="margin-top: 6px;">{{ headerNote }}</p>

      <p v-if="stage?.description" class="muted small" style="margin-top: 6px;">{{ stage.description }}</p>
      <p v-if="innerDecision?.applied_lmat" class="muted small">
        已写入 <span class="mono">{{ innerDecision.applied_lmat }}</span>
      </p>
      <p v-if="innerDecision?.backup_lmat" class="muted small">
        备份 <span class="mono">{{ innerDecision.backup_lmat }}</span>
      </p>
      <p v-if="screenCapture && screenCapture.output_path" class="muted small">
        重渲染后截图 <span class="mono">{{ screenCapture.output_path }}</span>
      </p>
    </section>

    <section class="section">
      <div v-if="tabs.length" class="tab-bar">
        <button
          v-for="tab in tabs"
          :key="tab.key"
          class="tab-btn"
          :class="{ 'is-active': activeTab === tab.key }"
          @click="activeTab = tab.key"
        >
          {{ tab.label }}
        </button>
      </div>

      <div v-show="activeTab === 'decision' && detail.kind === 'auto_adjust'">
        <ParamChangesTable :changes="changes" />
      </div>

      <div v-show="activeTab === 'agenda' && detail.kind === 'auto_adjust'">
        <div v-if="paramRankingRows.length" class="param-agenda-card">
          <div class="param-agenda-header">
            <div>
              <h4>全量参数优先级 Top {{ Math.min(5, paramRankingRows.length) }}</h4>
              <p class="muted small">
                {{ paramSelectionRule }}
              </p>
              <p class="muted small">
                用户允许搜索控件：{{ allSearchableParamCount }} 个；当前活跃可搜索参数：{{ searchParamCount }} 个；被 gate 暂停：{{ gatedParamCount }} 个。
                这里展示的是当前活跃参数排序，不等同于本轮实际生成候选的数量。
              </p>
            </div>
            <button
              v-if="paramRankingRows.length > 5"
              type="button"
              class="link-btn"
              @click="showAllParamRanking = !showAllParamRanking"
            >
              {{ showAllParamRanking ? '收起为 Top 5' : `查看全部可搜索参数（${searchParamCount}）` }}
            </button>
          </div>
          <table class="agenda-table">
            <thead>
              <tr>
                <th>#</th>
                <th>参数</th>
                <th>分组</th>
                <th>priority</th>
                <th>语义</th>
                <th>尝试/接受</th>
                <th>fit收益</th>
                <th>分项收益 Top</th>
                <th>风险</th>
                <th>失败</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(row, index) in visibleParamRankingRows" :key="row.param">
                <td class="muted small">{{ index + 1 }}</td>
                <td><span class="mono">{{ row.param }}</span></td>
                <td class="muted small">{{ row.group ?? '—' }}</td>
                <td class="numeric mono">{{ fmt(row.priority) }}</td>
                <td class="numeric mono">{{ fmt(row.semantic_relevance) }}</td>
                <td class="numeric mono">{{ row.attempts ?? 0 }}/{{ row.accepted ?? 0 }}</td>
                <td class="numeric mono">{{ fmtSigned(row.fit_gain_ema) }}</td>
                <td class="muted small">{{ topComponentGain(row) }}</td>
                <td class="numeric mono">{{ fmt(row.risk_ema) }}</td>
                <td class="numeric mono">{{ row.recent_failures ?? 0 }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-if="paramCandidatePoolRows.length" class="param-agenda-card">
          <div class="param-agenda-header">
            <div>
              <h4>本轮候选池</h4>
              <p class="muted small">
                从全量排序中取前 {{ paramCandidatePoolSize }} 项作为本轮候选池；breakthrough 和参数优先搜索会优先围绕这些参数生成单参数或小组合候选。
              </p>
            </div>
          </div>
          <table class="agenda-table">
            <thead>
              <tr>
                <th>#</th>
                <th>参数</th>
                <th>分组</th>
                <th>priority</th>
                <th>语义</th>
                <th>尝试/接受</th>
                <th>fit收益</th>
                <th>风险</th>
                <th>失败</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(row, index) in paramCandidatePoolRows" :key="`${row.param}-pool`">
                <td class="muted small">{{ index + 1 }}</td>
                <td><span class="mono">{{ row.param }}</span></td>
                <td class="muted small">{{ row.group ?? '—' }}</td>
                <td class="numeric mono">{{ fmt(row.priority) }}</td>
                <td class="numeric mono">{{ fmt(row.semantic_relevance) }}</td>
                <td class="numeric mono">{{ row.attempts ?? 0 }}/{{ row.accepted ?? 0 }}</td>
                <td class="numeric mono">{{ fmtSigned(row.fit_gain_ema) }}</td>
                <td class="numeric mono">{{ fmt(row.risk_ema) }}</td>
                <td class="numeric mono">{{ row.recent_failures ?? 0 }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-if="activationCandidateRows.length || gatedParamRows.length" class="param-agenda-card">
          <div class="param-agenda-header">
            <div>
              <h4>待激活 / 门控参数</h4>
              <p class="muted small">
                这些参数是用户允许搜索的控件，但当前可能被强度为 0、功能开关或 shader define 挡住。优化器可先尝试 gate/Intensity，再让下游参数进入活跃排序。
              </p>
            </div>
          </div>
          <table v-if="activationCandidateRows.length" class="agenda-table">
            <thead>
              <tr>
                <th>#</th>
                <th>激活参数</th>
                <th>分组</th>
                <th>priority</th>
                <th>原因</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(row, index) in activationCandidateRows" :key="`${row.param}-activation`">
                <td class="muted small">{{ index + 1 }}</td>
                <td><span class="mono">{{ row.param }}</span></td>
                <td class="muted small">{{ row.group ?? '—' }}</td>
                <td class="numeric mono">{{ fmt(row.priority) }}</td>
                <td class="muted small">{{ row.reason ?? '—' }}</td>
              </tr>
            </tbody>
          </table>
          <table v-if="gatedParamRows.length" class="agenda-table gated-table">
            <thead>
              <tr>
                <th>#</th>
                <th>暂未进入活跃排序</th>
                <th>分组</th>
                <th>被 gate 阻挡</th>
                <th>原因</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(row, index) in gatedParamRows" :key="`${row.param}-gated`">
                <td class="muted small">{{ index + 1 }}</td>
                <td><span class="mono">{{ row.param }}</span></td>
                <td class="muted small">{{ row.group ?? '—' }}</td>
                <td class="muted small">{{ row.blocked_by.length ? row.blocked_by.join(', ') : '—' }}</td>
                <td class="muted small">{{ row.reason ?? '—' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-if="!paramRankingRows.length && !paramCandidatePoolRows.length" class="muted small">
          本轮没有参数优先级数据。旧实验记录可能没有 <span class="mono">scheduler.param_ranking</span>。
        </p>
      </div>

      <div v-show="activeTab === 'channels' && detail.diff_analysis">
        <p v-if="detail.kind === 'auto_adjust' && decision?.multiview_analysis" class="muted small" style="margin-bottom: 8px;">
          这是多视角聚合通道分析；优化器使用的也是这份聚合信号，不再只取第一视角。
        </p>
        <p v-if="diffAnalysisOnly" class="muted small" style="margin-bottom: 8px;">
          这是一次性 <span class="mono">analyze_diff</span> 的产物，没有 decision，仅展示通道分析。
        </p>
        <ChannelMetricsTable :diff-analysis="detail.diff_analysis" />
      </div>

      <div v-show="activeTab === 'params' && detail.candidate_params">
        <pre class="params-pane">{{ candidateParamsJson }}</pre>
      </div>

      <div v-show="activeTab === 'lmat' && detail.candidate_lmat_text">
        <pre class="params-pane">{{ detail.candidate_lmat_text }}</pre>
      </div>

      <div v-show="activeTab === 'capture' && detail.capture_request">
        <pre class="params-pane">{{ captureRequestJson }}</pre>
      </div>

      <p v-if="!tabs.length" class="muted small">本轮没有可显示的详情数据。</p>
    </section>
  </div>
</template>

<style scoped>
.iter-summary { display: flex; gap: 8px; flex-wrap: wrap; }
.iter-summary.perceptual { margin-top: 6px; }
.stat-pill--accent { background: rgba(53, 132, 228, 0.12); border-color: rgba(53, 132, 228, 0.3); }
.stat-pill--muted { opacity: 0.6; }
.mono { font-family: var(--mono); }
.param-agenda-card {
  margin-top: 14px;
  padding: 12px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.02);
}
.param-agenda-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
  margin-bottom: 10px;
}
.param-agenda-header h4 {
  margin: 0 0 4px;
  font-size: 13px;
}
.link-btn {
  border: 1px solid var(--border);
  background: transparent;
  color: var(--accent);
  border-radius: 6px;
  padding: 4px 8px;
  cursor: pointer;
  white-space: nowrap;
}
.agenda-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}
.agenda-table th,
.agenda-table td {
  padding: 6px 8px;
  border-bottom: 1px solid var(--border);
  text-align: left;
}
.agenda-table th {
  color: var(--muted);
  font-weight: 600;
}
.agenda-table .numeric {
  text-align: right;
}
</style>
