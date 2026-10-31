<template>
  <div>
    <h2 class="page-title">Lead Dashboard</h2>

    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <p v-if="loading">Loading...</p>

    <template v-else>
      <div class="stats">
        <router-link to="/assignments" class="stat butter">
          <span class="stat-num">{{ unassigned.length }}</span>
          <span class="stat-label">Waiting for assignment</span>
        </router-link>
        <router-link to="/assignments#reassignment-requests" class="stat rose">
          <span class="stat-num">{{ requests.length }}</span>
          <span class="stat-label">Reassignment requests</span>
        </router-link>
        <router-link to="/lead/calendar" class="stat sky">
          <span class="stat-num">{{ activeCount }}</span>
          <span class="stat-label">Active events</span>
        </router-link>
        <router-link to="/supervision" class="stat mint">
          <span class="stat-num">{{ coordinators.length }}</span>
          <span class="stat-label">Active coordinators</span>
        </router-link>
      </div>

      <section class="card">
        <h3 class="card-title">Needs your attention</h3>
        <p v-if="!attention.length" class="empty">Nothing to assign or reassign right now.</p>
        <div v-else class="table-wrap">
          <table>
            <thead>
              <tr><th>Request</th><th>Why</th><th>Event date</th><th>Status</th><th></th></tr>
            </thead>
            <tbody>
              <tr v-for="row in attention" :key="row.key">
                <td class="name">#{{ row.id }} {{ row.name || "(untitled)" }}</td>
                <td>{{ row.why }}</td>
                <td class="muted">{{ formatEventDate(row.date, row.time) }}</td>
                <td><StatusBadge :status="row.status" :label="row.statusLabel" /></td>
                <td class="action">
                  <router-link :to="{ name: 'assignments', query: { event: row.id } }" class="view-link">
                    {{ row.action }}
                  </router-link>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section class="card">
        <h3 class="card-title">Coordinator workload</h3>
        <div class="table-wrap">
          <table>
            <thead>
              <tr><th>Coordinator</th><th>Active events</th><th>Next event</th><th></th></tr>
            </thead>
            <tbody>
              <tr v-for="c in coordinators" :key="c.id">
                <td class="name">{{ c.name }}</td>
                <td>{{ c.activeEventCount }}</td>
                <td class="muted">
                  <span v-if="c.events.length">
                    {{ c.events[0].name }} · {{ formatEventDate(c.events[0].proposedDate, c.events[0].proposedTime) }}
                  </span>
                  <span v-else>—</span>
                </td>
                <td class="action"><router-link to="/supervision" class="view-link">View</router-link></td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </template>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from "vue";
import eventsApi from "../api/events";
import StatusBadge from "../components/StatusBadge.vue";
import { formatEventDate } from "../utils/display";

const unassigned = ref([]);
const requests = ref([]);
const coordinators = ref([]);
const allEvents = ref([]);
const loading = ref(true);
const error = ref("");

const ACTIVE = ["submitted", "under_review", "approved", "planning", "safety_check", "confirmed"];
const activeCount = computed(() => allEvents.value.filter((e) => ACTIVE.includes(e.status)).length);

const attention = computed(() => {
  const byId = Object.fromEntries(allEvents.value.map((e) => [e.id, e]));
  const rows = unassigned.value.map((e) => ({
    key: `u${e.id}`, id: e.id, name: e.name, date: e.proposedDate, time: e.proposedTime,
    status: e.status, statusLabel: e.statusLabel, why: "Not assigned yet", action: "Assign",
  }));
  for (const r of requests.value) {
    const e = byId[r.eventId] || {};
    rows.push({
      key: `r${r.id}`, id: r.eventId, name: r.eventName, date: e.proposedDate, time: e.proposedTime,
      status: e.status, statusLabel: e.statusLabel,
      why: `${r.requestedByName} asked to be reassigned`, action: "Review",
    });
  }
  return rows;
});

// Each part loads on its own, so one failing request only hides that part.
onMounted(async () => {
  const parts = [
    ["the unassigned requests", eventsApi.unassignedEvents, (d) => (unassigned.value = d.filter((e) => e.status === "submitted"))],
    ["the reassignment requests", eventsApi.listReassignmentRequests, (d) => (requests.value = d)],
    ["coordinator workload", eventsApi.supervision, (d) => (coordinators.value = d)],
    ["the events", eventsApi.allEvents, (d) => (allEvents.value = d)],
  ];
  const results = await Promise.allSettled(parts.map(([, call]) => call()));
  const failed = [];
  results.forEach((r, i) => {
    if (r.status === "fulfilled") parts[i][2](r.value.data);
    else failed.push(parts[i][0]);
  });
  if (failed.length) error.value = `Could not load ${failed.join(", ")}. The rest of the dashboard is shown.`;
  loading.value = false;
});
</script>

<style scoped>
.page-title {
  margin: 0 0 1rem;
  font-size: 1.5rem;
  font-weight: 600;
}
.stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 0.75rem;
  margin-bottom: 1rem;
}
.stat {
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
  padding: 1rem 1.1rem;
  border-radius: 14px;
  text-decoration: none;
}
.stat:hover {
  filter: brightness(0.97);
}
.stat-num {
  font-size: 1.75rem;
  font-weight: 600;
  line-height: 1.1;
}
.stat-label {
  font-size: 0.85rem;
  font-weight: 500;
}
.stat.sky { background: var(--sky-bg); color: var(--sky-text); }
.stat.butter { background: var(--butter-bg); color: var(--butter-text); }
.stat.mint { background: var(--mint-bg); color: var(--mint-text); }
.stat.rose { background: var(--rose-bg); color: var(--rose-text); }
.card {
  margin-bottom: 1rem;
  background: var(--surface, #fff);
  border: 1px solid var(--border, #e4defa);
  border-radius: 14px;
  box-shadow: 0 4px 16px rgba(109, 91, 208, 0.08);
  overflow: hidden;
}
.card-title {
  margin: 0;
  padding: 0.85rem 1rem;
  font-size: 1rem;
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
  padding: 0.7rem 1rem;
  background: #ddd6fb;
  font-size: 0.85rem;
  font-weight: 600;
  color: var(--lilac-text, #4b3fa0);
  white-space: nowrap;
}
td {
  padding: 0.75rem 1rem;
  border-top: 1px solid var(--border, #e4defa);
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
.action {
  text-align: right;
  white-space: nowrap;
}
.view-link {
  color: var(--primary, #6d5bd0);
  font-weight: 500;
  text-decoration: none;
}
.view-link:hover {
  text-decoration: underline;
}
.empty {
  margin: 0;
  padding: 0 1rem 1rem;
  color: var(--text-muted, #6b6890);
}
.error {
  color: var(--rose-text, #a12b47);
}
</style>
