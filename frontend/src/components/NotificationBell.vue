<template>
  <router-link to="/notifications" class="bell" :aria-label="label">
    Notifications
    <span v-if="count > 0" class="badge">{{ count > 99 ? "99+" : count }}</span>
  </router-link>
</template>

<script setup>
// Nav link with an unread badge. Refreshes on every page change and every
// POLL_MS while the tab is open. Real-time push (websockets/SSE) is out of
// scope for the skeleton — swap the polling out later if the team wants it.
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { useRoute } from "vue-router";
import notificationsApi from "../api/notifications";

const POLL_MS = 60_000;

const count = ref(0);
const route = useRoute();
let timer = null;

const label = computed(() =>
  count.value ? `Notifications, ${count.value} unread` : "Notifications"
);

async function refresh() {
  try {
    const { data } = await notificationsApi.unreadCount();
    count.value = data.count;
  } catch {
    // A failed badge refresh should never break navigation; keep the old count.
  }
}

onMounted(() => {
  refresh();
  timer = setInterval(refresh, POLL_MS);
});
onUnmounted(() => clearInterval(timer));
watch(() => route.fullPath, refresh);

defineExpose({ refresh });
</script>

<style scoped>
.bell {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
}

.badge {
  min-width: 1.25rem;
  padding: 0 0.35rem;
  border-radius: 999px;
  background: var(--rose-bg);
  color: var(--rose-text);
  font-size: 0.75rem;
  font-weight: 600;
  line-height: 1.25rem;
  text-align: center;
}
</style>
