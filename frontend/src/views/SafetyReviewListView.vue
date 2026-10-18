<template>
  <div class="safety-list">
    <h2 class="page-title">Safety Reviews</h2>
    <p class="hint">Events whose venue and equipment arrangements are ready and are awaiting your safety check.</p>

    <p v-if="loading" class="hint">Loading…</p>
    <p v-else-if="error" class="notice error">{{ error }}</p>
    <div v-else-if="events.length === 0" class="card empty-state">
      No events are awaiting a safety check.
    </div>

    <div v-else class="card table-card">
      <table>
        <thead>
          <tr>
            <th>Event</th>
            <th>Date</th>
            <th>Venue(s)</th>
            <th class="num">Expected attendance</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="e in events" :key="e.id">
            <td>
              <span class="event-name">{{ orNotSpecified(e.name) }}</span>
              <span v-if="e.assessmentInProgress" class="badge in-progress">Assessment in progress</span>
            </td>
            <td>{{ formatEventDate(e.proposedDate, e.proposedTime) }}</td>
            <td>
              <template v-if="e.venues.length">{{ e.venues.map((v) => v.name).join(", ") }}</template>
              <span v-else class="missing">Not specified</span>
            </td>
            <td class="num">
              <template v-if="e.expectedAttendance != null">{{ e.expectedAttendance }}</template>
              <span v-else class="missing">Not specified</span>
            </td>
            <td class="action">
              <router-link class="btn btn-primary" :to="`/safety-reviews/${e.id}`">
                {{ e.assessmentInProgress ? "Continue" : "Review" }}
              </router-link>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import eventsApi from "../api/events";
import { formatEventDate, orNotSpecified } from "../utils/display";

const router = useRouter();
const events = ref([]);
const loading = ref(true);
const error = ref("");

onMounted(async () => {
  try {
    const { data } = await eventsApi.listSafetyReviews();
    events.value = data;
  } catch (e) {
    if (e.response?.status === 403) {
      router.replace({ name: "access-denied" });
      return;
    }
    error.value = e.response?.data?.error || "Could not load the safety review list.";
  } finally {
    loading.value = false;
  }
});
</script>

<style scoped>
.page-title {
  margin: 0;
  font-size: 1.5rem;
  font-weight: 600;
}
.hint {
  color: var(--text-muted, #6b6890);
  font-size: 0.9rem;
}
.card {
  margin-top: 1rem;
  padding: 1.25rem 1.5rem;
  background: var(--surface, #ffffff);
  border: 1px solid var(--border, #e4defa);
  border-radius: 14px;
  box-shadow: 0 4px 16px rgba(109, 91, 208, 0.08);
}
.table-card {
  padding: 0.5rem 0.75rem;
  overflow-x: auto;
}
.empty-state {
  color: var(--text-muted, #6b6890);
}
th {
  font-size: 0.8rem;
  font-weight: 600;
  color: var(--text-muted, #6b6890);
  text-transform: uppercase;
  letter-spacing: 0.03em;
}
td {
  vertical-align: middle;
}
tbody tr:last-child td {
  border-bottom: none;
}
.num {
  text-align: right;
  font-variant-numeric: tabular-nums;
}
.action {
  text-align: right;
  white-space: nowrap;
}
.event-name {
  font-weight: 500;
  margin-right: 0.5rem;
}
.missing {
  color: var(--text-muted, #6b6890);
  font-style: italic;
}
.badge {
  display: inline-block;
  padding: 0.1rem 0.55rem;
  border-radius: 999px;
  font-size: 0.75rem;
  font-weight: 500;
}
.badge.in-progress {
  background: var(--sky-bg, #d6ecff);
  color: var(--sky-text, #1f5f99);
}
.btn {
  display: inline-block;
  padding: 0.4rem 1rem;
  border-radius: 999px;
  font-size: 0.85rem;
  font-weight: 500;
  text-decoration: none;
}
.btn-primary {
  background: var(--primary, #6d5bd0);
  color: #ffffff;
}
.btn-primary:hover {
  background: var(--primary-hover, #5b49bd);
}
.notice.error {
  padding: 0.85rem 1rem;
  border-radius: 12px;
  background: var(--rose-bg, #ffdce3);
  color: var(--rose-text, #a12b47);
}
</style>
