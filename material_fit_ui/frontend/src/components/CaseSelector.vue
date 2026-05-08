<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue';
import type { CaseKind, CaseSummary } from '../types';

const props = defineProps<{ cases: CaseSummary[]; modelValue: string }>();
const emit = defineEmits<{ (e: 'update:modelValue', value: string): void }>();

const isOpen = ref(false);
const rootEl = ref<HTMLElement | null>(null);

const KIND_ORDER: CaseKind[] = ['project', 'auto_adjust', 'probe', 'diff_only', 'empty'];
const KIND_TITLE: Record<CaseKind, string> = {
  project: '项目（可控）',
  auto_adjust: '自动调参',
  probe: '探针候选',
  diff_only: '一次性差异',
  empty: '空目录',
};

const selectedCase = computed<CaseSummary | null>(() => {
  return props.cases.find((entry) => entry.id === props.modelValue) ?? null;
});

const groups = computed(() => {
  const buckets = new Map<CaseKind, CaseSummary[]>();
  for (const kind of KIND_ORDER) buckets.set(kind, []);
  for (const entry of props.cases) {
    if (!buckets.has(entry.kind)) buckets.set(entry.kind, []);
    buckets.get(entry.kind)!.push(entry);
  }
  for (const list of buckets.values()) {
    list.sort((a, b) => {
      const ta = a.last_modified ?? '';
      const tb = b.last_modified ?? '';
      return tb.localeCompare(ta);
    });
  }
  return KIND_ORDER.filter((kind) => (buckets.get(kind) || []).length > 0).map((kind) => ({
    kind,
    title: KIND_TITLE[kind],
    items: buckets.get(kind) || [],
  }));
});

function pick(entry: CaseSummary): void {
  emit('update:modelValue', entry.id);
  isOpen.value = false;
}

function toggleOpen(event: MouseEvent): void {
  event.stopPropagation();
  isOpen.value = !isOpen.value;
}

function onDocumentClick(event: MouseEvent): void {
  if (!isOpen.value) return;
  const target = event.target as Node | null;
  if (target && rootEl.value && rootEl.value.contains(target)) return;
  isOpen.value = false;
}

watch(
  () => props.cases.length,
  () => {
    isOpen.value = false;
  },
);

onMounted(() => {
  document.addEventListener('click', onDocumentClick);
});

onUnmounted(() => {
  document.removeEventListener('click', onDocumentClick);
});

function shortDate(iso: string | null | undefined): string {
  if (!iso) return '';
  try {
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return '';
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    const hour = String(date.getHours()).padStart(2, '0');
    const minute = String(date.getMinutes()).padStart(2, '0');
    return `${month}-${day} ${hour}:${minute}`;
  } catch {
    return '';
  }
}
</script>

<template>
  <div ref="rootEl" class="case-selector">
    <span class="muted small">case</span>
    <button class="case-trigger" type="button" @click="toggleOpen">
      <template v-if="selectedCase">
        <span class="kind-badge" :class="`kind-${selectedCase.kind}`">{{ selectedCase.kind_label }}</span>
        <span class="case-name">{{ selectedCase.id }}</span>
        <span class="muted small case-summary">{{ selectedCase.summary }}</span>
      </template>
      <template v-else>
        <span class="muted">未选择</span>
      </template>
      <span class="caret" :class="{ 'is-open': isOpen }">▾</span>
    </button>

    <div v-if="isOpen" class="case-popover">
      <div v-for="group in groups" :key="group.kind" class="case-group">
        <div class="case-group-title">
          {{ group.title }}
          <span class="muted small">({{ group.items.length }})</span>
        </div>
        <button
          v-for="item in group.items"
          :key="item.id"
          type="button"
          class="case-option"
          :class="{ 'is-active': item.id === modelValue }"
          @click="pick(item)"
        >
          <span class="kind-badge" :class="`kind-${item.kind}`">{{ item.kind_label }}</span>
          <span class="case-option-body">
            <span class="case-name">{{ item.id }}</span>
            <span class="muted small">{{ item.summary }}</span>
          </span>
          <span class="muted small case-mtime">{{ shortDate(item.last_modified) }}</span>
        </button>
      </div>
      <div v-if="!cases.length" class="muted small" style="padding: 6px 10px;">没有发现 case</div>
    </div>
  </div>
</template>

<style scoped>
.case-selector {
  position: relative;
  display: flex;
  align-items: center;
  gap: 6px;
}
.case-trigger {
  display: flex;
  align-items: center;
  gap: 8px;
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  color: var(--text);
  padding: 4px 10px;
  border-radius: var(--radius);
  cursor: pointer;
  min-width: 320px;
  text-align: left;
}
.case-trigger:hover { background: var(--bg-hover); }
.case-name { font-family: var(--mono); }
.case-summary {
  border-left: 1px solid var(--border-strong);
  padding-left: 8px;
  margin-left: 2px;
  flex: 1;
}
.caret { color: var(--text-dim); transition: transform 0.15s ease; }
.caret.is-open { transform: rotate(180deg); }

.case-popover {
  position: absolute;
  top: calc(100% + 4px);
  left: 32px;
  z-index: 20;
  background: var(--bg-panel);
  border: 1px solid var(--border-strong);
  border-radius: var(--radius);
  min-width: 460px;
  max-height: 60vh;
  overflow-y: auto;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.4);
  padding: 4px 0;
}
.case-group + .case-group { border-top: 1px solid var(--border); margin-top: 4px; padding-top: 4px; }
.case-group-title {
  padding: 6px 12px 4px;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  color: var(--text-muted);
}
.case-option {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  background: transparent;
  border: none;
  border-radius: 0;
  color: var(--text);
  padding: 6px 12px;
  text-align: left;
  cursor: pointer;
}
.case-option:hover { background: var(--bg-hover); }
.case-option.is-active { background: var(--bg-hover); }
.case-option-body { display: flex; flex-direction: column; flex: 1; min-width: 0; }
.case-option-body .case-name { font-family: var(--mono); }
.case-mtime { white-space: nowrap; }

.kind-badge {
  display: inline-block;
  font-family: var(--mono);
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 999px;
  border: 1px solid currentColor;
  text-transform: lowercase;
  white-space: nowrap;
}
.kind-project { color: #d2a8ff; background: rgba(210, 168, 255, 0.08); }
.kind-auto_adjust { color: var(--good); }
.kind-probe { color: var(--accent); }
.kind-diff_only { color: var(--warn); }
.kind-empty { color: var(--text-dim); }
</style>
