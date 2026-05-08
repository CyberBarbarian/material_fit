<script setup lang="ts">
import { computed } from 'vue';
import type { IterationSummary } from '../types';

const props = defineProps<{
  iterations: IterationSummary[];
  selectedIterId: string;
}>();

const emit = defineEmits<{ (e: 'select', iterId: string): void }>();

interface Point {
  iteration: number;
  iterId: string;
  cx: number;
  fitY: number | null;
  maeY: number | null;
  fit: number | null;
  mae: number | null;
}

const width = 1200;
const height = 110;
const paddingLeft = 36;
const paddingRight = 12;
const paddingTop = 10;
const paddingBottom = 22;

const yMin = 0;
const yMax = 1;

function clamp01(value: number): number {
  return Math.max(yMin, Math.min(yMax, value));
}

function projectY(value: number): number {
  const innerH = height - paddingTop - paddingBottom;
  return paddingTop + (1 - (clamp01(value) - yMin) / (yMax - yMin)) * innerH;
}

const points = computed<Point[]>(() => {
  if (props.iterations.length === 0) return [];
  const xs = props.iterations.map((entry) => entry.iteration);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const denomX = maxX - minX || 1;
  const innerW = width - paddingLeft - paddingRight;
  return props.iterations.map((entry) => {
    const fit = typeof entry.fit_score_before === 'number' ? entry.fit_score_before : null;
    const mae = typeof entry.diff_score_before === 'number' ? entry.diff_score_before : null;
    const cx = paddingLeft + ((entry.iteration - minX) / denomX) * innerW;
    return {
      iteration: entry.iteration,
      iterId: entry.iter_id,
      cx,
      fitY: fit == null ? null : projectY(fit),
      maeY: mae == null ? null : projectY(mae),
      fit,
      mae,
    };
  });
});

const target = computed<number | null>(() => {
  for (const entry of props.iterations) {
    if (typeof entry.target_score === 'number') return entry.target_score;
  }
  return null;
});

const targetY = computed<number | null>(() => (target.value == null ? null : projectY(target.value)));

function buildPath(getter: (p: Point) => number | null): string {
  const valid = points.value.filter((p) => getter(p) != null);
  if (valid.length === 0) return '';
  return valid
    .map((p, i) => `${i === 0 ? 'M' : 'L'}${p.cx.toFixed(1)},${getter(p)!.toFixed(1)}`)
    .join(' ');
}

const fitPath = computed(() => buildPath((p) => p.fitY));
const maePath = computed(() => buildPath((p) => p.maeY));

const yTicks = [0, 0.25, 0.5, 0.75, 1];

function tickY(value: number): number {
  return projectY(value);
}

function isSelected(p: Point): boolean {
  return p.iterId === props.selectedIterId;
}

function selectPoint(p: Point): void {
  emit('select', p.iterId);
}
</script>

<template>
  <footer class="score-curve">
    <div class="score-curve-header">
      <span>iter timeline</span>
      <span class="legend-dot fit" />
      <span class="muted small">fit_score</span>
      <span class="legend-dot mae" />
      <span class="muted small">RGB MAE</span>
      <span v-if="target != null" class="legend-dot target" />
      <span v-if="target != null" class="muted small">target = {{ target.toFixed(3) }}</span>
      <span v-if="iterations.length === 0" class="muted small">无迭代数据</span>
    </div>
    <svg
      v-if="iterations.length > 0"
      class="score-curve-svg"
      :viewBox="`0 0 ${width} ${height}`"
      preserveAspectRatio="none"
    >
      <g>
        <line
          v-for="t in yTicks"
          :key="t"
          :x1="paddingLeft"
          :x2="width - paddingRight"
          :y1="tickY(t)"
          :y2="tickY(t)"
          stroke="#2a313c"
          stroke-width="1"
        />
        <text
          v-for="t in yTicks"
          :key="`label-${t}`"
          :x="paddingLeft - 6"
          :y="tickY(t) + 3"
          fill="#6e7681"
          font-size="10"
          text-anchor="end"
          font-family="ui-monospace, Menlo, Consolas, monospace"
        >
          {{ t.toFixed(2) }}
        </text>
      </g>

      <line
        v-if="targetY != null"
        :x1="paddingLeft"
        :x2="width - paddingRight"
        :y1="targetY"
        :y2="targetY"
        stroke="#d29922"
        stroke-width="1"
        stroke-dasharray="4 4"
      />

      <path :d="maePath" stroke="#f0883e" stroke-width="1.5" fill="none" stroke-dasharray="3 3" />
      <path :d="fitPath" stroke="#58a6ff" stroke-width="1.5" fill="none" />

      <g>
        <template v-for="p in points" :key="p.iterId">
          <circle
            v-if="p.maeY != null"
            :cx="p.cx"
            :cy="p.maeY"
            :r="isSelected(p) ? 3.5 : 2.2"
            fill="#f0883e"
            stroke="#0d1117"
            stroke-width="1"
            style="cursor: pointer"
            @click="selectPoint(p)"
          >
            <title>iter {{ p.iteration }} · MAE {{ p.mae == null ? '—' : p.mae.toFixed(4) }}</title>
          </circle>
          <circle
            v-if="p.fitY != null"
            :cx="p.cx"
            :cy="p.fitY"
            :r="isSelected(p) ? 4.5 : 2.8"
            :fill="isSelected(p) ? '#f0883e' : '#58a6ff'"
            stroke="#0d1117"
            stroke-width="1"
            style="cursor: pointer"
            @click="selectPoint(p)"
          >
            <title>iter {{ p.iteration }} · fit {{ p.fit == null ? '—' : p.fit.toFixed(4) }}</title>
          </circle>
        </template>
      </g>
    </svg>
  </footer>
</template>

<style scoped>
.legend-dot {
  display: inline-block;
  width: 10px;
  height: 2px;
  vertical-align: middle;
  margin: 0 2px 0 6px;
  background: #58a6ff;
  border-radius: 1px;
}
.legend-dot.fit { background: #58a6ff; }
.legend-dot.mae { background: #f0883e; }
.legend-dot.target { background: #d29922; }
</style>
