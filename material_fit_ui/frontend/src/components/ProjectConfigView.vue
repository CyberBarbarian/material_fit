<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import {
  deleteProject,
  externalPreviewUrl,
  fetchProject,
  patchProject,
  pickFile,
  pickRegion,
} from '../api';
import type { CaptureRegion, LayaCaptureAnchor, LayaWindowConfig, ProjectDetail, ProjectInputs } from '../types';
import RefreshPreflightCard from './RefreshPreflightCard.vue';

const defaultLayaWindow: LayaWindowConfig = {
  process_pattern: 'LayaAirIDE',
  title_pattern: '',
  settle_ms: 250,
};

const props = defineProps<{ projectId: string }>();
const emit = defineEmits<{
  (e: 'changed'): void;
  (e: 'deleted'): void;
}>();

const project = ref<ProjectDetail | null>(null);
const error = ref<string | null>(null);
const saving = ref(false);
const pickingRegion = ref(false);

interface Slot {
  key: keyof ProjectInputs;
  label: string;
  hint: string;
  required: boolean;
  filetypes: [string, string][];
  image?: boolean;
  isDir?: boolean;
}

const slots: Slot[] = [
  {
    key: 'laya_shader_path',
    label: 'Laya 着色器',
    hint: '.shader / .vs / .fs',
    required: true,
    filetypes: [['Laya shader', '*.shader *.vs *.fs'], ['All files', '*.*']],
  },
  {
    key: 'laya_material_lmat_path',
    label: 'Laya .lmat 写入目标',
    hint: '调参会写入此文件（自动备份 .bak）',
    required: true,
    filetypes: [['Laya material', '*.lmat'], ['All files', '*.*']],
  },
  {
    key: 'unity_shader_path',
    label: 'Unity 着色器',
    hint: 'Unity ShaderLab .shader',
    required: false,
    filetypes: [['Unity shader', '*.shader'], ['All files', '*.*']],
  },
  {
    key: 'unity_material_params_path',
    label: 'Unity 材质参数 JSON',
    hint: 'Editor 工具导出的实际参数',
    required: false,
    filetypes: [['JSON', '*.json'], ['All files', '*.*']],
  },
  {
    key: 'unity_reference_image_path',
    label: 'Unity 参考图',
    hint: '同视角同光照下的 Unity PNG',
    required: false,
    image: true,
    filetypes: [['PNG image', '*.png *.jpg *.jpeg *.bmp'], ['All files', '*.*']],
  },
  {
    key: 'laya_capture_dir',
    label: 'Laya 截图保存目录',
    hint: '默认 tools/material_fit/vision/test_image',
    required: false,
    filetypes: [],
    isDir: true,
  },
];

async function load(): Promise<void> {
  if (!props.projectId) return;
  try {
    const data = await fetchProject(props.projectId);
    project.value = data;
    error.value = null;
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err);
  }
}

watch(() => props.projectId, () => { void load(); });
onMounted(() => { void load(); });

async function pickSlot(slot: Slot): Promise<void> {
  if (!project.value) return;
  try {
    const result = await pickFile({
      mode: slot.isDir ? 'directory' : 'open',
      title: slot.label,
      initial_dir: slotInitialDir(slot.key),
      filetypes: slot.isDir ? undefined : slot.filetypes,
    });
    if (result.error) { error.value = result.error; return; }
    if (!result.path) return;
    await save({ inputs: { [slot.key]: result.path } });
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err);
  }
}

async function clearSlot(key: keyof ProjectInputs): Promise<void> {
  await save({ inputs: { [key]: null } });
}

async function pickRegionOnScreen(): Promise<void> {
  pickingRegion.value = true;
  error.value = null;
  try {
    const window = layaWindow.value;
    const result = await pickRegion({
      laya_window: {
        process_pattern: window.process_pattern,
        title_pattern: window.title_pattern,
      },
    });
    if (result.error) {
      error.value = result.error;
      return;
    }
    if (result.region) {
      const inputsPatch: Record<string, unknown> = {
        laya_capture_region: result.region as CaptureRegion,
      };
      // If the backend was able to find the Laya window at pick time
      // it already computed (offset_x, offset_y, width, height) — save
      // them so future captures survive Laya window drags. If it
      // couldn't (laya_window pattern stale), keep the user's existing
      // anchor and surface the error so they can fix the pattern.
      if (result.anchor) {
        inputsPatch.laya_capture_anchor = {
          enabled: project.value?.inputs.laya_capture_anchor?.enabled ?? true,
          offset_x: result.anchor.offset_x,
          offset_y: result.anchor.offset_y,
          width: result.anchor.width,
          height: result.anchor.height,
        };
      } else if (result.anchor_error) {
        error.value = result.anchor_error;
      }
      await save({ inputs: inputsPatch });
    }
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err);
  } finally {
    pickingRegion.value = false;
  }
}

const captureAnchor = computed<LayaCaptureAnchor>(() => {
  const fromProject = project.value?.inputs?.laya_capture_anchor;
  if (fromProject && typeof fromProject === 'object') {
    return {
      enabled: fromProject.enabled ?? true,
      offset_x: fromProject.offset_x ?? 0,
      offset_y: fromProject.offset_y ?? 0,
      width: fromProject.width ?? 0,
      height: fromProject.height ?? 0,
    };
  }
  return { enabled: true, offset_x: 0, offset_y: 0, width: 0, height: 0 };
});

const anchorReady = computed(() => captureAnchor.value.width > 0 && captureAnchor.value.height > 0);

async function toggleAnchor(): Promise<void> {
  await save({
    inputs: {
      laya_capture_anchor: {
        ...captureAnchor.value,
        enabled: !captureAnchor.value.enabled,
      },
    },
  });
}

async function clearRegion(): Promise<void> {
  await save({ inputs: { laya_capture_region: null } });
}

const layaWindow = computed<LayaWindowConfig>(() => {
  const fromProject = project.value?.inputs?.laya_window;
  if (fromProject && typeof fromProject === 'object') {
    return {
      process_pattern: fromProject.process_pattern ?? defaultLayaWindow.process_pattern,
      title_pattern: fromProject.title_pattern ?? defaultLayaWindow.title_pattern,
      settle_ms: typeof fromProject.settle_ms === 'number' ? fromProject.settle_ms : defaultLayaWindow.settle_ms,
    };
  }
  return { ...defaultLayaWindow };
});

async function saveLayaWindow(patch: Partial<LayaWindowConfig>): Promise<void> {
  const merged: LayaWindowConfig = { ...layaWindow.value, ...patch };
  await save({ inputs: { laya_window: merged } });
}

async function save(patch: Record<string, unknown>): Promise<void> {
  if (!project.value) return;
  saving.value = true;
  try {
    project.value = await patchProject(project.value.id, patch);
    emit('changed');
    error.value = null;
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err);
  } finally {
    saving.value = false;
  }
}

async function onDelete(): Promise<void> {
  if (!project.value) return;
  if (!confirm(`确认删除项目 "${project.value.id}"？该目录会被移动到 output/.trash/`)) return;
  try {
    await deleteProject(project.value.id);
    emit('deleted');
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err);
  }
}

function slotInitialDir(key: keyof ProjectInputs): string | undefined {
  const value = project.value?.inputs[key];
  if (typeof value === 'string' && value) {
    const idx = Math.max(value.lastIndexOf('/'), value.lastIndexOf('\\'));
    return idx > 0 ? value.slice(0, idx) : undefined;
  }
  return undefined;
}

const requiredFilled = computed(
  () => !!project.value?.inputs.laya_shader_path && !!project.value?.inputs.laya_material_lmat_path,
);

function shorten(value: string | null | undefined): string {
  if (!value) return '未选择';
  if (value.length <= 100) return value;
  return value.slice(0, 30) + ' … ' + value.slice(-65);
}

const referenceImageUrl = computed(() => {
  const path = project.value?.inputs.unity_reference_image_path;
  return path ? externalPreviewUrl(path) : null;
});
</script>

<template>
  <div class="project-config">
    <div v-if="error" class="error-banner">{{ error }}</div>
    <p v-if="!project" class="muted small">加载中…</p>
    <template v-else>
      <header class="pc-head">
        <div>
          <h2>{{ project.name }}</h2>
          <p class="muted small">
            id <span class="mono">{{ project.id }}</span> ·
            创建 {{ project.created_at }} ·
            最后更新 {{ project.updated_at }}
          </p>
        </div>
        <span class="status-pill" :class="{ ok: requiredFilled, pending: !requiredFilled }">
          {{ requiredFilled ? '✓ 必选输入就绪' : '⚠ 缺必选输入' }}
        </span>
      </header>

      <section class="section">
        <h3 class="section-title">输入文件</h3>
        <div class="slot-grid">
          <div v-for="slot in slots" :key="slot.key" class="slot">
            <div class="slot-head">
              <span class="slot-label">
                {{ slot.label }}
                <span v-if="slot.required" class="required">*</span>
              </span>
              <div class="slot-actions">
                <button @click="pickSlot(slot)">选择…</button>
                <button v-if="project.inputs[slot.key]" class="ghost" @click="clearSlot(slot.key)">清除</button>
              </div>
            </div>
            <div class="slot-hint muted small">{{ slot.hint }}</div>
            <div class="slot-value mono small" :class="{ filled: !!project.inputs[slot.key] }">
              {{ shorten(typeof project.inputs[slot.key] === 'string' ? (project.inputs[slot.key] as string) : null) }}
            </div>
          </div>
        </div>
      </section>

      <section v-if="referenceImageUrl" class="section">
        <h3 class="section-title">Unity 参考图预览</h3>
        <div class="ref-preview">
          <img :src="referenceImageUrl" alt="unity reference" />
        </div>
      </section>

      <section class="section">
        <h3 class="section-title">Laya 截图区域</h3>
        <div class="region-row">
          <button class="primary" @click="pickRegionOnScreen" :disabled="pickingRegion || saving">
            {{ pickingRegion ? '请在屏幕上拖动…' : project.inputs.laya_capture_region ? '重新框选' : '在屏幕上框选…' }}
          </button>
          <button v-if="project.inputs.laya_capture_region" class="ghost" @click="clearRegion" :disabled="saving">清除</button>
          <div class="region-display-inline">
            <template v-if="project.inputs.laya_capture_region">
              <span class="region-pill">x <strong>{{ project.inputs.laya_capture_region.x }}</strong></span>
              <span class="region-pill">y <strong>{{ project.inputs.laya_capture_region.y }}</strong></span>
              <span class="region-pill">width <strong>{{ project.inputs.laya_capture_region.width }}</strong></span>
              <span class="region-pill">height <strong>{{ project.inputs.laya_capture_region.height }}</strong></span>
            </template>
            <span v-else class="muted small">未框选 — 点上面的按钮，鼠标拖一个矩形即可。Esc 取消。</span>
          </div>
        </div>
        <p class="muted small" style="margin-top: 6px;">
          每轮调参 apply 之后，按这个矩形从主屏幕抓取 Laya 渲染窗口。点"在屏幕上框选…"会弹出一个全屏半透明 overlay，
          鼠标拖一个矩形选中 Laya 编辑器/预览窗口的渲染区域，松开鼠标即保存。
        </p>

        <div class="anchor-row">
          <label class="anchor-toggle">
            <input
              type="checkbox"
              :checked="captureAnchor.enabled"
              @change="toggleAnchor"
              :disabled="saving"
            />
            <span>
              <strong>锚定到 Laya 窗口</strong>
              <span class="muted small" style="margin-left: 6px;">
                启用后：每次截屏前查询 Laya 窗口当前位置，以"框选时记录的窗口偏移"为基准重算绝对坐标——这样你之后拖动/缩放 Laya 窗口都不会让截图跑偏。
              </span>
            </span>
          </label>
          <div class="anchor-status" :class="{ ok: anchorReady, pending: !anchorReady }">
            <template v-if="anchorReady">
              偏移已记录：
              <span class="region-pill">dx <strong>{{ captureAnchor.offset_x }}</strong></span>
              <span class="region-pill">dy <strong>{{ captureAnchor.offset_y }}</strong></span>
              <span class="region-pill">w <strong>{{ captureAnchor.width }}</strong></span>
              <span class="region-pill">h <strong>{{ captureAnchor.height }}</strong></span>
            </template>
            <template v-else>
              偏移未记录（需要点一次"在屏幕上框选…"，框选时后端会同时记录 Laya 窗口位置）
            </template>
          </div>
        </div>
      </section>

      <section class="section">
        <h3 class="section-title">Laya 窗口聚焦</h3>
        <p class="muted small" style="margin: 0 0 8px;">
          Laya 编辑器在<strong>窗口失焦时会暂停渲染</strong>——后续每轮调参的截图都会拿到旧帧、让 fit_score 失真。
          下面这两条匹配规则用来在每次 .lmat 写入和每次截屏之前，自动把 Laya 窗口拉到前台。
          <span class="mono">process_pattern</span> 默认 <span class="mono">LayaAirIDE</span>；
          <span class="mono">title_pattern</span> 填你<strong>正在 Laya 编辑器里打开的那个项目名</strong>（注意这跟左侧 UI 的项目 id 通常不一样，
          以 Laya 编辑器窗口标题栏显示的为准）。同时打开多个 Laya 项目时尤其要填，否则可能聚焦到错的那个。
        </p>
        <div class="window-grid">
          <label class="window-field">
            <span class="window-label">process_pattern</span>
            <input
              :value="layaWindow.process_pattern"
              @change="(e) => saveLayaWindow({ process_pattern: (e.target as HTMLInputElement).value })"
              class="window-input"
              placeholder="LayaAirIDE"
              :disabled="saving"
            />
          </label>
          <label class="window-field">
            <span class="window-label">title_pattern</span>
            <input
              :value="layaWindow.title_pattern"
              @change="(e) => saveLayaWindow({ title_pattern: (e.target as HTMLInputElement).value })"
              class="window-input"
              placeholder="例如 effect / fish — 跟 Laya 编辑器标题栏一致"
              :disabled="saving"
            />
          </label>
          <label class="window-field">
            <span class="window-label">settle_ms</span>
            <input
              :value="layaWindow.settle_ms"
              @change="(e) => saveLayaWindow({ settle_ms: Number((e.target as HTMLInputElement).value) || 0 })"
              class="window-input window-input--num"
              type="number"
              min="0"
              step="50"
              :disabled="saving"
            />
          </label>
        </div>
        <p class="muted small" style="margin-top: 6px;">
          settle_ms 是切到前台之后等 Laya 把新一帧画出来的时间。默认 250ms，慢机器可调到 500。设 <span class="mono">process_pattern</span> 为空字符串可以禁用聚焦（不推荐）。
        </p>
      </section>

      <RefreshPreflightCard
        :project-id="project.id"
        :lmat-path="project.inputs.laya_material_lmat_path"
        :region-filled="!!project.inputs.laya_capture_region"
      />

      <section class="section">
        <h3 class="section-title">危险区</h3>
        <button class="danger" @click="onDelete">删除项目</button>
        <span class="muted small" style="margin-left: 8px;">
          会被移动到 <span class="mono">output/.trash/</span>，可手动恢复。
        </span>
      </section>
    </template>
  </div>
</template>

<style scoped>
.project-config { display: flex; flex-direction: column; gap: 14px; padding-bottom: 24px; }
.pc-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; }
.pc-head h2 { margin: 0 0 4px; font-size: 16px; }
.status-pill {
  padding: 4px 10px;
  border-radius: 999px;
  font-size: 12px;
  font-family: var(--mono);
  border: 1px solid;
}
.status-pill.ok { color: var(--good); border-color: var(--good); }
.status-pill.pending { color: var(--warn); border-color: var(--warn); }

.slot-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.slot {
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 8px 10px;
  display: flex; flex-direction: column; gap: 4px;
}
.slot-head { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
.slot-label { font-weight: 600; font-size: 13px; }
.required { color: var(--bad); margin-left: 2px; }
.slot-hint { line-height: 1.4; }
.slot-actions .ghost { background: transparent; border: 1px dashed var(--border-strong); }
.slot-value {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  padding: 4px 8px;
  border-radius: 4px;
  word-break: break-all;
  color: var(--text-dim);
}
.slot-value.filled { color: var(--good); }

.ref-preview { background: #0d1117; padding: 8px; border-radius: var(--radius); border: 1px solid var(--border); }
.ref-preview img { max-width: 100%; max-height: 360px; display: block; margin: 0 auto; }

.region-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.region-row .primary { background: var(--accent-strong); border-color: var(--accent-strong); color: white; }
.region-row .primary:disabled { opacity: 0.6; }
.region-row .ghost { background: transparent; border: 1px dashed var(--border-strong); }
.region-display-inline {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 4px 10px;
  flex: 1;
  min-height: 30px;
}
.region-pill {
  background: var(--bg-panel);
  border: 1px solid var(--border-strong);
  border-radius: 999px;
  padding: 1px 10px;
  font-size: 11px;
  color: var(--text-muted);
  font-family: var(--mono);
}
.region-pill strong { color: var(--good); margin-left: 4px; }

.anchor-row {
  margin-top: 10px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 8px 10px;
}
.anchor-toggle { display: flex; align-items: flex-start; gap: 8px; cursor: pointer; }
.anchor-toggle input[type="checkbox"] { margin-top: 4px; }
.anchor-status { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; font-size: 12px; }
.anchor-status.ok { color: var(--text); }
.anchor-status.pending { color: var(--warn); }

.window-grid {
  display: grid;
  grid-template-columns: 1fr 1fr 140px;
  gap: 8px;
}
.window-field { display: flex; flex-direction: column; gap: 4px; }
.window-label {
  font-size: 11px;
  color: var(--text-dim);
  font-family: var(--mono);
}
.window-input {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  color: var(--text);
  padding: 4px 8px;
  border-radius: 4px;
  font-family: var(--mono);
  font-size: 12px;
}
.window-input--num { width: 100%; }
@media (max-width: 900px) { .window-grid { grid-template-columns: 1fr; } }

.danger {
  background: rgba(248, 81, 73, 0.12);
  border-color: rgba(248, 81, 73, 0.4);
  color: var(--bad);
}
.danger:hover { background: rgba(248, 81, 73, 0.2); }
@media (max-width: 900px) { .slot-grid { grid-template-columns: 1fr; } }
</style>
