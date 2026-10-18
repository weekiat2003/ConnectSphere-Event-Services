<template>
  <section>
    <h2 class="page-title">Venue Search</h2>

    <!-- Step 1: the event details the search is based on -->
    <form class="card panel" @submit.prevent="search">
      <div class="panel-head">
        <h3>Event details</h3>
        <p class="hint">Enter when the event takes place and how many people are coming.</p>
      </div>
      <div class="fields">
        <label>
          Date
          <input v-model="criteria.date" type="date" :aria-invalid="!!errors.date" />
          <span v-if="errors.date" class="field-error">{{ errors.date }}</span>
        </label>
        <label>
          Start time
          <input v-model="criteria.start_time" type="time" :aria-invalid="!!errors.start_time" />
          <span v-if="errors.start_time" class="field-error">{{ errors.start_time }}</span>
        </label>
        <label>
          End time
          <input v-model="criteria.end_time" type="time" :aria-invalid="!!errors.end_time" />
          <span v-if="errors.end_time" class="field-error">{{ errors.end_time }}</span>
        </label>
        <label>
          Expected attendance
          <input
            v-model="criteria.attendance"
            type="text"
            inputmode="numeric"
            placeholder="e.g. 80"
            :aria-invalid="!!errors.attendance"
          />
          <span v-if="errors.attendance" class="field-error">{{ errors.attendance }}</span>
        </label>
      </div>

      <p v-if="pageError" class="error-banner" role="alert">{{ pageError }}</p>
      <div class="form-actions">
        <button type="submit" class="btn-primary" :disabled="loading">
          {{ loading ? "Searching..." : "Search venues" }}
        </button>
      </div>
    </form>

    <!-- Step 2: filters. They apply automatically, so there is no Apply button. -->
    <div class="card panel">
      <div class="panel-head filter-head">
        <div>
          <h3>
            Filters
            <span v-if="activeFilterCount" class="badge lilac">{{ activeFilterCount }} active</span>
          </h3>
          <p class="hint">
            {{
              hasSearched
                ? "Results update as soon as you change a filter."
                : "Run a search first, then narrow the results with these filters."
            }}
          </p>
        </div>
        <button
          v-if="activeFilterCount"
          type="button"
          class="btn-ghost"
          :disabled="loading"
          @click="clearFilters"
        >
          Clear filters
        </button>
      </div>

      <p v-if="filterOptionsError" class="error-banner" role="alert">{{ filterOptionsError }}</p>

      <div class="fields">
        <label>
          Location
          <select v-model="filters.location" @change="applyFilters">
            <option value="">All locations</option>
            <option v-for="location in filterOptions.locations" :key="location" :value="location">
              {{ location }}
            </option>
          </select>
        </label>
        <label>
          Room layout
          <select v-model="filters.layout" @change="applyFilters">
            <option value="">All layouts</option>
            <option v-for="layout in filterOptions.layouts" :key="layout" :value="layout" class="cap-text">
              {{ layout }}
            </option>
          </select>
        </label>
        <label>
          Maximum capacity
          <input
            v-model="filters.max_capacity"
            type="number"
            min="1"
            step="1"
            placeholder="No limit"
            :aria-invalid="!!errors.max_capacity"
            @input="onCapacityInput"
          />
          <span v-if="errors.max_capacity" class="field-error">{{ errors.max_capacity }}</span>
        </label>
      </div>

      <div class="option-groups">
        <fieldset class="option-group">
          <legend>
            Accessibility features
            <span v-if="filters.accessibility.length" class="count-pill">{{ filters.accessibility.length }}</span>
          </legend>
          <p v-if="!filterOptions.accessibilityFeatures.length" class="hint">
            No accessibility features are listed in the venue catalogue.
          </p>
          <div v-else class="option-list">
            <label
              v-for="feature in filterOptions.accessibilityFeatures"
              :key="feature"
              class="option-label"
            >
              <input
                v-model="filters.accessibility"
                type="checkbox"
                :value="feature"
                @change="applyFilters"
              />
              {{ feature }}
            </label>
          </div>
        </fieldset>

        <fieldset class="option-group">
          <legend>
            Facilities
            <span v-if="filters.facilities.length" class="count-pill">{{ filters.facilities.length }}</span>
          </legend>
          <p v-if="!filterOptions.facilities.length" class="hint">
            No facilities are listed in the venue catalogue.
          </p>
          <div v-else class="option-list">
            <label
              v-for="facility in filterOptions.facilities"
              :key="facility"
              class="option-label"
            >
              <input
                v-model="filters.facilities"
                type="checkbox"
                :value="facility"
                @change="applyFilters"
              />
              {{ facility }}
            </label>
          </div>
        </fieldset>
      </div>
      <p class="hint all-hint">A venue must offer every accessibility feature and facility you tick.</p>
    </div>

    <!-- Results -->
    <section v-if="results !== null" class="results" :class="{ busy: loading }" aria-live="polite">
      <h3 class="results-title">
        Results <span class="badge cap">{{ results.length }}</span>
      </h3>
      <p v-if="!results.length" class="card empty">No venues match your filters.</p>
      <div v-else class="grid">
        <article v-for="venue in results" :key="venue.id" class="card venue-card">
          <header>
            <h4>{{ venue.name }}</h4>
            <span class="badge cap">Capacity {{ venue.capacity }}</span>
          </header>
          <p class="meta">{{ venue.location || "Location not specified" }}</p>

          <div v-if="venue.supportedLayouts?.length" class="chips">
            <span class="label">Layouts</span>
            <span v-for="item in venue.supportedLayouts" :key="item" class="badge sky cap-text">{{ item }}</span>
          </div>
          <div v-if="venue.accessibilityFeatures?.length" class="chips">
            <span class="label">Accessibility</span>
            <span v-for="item in venue.accessibilityFeatures" :key="item" class="badge mint">{{ item }}</span>
          </div>
          <div v-if="venue.facilities?.length" class="chips">
            <span class="label">Facilities</span>
            <span v-for="item in venue.facilities" :key="item" class="badge lilac">{{ item }}</span>
          </div>
        </article>
      </div>
    </section>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from "vue";
import venuesApi from "../api/venues";

const criteria = reactive({
  date: "",
  start_time: "",
  end_time: "",
  attendance: "",
});
const filters = reactive({
  location: "",
  layout: "",
  max_capacity: "",
  accessibility: [],
  facilities: [],
});
const filterOptions = reactive({
  locations: [],
  layouts: [],
  accessibilityFeatures: [],
  facilities: [],
});
const filterOptionsError = ref("");
const errors = reactive({});
const results = ref(null);
const loading = ref(false);
const pageError = ref("");
const hasSearched = ref(false);
let searchSequence = 0;
let capacityTimer = null;

const activeFilterCount = computed(
  () =>
    (filters.location ? 1 : 0) +
    (filters.layout ? 1 : 0) +
    (String(filters.max_capacity).trim() !== "" ? 1 : 0) +
    filters.accessibility.length +
    filters.facilities.length,
);

function validate() {
  Object.keys(errors).forEach((key) => delete errors[key]);
  if (!criteria.date) errors.date = "Date is required.";
  if (!criteria.start_time) errors.start_time = "Start time is required.";
  if (!criteria.end_time) errors.end_time = "End time is required.";
  if (criteria.start_time && criteria.end_time && criteria.end_time <= criteria.start_time) {
    errors.end_time = "End time must be after start time.";
  }
  if (criteria.attendance === "" || criteria.attendance === null) {
    errors.attendance = "Expected attendance is required.";
  } else if (
    !/^[0-9]+$/.test(String(criteria.attendance)) ||
    Number(criteria.attendance) < 1
  ) {
    errors.attendance = "Enter a positive whole number.";
  }
  return Object.keys(errors).length === 0;
}

async function runSearch() {
  const sequence = ++searchSequence;
  pageError.value = "";
  if (!validate()) {
    results.value = null;
    loading.value = false;
    return;
  }

  hasSearched.value = true;
  loading.value = true;
  try {
    if (
      filters.max_capacity !== "" &&
      Number(filters.max_capacity) < Number(criteria.attendance)
    ) {
      errors.max_capacity = "Maximum capacity cannot be lower than expected attendance.";
      results.value = null;
      return;
    }
    delete errors.max_capacity;
    const { data } = await venuesApi.search({
      ...criteria,
      ...filters,
    });
    if (sequence === searchSequence) results.value = data;
  } catch (error) {
    if (sequence === searchSequence) {
      if (error.response?.data?.errors) {
        Object.assign(errors, error.response.data.errors);
        results.value = null;
      } else {
        results.value = null;
        pageError.value = error.response?.data?.error || "Could not search venues.";
      }
    }
  } finally {
    if (sequence === searchSequence) loading.value = false;
  }
}

function search() {
  loadFilterOptions(); // refresh the catalogue-backed options on every new search
  return runSearch();
}

function applyFilters() {
  if (hasSearched.value) return runSearch();
}

// Typing a maximum capacity re-filters shortly after the user stops typing.
function onCapacityInput() {
  clearTimeout(capacityTimer);
  capacityTimer = setTimeout(applyFilters, 400);
}

function clearFilters() {
  clearTimeout(capacityTimer);
  filters.location = "";
  filters.layout = "";
  filters.max_capacity = "";
  filters.accessibility = [];
  filters.facilities = [];
  if (hasSearched.value) runSearch();
}

async function loadFilterOptions() {
  try {
    const { data } = await venuesApi.searchOptions();
    Object.assign(filterOptions, data);
    filterOptionsError.value = "";
  } catch (error) {
    filterOptionsError.value =
      error.response?.data?.error || "Could not load venue filter options.";
  }
}

onMounted(loadFilterOptions);
onBeforeUnmount(() => clearTimeout(capacityTimer));
</script>

<style scoped>
.page-title { margin: 0 0 1rem; font-size: 1.5rem; font-weight: 600; color: var(--text); }

.card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 14px;
  box-shadow: 0 4px 16px rgba(109, 91, 208, 0.08);
}
.panel { padding: 1.25rem 1.5rem; margin-bottom: 1rem; }
.panel-head h3 { margin: 0 0 0.2rem; font-size: 1.1rem; font-weight: 600; color: var(--text); }
.panel-head { margin-bottom: 1rem; }
.filter-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 1rem; }
.hint { margin: 0; color: var(--text-muted); font-size: 0.85rem; font-weight: 400; }
.all-hint { margin-top: 0.75rem; }

.fields {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
  gap: 1rem;
}

label {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  color: var(--text);
  font-size: 0.875rem;
  font-weight: 600;
}
input, select {
  box-sizing: border-box;
  width: 100%;
  min-height: 2.4rem;
  padding: 0.4rem 0.6rem;
  border: 1px solid var(--border);
  border-radius: 8px;
  color: var(--text);
  background: var(--surface);
  font: inherit;
  font-weight: 400;
}
input:focus-visible, select:focus-visible, button:focus-visible {
  outline: 2px solid var(--primary);
  outline-offset: 2px;
}
input[aria-invalid="true"] { border-color: #a12b47; }
.field-error { color: #a12b47; font-size: 0.85rem; font-weight: 400; }
.error-banner {
  margin: 0 0 1rem;
  padding: 0.6rem 0.9rem;
  border-radius: 10px;
  background: var(--rose-bg);
  color: var(--rose-text);
  font-size: 0.9rem;
}

/* Accessibility / facilities: a bounded, scrollable list so a long catalogue
   never pushes the results off the screen. */
.option-groups {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 1rem;
  margin-top: 1rem;
}
.option-group {
  min-width: 0;
  margin: 0;
  padding: 0.6rem 0.8rem 0.8rem;
  border: 1px solid var(--border);
  border-radius: 10px;
}
.option-group legend {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0 0.3rem;
  color: var(--text);
  font-size: 0.875rem;
  font-weight: 600;
}
.option-list {
  max-height: 9.5rem;
  overflow-y: auto;
  padding-right: 0.25rem;
  scrollbar-width: thin;
  scrollbar-color: var(--border) transparent;
}
.option-label {
  display: flex;
  flex-direction: row;
  align-items: center;
  gap: 0.5rem;
  padding: 0.3rem 0.25rem;
  border-radius: 6px;
  font-weight: 400;
  cursor: pointer;
}
.option-label:hover { background: var(--primary-tint); }
.option-label input { width: auto; min-height: auto; margin: 0; accent-color: var(--primary); }
.count-pill {
  min-width: 1.2rem;
  padding: 0 0.4rem;
  border-radius: 999px;
  background: var(--primary);
  color: #fff;
  font-size: 0.75rem;
  font-weight: 600;
  text-align: center;
}

.form-actions { display: flex; justify-content: flex-end; margin-top: 1rem; }
.btn-primary, .btn-ghost {
  padding: 0.5rem 1.2rem;
  border: none;
  border-radius: 999px;
  font: inherit;
  font-weight: 500;
  cursor: pointer;
}
.btn-primary { background: var(--primary); color: #fff; }
.btn-primary:hover:not(:disabled) { background: var(--primary-hover); }
.btn-ghost { background: var(--lilac-bg); color: var(--lilac-text); white-space: nowrap; }
.btn-ghost:hover:not(:disabled) { background: #ddd6fb; }
.btn-primary:disabled, .btn-ghost:disabled { opacity: 0.6; cursor: not-allowed; }

.badge {
  display: inline-block;
  padding: 0.15rem 0.6rem;
  border-radius: 999px;
  font-size: 0.8rem;
  font-weight: 500;
  white-space: nowrap;
}
.cap { background: var(--butter-bg); color: var(--butter-text); }
.sky { background: var(--sky-bg); color: var(--sky-text); }
.lilac { background: var(--lilac-bg); color: var(--lilac-text); }
.mint { background: var(--mint-bg); color: var(--mint-text); }
.cap-text { text-transform: capitalize; }

.results { transition: opacity 0.15s; }
.results.busy { opacity: 0.55; }
.results-title { display: flex; align-items: center; gap: 0.5rem; margin: 0 0 0.75rem; font-size: 1.1rem; font-weight: 600; color: var(--text); }
.empty { padding: 1.25rem 1.5rem; color: var(--text-muted); }
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(290px, 1fr));
  gap: 1rem;
}
.venue-card { padding: 1.25rem 1.5rem; }
.venue-card header { display: flex; align-items: flex-start; justify-content: space-between; gap: 0.5rem; }
.venue-card h4 { margin: 0 0 0.3rem; font-size: 1.05rem; color: var(--text); }
.meta { margin: 0.1rem 0 0.4rem; color: var(--text-muted); font-size: 0.92rem; }
.chips { display: flex; flex-wrap: wrap; align-items: center; gap: 0.35rem; margin-top: 0.55rem; }
.label { margin-right: 0.2rem; color: var(--text-muted); font-size: 0.85rem; }

@media (max-width: 560px) {
  .panel { padding: 1rem; }
  .filter-head { flex-direction: column; }
  .fields { grid-template-columns: 1fr; }
}
</style>