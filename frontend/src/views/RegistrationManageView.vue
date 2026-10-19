<template>
  <section>
    <h2 class="page-title">Event registrations</h2>

    <p v-if="notice" class="notice" role="status">{{ notice }}</p>
    <p v-if="error" class="field-error" role="alert">{{ error }}</p>
    <p v-if="loading" class="empty">Loading...</p>
    <p v-else-if="!events.length && !error" class="empty">
      None of your events take registrations. Turn on "registration required" when you request an event.
    </p>

    <div v-else class="layout">
      <ul class="events" aria-label="Your events">
        <li v-for="e in events" :key="e.id">
          <button type="button" :class="['event-btn', { on: e.id === selectedId }]" @click="select(e.id)">
            <strong>{{ e.name }}</strong>
            <span class="meta">{{ e.date || "No date" }} · {{ e.statusLabel }}</span>
            <span :class="['badge', e.registrationOpen ? 'mint' : 'rose']">
              {{ e.registrationOpen ? "Open" : "Closed" }}
            </span>
          </button>
        </li>
      </ul>

      <div v-if="data" class="card">
        <div class="head">
          <h3>{{ data.event.name }}</h3>
          <button v-if="current?.isOrganiser && !data.event.registrationOpen" type="button" class="btn-primary" :disabled="busy" @click="toggle(true)">
            Open registration
          </button>
          <button v-else-if="current?.isOrganiser" type="button" class="btn-ghost" :disabled="busy" @click="toggle(false)">
            Close registration
          </button>
        </div>

        <dl class="summary">
          <div><dt>Registered</dt><dd>{{ data.summary.registered }}</dd></div>
          <div><dt>Waiting list</dt><dd>{{ data.summary.waitlisted }}</dd></div>
          <div><dt>Withdrawn</dt><dd>{{ data.summary.withdrawn }}</dd></div>
          <div><dt>Places left</dt><dd>{{ data.summary.placesRemaining === null ? "Unlimited" : data.summary.placesRemaining }}</dd></div>
        </dl>

        <p v-if="!data.registrations.length" class="empty">Nobody has registered yet.</p>
        <div v-else class="scroll">
          <table>
            <thead>
              <tr><th>Name</th><th>Status</th><th>Waiting list position</th></tr>
            </thead>
            <tbody>
              <tr v-for="r in data.registrations" :key="r.id" :class="{ withdrawn: r.status === 'withdrawn' }">
                <td>{{ r.attendeeName }}</td>
                <td><span :class="['badge', badge(r.status)]">{{ r.status }}</span></td>
                <td>{{ r.queuePosition ?? "" }}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <div v-if="data.pages > 1" class="paging">
          <button type="button" class="btn-ghost" :disabled="data.page <= 1" @click="goTo(data.page - 1)">Previous</button>
          <span>Page {{ data.page }} of {{ data.pages }} ({{ data.total }} registrations)</span>
          <button type="button" class="btn-ghost" :disabled="data.page >= data.pages" @click="goTo(data.page + 1)">Next</button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from "vue";
import registrationsApi from "../api/registrations";

const events = ref([]);
const selectedId = ref(null);
const data = ref(null);
const loading = ref(false);
const busy = ref(false);
const error = ref("");
const notice = ref("");

const current = computed(() => events.value.find((e) => e.id === selectedId.value));
const badge = (s) => ({ registered: "mint", waitlisted: "butter", withdrawn: "grey" })[s] || "grey";

async function loadEvents() {
  const res = await registrationsApi.managedEvents();
  events.value = res.data;
}

async function loadAttendees(page = 1) {
  try {
    const res = await registrationsApi.attendees(selectedId.value, page);
    data.value = res.data;
  } catch (e) {
    data.value = null;
    error.value = e.response?.data?.error || "Could not load the attendee list.";
  }
}

async function select(id) {
  selectedId.value = id;
  error.value = "";
  notice.value = "";
  await loadAttendees(1);
}

const goTo = (page) => loadAttendees(page);

async function toggle(open) {
  busy.value = true;
  error.value = "";
  notice.value = "";
  try {
    if (open) await registrationsApi.openRegistration(selectedId.value);
    else await registrationsApi.closeRegistration(selectedId.value);
    notice.value = open ? "Registration is now open." : "Registration is now closed. Existing places are unchanged.";
  } catch (e) {
    error.value = e.response?.data?.error || "Could not change registration.";
  } finally {
    await loadEvents();
    await loadAttendees(data.value?.page || 1);
    busy.value = false;
  }
}

onMounted(async () => {
  loading.value = true;
  try {
    await loadEvents();
    if (events.value.length) await select(events.value[0].id);
  } catch (e) {
    error.value = e.response?.data?.error || "Could not load your events.";
  } finally {
    loading.value = false;
  }
});
</script>

<style scoped>
.page-title { margin: 0 0 1rem; font-size: 1.5rem; font-weight: 600; color: var(--text); }
.layout { display: grid; grid-template-columns: 280px 1fr; gap: 1rem; align-items: start; }
.events { list-style: none; margin: 0; padding: 0; display: grid; gap: 0.5rem; }
.event-btn { width: 100%; display: grid; gap: 0.2rem; text-align: left; padding: 0.7rem 0.9rem; background: var(--surface); border: 1px solid var(--border); border-radius: 12px; font: inherit; color: var(--text); cursor: pointer; }
.event-btn.on { border-color: var(--primary); background: var(--primary-tint); }
.meta { color: var(--text-muted); font-size: 0.88rem; }
.card { padding: 1.25rem 1.5rem; background: var(--surface); border: 1px solid var(--border); border-radius: 14px; }
.head { display: flex; justify-content: space-between; align-items: center; gap: 1rem; flex-wrap: wrap; }
.head h3 { margin: 0; }
.summary { display: grid; grid-template-columns: repeat(auto-fit, minmax(110px, 1fr)); gap: 0.6rem; margin: 1rem 0; }
.summary div { padding: 0.6rem 0.8rem; background: var(--bg); border-radius: 10px; }
.summary dt { color: var(--text-muted); font-size: 0.85rem; }
.summary dd { margin: 0; font-size: 1.3rem; font-weight: 600; }
.scroll { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; }
th, td { text-align: left; padding: 0.5rem 0.6rem; border-bottom: 1px solid var(--border); }
th { color: var(--text-muted); font-size: 0.85rem; }
tr.withdrawn td { opacity: 0.6; }
.badge { padding: 0.15rem 0.6rem; border-radius: 999px; font-size: 0.82rem; font-weight: 500; width: fit-content; }
.mint { background: var(--mint-bg); color: var(--mint-text); }
.rose { background: var(--rose-bg); color: var(--rose-text); }
.butter { background: var(--butter-bg); color: var(--butter-text); }
.grey { background: var(--border); color: var(--text-muted); }
.paging { display: flex; align-items: center; justify-content: center; gap: 1rem; margin-top: 1rem; }
.notice { padding: 0.6rem 0.9rem; border-radius: 10px; background: var(--mint-bg); color: var(--mint-text); }
.field-error { color: #a12b47; }
.empty { padding: 1rem; color: var(--text-muted); }
.btn-primary, .btn-ghost { padding: 0.5rem 1.2rem; border: none; border-radius: 999px; font: inherit; font-weight: 500; cursor: pointer; }
.btn-primary { background: var(--primary); color: #fff; }
.btn-ghost { background: var(--lilac-bg); color: var(--lilac-text); }
button:disabled { opacity: 0.6; cursor: not-allowed; }
button:focus-visible { outline: 2px solid var(--primary); outline-offset: 2px; }
@media (max-width: 720px) { .layout { grid-template-columns: 1fr; } }
</style>
