<template>
  <section class="card calendar">
    <div class="cal-head">
      <h3 class="cal-title">Equipment reservation calendar</h3>
      <div class="cal-nav">
        <button class="btn" aria-label="Previous month" @click="shift(-1)">‹</button>
        <strong class="month">{{ monthLabel }}</strong>
        <button class="btn" aria-label="Next month" @click="shift(1)">›</button>
        <button class="btn" @click="goToday">Today</button>
      </div>
    </div>

    <p v-if="error" class="error">{{ error }}</p>
    <p v-if="warning" class="warning">{{ warning }}</p>
    <p v-if="loading" class="muted">Loading…</p>

    <template v-else>
      <div class="grid weekdays">
        <span v-for="d in WEEKDAYS" :key="d">{{ d }}</span>
      </div>
      <div class="grid">
        <div
          v-for="cell in cells"
          :key="cell.key"
          :class="['cell', { outside: !cell.inMonth, today: cell.isToday }]"
        >
          <span class="day-num">{{ cell.day }}</span>
          <router-link
            v-for="r in cell.items"
            :key="`${cell.key}-${r.key}`"
            :to="{ path: '/technical-review', query: { event: r.eventId } }"
            class="chip"
            :title="`${r.quantity} × ${r.type} for ${r.eventName}`"
          >
            {{ r.quantity }} × {{ r.type }}
            <small>{{ r.eventName }}</small>
          </router-link>
        </div>
      </div>
      <p v-if="!reservations.length" class="muted note">No equipment has been reserved yet.</p>
    </template>
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from "vue";
import eventsApi from "../api/events";
import equipmentApi from "../api/equipment";

const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const HIDDEN_EVENT_STATUSES = ["draft", "cancelled", "rejected", "completed"];

const reservations = ref([]);
const loading = ref(true);
const error = ref("");
const warning = ref("");

function startOfMonth(d) { return new Date(d.getFullYear(), d.getMonth(), 1); }
function dayKey(d) { return `${d.getFullYear()}-${d.getMonth() + 1}-${d.getDate()}`; }

const month = ref(startOfMonth(new Date()));
const monthLabel = computed(() =>
  month.value.toLocaleDateString([], { month: "long", year: "numeric" })
);

function shift(n) {
  month.value = new Date(month.value.getFullYear(), month.value.getMonth() + n, 1);
}
function goToday() { month.value = startOfMonth(new Date()); }

// A reservation appears on every day it covers.
const byDay = computed(() => {
  const map = new Map();
  for (const r of reservations.value) {
    const day = new Date(r.start.getFullYear(), r.start.getMonth(), r.start.getDate());
    const last = new Date(r.end.getFullYear(), r.end.getMonth(), r.end.getDate());
    for (let n = 0; day <= last && n < 62; n += 1) {
      const key = dayKey(day);
      if (!map.has(key)) map.set(key, []);
      map.get(key).push(r);
      day.setDate(day.getDate() + 1);
    }
  }
  return map;
});

const cells = computed(() => {
  const first = month.value;
  const gridStart = new Date(first.getFullYear(), first.getMonth(), 1 - first.getDay());
  const daysInMonth = new Date(first.getFullYear(), first.getMonth() + 1, 0).getDate();
  const total = Math.ceil((first.getDay() + daysInMonth) / 7) * 7;
  const todayKey = dayKey(new Date());
  return Array.from({ length: total }, (_, i) => {
    const d = new Date(gridStart.getFullYear(), gridStart.getMonth(), gridStart.getDate() + i);
    const key = dayKey(d);
    return {
      key,
      day: d.getDate(),
      inMonth: d.getMonth() === first.getMonth(),
      isToday: key === todayKey,
      items: byDay.value.get(key) || [],
    };
  });
});

async function load() {
  try {
    const { data } = await eventsApi.allEvents();
    const visible = data.filter((e) => !HIDDEN_EVENT_STATUSES.includes(e.status));
    const results = await Promise.allSettled(
      visible.map((e) => equipmentApi.eventRequirements(e.id))
    );

    const found = [];
    let failed = 0;
    results.forEach((result, i) => {
      if (result.status !== "fulfilled") {
        failed += 1;
        return;
      }
      const event = visible[i];
      const types = new Map((event.equipmentRequirements || []).map((r) => [r.id, r.type]));
      for (const req of result.value.data.requirements || []) {
        if (!req.reservation) continue;
        found.push({
          key: `${event.id}-${req.id}`,
          eventId: event.id,
          eventName: event.name,
          type: types.get(req.id) || "Equipment",
          quantity: req.reservation.quantity,
          start: new Date(req.reservation.start),
          end: new Date(req.reservation.end),
        });
      }
    });

    found.sort((a, b) => a.start - b.start);
    reservations.value = found;
    if (failed) warning.value = "Could not load reservations for some events.";

    const upcoming = found.find((r) => r.end >= new Date());
    if (upcoming) month.value = startOfMonth(upcoming.start);
  } catch (e) {
    error.value = e.response?.data?.error || "Could not load reservations.";
  } finally {
    loading.value = false;
  }
}

onMounted(load);
</script>

<style scoped>
.card { background: var(--surface, #fff); border: 1px solid var(--border, #e4defa); border-radius: 14px;
  box-shadow: 0 4px 16px rgba(109, 91, 208, 0.08); padding: 1rem; margin-bottom: 1rem; }
.cal-head { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 0.75rem; margin-bottom: 0.75rem; }
.cal-title { margin: 0; font-size: 1.1rem; font-weight: 600; color: var(--text, #2d2a4a); }
.cal-nav { display: flex; align-items: center; gap: 0.5rem; }
.month { min-width: 9rem; text-align: center; }
.btn { padding: 0.3rem 0.8rem; border: none; border-radius: 999px; background: var(--lilac-bg, #e9e5fb);
  color: var(--lilac-text, #4b3fa0); font: inherit; font-weight: 500; cursor: pointer; }
.grid { display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); gap: 4px; }
.weekdays span { padding: 0.35rem; text-align: center; font-size: 0.8rem; font-weight: 600; color: var(--text-muted, #6b6890); }
.cell { min-height: 5.5rem; padding: 0.3rem; border: 1px solid var(--border, #e4defa); border-radius: 8px; background: #fff; overflow: hidden; }
.cell.outside { background: #faf9ff; opacity: 0.6; }
.cell.today { border-color: var(--primary, #6d5bd0); box-shadow: 0 0 0 1px var(--primary, #6d5bd0); }
.day-num { display: block; font-size: 0.75rem; color: var(--text-muted, #6b6890); margin-bottom: 0.2rem; }
.chip { display: block; margin-bottom: 0.2rem; padding: 0.15rem 0.4rem; border-radius: 6px; font-size: 0.75rem; font-weight: 500;
  background: var(--sky-bg, #d6ecff); color: var(--sky-text, #1f5f99); text-decoration: none; }
.chip small { display: block; font-weight: 400; opacity: 0.85; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.muted { color: var(--text-muted, #6b6890); font-size: 0.9rem; }
.note { margin: 0.75rem 0 0; }
.error { margin: 0 0 1rem; padding: 0.6rem 0.9rem; border-radius: 10px; background: var(--rose-bg, #ffdce3);
  color: var(--rose-text, #a12b47); font-size: 0.9rem; }
.warning { margin: 0 0 1rem; padding: 0.6rem 0.9rem; border-radius: 10px; background: #fff3cd; color: #7a5d00; font-size: 0.9rem; }
</style>