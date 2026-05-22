<script setup lang="ts">
import type { IterationKind, IterationSummary, JobState } from '../types';
import {
  COMPARE_VIEW_ID,
  OVERVIEW_VIEW_ID,
  REPORT_VIEW_ID,
} from '../types';

const props = defineProps<{
  iterations: IterationSummary[];
  modelValue: string;
  hasReport: boolean;
  isProject: boolean;
  jobIsRunning?: boolean;
  jobs?: JobState[];
  selectedJobId?: string;
}>();

defineEmits<{
  (e: 'update:modelValue', value: string): void;
  (e: 'update:selectedJobId', value: string): void;
}>();

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

function jobLabel(job: JobState): string {
  const value = job.started_at ?? job.job_id;
  return value.replace('T', ' ').replace(/\.\d+.*$/, '');
}

function jobScore(job: JobState): string {
  const raw = job.last_decision_summary?.research_score ?? job.last_decision_summary?.fit_score_before ?? null;
  const score = typeof raw === 'number' && raw > 1 ? raw / 100 : raw;
  return formatScore(score);
}
</script>

<template>
  <div class="iter-list">
    <template v-if="isProject">
      <section class="job-column">
        <button
          v-for="job in jobs ?? []"
          :key="job.job_id"
          type="button"
          class="iter-item job-item"
          :class="{ 'is-active': job.job_id === selectedJobId }"
          @click="$emit('update:selectedJobId', job.job_id)"
        >
          <span class="iter-num">job</span>
          <span class="iter-stage">
            <span class="kind-tag" :class="`status-${job.status}`">{{ job.status }}</span>
            {{ jobLabel(job) }}
            <span class="muted small"> · {{ job.iterations_observed }} iters</span>
          </span>
          <span class="iter-meta">
            <span class="severity-badge" :class="job.status === 'failed' ? 'severity-high' : 'severity-none'">
              {{ jobScore(job) }}
            </span>
          </span>
        </button>
        <p v-if="!(jobs ?? []).length" class="iter-empty muted small">
          尚未创建实验 job。先去运行控制台开始。
        </p>
      </section>
    </template>

    <ul v-else class="iter-nav-list">
      <li
        class="iter-item nav-item"
        :class="{ 'is-active': modelValue === OVERVIEW_VIEW_ID }"
        @click="$emit('update:modelValue', OVERVIEW_VIEW_ID)"
      >
        <span class="iter-num icon">★</span>
        <span class="iter-stage">case overview</span>
        <span class="iter-meta muted small">元数据</span>
      </li>
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

      <li v-if="!iterations.length" class="iter-empty muted small">
        没有迭代记录。
      </li>
    </ul>
  </div>
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
.kind-tag.status-running { color: var(--accent); border: 1px solid var(--accent); }
.kind-tag.status-completed { color: var(--good); border: 1px solid var(--good); }
.kind-tag.status-failed { color: var(--bad); border: 1px solid var(--bad); }
.kind-tag.status-cancelled,
.kind-tag.status-cancelling { color: var(--warn); border: 1px solid var(--warn); }
.nav-item .iter-num.icon { color: var(--accent); font-weight: 600; }
.nav-item { border-bottom: 1px dashed var(--border); }
.iter-nav-list {
  list-style: none;
  margin: 0;
  padding: 0;
}
.job-iter-browser {
  display: grid;
  grid-template-columns: minmax(0, 1.05fr) minmax(0, 1fr);
  min-height: 220px;
  border-top: 1px solid var(--border);
}
.job-column,
.iter-column {
  min-width: 0;
}
.job-column {
  border-right: 1px solid var(--border);
}
.job-item { border-bottom: 1px solid rgba(255,255,255,0.04); }
.job-item .iter-stage {
  word-break: normal;
}
.job-item .iter-meta {
  white-space: nowrap;
}
.job-iter-browser button.iter-item {
  width: 100%;
  appearance: none;
  background: transparent;
  border: 0;
  color: inherit;
  text-align: left;
  cursor: pointer;
}
.iter-divider {
  padding: 8px 12px 2px;
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
.iter-empty { padding: 16px 12px; }
</style>
