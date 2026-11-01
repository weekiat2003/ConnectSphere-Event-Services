<template>
  <div>
    <h2 class="page-title">Coordinator Supervision</h2>
    <p class="hint">
      Each active Event Coordinator and the active events currently assigned to them
      (under review through confirmed). Reassign from the
      <router-link to="/assignments">Assignment Queue</router-link>.
    </p>

    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <p v-if="loading">Loading...</p>
    <div v-else-if="!coordinators.length" class="card empty">There are no active Event Coordinators.</div>

    <section v-for="c in coordinators" v-else :key="c.id" class="card">
      <header>
        <h3>{{ c.name }}</h3>
        <span class="count">{{ c.activeEventCount }} active event{{ c.activeEventCount === 1 ? "" : "s" }}</span>
      </header>
      <p v-if="!c.events.length" class="muted">No active events assigned.</p>
      <table v-else>
        <thead>
          <tr><th>Request</th><th>Organiser</th><th>Event date</th><th>Attendance</th><th>Status</th></tr>
        </thead>
        <tbody>
          <tr v-for="e in c.events" :key="e.id">
            <td><router-link :to="`/events/${e.id}`">#{{ e.id }} {{ e.name || "(untitled)" }}</router-link></td>
            <td>{{ e.organiserName || "—" }}</td>
            <td>{{ formatEventDate(e.proposedDate, e.proposedTime) }}</td>
            <td>{{ e.expectedAttendance ?? "—" }}</td>
            <td><StatusBadge :status="e.status" :label="e.statusLabel" /></td>
          </tr>
        </tbody>
      </table>
    </section>
  </div>
</template>

<script setup>
import { onMounted, ref } from "vue";
import eventsApi from "../api/events";
import StatusBadge from "../components/StatusBadge.vue";
import { formatEventDate } from "../utils/display";

const coordinators = ref([]);
const loading = ref(true);
const error = ref("");

onMounted(async () => {
  try {
    coordinators.value = (await eventsApi.supervision()).data;
  } catch (e) {
    error.value = e.response?.data?.error || "Could not load the supervision view.";
  } finally {
    loading.value = false;
  }
});
</script>

<style scoped>
.hint,
.muted {
  color: var(--text-muted);
}

.card {
  margin-top: 0.8rem;
  padding: 0.9rem 1rem;
  border: 1px solid var(--border);
  border-radius: 12px;
  background: var(--surface);
  overflow-x: auto;
}

.card.empty {
  color: var(--text-muted);
}

header {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 1rem;
}

h3 {
  margin: 0;
}

.count {
  font-size: 0.9rem;
  color: var(--text-muted);
}

table {
  width: 100%;
  margin-top: 0.5rem;
  border-collapse: collapse;
  font-size: 0.9rem;
}

th,
td {
  text-align: left;
  padding: 0.35rem 0.5rem;
  border-bottom: 1px solid var(--border);
}

.error {
  color: var(--rose-text);
}
</style>
