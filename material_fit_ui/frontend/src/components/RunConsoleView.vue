<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import {
  cancelJob,
  fetchJob,
  fetchJobLog,
  fetchProject,
  listJobs,
  startJob,
} from '../api';
import type { JobState, ProjectDetail } from '../types';

const props = defineProps<{ projectId: string }>();
const emit = defineEmits<{
  (e: 'job-progress'): void;
  (e: 'open-iter', iterId: string): void;
}>();

const project = ref<ProjectDetail | null>(null);
const jobs = ref<JobState[]>([]);
const activeJob = ref<JobState | null>(null);
const log = ref('');
const error = ref<string | null>(null);
const starting = ref(false);
const cancelling = ref(false);

let pollHandle: ReturnType<typeof setInterval> | null = null;

async function loadProject(): Promise<void> {
  if (!props.projectId) return;
  try {
    project.value = await fetchProject(props.projectId);
    error.value = null;
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err);
  }
}

async function loadJobs(): Promise<void> {
  if (!props.projectId) return;
  try {
    jobs.value = await listJobs(props.projectId);
    const latestId = project.value?.active_job_id ?? project.value?.last_job_id ?? jobs.value[0]?.job_id;
    if (latestId) {
      activeJob.value = await fetchJob(latestId);
    } else {
      activeJob.value = null;
    }
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err);
  }
}

async function tick(): Promise<void> {
  if (!activeJob.value) return;
  try {
    const updated = await fetchJob(activeJob.value.job_id);
    const prev = activeJob.value;
    activeJob.value = updated;
    if (
      prev.iterations_observed !== updated.iterations_observed ||
      prev.last_iter_id !== updated.last_iter_id ||
      prev.status !== updated.status
    ) {
      emit('job-progress');
      void refreshLog();
    }
    if (['completed', 'failed', 'cancelled'].includes(updated.status)) {
      stopPolling();
      void loadProject();
    }
  } catch {
    /* network blip; keep polling */
  }
}

function startPolling(): void {
  stopPolling();
  pollHandle = setInterval(() => { void tick(); }, 1500);
}

function stopPolling(): void {
  if (pollHandle) {
    clearInterval(pollHandle);
    pollHandle = null;
  }
}

async function start(): Promise<void> {
  if (!props.projectId) return;
  starting.value = true;
  error.value = null;
  try {
    const job = await startJob(props.projectId);
    activeJob.value = job;
    jobs.value = [job, ...jobs.value];
    await loadProject();
    startPolling();
    void refreshLog();
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err);
  } finally {
    starting.value = false;
  }
}

async function doCancel(): Promise<void> {
  if (!activeJob.value) return;
  cancelling.value = true;
  try {
    await cancelJob(activeJob.value.job_id);
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err);
  } finally {
    cancelling.value = false;
  }
}

async function refreshLog(): Promise<void> {
  if (!activeJob.value) return;
  try {
    const result = await fetchJobLog(activeJob.value.job_id, 64);
    log.value = result.text;
  } catch {
    /* ignore */
  }
}

watch(() => props.projectId, async () => {
  stopPolling();
  await loadProject();
  await loadJobs();
  await refreshLog();
  if (activeJob.value && activeJob.value.status === 'running') {
    startPolling();
  }
});

onMounted(async () => {
  await loadProject();
  await loadJobs();
  await refreshLog();
  if (activeJob.value && activeJob.value.status === 'running') {
    startPolling();
  }
});

onBeforeUnmount(() => stopPolling());

const isRunning = computed(() => activeJob.value?.status === 'running' || activeJob.value?.status === 'cancelling');
const inputsReady = computed(() => {
  const inputs = project.value?.inputs;
  if (!inputs) return false;
  return !!inputs.laya_shader_path && !!inputs.laya_material_lmat_path;
});

function fmt(value: number | null): string {
  if (value == null || Number.isNaN(value)) return '—';
  return value.toFixed(4);
}

function statusColor(status: string): string {
  switch (status) {
    case 'running': return 'running';
    case 'completed': return 'ok';
    case 'failed': return 'bad';
    case 'cancelled': return 'warn';
    case 'cancelling': return 'warn';
    default: return 'muted';
  }
}

function pickIter(iterId: string | null): void {
  if (iterId) emit('open-iter', iterId);
}
</script>

<template>
  <div class="run-console">
    <header class="rc-head">
      <h2 class="section-title" style="margin: 0;">运行控制台</h2>
      <span class="muted small">驱动 fit_material.py 子进程，实时收集每轮迭代</span>
    </header>

    <div v-if="error" class="error-banner">{{ error }}</div>

    <section class="section actions">
      <button class="primary" :disabled="!inputsReady || isRunning || starting" @click="start">
        {{ starting ? '启动中…' : isRunning ? '运行中' : '开始自动调参' }}
      </button>
      <button :disabled="!isRunning || cancelling" @click="doCancel">
        {{ cancelling ? '取消中…' : '取消运行' }}
      </button>
      <button @click="loadJobs">刷新</button>
      <span v-if="!inputsReady" class="muted small">⚠ 项目配置里的必选输入还没填齐</span>
    </section>

    <section v-if="activeJob" class="section">
      <div class="job-card">
        <div class="job-head">
          <span class="mono">{{ activeJob.job_id }}</span>
          <span class="status-pill" :class="statusColor(activeJob.status)">{{ activeJob.status }}</span>
        </div>
        <div class="job-stats">
          <span class="stat-pill">iters <strong>{{ activeJob.iterations_observed }}</strong></span>
          <span v-if="activeJob.last_iter_id" class="stat-pill clickable" @click="pickIter(activeJob.last_iter_id)">
            last <strong>{{ activeJob.last_iter_id }}</strong>
          </span>
          <span v-if="activeJob.last_decision_summary?.fit_score_before != null" class="stat-pill">
            fit <strong>{{ fmt(activeJob.last_decision_summary?.fit_score_before ?? null) }}</strong>
          </span>
          <span v-if="activeJob.last_decision_summary?.diff_score_before != null" class="stat-pill">
            mae <strong>{{ fmt(activeJob.last_decision_summary?.diff_score_before ?? null) }}</strong>
          </span>
          <span v-if="activeJob.last_decision_summary?.selected_stage" class="stat-pill">
            stage <strong>{{ activeJob.last_decision_summary?.selected_stage }}</strong>
          </span>
          <span v-if="activeJob.last_decision_summary?.stop_reason" class="stat-pill">
            stop <strong>{{ activeJob.last_decision_summary?.stop_reason }}</strong>
          </span>
        </div>
        <p class="muted small" style="margin: 4px 0;">
          started {{ activeJob.started_at ?? '—' }}
          <span v-if="activeJob.ended_at"> · ended {{ activeJob.ended_at }}</span>
          <span v-if="activeJob.return_code != null"> · exit {{ activeJob.return_code }}</span>
          <span v-if="activeJob.error" class="bad"> · {{ activeJob.error }}</span>
        </p>
        <details class="cli-details">
          <summary class="muted small">展开命令行参数</summary>
          <pre class="params-pane">{{ activeJob.args.join(' ') }}</pre>
        </details>
      </div>
    </section>

    <section class="section">
      <div style="display: flex; align-items: baseline; gap: 8px;">
        <h3 class="section-title" style="margin: 0;">日志（tail 64 KB）</h3>
        <button @click="refreshLog" class="ghost">刷新日志</button>
      </div>
      <pre class="log-pane">{{ log || '(no log yet)' }}</pre>
    </section>

    <section v-if="jobs.length > 1" class="section">
      <h3 class="section-title">历史作业</h3>
      <table class="job-table">
        <thead>
          <tr>
            <th>job</th>
            <th>status</th>
            <th>started</th>
            <th>ended</th>
            <th>iters</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="j in jobs" :key="j.job_id" :class="{ active: j.job_id === activeJob?.job_id }">
            <td><span class="mono">{{ j.job_id }}</span></td>
            <td><span class="status-pill" :class="statusColor(j.status)">{{ j.status }}</span></td>
            <td class="muted small">{{ j.started_at ?? '—' }}</td>
            <td class="muted small">{{ j.ended_at ?? '—' }}</td>
            <td class="numeric mono">{{ j.iterations_observed }}</td>
          </tr>
        </tbody>
      </table>
    </section>
  </div>
</template>

<style scoped>
.run-console { display: flex; flex-direction: column; gap: 12px; padding-bottom: 24px; }
.rc-head { display: flex; align-items: baseline; gap: 12px; }
.actions { display: flex; gap: 8px; align-items: center; }
.primary { background: var(--accent-strong); border-color: var(--accent-strong); color: white; }
.primary:disabled { opacity: 0.5; }
.ghost { background: transparent; border: 1px dashed var(--border-strong); }

.job-card {
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 10px 12px;
}
.job-head { display: flex; align-items: center; gap: 10px; }
.job-head .mono { font-size: 13px; font-weight: 600; }
.job-stats { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 6px; }
.stat-pill.clickable { cursor: pointer; }
.stat-pill.clickable:hover { background: var(--bg-hover); border-color: var(--accent); }

.status-pill {
  display: inline-block;
  font-family: var(--mono);
  font-size: 11px;
  padding: 0 8px;
  border-radius: 999px;
  border: 1px solid;
}
.status-pill.running { color: var(--accent); border-color: var(--accent); animation: pulse 1.6s infinite; }
.status-pill.ok { color: var(--good); border-color: var(--good); }
.status-pill.bad { color: var(--bad); border-color: var(--bad); }
.status-pill.warn { color: var(--warn); border-color: var(--warn); }
.status-pill.muted { color: var(--text-muted); border-color: var(--border-strong); }
@keyframes pulse {
  0% { opacity: 0.6; } 50% { opacity: 1; } 100% { opacity: 0.6; }
}

.bad { color: var(--bad); }
.cli-details summary { cursor: pointer; }
.log-pane {
  background: #0d1117;
  border: 1px solid var(--border);
  color: var(--text);
  padding: 8px 12px;
  border-radius: var(--radius);
  font-family: var(--mono);
  font-size: 11px;
  white-space: pre-wrap;
  max-height: 280px;
  overflow: auto;
  line-height: 1.5;
}

.job-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.job-table th, .job-table td {
  border-bottom: 1px solid var(--border);
  padding: 4px 8px;
  text-align: left;
}
.job-table th { color: var(--text-muted); font-weight: 500; }
.job-table tr.active { background: var(--bg-hover); }
.job-table .numeric { text-align: right; font-family: var(--mono); }
</style>
