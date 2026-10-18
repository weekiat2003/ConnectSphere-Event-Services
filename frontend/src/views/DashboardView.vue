<template>
  <div>
    <h2 class="page-title">
      {{ auth.hasRole("event_coordinator") ? "Events Assigned to Me" : "My Events" }}
    </h2>

    <template v-if="events.length">
      <!-- Summary counts, worked out from the events list -->
      <div class="stats">
        <div class="stat sky">
          <span class="stat-num">{{ stats.total }}</span>
          <span class="stat-label">All events</span>
        </div>
        <div class="stat butter">
          <span class="stat-num">{{ stats.review }}</span>
          <span class="stat-label">In review</span>
        </div>
        <div class="stat mint">
          <span class="stat-num">{{ stats.approved }}</span>
          <span class="stat-label">Approved</span>
        </div>
        <div class="stat rose">
          <span class="stat-num">{{ stats.closed }}</span>
          <span class="stat-label">Rejected or cancelled</span>
        </div>
      </div>

      <div class="card">
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Status</th>
                <th>Proposed Date/Time</th>
                <th>Venue Reqs.</th>
                <th v-if="auth.hasRole('event_coordinator')">Organiser</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="e in events" :key="e.id">
                <td class="name">{{ e.name || "(untitled)" }}</td>
                <td>
                  <span class="badge" :class="e.status">{{ statusLabel(e.status) }}</span>
                </td>
                <td class="muted">{{ e.proposedDate || "—" }} {{ e.proposedTime || "" }}</td>
                <td>{{ venueSummary(e) }}</td>
                <td v-if="auth.hasRole('event_coordinator')">{{ e.organiserName || "—" }}</td>
                <td class="action">
                  <router-link :to="`/events/${e.id}`" class="view-link">View</router-link>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </template>

    <div v-else class="card empty">
      <p>No events yet.</p>
      <router-link v-if="auth.hasRole('event_organiser')" to="/events/new" class="btn">
        Create an event
      </router-link>
    </div>

  </div>
</template>

<script setup>
import { computed, onMounted, ref } from "vue";
import { useAuthStore } from "../stores/auth";
import eventsApi from "../api/events";

const auth = useAuthStore();
const events = ref([]);


// Summary for the "Venue Reqs." column — this project doesn't have an actual
// booked-venue entity yet (only what the Organiser requested), so this shows
// requirements, not a confirmed venue.
function venueSummary(e) {
  const v = e.venueRequirements;
  if (!v || (!v.capacityNeeded && !v.requiredLayout)) return "—";
  return [v.capacityNeeded ? `${v.capacityNeeded} pax` : null, v.requiredLayout].filter(Boolean).join(", ");
}

// "under_review" -> "under review"
const statusLabel = (status) => (status || "").replace(/_/g, " ");

const stats = computed(() => {
  const count = (list) => events.value.filter((e) => list.includes(e.status)).length;
  return {
    total: events.value.length,
    review: count(["under_review", "submitted"]),
    approved: count(["approved", "confirmed", "completed"]),
    closed: count(["rejected", "cancelled"]),
  };
});


onMounted(async () => {
  const call = auth.hasRole("safety_officer")
    ? eventsApi.allEvents
    : auth.hasRole("event_coordinator")
      ? eventsApi.assignedEvents
      : eventsApi.myEvents;
  const { data } = await call();
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

/* Summary cards */
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

.stat.sky { background: var(--sky-bg, #d6ecff); color: var(--sky-text, #1f5f99); }
.stat.butter { background: var(--butter-bg, #fff1c2); color: var(--butter-text, #8a5a00); }
.stat.mint { background: var(--mint-bg, #d3f5e3); color: var(--mint-text, #1e6b47); }
.stat.rose { background: var(--rose-bg, #ffdce3); color: var(--rose-text, #a12b47); }

/* Card around the table */
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

.view-link {
  color: var(--primary, #6d5bd0);
  font-weight: 500;
  text-decoration: none;
}

.view-link:hover {
  color: var(--primary-hover, #5b49bd);
  text-decoration: underline;
}

.view-link:focus-visible,
.btn:focus-visible {
  outline: 2px solid var(--primary, #6d5bd0);
  outline-offset: 2px;
  border-radius: 4px;
}

/* Status badges: pastel background, darker text of the same colour */
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
  margin: 0 0 1rem;
}

.btn {
  display: inline-block;
  padding: 0.5rem 1.1rem;
  border-radius: 999px;
  background: var(--primary, #6d5bd0);
  color: #ffffff;
  font-weight: 500;
  text-decoration: none;
}

.btn:hover {
  background: var(--primary-hover, #5b49bd);
}
</style>