<template>
  <div>
    <h2 class="page-title">Assignment Queue</h2>
    <p class="hint">
      Every submitted request waits here until you assign it to a Coordinator. The least busy
      Coordinator is suggested first. The Coordinator (and on reassignment, the previous one) and
      the organiser are notified, and the other Leads' notifications for the request are cleared.
    </p>

    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <p v-if="notice" class="notice" role="status">{{ notice }}</p>

    <!-- Unassigned ------------------------------------------------------- -->
    <h3 class="section-title">Unassigned ({{ unassigned.length }})</h3>
    <p v-if="loading">Loading...</p>
    <div v-else-if="!unassigned.length" class="card empty">No requests are waiting for assignment.</div>
    <ul v-else class="list">
      <li
        v-for="e in unassigned"
        :id="`request-${e.id}`"
        :key="e.id"
        :class="['card', 'request', { highlight: e.id === highlightId }]"
      >
        <div class="details">
          <div class="title-row">
            <router-link :to="`/events/${e.id}`" class="title">#{{ e.id }} {{ e.name || "(untitled)" }}</router-link>
            <StatusBadge :status="e.status" :label="e.statusLabel" />
          </div>
          <dl>
            <dt>Requester</dt><dd>{{ e.organiserName || "—" }}</dd>
            <dt>Event type</dt><dd>{{ e.category || "Not specified" }}</dd>
            <dt>Event date</dt><dd>{{ formatEventDate(e.proposedDate, e.proposedTime) }}</dd>
            <dt>Attendance</dt><dd>{{ e.expectedAttendance ?? "Not specified" }}</dd>
            <dt>Submitted</dt><dd>{{ formatTimestamp(e.submittedAt) }}</dd>
          </dl>
        </div>
        <div class="assign">
          <label :for="`coord-${e.id}`">Coordinator</label>
          <select :id="`coord-${e.id}`" v-model.number="choice[e.id]">
            <option v-for="(c, i) in coordinators" :key="c.id" :value="c.id">
              {{ coordinatorOption(c) }}{{ i === 0 ? " (suggested)" : "" }}
            </option>
          </select>
          <button class="btn btn-primary" :disabled="!choice[e.id] || busyId !== null" @click="assign(e)">
            {{ busyId === e.id ? "Assigning..." : "Assign" }}
          </button>
        </div>
      </li>
    </ul>

    <!-- Reassignment requests from Coordinators -------------------------- -->
    <h3 id="reassignment-requests" class="section-title">Reassignment requests ({{ requests.length }})</h3>
    <p v-if="requestsError" class="error" role="alert">{{ requestsError }}</p>
    <div v-else-if="!loading && !requests.length" class="card empty">No Coordinator has asked to be reassigned.</div>
    <ul v-else-if="requests.length" class="list">
      <li
        v-for="r in requests"
        :id="`reassignment-${r.eventId}`"
        :key="r.id"
        :class="['card', 'request', { highlight: r.eventId === highlightId }]"
      >
        <div class="details">
          <div class="title-row">
            <router-link :to="`/events/${r.eventId}`" class="title">#{{ r.eventId }} {{ r.eventName || "(untitled)" }}</router-link>
            <StatusBadge v-if="eventById(r.eventId)" :status="eventById(r.eventId).status" :label="eventById(r.eventId).statusLabel" />
          </div>
          <dl>
            <dt>Asked by</dt><dd>{{ r.requestedByName }} (current Coordinator)</dd>
            <dt>Asked on</dt><dd>{{ formatTimestamp(r.createdAt) }}</dd>
            <dt>Event date</dt>
            <dd>{{ formatEventDate(eventById(r.eventId)?.proposedDate, eventById(r.eventId)?.proposedTime) }}</dd>
            <dt>Reason</dt><dd class="reason">{{ r.reason }}</dd>
          </dl>
        </div>
        <div class="assign">
          <label :for="`req-${r.id}`">Reassign to</label>
          <select :id="`req-${r.id}`" v-model.number="reassignChoice[r.eventId]">
            <option :value="undefined">Select a Coordinator</option>
            <option v-for="c in coordinators.filter((c) => c.id !== r.requestedById)" :key="c.id" :value="c.id">
              {{ coordinatorOption(c) }}
            </option>
          </select>
          <button
            class="btn btn-primary"
            :disabled="!reassignChoice[r.eventId] || busyId !== null"
            @click="reassign(eventById(r.eventId) || { id: r.eventId })"
          >
            Reassign
          </button>
          <template v-if="declining === r.id">
            <label :for="`decline-${r.id}`">Note to {{ r.requestedByName }} (optional)</label>
            <textarea :id="`decline-${r.id}`" v-model="declineNote" rows="2" maxlength="500"></textarea>
            <div class="row">
              <button class="btn btn-rose" :disabled="busyId !== null" @click="decline(r)">Keep current Coordinator</button>
              <button class="btn" @click="declining = null">Cancel</button>
            </div>
          </template>
          <button v-else class="btn" :disabled="busyId !== null" @click="startDecline(r)">Decline request</button>
        </div>
      </li>
    </ul>

    <!-- Assigned --------------------------------------------------------- -->
    <h3 class="section-title">Assigned and in progress ({{ assigned.length }})</h3>
    <div v-if="!loading && !assigned.length" class="card empty">No assigned requests in progress.</div>
    <div v-else-if="assigned.length" class="card table-card">
      <div class="table-wrap">
        <table>
          <thead>
            <tr><th>Request</th><th>Status</th><th>Assigned to</th><th>Reassign to</th><th>History</th></tr>
          </thead>
          <tbody>
            <template v-for="e in assigned" :key="e.id">
              <tr :id="`request-${e.id}`" :class="{ highlight: e.id === highlightId }">
                <td><router-link :to="`/events/${e.id}`" class="title">#{{ e.id }} {{ e.name || "(untitled)" }}</router-link></td>
                <td><StatusBadge :status="e.status" :label="e.statusLabel" /></td>
                <td>
                  {{ e.coordinatorName }}
                  <a v-if="pendingFor(e.id)" :href="`#reassignment-${e.id}`" class="flag">Reassignment requested</a>
                </td>
                <td>
                  <div class="reassign">
                    <select v-model.number="reassignChoice[e.id]" :aria-label="`Reassign request ${e.id}`">
                      <option :value="undefined">Select</option>
                      <option v-for="c in coordinators.filter((c) => c.id !== e.coordinatorId)" :key="c.id" :value="c.id">
                        {{ coordinatorOption(c) }}
                      </option>
                    </select>
                    <button class="btn" :disabled="!reassignChoice[e.id] || busyId !== null" @click="reassign(e)">
                      Reassign
                    </button>
                  </div>
                </td>
                <td>
                  <button class="btn" :aria-expanded="!!history[e.id]" @click="toggleHistory(e)">
                    {{ history[e.id] ? "Hide" : "Show" }}
                  </button>
                </td>
              </tr>
              <tr v-if="history[e.id]" class="history-row">
                <td colspan="5">
                  <ol class="history">
                    <li v-for="h in history[e.id]" :key="h.id">
                      <strong>{{ h.coordinatorName }}</strong>
                      — {{ h.assignmentType === "reassignment" ? "reassigned" : "assigned" }}
                      {{ formatTimestamp(h.assignedAt) }}<span v-if="h.assignedByName"> by {{ h.assignedByName }}</span>
                      <span v-if="h.unassignedAt" class="muted"> (until {{ formatTimestamp(h.unassignedAt) }})</span>
                      <span v-else class="current"> (current)</span>
                    </li>
                  </ol>
                </td>
              </tr>
            </template>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>

<script setup>
import { nextTick, onMounted, reactive, ref } from "vue";
import { useRoute } from "vue-router";
import eventsApi from "../api/events";
import StatusBadge from "../components/StatusBadge.vue";
import { useConfirm } from "../composables/useConfirm";
import { formatEventDate, formatTimestamp } from "../utils/display";

// "submitted" is included so an older request that already has a Coordinator
// (assigned before the Lead queue existed) still shows up somewhere.
const IN_PROGRESS = ["submitted", "under_review", "approved", "planning", "safety_check", "confirmed"];

const route = useRoute();
const { confirm } = useConfirm();

const unassigned = ref([]);
const assigned = ref([]);
const requests = ref([]);
const coordinators = ref([]);
const choice = reactive({});
const reassignChoice = reactive({});
const history = reactive({});
const loading = ref(true);
const busyId = ref(null);
const error = ref("");
const notice = ref("");
const declining = ref(null);
const requestsError = ref("");
const declineNote = ref("");
const highlightId = Number(route.query.event) || null;
const eventsById = ref({});

function coordinatorOption(c) {
  const n = c.activeEvents ?? c.openRequests ?? 0;
  return `${c.name} — ${n} active event${n === 1 ? "" : "s"}`;
}

function eventById(id) {
  return eventsById.value[id];
}

function pendingFor(eventId) {
  return requests.value.some((r) => r.eventId === eventId);
}

async function load() {
  loading.value = true;
  try {
    const [queue, coords, all] = await Promise.all([
      eventsApi.unassignedEvents(),
      eventsApi.listCoordinators(),
      eventsApi.allEvents(),
    ]);
    // Loaded separately: if it fails, assigning still works.
    requestsError.value = "";
    const reqs = await eventsApi.listReassignmentRequests().catch(() => {
      requestsError.value = "Could not load reassignment requests.";
      return { data: [] };
    });
    coordinators.value = coords.data;
    eventsById.value = Object.fromEntries(all.data.map((e) => [e.id, e]));
    unassigned.value = queue.data.filter((e) => e.status === "submitted");
    assigned.value = all.data
      .filter((e) => e.coordinatorId && IN_PROGRESS.includes(e.status))
      .sort((a, b) => (a.proposedDate || "9999").localeCompare(b.proposedDate || "9999"));
    requests.value = reqs.data;
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
    if (history[event.id]) delete history[event.id];
    delete reassignChoice[event.id];
    await load();
  }
}

async function toggleHistory(event) {
  if (history[event.id]) {
    delete history[event.id];
    return;
  }
  try {
    history[event.id] = (await eventsApi.assignmentHistory(event.id)).data;
  } catch (e) {
    error.value = e.response?.data?.error || "Could not load the assignment history.";
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

function startDecline(r) {
  declining.value = r.id;
  declineNote.value = "";
}

async function decline(r) {
  error.value = "";
  notice.value = "";
  if (!(await confirm(`Keep ${r.requestedByName} as the Coordinator for #${r.eventId}? They will be notified.`))) return;
  busyId.value = r.eventId;
  try {
    await eventsApi.declineReassignmentRequest(r.eventId, declineNote.value);
    notice.value = `Reassignment request for #${r.eventId} declined. ${r.requestedByName} has been notified.`;
    declining.value = null;
  } catch (e) {
    error.value = e.response?.data?.error || "Could not decline the request.";
  } finally {
    busyId.value = null;
    await load();
  }
}

onMounted(async () => {
  await load();
  if (highlightId) {
    await nextTick();
    const target =
      document.getElementById(`reassignment-${highlightId}`) || document.getElementById(`request-${highlightId}`);
    target?.scrollIntoView({ block: "center" });
    if (!unassigned.value.some((e) => e.id === highlightId) && !pendingFor(highlightId)) {
      const taken = assigned.value.find((e) => e.id === highlightId);
      if (taken) notice.value = `Request #${taken.id} is assigned to ${taken.coordinatorName}. You can reassign it below.`;
    }
  } else if (route.hash) {
    await nextTick();
    document.querySelector(route.hash)?.scrollIntoView({ block: "start" });
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
  border: 1px solid var(--border);
  border-radius: 14px;
  background: var(--surface);
  box-shadow: 0 4px 16px rgba(109, 91, 208, 0.08);
}

.request {
  display: flex;
  flex-wrap: wrap;
  gap: 1rem;
  justify-content: space-between;
  padding: 0.9rem 1rem;
}

.card.highlight,
tr.highlight td {
  background: #f7f5ff;
}

.card.highlight {
  border-color: var(--primary);
  box-shadow: 0 0 0 2px var(--primary-tint);
}

.card.empty {
  padding: 0.9rem 1rem;
  color: var(--text-muted);
}

.title-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem;
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

.reason {
  max-width: 34rem;
  white-space: pre-wrap;
}

.assign {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  min-width: 240px;
}

.assign label {
  font-size: 0.85rem;
  font-weight: 500;
}

.row {
  display: flex;
  gap: 0.4rem;
}

textarea {
  padding: 0.4rem;
  border: 1px solid var(--border);
  border-radius: 8px;
  font: inherit;
}

.table-card {
  overflow: hidden;
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
  padding: 0.7rem 0.75rem;
  background: #ddd6fb;
  font-size: 0.85rem;
  font-weight: 600;
  color: var(--lilac-text);
  white-space: nowrap;
}

td {
  padding: 0.65rem 0.75rem;
  border-top: 1px solid var(--border);
  vertical-align: middle;
}

.flag {
  display: inline-block;
  margin-top: 0.25rem;
  padding: 0.1rem 0.55rem;
  border-radius: 999px;
  background: var(--rose-bg);
  color: var(--rose-text);
  font-size: 0.75rem;
  font-weight: 500;
  text-decoration: none;
  white-space: nowrap;
}

.reassign {
  display: flex;
  gap: 0.4rem;
  align-items: center;
}

.reassign select {
  min-width: 0;
  flex: 1;
  max-width: 11rem;
}

th:first-child,
td:first-child {
  min-width: 10rem;
}

select {
  padding: 0.4rem 0.5rem;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: #fff;
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
  cursor: pointer;
}

.btn-primary {
  background: var(--primary);
  color: #fff;
}

.btn-rose {
  background: var(--rose-bg);
  color: var(--rose-text);
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

.history {
  margin: 0;
  padding-left: 1.2rem;
  font-size: 0.9rem;
}

.muted {
  color: var(--text-muted);
}

.current {
  color: var(--mint-text);
}
</style>
