<template>
  <div>
    <h2 class="page-title">
      {{ isEditMode ? "Edit Draft Event Request" : "New Event Request" }}
    </h2>

    <div class="card">
      <form @submit.prevent="submit">
        <label>
          Name
          <input v-model="form.name" required />
        </label>

        <label>
          Purpose
          <input v-model="form.purpose" required />
        </label>

        <label>
          Description
          <textarea v-model="form.description" required></textarea>
        </label>

        <label>
          Proposed Date
          <input
            v-model="form.proposed_date"
            type="date"
            :min="todayString"
          />
        </label>

        <label>
          Proposed Time
          <input v-model="form.proposed_time" type="time" />
        </label>

        <label>
          Expected Attendance
          <input
            v-model.number="form.expected_attendance"
            type="number"
            min="1"
          />
        </label>

        <label>
          Capacity Needed
          <input
            v-model.number="form.capacity_needed"
            type="number"
            min="1"
            placeholder="Minimum venue capacity"
          />
        </label>

        <label>
          Required Layout

          <select v-model="form.required_layout">
            <option value="">Select a layout</option>

            <option
              v-for="layout in venueLayouts"
              :key="layout"
              :value="layout"
            >
              {{ layout }}
            </option>
          </select>

          <span v-if="!venueLayouts.length" class="hint">
            No venue layouts available.
          </span>
        </label>

        <label>
          Accessibility Needs
          <textarea v-model="form.accessibility_needs"></textarea>
        </label>


        <div class="equipment-section full">
          <div class="equipment-heading">
            <div>
              <h3>Equipment Required</h3>
              <p class="equipment-description">
                Select equipment from the catalogue and specify the quantity needed for your event.
              </p>
            </div>
          </div>

          <div
            v-for="(item, index) in equipmentRequirements"
            :key="index"
            class="equipment-item"
          >
            <div class="item-header">
              <strong>Equipment {{ index + 1 }}</strong>

              <button
                type="button"
                class="text-button"
                @click="equipmentRequirements.splice(index, 1)"
              >
                Remove
              </button>
            </div>

            <div class="equipment-fields">
              <label>
                Equipment Type *
                <select v-model="item.type" required>
                  <option value="">Select equipment</option>
                  <option
                    v-for="eq in equipmentItems"
                    :key="eq.id"
                    :value="eq.name"
                  >
                    {{ eq.name }}
                  </option>
                </select>
              </label>

              <label>
                Quantity *
                <input
                  v-model.number="item.quantity"
                  type="number"
                  min="1"
                  required
                />
              </label>
            </div>

            <label class="technical-label">
              Technical Requirements
              <textarea
                v-model="item.technicalNotes"
                rows="2"
                placeholder="e.g. HDMI connection required"
              ></textarea>
            </label>
          </div>

          <button
            type="button"
            class="btn-add-equipment"
            @click="addEquipment"
          >
            + Add Equipment
          </button>
        </div>
       
        <label class="checkbox">
          <input v-model="form.registration_required" type="checkbox" />
          Registration required
        </label>

        <label v-if="form.registration_required">
          Intended Capacity (optional)
          <input
            v-model.number="form.intended_capacity"
            type="number"
            min="1"
            placeholder="Optional if not yet known"
          />
        </label>

        <p v-if="error" class="error full">{{ error }}</p>

        <div class="actions full">
          <button type="button" class="btn-draft" @click="saveDraft">
            {{ isEditMode ? "Save Changes" : "Save as Draft" }}
          </button>

          <button type="submit" class="btn-submit">
            Submit Now
          </button>
        </div>
      </form>
    </div>
  </div>
</template>



<script setup>
import { onMounted, reactive, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import eventsApi from "../api/events";
import equipmentApi from "../api/equipment";
import { useConfirm } from "../composables/useConfirm";
import venuesApi from "../api/venues";

async function loadEquipmentCatalogue() {
  try {
    const { data } = await equipmentApi.listItems();

    equipmentItems.value = (Array.isArray(data) ? data : [])
      .filter(item => item.status === "active");
  } catch (e) {
    error.value =
      e.response?.data?.error ||
      "Could not load equipment catalogue.";
  }
}

const route = useRoute();
const router = useRouter();
const error = ref("");
const todayString = new Date().toISOString().split("T")[0];
const { confirm } = useConfirm();

const draftId = route.params.id;
const isEditMode = Boolean(draftId);
const form = reactive({
  name: "",
  purpose: "",
  description: "",
  proposed_date: "",
  proposed_time: "",
  expected_attendance: null,
  capacity_needed: null,
  required_layout: "",
  accessibility_needs: "",
  registration_required: false,
  intended_capacity: null,
});

const equipmentItems = ref([]);

const equipmentRequirements = ref([]);

const venueLayouts = ref([]);

async function loadVenueLayouts() {
  try {
    const { data } = await venuesApi.listVenues();

    // Get layouts from all active venues
    const layouts = data.flatMap(venue =>
      venue.supportedLayouts || []
    );

    // Remove duplicate layout names
    venueLayouts.value = [
      ...new Set(layouts.filter(layout => layout && layout.trim()))
    ].sort();

  } catch (e) {
    error.value =
      e.response?.data?.error ||
      "Could not load venue layouts.";
  }
}

async function loadDraft() {
  error.value = "";

  try {
    const { data } = await eventsApi.getEvent(draftId);

    if (data.status !== "draft") {
      error.value = "Only draft event requests can be edited.";
      return;
    }

    Object.assign(form, {
      name: data.name || "",
      purpose: data.purpose || "",
      description: data.description || "",
      proposed_date: data.proposedDate || "",
      proposed_time: data.proposedTime ? data.proposedTime.slice(0, 5) : "",
      expected_attendance: data.expectedAttendance ?? null,
      capacity_needed: data.venueRequirements?.capacityNeeded ?? null,
      required_layout: data.venueRequirements?.requiredLayout || "",
      accessibility_needs:
        data.venueRequirements?.accessibilityNeeds || "",
      registration_required: data.registrationRequired ?? false,
      intended_capacity: data.intendedCapacity ?? null,
    });
  } catch (e) {
    error.value = e.response?.data?.error || "Could not load this draft.";
  }
  equipmentRequirements.value = (
  data.equipmentRequirements || []
).map(item => ({
  type: item.type || "",
  quantity: item.quantity || 1,
  technicalNotes: item.technicalNotes || "",
}));
}

function sanitizePayload(data) {
  const cleaned = {
    ...data,

    equipment_requirements: equipmentRequirements.value.map(item => ({
      type: item.type,
      quantity: Number(item.quantity),
      technicalNotes: item.technicalNotes,
    })),
  };

  if (!cleaned.proposed_date) {
    cleaned.proposed_date = null;
  }

  if (!cleaned.proposed_time) {
    cleaned.proposed_time = null;
  }

  if (!cleaned.intended_capacity) {
    cleaned.intended_capacity = null;
  }

  return cleaned;
}

function validateDate() {
  if (!form.proposed_date) return true;

  if (form.proposed_date < todayString) {
    error.value = "Proposed date cannot be in the past.";
    return false;
  }

  return true;
}

async function saveDraft() {
  error.value = "";

  if (!validateDate()) {
    return;
  }

  try {
    const payload = sanitizePayload(form);

    if (isEditMode) {
      await eventsApi.updateDraft(draftId, payload);
    } else {
      await eventsApi.saveDraft(payload);
    }

    router.push({ name: "drafts" });
  } catch (e) {
    error.value = e.response?.data?.error || "Could not save draft.";
  }
}

const FIELD_LABELS = {
  proposed_date: "Proposed Date",
  proposed_time: "Proposed Time",
  expected_attendance: "Expected Attendance",
  capacity_needed: "Capacity Needed",
  required_layout: "Required Layout",
  accessibility_needs: "Accessibility Needs",
  name: "Name",
  purpose: "Purpose",
  description: "Description",
};

function friendlyError(rawMessage) {
  const match = rawMessage?.match(/Missing required field\(s\):\s*(.+)/i);
  if (!match) return rawMessage;

  const fields = match[1].split(",").map((f) => f.trim());
  const labels = fields.map((f) => FIELD_LABELS[f] || f);

  return `Please fill in: ${labels.join(", ")}`;
}

function addEquipment() {
  equipmentRequirements.value.push({
    type: "",
    quantity: 1,
    technicalNotes: "",
  });
}

async function submit() {
  error.value = "";

  if (!validateDate()) {
    return;
  }

  const confirmed = await confirm(
    "Submit this event request for review? You won't be able to edit it directly afterwards."
  );
  if (!confirmed) return;

  try {
    const payload = sanitizePayload(form);

    if (isEditMode) {
      await eventsApi.updateDraft(draftId, payload);
      await eventsApi.submitEvent(draftId);
    } else {
      await eventsApi.createEvent({ ...payload, submit: true });
    }
    router.push({ name: "dashboard" });
  } catch (e) {
    error.value = friendlyError(e.response?.data?.error) || "Could not submit request";
  }
}

onMounted(() => {
  loadEquipmentCatalogue();
  loadVenueLayouts();

  if (isEditMode) {
    loadDraft();
  }
});
</script>

<style scoped>
.page-title {
  margin: 0 0 1rem;
  font-size: 1.5rem;
  font-weight: 600;
  color: var(--text, #2d2a4a);
}

.card {
  max-width: 720px;
  padding: 1.5rem;
  background: var(--surface, #ffffff);
  border: 1px solid var(--border, #e4defa);
  border-radius: 14px;
  box-shadow: 0 4px 16px rgba(109, 91, 208, 0.08);
}

/* Two columns on wide screens; .full fields span both */
form {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1rem;
}

.full {
  grid-column: 1 / -1;
}

label {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  font-size: 0.9rem;
  font-weight: 500;
  color: var(--text, #2d2a4a);
}

label.checkbox {
  flex-direction: row;
  align-items: center;
  gap: 0.5rem;
}

input,
textarea,
select {
  padding: 0.6rem 0.75rem;
  border: 1px solid var(--border, #e4defa);
  border-radius: 10px;
  background: #fcfbff;
  color: var(--text, #2d2a4a);
  font: inherit;
  font-weight: 400;
}

input::placeholder,
textarea::placeholder,
select::placeholder {
  color: #a5a2c2;
}

input:focus,
textarea:focus {
  outline: none;
  border-color: var(--primary, #6d5bd0);
  background: #ffffff;
  box-shadow: 0 0 0 3px var(--primary-tint, #ebe7ff);
}

input[type="checkbox"] {
  width: 1.1rem;
  height: 1.1rem;
  padding: 0;
  accent-color: var(--primary, #6d5bd0);
}

textarea {
  min-height: 90px;
  resize: vertical;
}

/* Buttons */
.actions {
  display: flex;
  gap: 0.6rem;
  margin-top: 0.25rem;
}

.btn-draft,
.btn-submit {
  padding: 0.55rem 1.3rem;
  border: none;
  border-radius: 999px;
  font: inherit;
  font-weight: 500;
  cursor: pointer;
}

.btn-draft {
  background: var(--lilac-bg, #e9e5fb);
  color: var(--lilac-text, #4b3fa0);
}

.btn-draft:hover {
  background: #ddd6fb;
}

.btn-submit {
  background: var(--primary, #6d5bd0);
  color: #ffffff;
}

.btn-submit:hover {
  background: var(--primary-hover, #5b49bd);
}

.btn-draft:focus-visible,
.btn-submit:focus-visible {
  outline: 2px solid var(--primary, #6d5bd0);
  outline-offset: 2px;
}

/* Error message */
.error {
  margin: 0;
  padding: 0.6rem 0.9rem;
  border-radius: 10px;
  background: var(--rose-bg, #ffdce3);
  color: var(--rose-text, #a12b47);
  font-size: 0.9rem;
}

/* One column on phones */
@media (max-width: 560px) {
  form {
    grid-template-columns: 1fr;
  }
}


/* Equipment requirements section */
.equipment-section {
  padding: 1.25rem;
  background: #faf9ff;
  border: 1px solid var(--border, #e4defa);
  border-radius: 12px;
}

.equipment-heading h3 {
  margin: 0 0 0.4rem;
  color: var(--lilac-text, #4b3fa0);
  font-size: 1.05rem;
  font-weight: 600;
}

.equipment-description {
  margin: 0 0 1rem;
  color: var(--text-muted, #6b6890);
  font-size: 0.875rem;
  line-height: 1.5;
}

.equipment-item {
  margin-top: 1rem;
  padding: 1.1rem;
  background: #ffffff;
  border: 1px solid var(--border, #e4defa);
  border-radius: 10px;
}

.item-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 1rem;
}

.item-header strong {
  color: var(--lilac-text, #4b3fa0);
  font-size: 0.95rem;
}

.equipment-fields {
  display: grid;
  grid-template-columns: 2fr 1fr;
  gap: 1rem;
}

.equipment-section select {
  width: 100%;
  padding: 0.6rem 0.75rem;
  border: 1px solid var(--border, #e4defa);
  border-radius: 10px;
  background: #fcfbff;
  color: var(--text, #2d2a4a);
  font: inherit;
}

.equipment-section select:focus {
  outline: none;
  border-color: var(--primary, #6d5bd0);
  background: #ffffff;
  box-shadow: 0 0 0 3px var(--primary-tint, #ebe7ff);
}

.technical-label {
  margin-top: 0.8rem;
}

.text-button {
  border: none;
  background: transparent;
  color: var(--rose-text, #a12b47);
  font: inherit;
  font-size: 0.85rem;
  cursor: pointer;
}

.text-button:hover {
  text-decoration: underline;
}

.btn-add-equipment {
  margin-top: 1rem;
  padding: 0.55rem 1.1rem;
  border: none;
  border-radius: 999px;
  background: var(--lilac-bg, #e9e5fb);
  color: var(--lilac-text, #4b3fa0);
  font: inherit;
  font-weight: 500;
  cursor: pointer;
}

.btn-add-equipment:hover {
  background: #ddd6fb;
}

@media (max-width: 560px) {
  .equipment-fields {
    grid-template-columns: 1fr;
    gap: 0;
  }
}

</style>