<script setup lang="ts">
import { computed, ref } from 'vue';
import ImageLightbox from './ImageLightbox.vue';

interface Card {
  key: 'reference' | 'candidate' | 'diff';
  title: string;
  hint: string;
}

const props = defineProps<{
  images: { reference: string | null; candidate: string | null; diff: string | null };
  contextLabel?: string;
}>();

const cards: Card[] = [
  { key: 'reference', title: 'Unity 参考', hint: 'reference' },
  { key: 'candidate', title: 'Laya 候选', hint: 'candidate' },
  { key: 'diff', title: '差异图', hint: 'diff (×4 gain)' },
];

const dims = ref<Record<string, string>>({});

const lightboxOpen = ref(false);
const lightboxIndex = ref(0);

const lightboxItems = computed(() => {
  const arr: { src: string; title: string; subtitle?: string }[] = [];
  for (const card of cards) {
    const url = props.images[card.key];
    if (!url) continue;
    arr.push({
      src: url,
      title: card.title,
      subtitle: dims.value[card.key]
        ? `${card.hint} · ${dims.value[card.key]}${props.contextLabel ? ' · ' + props.contextLabel : ''}`
        : `${card.hint}${props.contextLabel ? ' · ' + props.contextLabel : ''}`,
    });
  }
  return arr;
});

function recordDimensions(key: string, event: Event): void {
  const target = event.target as HTMLImageElement;
  if (target.naturalWidth && target.naturalHeight) {
    dims.value[key] = `${target.naturalWidth} × ${target.naturalHeight}`;
  }
}

function open(card: Card): void {
  if (!props.images[card.key]) return;
  const items = lightboxItems.value;
  const target = items.findIndex((item) => item.src === props.images[card.key]);
  lightboxIndex.value = Math.max(0, target);
  lightboxOpen.value = true;
}
</script>

<template>
  <section class="section">
    <h3 class="section-title">图像对比<span v-if="contextLabel" class="muted small" style="margin-left: 8px;">{{ contextLabel }}</span></h3>
    <div class="image-row">
      <div
        v-for="card in cards"
        :key="card.key"
        class="image-card"
        :class="{ empty: !images[card.key] }"
      >
        <div class="image-card-header">
          <span>{{ card.title }}</span>
          <span class="muted small">
            {{ dims[card.key] ?? card.hint }}
          </span>
        </div>
        <div class="image-card-body">
          <img
            v-if="images[card.key]"
            :src="images[card.key]!"
            :alt="card.title"
            loading="lazy"
            title="点击放大"
            style="cursor: zoom-in"
            @click="open(card)"
            @load="recordDimensions(card.key, $event)"
          />
          <span v-else>无</span>
        </div>
      </div>
    </div>

    <ImageLightbox
      :items="lightboxItems"
      :initial-index="lightboxIndex"
      :open="lightboxOpen"
      @close="lightboxOpen = false"
    />
  </section>
</template>
