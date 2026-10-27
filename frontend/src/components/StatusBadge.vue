<template>
  <span :class="['badge', tone]">{{ text }}</span>
</template>

<script setup>
import { computed } from "vue";

const props = defineProps({
  kind: { type: String, default: "event" },
  status: { type: String, default: "" },
  label: { type: String, default: "" },
});

// Event colours mirror the Coordinator dashboard exactly.
const TONES = {
  event: {
    approved: "mint", confirmed: "mint", completed: "mint",
    rejected: "rose", cancelled: "rose",
    under_review: "butter", submitted: "butter",
    planning: "sky",
  },
  requirement: { requested: "butter", confirmed: "mint", unavailable: "rose" },
  preparation: { pending: "lilac", in_progress: "sky", done: "mint" },
  item: { active: "mint", damaged: "rose", maintenance: "butter" },
};

const LABELS = {
  requirement: { requested: "Requested", confirmed: "Reserved", unavailable: "Unavailable" },
  preparation: { pending: "Pending", in_progress: "In progress", done: "Done" },
  item: { active: "Active", damaged: "Damaged", maintenance: "Under Maintenance" },
};

const tone = computed(() => TONES[props.kind]?.[props.status] || "lilac");
const text = computed(
  () => props.label || LABELS[props.kind]?.[props.status] || props.status.replace(/_/g, " ") || "Unknown status"
);
</script>

<style scoped>
.badge {
  display: inline-block;
  padding: 0.15rem 0.65rem;
  margin-right: 0.35rem;
  border-radius: 999px;
  font-size: 0.8rem;
  font-weight: 500;
  text-transform: capitalize;
  white-space: nowrap;
}
.lilac { background: var(--lilac-bg, #e9e5fb); color: var(--lilac-text, #4b3fa0); }
.mint { background: var(--mint-bg, #d3f5e3); color: var(--mint-text, #1e6b47); }
.rose { background: var(--rose-bg, #ffdce3); color: var(--rose-text, #a12b47); }
.butter { background: var(--butter-bg, #fff1c2); color: var(--butter-text, #8a5a00); }
.sky { background: var(--sky-bg, #d6ecff); color: var(--sky-text, #1f5f99); }
</style>