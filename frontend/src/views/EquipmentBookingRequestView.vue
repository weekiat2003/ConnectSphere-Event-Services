<template>
  <div class="equipment-booking">
    <h2 class="page-title">Equipment Booking</h2>
    <div class="tabs" role="tablist" aria-label="Equipment booking sections">
      <button type="button" role="tab" :aria-selected="tab === 'request'" :class="['tab', { active: tab === 'request' }]" @click="tab = 'request'">Request Equipment</button>
      <button type="button" role="tab" :aria-selected="tab === 'requests'" :class="['tab', { active: tab === 'requests' }]" @click="openRequests">My Equipment Requests</button>
    </div>

    <section v-if="tab === 'request'" class="card">
      <h3>Event</h3>
      <p class="muted">Only events in Planning status can be selected.</p>
      <label for="equipment-event">Select Event *</label>
      <select id="equipment-event" v-model="eventId" :disabled="loading || saving">
        <option value="">Select an event</option>
        <option v-for="event in planningEvents" :key="event.id" :value="String(event.id)">{{ event.name || event.title }}</option>
      </select>
      <p v-if="!loading && !planningEvents.length" class="muted">No events currently have Planning status.</p>

      <template v-if="selectedEvent">
        <div class="event-summary">
          <h4>Event Details</h4>
          <p><strong>Event:</strong> {{ selectedEvent.name || selectedEvent.title }}</p>
          <p><strong>Status:</strong> {{ selectedEvent.statusLabel || selectedEvent.status }}</p>
          <p v-if="selectedEvent.proposedDate"><strong>Proposed date:</strong> {{ selectedEvent.proposedDate }}</p>
        </div>

        <h3>Equipment Requirements</h3>
        <p class="muted">Select equipment from the catalogue, enter the quantity, and describe any technical requirements.</p>
        <div v-for="(item, index) in requirements" :key="item.key" class="equipment-item">
          <div class="item-header"><strong>Equipment {{ index + 1 }}</strong><button type="button" class="text-button" @click="requirements.splice(index, 1)">Remove</button></div>
          <div class="fields">
            <div><label :for="`eq-type-${index}`">Equipment type *</label>
              <select :id="`eq-type-${index}`" v-model="item.type" required>
                <option value="">Select equipment</option>
                <option v-if="item.type && !equipmentItems.some(e => e.name === item.type)" :value="item.type">{{ item.type }} (existing requirement)</option>
                <option v-for="eq in equipmentItems" :key="eq.id" :value="eq.name">{{ eq.name }}</option>
              </select>
            </div>
            <div><label :for="`eq-qty-${index}`">Quantity *</label><input :id="`eq-qty-${index}`" v-model.number="item.quantity" type="number" min="1" step="1" required /></div>
          </div>
          <label :for="`eq-notes-${index}`">Technical requirements</label>
          <textarea :id="`eq-notes-${index}`" v-model="item.technicalNotes" rows="2" placeholder="e.g. ceiling-mounted, 5 m cable"></textarea>
        </div>
        <button type="button" class="btn secondary" @click="addEquipment">+ Add Equipment</button>
        <p v-if="error" role="alert" class="error">{{ error }}</p>
        <p v-if="success" role="status" class="success">{{ success }}</p>
        <button type="button" class="btn primary submit" :disabled="saving || !requirements.length" @click="submit">{{ saving ? 'Saving…' : 'Submit Equipment Request' }}</button>
      </template>
      <p v-else-if="error" role="alert" class="error">{{ error }}</p>
    </section>

    <section v-else class="card">
      <div class="section-header"><h3>My Equipment Requests</h3><button class="btn secondary" type="button" @click="loadEvents">Refresh Status</button></div>
      <p v-if="error" role="alert" class="error">{{ error }}</p>
      <p v-if="!planningEvents.length" class="muted">No planning events available.</p>
      <article v-for="event in planningEvents" :key="event.id" class="request-card">
        <h4>{{ event.name || event.title }}</h4>
        <p v-if="!event.equipmentRequirements?.length" class="muted">No equipment requests for this event.</p>
        <table v-else><thead><tr><th>Equipment</th><th>Qty</th><th>Technical requirements</th><th>Status</th></tr></thead>
          <tbody><tr v-for="(req, i) in event.equipmentRequirements" :key="req.id || i"><td>{{ req.type }}</td><td>{{ req.quantity }}</td><td>{{ req.technicalNotes || '—' }}</td><td>{{ req.status || 'Pending' }}</td></tr></tbody>
        </table>
      </article>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from "vue";
import eventsApi from "../api/events";
import equipmentApi from "../api/equipment";

const tab = ref("request");
const events = ref([]);
const equipmentItems = ref([]);
const eventId = ref("");
const requirements = ref([]);
const loading = ref(false);
const saving = ref(false);
const error = ref("");
const success = ref("");
let nextKey = 0;

const planningEvents = computed(() => events.value.filter(e => String(e.status).toLowerCase() === "planning"));
const selectedEvent = computed(() => planningEvents.value.find(e => String(e.id) === String(eventId.value)));

function addEquipment() {
  requirements.value.push({ key: nextKey++, id: null, type: "", quantity: 1, technicalNotes: "" });
}
watch(selectedEvent, event => {
  requirements.value = (event?.equipmentRequirements || []).map(req => ({
    key: nextKey++, id: req.id ?? null, type: req.equipmentType ?? req.type ?? "",
    quantity: req.quantity ?? 1, technicalNotes: req.technicalNotes ?? "",
  }));
  error.value = "";
  success.value = "";
});

async function loadEvents() {
  loading.value = true;
  error.value = "";
  try {
    const { data } = await eventsApi.assignedEvents();
    events.value = Array.isArray(data) ? data : [];
    if (eventId.value && !events.value.some(e => String(e.id) === String(eventId.value) && String(e.status).toLowerCase() === "planning")) eventId.value = "";
  } catch (e) {
    error.value = e.response?.data?.error || "Unable to load assigned events.";
  } finally {
    loading.value = false;
  }
}
async function loadEquipment() {
  try {
    const { data } = await equipmentApi.listItems();
    equipmentItems.value = (Array.isArray(data) ? data : []).filter(e => e.status === "active");
  } catch (e) {
    error.value = e.response?.data?.error || "Unable to load equipment catalogue.";
  }
}
async function openRequests() {
  tab.value = "requests";
  await loadEvents();
}
async function submit() {
  error.value = "";
  success.value = "";
  if (!selectedEvent.value || String(selectedEvent.value.status).toLowerCase() !== "planning") {
    error.value = "Select an event in Planning status.";
    return;
  }
  if (!requirements.value.length || requirements.value.some(r => !r.type.trim() || !Number.isInteger(Number(r.quantity)) || Number(r.quantity) < 1)) {
    error.value = "Each equipment request needs a type and a positive whole-number quantity.";
    return;
  }
  saving.value = true;
  try {
    await eventsApi.updateEvent(selectedEvent.value.id, {
      fields: {
        equipment_requirements: requirements.value.map(r => ({
          ...(r.id != null ? { id: r.id } : {}),
          type: r.type.trim(), quantity: Number(r.quantity),
          technicalNotes: r.technicalNotes.trim(),
        })),
      },
      offlineReviewConfirmed: true,
    });
    await loadEvents();
    success.value = "Equipment requirements saved to the event for Technical Review.";
  } catch (e) {
    const details = e.response?.data;
    error.value = details?.error || (details?.errors ? JSON.stringify(details.errors) : "Unable to save equipment requirements.");
  } finally {
    saving.value = false;
  }
}
onMounted(async () => { await Promise.all([loadEvents(), loadEquipment()]); });
</script>

<style scoped>
.equipment-booking { color: var(--text, #2d2a4a); }
.page-title { margin: 0 0 1rem; font-size: 1.5rem; font-weight: 600; color: var(--text, #2d2a4a); }
.tabs { display: flex; gap: .5rem; margin: 0 0 1.25rem; border-bottom: 1px solid var(--border, #e4defa); }
.tab { padding: .8rem 1rem; border: none; border-bottom: 3px solid transparent; background: transparent; color: var(--text-muted, #6b6890); font: inherit; font-weight: 600; cursor: pointer; }
.tab.active { color: var(--lilac-text, #4b3fa0); border-bottom-color: var(--primary, #6d5bd0); }
.card { background: var(--surface, #fff); border: 1px solid var(--border, #e4defa); border-radius: 14px; box-shadow: 0 4px 16px rgba(109, 91, 208, .08); padding: 1.25rem; overflow: hidden; }
h3 { margin: 0 0 1rem; color: var(--text, #2d2a4a); font-size: 1.1rem; font-weight: 600; }
h4 { margin: 0 0 .8rem; color: var(--lilac-text, #4b3fa0); font-size: .95rem; }
label { display: block; color: var(--text, #2d2a4a); font-size: .875rem; font-weight: 500; margin: 0 0 .35rem; }
select, input[type=number], textarea { display: block; width: 100%; max-width: 100%; box-sizing: border-box; padding: .65rem .75rem; border: 1px solid var(--border, #e4defa); border-radius: 8px; background-color: #fff; color: var(--text, #2d2a4a); font: inherit; margin-bottom: 1rem; }
/* Use a single, consistently inset dropdown arrow rather than the browser's far-right default. */
select { appearance: none; -webkit-appearance: none; padding-right: 2.75rem; background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 24 24' fill='none' stroke='%236b6890' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='m6 9 6 6 6-6'/%3E%3C/svg%3E"); background-repeat: no-repeat; background-position: right 1rem center; background-size: 16px; }
select:focus, input:focus, textarea:focus { outline: 2px solid var(--primary, #6d5bd0); outline-offset: 1px; border-color: var(--primary, #6d5bd0); }
.muted { margin: 0 0 1rem; color: var(--text-muted, #6b6890); font-size: .9rem; }
.event-summary { margin-top: 1rem; padding: 1rem; background: #faf9ff; border: 1px solid var(--border, #e4defa); border-radius: 10px; }
.event-summary p { margin: .35rem 0; font-size: .875rem; }
.event-summary + h3 { margin-top: 1.5rem; }
.equipment-item { margin-top: 1rem; padding: 1.25rem; background: #faf9ff; border: 1px solid var(--border, #e4defa); border-radius: 12px; }
.item-header, .section-header { display: flex; align-items: center; justify-content: space-between; gap: 1rem; margin-bottom: 1rem; }
.item-header strong { color: var(--lilac-text, #4b3fa0); font-size: 1rem; }
.fields { display: grid; grid-template-columns: 2fr 1fr; gap: 0 1rem; }
.text-button { border: 0; background: transparent; color: var(--rose-text, #a12b47); font: inherit; font-size: .85rem; cursor: pointer; }
.text-button:hover { text-decoration: underline; }
.btn { display: inline-block; padding: .55rem 1.1rem; border: none; border-radius: 999px; font: inherit; font-weight: 500; cursor: pointer; }
.btn.primary { background: var(--primary, #6d5bd0); color: #fff; }
.btn.primary:hover:not(:disabled) { background: var(--primary-hover, #5b49bd); }
.btn.secondary { background: var(--lilac-bg, #e9e5fb); color: var(--lilac-text, #4b3fa0); }
.btn.secondary:hover { background: #ddd6fb; }
.btn:disabled { opacity: .6; cursor: not-allowed; }
.submit { display: block; margin: 1.25rem 0 0 auto; }
.confirmation { display: flex; align-items: flex-start; gap: .65rem; margin: 1.25rem 0 0; padding: .9rem 1rem; background: #faf9ff; border: 1px solid var(--border, #e4defa); border-radius: 10px; line-height: 1.5; }
.confirmation input { flex: none; margin: .2rem 0 0; accent-color: var(--primary, #6d5bd0); }
.error { margin: 1rem 0; padding: .8rem 1rem; border-radius: 8px; background: var(--rose-bg, #fde8ee); color: var(--rose-text, #a12b47); font-size: .875rem; }
.success { margin: 1rem 0; padding: .9rem 1rem; border-radius: 10px; background: var(--mint-bg, #d3f5e3); color: var(--mint-text, #1e6b47); }
.request-card { margin-top: 1rem; padding: 1.25rem; background: #faf9ff; border: 1px solid var(--border, #e4defa); border-radius: 12px; overflow-x: auto; }
table { width: 100%; border-collapse: collapse; text-align: left; font-size: .875rem; }
th, td { padding: .7rem; border-bottom: 1px solid var(--border, #e4defa); }
@media (max-width: 700px) { .fields { grid-template-columns: 1fr; } .section-header { align-items: flex-start; flex-direction: column; } .tabs { flex-wrap: wrap; } .submit { width: 100%; } }
/* More spacing between equipment fields and Add Equipment button */
.equipment-item + .btn.secondary {
  margin-top: 16px;
}
</style>
