<script setup lang="ts">
import type { IterationKind, IterationSummary } from '../types';
import {
  ALGO_CONFIG_VIEW_ID,
  COMPARE_VIEW_ID,
  LLM_VIEW_ID,
  OVERVIEW_VIEW_ID,
  PREANALYSIS_VIEW_ID,
  PROJECT_CONFIG_VIEW_ID,
  REPORT_VIEW_ID,
  RUN_VIEW_ID,
} from '../types';

const props = defineProps<{
  iterations: IterationSummary[];
  modelValue: string;
  hasReport: boolean;
  isProject: boolean;
  jobIsRunning: boolean;
}>();

defineEmits<{ (e: 'update:modelValue', value: string): void }>();

void props;

function severityClass(fitScore: number | null, target: number | null): string {
  if (fitScore == null) return 'severity-none';
  if (target != null && fitScore >= target) return 'severity-none';
  if (fitScore >= 0.85) return 'severity-none';
  if (fitScore >= 0.7) return 'severity-low';
  if (fitScore >= 0.5) return 'severity-medium';
  return 'severity-high';
}

function formatScore(value: number | null): string {
  if (value == null || Number.isNaN(value)) return '—';
  return value.toFixed(4);
}

function kindLabel(kind: IterationKind): string {
  switch (kind) {
    case 'auto_adjust': return 'auto';
    case 'probe': return 'probe';
    case 'diff_only': return 'diff';
    default: return kind;
  }
}

function stageLabel(entry: IterationSummary): string {
  if (entry.kind === 'probe') return '探针候选';
  if (entry.kind === 'diff_only') return '一次性差异分析';
  return entry.selected_stage ?? entry.stop_reason ?? '—';
}
</script>

<template>
  <ul class="iter-list">
    <li
      class="iter-item nav-item"
      :class="{ 'is-active': modelValue === OVERVIEW_VIEW_ID }"
      @click="$emit('update:modelValue', OVERVIEW_VIEW_ID)"
    >
      <span class="iter-num icon">★</span>
      <span class="iter-stage">case overview</span>
      <span class="iter-meta muted small">元数据</span>
    </li>

    <template v-if="isProject">
      <li
        class="iter-item nav-item"
        :class="{ 'is-active': modelValue === PROJECT_CONFIG_VIEW_ID }"
        @click="$emit('update:modelValue', PROJECT_CONFIG_VIEW_ID)"
      >
        <span class="iter-num icon">⚙</span>
        <span class="iter-stage">项目配置</span>
        <span class="iter-meta muted small">输入文件</span>
      </li>
      <li
        class="iter-item nav-item"
        :class="{ 'is-active': modelValue === PREANALYSIS_VIEW_ID }"
        @click="$emit('update:modelValue', PREANALYSIS_VIEW_ID)"
      >
        <span class="iter-num icon">⚗</span>
        <span class="iter-stage">预分析</span>
        <span class="iter-meta muted small">shader diff</span>
      </li>
      <li
        class="iter-item nav-item"
        :class="{ 'is-active': modelValue === ALGO_CONFIG_VIEW_ID }"
        @click="$emit('update:modelValue', ALGO_CONFIG_VIEW_ID)"
      >
        <span class="iter-num icon">⌬</span>
        <span class="iter-stage">算法配置</span>
        <span class="iter-meta muted small">target / iter</span>
      </li>
      <li
        class="iter-item nav-item"
        :class="{ 'is-active': modelValue === RUN_VIEW_ID }"
        @click="$emit('update:modelValue', RUN_VIEW_ID)"
      >
        <span class="iter-num icon">▶</span>
        <span class="iter-stage">运行控制台</span>
        <span class="iter-meta">
          <span v-if="jobIsRunning" class="severity-badge severity-low">running</span>
          <span v-else class="muted small">start/cancel</span>
        </span>
      </li>
      <li
        class="iter-item nav-item"
        :class="{ 'is-active': modelValue === LLM_VIEW_ID }"
        @click="$emit('update:modelValue', LLM_VIEW_ID)"
      >
        <span class="iter-num icon">✦</span>
        <span class="iter-stage">LLM 助手</span>
        <span class="iter-meta muted small">骨架</span>
      </li>
    </template>

    <li
      v-if="hasReport"
      class="iter-item nav-item"
      :class="{ 'is-active': modelValue === REPORT_VIEW_ID }"
      @click="$emit('update:modelValue', REPORT_VIEW_ID)"
    >
      <span class="iter-num icon">▤</span>
      <span class="iter-stage">report.md</span>
      <span class="iter-meta muted small">人类可读</span>
    </li>

    <li
      v-if="iterations.length >= 2"
      class="iter-item nav-item"
      :class="{ 'is-active': modelValue === COMPARE_VIEW_ID }"
      @click="$emit('update:modelValue', COMPARE_VIEW_ID)"
    >
      <span class="iter-num icon">⇄</span>
      <span class="iter-stage">迭代对比</span>
      <span class="iter-meta muted small">A vs B</span>
    </li>

    <li class="iter-divider muted small">迭代</li>

    <li
      v-for="entry in iterations"
      :key="entry.iter_id"
      class="iter-item"
      :class="{ 'is-active': entry.iter_id === modelValue }"
      @click="$emit('update:modelValue', entry.iter_id)"
    >
      <span class="iter-num">#{{ entry.iteration }}</span>
      <span class="iter-stage">
        <span class="kind-tag" :class="`kind-${entry.kind}`">{{ kindLabel(entry.kind) }}</span>
        {{ stageLabel(entry) }}
        <span v-if="entry.changes_count" class="muted small"> · {{ entry.changes_count }} changes</span>
      </span>
      <span class="iter-meta">
        <span
          v-if="entry.fit_score_before != null"
          class="severity-badge"
          :class="severityClass(entry.fit_score_before, entry.target_score)"
        >
          {{ formatScore(entry.fit_score_before) }}
        </span>
        <span v-else class="muted small">—</span>
      </span>
    </li>

    <li v-if="!iterations.length && !isProject" class="iter-empty muted small">
      没有迭代记录。
    </li>
    <li v-else-if="!iterations.length && isProject" class="iter-empty muted small">
      尚未跑出迭代。先去运行控制台开始。
    </li>
  </ul>
</template>

<style scoped>
.severity-badge {
  display: inline-block;
  font-family: var(--mono);
  padding: 0 6px;
  border-radius: 999px;
  border: 1px solid;
  font-size: 11px;
}
.kind-tag {
  display: inline-block;
  font-family: var(--mono);
  font-size: 10px;
  padding: 0 4px;
  border-radius: 3px;
  margin-right: 4px;
  vertical-align: 1px;
}
.kind-tag.kind-auto_adjust { color: var(--good); border: 1px solid var(--good); }
.kind-tag.kind-probe { color: var(--accent); border: 1px solid var(--accent); }
.kind-tag.kind-diff_only { color: var(--warn); border: 1px solid var(--warn); }
.nav-item .iter-num.icon { color: var(--accent); font-weight: 600; }
.nav-item { border-bottom: 1px dashed var(--border); }
.iter-divider {
  padding: 8px 12px 2px;
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
.iter-empty { padding: 16px 12px; }
</style>
