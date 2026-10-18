<template>
  <div class="assessment">
    <router-link class="back" to="/safety-reviews">← Safety Reviews</router-link>

    <p v-if="loading" class="hint">Loading…</p>
    <p v-else-if="loadError" class="notice error">{{ loadError }}</p>

    <template v-else-if="review">
      <!-- Header -->
      <div class="header">
        <h2 class="page-title">{{ orNotSpecified(review.event.name) }}</h2>
        <span class="badge" :class="review.event.status">{{ review.event.statusLabel }}</span>
      </div>
      <p class="hint">
        {{ formatEventDate(review.event.proposedDate, review.event.proposedTime) }}
        <template v-if="review.event.coordinatorName"> · Coordinator: {{ review.event.coordinatorName }}</template>
      </p>

      <!-- Latest decision -->
      <div
        v-if="latestDecision"
        class="notice"
        :class="latestDecision.decision === 'approved' ? 'approved' : 'rejected'"
      >
        <strong>{{ decisionHeading(latestDecision.decision) }}</strong>
        <p class="meta">
          By {{ latestDecision.safetyOfficerName || `Safety Officer #${latestDecision.safetyOfficerId}` }}
          on {{ formatTimestamp(latestDecision.createdAt) }}
        </p>
        <p v-if="latestDecision.comments"><strong>Reason:</strong> {{ latestDecision.comments }}</p>
        <p v-if="latestDecision.affectedArrangements?.length">
          <strong>Affected arrangements:</strong> {{ formatArrangements(latestDecision.affectedArrangements) }}
        </p>
        <ul class="decision-factors">
          <li v-for="f in review.factors" :key="f.key">
            <span class="outcome-pill" :class="decisionOutcome(latestDecision, f.key)">
              {{ outcomeLabel(decisionOutcome(latestDecision, f.key)) }}
            </span>
            {{ f.label }}<template v-if="latestDecision.factorNotes?.[f.key]">: {{ latestDecision.factorNotes[f.key] }}</template>
          </li>
        </ul>
      </div>

      <!-- AC2: facts under review -->
      <section class="card">
        <h3 class="section-title">Event requirements</h3>
        <dl class="facts">
          <div>
            <dt>Expected attendance</dt>
            <dd :class="{ missing: isMissing(review.expectedAttendance) }">{{ orNotSpecified(review.expectedAttendance) }}</dd>
          </div>
          <div>
            <dt>Required layout</dt>
            <dd :class="{ missing: isMissing(review.requiredLayout) }">{{ orNotSpecified(review.requiredLayout) }}</dd>
          </div>
          <div class="wide">
            <dt>Accessibility requirements</dt>
            <dd :class="{ missing: isMissing(review.accessibilityRequirements) }">
              {{ orNotSpecified(review.accessibilityRequirements) }}
            </dd>
          </div>
        </dl>
      </section>

      <section class="card">
        <h3 class="section-title">Booked venues</h3>
        <p v-if="!review.venues.length" class="missing">Not specified</p>
        <div v-for="venue in review.venues" :key="venue.bookingId" class="venue">
          <div class="venue-head">
            <strong>{{ orNotSpecified(venue.name) }}</strong>
            <span v-if="venue.location" class="hint">{{ venue.location }}</span>
            <span v-if="venue.startDatetime" class="hint">· {{ bookingWindow(venue) }}</span>
          </div>
          <dl class="facts">
            <div>
              <dt>Capacity</dt>
              <dd :class="{ missing: isMissing(venue.capacity) }">
                {{ orNotSpecified(venue.capacity) }}
                <span
                  v-if="venue.capacity != null && review.expectedAttendance != null && review.expectedAttendance > venue.capacity"
                  class="warn"
                >Below expected attendance ({{ review.expectedAttendance }})</span>
              </dd>
            </div>
            <div>
              <dt>Supported layouts</dt>
              <dd :class="{ missing: !venue.supportedLayouts.length }">
                <template v-if="venue.supportedLayouts.length">
                  <span v-for="layout in venue.supportedLayouts" :key="layout.name" class="chip">
                    {{ layout.name }}<template v-if="layout.maxCapacity"> (max {{ layout.maxCapacity }})</template>
                  </span>
                </template>
                <template v-else>Not specified</template>
              </dd>
            </div>
            <div class="wide">
              <dt>Known restrictions</dt>
              <dd :class="{ missing: isMissing(venue.knownRestrictions) }" class="pre">
                {{ orNotSpecified(venue.knownRestrictions) }}
              </dd>
            </div>
            <div>
              <dt>Operating hours</dt>
              <dd :class="{ missing: isMissing(venue.operatingHours) }">{{ orNotSpecified(venue.operatingHours) }}</dd>
            </div>
            <div>
              <dt>Accessibility features</dt>
              <dd :class="{ missing: !venue.accessibilityFeatures.length }">
                {{ venue.accessibilityFeatures.length ? venue.accessibilityFeatures.join(", ") : "Not specified" }}
              </dd>
            </div>
          </dl>
        </div>
      </section>

      <section class="card">
        <h3 class="section-title">Equipment requirements</h3>
        <p v-if="!review.equipmentRequirements.length" class="missing">Not specified</p>
        <table v-else>
          <thead>
            <tr><th>Equipment</th><th class="num">Quantity</th><th>Technical notes</th></tr>
          </thead>
          <tbody>
            <tr v-for="item in review.equipmentRequirements" :key="item.id">
              <td>{{ orNotSpecified(item.type) }}</td>
              <td class="num">{{ orNotSpecified(item.quantity) }}</td>
              <td :class="{ missing: isMissing(item.technicalNotes) }">{{ orNotSpecified(item.technicalNotes) }}</td>
            </tr>
          </tbody>
        </table>
      </section>

      <!-- AC3: per-factor assessment -->
      <section v-if="review.canAssess" class="card">
        <div class="section-head">
          <h3 class="section-title">Safety assessment</h3>
          <span class="hint">{{ assessedCount }} of {{ review.factors.length }} factors assessed</span>
        </div>

        <fieldset v-for="f in review.factors" :key="f.key" class="factor" :class="form[f.key].outcome">
          <legend class="sr-only">{{ f.label }}</legend>
          <div class="factor-top">
            <div>
              <div class="factor-label">{{ f.label }}</div>
              <div v-if="factorHint(f.key)" class="factor-hint">{{ factorHint(f.key) }}</div>
            </div>
            <div class="segmented" role="radiogroup" :aria-label="`${f.label} outcome`">
              <label :class="{ on: form[f.key].outcome === 'satisfactory' }">
                <input v-model="form[f.key].outcome" type="radio" :name="`outcome-${f.key}`" value="satisfactory">
                Satisfactory
              </label>
              <label :class="{ on: form[f.key].outcome === 'concern', concern: true }">
                <input v-model="form[f.key].outcome" type="radio" :name="`outcome-${f.key}`" value="concern">
                Concern
              </label>
            </div>
          </div>
          <textarea
            v-model="form[f.key].notes"
            rows="2"
            :aria-label="`${f.label} notes`"
            :placeholder="form[f.key].outcome === 'concern' ? 'Describe the concern' : 'Notes (optional)'"
          ></textarea>
        </fieldset>

        <div class="save-row">
          <button class="btn btn-primary" :disabled="saving || !dirty" @click="saveAssessment">
            {{ saving ? "Saving…" : "Save assessment" }}
          </button>
          <span v-if="saveError" class="field-error">{{ saveError }}</span>
          <span v-else-if="dirty" class="hint">Unsaved changes</span>
          <span v-else-if="review.assessment" class="hint">
            Saved by {{ review.assessment.safetyOfficerName }} on {{ formatTimestamp(review.assessment.updatedAt) }}
          </span>
        </div>
      </section>

      <!-- Decision (previous story), using the assessment above -->
      <section v-if="review.canAssess" class="card">
        <h3 class="section-title">Decision</h3>
        <fieldset class="arrangements">
          <legend>Affected arrangements (required to reject or request changes)</legend>
          <label><input v-model="affectedArrangements" type="checkbox" value="venue"> Venue</label>
          <label><input v-model="affectedArrangements" type="checkbox" value="equipment"> Equipment</label>
        </fieldset>
        <textarea
          v-model="reason"
          rows="3"
          aria-label="Reason"
          placeholder="Reason (required to reject or request changes)"
        ></textarea>
        <ul v-if="decisionErrors.length" class="field-error errors">
          <li v-for="message in decisionErrors" :key="message">{{ message }}</li>
        </ul>
        <p v-if="approveBlockedReason" class="hint">{{ approveBlockedReason }}</p>
        <div class="actions">
          <button class="btn btn-mint" :disabled="!!approveBlockedReason || deciding" @click="decide('approved')">
            Approve safety
          </button>
          <button class="btn btn-rose" :disabled="deciding" @click="decide('rejected')">Reject arrangement</button>
          <button class="btn btn-butter" :disabled="deciding" @click="decide('changes_requested')">Request changes</button>
        </div>
      </section>

      <p v-else-if="!latestDecision" class="notice">
        This event is not awaiting a safety check, so it cannot be assessed right now.
      </p>
    </template>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from "vue";
import { onBeforeRouteLeave, useRoute, useRouter } from "vue-router";
import eventsApi from "../api/events";
import {
  formatEventDate,
  formatTimestamp,
  isMissing,
  orNotSpecified,
} from "../utils/display";

const route = useRoute();
const router = useRouter();

const review = ref(null);
const loading = ref(true);
const loadError = ref("");

const form = reactive({});
const savedSnapshot = ref("");
const saving = ref(false);
const saveError = ref("");

const affectedArrangements = ref([]);
const reason = ref("");
const decisionErrors = ref([]);
const deciding = ref(false);

function resetForm(data) {
  const saved = data.assessment?.factors || {};
  for (const key of Object.keys(form)) delete form[key];
  for (const f of data.factors) {
    form[f.key] = {
      outcome: saved[f.key]?.outcome ?? null,
      notes: saved[f.key]?.notes ?? "",
    };
  }
  savedSnapshot.value = JSON.stringify(payload());
}

function payload() {
  const result = {};
  for (const [key, value] of Object.entries(form)) {
    result[key] = { outcome: value.outcome, notes: value.notes?.trim() || null };
  }
  return result;
}

async function load() {
  loading.value = true;
  loadError.value = "";
  try {
    const { data } = await eventsApi.getSafetyAssessment(route.params.id);
    review.value = data;
    resetForm(data);
  } catch (e) {
    if (e.response?.status === 403) {
      router.replace({ name: "access-denied", query: { roles: "safety_officer" } });
      return;
    }
    loadError.value = e.response?.status === 404
      ? "Event not found."
      : e.response?.data?.error || "Could not load this safety assessment.";
  } finally {
    loading.value = false;
  }
}

onMounted(load);

const dirty = computed(() => review.value?.canAssess && JSON.stringify(payload()) !== savedSnapshot.value);

onBeforeRouteLeave(() => {
  if (dirty.value && !window.confirm("You have unsaved assessment changes. Leave without saving?")) {
    return false;
  }
  return true;
});

const assessedCount = computed(() => Object.values(form).filter((f) => f.outcome).length);
const concernCount = computed(() => Object.values(form).filter((f) => f.outcome === "concern").length);
const latestDecision = computed(() => review.value?.safetyReviews?.at(-1) || null);

const approveBlockedReason = computed(() => {
  if (!review.value) return "";
  const remaining = review.value.factors.length - assessedCount.value;
  if (remaining > 0) return `Assess every factor to approve (${remaining} remaining).`;
  if (concernCount.value) {
    return "An event with safety concerns cannot be approved. Reject or request changes instead.";
  }
  return "";
});

async function saveAssessment() {
  saving.value = true;
  saveError.value = "";
  try {
    const { data } = await eventsApi.saveSafetyAssessment(route.params.id, payload());
    review.value = data;
    resetForm(data);
  } catch (e) {
    saveError.value = e.response?.data?.error || "Could not save the assessment.";
  } finally {
    saving.value = false;
  }
}

async function decide(decision) {
  decisionErrors.value = [];
  if (decision !== "approved") {
    if (!reason.value.trim()) decisionErrors.value.push("Give a reason for this decision.");
    if (!concernCount.value) decisionErrors.value.push("Mark at least one safety factor as a concern.");
    if (!affectedArrangements.value.length) {
      decisionErrors.value.push("Specify affected arrangements: venue, equipment, or both.");
    }
    if (decisionErrors.value.length) return;
  }

  deciding.value = true;
  try {
    await eventsApi.reviewSafety(route.params.id, {
      decision,
      comments: reason.value.trim() || null,
      affectedArrangements: affectedArrangements.value,
      factorAssessments: payload(),
    });
    reason.value = "";
    affectedArrangements.value = [];
    await load();
  } catch (e) {
    const data = e.response?.data;
    decisionErrors.value = data?.errors?.length
      ? data.errors
      : [data?.error || "Could not submit the safety decision."];
  } finally {
    deciding.value = false;
  }
}

// What the officer should look at for each factor, drawn from the facts above.
function factorHint(key) {
  const r = review.value;
  const attendance = r.expectedAttendance ?? "Not specified";
  const venues = r.venues;
  switch (key) {
    case "expected_attendance":
      return `Expected attendance: ${attendance}`;
    case "venue_capacity":
      return venues.length
        ? `Expected ${attendance} · Capacity: ${venues.map((v) => `${v.name} ${v.capacity ?? "not specified"}`).join(", ")}`
        : "No booked venue";
    case "venue_layout": {
      const supported = [...new Set(venues.flatMap((v) => v.supportedLayouts.map((l) => l.name)))];
      return `Required: ${r.requiredLayout || "Not specified"} · Supported: ${supported.join(", ") || "Not specified"}`;
    }
    case "accessibility":
      return `Required: ${r.accessibilityRequirements || "Not specified"}`;
    case "equipment_placement":
      return r.equipmentRequirements.length
        ? r.equipmentRequirements.map((e) => `${e.quantity} × ${e.type}`).join(", ")
        : "No equipment requirements";
    case "venue_restrictions": {
      const listed = venues.filter((v) => v.knownRestrictions);
      return listed.length ? listed.map((v) => `${v.name}: ${v.knownRestrictions}`).join(" | ") : "None recorded";
    }
    default:
      return "";
  }
}

function decisionOutcome(decision, key) {
  if (decision.concernFactors?.includes(key)) return "concern";
  if (decision.assessedFactors?.includes(key)) return "satisfactory";
  return "unassessed";
}

function outcomeLabel(outcome) {
  return { concern: "Concern", satisfactory: "Satisfactory", unassessed: "Not assessed" }[outcome];
}

function decisionHeading(decision) {
  if (decision === "approved") return "Safety approved: cleared for preparation";
  if (decision === "rejected") return "Safety arrangement rejected: returned to planning";
  return "Safety changes requested: returned to planning";
}

function formatArrangements(keys) {
  return keys.map((k) => k.charAt(0).toUpperCase() + k.slice(1)).join(" and ");
}

// Booking times are the venue's local wall-clock times, so show them as stored.
function bookingWindow(venue) {
  const start = venue.startDatetime?.slice(11, 16);
  const end = venue.endDatetime?.slice(11, 16);
  return start && end ? `${start}–${end}` : "";
}
</script>

<style scoped>
.back {
  display: inline-block;
  margin-bottom: 0.75rem;
  color: var(--primary, #6d5bd0);
  text-decoration: none;
  font-size: 0.9rem;
}
.header {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  flex-wrap: wrap;
}
.page-title {
  margin: 0;
  font-size: 1.5rem;
  font-weight: 600;
}
.hint {
  color: var(--text-muted, #6b6890);
  font-size: 0.9rem;
}
.card {
  margin-top: 1rem;
  padding: 1.25rem 1.5rem;
  background: var(--surface, #ffffff);
  border: 1px solid var(--border, #e4defa);
  border-radius: 14px;
  box-shadow: 0 4px 16px rgba(109, 91, 208, 0.08);
}
.section-title {
  margin: 0 0 0.75rem;
  font-size: 1.1rem;
  font-weight: 600;
}
.section-head {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 1rem;
  flex-wrap: wrap;
}
.facts {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 0.75rem 1.25rem;
  margin: 0;
}
.facts .wide {
  grid-column: 1 / -1;
}
dt {
  font-size: 0.75rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.03em;
  color: var(--text-muted, #6b6890);
}
dd {
  margin: 0.15rem 0 0;
}
.pre {
  white-space: pre-line;
}
.missing {
  color: var(--text-muted, #6b6890);
  font-style: italic;
}
.warn {
  display: inline-block;
  margin-left: 0.4rem;
  padding: 0.05rem 0.5rem;
  border-radius: 999px;
  background: var(--rose-bg, #ffdce3);
  color: var(--rose-text, #a12b47);
  font-size: 0.75rem;
  font-style: normal;
}
.venue + .venue {
  margin-top: 1rem;
  padding-top: 1rem;
  border-top: 1px solid var(--border, #e4defa);
}
.venue-head {
  display: flex;
  gap: 0.5rem;
  align-items: baseline;
  flex-wrap: wrap;
  margin-bottom: 0.5rem;
}
.chip {
  display: inline-block;
  margin: 0 0.3rem 0.3rem 0;
  padding: 0.05rem 0.55rem;
  border-radius: 999px;
  background: var(--lilac-bg, #e9e5fb);
  color: var(--lilac-text, #4b3fa0);
  font-size: 0.85rem;
  text-transform: capitalize;
}
.num {
  text-align: right;
  font-variant-numeric: tabular-nums;
}
th {
  font-size: 0.75rem;
  font-weight: 600;
  text-transform: uppercase;
  color: var(--text-muted, #6b6890);
}

/* Factor rows */
.factor {
  margin: 0 0 0.75rem;
  padding: 0.75rem 1rem;
  border: 1px solid var(--border, #e4defa);
  border-left: 4px solid var(--border, #e4defa);
  border-radius: 10px;
}
.factor.satisfactory {
  border-left-color: var(--mint-text, #1e6b47);
}
.factor.concern {
  border-left-color: var(--rose-text, #a12b47);
  background: #fff8f9;
}
.factor-top {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 1rem;
  flex-wrap: wrap;
}
.factor-label {
  font-weight: 600;
}
.factor-hint {
  margin-top: 0.15rem;
  font-size: 0.85rem;
  color: var(--text-muted, #6b6890);
}
.segmented {
  display: inline-flex;
  border: 1px solid var(--border, #e4defa);
  border-radius: 999px;
  overflow: hidden;
  flex-shrink: 0;
}
.segmented label {
  padding: 0.3rem 0.9rem;
  font-size: 0.85rem;
  cursor: pointer;
  user-select: none;
}
.segmented label + label {
  border-left: 1px solid var(--border, #e4defa);
}
.segmented input {
  position: absolute;
  opacity: 0;
  pointer-events: none;
}
.segmented label:focus-within {
  outline: 2px solid var(--primary, #6d5bd0);
  outline-offset: -2px;
}
.segmented label.on {
  background: var(--mint-bg, #d3f5e3);
  color: var(--mint-text, #1e6b47);
  font-weight: 600;
}
.segmented label.on.concern {
  background: var(--rose-bg, #ffdce3);
  color: var(--rose-text, #a12b47);
}
textarea {
  width: 100%;
  box-sizing: border-box;
  margin-top: 0.6rem;
  padding: 0.5rem 0.75rem;
  border: 1px solid var(--border, #e4defa);
  border-radius: 10px;
  font: inherit;
  resize: vertical;
}
.save-row,
.actions {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  flex-wrap: wrap;
  margin-top: 0.75rem;
}
.arrangements {
  display: flex;
  gap: 1.25rem;
  flex-wrap: wrap;
  margin: 0;
  padding: 0.6rem 1rem;
  border: 1px solid var(--border, #e4defa);
  border-radius: 10px;
}
.arrangements legend {
  padding: 0 0.35rem;
  font-size: 0.9rem;
  font-weight: 600;
}
.field-error {
  color: var(--rose-text, #a12b47);
  font-size: 0.85rem;
}
.errors {
  margin: 0.5rem 0 0;
  padding-left: 1.2rem;
}

/* Decision banner */
.notice {
  margin: 1rem 0 0;
  padding: 0.85rem 1rem;
  border-radius: 12px;
  background: var(--butter-bg, #fff1c2);
  color: var(--butter-text, #8a5a00);
}
.notice p {
  margin: 0.3rem 0 0;
}
.notice.approved {
  background: var(--mint-bg, #d3f5e3);
  color: var(--mint-text, #1e6b47);
}
.notice.rejected,
.notice.error {
  background: var(--rose-bg, #ffdce3);
  color: var(--rose-text, #a12b47);
}
.meta {
  font-size: 0.85rem;
  opacity: 0.85;
}
.decision-factors {
  margin: 0.6rem 0 0;
  padding: 0;
  list-style: none;
  font-size: 0.9rem;
}
.decision-factors li {
  margin-top: 0.25rem;
}
.outcome-pill {
  display: inline-block;
  min-width: 6.5rem;
  margin-right: 0.4rem;
  padding: 0.05rem 0.5rem;
  border-radius: 999px;
  background: #ffffff;
  font-size: 0.75rem;
  font-weight: 600;
  text-align: center;
}
.outcome-pill.concern {
  color: var(--rose-text, #a12b47);
}
.outcome-pill.satisfactory {
  color: var(--mint-text, #1e6b47);
}
.outcome-pill.unassessed {
  color: var(--text-muted, #6b6890);
}

.badge {
  display: inline-block;
  padding: 0.15rem 0.65rem;
  border-radius: 999px;
  background: var(--lilac-bg, #e9e5fb);
  color: var(--lilac-text, #4b3fa0);
  font-size: 0.8rem;
  font-weight: 500;
}
.badge.safety_check {
  background: var(--butter-bg, #fff1c2);
  color: var(--butter-text, #8a5a00);
}
.badge.confirmed {
  background: var(--mint-bg, #d3f5e3);
  color: var(--mint-text, #1e6b47);
}
.badge.planning {
  background: var(--sky-bg, #d6ecff);
  color: var(--sky-text, #1f5f99);
}

.btn { padding: 0.5rem 1.1rem; border: none; border-radius: 999px; font: inherit; font-size: 0.9rem; font-weight: 500; cursor: pointer; }
.btn:focus-visible { outline: 2px solid var(--primary, #6d5bd0); outline-offset: 2px; }
.btn:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-primary { background: var(--primary, #6d5bd0); color: #ffffff; }
.btn-mint { background: var(--mint-bg, #d3f5e3); color: var(--mint-text, #1e6b47); }
.btn-rose { background: var(--rose-bg, #ffdce3); color: var(--rose-text, #a12b47); }
.btn-butter { background: var(--butter-bg, #fff1c2); color: var(--butter-text, #8a5a00); }

.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
}
</style>
