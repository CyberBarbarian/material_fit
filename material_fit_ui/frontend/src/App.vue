<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import {
  fetchCaseOverview,
  fetchCases,
  fetchIterationDetail,
  fetchIterations,
  fetchProject,
} from './api';
import type {
  CaseOverviewPayload,
  CaseSummary,
  IterationDetail,
  IterationSummary,
  ProjectDetail,
} from './types';
import {
  ALGO_CONFIG_VIEW_ID,
  COMPARE_VIEW_ID,
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
const selectedView = ref<string>(OVERVIEW_VIEW_ID);
const iterationDetail = ref<IterationDetail | null>(null);
const isLoadingCase = ref(false);
const isLoadingIter = ref(false);
const errorMessage = ref<string | null>(null);
const wizardOpen = ref(false);

interface Persisted { case?: string; view?: string; }

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
      JSON.stringify({ case: selectedCaseId.value, view: selectedView.value }),
    );
  } catch { /* ignore */ }
}

function isValidView(view: string, iters: IterationSummary[]): boolean {
  if (isSyntheticView(view)) return true;
  return iters.some((entry) => entry.iter_id === view);
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

    const [ov, iters, proj] = await Promise.all([
      fetchCaseOverview(caseId),
      fetchIterations(caseId),
      isProject ? fetchProject(caseId) : Promise.resolve(null as ProjectDetail | null),
    ]);
    overview.value = ov;
    iterations.value = iters;
    project.value = proj;

    const persisted = loadPersisted();
    let nextView: string = OVERVIEW_VIEW_ID;
    if (
      persisted.case === caseId &&
      persisted.view &&
      isValidView(persisted.view, iters)
    ) {
      nextView = persisted.view;
    } else if (isProject) {
      nextView = PROJECT_CONFIG_VIEW_ID;
    } else if (iters.length > 0) {
      nextView = iters[iters.length - 1].iter_id;
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
    const result = await fetchIterationDetail(caseId, view);
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
      const [iters, proj] = await Promise.all([
        fetchIterations(selectedCaseId.value),
        fetchProject(selectedCaseId.value).catch(() => null),
      ]);
      if (iters.length !== iterations.value.length) {
        iterations.value = iters;
      } else {
        iterations.value = iters;
      }
      if (proj) {
        project.value = proj;
        if (!proj.active_job_id) {
          stopPolling();
        }
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

const hasReport = computed(() => overview.value?.has_report ?? false);
const showScoreCurve = computed(() => iterations.value.some((entry) => entry.fit_score_before != null));

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
    iterations.value = await fetchIterations(selectedCaseId.value);
    project.value = await fetchProject(selectedCaseId.value);
  } catch { /* ignore */ }
}

function onOpenIter(iterId: string): void {
  selectedView.value = iterId;
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

    <div class="app-body">
      <aside class="iter-panel">
        <div class="iter-panel-header">
          视图 <span class="muted">({{ iterations.length }} 迭代)</span>
        </div>
        <IterationList
          v-model="selectedView"
          :iterations="iterations"
          :has-report="hasReport"
          :is-project="isProjectCase"
          :job-is-running="isJobRunning"
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
        />
        <IterationDetailView
          v-else-if="showIteration && iterationDetail"
          :detail="iterationDetail"
        />
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
