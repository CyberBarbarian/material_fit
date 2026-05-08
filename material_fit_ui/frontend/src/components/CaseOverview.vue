<script setup lang="ts">
import { computed, ref } from 'vue';
import type { CaseOverviewPayload } from '../types';

const props = defineProps<{ overview: CaseOverviewPayload | null }>();

type SectionKey = 'meta' | 'auto' | 'stages' | 'policies' | 'initial' | 'shader';
const open = ref<Record<SectionKey, boolean>>({
  meta: true,
  auto: true,
  stages: true,
  policies: true,
  initial: false,
  shader: false,
});

function toggle(key: SectionKey): void {
  open.value[key] = !open.value[key];
}

const stages = computed(() => props.overview?.stage_plan ?? []);
const policies = computed(() => props.overview?.adjustment_policies ?? []);

const initialParamsJson = computed(() => {
  if (!props.overview?.initial_params) return '';
  return JSON.stringify(props.overview.initial_params, null, 2);
});

const layaShaderName = computed(() => props.overview?.laya_shader_params?.name ?? '');
const layaShaderParamCount = computed(() => props.overview?.laya_shader_params?.params?.length ?? 0);
const layaShaderDefineCount = computed(() => props.overview?.laya_shader_params?.defines?.length ?? 0);
const unityShaderName = computed(() => props.overview?.unity_shader_params?.name ?? '');

const auto = computed(() => props.overview?.auto_adjust_result ?? null);

function fmt(value: unknown, digits = 4): string {
  if (typeof value !== 'number' || Number.isNaN(value)) return '—';
  return value.toFixed(digits);
}
</script>

<template>
  <div v-if="!overview" class="muted small">未选中 case。</div>
  <div v-else class="case-overview">
    <section class="ov-section">
      <div class="ov-section-head" @click="toggle('meta')">
        <span class="ov-caret" :class="{ 'is-open': open.meta }">▸</span>
        <span class="ov-section-title">case 元数据</span>
        <span class="kind-badge" :class="`kind-${overview.kind}`">{{ overview.kind_label }}</span>
      </div>
      <div v-if="open.meta" class="ov-section-body">
        <div class="meta-grid">
          <div><span class="muted small">id</span><span class="mono">{{ overview.id }}</span></div>
          <div><span class="muted small">output_dir</span><span class="mono small">{{ overview.output_dir }}</span></div>
          <div><span class="muted small">最后修改</span><span class="mono small">{{ overview.last_modified ?? '—' }}</span></div>
          <div><span class="muted small">summary</span><span>{{ overview.summary || '—' }}</span></div>
          <div v-if="layaShaderName">
            <span class="muted small">Laya shader</span>
            <span class="mono small">{{ layaShaderName }}<span class="muted"> ({{ layaShaderParamCount }} params · {{ layaShaderDefineCount }} defines)</span></span>
          </div>
          <div v-if="unityShaderName">
            <span class="muted small">Unity shader</span>
            <span class="mono small">{{ unityShaderName }}</span>
          </div>
        </div>
      </div>
    </section>

    <section v-if="auto" class="ov-section">
      <div class="ov-section-head" @click="toggle('auto')">
        <span class="ov-caret" :class="{ 'is-open': open.auto }">▸</span>
        <span class="ov-section-title">auto-adjust 结果</span>
        <span class="muted small">status {{ auto.status ?? '—' }}</span>
      </div>
      <div v-if="open.auto" class="ov-section-body">
        <div class="meta-grid">
          <div><span class="muted small">target fit</span><span class="mono">{{ fmt(auto.target_score, 3) }}</span></div>
          <div><span class="muted small">best fit</span><span class="mono">{{ fmt(auto.best_fit_score) }}</span></div>
          <div><span class="muted small">best RGB MAE</span><span class="mono">{{ fmt(auto.best_score) }}</span></div>
          <div v-if="auto.state_path"><span class="muted small">state</span><span class="mono small">{{ auto.state_path }}</span></div>
        </div>
        <p class="muted small" style="margin-top: 6px;">
          阈值条件：fit_score ≥ target 即停止。当前算法用 RGB MAE 作主指标，与材质语义通道分离。
        </p>
      </div>
    </section>

    <section v-if="stages.length" class="ov-section">
      <div class="ov-section-head" @click="toggle('stages')">
        <span class="ov-caret" :class="{ 'is-open': open.stages }">▸</span>
        <span class="ov-section-title">stage plan</span>
        <span class="muted small">({{ stages.length }} 阶段)</span>
      </div>
      <div v-if="open.stages" class="ov-section-body">
        <ol class="stage-list">
          <li v-for="stage in stages" :key="stage.name">
            <div class="stage-head">
              <span class="mono">{{ stage.name }}</span>
              <span class="muted small">{{ stage.params.length }} params</span>
            </div>
            <p v-if="stage.description" class="muted small" style="margin: 2px 0 4px;">{{ stage.description }}</p>
            <code class="param-list">{{ stage.params.join(', ') || '—' }}</code>
          </li>
        </ol>
      </div>
    </section>

    <section v-if="policies.length" class="ov-section">
      <div class="ov-section-head" @click="toggle('policies')">
        <span class="ov-caret" :class="{ 'is-open': open.policies }">▸</span>
        <span class="ov-section-title">adjustment policies</span>
        <span class="muted small">({{ policies.length }})</span>
      </div>
      <div v-if="open.policies" class="ov-section-body">
        <table class="policy-table">
          <thead>
            <tr>
              <th>name</th>
              <th>channels</th>
              <th>params</th>
              <th class="numeric">target</th>
              <th class="numeric">max iters</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="policy in policies" :key="policy.name">
              <td><span class="mono">{{ policy.name }}</span></td>
              <td class="muted small">{{ policy.channels.join(', ') }}</td>
              <td class="muted small">{{ policy.params.length }} 个</td>
              <td class="numeric mono">{{ policy.target_score.toFixed(3) }}</td>
              <td class="numeric mono">{{ policy.max_iterations }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <section v-if="initialParamsJson" class="ov-section">
      <div class="ov-section-head" @click="toggle('initial')">
        <span class="ov-caret" :class="{ 'is-open': open.initial }">▸</span>
        <span class="ov-section-title">initial params</span>
        <span class="muted small">{{ Object.keys(overview.initial_params ?? {}).length }} 个</span>
      </div>
      <pre v-if="open.initial" class="params-pane">{{ initialParamsJson }}</pre>
    </section>

    <section v-if="overview.kind === 'empty'" class="ov-section ov-empty">
      <p>
        这个目录没有可视化产物（无 auto_adjust、无探针候选、无 diff_analysis）。
      </p>
      <p class="muted small">
        可以直接用资源管理器删除：<span class="mono">{{ overview.output_dir }}</span>
      </p>
    </section>
  </div>
</template>

<style scoped>
.case-overview { display: flex; flex-direction: column; gap: 12px; padding-bottom: 16px; }
.ov-section {
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  overflow: hidden;
}
.ov-section-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  cursor: pointer;
  user-select: none;
  background: var(--bg-elevated);
  border-bottom: 1px solid var(--border);
}
.ov-section-head:hover { background: var(--bg-hover); }
.ov-section-title { font-weight: 600; }
.ov-caret { color: var(--text-dim); transition: transform 0.15s; }
.ov-caret.is-open { transform: rotate(90deg); }
.ov-section-body { padding: 10px 12px; }
.ov-empty { padding: 12px; }

.meta-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 8px 16px;
}
.meta-grid > div { display: flex; flex-direction: column; gap: 1px; min-width: 0; }
.meta-grid > div span:first-child { font-size: 10px; text-transform: uppercase; letter-spacing: 0.4px; }
.mono { font-family: var(--mono); }

.stage-list { margin: 0; padding-left: 22px; }
.stage-list li + li { margin-top: 6px; }
.stage-head { display: flex; gap: 8px; align-items: baseline; }
.param-list {
  display: block;
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 4px 8px;
  font-size: 11px;
  font-family: var(--mono);
  color: var(--text-muted);
}

.policy-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.policy-table th, .policy-table td {
  border-bottom: 1px solid var(--border);
  padding: 4px 8px;
  text-align: left;
}
.policy-table th { color: var(--text-muted); font-weight: 500; }
.policy-table .numeric { text-align: right; }

.kind-badge {
  display: inline-block;
  font-family: var(--mono);
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 999px;
  border: 1px solid currentColor;
  text-transform: lowercase;
}
.kind-auto_adjust { color: var(--good); }
.kind-probe { color: var(--accent); }
.kind-diff_only { color: var(--warn); }
.kind-empty { color: var(--text-dim); }
</style>
