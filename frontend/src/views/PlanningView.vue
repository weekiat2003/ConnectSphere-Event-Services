<template>
  <div class="planning-view">
    <h2>Planning View</h2>
    <p class="hint">
      All events, for planning visibility. Assignment is automatic —
      there's no claim or self-assign action here.
    </p>

    <div class="controls">
      <div class="tabs">
        <button
          v-for="tab in tabs"
          :key="tab.key"
          :class="{ active: activeTab === tab.key }"
          @click="activeTab = tab.key"
        >
          {{ tab.label }} ({{ counts[tab.key] }})
        </button>
      </div>
      <label>
        Sort by date
        <select v-model="sortDirection">
          <option value="asc">Soonest first</option>
          <option value="desc">Latest first</option>
        </select>
      </label>
    </div>

    <p v-if="loading">Loading...</p>
    <p v-else-if="filteredEvents.length === 0" class="empty-state">No events in this view.</p>

    <table v-else>
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
          <td>{{ e.name || "(untitled)" }}</td>
          <td><span class="badge" :class="e.status">{{ e.status.replaceAll("_", " ") }}</span></td>
          <td>{{ e.proposedDate || "—" }} {{ e.proposedTime || "" }}</td>
          <td>{{ e.expectedAttendance ?? "—" }}</td>
          <td>
            <span v-if="!e.coordinatorId" class="badge unassigned">Unassigned</span>
            <span v-else-if="e.coordinatorId === auth.user?.id">Me</span>
            <span v-else>{{ e.coordinatorName || "—" }}</span>
          </td>
          <td><router-link :to="`/events/${e.id}`">View</router-link></td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from "vue";
import { useAuthStore } from "../stores/auth";
import eventsApi from "../api/events";

const auth = useAuthStore();
const events = ref([]);
const loading = ref(true);
const activeTab = ref("unassigned");
const sortDirection = ref("asc");

const tabs = [
  { key: "unassigned", label: "Unassigned" },
  { key: "mine", label: "Assigned to me" },
  { key: "others", label: "Assigned to others" },
  { key: "all", label: "All" },
];

async function load() {
  loading.value = true;
  // Source of truth is the same "all events" visibility every Coordinator
  // already has (GET /events, unchanged) — unassigned/mine/others are just
  // client-side categorizations of that one list, so this single view can
  // filter between them instead of being a separate unassigned-only page.
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
  const sorted = [...base].sort((a, b) => {
    const da = a.proposedDate ? new Date(a.proposedDate) : new Date(8640000000000000);
    const db = b.proposedDate ? new Date(b.proposedDate) : new Date(8640000000000000);
    return sortDirection.value === "asc" ? da - db : db - da;
  });
  return sorted;
});

onMounted(load);
</script>

<style scoped>
.hint {
  color: #666;
  font-size: 0.9rem;
}
.controls {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin: 1rem 0;
  flex-wrap: wrap;
  gap: 0.75rem;
}
.tabs {
  display: flex;
  gap: 0.5rem;
}
.tabs button {
  padding: 0.4rem 0.75rem;
  border: 1px solid #ccc;
  border-radius: 999px;
  background: #fff;
  cursor: pointer;
}
.tabs button.active {
  background: #2b2d42;
  color: #fff;
  border-color: #2b2d42;
}
.badge {
  padding: 0.15rem 0.5rem;
  border-radius: 999px;
  background: #eee;
  font-size: 0.8rem;
  text-transform: capitalize;
}
.badge.approved, .badge.confirmed, .badge.completed { background: #d7f5dd; }
.badge.rejected, .badge.cancelled { background: #fbdcdc; }
.badge.under_review, .badge.submitted, .badge.planning, .badge.safety_check { background: #fff3cd; }
.badge.unassigned { background: #ffe0b2; }
.empty-state {
  color: #666;
}
</style>
