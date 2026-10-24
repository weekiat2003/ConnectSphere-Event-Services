<template>
  <div>
    <h2 class="page-title">Review Queue</h2>

    <div v-if="events.length" class="card">
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Name</th>
              <th>Status</th>
              <th>Proposed Date/Time</th>
              <th>Venue Reqs.</th>
              <th>Organiser</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="e in events" :key="e.id">
              <td class="name">{{ e.name }}</td>
              <td>
                <span class="badge" :class="e.status">{{ e.statusLabel || "Unknown status" }}</span>              
              </td>
              <td class="muted">{{ e.proposedDate || "—" }} {{ e.proposedTime || "" }}</td>
              <td>{{ venueSummary(e) }}</td>
              <td>{{ e.organiserName || "—" }}</td>
              <td class="action">
                <router-link :to="`/events/${e.id}`" class="review-link">Review</router-link>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <div v-else class="card empty">
      <p>No assigned requests.</p>
    </div>

  </div>
</template>

<script setup>
import { onMounted, ref } from "vue";
import eventsApi from "../api/events";

const events = ref([]);


function venueSummary(e) {
  const v = e.venueRequirements;
  if (!v || (!v.capacityNeeded && !v.requiredLayout)) return "—";
  return [v.capacityNeeded ? `${v.capacityNeeded} pax` : null, v.requiredLayout].filter(Boolean).join(", ");
}

onMounted(async () => {
  const { data } = await eventsApi.assignedEvents();
  events.value = data;
});
</script>

<style scoped>
.page-title {
  margin: 0 0 1rem;
  font-size: 1.5rem;
  font-weight: 600;
  color: var(--text, #2d2a4a);
}

.card {
  background: var(--surface, #ffffff);
  border: 1px solid var(--border, #e4defa);
  border-radius: 14px;
  box-shadow: 0 4px 16px rgba(109, 91, 208, 0.08);
  overflow: hidden;
}

/* Lets the table scroll sideways on small screens */
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

.action {
  text-align: right;
}

.review-link {
  display: inline-block;
  padding: 0.3rem 0.9rem;
  border-radius: 999px;
  background: var(--primary-tint, #ebe7ff);
  color: var(--primary, #6d5bd0);
  font-size: 0.9rem;
  font-weight: 500;
  text-decoration: none;
}

.review-link:hover {
  background: var(--primary, #6d5bd0);
  color: #ffffff;
}

.review-link:focus-visible {
  outline: 2px solid var(--primary, #6d5bd0);
  outline-offset: 2px;
}

/* Status badges */
.badge {
  display: inline-block;
  padding: 0.15rem 0.65rem;
  border-radius: 999px;
  background: var(--lilac-bg, #e9e5fb);
  color: var(--lilac-text, #4b3fa0);
  font-size: 0.8rem;
  font-weight: 500;
  text-transform: capitalize;
  white-space: nowrap;
}

.badge.approved,
.badge.confirmed,
.badge.completed {
  background: var(--mint-bg, #d3f5e3);
  color: var(--mint-text, #1e6b47);
}

.badge.rejected,
.badge.cancelled {
  background: var(--rose-bg, #ffdce3);
  color: var(--rose-text, #a12b47);
}

.badge.under_review,
.badge.submitted {
  background: var(--butter-bg, #fff1c2);
  color: var(--butter-text, #8a5a00);
}

.badge.planning {
  background: var(--sky-bg, #d6ecff);
  color: var(--sky-text, #1f5f99);
}

/* Empty state */
.empty {
  padding: 2rem 1rem;
  text-align: center;
  color: var(--text-muted, #6b6890);
}

.empty p {
  margin: 0;
}
</style>