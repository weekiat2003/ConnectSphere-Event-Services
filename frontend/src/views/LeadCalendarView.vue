<template>
  <div>
    <h2 class="page-title">Events Calendar</h2>
    <p class="hint">
      Every active event on its proposed date, with the Coordinator handling it.
      Unassigned requests have a dashed amber outline.
    </p>

    <p v-if="error" class="error" role="alert">{{ error }}</p>

    <div class="filters card">
      <label>
        Coordinator
        <select v-model="coordinatorFilter" aria-label="Filter by coordinator">
          <option value="all">All coordinators</option>
          <option value="unassigned">Unassigned only</option>
          <option v-for="c in coordinators" :key="c.id" :value="String(c.id)">{{ c.name }}</option>
        </select>
      </label>
      <label>
        Status
        <select v-model="statusFilter" aria-label="Filter by status">
          <option value="active">All active statuses</option>
          <option v-for="s in ACTIVE_STATUSES" :key="s" :value="s">{{ STATUS_LABEL[s] }}</option>
          <option value="closed">Closed (cancelled, rejected, completed)</option>
        </select>
      </label>
      <button v-if="filtersOn" type="button" class="btn-soft" @click="clearFilters">Clear filters</button>
      <span class="count">{{ visibleEvents.length }} event{{ visibleEvents.length === 1 ? "" : "s" }} shown</span>
    </div>

    <p v-if="loading">Loading...</p>
    <EventMonthCalendar v-else :events="visibleEvents" show-coordinator>
      <template #actions="{ event }">
        <router-link
          v-if="isAssignable(event)"
          :to="{ name: 'assignments', query: { event: event.id } }"
          class="btn-secondary"
        >
          {{ event.coordinatorId ? "Reassign in Assignment Queue" : "Assign in Assignment Queue" }}
        </router-link>
      </template>
    </EventMonthCalendar>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from "vue";
import eventsApi from "../api/events";
import EventMonthCalendar from "../components/EventMonthCalendar.vue";

const ACTIVE_STATUSES = ["submitted", "under_review", "approved", "planning", "safety_check", "confirmed"];
const CLOSED_STATUSES = ["cancelled", "rejected", "completed"];
const STATUS_LABEL = {
  submitted: "Submitted", under_review: "Under review", approved: "Approved",
  planning: "Planning", safety_check: "Safety check", confirmed: "Confirmed",
};

const events = ref([]);
const coordinators = ref([]);
const loading = ref(true);
const error = ref("");
const coordinatorFilter = ref("all");
const statusFilter = ref("active");

const filtersOn = computed(() => coordinatorFilter.value !== "all" || statusFilter.value !== "active");

const visibleEvents = computed(() =>
  events.value.filter((e) => {
    if (statusFilter.value === "active" && !ACTIVE_STATUSES.includes(e.status)) return false;
    if (statusFilter.value === "closed" && !CLOSED_STATUSES.includes(e.status)) return false;
    if (!["active", "closed"].includes(statusFilter.value) && e.status !== statusFilter.value) return false;
    if (coordinatorFilter.value === "unassigned") return !e.coordinatorId;
    if (coordinatorFilter.value !== "all") return String(e.coordinatorId) === coordinatorFilter.value;
    return true;
  })
);

function isAssignable(e) {
  return ACTIVE_STATUSES.includes(e.status);
}

function clearFilters() {
  coordinatorFilter.value = "all";
  statusFilter.value = "active";
}

onMounted(async () => {
  try {
    const [all, coords] = await Promise.all([eventsApi.allEvents(), eventsApi.listCoordinators()]);
    events.value = all.data;
    coordinators.value = [...coords.data].sort((a, b) => a.name.localeCompare(b.name));
  } catch (e) {
    error.value = e.response?.data?.error || "Could not load the calendar.";
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
  align-items: flex-end;
  gap: 0.75rem 1.25rem;
  padding: 0.85rem 1rem;
  margin-bottom: 1rem;
}
label {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  font-size: 0.85rem;
  font-weight: 500;
}
select {
  min-width: 13rem;
  padding: 0.45rem 0.6rem;
  border: 1px solid var(--border, #e4defa);
  border-radius: 8px;
  background: #fff;
  font: inherit;
}
.btn-soft {
  padding: 0.45rem 0.9rem;
  border: none;
  border-radius: 999px;
  background: var(--primary-tint, #ebe7ff);
  color: var(--primary, #6d5bd0);
  font: inherit;
  font-weight: 500;
  cursor: pointer;
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
