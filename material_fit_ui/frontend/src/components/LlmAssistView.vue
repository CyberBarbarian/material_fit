<script setup lang="ts">
import { onMounted, ref, watch } from 'vue';
import { fetchProject, patchProject } from '../api';
import type { ProjectDetail } from '../types';

const props = defineProps<{ projectId: string }>();
const project = ref<ProjectDetail | null>(null);
const error = ref<string | null>(null);
const enabled = ref(false);
const provider = ref('');

async function load(): Promise<void> {
  if (!props.projectId) return;
  try {
    project.value = await fetchProject(props.projectId);
    enabled.value = !!project.value.llm_config?.enabled;
    provider.value = project.value.llm_config?.provider ?? '';
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err);
  }
}

watch(() => props.projectId, () => { void load(); });
onMounted(() => { void load(); });

async function save(): Promise<void> {
  if (!project.value) return;
  try {
    project.value = await patchProject(project.value.id, {
      llm_config: { enabled: enabled.value, provider: provider.value || null },
    });
    error.value = null;
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err);
  }
}
</script>

<template>
  <div class="llm-view">
    <header style="display: flex; gap: 12px; align-items: baseline;">
      <h2 class="section-title" style="margin: 0;">LLM 助手</h2>
      <span class="muted small">骨架占位 · 未来接入 GPT-4 / Claude / Gemini</span>
    </header>

    <div v-if="error" class="error-banner">{{ error }}</div>

    <section class="section">
      <h3 class="section-title">规划用途</h3>
      <ul class="plan-list">
        <li>
          <strong>预分析阶段</strong>：把 Unity/Laya shader 源 + 解析后 uniformMap 喂给 LLM，
          要求生成跨引擎参数映射、识别 Unity 端独有特性的迁移方案、并在
          <span class="mono">predicted_strategy</span> 字段返回结构化建议。
        </li>
        <li>
          <strong>每轮调参</strong>：把当前迭代的 <span class="mono">decision.json</span> +
          <span class="mono">diff_analysis.json</span> + 最近 3 轮历史送进 LLM，请它在算法
          抽不出方向时（如所有阶段都被标记 <span class="mono">no_effective_change</span>）
          补一个语义化建议（"压暗 base color、提高 fresnel power"等）。
        </li>
        <li>
          <strong>停滞救援</strong>：当 fit_score 连续 N 轮无明显改进，算法层主动调用 LLM 提议
          一个跨阶段的"突破策略"，并以 <span class="kbd">--apply-llm-suggestion</span> 的方式
          灌回参数空间。
        </li>
        <li>
          <strong>报告强化</strong>：完成后把 report.md + 全部迭代摘要交给 LLM，让它写一段
          "为什么这次跑成功/失败"的归因总结放在 report 顶部。
        </li>
      </ul>
    </section>

    <section class="section" v-if="project">
      <h3 class="section-title">本项目的 LLM 设置（暂存，不调真 LLM）</h3>
      <p class="muted small">
        现在保存的是项目的 LLM 偏好；后端尚未接入实际 provider。等我们把硬缺口（真实 Laya 闭环 +
        真正的搜索算法）填好后，会在这里加 API key 字段并对接到 `optimizer/` 里。
      </p>
      <div class="llm-form">
        <label>
          <input type="checkbox" v-model="enabled" />
          启用 LLM 辅助（当前不会发起真实请求）
        </label>
        <label>
          provider
          <select v-model="provider">
            <option value="">未选择</option>
            <option value="openai">OpenAI (GPT-4o/4.1)</option>
            <option value="anthropic">Anthropic (Claude 4)</option>
            <option value="gemini">Google Gemini 2</option>
            <option value="local">本地模型（Ollama 等）</option>
          </select>
        </label>
        <button class="primary" @click="save">保存设置</button>
      </div>
    </section>

    <section class="section">
      <h3 class="section-title">后续硬缺口对照</h3>
      <p class="muted small">
        这些项目落实之后，本面板里 "运行中"按钮会真正点亮：
      </p>
      <ul class="gap-list">
        <li>
          <span class="kbd">优先级 P0</span> 真实 Laya 渲染回路：把
          <span class="mono">render_driver.RenderDriver</span> 跟你的 Laya 工程的
          预览页 / Editor 真实连起来（通过 capture_laya.js 或直接读 LayaAir 编辑器的截图区域），
          否则 capture_screen_after_apply 等于看的还是上一帧。
        </li>
        <li>
          <span class="kbd">优先级 P0</span> 真正的搜索算法：当前
          <span class="mono">optimizer/adjustment_algorithm.py</span> 是反馈控制器，没有 rollback/分支搜索。
          要么加上 best-of-N 多候选并行评估，要么挂到 <span class="mono">scipy.optimize</span> /
          <span class="mono">scikit-optimize</span> 之类的实现。
        </li>
        <li>
          <span class="kbd">优先级 P1</span> Unity → Laya 参数映射字典：现在用名字相似度，
          准确率约 60%。要落实一份 Unity Standard / URP Lit / Toon → Laya 标准着色器的语义对照表。
        </li>
        <li>
          <span class="kbd">优先级 P1</span> 区域语义分析：图像 diff 现在是全图 RGB MAE。
          要根据材质语义（高光/阴影/边缘）按 mask 加权评分，避免高频噪声拉低分数。
        </li>
        <li>
          <span class="kbd">优先级 P2</span> LLM 实接入：上面任意一个挂上去之前，
          <span class="mono">llm_config.enabled</span> 都只是声明意图。
        </li>
      </ul>
    </section>
  </div>
</template>

<style scoped>
.llm-view { display: flex; flex-direction: column; gap: 14px; padding-bottom: 24px; }
.plan-list, .gap-list { padding-left: 22px; margin: 4px 0; }
.plan-list li, .gap-list li { margin: 6px 0; line-height: 1.55; }
.gap-list .kbd {
  display: inline-block;
  margin-right: 6px;
  background: var(--bg-elevated);
  border: 1px solid var(--border-strong);
  color: var(--accent);
  padding: 1px 6px;
  border-radius: 4px;
  font-family: var(--mono);
  font-size: 11px;
}
.llm-form {
  display: flex;
  gap: 12px;
  align-items: center;
  flex-wrap: wrap;
  background: var(--bg-panel);
  border: 1px solid var(--border);
  padding: 8px 12px;
  border-radius: var(--radius);
}
.llm-form select {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  color: var(--text);
  padding: 4px 6px;
  border-radius: 4px;
}
.primary { background: var(--accent-strong); border-color: var(--accent-strong); color: white; }
</style>
