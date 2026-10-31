<template>
  <div class="month-calendar">
    <div class="cal-head">
      <div class="nav">
        <button type="button" class="btn-icon" aria-label="Previous month" @click="shiftMonth(-1)">‹</button>
        <h3 class="month-label">{{ monthLabel }}</h3>
        <button type="button" class="btn-icon" aria-label="Next month" @click="shiftMonth(1)">›</button>
        <button type="button" class="btn-soft" @click="goToday">Today</button>
      </div>
      <p class="summary">
        {{ monthEvents.length }} event{{ monthEvents.length === 1 ? "" : "s" }} this month
        <span v-if="nextEventLabel"> · <button type="button" class="link" @click="jumpToNext">Next: {{ nextEventLabel }}</button></span>
      </p>
    </div>

    <div class="grid" role="grid" :aria-label="`Events in ${monthLabel}`">
      <div v-for="d in WEEKDAYS" :key="d" class="dow" role="columnheader">{{ d }}</div>
      <div
        v-for="cell in cells"
        :key="cell.key"
        role="gridcell"
        :class="['day', { outside: !cell.inMonth, today: cell.isToday }]"
      >
        <span class="day-num">{{ cell.day }}</span>
        <button
          v-for="e in cell.events.slice(0, MAX_PER_DAY)"
          :key="e.id"
          type="button"
          :class="['chip', toneOf(e), { unassigned: showCoordinator && !e.coordinatorId, readonly: e.isReadOnly, selected: selected?.id === e.id }]"
          :title="chipTitle(e)"
          @click="select(e)"
        >
          <span class="chip-time">{{ e.proposedTime || "" }}</span>
          <span class="chip-name">{{ e.name || "(untitled)" }}</span>
          <span v-if="showCoordinator" class="chip-sub">{{ e.coordinatorName || "Unassigned" }}</span>
        </button>
        <button
          v-if="cell.events.length > MAX_PER_DAY"
          type="button"
          class="more"
          @click="select(cell.events[MAX_PER_DAY])"
        >
          +{{ cell.events.length - MAX_PER_DAY }} more
        </button>
      </div>
    </div>

    <ul v-if="undated.length" class="undated">
      <li class="undated-title">No proposed date yet:</li>
      <li v-for="e in undated" :key="e.id">
        <button type="button" class="link" @click="select(e)">{{ e.name || "(untitled)" }}</button>
      </li>
    </ul>

    <!-- Details for the selected event -->
    <aside v-if="selected" class="detail" aria-live="polite">
      <div class="detail-head">
        <h4>{{ selected.name || "(untitled)" }}</h4>
        <button type="button" class="btn-icon" aria-label="Close details" @click="selected = null">×</button>
      </div>
      <dl>
        <dt>When</dt><dd>{{ formatEventDate(selected.proposedDate, selected.proposedTime) }}</dd>
        <dt>Status</dt><dd><StatusBadge :status="selected.status" :label="selected.statusLabel" /></dd>
        <template v-if="showCoordinator">
          <dt>Coordinator</dt>
          <dd>
            <span v-if="selected.coordinatorName">{{ selected.coordinatorName }}</span>
            <span v-else class="unassigned-tag">Unassigned</span>
          </dd>
        </template>
        <template v-if="selected.isReadOnly">
          <dt>Now with</dt><dd>{{ selected.coordinatorName || "another Coordinator" }} (read-only for you)</dd>
        </template>
        <dt>Organiser</dt><dd>{{ selected.organiserName || "—" }}</dd>
        <dt>Attendance</dt><dd>{{ selected.expectedAttendance ?? "—" }}</dd>
      </dl>
      <div class="detail-actions">
        <router-link :to="`/events/${selected.id}`" class="btn-primary">Open details</router-link>
        <slot name="actions" :event="selected" />
      </div>
    </aside>
  </div>
</template>

<script setup>
import { computed, ref, watch } from "vue";
import StatusBadge from "./StatusBadge.vue";
import { formatEventDate } from "../utils/display";

const props = defineProps({
  events: { type: Array, default: () => [] },
  // Lead calendar: show who coordinates each event and mark Unassigned ones.
  showCoordinator: { type: Boolean, default: false },
});

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const MAX_PER_DAY = 3;
const TONES = {
  submitted: "butter", under_review: "butter", approved: "mint", planning: "sky",
  safety_check: "lilac", confirmed: "mint", completed: "mint", cancelled: "rose", rejected: "rose",
};

const today = new Date();
const cursor = ref(new Date(today.getFullYear(), today.getMonth(), 1));
const selected = ref(null);

const pad = (n) => String(n).padStart(2, "0");
const isoOf = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const todayIso = isoOf(today);

const monthLabel = computed(() =>
  cursor.value.toLocaleDateString(undefined, { month: "long", year: "numeric" })
);

const byDate = computed(() => {
  const map = {};
  for (const e of props.events) {
    if (!e.proposedDate) continue;
    (map[e.proposedDate] ||= []).push(e);
  }
  for (const list of Object.values(map)) {
    list.sort((a, b) => (a.proposedTime || "").localeCompare(b.proposedTime || ""));
  }
  return map;
});

const undated = computed(() => props.events.filter((e) => !e.proposedDate));

// Six weeks starting on the Monday on/before the 1st of the month.
const cells = computed(() => {
  const first = cursor.value;
  const offset = (first.getDay() + 6) % 7;
  const start = new Date(first.getFullYear(), first.getMonth(), 1 - offset);
  const out = [];
  for (let i = 0; i < 42; i++) {
    const d = new Date(start.getFullYear(), start.getMonth(), start.getDate() + i);
    const iso = isoOf(d);
    out.push({
      key: iso,
      day: d.getDate(),
      inMonth: d.getMonth() === first.getMonth(),
      isToday: iso === todayIso,
      events: byDate.value[iso] || [],
    });
  }
  return out;
});

const monthEvents = computed(() => {
  const prefix = `${cursor.value.getFullYear()}-${pad(cursor.value.getMonth() + 1)}`;
  return props.events.filter((e) => e.proposedDate?.startsWith(prefix));
});

// Shortcut to the next month that has an event, when this month is empty.
const nextEvent = computed(() => {
  if (monthEvents.value.length) return null;
  const after = isoOf(new Date(cursor.value.getFullYear(), cursor.value.getMonth() + 1, 1));
  return props.events
    .filter((e) => e.proposedDate && e.proposedDate >= after)
    .sort((a, b) => a.proposedDate.localeCompare(b.proposedDate))[0] || null;
});
const nextEventLabel = computed(() =>
  nextEvent.value ? `${nextEvent.value.name || "(untitled)"} on ${formatEventDate(nextEvent.value.proposedDate)}` : ""
);

function shiftMonth(delta) {
  cursor.value = new Date(cursor.value.getFullYear(), cursor.value.getMonth() + delta, 1);
}
function goToday() {
  cursor.value = new Date(today.getFullYear(), today.getMonth(), 1);
}
function jumpToNext() {
  const [y, m] = nextEvent.value.proposedDate.split("-").map(Number);
  cursor.value = new Date(y, m - 1, 1);
}
function select(e) {
  selected.value = e;
}
function toneOf(e) {
  return TONES[e.status] || "lilac";
}
function chipTitle(e) {
  const who = props.showCoordinator ? ` · ${e.coordinatorName || "Unassigned"}` : "";
  return `${e.name || "(untitled)"} · ${e.proposedTime || "time not set"} · ${e.statusLabel || e.status}${who}`;
}

// Keep the details panel in step with filters / reloads.
watch(
  () => props.events,
  (list) => {
    if (selected.value) selected.value = list.find((e) => e.id === selected.value.id) || null;
  }
);
</script>

<style scoped>
.month-calendar {
  background: var(--surface, #fff);
  border: 1px solid var(--border, #e4defa);
  border-radius: 14px;
  box-shadow: 0 4px 16px rgba(109, 91, 208, 0.08);
  padding: 1rem;
}
.cal-head {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.75rem;
}
.nav {
  display: flex;
  align-items: center;
  gap: 0.4rem;
}
.month-label {
  margin: 0;
  min-width: 10rem;
  text-align: center;
  font-size: 1.1rem;
  color: var(--text, #2d2a4a);
}
.summary {
  margin: 0;
  color: var(--text-muted, #6b6890);
  font-size: 0.85rem;
}
.btn-icon {
  width: 2rem;
  height: 2rem;
  border: none;
  border-radius: 999px;
  background: var(--lilac-bg, #e9e5fb);
  color: var(--lilac-text, #4b3fa0);
  font-size: 1.1rem;
  cursor: pointer;
}
.btn-soft {
  padding: 0.35rem 0.85rem;
  border: none;
  border-radius: 999px;
  background: var(--primary-tint, #ebe7ff);
  color: var(--primary, #6d5bd0);
  font: inherit;
  font-weight: 500;
  cursor: pointer;
}
.link {
  padding: 0;
  border: none;
  background: none;
  color: var(--primary, #6d5bd0);
  font: inherit;
  cursor: pointer;
  text-decoration: underline;
}
.grid {
  display: grid;
  grid-template-columns: repeat(7, minmax(0, 1fr));
  gap: 4px;
}
.dow {
  padding: 0.35rem 0;
  text-align: center;
  font-size: 0.75rem;
  font-weight: 600;
  color: var(--lilac-text, #4b3fa0);
  background: #ddd6fb;
  border-radius: 6px;
}
.day {
  min-height: 6.2rem;
  padding: 0.3rem;
  border: 1px solid var(--border, #e4defa);
  border-radius: 8px;
  background: #fff;
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}
.day.outside {
  background: #faf9ff;
  opacity: 0.6;
}
.day.today {
  border-color: var(--primary, #6d5bd0);
  box-shadow: inset 0 0 0 1px var(--primary, #6d5bd0);
}
.day-num {
  font-size: 0.75rem;
  color: var(--text-muted, #6b6890);
}
.chip {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  width: 100%;
  padding: 0.2rem 0.35rem;
  border: 1px solid transparent;
  border-radius: 6px;
  font: inherit;
  font-size: 0.72rem;
  line-height: 1.2;
  text-align: left;
  cursor: pointer;
  overflow: hidden;
}
.chip-time {
  font-weight: 600;
}
.chip-name,
.chip-sub {
  width: 100%;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.chip-sub {
  opacity: 0.8;
}
.chip.selected {
  outline: 2px solid var(--primary, #6d5bd0);
}
/* Unassigned requests stand out: dashed amber border and label */
.chip.unassigned {
  border: 1.5px dashed #d97706;
  background: #fff7e6;
  color: #8a4b00;
}
.chip.readonly {
  opacity: 0.6;
  border-style: dotted;
  border-color: currentColor;
}
.lilac { background: var(--lilac-bg, #e9e5fb); color: var(--lilac-text, #4b3fa0); }
.mint { background: var(--mint-bg, #d3f5e3); color: var(--mint-text, #1e6b47); }
.rose { background: var(--rose-bg, #ffdce3); color: var(--rose-text, #a12b47); }
.butter { background: var(--butter-bg, #fff1c2); color: var(--butter-text, #8a5a00); }
.sky { background: var(--sky-bg, #d6ecff); color: var(--sky-text, #1f5f99); }
.more {
  border: none;
  background: none;
  padding: 0;
  font-size: 0.72rem;
  color: var(--primary, #6d5bd0);
  cursor: pointer;
  text-align: left;
}
.undated {
  list-style: none;
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  margin: 0.75rem 0 0;
  padding: 0;
  font-size: 0.85rem;
}
.undated-title {
  color: var(--text-muted, #6b6890);
}
.detail {
  margin-top: 1rem;
  padding: 1rem;
  border: 1px solid var(--border, #e4defa);
  border-radius: 12px;
  background: #faf9ff;
}
.detail-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.detail-head h4 {
  margin: 0;
  font-size: 1rem;
}
dl {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 0.3rem 1rem;
  margin: 0.75rem 0;
  font-size: 0.9rem;
}
dt {
  color: var(--text-muted, #6b6890);
}
dd {
  margin: 0;
}
.unassigned-tag {
  padding: 0.1rem 0.55rem;
  border: 1.5px dashed #d97706;
  border-radius: 999px;
  background: #fff7e6;
  color: #8a4b00;
  font-size: 0.8rem;
}
.detail-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}
.btn-primary,
.detail-actions :slotted(.btn-secondary) {
  display: inline-block;
  padding: 0.45rem 1rem;
  border-radius: 999px;
  font-weight: 500;
  text-decoration: none;
}
.btn-primary {
  background: var(--primary, #6d5bd0);
  color: #fff;
}
.detail-actions :slotted(.btn-secondary) {
  background: var(--lilac-bg, #e9e5fb);
  color: var(--lilac-text, #4b3fa0);
}
@media (max-width: 700px) {
  .day {
    min-height: 4.5rem;
  }
  .chip-sub,
  .chip-time {
    display: none;
  }
}
</style>
