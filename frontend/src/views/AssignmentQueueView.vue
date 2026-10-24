<template>
  <div>
    <h2 class="page-title">Assignment Queue</h2>
    <p class="hint">
      Every submitted request waits here until you assign it to a Coordinator. The least busy
      Coordinator is suggested first. The assigned Coordinator is notified, and the other Leads'
      notifications for the request are cleared.
    </p>

    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <p v-if="notice" class="notice" role="status">{{ notice }}</p>

    <h3 class="section-title">Unassigned ({{ unassigned.length }})</h3>
    <p v-if="loading">Loading...</p>
    <div v-else-if="!unassigned.length" class="card empty">No requests are waiting for assignment.</div>
    <ul v-else class="list">
      <li
        v-for="e in unassigned"
        :id="`request-${e.id}`"
        :key="e.id"
        :class="['card', { highlight: e.id === highlightId }]"
      >
        <div class="details">
          <router-link :to="`/events/${e.id}`" class="title">#{{ e.id }} {{ e.name || "(untitled)" }}</router-link>
          <dl>
            <dt>Requester</dt><dd>{{ e.organiserName || "—" }}</dd>
            <dt>Event type</dt><dd>{{ e.category || "Not specified" }}</dd>
            <dt>Event date</dt><dd>{{ formatEventDate(e.proposedDate, e.proposedTime) }}</dd>
            <dt>Submitted</dt><dd>{{ formatTimestamp(e.submittedAt) }}</dd>
          </dl>
        </div>
        <div class="assign">
          <label :for="`coord-${e.id}`">Coordinator</label>
          <select :id="`coord-${e.id}`" v-model.number="choice[e.id]">
            <option v-for="(c, i) in coordinators" :key="c.id" :value="c.id">
              {{ c.name }} — {{ c.openRequests }} open{{ i === 0 ? " (suggested)" : "" }}
            </option>
          </select>
          <button class="btn btn-primary" :disabled="!choice[e.id] || busyId !== null" @click="assign(e)">
            {{ busyId === e.id ? "Assigning..." : "Assign" }}
          </button>
        </div>
      </li>
    </ul>

    <h3 class="section-title">Assigned and in progress ({{ assigned.length }})</h3>
    <div v-if="!loading && !assigned.length" class="card empty">No assigned requests in progress.</div>
    <table v-else-if="assigned.length">
      <thead>
        <tr><th>Request</th><th>Status</th><th>Assigned to</th><th>Reassign to</th></tr>
      </thead>
      <tbody>
        <tr v-for="e in assigned" :key="e.id">
          <td><router-link :to="`/events/${e.id}`">#{{ e.id }} {{ e.name }}</router-link></td>
          <td>{{ e.statusLabel }}</td>
          <td>{{ e.coordinatorName }}</td>
          <td>
            <div class="reassign">
              <select v-model.number="reassignChoice[e.id]" :aria-label="`Reassign request ${e.id}`">
                <option :value="undefined" disabled>Select</option>
                <option v-for="c in coordinators.filter((c) => c.id !== e.coordinatorId)" :key="c.id" :value="c.id">
                  {{ c.name }} — {{ c.openRequests }} open
                </option>
              </select>
              <button class="btn" :disabled="!reassignChoice[e.id] || busyId !== null" @click="reassign(e)">
                Reassign
              </button>
            </div>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<script setup>
import { nextTick, onMounted, reactive, ref } from "vue";
import { useRoute } from "vue-router";
import eventsApi from "../api/events";
import { useConfirm } from "../composables/useConfirm";
import { formatEventDate, formatTimestamp } from "../utils/display";

const IN_PROGRESS = ["under_review", "approved", "planning", "safety_check", "confirmed"];

const route = useRoute();
const { confirm } = useConfirm();

const unassigned = ref([]);
const assigned = ref([]);
const coordinators = ref([]);
const choice = reactive({});
const reassignChoice = reactive({});
const loading = ref(true);
const busyId = ref(null);
const error = ref("");
const notice = ref("");
const highlightId = Number(route.query.event) || null;

async function load() {
  loading.value = true;
  try {
    const [queue, coords, all] = await Promise.all([
      eventsApi.unassignedEvents(),
      eventsApi.listCoordinators(),
      eventsApi.allEvents(),
    ]);
    coordinators.value = coords.data;
    unassigned.value = queue.data.filter((e) => e.status === "submitted");
    assigned.value = all.data.filter((e) => e.coordinatorId && IN_PROGRESS.includes(e.status));
    for (const e of unassigned.value) {
      if (!choice[e.id] && coordinators.value.length) choice[e.id] = coordinators.value[0].id;
    }
  } catch (e) {
    error.value = e.response?.data?.error || "Could not load the assignment queue.";
  } finally {
    loading.value = false;
  }
}

// The backend asks for confirmation (409 + requiresConfirmation) before acting,
// and refuses with 409 + assignedTo if another Lead got there first.
async function confirmAndRun(call, event, coordinatorId, doneMessage) {
  error.value = "";
  notice.value = "";
  busyId.value = event.id;
  try {
    try {
      await call(event.id, coordinatorId, false);
    } catch (e) {
      const body = e.response?.data || {};
      if (!body.requiresConfirmation) throw e;
      if (!(await confirm(body.message))) return;
    }
    await call(event.id, coordinatorId, true);
    notice.value = doneMessage;
  } catch (e) {
    const body = e.response?.data || {};
    error.value = body.assignedTo
      ? `Request #${event.id} is already assigned to ${body.assignedTo}.`
      : body.error || "That didn't work. Please try again.";
  } finally {
    busyId.value = null;
    await load();
  }
}

function nameOf(id) {
  return coordinators.value.find((c) => c.id === id)?.name || "the Coordinator";
}

function assign(event) {
  const id = choice[event.id];
  return confirmAndRun(eventsApi.leadAssign, event, id, `Request #${event.id} assigned to ${nameOf(id)}.`);
}

function reassign(event) {
  const id = reassignChoice[event.id];
  return confirmAndRun(eventsApi.leadReassign, event, id, `Request #${event.id} reassigned to ${nameOf(id)}.`);
}

onMounted(async () => {
  await load();
  if (highlightId) {
    await nextTick();
    document.getElementById(`request-${highlightId}`)?.scrollIntoView({ block: "center" });
    if (!unassigned.value.some((e) => e.id === highlightId)) {
      const taken = assigned.value.find((e) => e.id === highlightId);
      if (taken) notice.value = `Request #${taken.id} is already assigned to ${taken.coordinatorName}.`;
    }
  }
});
</script>

<style scoped>
.hint {
  color: var(--text-muted);
}

.section-title {
  margin-top: 1.5rem;
}

.list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: grid;
  gap: 0.6rem;
}

.card {
  display: flex;
  flex-wrap: wrap;
  gap: 1rem;
  justify-content: space-between;
  padding: 0.9rem 1rem;
  border: 1px solid var(--border);
  border-radius: 12px;
  background: var(--surface);
}

.card.highlight {
  border-color: var(--primary);
  box-shadow: 0 0 0 2px var(--primary-tint);
}

.card.empty {
  color: var(--text-muted);
}

.title {
  font-weight: 600;
  color: var(--text);
}

dl {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 0.15rem 0.75rem;
  margin: 0.4rem 0 0;
  font-size: 0.9rem;
}

dt {
  color: var(--text-muted);
}

dd {
  margin: 0;
}

.assign {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  min-width: 220px;
}

.reassign {
  display: flex;
  gap: 0.4rem;
  align-items: center;
}

.reassign select {
  min-width: 0;
  flex: 1;
}

select {
  padding: 0.35rem;
  border: 1px solid var(--border);
  border-radius: 8px;
  font: inherit;
}

.btn {
  padding: 0.4rem 0.9rem;
  border: none;
  border-radius: 999px;
  background: var(--lilac-bg);
  color: var(--lilac-text);
  font: inherit;
  font-weight: 500;
}

.btn-primary {
  background: var(--primary);
  color: #fff;
}

.btn:disabled {
  opacity: 0.5;
  cursor: default;
}

.error {
  color: var(--rose-text);
}

.notice {
  color: var(--mint-text);
}
</style>
