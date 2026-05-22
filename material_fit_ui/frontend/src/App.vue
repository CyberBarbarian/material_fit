<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import {
  fetchCaseOverview,
  fetchCases,
  fetchIterationDetail,
  fetchIterations,
  fetchJobIterationDetail,
  fetchJobIterations,
  fetchProject,
  listJobs,
} from './api';
import type {
  CaseOverviewPayload,
  CaseSummary,
  IterationDetail,
  JobIterationSummary,
  JobState,
  IterationSummary,
  ProjectDetail,
} from './types';
import {
  ALGO_CONFIG_VIEW_ID,
  COMPARE_VIEW_ID,
  EXPERIMENT_RESULTS_VIEW_ID,
  LLM_VIEW_ID,
  OVERVIEW_VIEW_ID,
  PREANALYSIS_VIEW_ID,
  PROJECT_CONFIG_VIEW_ID,
  REPORT_VIEW_ID,
  RUN_VIEW_ID,
  isSyntheticView,
} from './types';
import CaseSelector from './components/CaseSelector.vue';
import IterationList from './components/IterationList.vue';
import JobIterationColumn from './components/JobIterationColumn.vue';
import IterationDetailView from './components/IterationDetail.vue';
import CaseOverviewView from './components/CaseOverview.vue';
import ReportView from './components/ReportView.vue';
import IterationCompareView from './components/IterationCompareView.vue';
import ScoreCurve from './components/ScoreCurve.vue';
import NewProjectWizard from './components/NewProjectWizard.vue';
import ProjectConfigView from './components/ProjectConfigView.vue';
import PreanalysisView from './components/PreanalysisView.vue';
import AlgoConfigView from './components/AlgoConfigView.vue';
import RunConsoleView from './components/RunConsoleView.vue';
import LlmAssistView from './components/LlmAssistView.vue';

const STORAGE_KEY = 'material-fit-ui:selection';

const cases = ref<CaseSummary[]>([]);
const selectedCaseId = ref<string>('');
const overview = ref<CaseOverviewPayload | null>(null);
const project = ref<ProjectDetail | null>(null);
const iterations = ref<IterationSummary[]>([]);
const jobs = ref<JobState[]>([]);
const selectedJobId = ref<string>('');
const jobIterationsById = ref<Record<string, JobIterationSummary[]>>({});
const selectedView = ref<string>(OVERVIEW_VIEW_ID);
const iterationDetail = ref<IterationDetail | null>(null);
const isLoadingCase = ref(false);
const isLoadingIter = ref(false);
const errorMessage = ref<string | null>(null);
const wizardOpen = ref(false);

interface Persisted { case?: string; view?: string; job?: string; }

let suppressViewWatch = false;
let detailRequestId = 0;
let projectPollHandle: ReturnType<typeof setInterval> | null = null;

function loadPersisted(): Persisted {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return {};
    const data = JSON.parse(raw);
    if (data && typeof data === 'object') return data as Persisted;
  } catch { /* ignore */ }
  return {};
}

function persist(): void {
  try {
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ case: selectedCaseId.value, view: selectedView.value, job: selectedJobId.value }),
    );
  } catch { /* ignore */ }
}

function isValidView(view: string, iters: IterationSummary[]): boolean {
  if (isSyntheticView(view)) return true;
  return iters.some((entry) => entry.iter_id === view);
}

function isLightweightProjectStartupView(view: string): boolean {
  if (!isSyntheticView(view)) return false;
  return view !== COMPARE_VIEW_ID;
}

function latestJobId(list: JobState[]): string {
  return list[0]?.job_id ?? '';
}

async function loadProjectJobs(projectId: string, preferredJobId = selectedJobId.value): Promise<IterationSummary[]> {
  const list = await listJobs(projectId);
  jobs.value = list;
  const persisted = loadPersisted();
  const nextJob =
    (preferredJobId && list.some((job) => job.job_id === preferredJobId) && preferredJobId) ||
    (persisted.case === projectId && persisted.job && list.some((job) => job.job_id === persisted.job) && persisted.job) ||
    project.value?.active_job_id ||
    project.value?.last_job_id ||
    latestJobId(list);
  selectedJobId.value = nextJob || '';
  if (!selectedJobId.value) {
    jobIterationsById.value = {};
    return [];
  }
  const jobIters = await fetchJobIterations(selectedJobId.value);
  jobIterationsById.value = { ...jobIterationsById.value, [selectedJobId.value]: jobIters };
  return jobIters;
}

const currentCase = computed<CaseSummary | null>(
  () => cases.value.find((c) => c.id === selectedCaseId.value) ?? null,
);
const isProjectCase = computed(() => currentCase.value?.kind === 'project');

async function loadCases(): Promise<void> {
  errorMessage.value = null;
  try {
    const list = await fetchCases();
    cases.value = list;
    if (!list.length) {
      selectedCaseId.value = '';
      return;
    }
    const persisted = loadPersisted();
    const persistedCaseValid =
      persisted.case && list.some((entry) => entry.id === persisted.case);
    if (persistedCaseValid && persisted.case) {
      selectedCaseId.value = persisted.case;
    } else if (!selectedCaseId.value) {
      const project = list.find((entry) => entry.kind === 'project');
      const auto = list.find((entry) => entry.kind === 'auto_adjust');
      selectedCaseId.value = (project ?? auto ?? list[0]).id;
    }
  } catch (err) {
    errorMessage.value = formatError(err);
  }
}

async function loadCaseDetails(caseId: string): Promise<void> {
  if (!caseId) {
    overview.value = null;
    project.value = null;
    iterations.value = [];
    suppressViewWatch = true;
    selectedView.value = OVERVIEW_VIEW_ID;
    iterationDetail.value = null;
    return;
  }
  isLoadingCase.value = true;
  errorMessage.value = null;
  try {
    const summary = cases.value.find((c) => c.id === caseId);
    const isProject = summary?.kind === 'project';

    const [ov, legacyIters, proj] = await Promise.all([
      fetchCaseOverview(caseId),
      isProject ? Promise.resolve([] as IterationSummary[]) : fetchIterations(caseId),
      isProject ? fetchProject(caseId) : Promise.resolve(null as ProjectDetail | null),
    ]);
    overview.value = ov;
    project.value = proj;
    iterations.value = isProject ? await loadProjectJobs(caseId) : legacyIters;

    const persisted = loadPersisted();
    let nextView: string = OVERVIEW_VIEW_ID;
    if (
      persisted.case === caseId &&
      persisted.view &&
      isValidView(persisted.view, iterations.value) &&
      (!isProject || isLightweightProjectStartupView(persisted.view))
    ) {
      nextView = persisted.view;
    } else if (isProject) {
      nextView = proj?.active_job_id ? RUN_VIEW_ID : PROJECT_CONFIG_VIEW_ID;
    } else if (iterations.value.length > 0) {
      nextView = iterations.value[iterations.value.length - 1].iter_id;
    }

    suppressViewWatch = true;
    selectedView.value = nextView;
    persist();
    await refreshIterationDetail(caseId, nextView);
    schedulePolling();
  } catch (err) {
    overview.value = null;
    project.value = null;
    iterations.value = [];
    suppressViewWatch = true;
    selectedView.value = OVERVIEW_VIEW_ID;
    iterationDetail.value = null;
    errorMessage.value = formatError(err);
  } finally {
    isLoadingCase.value = false;
  }
}

async function refreshIterationDetail(caseId: string, view: string): Promise<void> {
  const myReq = ++detailRequestId;
  if (!caseId || !view || isSyntheticView(view)) {
    iterationDetail.value = null;
    return;
  }
  isLoadingIter.value = true;
  try {
    const result = isProjectCase.value && selectedJobId.value
      ? await fetchJobIterationDetail(selectedJobId.value, view)
      : await fetchIterationDetail(caseId, view);
    if (myReq !== detailRequestId) return;
    iterationDetail.value = result;
  } catch (err) {
    if (myReq !== detailRequestId) return;
    iterationDetail.value = null;
    errorMessage.value = formatError(err);
  } finally {
    if (myReq === detailRequestId) isLoadingIter.value = false;
  }
}

const isJobRunning = computed(
  () => !!project.value?.active_job_id,
);

function schedulePolling(): void {
  stopPolling();
  if (!isJobRunning.value) return;
  projectPollHandle = setInterval(async () => {
    if (!selectedCaseId.value) return;
    try {
      const proj = await fetchProject(selectedCaseId.value).catch(() => null);
      if (proj) project.value = proj;
      if (isProjectCase.value) {
        iterations.value = await loadProjectJobs(selectedCaseId.value);
      } else {
        iterations.value = await fetchIterations(selectedCaseId.value);
      }
      if (proj && !proj.active_job_id) {
        stopPolling();
      }
    } catch { /* keep polling */ }
  }, 1500);
}

function stopPolling(): void {
  if (projectPollHandle) {
    clearInterval(projectPollHandle);
    projectPollHandle = null;
  }
}

function formatError(err: unknown): string {
  if (err instanceof Error) return err.message;
  return String(err);
}

const headerStats = computed(() => {
  const stats: Array<{ label: string; value: string }> = [];
  if (!overview.value) return stats;
  stats.push({ label: 'iters', value: String(overview.value.iterations_count) });
  if (overview.value.kind === 'project' && project.value) {
    if (project.value.active_job_id) {
      stats.push({ label: 'job', value: 'running' });
    } else if (project.value.last_job_id) {
      stats.push({ label: 'last job', value: project.value.last_job_id });
    }
  }
  const auto = overview.value.auto_adjust_result;
  if (auto?.status) stats.push({ label: 'status', value: auto.status });
  if (auto && typeof auto.target_score === 'number') {
    stats.push({ label: 'target', value: auto.target_score.toFixed(3) });
  }
  if (auto && typeof auto.best_fit_score === 'number') {
    stats.push({ label: 'best fit', value: auto.best_fit_score.toFixed(4) });
  }
  if (auto && typeof auto.best_score === 'number') {
    stats.push({ label: 'best mae', value: auto.best_score.toFixed(4) });
  }
  if (overview.value.kind === 'diff_only' && typeof overview.value.root_diff_score === 'number') {
    stats.push({ label: 'RGB MAE', value: overview.value.root_diff_score.toFixed(4) });
  }
  return stats;
});

const view = computed(() => selectedView.value);
const showOverview = computed(() => view.value === OVERVIEW_VIEW_ID);
const showReport = computed(() => view.value === REPORT_VIEW_ID);
const showCompare = computed(() => view.value === COMPARE_VIEW_ID);
const showProjectConfig = computed(() => view.value === PROJECT_CONFIG_VIEW_ID);
const showPreanalysis = computed(() => view.value === PREANALYSIS_VIEW_ID);
const showAlgoConfig = computed(() => view.value === ALGO_CONFIG_VIEW_ID);
const showRun = computed(() => view.value === RUN_VIEW_ID);
const showLlm = computed(() => view.value === LLM_VIEW_ID);
const showIteration = computed(() => !isSyntheticView(view.value));
const showExperimentResults = computed(() => isProjectCase.value && (view.value === EXPERIMENT_RESULTS_VIEW_ID || showIteration.value));
const showResultColumns = computed(() => showExperimentResults.value);

const hasReport = computed(() => overview.value?.has_report ?? false);
const showScoreCurve = computed(() => iterations.value.some((entry) => entry.fit_score_before != null));
const projectNavItems = computed(() => {
  const items = [
    { id: OVERVIEW_VIEW_ID, label: '概览', meta: 'metadata' },
    { id: EXPERIMENT_RESULTS_VIEW_ID, label: '实验结果', meta: `${jobs.value.length} jobs / ${iterations.value.length} iters` },
    { id: PROJECT_CONFIG_VIEW_ID, label: '项目配置', meta: 'inputs' },
    { id: PREANALYSIS_VIEW_ID, label: '预分析', meta: 'shader diff' },
    { id: ALGO_CONFIG_VIEW_ID, label: '算法配置', meta: 'target / iter' },
    { id: RUN_VIEW_ID, label: '运行控制台', meta: isJobRunning.value ? 'running' : 'start / cancel' },
    { id: LLM_VIEW_ID, label: 'LLM 助手', meta: '骨架' },
  ];
  if (hasReport.value) {
    items.push({ id: REPORT_VIEW_ID, label: '报告', meta: 'report.md' });
  }
  if (iterations.value.length >= 2 || jobs.value.length >= 2) {
    items.push({ id: COMPARE_VIEW_ID, label: '迭代对比', meta: 'job + iter' });
  }
  return items;
});

function isProjectNavActive(id: string): boolean {
  if (id === EXPERIMENT_RESULTS_VIEW_ID) return showExperimentResults.value;
  return selectedView.value === id;
}

function selectProjectNav(id: string): void {
  if (id === EXPERIMENT_RESULTS_VIEW_ID) {
    const currentIterValid = !isSyntheticView(selectedView.value) && iterations.value.some((entry) => entry.iter_id === selectedView.value);
    selectedView.value = currentIterValid
      ? selectedView.value
      : (iterations.value[0]?.iter_id ?? EXPERIMENT_RESULTS_VIEW_ID);
    return;
  }
  selectedView.value = id;
}

watch(selectedCaseId, (caseId, oldId) => {
  if (caseId === oldId) return;
  detailRequestId += 1;
  iterationDetail.value = null;
  suppressViewWatch = true;
  selectedView.value = OVERVIEW_VIEW_ID;
  stopPolling();
  void loadCaseDetails(caseId);
  persist();
});

watch(selectedView, (view) => {
  if (suppressViewWatch) {
    suppressViewWatch = false;
    return;
  }
  void refreshIterationDetail(selectedCaseId.value, view);
  persist();
});

watch(isJobRunning, (running) => {
  if (running) schedulePolling();
  else stopPolling();
});

onMounted(() => {
  void loadCases();
});

function reload(): void {
  void (async () => {
    const before = selectedCaseId.value;
    await loadCases();
    if (selectedCaseId.value && selectedCaseId.value === before) {
      await loadCaseDetails(selectedCaseId.value);
    }
  })();
}

async function onProjectCreated(projectId: string): Promise<void> {
  wizardOpen.value = false;
  await loadCases();
  selectedCaseId.value = projectId;
  await loadCaseDetails(projectId);
  selectedView.value = PROJECT_CONFIG_VIEW_ID;
}

async function onProjectChanged(): Promise<void> {
  await loadCases();
  if (selectedCaseId.value) {
    try {
      project.value = await fetchProject(selectedCaseId.value);
      if (isProjectCase.value) {
        iterations.value = await loadProjectJobs(selectedCaseId.value);
      }
    } catch { /* ignore */ }
  }
}

async function onProjectDeleted(): Promise<void> {
  selectedCaseId.value = '';
  await loadCases();
  if (cases.value.length) {
    selectedCaseId.value = cases.value[0].id;
  }
}

async function onJobProgress(): Promise<void> {
  if (!selectedCaseId.value) return;
  try {
    project.value = await fetchProject(selectedCaseId.value);
    iterations.value = isProjectCase.value
      ? await loadProjectJobs(selectedCaseId.value)
      : await fetchIterations(selectedCaseId.value);
  } catch { /* ignore */ }
}

function onOpenIter(iterId: string): void {
  selectedView.value = iterId;
}

async function onSelectJob(jobId: string): Promise<void> {
  if (!jobId || jobId === selectedJobId.value) return;
  selectedJobId.value = jobId;
  try {
    const jobIters = await fetchJobIterations(jobId);
    jobIterationsById.value = { ...jobIterationsById.value, [jobId]: jobIters };
    iterations.value = jobIters;
    if (!isSyntheticView(selectedView.value) && !isValidView(selectedView.value, jobIters)) {
      selectedView.value = EXPERIMENT_RESULTS_VIEW_ID;
    } else if (!isSyntheticView(selectedView.value)) {
      await refreshIterationDetail(selectedCaseId.value, selectedView.value);
    }
    persist();
  } catch (err) {
    errorMessage.value = formatError(err);
  }
}
</script>

<template>
  <div class="app-shell">
    <header class="app-header">
      <h1>Material Fit Inspector <span class="muted small">stage B · projects</span></h1>
      <CaseSelector v-model="selectedCaseId" :cases="cases" />
      <button class="primary" @click="wizardOpen = true">+ 新建项目</button>
      <button @click="reload" :disabled="isLoadingCase">刷新</button>
      <div class="header-stats">
        <span v-for="stat in headerStats" :key="stat.label" class="stat-pill">
          {{ stat.label }} <strong>{{ stat.value }}</strong>
        </span>
      </div>
    </header>

    <div v-if="errorMessage" class="error-banner" style="margin: 8px 16px 0;">
      {{ errorMessage }}
      <button class="dismiss-btn" @click="errorMessage = null" aria-label="dismiss">×</button>
    </div>

    <nav v-if="isProjectCase" class="project-view-tabs">
      <button
        v-for="item in projectNavItems"
        :key="item.id"
        type="button"
        class="project-view-tab"
        :class="{ 'is-active': isProjectNavActive(item.id) }"
        @click="selectProjectNav(item.id)"
      >
        <span>{{ item.label }}</span>
        <small>{{ item.meta }}</small>
      </button>
    </nav>

    <div
      class="app-body"
      :class="{
        'is-project-results-layout': showResultColumns,
        'is-project-full-layout': isProjectCase && !showResultColumns,
      }"
    >
      <aside v-if="!isProjectCase || showResultColumns" class="iter-panel job-panel">
        <div class="iter-panel-header">
          {{ isProjectCase ? '实验 jobs' : '视图' }}
          <span class="muted">
            ({{ isProjectCase ? `${jobs.length} jobs` : `${iterations.length} 迭代` }})
          </span>
        </div>
        <IterationList
          v-model="selectedView"
          :iterations="iterations"
          :has-report="hasReport"
          :is-project="isProjectCase"
          :job-is-running="isJobRunning"
          :jobs="jobs"
          :selected-job-id="selectedJobId"
          @update:selected-job-id="onSelectJob"
        />
      </aside>
      <aside v-if="showResultColumns" class="iter-panel round-panel">
        <div class="iter-panel-header">
          当前 job 迭代
          <span class="muted">({{ iterations.length }} 轮)</span>
        </div>
        <JobIterationColumn
          v-model="selectedView"
          :iterations="iterations"
          :selected-job-id="selectedJobId"
        />
      </aside>
      <main class="main-pane">
        <CaseOverviewView v-if="showOverview" :overview="overview" />
        <ProjectConfigView
          v-else-if="showProjectConfig && selectedCaseId"
          :project-id="selectedCaseId"
          @changed="onProjectChanged"
          @deleted="onProjectDeleted"
        />
        <PreanalysisView
          v-else-if="showPreanalysis && selectedCaseId"
          :project-id="selectedCaseId"
        />
        <AlgoConfigView
          v-else-if="showAlgoConfig && selectedCaseId"
          :project-id="selectedCaseId"
          @changed="onProjectChanged"
        />
        <RunConsoleView
          v-else-if="showRun && selectedCaseId"
          :project-id="selectedCaseId"
          @job-progress="onJobProgress"
          @open-iter="onOpenIter"
        />
        <LlmAssistView v-else-if="showLlm && selectedCaseId" :project-id="selectedCaseId" />
        <ReportView v-else-if="showReport && selectedCaseId" :case-id="selectedCaseId" />
        <IterationCompareView
          v-else-if="showCompare && selectedCaseId"
          :case-id="selectedCaseId"
          :iterations="iterations"
          :jobs="jobs"
          :job-iterations-by-id="jobIterationsById"
        />
        <IterationDetailView
          v-else-if="showIteration && iterationDetail"
          :detail="iterationDetail"
        />
        <div v-else-if="showExperimentResults" class="empty-state">
          请选择左侧 job 和迭代轮查看实验结果。
        </div>
        <div v-else-if="isLoadingIter" class="empty-state">加载中…</div>
        <div v-else-if="!selectedCaseId" class="empty-state">
          还没有项目。点右上角 <span class="kbd">+ 新建项目</span> 开始一个 Unity → Laya 调参任务。
        </div>
        <div v-else class="empty-state">请从左侧选择一个视图。</div>
      </main>
    </div>

    <ScoreCurve
      v-if="showScoreCurve"
      :iterations="iterations"
      :selected-iter-id="selectedView"
      @select="selectedView = $event"
    />

    <NewProjectWizard
      :open="wizardOpen"
      @close="wizardOpen = false"
      @created="onProjectCreated"
    />
  </div>
</template>

<style scoped>
.app-header .primary {
  background: var(--accent-strong);
  border-color: var(--accent-strong);
  color: white;
}
.app-body.is-project-results-layout {
  grid-template-columns: 220px 300px minmax(0, 1fr);
}
.app-body.is-project-full-layout {
  grid-template-columns: minmax(0, 1fr);
}
.round-panel {
  background: #101720;
}
.project-view-tabs {
  flex: 0 0 auto;
  display: flex;
  gap: 8px;
  flex-wrap: nowrap;
  align-items: stretch;
  overflow-x: auto;
  padding: 10px 16px;
  background: var(--bg);
  border-bottom: 1px solid var(--border);
}
.project-view-tab {
  flex: 0 0 104px;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  justify-content: center;
  min-width: 104px;
  height: 58px;
  max-height: 58px;
  gap: 1px;
  padding: 7px 10px;
  background: var(--bg-panel);
  overflow: hidden;
}
.project-view-tab.is-active {
  border-color: var(--accent);
  color: var(--accent);
  background: rgba(88, 166, 255, 0.08);
}
.project-view-tab small {
  color: var(--text-muted);
  font-size: 10px;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.dismiss-btn {
  margin-left: 8px;
  background: transparent;
  border: none;
  color: inherit;
  font-size: 16px;
  cursor: pointer;
  padding: 0 4px;
}
</style>
