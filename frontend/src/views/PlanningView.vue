<template>
  <div class="planning-view">
    <h2 class="page-title">Planning View</h2>
    <p class="hint">
      All events, for planning visibility. Event Coordinator Leads assign
      Unassigned requests — there's no claim or self-assign action here.
    </p>

    <div class="controls">
      <div class="tabs" role="tablist" aria-label="Filter events">
        <button
          v-for="tab in tabs"
          :key="tab.key"
          type="button"
          role="tab"
          :aria-selected="activeTab === tab.key"
          :class="['tab', { active: activeTab === tab.key }]"
          @click="activeTab = tab.key"
        >
          {{ tab.label }} <span class="tab-count">{{ counts[tab.key] }}</span>
        </button>
      </div>
      <label class="sort">
        Sort by date
        <select v-model="sortDirection">
          <option value="asc">Soonest first</option>
          <option value="desc">Latest first</option>
        </select>
      </label>
    </div>

    <p v-if="loading">Loading...</p>
    <div v-else-if="filteredEvents.length === 0" class="card empty">No events in this view.</div>

    <div v-else class="card">
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Name</th>
              <th>Status</th>
              <th>Proposed Date/Time</th>
              <th>Expected Attendance</th>
              <th>Coordinator</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="e in filteredEvents" :key="e.id">
              <td class="name">{{ e.name || "(untitled)" }}</td>
              <td><StatusBadge :status="e.status" :label="e.statusLabel" /></td>
              <td class="muted">{{ e.proposedDate || "—" }} {{ e.proposedTime || "" }}</td>
              <td>{{ e.expectedAttendance ?? "—" }}</td>
              <td>
                <span v-if="!e.coordinatorId" class="unassigned">Unassigned</span>
                <span v-else-if="e.coordinatorId === auth.user?.id">Me</span>
                <span v-else>{{ e.coordinatorName || "—" }}</span>
              </td>
              <td class="action"><router-link :to="`/events/${e.id}`" class="view-link">View</router-link></td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from "vue";
import { useAuthStore } from "../stores/auth";
import eventsApi from "../api/events";
import StatusBadge from "../components/StatusBadge.vue";

const auth = useAuthStore();
const events = ref([]);
const loading = ref(true);
const activeTab = ref("all");
const sortDirection = ref("asc");

const tabs = [
  { key: "all", label: "All" },
  { key: "mine", label: "Assigned to me" },
  { key: "others", label: "Assigned to others" },
  { key: "unassigned", label: "Unassigned" },
];

async function load() {
  loading.value = true;
  // Source of truth is the same "all events" visibility every Coordinator
  // already has (GET /events) — the tabs are client-side filters of that list.
  const { data } = await eventsApi.allEvents();
  events.value = data;
  loading.value = false;
}

function categoryOf(e) {
  if (!e.coordinatorId) return "unassigned";
  return e.coordinatorId === auth.user?.id ? "mine" : "others";
}

const counts = computed(() => {
  const c = { unassigned: 0, mine: 0, others: 0, all: events.value.length };
  for (const e of events.value) c[categoryOf(e)]++;
  return c;
});

const filteredEvents = computed(() => {
  const base = activeTab.value === "all" ? events.value : events.value.filter((e) => categoryOf(e) === activeTab.value);
  return [...base].sort((a, b) => {
    const da = a.proposedDate ? new Date(a.proposedDate) : new Date(8640000000000000);
    const db = b.proposedDate ? new Date(b.proposedDate) : new Date(8640000000000000);
    return sortDirection.value === "asc" ? da - db : db - da;
  });
});

onMounted(load);
</script>

<style scoped>
.page-title {
  margin: 0 0 0.5rem;
  font-size: 1.5rem;
  font-weight: 600;
  color: var(--text, #2d2a4a);
}
.hint {
  margin: 0 0 1rem;
  color: var(--text-muted, #6b6890);
  font-size: 0.9rem;
}
.controls {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 1rem;
  flex-wrap: wrap;
  gap: 0.75rem;
}
.tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
}
.tab {
  padding: 0.4rem 0.9rem;
  border: none;
  border-radius: 999px;
  background: var(--lilac-bg, #e9e5fb);
  color: var(--lilac-text, #4b3fa0);
  font: inherit;
  font-weight: 500;
  cursor: pointer;
}
.tab.active {
  background: var(--primary, #6d5bd0);
  color: #fff;
}
.tab-count {
  margin-left: 0.2rem;
  opacity: 0.8;
}
.sort {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.9rem;
  color: var(--text-muted, #6b6890);
}
.sort select {
  padding: 0.35rem 0.5rem;
  border: 1px solid var(--border, #e4defa);
  border-radius: 8px;
  background: #fff;
  font: inherit;
}
/* Same card + table look as the Dashboard */
.card {
  background: var(--surface, #fff);
  border: 1px solid var(--border, #e4defa);
  border-radius: 14px;
  box-shadow: 0 4px 16px rgba(109, 91, 208, 0.08);
  overflow: hidden;
}
.card.empty {
  padding: 2rem 1rem;
  text-align: center;
  color: var(--text-muted, #6b6890);
}
.table-wrap {
  overflow-x: auto;
}
table {
  width: 100%;
  border-collapse: collapse;
  text-align: left;
}
th {
  padding: 0.75rem 1rem;
  background: #ddd6fb;
  border-bottom: 1px solid var(--border, #e4defa);
  font-size: 0.85rem;
  font-weight: 600;
  color: var(--lilac-text, #4b3fa0);
  white-space: nowrap;
}
td {
  padding: 0.85rem 1rem;
  border-bottom: 1px solid var(--border, #e4defa);
  color: var(--text, #2d2a4a);
}
tbody tr:last-child td {
  border-bottom: none;
}
tbody tr:hover {
  background: #faf9ff;
}
.name {
  font-weight: 500;
}
.muted {
  color: var(--text-muted, #6b6890);
}
.unassigned {
  padding: 0.1rem 0.55rem;
  border: 1.5px dashed #d97706;
  border-radius: 999px;
  background: #fff7e6;
  color: #8a4b00;
  font-size: 0.8rem;
  white-space: nowrap;
}
.action {
  text-align: right;
}
.view-link {
  color: var(--primary, #6d5bd0);
  font-weight: 500;
  text-decoration: none;
}
.view-link:hover {
  text-decoration: underline;
}
</style>
