<script setup lang="ts">
import { computed } from 'vue';
import type { CenterEdgeBalance, DiffAnalysis, MaterialChannel } from '../types';

const props = defineProps<{ diffAnalysis: DiffAnalysis | null }>();

interface ChannelRow {
  key: string;
  name: string;
  severity: string;
  rgbMae: number;
  lumaBias: number;
  satBias: number;
  contrastBias: number;
  rgbBias: [number, number, number];
  relatedParams: string[];
}

interface BalanceRow {
  centerLuma: number;
  edgeLuma: number;
  edgeMinusCenter: number;
  relatedParams: string[];
}

function isMaterialChannel(value: MaterialChannel | CenterEdgeBalance | undefined): value is MaterialChannel {
  return !!value && (value as MaterialChannel).severity !== undefined;
}

const rows = computed<ChannelRow[]>(() => {
  if (!props.diffAnalysis) return [];
  const out: ChannelRow[] = [];
  for (const [key, value] of Object.entries(props.diffAnalysis.material_channels)) {
    if (!isMaterialChannel(value)) continue;
    if (!value.valid) continue;
    out.push({
      key,
      name: value.name,
      severity: value.severity,
      rgbMae: value.rgb_mae,
      lumaBias: value.luma_bias_candidate_minus_reference,
      satBias: value.saturation_bias_candidate_minus_reference,
      contrastBias: value.contrast_bias_candidate_minus_reference,
      rgbBias: value.rgb_bias_candidate_minus_reference,
      relatedParams: value.related_params,
    });
  }
  out.sort((a, b) => b.rgbMae - a.rgbMae);
  return out;
});

const balance = computed<BalanceRow | null>(() => {
  if (!props.diffAnalysis) return null;
  const value = props.diffAnalysis.material_channels.center_vs_edge_balance as CenterEdgeBalance | undefined;
  if (!value || !value.valid) return null;
  return {
    centerLuma: value.center_luma_signed,
    edgeLuma: value.edge_luma_signed,
    edgeMinusCenter: value.edge_minus_center_luma_bias,
    relatedParams: value.related_params,
  };
});

const hints = computed(() => props.diffAnalysis?.adjustment_hints ?? []);

function fmt(value: number, digits = 4): string {
  if (Number.isNaN(value)) return 'NaN';
  return value.toFixed(digits);
}

function signed(value: number): string {
  return (value >= 0 ? '+' : '') + fmt(value);
}

function biasClass(value: number): string {
  if (Math.abs(value) < 0.005) return 'muted';
  return value > 0 ? 'numeric-cell positive' : 'numeric-cell negative';
}
</script>

<template>
  <div>
    <p v-if="!diffAnalysis" class="muted small">没有 diff_analysis.json。</p>
    <template v-else>
      <table class="channels-table">
        <thead>
          <tr>
            <th>通道</th>
            <th>语义</th>
            <th>severity</th>
            <th>RGB MAE</th>
            <th>Δluma</th>
            <th>Δsat</th>
            <th>Δcontrast</th>
            <th>Δrgb (cand−ref)</th>
            <th>相关参数</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in rows" :key="row.key">
            <td><span class="mono">{{ row.key }}</span></td>
            <td class="muted small">{{ row.name }}</td>
            <td>
              <span class="severity-badge" :class="`severity-${row.severity}`">{{ row.severity }}</span>
            </td>
            <td class="numeric-cell">{{ fmt(row.rgbMae) }}</td>
            <td :class="biasClass(row.lumaBias)">{{ signed(row.lumaBias) }}</td>
            <td :class="biasClass(row.satBias)">{{ signed(row.satBias) }}</td>
            <td :class="biasClass(row.contrastBias)">{{ signed(row.contrastBias) }}</td>
            <td class="mono small muted">
              [{{ signed(row.rgbBias[0]) }}, {{ signed(row.rgbBias[1]) }}, {{ signed(row.rgbBias[2]) }}]
            </td>
            <td class="muted small">{{ row.relatedParams.join(', ') }}</td>
          </tr>
        </tbody>
      </table>

      <p v-if="balance" class="small muted" style="margin-top: 8px;">
        center vs edge:
        center luma {{ signed(balance.centerLuma) }},
        edge luma {{ signed(balance.edgeLuma) }},
        edge−center {{ signed(balance.edgeMinusCenter) }}
        <span v-if="balance.relatedParams.length"> · 相关 {{ balance.relatedParams.join(', ') }}</span>
      </p>

      <section v-if="hints.length" style="margin-top: 12px;">
        <h4 class="hints-title">调参提示（来自 diff 分析）</h4>
        <ul class="hint-list">
          <li v-for="hint in hints" :key="hint.channel + hint.direction">
            <span class="severity-badge" :class="`severity-${hint.severity}`">{{ hint.severity }}</span>
            <span class="mono small">{{ hint.channel }}</span>
            <span class="muted small">→</span>
            <span class="hint-direction" :class="`dir-${hint.direction}`">{{ hint.direction }}</span>
            <span class="muted small">·</span>
            <span class="muted small">{{ hint.reason }}</span>
            <span v-if="hint.related_params.length" class="muted small">
              · 相关 <span class="mono">{{ hint.related_params.slice(0, 3).join(', ') }}{{ hint.related_params.length > 3 ? '…' : '' }}</span>
            </span>
          </li>
        </ul>
      </section>
    </template>
  </div>
</template>

<style scoped>
.hints-title {
  font-size: 12px;
  margin: 0 0 6px;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.4px;
}
.hint-list { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 4px; }
.hint-list li {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  padding: 4px 8px;
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: 4px;
}
.hint-direction {
  font-family: var(--mono);
  font-size: 11px;
  padding: 0 6px;
  border-radius: 3px;
  border: 1px solid;
}
.dir-decrease { color: var(--bad); }
.dir-increase { color: var(--accent); }
.dir-inspect { color: var(--text-muted); }
</style>
