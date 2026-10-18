<template>
  <section>
    <div class="head">
      <h2 class="page-title">Venue Catalogue</h2>
      <button v-if="canManage" type="button" class="btn-primary" @click="openCreate">
        Add venue
      </button>
    </div>

    <p v-if="notice" class="notice" role="status">{{ notice }}</p>
    <p v-if="pageError" class="field-error" role="alert">{{ pageError }}</p>

    <!-- Create / edit form (Venue Staff only) -->
    <form v-if="showForm" class="card form" novalidate @submit.prevent="save">
      <h3>{{ editingId ? "Edit venue" : "Add venue" }}</h3>

      <div class="fields">
        <label>
          Name
          <input v-model="form.name" type="text" :aria-invalid="!!errors.name" />
          <span v-if="errors.name" class="field-error">{{ errors.name }}</span>
        </label>
        <label>
          Capacity
          <input
            v-model="form.capacity"
            type="text"
            inputmode="numeric"
            :aria-invalid="!!errors.capacity"
          />
          <span v-if="errors.capacity" class="field-error">{{ errors.capacity }}</span>
        </label>
        <label>
          Location (optional)
          <input v-model="form.location" type="text" />
        </label>
        <label>
          Operating hours (optional)
          <input v-model="form.operatingHours" type="text" placeholder="e.g. 08:00-22:00" />
        </label>
        <label>
          Setup time (minutes)
          <input
            v-model="form.setupMinutes"
            type="text"
            inputmode="numeric"
            :aria-invalid="!!errors.setupMinutes"
          />
          <span v-if="errors.setupMinutes" class="field-error">{{ errors.setupMinutes }}</span>
        </label>
        <label>
          Turnaround time (minutes)
          <input
            v-model="form.turnaroundMinutes"
            type="text"
            inputmode="numeric"
            :aria-invalid="!!errors.turnaroundMinutes"
          />
          <span v-if="errors.turnaroundMinutes" class="field-error">
            {{ errors.turnaroundMinutes }}
          </span>
        </label>
        <label class="wide">
          Facilities (optional, separate with commas)
          <input v-model="form.facilities" type="text" placeholder="projector, wifi, stage" />
        </label>
        <fieldset class="wide layouts">
          <legend>Supported layouts (optional)</legend>
          <label v-for="l in STANDARD_LAYOUTS" :key="l" class="check">
            <input v-model="form.layouts" type="checkbox" :value="l" />
            {{ l }}
          </label>
          <label class="other">
            Other layouts (separate with commas)
            <input v-model="form.otherLayouts" type="text" placeholder="e.g. u-shape, cabaret" />
          </label>
        </fieldset>
        <label class="wide">
          Accessibility features (optional, separate with commas)
          <input
            v-model="form.accessibilityFeatures"
            type="text"
            placeholder="wheelchair ramp, hearing loop"
          />
        </label>
        <label class="wide">
          Description (optional)
          <textarea v-model="form.description" rows="2" />
        </label>
      </div>

      <p v-if="formError" class="field-error" role="alert">{{ formError }}</p>
      <div class="actions">
        <button type="submit" class="btn-primary" :disabled="saving">
          {{ saving ? "Saving..." : editingId ? "Save changes" : "Create venue" }}
        </button>
        <button type="button" class="btn-ghost" @click="closeForm">Cancel</button>
      </div>
    </form>

    <!-- Filters -->
    <div class="card filters">
      <label>
        Search by name or location
        <input v-model="filters.text" type="search" />
      </label>
      <label>
        Minimum capacity
        <input v-model="filters.minCapacity" type="text" inputmode="numeric" />
      </label>
    </div>

    <p v-if="loading" class="empty">Loading venues...</p>
    <p v-else-if="!venues.length" class="empty">
      No venues yet.<span v-if="canManage"> Use "Add venue" to create the first one.</span>
    </p>
    <p v-else-if="!filtered.length" class="empty">No venues match your filters.</p>

    <div v-else class="grid" aria-live="polite">
      <article v-for="v in filtered" :key="v.id" class="card venue">
        <header>
          <h3>{{ v.name }}</h3>
          <span class="badge cap">{{ v.capacity }} people</span>
        </header>

        <p class="meta">{{ v.location || "Location not specified" }}</p>
        <p class="meta">Hours: {{ v.operatingHours || "Not specified" }}</p>
        <p class="meta">
          Setup {{ v.setupMinutes ?? 0 }} min, turnaround {{ v.turnaroundMinutes ?? 0 }} min
        </p>
        <p v-if="v.description" class="desc">{{ v.description }}</p>

        <div v-if="v.facilities?.length" class="chips">
          <span class="label">Facilities</span>
          <span v-for="f in v.facilities" :key="f" class="badge sky">{{ f }}</span>
        </div>
        <div v-if="v.supportedLayouts?.length" class="chips">
          <span class="label">Layouts</span>
          <span v-for="l in v.supportedLayouts" :key="l" class="badge lilac">{{ l }}</span>
        </div>
        <div v-if="v.accessibilityFeatures?.length" class="chips">
          <span class="label">Accessibility</span>
          <span v-for="a in v.accessibilityFeatures" :key="a" class="badge mint">{{ a }}</span>
        </div>

        <div v-if="canManage" class="actions">
          <button type="button" class="btn-ghost" @click="openEdit(v)">Edit</button>
          <button type="button" class="btn-danger" @click="remove(v)">Deactivate</button>
        </div>
      </article>
    </div>
  </section>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from "vue";
import venuesApi from "../api/venues";
import { useAuthStore } from "../stores/auth";
import { useConfirm } from "../composables/useConfirm";

const auth = useAuthStore();
const { confirm } = useConfirm();
const canManage = computed(() => auth.hasRole("venue_staff"));

const venues = ref([]);
const loading = ref(false);
const saving = ref(false);
const pageError = ref("");
const formError = ref("");
const notice = ref("");

const STANDARD_LAYOUTS = ["classroom", "theatre", "boardroom", "banquet", "exhibition"];

const filters = reactive({ text: "", minCapacity: "" });
const filtered = computed(() => {
  const q = filters.text.trim().toLowerCase();
  const min = Number(filters.minCapacity) || 0;
  return venues.value.filter(
    (v) =>
      (!q || `${v.name} ${v.location || ""}`.toLowerCase().includes(q)) && v.capacity >= min
  );
});

// ---- form state ----
const showForm = ref(false);
const editingId = ref(null);
const errors = reactive({});
const blankForm = () => ({
  name: "",
  location: "",
  capacity: "",
  description: "",
  operatingHours: "",
  setupMinutes: "0",
  turnaroundMinutes: "0",
  facilities: "",
  layouts: [],
  otherLayouts: "",
  accessibilityFeatures: "",
});
const form = reactive(blankForm());

const toList = (text) => [
  ...new Set(
    String(text)
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean)
  ),
];

function openCreate() {
  Object.assign(form, blankForm());
  editingId.value = null;
  resetMessages();
  showForm.value = true;
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function openEdit(v) {
  const saved = (v.supportedLayouts || []).map((l) => String(l).trim().toLowerCase());
  Object.assign(form, {
    name: v.name,
    location: v.location || "",
    capacity: String(v.capacity),
    description: v.description || "",
    operatingHours: v.operatingHours || "",
    setupMinutes: String(v.setupMinutes ?? 0),
    turnaroundMinutes: String(v.turnaroundMinutes ?? 0),
    facilities: (v.facilities || []).join(", "),
    layouts: STANDARD_LAYOUTS.filter((l) => saved.includes(l)),
    otherLayouts: saved.filter((l) => !STANDARD_LAYOUTS.includes(l)).join(", "),
    accessibilityFeatures: (v.accessibilityFeatures || []).join(", "),
  });
  editingId.value = v.id;
  resetMessages();
  showForm.value = true;
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function closeForm() {
  showForm.value = false;
  editingId.value = null;
  formError.value = "";
  Object.keys(errors).forEach((k) => delete errors[k]);
}

function resetMessages() {
  notice.value = "";
  pageError.value = "";
  closeFormErrorsOnly();
}
function closeFormErrorsOnly() {
  formError.value = "";
  Object.keys(errors).forEach((k) => delete errors[k]);
}

// Mirrors the API rules so users get instant feedback; the server still validates.
function validate() {
  closeFormErrorsOnly();
  if (!form.name.trim()) errors.name = "Venue name is required.";
  const cap = String(form.capacity).trim();
  if (!/^\d+$/.test(cap) || Number(cap) < 1) {
    errors.capacity = "Enter a whole number greater than zero.";
  }
  for (const [key, label] of [
    ["setupMinutes", "Setup time"],
    ["turnaroundMinutes", "Turnaround time"],
  ]) {
    const value = String(form[key]).trim();
    if (value !== "" && !/^\d+$/.test(value)) {
      errors[key] = `${label} must be a whole number of minutes, 0 or more.`;
    }
  }
  return Object.keys(errors).length === 0;
}

function buildPayload() {
  return {
    name: form.name.trim(),
    location: form.location.trim() || null,
    capacity: Number(form.capacity),
    description: form.description.trim() || null,
    operatingHours: form.operatingHours.trim() || null,
    setupMinutes: Number(String(form.setupMinutes).trim() || 0),
    turnaroundMinutes: Number(String(form.turnaroundMinutes).trim() || 0),
    facilities: toList(form.facilities),
    supportedLayouts: [
      ...new Set([...form.layouts, ...toList(form.otherLayouts).map((l) => l.toLowerCase())]),
    ],
    accessibilityFeatures: toList(form.accessibilityFeatures),
  };
}

async function load() {
  loading.value = true;
  try {
    const { data } = await venuesApi.listVenues();
    venues.value = data;
  } catch (error) {
    pageError.value = error.response?.data?.error || "Could not load venues.";
  } finally {
    loading.value = false;
  }
}

async function save() {
  notice.value = "";
  if (!validate()) return;
  saving.value = true;
  try {
    if (editingId.value) {
      const { data } = await venuesApi.update(editingId.value, buildPayload());
      const affected = data.flagsRaised?.length || 0;
      notice.value = affected
        ? `Venue updated. ${affected} booked event(s) are affected and their coordinators need to review them.`
        : "Venue updated.";
    } else {
      await venuesApi.create(buildPayload());
      notice.value = "Venue created.";
    }
    closeForm();
    await load();
  } catch (error) {
    formError.value = error.response?.data?.error || "Could not save the venue.";
  } finally {
    saving.value = false;
  }
}

async function remove(v) {
  const ok = await confirm(`Deactivate "${v.name}"? It will no longer appear in the catalogue.`);
  if (!ok) return;
  notice.value = "";
  pageError.value = "";
  try {
    await venuesApi.deactivate(v.id);
    notice.value = "Venue deactivated.";
    await load();
  } catch (error) {
    pageError.value = error.response?.data?.error || "Could not deactivate the venue.";
  }
}

onMounted(load);
</script>

<style scoped>
.head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: 1rem;
}
.page-title { margin: 0; font-size: 1.5rem; font-weight: 600; color: var(--text); }

.card {
  padding: 1.25rem 1.5rem;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 14px;
  box-shadow: 0 4px 16px rgba(109, 91, 208, 0.08);
}
.form, .filters { margin-bottom: 1rem; }
.form h3 { margin: 0 0 0.75rem; }

.fields {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 1rem;
  margin-bottom: 1rem;
}
.filters {
  display: grid;
  grid-template-columns: 2fr 1fr;
  gap: 1rem;
}
.wide { grid-column: 1 / -1; }

label {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  font-weight: 600;
}
fieldset.layouts {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem 1.25rem;
  margin: 0;
  padding: 0.6rem 0.8rem;
  border: 1px solid var(--border);
  border-radius: 0.35rem;
}
fieldset.layouts legend { padding: 0 0.3rem; font-weight: 600; }
.check { flex-direction: row; align-items: center; gap: 0.4rem; font-weight: 400; text-transform: capitalize; }
.check input { width: auto; min-height: auto; }
.other { flex: 1 1 100%; }

input, textarea {
  box-sizing: border-box;
  width: 100%;
  min-height: 2.4rem;
  padding: 0.4rem;
  border: 1px solid var(--border);
  border-radius: 0.35rem;
  color: var(--text);
  background: var(--surface);
  font: inherit;
  font-weight: 400;
}
input:focus-visible, textarea:focus-visible, button:focus-visible {
  outline: 2px solid var(--primary);
  outline-offset: 2px;
}
input[aria-invalid="true"] { border-color: #a12b47; }
.field-error { color: #a12b47; font-size: 0.875rem; font-weight: 400; }
.notice {
  margin: 0 0 1rem;
  padding: 0.6rem 0.9rem;
  border-radius: 10px;
  background: var(--mint-bg);
  color: var(--mint-text);
}
.empty { padding: 1rem; color: var(--text-muted); }

.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(290px, 1fr));
  gap: 1rem;
}
.venue header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 0.5rem;
}
.venue h3 { margin: 0 0 0.4rem; font-size: 1.1rem; }
.meta { margin: 0.2rem 0; color: var(--text-muted); font-size: 0.92rem; }
.desc { margin: 0.5rem 0; }

.chips { display: flex; flex-wrap: wrap; align-items: center; gap: 0.35rem; margin-top: 0.6rem; }
.label { font-size: 0.85rem; color: var(--text-muted); margin-right: 0.2rem; }
.badge {
  padding: 0.15rem 0.6rem;
  border-radius: 999px;
  font-size: 0.82rem;
  font-weight: 500;
  white-space: nowrap;
}
.cap { background: var(--butter-bg); color: var(--butter-text); }
.sky { background: var(--sky-bg); color: var(--sky-text); }
.lilac { background: var(--lilac-bg); color: var(--lilac-text); }
.mint { background: var(--mint-bg); color: var(--mint-text); }

.actions { display: flex; gap: 0.5rem; margin-top: 1rem; }
.btn-primary, .btn-ghost, .btn-danger {
  padding: 0.5rem 1.2rem;
  border: none;
  border-radius: 999px;
  font: inherit;
  font-weight: 500;
}
.btn-primary { background: var(--primary); color: #fff; }
.btn-primary:hover { background: var(--primary-hover); }
.btn-primary:disabled { opacity: 0.6; cursor: not-allowed; }
.btn-ghost { background: var(--lilac-bg); color: var(--lilac-text); }
.btn-danger { background: var(--rose-bg); color: var(--rose-text); }

@media (max-width: 560px) {
  .filters { grid-template-columns: 1fr; }
  .head { flex-wrap: wrap; }
}
</style>
