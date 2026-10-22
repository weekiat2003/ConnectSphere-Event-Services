<template>
  <div>
    <h2 class="page-title">Technical Review: Equipment Requirements</h2>
    <p v-if="error" class="error">{{ error }}</p>
    <p v-if="loading" class="loading">Loading…</p>
    <div v-else-if="!events.length" class="card empty"><p>No events to review yet.</p></div>


    <div v-for="event in events" :key="event.id" class="card">
      <div class="card-head">
        <router-link :to="{ name: 'event-detail', params: { id: event.id } }" class="event-name">{{ event.name }}</router-link>
        <span class="muted">{{ event.proposedDate || "—" }}</span>
        <span class="badge badge-neutral">{{ event.statusLabel || event.status }}</span>
      </div>
      <p v-if="!event.equipmentRequirements.length" class="muted empty-note">
        No equipment requirements for this event.
      </p>
      <table v-else class="req-table">
        <thead>
          <tr>
            <th>Type</th><th>Qty</th><th>Technical requirements</th><th>Status</th>
            <th>Reserved</th><th>Testing</th><th>Installation</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="req in event.equipmentRequirements" :key="req.id">
            <td>{{ req.type }}</td>
            <td>{{ req.quantity }}</td>
            <td>{{ req.technicalNotes || "—" }}</td>
            <td>
              <span :class="['badge', badgeClass(req.status)]">{{ statusText(req.status) }}</span>
              <span v-if="req.needsRecheck" class="badge badge-warn">Needs recheck</span>
            </td>
            <td>{{ reservationText(req.reservation) }}</td>
            <td><span class="badge badge-neutral">{{ prepText(req.testingStatus) }}</span></td>
            <td><span class="badge badge-neutral">{{ prepText(req.installationStatus) }}</span></td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>


<script setup>
import { onMounted, ref } from "vue";
import eventsApi from "../api/events";
import equipmentApi from "../api/equipment";


const STATUS = { requested: "Requested", confirmed: "Reserved", unavailable: "Unavailable" };
const PREPARATION = { pending: "Pending", in_progress: "In progress", done: "Done" };
const HIDDEN_EVENT_STATUSES = ["draft", "cancelled", "rejected", "completed"];


const events = ref([]);
const loading = ref(true);
const error = ref("");


function message(e, fallback) { return e.response?.data?.error || fallback; }
function statusText(s) { return STATUS[s] || s; }
function prepText(s) { return PREPARATION[s] || s; }
function badgeClass(s) {
  if (s === "confirmed") return "badge-ok";
  if (s === "unavailable") return "badge-bad";
  return "badge-neutral";
}
function formatTime(iso) { return new Date(iso).toLocaleString([], { dateStyle: "medium", timeStyle: "short" }); }
function reservationText(r) {
  if (!r) return "—";
  return `${r.quantity} × ${formatTime(r.start)} to ${formatTime(r.end)}`;
}


async function load() {
  loading.value = true;
  try {
    const { data } = await eventsApi.allEvents();
    const visible = data.filter((e) => !HIDDEN_EVENT_STATUSES.includes(e.status));

    // Reservation details come from the technical review endpoint.
    const results = await Promise.allSettled(
      visible.map((e) => equipmentApi.eventRequirements(e.id))
    );
    let failed = 0;
    results.forEach((result, i) => {
      if (result.status !== "fulfilled") {
        failed += 1;
        return;
      }
      const byId = new Map(result.value.data.requirements.map((r) => [r.id, r.reservation]));
      visible[i].equipmentRequirements.forEach((req) => {
        req.reservation = byId.get(req.id) || null;
      });
    });
    if (failed) error.value = "Could not load reservation details for some events.";
    events.value = visible;
  } catch (e) {
    error.value = message(e, "Could not load events.");
  } finally {
    loading.value = false;
  }
}


onMounted(load);
</script>


<style scoped>
.page-title { margin: 0 0 1rem; font-size: 1.5rem; font-weight: 600; color: var(--text, #2d2a4a); }
.card { background: var(--surface, #fff); border: 1px solid var(--border, #e4defa); border-radius: 14px;
  box-shadow: 0 4px 16px rgba(109, 91, 208, 0.08); padding: 1rem; margin-bottom: 1rem; }
.card-head { display: flex; flex-wrap: wrap; align-items: center; gap: 0.75rem; margin-bottom: 0.75rem; }
.event-name { font-weight: 600; font-size: 1.05rem; color: var(--primary, #6d5bd0); text-decoration: none; }
.muted { color: var(--text-muted, #6b6890); font-size: 0.9rem; }
.empty-note { margin: 0; }
.req-table { width: 100%; border-collapse: collapse; }
.req-table th, .req-table td { text-align: left; padding: 0.5rem 0.6rem; border-bottom: 1px solid var(--border, #e4defa); }
.req-table th { font-size: 0.8rem; color: var(--text-muted, #6b6890); font-weight: 500; }
.badge { padding: 0.15rem 0.6rem; border-radius: 999px; font-size: 0.8rem; font-weight: 500; margin-right: 0.35rem; }
.badge-ok { background: #d9f5e3; color: #1f7a45; }
.badge-warn { background: #ffe9c7; color: #8a5a00; }
.badge-bad { background: #ffdce3; color: #a12b47; }
.badge-neutral { background: #ece8fb; color: #4b3fa0; }
.error { margin: 0 0 1rem; padding: 0.6rem 0.9rem; border-radius: 10px; background: var(--rose-bg, #ffdce3);
  color: var(--rose-text, #a12b47); font-size: 0.9rem; }
.empty { text-align: center; color: var(--text-muted, #6b6890); }
.loading { color: var(--text-muted, #6b6890); }
</style>