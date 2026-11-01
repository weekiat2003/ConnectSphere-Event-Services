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
          :class="['cell', {
            outside: !cell.inMonth,
            today: cell.isToday,
            'has-items': cell.items.length,
            'popup-open': activePopupKey === cell.key,
          }]"
          :tabindex="cell.items.length ? 0 : -1"
          role="group"
          :aria-label="cellAriaLabel(cell)"
          :aria-expanded="activePopupKey === cell.key"
          :aria-haspopup="cell.items.length ? 'dialog' : undefined"
          :aria-controls="cell.items.length ? `day-popup-${cell.key}` : undefined"
          @mouseenter="cell.items.length && showPopup(cell, $event)"
          @focusin="cell.items.length && showPopup(cell, $event)"
          @click="cell.items.length && showPopup(cell, $event)"
          @keydown.enter.space.prevent="cell.items.length && showPopup(cell, $event)"
          @keydown.esc.stop.prevent="closePopup(true)"
          @mouseleave="schedulePopupClose"
        >
          <span class="day-num">
            {{ cell.day }}
            <span v-if="cell.items.length > 2" class="more-count">
              +{{ cell.items.length - 2 }} more
            </span>
          </span>
          <router-link
            v-for="r in cell.items.slice(0, 2)"
            :key="`${cell.key}-${r.key}`"
            :to="{ path: '/technical-review', query: { event: r.eventId } }"
            class="chip"
            :title="`${formatReservationTime(r.start)}–${formatReservationTime(r.end)} · ${r.quantity} × ${r.type} · ${r.eventName}`"
            @click.stop
          >
            <span class="chip-main">
              {{ formatReservationTime(r.start) }}–{{ formatReservationTime(r.end) }} · {{ r.quantity }} × {{ r.type }}
            </span>
            <small>{{ r.eventName }}</small>
          </router-link>

          <div
            v-if="activePopupKey === cell.key"
            :ref="setPopupElement"
            class="day-popup"
            :id="`day-popup-${cell.key}`"
            role="dialog"
            :aria-label="`Reservations for ${cellDateLabel(cell)}`"
            :style="popupPosition"
            @click.stop
            @mouseenter="cancelPopupClose"
            @mouseleave="schedulePopupClose"
            @keydown.esc.stop.prevent="closePopup(true)"
          >
            <strong class="popup-title">{{ cellDateLabel(cell) }}</strong>
            <ul class="popup-list">
              <li v-for="r in cell.items" :key="`${cell.key}-popup-${r.key}`">
                <router-link
                  :to="{ path: '/technical-review', query: { event: r.eventId } }"
                  class="popup-link"
                >
                  <span>{{ formatReservationTime(r.start) }}–{{ formatReservationTime(r.end) }} · {{ r.quantity }} × {{ r.type }}</span>
                  <small>{{ r.eventName }}</small>
                </router-link>
              </li>
            </ul>
          </div>
        </div>
      </div>
      <p v-if="!reservations.length" class="muted note">No equipment has been reserved yet.</p>
    </template>
  </section>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from "vue";
import eventsApi from "../api/events";
import equipmentApi from "../api/equipment";
import { formatReservationTime } from "../utils/display";

const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const HIDDEN_EVENT_STATUSES = ["draft", "cancelled", "rejected", "completed"];

const reservations = ref([]);
const loading = ref(true);
const error = ref("");
const warning = ref("");
const activePopupKey = ref(null);
const popupPosition = ref({ left: "0px", top: "0px" });
const popupRef = ref(null);
const activeCellElement = ref(null);
let popupCloseTimer;

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

function cellDateLabel(cell) {
  const [year, monthNumber, day] = cell.key.split("-").map(Number);
  return new Date(year, monthNumber - 1, day).toLocaleDateString([], {
    weekday: "long",
    year: "numeric",
    month: "long",
    day: "numeric",
  });
}

function cellAriaLabel(cell) {
  const count = cell.items.length;
  return count
    ? `${cellDateLabel(cell)}, ${count} reservation${count === 1 ? "" : "s"}`
    : cellDateLabel(cell);
}

function setPopupElement(element) { popupRef.value = element; }

function positionPopup() {
  const cell = activeCellElement.value;
  const popup = popupRef.value;
  if (!cell || !popup) return;

  const bounds = cell.getBoundingClientRect();
  const popupBounds = popup.getBoundingClientRect();
  const margin = 12;
  let left = bounds.left;
  if (left + popupBounds.width > window.innerWidth - margin) {
    left = bounds.right - popupBounds.width;
  }
  left = Math.max(margin, Math.min(left, window.innerWidth - popupBounds.width - margin));

  let top = bounds.bottom + margin / 2;
  if (top + popupBounds.height > window.innerHeight - margin) {
    top = bounds.top - popupBounds.height - margin / 2;
  }
  top = Math.max(margin, Math.min(top, window.innerHeight - popupBounds.height - margin));
  popupPosition.value = { left: `${left}px`, top: `${top}px` };
}

async function showPopup(cell, event) {
  cancelPopupClose();
  activePopupKey.value = cell.key;
  activeCellElement.value = event.currentTarget;
  await nextTick();
  positionPopup();
}

function closePopup(returnFocus = false) {
  cancelPopupClose();
  const cell = activeCellElement.value;
  activePopupKey.value = null;
  activeCellElement.value = null;
  if (returnFocus) cell?.focus();
}

function schedulePopupClose() {
  cancelPopupClose();
  popupCloseTimer = window.setTimeout(() => closePopup(), 180);
}

function cancelPopupClose() {
  if (popupCloseTimer) window.clearTimeout(popupCloseTimer);
  popupCloseTimer = undefined;
}

function handleOutsidePointerDown(event) {
  if (!activePopupKey.value) return;
  if (activeCellElement.value?.contains(event.target) || popupRef.value?.contains(event.target)) return;
  closePopup();
}

function handleEscape(event) {
  if (event.key === "Escape" && activePopupKey.value) {
    event.preventDefault();
    closePopup(true);
  }
}

// A reservation appears on every day it covers.
const byDay = computed(() => {
  const map = new Map();
  for (const r of reservations.value) {
    if (Number.isNaN(r.start.getTime()) || Number.isNaN(r.end.getTime()) || r.end <= r.start) continue;
    const day = new Date(r.start.getFullYear(), r.start.getMonth(), r.start.getDate());
    const last = new Date(r.end.getFullYear(), r.end.getMonth(), r.end.getDate());
    if (
      r.end.getHours() === 0
      && r.end.getMinutes() === 0
      && r.end.getSeconds() === 0
      && r.end.getMilliseconds() === 0
    ) {
      last.setDate(last.getDate() - 1);
    }
    while (day <= last) {
      const key = dayKey(day);
      if (!map.has(key)) map.set(key, []);
      map.get(key).push(r);
      day.setDate(day.getDate() + 1);
    }
  }
  for (const items of map.values()) items.sort((a, b) => a.start - b.start);
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

onMounted(() => {
  document.addEventListener("pointerdown", handleOutsidePointerDown);
  document.addEventListener("keydown", handleEscape);
  window.addEventListener("resize", positionPopup);
  document.addEventListener("scroll", positionPopup, true);
  load();
});

onBeforeUnmount(() => {
  cancelPopupClose();
  document.removeEventListener("pointerdown", handleOutsidePointerDown);
  document.removeEventListener("keydown", handleEscape);
  window.removeEventListener("resize", positionPopup);
  document.removeEventListener("scroll", positionPopup, true);
});
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
.cell { position: relative; min-height: 5.5rem; padding: 0.3rem; border: 1px solid var(--border, #e4defa); border-radius: 8px; background: #fff; }
.cell.has-items { cursor: pointer; }
.cell.popup-open { z-index: 20; opacity: 1; }
.cell.has-items:focus-visible { outline: 2px solid var(--primary, #6d5bd0); outline-offset: 2px; z-index: 21; }
.cell.outside { background: #faf9ff; opacity: 0.6; }
.cell.today { border-color: var(--primary, #6d5bd0); box-shadow: 0 0 0 1px var(--primary, #6d5bd0); }
.day-num { display: flex; align-items: center; justify-content: space-between; gap: 0.2rem; font-size: 0.75rem; color: var(--text-muted, #6b6890); margin-bottom: 0.2rem; }
.more-count { color: var(--primary, #6d5bd0); font-weight: 600; white-space: nowrap; }
.chip { display: block; margin-bottom: 0.2rem; padding: 0.15rem 0.4rem; border-radius: 6px; font-size: 0.72rem; font-weight: 500;
  background: var(--sky-bg, #d6ecff); color: var(--sky-text, #1f5f99); text-decoration: none; }
.chip-main, .chip small { display: block; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.chip small { font-weight: 400; opacity: 0.85; }
.day-popup { position: fixed; z-index: 30; width: min(340px, calc(100vw - 24px)); max-height: min(440px, calc(100vh - 24px));
  overflow: auto; padding: 0.75rem; border: 1px solid var(--border, #e4defa); border-radius: 10px;
  background: var(--surface, #fff); box-shadow: 0 8px 24px rgba(45, 42, 74, 0.2); cursor: default; }
.popup-title { display: block; margin-bottom: 0.4rem; font-size: 0.9rem; color: var(--text, #2d2a4a); }
.popup-list { display: grid; gap: 0.25rem; margin: 0; padding: 0; list-style: none; }
.popup-link { display: block; padding: 0.45rem 0.5rem; border-radius: 6px; color: var(--sky-text, #1f5f99);
  text-decoration: none; }
.popup-link:hover, .popup-link:focus-visible { background: var(--sky-bg, #d6ecff); outline: none; }
.popup-link span, .popup-link small { display: block; }
.popup-link small { margin-top: 0.1rem; color: var(--text-muted, #6b6890); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.muted { color: var(--text-muted, #6b6890); font-size: 0.9rem; }
.note { margin: 0.75rem 0 0; }
.error { margin: 0 0 1rem; padding: 0.6rem 0.9rem; border-radius: 10px; background: var(--rose-bg, #ffdce3);
  color: var(--rose-text, #a12b47); font-size: 0.9rem; }
.warning { margin: 0 0 1rem; padding: 0.6rem 0.9rem; border-radius: 10px; background: #fff3cd; color: #7a5d00; font-size: 0.9rem; }
</style>