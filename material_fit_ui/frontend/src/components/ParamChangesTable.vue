<script setup lang="ts">
import type { ParamChange } from '../types';

const props = defineProps<{ changes: ParamChange[] }>();

function formatValue(value: unknown): string {
  if (value == null) return '—';
  if (typeof value === 'number') return formatNumber(value);
  if (Array.isArray(value)) {
    return '[' + value.map((item) => (typeof item === 'number' ? formatNumber(item) : String(item))).join(', ') + ']';
  }
  return JSON.stringify(value);
}

function formatNumber(value: number): string {
  if (Number.isNaN(value) || !Number.isFinite(value)) return String(value);
  if (Math.abs(value) < 0.0001 && value !== 0) return value.toExponential(2);
  return Number(value).toFixed(4);
}

function delta(oldVal: unknown, newVal: unknown): string {
  if (typeof oldVal === 'number' && typeof newVal === 'number') {
    return (newVal - oldVal >= 0 ? '+' : '') + formatNumber(newVal - oldVal);
  }
  if (Array.isArray(oldVal) && Array.isArray(newVal)) {
    const len = Math.min(oldVal.length, newVal.length);
    const parts: string[] = [];
    for (let i = 0; i < len; i++) {
      const a = oldVal[i];
      const b = newVal[i];
      if (typeof a === 'number' && typeof b === 'number') {
        parts.push((b - a >= 0 ? '+' : '') + formatNumber(b - a));
      } else {
        parts.push('?');
      }
    }
    return '[' + parts.join(', ') + ']';
  }
  return '—';
}

function isColorLike(name: string, value: unknown): boolean {
  if (!Array.isArray(value)) return false;
  if (value.length < 3) return false;
  if (!value.slice(0, 3).every((item) => typeof item === 'number')) return false;
  const lower = name.toLowerCase();
  return /color|tint|shadow|emission|specular|fresnel|matcap|ibl/.test(lower);
}

function colorCss(value: unknown): string {
  if (!Array.isArray(value) || value.length < 3) return 'transparent';
  const clamp = (v: unknown): number => {
    const n = typeof v === 'number' ? v : 0;
    return Math.max(0, Math.min(1, n));
  };
  const r = Math.round(clamp(value[0]) * 255);
  const g = Math.round(clamp(value[1]) * 255);
  const b = Math.round(clamp(value[2]) * 255);
  return `rgb(${r}, ${g}, ${b})`;
}

const hasChanges = (): boolean => props.changes.length > 0;
</script>

<template>
  <div>
    <table v-if="hasChanges()" class="changes-table">
      <thead>
        <tr>
          <th>参数</th>
          <th>旧值</th>
          <th>新值</th>
          <th>Δ</th>
          <th>原因</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="change in changes" :key="change.param">
          <td><span class="mono">{{ change.param }}</span></td>
          <td class="numeric">
            <span v-if="isColorLike(change.param, change.old)" class="color-swatch" :style="{ background: colorCss(change.old) }" />
            <span class="mono">{{ formatValue(change.old) }}</span>
          </td>
          <td class="numeric">
            <span v-if="isColorLike(change.param, change.new)" class="color-swatch" :style="{ background: colorCss(change.new) }" />
            <span class="mono">{{ formatValue(change.new) }}</span>
          </td>
          <td class="numeric muted"><span class="mono">{{ delta(change.old, change.new) }}</span></td>
          <td class="muted small">{{ change.reason ?? '—' }}</td>
        </tr>
      </tbody>
    </table>
    <p v-else class="muted small">本轮没有参数变化。</p>
  </div>
</template>

<style scoped>
.color-swatch {
  display: inline-block;
  width: 12px;
  height: 12px;
  margin-right: 4px;
  vertical-align: -2px;
  border: 1px solid var(--border-strong);
  border-radius: 2px;
}
</style>
