<script setup lang="ts">
import { computed, ref } from 'vue';
import { createProject, patchProject, pickFile, pickRegion } from '../api';
import type { CaptureRegion, ProjectInputs } from '../types';

const props = defineProps<{ open: boolean }>();
const emit = defineEmits<{
  (e: 'close'): void;
  (e: 'created', projectId: string): void;
}>();

const step = ref<1 | 2>(1);

const id = ref('');
const name = ref('');
const description = ref('');

const inputs = ref<ProjectInputs>({
  unity_shader_path: null,
  unity_material_params_path: null,
  unity_reference_image_path: null,
  laya_shader_path: null,
  laya_material_lmat_path: null,
  laya_capture_region: null,
  laya_capture_dir: null,
  laya_capture_state_file: null,
  laya_capture_prefix: 'laya_candidate',
});

const region = ref<CaptureRegion | null>(null);
const pickingRegion = ref(false);
const submitting = ref(false);
const error = ref<string | null>(null);

const isIdValid = computed(() => /^[a-zA-Z0-9_\-]{1,64}$/.test(id.value));
const requiredFilled = computed(
  () => !!inputs.value.laya_shader_path && !!inputs.value.laya_material_lmat_path,
);

interface Slot {
  key: keyof ProjectInputs;
  label: string;
  hint: string;
  required: boolean;
  filetypes: [string, string][];
  image?: boolean;
}

const slots: Slot[] = [
  {
    key: 'laya_shader_path',
    label: 'Laya 着色器（必选）',
    hint: '工程里实际使用的 .shader 文件，用于解析 uniformMap/defines',
    required: true,
    filetypes: [
      ['Laya shader', '*.shader *.vs *.fs'],
      ['All files', '*.*'],
    ],
  },
  {
    key: 'laya_material_lmat_path',
    label: 'Laya 材质 .lmat（必选，写入目标）',
    hint: '自动调参会把候选参数写入这里（每轮先备份 .bak）',
    required: true,
    filetypes: [
      ['Laya material', '*.lmat'],
      ['All files', '*.*'],
    ],
  },
  {
    key: 'unity_shader_path',
    label: 'Unity 着色器（可选）',
    hint: 'Unity ShaderLab .shader 文件；提供后才能做参数对照',
    required: false,
    filetypes: [
      ['Unity shader', '*.shader'],
      ['All files', '*.*'],
    ],
  },
  {
    key: 'unity_material_params_path',
    label: 'Unity 材质参数 JSON（可选）',
    hint: 'Editor 工具导出的 unity 材质实际参数（params/properties dict）',
    required: false,
    filetypes: [
      ['JSON', '*.json'],
      ['All files', '*.*'],
    ],
  },
  {
    key: 'unity_reference_image_path',
    label: 'Unity 渲染参考图（强烈推荐）',
    hint: '同视角同光照下 Unity 渲染出的 PNG，是 diff 的"真值"',
    required: false,
    image: true,
    filetypes: [
      ['PNG image', '*.png *.jpg *.jpeg *.bmp'],
      ['All files', '*.*'],
    ],
  },
  {
    key: 'laya_capture_dir',
    label: 'Laya 截图保存目录（可选）',
    hint: '周期截屏会写到这里；默认是 tools/material_fit/vision/test_image',
    required: false,
    filetypes: [],
  },
];

function close(): void {
  emit('close');
}

async function pick(slot: Slot): Promise<void> {
  error.value = null;
  try {
    const isDir = slot.key === 'laya_capture_dir';
    const result = await pickFile({
      mode: isDir ? 'directory' : 'open',
      title: slot.label,
      initial_dir: getInitialDir(slot.key),
      filetypes: isDir ? undefined : slot.filetypes,
    });
    if (result.error) {
      error.value = result.error;
      return;
    }
    if (result.path) {
      inputs.value = { ...inputs.value, [slot.key]: result.path } as ProjectInputs;
    }
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err);
  }
}

function clearSlot(key: keyof ProjectInputs): void {
  inputs.value = { ...inputs.value, [key]: null } as ProjectInputs;
}

function getInitialDir(key: keyof ProjectInputs): string | undefined {
  const value = inputs.value[key];
  if (typeof value === 'string' && value) {
    const idx = Math.max(value.lastIndexOf('/'), value.lastIndexOf('\\'));
    return idx > 0 ? value.slice(0, idx) : undefined;
  }
  return undefined;
}

async function next(): Promise<void> {
  if (!isIdValid.value) {
    error.value = 'project id 只能用字母数字、下划线、短横线，长度 1-64';
    return;
  }
  step.value = 2;
}

async function submit(): Promise<void> {
  if (!requiredFilled.value) {
    error.value = '至少需要选择 Laya shader 与 Laya .lmat 两个文件';
    return;
  }
  submitting.value = true;
  error.value = null;
  try {
    await createProject({
      id: id.value.trim(),
      name: name.value.trim() || id.value.trim(),
      description: description.value.trim(),
    });
    await patchProject(id.value.trim(), {
      inputs: { ...inputs.value, laya_capture_region: region.value },
    });
    emit('created', id.value.trim());
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err);
  } finally {
    submitting.value = false;
  }
}

async function pickRegionOnScreen(): Promise<void> {
  pickingRegion.value = true;
  error.value = null;
  try {
    const result = await pickRegion();
    if (result.error) {
      error.value = result.error;
      return;
    }
    if (result.region) {
      region.value = result.region;
    }
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err);
  } finally {
    pickingRegion.value = false;
  }
}

function clearRegion(): void {
  region.value = null;
}

function shorten(value: string | null): string {
  if (!value) return '未选择';
  if (value.length <= 80) return value;
  return value.slice(0, 30) + ' … ' + value.slice(-45);
}
</script>

<template>
  <Teleport to="body">
    <div v-if="props.open" class="wizard-overlay" @click.self="close">
      <div class="wizard">
        <header class="wizard-head">
          <h2>新建调参项目 <span class="muted small">step {{ step }}/2</span></h2>
          <button class="wizard-close" @click="close" aria-label="close">×</button>
        </header>

        <div v-if="error" class="error-banner">{{ error }}</div>

        <section v-if="step === 1" class="wizard-body">
          <p class="muted small">
            为这个调参任务起一个标识符。它会被用作 <span class="kbd">tools/material_fit/output/</span> 下的目录名。
          </p>
          <label class="field">
            <span>项目 ID（[a-zA-Z0-9_-]，1-64）</span>
            <input v-model="id" placeholder="例如 fish_2025_body" />
          </label>
          <label class="field">
            <span>显示名称</span>
            <input v-model="name" placeholder="可选，默认与 ID 相同" />
          </label>
          <label class="field">
            <span>说明</span>
            <textarea v-model="description" rows="2" placeholder="可选" />
          </label>
          <footer class="wizard-foot">
            <span class="muted small">下一步：选择文件与截图区域</span>
            <button class="primary" :disabled="!isIdValid" @click="next">下一步</button>
          </footer>
        </section>

        <section v-else class="wizard-body">
          <div class="slot-grid">
            <div v-for="slot in slots" :key="slot.key" class="slot">
              <div class="slot-head">
                <span class="slot-label">
                  {{ slot.label }}
                  <span v-if="slot.required" class="required">*</span>
                </span>
                <div class="slot-actions">
                  <button @click="pick(slot)">选择…</button>
                  <button v-if="inputs[slot.key]" class="ghost" @click="clearSlot(slot.key)">清除</button>
                </div>
              </div>
              <div class="slot-hint muted small">{{ slot.hint }}</div>
              <div class="slot-value mono small" :class="{ filled: !!inputs[slot.key] }">
                {{ shorten(typeof inputs[slot.key] === 'string' ? (inputs[slot.key] as string) : null) }}
              </div>
            </div>
          </div>

          <div class="region-block">
            <div class="slot-head">
              <span class="slot-label">Laya 截图区域（可选）</span>
              <div class="slot-actions">
                <button @click="pickRegionOnScreen" :disabled="pickingRegion">
                  {{ pickingRegion ? '请在屏幕上拖动…' : region ? '重新框选' : '在屏幕上框选…' }}
                </button>
                <button v-if="region" class="ghost" @click="clearRegion">清除</button>
              </div>
            </div>
            <div class="region-display">
              <template v-if="region">
                <span class="region-pill">x <strong>{{ region.x }}</strong></span>
                <span class="region-pill">y <strong>{{ region.y }}</strong></span>
                <span class="region-pill">width <strong>{{ region.width }}</strong></span>
                <span class="region-pill">height <strong>{{ region.height }}</strong></span>
              </template>
              <span v-else class="muted small">未框选 — 点上面的按钮，鼠标拖一个矩形即可。Esc 取消。</span>
            </div>
            <p class="muted small" style="margin: 6px 0 0;">
              每轮 apply 之后会按这个矩形从主屏幕抓取 Laya 渲染窗口。如果不框选，必须在算法配置里关闭
              <span class="kbd">capture_screen_after_apply</span>。
            </p>
          </div>

          <footer class="wizard-foot">
            <button @click="step = 1">上一步</button>
            <span class="muted small" :class="{ ok: requiredFilled }">
              {{ requiredFilled ? '✓ 必选输入已就绪' : '⚠ Laya shader + .lmat 必填' }}
            </span>
            <button class="primary" :disabled="!requiredFilled || submitting" @click="submit">
              {{ submitting ? '创建中…' : '创建项目' }}
            </button>
          </footer>
        </section>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.wizard-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.7);
  z-index: 90;
  display: flex;
  align-items: center;
  justify-content: center;
}
.wizard {
  width: min(820px, 92vw);
  max-height: 88vh;
  background: var(--bg);
  border: 1px solid var(--border-strong);
  border-radius: var(--radius);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.5);
}
.wizard-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 16px;
  background: var(--bg-panel);
  border-bottom: 1px solid var(--border);
}
.wizard-head h2 { margin: 0; font-size: 15px; font-weight: 600; }
.wizard-close {
  background: transparent;
  border: none;
  color: var(--text-muted);
  font-size: 18px;
  cursor: pointer;
  padding: 0 8px;
}
.wizard-body {
  padding: 14px 16px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.field { display: flex; flex-direction: column; gap: 4px; }
.field input, .field textarea {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  color: var(--text);
  padding: 6px 10px;
  border-radius: var(--radius);
  font-family: inherit;
}
.slot-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.slot {
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 8px 10px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.slot-head { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
.slot-label { font-weight: 600; font-size: 13px; }
.required { color: var(--bad); margin-left: 2px; }
.slot-hint { line-height: 1.4; }
.slot-actions { display: flex; gap: 4px; }
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

.region-block {
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 8px 10px;
}
.region-display {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 6px;
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 6px 10px;
  min-height: 28px;
  align-items: center;
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

.wizard-foot {
  display: flex;
  justify-content: flex-end;
  align-items: center;
  gap: 12px;
  padding-top: 10px;
  border-top: 1px solid var(--border);
}
.wizard-foot .ok { color: var(--good); }
.wizard-foot .primary {
  background: var(--accent-strong);
  border-color: var(--accent-strong);
  color: white;
}
.wizard-foot .primary:disabled { opacity: 0.5; }
@media (max-width: 720px) {
  .slot-grid { grid-template-columns: 1fr; }
}
</style>
