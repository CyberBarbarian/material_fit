<script setup lang="ts">
import type { IterationKind, IterationSummary } from '../types';

defineProps<{
  iterations: IterationSummary[];
  modelValue: string;
  selectedJobId: string;
}>();

defineEmits<{ (e: 'update:modelValue', value: string): void }>();

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
  <div class="job-iteration-column">
    <button
      v-for="entry in iterations"
      :key="entry.iter_id"
      type="button"
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
    </button>

    <p v-if="!selectedJobId" class="iter-empty muted small">
      请先选择一个实验 job。
    </p>
    <p v-else-if="!iterations.length" class="iter-empty muted small">
      当前 job 尚未跑出迭代。
    </p>
  </div>
</template>

<style scoped>
.job-iteration-column {
  display: flex;
  flex-direction: column;
}
.job-iteration-column button.iter-item {
  width: 100%;
  appearance: none;
  background: transparent;
  border: 0;
  color: inherit;
  text-align: left;
  cursor: pointer;
  border-radius: 0;
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
.iter-empty { padding: 16px 12px; }
</style>
