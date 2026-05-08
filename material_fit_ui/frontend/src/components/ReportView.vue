<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import { marked } from 'marked';
import type { CaseReportPayload } from '../api';
import { fetchCaseReport } from '../api';

const props = defineProps<{ caseId: string }>();

const payload = ref<CaseReportPayload | null>(null);
const error = ref<string | null>(null);
const loading = ref(false);

async function load(): Promise<void> {
  if (!props.caseId) {
    payload.value = null;
    return;
  }
  loading.value = true;
  error.value = null;
  try {
    payload.value = await fetchCaseReport(props.caseId);
  } catch (err) {
    payload.value = null;
    error.value = err instanceof Error ? err.message : String(err);
  } finally {
    loading.value = false;
  }
}

watch(() => props.caseId, () => { void load(); });
onMounted(() => { void load(); });

const renderedHtml = computed<string>(() => {
  if (!payload.value) return '';
  marked.setOptions({ gfm: true, breaks: false });
  const html = marked.parse(payload.value.text, { async: false }) as string;
  return rewriteImageSrcs(html, payload.value);
});

function rewriteImageSrcs(html: string, p: CaseReportPayload): string {
  return html.replace(/<img\s+([^>]*?)src="([^"]+)"([^>]*)>/gi, (match, pre: string, src: string, post: string) => {
    if (/^(https?:|data:|\/api\/image)/i.test(src)) return match;
    let resolved: string;
    if (src.startsWith('/')) {
      resolved = src.replace(/^\//, '');
    } else if (src.startsWith('./')) {
      resolved = `${p.case_dir}/${src.slice(2)}`;
    } else {
      resolved = `${p.case_dir}/${src}`;
    }
    return `<img ${pre}src="${p.image_base}${encodeURI(resolved)}"${post}>`;
  });
}
</script>

<template>
  <div class="report-view">
    <div class="report-toolbar">
      <h3 class="section-title" style="margin: 0;">报告</h3>
      <span v-if="payload" class="muted small">{{ payload.report_path }}</span>
      <span class="report-spacer" />
      <button v-if="payload" @click="load" :disabled="loading">{{ loading ? '加载中…' : '刷新' }}</button>
    </div>
    <div v-if="loading" class="empty-state muted small">加载中…</div>
    <div v-else-if="error" class="error-banner">{{ error }}</div>
    <article v-else-if="payload" class="report-body markdown-body" v-html="renderedHtml" />
    <div v-else class="empty-state muted small">无报告。</div>
  </div>
</template>

<style scoped>
.report-view { display: flex; flex-direction: column; gap: 8px; padding-bottom: 24px; }
.report-toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 0 6px;
  border-bottom: 1px solid var(--border);
}
.report-spacer { flex: 1; }
.report-body { padding: 8px 0; }
</style>
