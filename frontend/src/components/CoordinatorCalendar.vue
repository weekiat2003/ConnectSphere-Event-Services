<template>
  <div class="coordinator-calendar">
    <h2 class="page-title">My Calendar</h2>
    <p class="hint">Events assigned to you, on their proposed dates.</p>

    <p v-if="error" class="error" role="alert">{{ error }}</p>

    <div class="filters card">
      <label class="checkbox">
        <input v-model="showReadOnly" type="checkbox" />
        Show events reassigned away from me (read-only)
      </label>
      <label class="checkbox">
        <input v-model="showClosed" type="checkbox" />
        Show cancelled, rejected and completed events
      </label>
      <span class="count">{{ visibleEvents.length }} event{{ visibleEvents.length === 1 ? "" : "s" }} shown</span>
    </div>

    <p v-if="loading">Loading...</p>
    <EventMonthCalendar v-else :events="visibleEvents" />
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from "vue";
import eventsApi from "../api/events";
import EventMonthCalendar from "./EventMonthCalendar.vue";

const CLOSED_STATUSES = ["cancelled", "rejected", "completed"];

const events = ref([]);
const showReadOnly = ref(true);
const showClosed = ref(false);
const loading = ref(true);
const error = ref("");

// The backend is the source of truth for isReadOnly: every write route already
// enforces "only the current Coordinator"; this flag only drives the display.
const visibleEvents = computed(() =>
  events.value.filter(
    (e) => (showReadOnly.value || !e.isReadOnly) && (showClosed.value || !CLOSED_STATUSES.includes(e.status))
  )
);

onMounted(async () => {
  try {
    events.value = (await eventsApi.coordinatorCalendar()).data;
  } catch (e) {
    error.value = e.response?.data?.error || "Could not load your calendar.";
  } finally {
    loading.value = false;
  }
});
</script>

<style scoped>
.page-title {
  margin: 0 0 0.5rem;
  font-size: 1.5rem;
  font-weight: 600;
}
.hint {
  margin: 0 0 1rem;
  color: var(--text-muted, #6b6890);
}
.card {
  background: var(--surface, #fff);
  border: 1px solid var(--border, #e4defa);
  border-radius: 14px;
  box-shadow: 0 4px 16px rgba(109, 91, 208, 0.08);
}
.filters {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.6rem 1.5rem;
  padding: 0.75rem 1rem;
  margin-bottom: 1rem;
  font-size: 0.9rem;
}
.checkbox {
  display: flex;
  align-items: center;
  gap: 0.4rem;
}
.count {
  margin-left: auto;
  color: var(--text-muted, #6b6890);
  font-size: 0.85rem;
}
.error {
  color: var(--rose-text, #a12b47);
}
</style>
