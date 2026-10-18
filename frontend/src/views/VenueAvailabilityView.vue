<template>
  <section>
    <div class="head">
      <h2 class="page-title">Venue Availability</h2>
      <div class="toggle" role="group" aria-label="Calendar view">
        <button type="button" :class="{ on: mode === 'combined' }" @click="setMode('combined')">
          All venues
        </button>
        <button type="button" :class="{ on: mode === 'single' }" @click="setMode('single')">
          One venue
        </button>
      </div>
    </div>

    <p v-if="notice" class="notice" role="status">{{ notice }}</p>
    <p v-if="pageError" class="field-error" role="alert">{{ pageError }}</p>

    <!-- Event Coordinators: events affected by an availability change -->
    <div v-if="isCoordinator && flags.length" class="card flags">
      <h3>Events affected by availability changes</h3>
      <ul>
        <li v-for="f in flags" :key="f.id">
          <span>
            <router-link :to="`/events/${f.eventId}`">Event #{{ f.eventId }}</router-link>
            at {{ venueName(f.venueId) }}: {{ f.reason || "Venue availability changed" }}
          </span>
          <button type="button" class="btn-ghost" @click="resolveFlag(f)">Mark resolved</button>
        </li>
      </ul>
    </div>

    <!-- Venue Staff: block a venue out -->
    <form v-if="isStaff" class="card block-form" novalidate @submit.prevent="addBlock">
      <h3>Mark a venue unavailable</h3>
      <div class="fields">
        <label>
          Venue
          <select v-model="blockForm.venueId" :aria-invalid="!!blockErrors.venueId">
            <option v-for="v in venues" :key="v.id" :value="v.id">{{ v.name }}</option>
          </select>
          <span v-if="blockErrors.venueId" class="field-error">{{ blockErrors.venueId }}</span>
        </label>
        <label>
          From
          <input v-model="blockForm.start" type="datetime-local" :aria-invalid="!!blockErrors.start" />
          <span v-if="blockErrors.start" class="field-error">{{ blockErrors.start }}</span>
        </label>
        <label>
          Until
          <input v-model="blockForm.end" type="datetime-local" :aria-invalid="!!blockErrors.end" />
          <span v-if="blockErrors.end" class="field-error">{{ blockErrors.end }}</span>
        </label>
        <label>
          Reason (maintenance, renovation, safety...)
          <input v-model="blockForm.reason" type="text" maxlength="255" />
        </label>
      </div>
      <p v-if="blockError" class="field-error" role="alert">{{ blockError }}</p>
      <button type="submit" class="btn-primary" :disabled="saving">
        {{ saving ? "Saving..." : "Mark unavailable" }}
      </button>
    </form>

    <!-- Week + venue controls -->
    <div class="card controls">
      <label v-if="mode === 'single'" class="venue-pick">
        Venue
        <select v-model="selectedVenueId" @change="load">
          <option v-for="v in venues" :key="v.id" :value="v.id">{{ v.name }}</option>
        </select>
      </label>
      <div class="weeknav">
        <button type="button" class="btn-ghost" @click="shiftWeek(-1)">Previous week</button>
        <strong>{{ weekLabel }}</strong>
        <button type="button" class="btn-ghost" @click="shiftWeek(1)">Next week</button>
        <button type="button" class="btn-ghost" @click="goToday">This week</button>
      </div>
    </div>

    <p v-if="mode === 'single' && !venues.length" class="empty">No venues in the catalogue yet.</p>

    <template v-else>
      <div class="days" role="group" aria-label="Day of week">
        <button
          v-for="d in weekDays"
          :key="d.key"
          type="button"
          :class="{ on: d.key === selectedDayKey }"
          :aria-pressed="d.key === selectedDayKey"
          @click="selectedDayKey = d.key"
        >
          {{ d.short }} <small>{{ d.date }}</small>
        </button>
      </div>

      <div class="card timeline">
        <div class="legend">
          <span><i class="sw booked" /> Booked event</span>
          <span><i class="sw held" /> Tentative hold</span>
          <span><i class="sw pad" /> Setup / turnaround</span>
          <span><i class="sw blocked" /> Unavailable</span>
        </div>

        <p v-if="loading" class="empty">Loading calendar...</p>
        <p v-else-if="!dayRows.length" class="empty">No venues to show.</p>
        <div v-else class="scroll">
          <div class="axis">
            <span />
            <div class="ticks">
              <span v-for="h in [0, 6, 12, 18, 24]" :key="h" :style="{ left: (h / 24) * 100 + '%' }">
                {{ pad2(h) }}:00
              </span>
            </div>
          </div>
          <div v-for="row in dayRows" :key="row.id" class="row">
            <div class="rowname">{{ row.name }}</div>
            <div class="track">
              <span
                v-for="(s, i) in row.segments"
                :key="i"
                :class="['seg', s.kind]"
                :style="{ left: s.left + '%', width: s.width + '%' }"
                :title="s.title"
              />
              <span v-if="!row.segments.length" class="free">Available</span>
            </div>
          </div>
        </div>
      </div>

      <div class="card list">
        <h3>This week</h3>
        <p v-if="!items.length" class="empty">Nothing booked, held, or blocked this week.</p>
        <table v-else>
          <thead>
            <tr>
              <th>When</th>
              <th>Venue</th>
              <th>Status</th>
              <th>Details</th>
              <th v-if="isStaff"><span class="sr-only">Actions</span></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="it in items" :key="it.key">
              <td>{{ fmt(it.start) }} to {{ fmt(it.end) }}</td>
              <td>{{ it.venue }}</td>
              <td>
                <span :class="['badge', it.type === 'booked' ? 'sky' : it.type === 'held' ? 'butter' : 'rose']">
                  {{ it.type === "booked" ? "Booked" : it.type === "held" ? "Held" : "Unavailable" }}
                </span>
              </td>
              <td>{{ it.detail }}</td>
              <td v-if="isStaff">
                <button
                  v-if="it.type === 'blocked'"
                  type="button"
                  class="btn-danger"
                  @click="removeBlock(it)"
                >
                  Remove
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>
  </section>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from "vue";
import venuesApi from "../api/venues";
import { useAuthStore } from "../stores/auth";
import { useConfirm } from "../composables/useConfirm";

const auth = useAuthStore();
const { confirm } = useConfirm();
const isStaff = computed(() => auth.hasRole("venue_staff"));
const isCoordinator = computed(() => auth.hasRole("event_coordinator"));

// ---- date helpers (the API uses naive local datetimes, e.g. 2026-10-10T10:00:00) ----
const DAY_MS = 86400000;
const pad2 = (n) => String(n).padStart(2, "0");
const dayKey = (d) => `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;
const naiveIso = (d) => `${dayKey(d)}T${pad2(d.getHours())}:${pad2(d.getMinutes())}:00`;
const fmt = (iso) =>
  new Date(iso).toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
const fmtTime = (iso) => new Date(iso).toLocaleTimeString([], { timeStyle: "short" });
// Hold expiry timestamps are stored in UTC; booking start/end times remain local.
function formatHoldExpiry(value) {
  if (!value) return "Not specified";
  const timestamp = String(value).trim().replace(" ", "T");
  const utcTimestamp = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(timestamp) ? timestamp : `${timestamp}Z`;
  const date = new Date(utcTimestamp);
  if (Number.isNaN(date.getTime())) return "Not specified";
  return date.toLocaleString("en-SG", {
    timeZone: "Asia/Singapore",
    day: "2-digit", month: "2-digit", year: "numeric",
    hour: "numeric", minute: "2-digit", hour12: true,
  });
}


function mondayOf(date) {
  const d = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  d.setDate(d.getDate() - ((d.getDay() + 6) % 7));
  return d;
}

// ---- state ----
const mode = ref("combined");
const venues = ref([]);
const selectedVenueId = ref("");
const rows = ref([]); // [{ venue, confirmedBookings, heldBookings, unavailability }]
const flags = ref([]);
const loading = ref(false);
const saving = ref(false);
const pageError = ref("");
const notice = ref("");

const weekStart = ref(mondayOf(new Date()));
const weekEndDate = computed(() => {
  const d = new Date(weekStart.value);
  d.setDate(d.getDate() + 7);
  return d;
});
const weekDays = computed(() =>
  Array.from({ length: 7 }, (_, i) => {
    const d = new Date(weekStart.value);
    d.setDate(d.getDate() + i);
    return {
      key: dayKey(d),
      short: d.toLocaleDateString([], { weekday: "short" }),
      date: d.getDate(),
    };
  })
);
const weekLabel = computed(() => {
  const last = new Date(weekStart.value);
  last.setDate(last.getDate() + 6);
  const opts = { day: "numeric", month: "short" };
  return `${weekStart.value.toLocaleDateString([], opts)} to ${last.toLocaleDateString([], {
    ...opts,
    year: "numeric",
  })}`;
});
const selectedDayKey = ref(dayKey(new Date()));

function pickDefaultDay() {
  const today = dayKey(new Date());
  selectedDayKey.value = weekDays.value.some((d) => d.key === today) ? today : weekDays.value[0].key;
}

function shiftWeek(delta) {
  const d = new Date(weekStart.value);
  d.setDate(d.getDate() + delta * 7);
  weekStart.value = d;
  pickDefaultDay();
  load();
}
function goToday() {
  weekStart.value = mondayOf(new Date());
  pickDefaultDay();
  load();
}
function setMode(next) {
  mode.value = next;
  load();
}

const venueName = (id) => venues.value.find((v) => v.id === id)?.name || `Venue #${id}`;

// ---- derived data for the timeline and the weekly list ----
const dayStart = computed(() => new Date(`${selectedDayKey.value}T00:00:00`).getTime());

function clip(startIso, endIso) {
  const s = Math.max(new Date(startIso).getTime() - dayStart.value, 0);
  const e = Math.min(new Date(endIso).getTime() - dayStart.value, DAY_MS);
  return e > s ? { left: (s / DAY_MS) * 100, width: ((e - s) / DAY_MS) * 100 } : null;
}

const dayRows = computed(() =>
  rows.value.map((r) => {
    const segments = [];
    for (const b of r.confirmedBookings || []) {
      const padded = clip(b.effectiveStart, b.effectiveEnd);
      if (padded) segments.push({ kind: "pad", ...padded, title: `Setup/turnaround, event #${b.eventId}` });
      const core = clip(b.startDatetime, b.endDatetime);
      if (core) {
        segments.push({
          kind: "booked",
          ...core,
          title: `${b.eventName || `Event #${b.eventId}`}, ${fmt(b.startDatetime)} to ${fmt(b.endDatetime)}`,
        });
      }
    }
    for (const b of r.heldBookings || []) {
      const padded = clip(b.effectiveStart || b.startDatetime, b.effectiveEnd || b.endDatetime);
      if (padded) segments.push({ kind: "pad", ...padded, title: `Setup/turnaround for held event #${b.eventId}` });
      const core = clip(b.startDatetime, b.endDatetime);
      if (core) {
        segments.push({
          kind: "held",
          ...core,
          title: `${b.eventName || `Event #${b.eventId}`} (Held), ${fmt(b.startDatetime)} to ${fmt(b.endDatetime)}. Expires ${formatHoldExpiry(b.holdExpiresAt)}`,
        });
      }
    }
    for (const u of r.unavailability || []) {
      const seg = clip(u.start, u.end);
      if (seg) segments.push({ kind: "blocked", ...seg, title: `Unavailable: ${u.reason || "no reason given"}` });
    }
    return { id: r.venue?.id, name: r.venue?.name || "Venue", segments };
  })
);

const items = computed(() =>
  rows.value
    .flatMap((r) => [
      ...(r.confirmedBookings || []).map((b) => ({
        key: `b${b.id}`,
        type: "booked",
        venue: r.venue?.name,
        start: b.startDatetime,
        end: b.endDatetime,
        detail: `${b.eventName || `Event #${b.eventId}`}. Venue held ${fmt(b.effectiveStart)} to ${fmt(b.effectiveEnd)} including setup and turnaround.`,
      })),
      ...(r.heldBookings || []).map((b) => ({
        key: `h${b.id}`,
        type: "held",
        venue: r.venue?.name,
        start: b.startDatetime,
        end: b.endDatetime,
        detail: `${b.eventName || `Event #${b.eventId}`}. Tentative hold expires ${formatHoldExpiry(b.holdExpiresAt)}.`,
      })),
      ...(r.unavailability || []).map((u) => ({
        key: `u${u.id}`,
        type: "blocked",
        id: u.id,
        venueId: r.venue?.id,
        venue: r.venue?.name,
        start: u.start,
        end: u.end,
        detail: u.reason || "No reason given",
      })),
    ])
    .sort((a, b) => new Date(a.start) - new Date(b.start))
);

// ---- loading ----
async function load() {
  pageError.value = "";
  loading.value = true;
  try {
    const start = naiveIso(weekStart.value);
    const end = naiveIso(weekEndDate.value);
    if (mode.value === "combined") {
      const { data } = await venuesApi.getCombinedCalendar(start, end);
      rows.value = data;
    } else if (selectedVenueId.value) {
      const { data } = await venuesApi.getCalendar(selectedVenueId.value, start, end);
      const venue = venues.value.find((v) => v.id === selectedVenueId.value);
      rows.value = [{ venue, ...data }];
    } else {
      rows.value = [];
    }
  } catch (error) {
    rows.value = [];
    pageError.value = error.response?.data?.error || "Could not load the calendar.";
  } finally {
    loading.value = false;
  }
}

async function loadFlags() {
  if (!isCoordinator.value) return;
  try {
    const { data } = await venuesApi.myFlags();
    flags.value = data;
  } catch {
    flags.value = [];
  }
}

async function resolveFlag(flag) {
  try {
    await venuesApi.resolveFlag(flag.id);
    notice.value = "Marked as resolved.";
    await loadFlags();
  } catch (error) {
    pageError.value = error.response?.data?.error || "Could not resolve the flag.";
  }
}

// ---- Venue Staff: add / remove unavailability ----
const blockForm = reactive({ venueId: "", start: "", end: "", reason: "" });
const blockErrors = reactive({});
const blockError = ref("");

async function addBlock() {
  notice.value = "";
  blockError.value = "";
  Object.keys(blockErrors).forEach((k) => delete blockErrors[k]);
  if (!blockForm.venueId) blockErrors.venueId = "Choose a venue.";
  if (!blockForm.start) blockErrors.start = "Choose a start date and time.";
  if (!blockForm.end) blockErrors.end = "Choose an end date and time.";
  if (blockForm.start && blockForm.end && blockForm.end <= blockForm.start) {
    blockErrors.end = "End must be after the start.";
  }
  if (Object.keys(blockErrors).length) return;

  saving.value = true;
  try {
    const { data } = await venuesApi.addUnavailability(blockForm.venueId, {
      start: `${blockForm.start}:00`,
      end: `${blockForm.end}:00`,
      reason: blockForm.reason.trim() || null,
    });
    const affected = data.flagsRaised?.length || 0;
    notice.value = affected
      ? `Venue marked unavailable. ${affected} booked event(s) overlap this period and were flagged for their coordinators.`
      : "Venue marked unavailable.";
    Object.assign(blockForm, { start: "", end: "", reason: "" });
    await load();
  } catch (error) {
    blockError.value = error.response?.data?.error || "Could not save the unavailability.";
  } finally {
    saving.value = false;
  }
}

async function removeBlock(item) {
  const ok = await confirm(`Remove this unavailable period for ${item.venue}?`);
  if (!ok) return;
  notice.value = "";
  try {
    await venuesApi.removeUnavailability(item.venueId, item.id);
    notice.value = "Unavailable period removed.";
    await load();
  } catch (error) {
    pageError.value = error.response?.data?.error || "Could not remove the period.";
  }
}

onMounted(async () => {
  pickDefaultDay();
  try {
    const { data } = await venuesApi.listVenues();
    venues.value = data;
    selectedVenueId.value = data[0]?.id ?? "";
    blockForm.venueId = data[0]?.id ?? "";
  } catch (error) {
    pageError.value = error.response?.data?.error || "Could not load venues.";
  }
  await Promise.all([load(), loadFlags()]);
});
</script>

<style scoped>
.head { display: flex; align-items: center; justify-content: space-between; gap: 1rem; margin-bottom: 1rem; flex-wrap: wrap; }
.page-title { margin: 0; font-size: 1.5rem; font-weight: 600; color: var(--text); }
h3 { margin: 0 0 0.75rem; }

.card {
  padding: 1.25rem 1.5rem;
  margin-bottom: 1rem;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 14px;
  box-shadow: 0 4px 16px rgba(109, 91, 208, 0.08);
}

.toggle { display: inline-flex; border: 1px solid var(--border); border-radius: 999px; overflow: hidden; }
.toggle button, .days button {
  padding: 0.45rem 1.1rem;
  border: none;
  background: var(--surface);
  color: var(--text);
  font: inherit;
  cursor: pointer;
}
.toggle button.on, .days button.on { background: var(--primary); color: #fff; }

.notice { margin: 0 0 1rem; padding: 0.6rem 0.9rem; border-radius: 10px; background: var(--mint-bg); color: var(--mint-text); }
.field-error { color: #a12b47; font-size: 0.875rem; font-weight: 400; }
.empty { padding: 1rem; color: var(--text-muted); }

.flags { border-color: var(--butter-text); }
.flags ul { list-style: none; margin: 0; padding: 0; }
.flags li { display: flex; justify-content: space-between; align-items: center; gap: 1rem; padding: 0.4rem 0; flex-wrap: wrap; }

.fields { display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 1rem; margin-bottom: 1rem; }
label { display: flex; flex-direction: column; gap: 0.35rem; font-weight: 600; }
input, select {
  box-sizing: border-box; width: 100%; min-height: 2.4rem; padding: 0.4rem;
  border: 1px solid var(--border); border-radius: 0.35rem;
  color: var(--text); background: var(--surface); font: inherit; font-weight: 400;
}
input:focus-visible, select:focus-visible, button:focus-visible { outline: 2px solid var(--primary); outline-offset: 2px; }
[aria-invalid="true"] { border-color: #a12b47; }

.controls { display: flex; align-items: flex-end; justify-content: space-between; gap: 1rem; flex-wrap: wrap; }
.venue-pick { min-width: 220px; }
.weeknav { display: flex; align-items: center; gap: 0.6rem; flex-wrap: wrap; }

.days { display: grid; grid-template-columns: repeat(7, 1fr); gap: 0.35rem; margin-bottom: 0.75rem; }
.days button { border: 1px solid var(--border); border-radius: 10px; padding: 0.4rem 0.2rem; }
.days small { display: block; font-size: 0.8rem; }

.legend { display: flex; gap: 1.2rem; flex-wrap: wrap; margin-bottom: 0.8rem; font-size: 0.9rem; color: var(--text-muted); }
.sw { display: inline-block; width: 0.9rem; height: 0.9rem; border-radius: 3px; margin-right: 0.35rem; vertical-align: -2px; }

.scroll { overflow-x: auto; }
.axis, .row { display: grid; grid-template-columns: 150px minmax(520px, 1fr); }
.axis { height: 1.3rem; margin-bottom: 0.2rem; font-size: 0.78rem; color: var(--text-muted); }
.ticks { position: relative; }
.ticks span { position: absolute; top: 0; transform: translateX(-50%); }
.ticks span:first-child { transform: none; }
.ticks span:last-child { transform: translateX(-100%); }
.row { align-items: center; margin-bottom: 0.4rem; }
.rowname { padding-right: 0.6rem; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.track { position: relative; height: 2rem; background: var(--bg); border: 1px solid var(--border); border-radius: 6px; overflow: hidden; }
.free { position: absolute; inset: 0; display: grid; place-items: center; font-size: 0.8rem; color: var(--text-muted); }

.seg { position: absolute; top: 0; bottom: 0; }
.seg.pad, .sw.pad { background: var(--butter-bg); border: 1px dashed var(--butter-text); }
.seg.booked, .sw.booked { background: var(--primary); }
.seg.held, .sw.held { background: #d9a441; }
.seg.blocked, .sw.blocked {
  background: repeating-linear-gradient(45deg, var(--rose-text), var(--rose-text) 6px, var(--rose-bg) 6px, var(--rose-bg) 12px);
}

.list table { width: 100%; border-collapse: collapse; }
.list th, .list td { text-align: left; padding: 0.5rem 0.6rem; border-bottom: 1px solid var(--border); vertical-align: top; }
.list th { font-size: 0.85rem; color: var(--text-muted); }
.badge { padding: 0.15rem 0.6rem; border-radius: 999px; font-size: 0.82rem; font-weight: 500; white-space: nowrap; }
.sky { background: var(--sky-bg); color: var(--sky-text); }
.butter { background: var(--butter-bg, #fef3c7); color: var(--butter-text, #92400e); }
.rose { background: var(--rose-bg); color: var(--rose-text); }
.sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); }

.btn-primary, .btn-ghost, .btn-danger { padding: 0.5rem 1.2rem; border: none; border-radius: 999px; font: inherit; font-weight: 500; cursor: pointer; }
.btn-primary { background: var(--primary); color: #fff; }
.btn-primary:hover { background: var(--primary-hover); }
.btn-primary:disabled { opacity: 0.6; cursor: not-allowed; }
.btn-ghost { background: var(--lilac-bg); color: var(--lilac-text); }
.btn-danger { background: var(--rose-bg); color: var(--rose-text); }
</style>
