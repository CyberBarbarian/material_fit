<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue';

interface LightboxItem {
  src: string;
  title: string;
  subtitle?: string;
}

const props = defineProps<{
  items: LightboxItem[];
  initialIndex: number;
  open: boolean;
}>();

const emit = defineEmits<{ (e: 'close'): void }>();

const idx = ref(props.initialIndex);
const scale = ref(1);
const offset = ref({ x: 0, y: 0 });
const drag = ref<{ active: boolean; startX: number; startY: number; baseX: number; baseY: number }>({
  active: false,
  startX: 0,
  startY: 0,
  baseX: 0,
  baseY: 0,
});

const current = computed<LightboxItem | null>(() => props.items[idx.value] ?? null);

watch(
  () => props.open,
  (open) => {
    if (open) {
      idx.value = Math.max(0, Math.min(props.initialIndex, props.items.length - 1));
      resetTransform();
    }
  },
  { immediate: true },
);

watch(
  () => props.initialIndex,
  (next) => {
    if (props.open) idx.value = Math.max(0, Math.min(next, props.items.length - 1));
  },
);

function resetTransform(): void {
  scale.value = 1;
  offset.value = { x: 0, y: 0 };
}

function close(): void {
  emit('close');
}

function navigate(delta: number): void {
  if (!props.items.length) return;
  idx.value = (idx.value + delta + props.items.length) % props.items.length;
  resetTransform();
}

function onWheel(event: WheelEvent): void {
  event.preventDefault();
  const factor = event.deltaY > 0 ? 0.9 : 1.1;
  const next = Math.max(0.2, Math.min(8, scale.value * factor));
  scale.value = next;
}

function onMouseDown(event: MouseEvent): void {
  drag.value = {
    active: true,
    startX: event.clientX,
    startY: event.clientY,
    baseX: offset.value.x,
    baseY: offset.value.y,
  };
}

function onMouseMove(event: MouseEvent): void {
  if (!drag.value.active) return;
  offset.value = {
    x: drag.value.baseX + (event.clientX - drag.value.startX),
    y: drag.value.baseY + (event.clientY - drag.value.startY),
  };
}

function onMouseUp(): void {
  drag.value.active = false;
}

function onKey(event: KeyboardEvent): void {
  if (!props.open) return;
  if (event.key === 'Escape') {
    event.preventDefault();
    close();
  } else if (event.key === 'ArrowLeft') {
    event.preventDefault();
    navigate(-1);
  } else if (event.key === 'ArrowRight') {
    event.preventDefault();
    navigate(1);
  } else if (event.key === '0') {
    resetTransform();
  } else if (event.key === '+' || event.key === '=') {
    scale.value = Math.min(8, scale.value * 1.2);
  } else if (event.key === '-') {
    scale.value = Math.max(0.2, scale.value / 1.2);
  }
}

onMounted(() => {
  window.addEventListener('keydown', onKey);
  window.addEventListener('mouseup', onMouseUp);
  window.addEventListener('mousemove', onMouseMove);
});

onUnmounted(() => {
  window.removeEventListener('keydown', onKey);
  window.removeEventListener('mouseup', onMouseUp);
  window.removeEventListener('mousemove', onMouseMove);
});

const transformStyle = computed(() => ({
  transform: `translate(${offset.value.x}px, ${offset.value.y}px) scale(${scale.value})`,
}));

const counter = computed(() => `${idx.value + 1} / ${props.items.length}`);
</script>

<template>
  <Teleport to="body">
    <div v-if="open && current" class="lightbox-overlay" @click.self="close">
      <div class="lightbox-toolbar">
        <span class="lightbox-counter">{{ counter }}</span>
        <span v-if="current.title" class="lightbox-title">{{ current.title }}</span>
        <span v-if="current.subtitle" class="lightbox-subtitle">{{ current.subtitle }}</span>
        <span class="lightbox-spacer" />
        <span class="lightbox-hint">滚轮缩放 · 拖拽平移 · ←/→ 切换 · 0 复位 · Esc 关闭</span>
        <button class="lightbox-btn" @click="resetTransform">复位</button>
        <button class="lightbox-btn" @click="close">关闭</button>
      </div>

      <button v-if="items.length > 1" class="lightbox-nav prev" @click="navigate(-1)">‹</button>
      <button v-if="items.length > 1" class="lightbox-nav next" @click="navigate(1)">›</button>

      <div
        class="lightbox-stage"
        @wheel="onWheel"
        @mousedown="onMouseDown"
      >
        <img
          :src="current.src"
          :alt="current.title"
          :style="transformStyle"
          draggable="false"
        />
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.lightbox-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.85);
  z-index: 100;
  display: grid;
  grid-template-rows: auto 1fr;
}
.lightbox-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 14px;
  background: rgba(0, 0, 0, 0.6);
  color: var(--text);
  font-size: 12px;
  border-bottom: 1px solid var(--border);
}
.lightbox-counter { font-family: var(--mono); color: var(--text-muted); }
.lightbox-title { font-weight: 600; }
.lightbox-subtitle { color: var(--text-muted); }
.lightbox-hint { color: var(--text-dim); font-size: 11px; }
.lightbox-spacer { flex: 1; }
.lightbox-btn {
  background: var(--bg-elevated);
  border: 1px solid var(--border-strong);
  color: var(--text);
  padding: 4px 10px;
  border-radius: var(--radius);
  cursor: pointer;
}
.lightbox-btn:hover { background: var(--bg-hover); }

.lightbox-stage {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  cursor: grab;
  background:
    linear-gradient(45deg, #14181f 25%, transparent 25%) 0 0/24px 24px,
    linear-gradient(-45deg, #14181f 25%, transparent 25%) 0 12px/24px 24px,
    linear-gradient(45deg, transparent 75%, #14181f 75%) 12px -12px/24px 24px,
    linear-gradient(-45deg, transparent 75%, #14181f 75%) -12px 0/24px 24px;
  background-color: #0d1117;
}
.lightbox-stage:active { cursor: grabbing; }
.lightbox-stage img {
  max-width: none;
  max-height: none;
  user-select: none;
  pointer-events: none;
  transform-origin: center;
  transition: transform 60ms ease-out;
}

.lightbox-nav {
  position: absolute;
  top: 50%;
  transform: translateY(-50%);
  background: rgba(0, 0, 0, 0.5);
  border: 1px solid var(--border-strong);
  color: var(--text);
  width: 40px;
  height: 64px;
  font-size: 28px;
  border-radius: var(--radius);
  cursor: pointer;
  z-index: 2;
}
.lightbox-nav:hover { background: rgba(0, 0, 0, 0.8); }
.lightbox-nav.prev { left: 12px; }
.lightbox-nav.next { right: 12px; }
</style>
