<template>
  <div>
    <h2 class="page-title">Technical Review: Equipment Requirements</h2>
    <p v-if="error" class="error">{{ error }}</p>
    <p v-if="loading" class="loading">Loading…</p>
    <div v-else-if="!events.length" class="card empty"><p>No events to review yet.</p></div>

    <label v-if="!loading && events.length" class="toggle">
      <input v-model="showEmpty" type="checkbox" />
      Show events without equipment ({{ hiddenCount }} hidden)
    </label>

    <div v-if="!loading && events.length && !visibleEvents.length" class="card empty">
      <p>No events have equipment requirements yet.</p>
    </div>

    <div
      v-for="event in visibleEvents"
      :id="`event-${event.id}`"
      :key="event.id"
      :class="['card', { highlight: event.id === highlightEventId }]"
    >
      <div class="card-head">
        <router-link :to="{ name: 'event-detail', params: { id: event.id } }" class="event-name">{{ event.name }}</router-link>
        <span class="muted">{{ event.proposedDate || "—" }}</span>
        <StatusBadge kind="event" :status="event.status" :label="event.statusLabel" />
      </div>
      <p v-if="!event.equipmentRequirements.length" class="muted empty-note">
        No equipment requirements for this event.
      </p>
      <table v-else class="req-table">
        <thead>
          <tr>
            <th>Type</th><th>Qty</th><th>Technical requirements</th><th>Status</th>
            <th>Reservation</th><th v-if="isTechSupport">Actions</th>
          </tr>
        </thead>
        <tbody>
          <template v-for="req in event.equipmentRequirements" :key="req.id">
            <tr>
              <td>{{ req.type }}</td>
              <td>{{ req.quantity }}</td>
              <td>{{ req.technicalNotes || "—" }}</td>
              <td>
                <StatusBadge kind="requirement" :status="req.status" />
                <span v-if="req.needsRecheck" class="badge-warn">Needs recheck</span>
              </td>
              <td>{{ reservationText(req.reservation) }}</td>
              <td v-if="isTechSupport">
                <button
                  v-if="!req.reservation"
                  type="button"
                  class="btn btn-primary"
                  @click="openReservation(event, req)"
                >
                  Reserve
                </button>
                <button
                  v-else
                  type="button"
                  class="btn btn-grey"
                  :disabled="releasingReservationId === req.reservation.id"
                  @click="releaseReservation(event, req)"
                >
                  {{ releasingReservationId === req.reservation.id ? "Releasing…" : "Release" }}
                </button>
                <button
                  v-if="req.status === 'confirmed' && req.needsRecheck"
                  type="button"
                  class="btn btn-grey"
                  :disabled="confirmingRecheckId === req.id"
                  @click="confirmStillSuitable(event, req)"
                >
                  {{ confirmingRecheckId === req.id ? "Confirming…" : "Confirm still suitable" }}
                </button>
                <p v-if="req.actionError" class="form-error" role="alert">
                  {{ req.actionError }}
                </p>
                <p v-if="req.recheckError" class="form-error" role="alert">
                  {{ req.recheckError }}
                </p>
              </td>
            </tr>
            <tr
              v-if="reservationForm?.key === rowKey(event.id, req.id)"
              class="reserve-row"
            >
              <td :colspan="isTechSupport ? 6 : 5">
                <form class="reserve-form" @submit.prevent="submitReservation(event, req)">
                  <label class="field">
                    <span>Equipment item</span>
                    <select v-model="reservationForm.equipmentItemId" required>
                      <option disabled value="">Select matching equipment</option>
                      <option
                        v-for="item in matchingItems(req)"
                        :key="item.id"
                        :value="item.id"
                      >
                        {{ item.name }} ({{ item.totalQuantity }} total)
                      </option>
                    </select>
                  </label>
                  <label class="field">
                    <span>Quantity</span>
                    <input
                      :value="req.quantity"
                      type="number"
                      min="1"
                      :max="req.quantity"
                      readonly
                      required
                    />
                  </label>
                  <label class="field">
                    <span>Start</span>
                    <input v-model="reservationForm.start" type="datetime-local" required />
                  </label>
                  <label class="field">
                    <span>End</span>
                    <input v-model="reservationForm.end" type="datetime-local" required />
                  </label>
                  <p v-if="!matchingItems(req).length" class="muted form-note">
                    No active catalogue item matches this equipment type.
                  </p>
                  <p v-if="reservationForm.error" class="form-error" role="alert">
                    {{ reservationForm.error }}
                  </p>
                  <div class="form-actions">
                    <button
                      class="btn btn-primary"
                      type="submit"
                      :disabled="reservationForm.submitting || !matchingItems(req).length"
                    >
                      {{ reservationForm.submitting ? "Reserving…" : "Confirm" }}
                    </button>
                    <button
                      class="btn btn-grey"
                      type="button"
                      :disabled="reservationForm.submitting"
                      @click="closeReservation"
                    >
                      Cancel
                    </button>
                  </div>
                </form>
              </td>
            </tr>
          </template>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, ref } from "vue";
import { useRoute } from "vue-router";
import eventsApi from "../api/events";
import equipmentApi from "../api/equipment";
import StatusBadge from "../components/StatusBadge.vue";
import { useAuthStore } from "../stores/auth";
import { useConfirm } from "../composables/useConfirm";
import { formatReservationDateTime } from "../utils/display";

const HIDDEN_EVENT_STATUSES = ["draft", "cancelled", "rejected", "completed"];

// Opened from an equipment notification: /technical-review?event=ID
const highlightEventId = Number(useRoute().query.event) || null;

const events = ref([]);
const equipmentItems = ref([]);
const loading = ref(true);
const error = ref("");
const showEmpty = ref(false);
const reservationForm = ref(null);
const releasingReservationId = ref(null);
const confirmingRecheckId = ref(null);
const auth = useAuthStore();
const { confirm } = useConfirm();
const isTechSupport = computed(() => auth.hasRole("technical_support_staff"));

const visibleEvents = computed(() =>
  events.value.filter(
    (e) => showEmpty.value || e.equipmentRequirements.length || e.id === highlightEventId
  )
);
const hiddenCount = computed(() => events.value.length - visibleEvents.value.length);

function message(e, fallback) { return e.response?.data?.error || fallback; }
function rowKey(eventId, requirementId) { return `${eventId}-${requirementId}`; }
function normalizedName(name) { return String(name || "").trim().toLowerCase(); }
function matchingItems(requirement) {
  const type = normalizedName(requirement.type);
  return equipmentItems.value.filter(
    (item) => item.status === "active" && normalizedName(item.name) === type
  );
}
function initialStart(event) {
  if (!event.proposedDate) return "";
  const time = String(event.proposedTime || "09:00").slice(0, 5);
  return `${event.proposedDate}T${time}`;
}
function addHours(value, hours) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  date.setHours(date.getHours() + hours);
  const pad = (part) => String(part).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}
function reservationText(r) {
  if (!r) return "—";
  return `${r.quantity} × ${formatReservationDateTime(r.start)} to ${formatReservationDateTime(r.end)}`;
}

async function reloadRequirement(event, requirement) {
  const { data } = await equipmentApi.eventRequirements(event.id);
  const updated = data.requirements.find((row) => row.id === requirement.id);
  if (!updated) throw new Error("Equipment requirement was not returned after reload.");
  Object.assign(requirement, updated, { recheckError: "" });
}

async function confirmStillSuitable(event, requirement) {
  const confirmed = await confirm(
    `Confirm that ${requirement.type} is still suitable for ${event.name}?`
  );
  if (!confirmed) return;

  requirement.recheckError = "";
  confirmingRecheckId.value = requirement.id;
  try {
    await equipmentApi.confirmRecheck(requirement.id);
    await reloadRequirement(event, requirement);
  } catch (e) {
    requirement.recheckError = message(e, "Could not confirm equipment suitability.");
  } finally {
    confirmingRecheckId.value = null;
  }
}

function openReservation(event, requirement) {
  const start = initialStart(event);
  reservationForm.value = {
    key: rowKey(event.id, requirement.id),
    equipmentItemId: "",
    start,
    end: addHours(start, 3),
    error: "",
    submitting: false,
  };
}

function closeReservation() {
  reservationForm.value = null;
}

async function submitReservation(event, requirement) {
  const form = reservationForm.value;
  if (!form) return;
  const selectedItem = matchingItems(requirement).find(
    (item) => item.id === form.equipmentItemId
  );
  if (!selectedItem) {
    form.error = "Select an active equipment item matching this requirement.";
    return;
  }

  form.error = "";
  form.submitting = true;
  const confirmed = await confirm(
    `Reserve ${requirement.quantity} × ${selectedItem.name} for ${event.name}?`
  );
  if (!confirmed) {
    form.submitting = false;
    return;
  }

  try {
    await equipmentApi.reserve({
      eventId: event.id,
      requirementId: requirement.id,
      equipmentItemId: form.equipmentItemId,
      quantity: requirement.quantity,
      start: form.start,
      end: form.end,
    });
    closeReservation();
    await load();
  } catch (e) {
    form.error = message(e, "Could not reserve this equipment.");
    form.submitting = false;
  }
}

async function releaseReservation(event, requirement) {
  requirement.actionError = "";
  const confirmed = await confirm(
    `Release ${requirement.reservation.quantity} × ${requirement.type} for ${event.name}?`
  );
  if (!confirmed) return;

  releasingReservationId.value = requirement.reservation.id;
  try {
    await equipmentApi.release(requirement.reservation.id);
    await load();
  } catch (e) {
    requirement.actionError = message(e, "Could not release this equipment reservation.");
  } finally {
    releasingReservationId.value = null;
  }
}

async function load() {
  loading.value = true;
  error.value = "";
  try {
    const [{ data }, { data: items }] = await Promise.all([
      eventsApi.allEvents(),
      equipmentApi.listItems(),
    ]);
    equipmentItems.value = Array.isArray(items) ? items : [];
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

onMounted(async () => {
  await load();
  if (highlightEventId) {
    await nextTick();
    document.getElementById(`event-${highlightEventId}`)?.scrollIntoView({ block: "start" });
  }
});
</script>

<style scoped>
.card.highlight { border-color: var(--primary); box-shadow: 0 0 0 2px var(--primary-tint); }
.page-title { margin: 0 0 1rem; font-size: 1.5rem; font-weight: 600; color: var(--text, #2d2a4a); }
.toggle { display: inline-flex; align-items: center; gap: 0.4rem; margin-bottom: 1rem; color: var(--text-muted, #6b6890); font-size: 0.9rem; }
.card { background: var(--surface, #fff); border: 1px solid var(--border, #e4defa); border-radius: 14px;
  box-shadow: 0 4px 16px rgba(109, 91, 208, 0.08); padding: 1rem; margin-bottom: 1rem; }
.card-head { display: flex; flex-wrap: wrap; align-items: center; gap: 0.75rem; margin-bottom: 0.75rem; }
.event-name { font-weight: 600; font-size: 1.05rem; color: var(--primary, #6d5bd0); text-decoration: none; }
.muted { color: var(--text-muted, #6b6890); font-size: 0.9rem; }
.empty-note { margin: 0; }
.req-table { width: 100%; border-collapse: collapse; }
.req-table th, .req-table td { text-align: left; padding: 0.5rem 0.6rem; border-bottom: 1px solid var(--border, #e4defa); }
.req-table th { font-size: 0.8rem; color: var(--text-muted, #6b6890); font-weight: 500; }
.btn { padding: 0.4rem 1rem; border: none; border-radius: 999px; font: inherit; font-size: 0.9rem; font-weight: 500; cursor: pointer; }
.btn:disabled { opacity: 0.6; cursor: not-allowed; }
.btn-primary { background: var(--primary, #6d5bd0); color: #fff; }
.btn-grey { background: #e2e5ea; color: #333; }
.reserve-row td { background: #faf9ff; }
.reserve-form { display: flex; flex-wrap: wrap; align-items: flex-end; gap: 0.75rem; padding: 0.35rem 0; }
.field { display: flex; flex-direction: column; gap: 0.25rem; font-size: 0.8rem; font-weight: 500; color: var(--text-muted, #6b6890); }
.field input, .field select { min-width: 12rem; padding: 0.4rem 0.7rem; border: 1px solid var(--border, #e4defa); border-radius: 8px; font: inherit; color: var(--text, #2d2a4a); }
.req-table select { max-width: 9rem; padding: 0.35rem; border: 1px solid var(--border, #e4defa); border-radius: 8px; font: inherit; color: var(--text, #2d2a4a); }
.req-table select:disabled { opacity: 0.65; }
.field input[type="number"] { min-width: 5rem; width: 5rem; }
.form-actions { display: inline-flex; gap: 0.5rem; }
.form-note, .form-error { flex-basis: 100%; margin: 0; }
.form-error { margin-top: 0.35rem; color: var(--rose-text, #a12b47); font-size: 0.9rem; }
.badge-warn { display: inline-block; padding: 0.15rem 0.65rem; border-radius: 999px; font-size: 0.8rem; font-weight: 500;
  background: var(--butter-bg, #fff1c2); color: var(--butter-text, #8a5a00); }
.error { margin: 0 0 1rem; padding: 0.6rem 0.9rem; border-radius: 10px; background: var(--rose-bg, #ffdce3);
  color: var(--rose-text, #a12b47); font-size: 0.9rem; }
.empty { text-align: center; color: var(--text-muted, #6b6890); }
.loading { color: var(--text-muted, #6b6890); }
</style>