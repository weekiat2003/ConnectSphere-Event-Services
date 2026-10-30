<template>
  <div>
    <h2 class="page-title">Venue Booking</h2>

    <div class="tabs" role="tablist" aria-label="Venue booking sections">
      <button type="button" role="tab" :aria-selected="activeTab === 'submit'"
        :class="['tab', { active: activeTab === 'submit' }]"
        @click="activeTab = 'submit'">Submit Booking Request</button>
      <button type="button" role="tab" :aria-selected="activeTab === 'status'"
        :class="['tab', { active: activeTab === 'status' }]"
        @click="switchTab('status')">My Booking Requests</button>
    </div>

    <div v-show="activeTab === 'submit'">
      <div class="card">
        <form @submit.prevent="submitBooking">
          <div v-if="resubmittingFromId !== null" class="resubmission-banner" role="status">
            <span class="resubmission-banner-icon" aria-hidden="true">ℹ</span>
            <span>
              <strong>Resubmitting rejected booking #{{ resubmittingFromId }}</strong>
              <span class="resubmission-banner-detail">A new pending request will be created. The rejected booking will remain in your history.</span>
            </span>
          </div>
          <div class="section">
            <h3>Event</h3>
            <div class="form-group">
              <label for="event">Select Event *</label>
              <select id="event" v-model="eventId" required>
                <option value="" disabled>Select an event</option>
                <option v-for="event in events" :key="event.id" :value="event.id">
                  {{ event.name || event.title || `Event ${event.id}` }}
                </option>
              </select>
            </div>

            <div v-if="selectedEvent" class="requirements-box">
              <h4>Event Venue Requirements</h4>
              <div class="requirements-grid">
                <div>
                  <span class="requirement-label">Capacity Needed</span>
                  <span>{{ selectedEvent.venueRequirements?.capacityNeeded ?? "Not specified" }}</span>
                </div>
                <div>
                  <span class="requirement-label">Required Layout</span>
                  <span>{{ selectedEvent.venueRequirements?.requiredLayout || "Not specified" }}</span>
                </div>
                <div>
                  <span class="requirement-label">Accessibility Needs</span>
                  <span>{{ selectedEvent.venueRequirements?.accessibilityNeeds || "Not specified" }}</span>
                </div>
                <div>
                  <span class="requirement-label">Required Facilities</span>
                  <span>{{ formatFacilities(selectedEvent.venueRequirements?.requiredFacilities) }}</span>
                </div>
              </div>
            </div>
          </div>

          <div class="section">
            <div class="section-heading">
              <div>
                <h3>Venues</h3>
                <p class="section-description">
                  Add one or more venues for this event. Each venue can have its own booking timing.
                </p>
              </div>
              <button type="button" class="btn secondary" @click="addVenue">+ Add Venue</button>
            </div>

            <div v-for="(venueRequest, index) in venueRequests" :key="venueRequest.key" class="venue-card">
              <div class="venue-heading">
                <h4>Venue {{ index + 1 }}</h4>
                <button v-if="venueRequests.length > 1" type="button" class="remove-btn"
                  @click="removeVenue(index)">Remove</button>
              </div>
              <div class="form-group">
                <label :for="`venue-${index}`">Venue *</label>
                <select :id="`venue-${index}`" v-model="venueRequest.venueId" required>
                  <option value="" disabled>Select a venue</option>
                  <option v-for="venue in availableVenues(index)" :key="venue.id" :value="venue.id">
                    {{ venue.name }}
                  </option>
                </select>
                <p v-if="fieldError(index, 'venue_id')" class="field-error">
                  {{ fieldError(index, "venue_id") }}
                </p>
              </div>

              <div v-if="venueRequest.venueId && selectedEvent" class="suitability-box">
                <h5 class="subheading">Venue Suitability Assessment</h5>
                <template v-if="selectedVenue(venueRequest)">
                  <p class="venue-summary">
                    <strong>{{ selectedVenue(venueRequest).name }}</strong>
                    · {{ selectedVenue(venueRequest).location || "Location not specified" }}
                  </p>
                  <p class="suitability-result" :class="suitability(venueRequest).status" role="status">
                    {{ suitability(venueRequest).status === "suitable"
                      ? "✓ Meets all specified event venue requirements"
                      : suitability(venueRequest).status === "unknown"
                        ? "ℹ Suitability cannot be fully assessed from the available information"
                        : "⚠ Some event requirements are not met or could not be verified. You may still submit this request." }}
                  </p>
                  <div class="suitability-grid">
                    <div v-for="check in suitability(venueRequest).checks" :key="check.label" class="suitability-check">
                      <span class="check-indicator" :class="check.status">
                        {{ check.status === "match" ? "✓" : check.status === "mismatch" ? "✕" : "?" }}
                      </span>
                      <div>
                        <strong>{{ check.label }}</strong>
                        <p>Required: {{ check.required }}</p>
                        <p>Venue: {{ check.available }}</p>
                      </div>
                    </div>
                  </div>
                  <p class="hint">Suitability is based on catalogue information, not booking availability. Venue Staff will assess the request.</p>
                </template>
              </div>

              <h5 class="subheading">Timing</h5>
              <div class="form-grid">
                <div class="form-group">
                  <label :for="`date-${index}`">Date *</label>
                  <input :id="`date-${index}`" v-model="venueRequest.date" type="date" :min="today" required />
                  <p v-if="fieldError(index, 'date')" class="field-error">{{ fieldError(index, "date") }}</p>
                </div>
                <div class="form-group">
                  <label :for="`start-${index}`">Start Time *</label>
                  <input :id="`start-${index}`" v-model="venueRequest.startTime" type="time" required />
                  <p v-if="fieldError(index, 'start_time')" class="field-error">
                    {{ fieldError(index, "start_time") }}
                  </p>
                </div>
                <div class="form-group">
                  <label :for="`end-date-${index}`">End Date</label>
                  <input :id="`end-date-${index}`" v-model="venueRequest.endDate"
                    type="date" :min="venueRequest.date || today" />
                  <p class="hint">Only needed if the booking ends on another day.</p>
                  <p v-if="fieldError(index, 'end_date')" class="field-error">
                    {{ fieldError(index, "end_date") }}
                  </p>
                </div>
                <div class="form-group">
                  <label :for="`end-${index}`">End Time *</label>
                  <input :id="`end-${index}`" v-model="venueRequest.endTime" type="time" required />
                  <p v-if="fieldError(index, 'end_time')" class="field-error">
                    {{ fieldError(index, "end_time") }}
                  </p>
                </div>
              </div>
            </div>

            <div v-if="generalErrors.length" class="error-message">
              <p v-for="(error, index) in generalErrors" :key="index">{{ error }}</p>
            </div>
          </div>

          <div class="actions">
            <button type="button" class="btn secondary" @click="resetForm">Clear</button>
            <button type="submit" class="btn" :disabled="submitting">
              {{ submitting ? "Submitting..." : resubmittingFromId !== null ? "Resubmit Booking Request" : "Submit Booking Request" }}
            </button>
          </div>
        </form>
      </div>
      <div v-if="successMessage" class="success-message">{{ successMessage }}</div>
      <div v-if="submitAdvisories.length" class="advisory possible_conflict" role="status">
        <p v-for="a in submitAdvisories" :key="a.id">{{ a.message }}</p>
      </div>
    </div>

    <section v-if="activeTab === 'status'" class="card status-section">
      <div class="section-heading">
        <div>
          <h3>My Booking Requests</h3>
          <p class="section-description">Each venue has its own booking status.</p>
        </div>
        <button type="button" class="btn secondary" @click="loadMyBookings" :disabled="statusLoading">
          {{ statusLoading ? "Refreshing..." : "Refresh Status" }}
        </button>
      </div>

      <p v-if="statusError" class="error-message" role="alert">{{ statusError }}</p>
      <p v-if="withdrawNotice" class="success-message" role="status">{{ withdrawNotice }}</p>
      <p v-if="statusLoading" class="status-message">Loading booking requests...</p>
      <p v-else-if="!statusError && myBookings.length === 0" class="status-message">
        You haven't submitted any venue booking requests yet.
      </p>

      <div v-if="!statusLoading && !statusError && myBookings.length" class="booking-list">
        <article v-for="booking in myBookings" :key="booking.id" class="booking-card">
          <button type="button" class="booking-expand-trigger" :aria-expanded="expandedBookingId === booking.id" :aria-controls="`booking-expanded-${booking.id}`" @click="toggleBooking(booking)">
          <div class="booking-heading">
            <div>
              <h4>{{ booking.eventName || `Event #${booking.eventId}` }}</h4>
              <p class="venue-label">{{ booking.venueName || `Venue #${booking.venueId}` }}</p>
            </div>
            <span class="booking-heading-right"><span class="status-pill" :class="booking.status">
              {{ formatStatus(booking.status) }}
            </span><span class="expand-chevron" :class="{ expanded: expandedBookingId === booking.id }" aria-hidden="true">⌄</span></span>
          </div>
          <div class="booking-details">
            <p><strong>Booking ID:</strong> #{{ booking.id }}</p>
            <p><strong>Start:</strong> {{ formatBookingDate(booking.startDatetime) }}</p>
            <p><strong>End:</strong> {{ formatBookingDate(booking.endDatetime) }}</p>
            <p><strong>Submitted:</strong> {{ formatBookingDate(booking.createdAt) }}</p>
          </div>
          </button>
          <div v-if="expandedBookingId === booking.id" :id="`booking-expanded-${booking.id}`" class="booking-expanded">
            <h5>Full booking details</h5>
            <div class="expanded-details">
              <p><strong>Event:</strong> {{ booking.eventName || `Event #${booking.eventId}` }}</p>
              <p><strong>Venue:</strong> {{ booking.venueName || `Venue #${booking.venueId}` }}</p>
              <p><strong>Status:</strong> {{ formatStatus(booking.status) }}</p>
              <p><strong>Start:</strong> {{ formatBookingDate(booking.startDatetime) }}</p>
              <p><strong>End:</strong> {{ formatBookingDate(booking.endDatetime) }}</p>
              <p><strong>Submitted:</strong> {{ formatBookingDate(booking.createdAt) }}</p>
              <p v-if="booking.label"><strong>Booking label:</strong> {{ booking.label }}</p>
              <p v-if="booking.equipment"><strong>Equipment:</strong> {{ booking.equipment }}</p>
              <p v-if="booking.catering"><strong>Catering:</strong> {{ booking.catering }}</p>
              <p v-if="booking.otherRequirements"><strong>Other requirements:</strong> {{ booking.otherRequirements }}</p>
            </div>
            <section class="event-equipment-section" aria-label="Event equipment requirements">
              <h5>Equipment requirements for this event</h5>
              <p v-if="equipmentLoading[booking.eventId]" class="expanded-note">Loading event equipment requirements...</p>
              <p v-else-if="equipmentErrors[booking.eventId]" class="error-message" role="alert">
                {{ equipmentErrors[booking.eventId] }}
                <button type="button" class="equipment-retry" @click="loadEventEquipment(booking.eventId, true)">Retry</button>
              </p>
              <template v-else-if="eventEquipment[booking.eventId]">
                <div v-if="eventEquipment[booking.eventId].length" class="equipment-table-wrap">
                  <table class="equipment-details-table">
                    <thead><tr><th>Equipment type</th><th>Quantity</th><th>Technical requirements</th><th>Review status</th></tr></thead>
                    <tbody>
                      <tr v-for="(item, index) in eventEquipment[booking.eventId]" :key="item.id ?? index">
                        <td>{{ item.type || item.equipmentType || 'Not specified' }}</td>
                        <td>{{ item.quantity ?? '—' }}</td>
                        <td>{{ item.technicalNotes || '—' }}</td>
                        <td>{{ item.status || 'Not reviewed' }}</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
                <p v-else class="expanded-note">No equipment requirements have been recorded for this event.</p>
              </template>
            </section>
            <p v-if="!booking.label && !booking.equipment && !booking.catering && !booking.otherRequirements" class="expanded-note">No additional venue-specific details were recorded with this booking.</p>
          <p v-if="booking.advisory" class="advisory" :class="booking.advisory.type" role="status">
            <strong>{{ booking.advisory.type === 'venue_confirmed' ? 'Venue now confirmed for another event:' : 'Advisory:' }}</strong>
            {{ booking.advisory.message }}
          </p>
          <p v-if="booking.status === 'cancelled'" class="cancellation-reason">
            <strong>Booking cancelled.</strong> This venue is no longer confirmed for your event.
            <span v-if="booking.decisionReason"><br /><strong>Reason:</strong> {{ booking.decisionReason }}</span>
          </p>
          <p v-if="booking.status === 'rejected' && booking.decisionReason" class="rejection-reason">
            <strong>Reason for rejection:</strong> {{ booking.decisionReason }}
          </p>
          <p v-if="booking.status === 'rejected' && booking.alternativeSuggestion" class="rejection-reason">
            <strong>Alternative suggestion:</strong> {{ booking.alternativeSuggestion }}
          </p>
          <div v-if="booking.status === 'rejected'" class="booking-actions">
            <button type="button" class="btn" @click="resubmitRejectedBooking(booking)">
              Resubmit Booking
            </button>
          </div>
          <div v-if="booking.status === 'pending'" class="booking-actions">
            <button type="button" class="btn withdraw-btn" :disabled="withdrawingId === booking.id"
              @click="openWithdrawConfirmation(booking)">
              {{ withdrawingId === booking.id ? "Withdrawing..." : "Withdraw Request" }}
            </button>
          </div>
          <p v-if="withdrawErrors[booking.id]" class="error-message" role="alert">
            {{ withdrawErrors[booking.id] }}
          </p>
          </div>
        </article>
      </div>
    </section>

    <div v-if="bookingToWithdraw" class="modal-backdrop" @click.self="cancelWithdrawal">
      <div class="confirmation-dialog" role="alertdialog" aria-modal="true"
        aria-labelledby="withdraw-dialog-title" aria-describedby="withdraw-dialog-description">
        <h3 id="withdraw-dialog-title">Withdraw booking request?</h3>
        <p id="withdraw-dialog-description">
          Are you sure you want to withdraw the pending request for
          <strong>{{ bookingToWithdraw.venueName || `Venue #${bookingToWithdraw.venueId}` }}</strong>?
          You cannot undo this withdrawal.
        </p>
        <div class="confirmation-actions">
          <button type="button" class="btn secondary" :disabled="withdrawingId !== null"
            @click="cancelWithdrawal">Cancel</button>
          <button type="button" class="btn withdraw-btn" :disabled="withdrawingId !== null"
            @click="confirmWithdrawal">
            {{ withdrawingId !== null ? "Withdrawing..." : "Yes, Withdraw" }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from "vue";
import eventsApi from "../api/events";
import venuesApi from "../api/venues";

const activeTab = ref("submit");
const events = ref([]);
const venues = ref([]);
const eventId = ref("");
const submitting = ref(false);
const errors = ref([]);
const successMessage = ref("");
const resubmittingFromId = ref(null);

const myBookings = ref([]);
const expandedBookingId = ref(null);
const eventEquipment = ref({});
const equipmentLoading = ref({});
const equipmentErrors = ref({});

async function loadEventEquipment(eventId, force = false) {
  if (eventId == null || eventId === "") {
    equipmentErrors.value[eventId] = "This booking has no linked event ID.";
    return;
  }
  if (equipmentLoading.value[eventId] || (!force && Object.prototype.hasOwnProperty.call(eventEquipment.value, eventId))) return;
  equipmentLoading.value[eventId] = true;
  equipmentErrors.value[eventId] = "";
  try {
    const { data } = await eventsApi.getEvent(eventId);
    // Event detail responses may be either the event itself or wrapped in { event }.
    const event = data?.event ?? data;
    const requirements = event?.equipmentRequirements ?? event?.equipment_requirements;
    if (!Array.isArray(requirements)) throw new Error("Equipment requirements were not included in the event response.");
    eventEquipment.value[eventId] = requirements;
  } catch (error) {
    equipmentErrors.value[eventId] = error.response?.data?.error || error.message || "Could not load equipment requirements.";
  } finally {
    equipmentLoading.value[eventId] = false;
  }
}

function toggleBooking(booking) {
  if (expandedBookingId.value === booking.id) {
    expandedBookingId.value = null;
    return;
  }
  expandedBookingId.value = booking.id;
  // Refresh each time a card opens so changes from Equipment Booking appear.
  loadEventEquipment(booking.eventId, true);
}

function parseHoldExpiry(value) {
  if (!value) return null;
  const text = String(value).trim().replace(" ", "T");
  const date = new Date(/(?:Z|[+-]\d{2}:?\d{2})$/i.test(text) ? text : `${text}Z`);
  return Number.isNaN(date.getTime()) ? null : date;
}

function formatHoldExpiry(date) {
  return date.toLocaleString("en-SG", {
    timeZone: "Asia/Singapore", day: "2-digit", month: "2-digit", year: "numeric",
    hour: "numeric", minute: "2-digit", hour12: true,
  });
}
const statusLoading = ref(false);
const statusError = ref("");
const bookingToWithdraw = ref(null);
const withdrawingId = ref(null);
const withdrawErrors = ref({});
const withdrawNotice = ref("");

const selectedEvent = computed(() =>
  events.value.find((event) => Number(event.id) === Number(eventId.value))
);

const today = new Date().toLocaleDateString("en-CA");
let nextVenueKey = 0;
const emptyVenue = () => ({
  key: nextVenueKey++,
  venueId: "",
  date: "",
  startTime: "",
  endTime: "",
  endDate: "",
  label: "",
  equipment: "",
  catering: "",
  otherRequirements: "",
});
const venueRequests = ref([emptyVenue()]);

const submitAdvisories = ref([]);

function formatFacilities(value) {
  if (Array.isArray(value)) return value.length ? value.join(", ") : "Not specified";
  return value || "Not specified";
}

function selectedVenue(request) {
  return venues.value.find((venue) => Number(venue.id) === Number(request.venueId));
}

function values(value) {
  if (Array.isArray(value)) return value.map(String).map(v => v.trim()).filter(Boolean);
  if (typeof value === "string") return value.split(",").map(v => v.trim()).filter(Boolean);
  return [];
}

function normalize(value) {
  return String(value).toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
}

function featureMatches(required, available) {
  const requirement = normalize(required);
  const candidate = normalize(available);
  if (requirement === candidate) return true;
  // Common wording differences in catalogue and event requirements.
  const stepFree = /step free/.test(requirement) && /step free/.test(candidate);
  return stepFree;
}

function suitability(request) {
  const venue = selectedVenue(request);
  const requirements = selectedEvent.value?.venueRequirements;
  if (!venue || !requirements) return { status: "unknown", checks: [] };

  const checks = [];
  const capacity = Number(requirements.capacityNeeded);
  const venueCapacity = Number(venue.capacity);
  checks.push({
    label: "Capacity",
    required: capacity > 0 ? `${capacity} people` : "Not specified",
    available: Number.isFinite(venueCapacity) && venue.capacity != null ? `${venueCapacity} people` : "Not specified",
    status: capacity > 0
      ? (venue.capacity == null || !Number.isFinite(venueCapacity) ? "unknown" : venueCapacity >= capacity ? "match" : "mismatch")
      : "unknown",
    applicable: capacity > 0,
  });

  const layout = String(requirements.requiredLayout || "").trim();
  const layouts = values(venue.supportedLayouts);
  checks.push({
    label: "Layout",
    required: layout || "Not specified",
    available: layouts.join(", ") || "Not specified",
    status: !layout ? "unknown" : !layouts.length ? "unknown"
      : layouts.some(item => featureMatches(layout, item)) ? "match" : "mismatch",
    applicable: !!layout,
  });

  const access = values(requirements.accessibilityNeeds);
  const accessible = values(venue.accessibilityFeatures);
  checks.push({
    label: "Accessibility",
    required: access.join(", ") || "Not specified",
    available: accessible.join(", ") || "Not specified",
    status: !access.length ? "unknown" : !accessible.length ? "unknown"
      : access.every(item => accessible.some(feature => featureMatches(item, feature))) ? "match" : "mismatch",
    applicable: access.length > 0,
  });

  const facilities = values(requirements.requiredFacilities);
  const availableFacilities = values(venue.facilities);
  checks.push({
    label: "Facilities",
    required: facilities.join(", ") || "Not specified",
    available: availableFacilities.join(", ") || "Not specified",
    status: !facilities.length ? "unknown" : !availableFacilities.length ? "unknown"
      : facilities.every(item => availableFacilities.some(feature => featureMatches(item, feature))) ? "match" : "mismatch",
    applicable: facilities.length > 0,
  });

  const applicable = checks.filter(check => check.applicable);
  const status = applicable.some(check => check.status === "mismatch")
    ? "warning" : applicable.length && applicable.every(check => check.status === "match")
      ? "suitable" : "unknown";
  return { status, checks };
}

function availableVenues(currentIndex) {
  const selectedIds = venueRequests.value
    .filter((_, index) => index !== currentIndex)
    .map((request) => Number(request.venueId))
    .filter(Boolean);
  return venues.value.filter((venue) => !selectedIds.includes(Number(venue.id)));
}

function addVenue() {
  venueRequests.value.push(emptyVenue());
}

function removeVenue(index) {
  venueRequests.value.splice(index, 1);
  errors.value = [];
}

function resetForm() {
  resubmittingFromId.value = null;
  eventId.value = "";
  venueRequests.value = [emptyVenue()];
  errors.value = [];
  successMessage.value = "";
}

function resubmitRejectedBooking(booking) {
  if (booking.status !== "rejected") return;

  // Keep database wall-clock times unchanged when filling date/time inputs.
  const start = String(booking.startDatetime || "").replace(" ", "T");
  const end = String(booking.endDatetime || "").replace(" ", "T");
  const startDate = start.slice(0, 10);
  const endDate = end.slice(0, 10);

  eventId.value = Number(booking.eventId);
  venueRequests.value = [{
    ...emptyVenue(),
    venueId: Number(booking.venueId),
    date: startDate,
    startTime: start.slice(11, 16),
    endTime: end.slice(11, 16),
    endDate: endDate !== startDate ? endDate : "",
    label: booking.label || "",
    equipment: booking.equipment || "",
    catering: booking.catering || "",
    otherRequirements: booking.otherRequirements || "",
  }];
  resubmittingFromId.value = booking.id;
  errors.value = [];
  successMessage.value = "";
  activeTab.value = "submit";
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function fieldError(index, field) {
  const request = venueRequests.value[index];
  const matchingError = errors.value.find((error) => {
    if (error.field !== field) return false;
    if (error.venue_id != null) {
      return Number(error.venue_id) === Number(request.venueId);
    }
    return error.venue === `Venue ${index + 1}`;
  });
  return matchingError?.message || "";
}

const generalErrors = computed(() =>
  errors.value.filter((error) => error.field === "venues").map((error) => error.message)
);

async function submitBooking() {
  errors.value = [];
  successMessage.value = "";

  if (!eventId.value) {
    errors.value = [{ field: "venues", message: "Please select an event." }];
    return;
  }

  submitting.value = true;
  try {
    const payload = {
      eventId: Number(eventId.value),
      venues: venueRequests.value.map((venue) => ({
        venueId: Number(venue.venueId),
        date: venue.date,
        startTime: venue.startTime,
        endTime: venue.endTime,
        endDate: venue.endDate || null,
        label: venue.label || null,
        equipment: venue.equipment || null,
        catering: venue.catering || null,
        otherRequirements: venue.otherRequirements || null,
      })),
    };

    const { data: created } = await venuesApi.submitBooking(payload);
    submitAdvisories.value = (created || [])
      .filter((b) => b.advisory)
      .map((b) => ({ id: b.id, message: b.advisory.message }));
    successMessage.value = resubmittingFromId.value !== null
      ? "Resubmission created as a new pending booking. The original rejection remains on record."
      : "Venue booking request submitted successfully.";
    resubmittingFromId.value = null;
    venueRequests.value = [emptyVenue()];
  } catch (error) {
    const data = error.response?.data;
    if (Array.isArray(data?.errors)) {
      errors.value = data.errors;
    } else {
      errors.value = [{
        field: "venues",
        message: data?.error || "Unable to submit the booking request.",
      }];
    }
  } finally {
    submitting.value = false;
  }
}

async function loadMyBookings() {
  statusLoading.value = true;
  statusError.value = "";
  withdrawNotice.value = "";
  try {
    const response = await venuesApi.getMyBookings();
    myBookings.value = response.data;
  } catch (error) {
    myBookings.value = []; // Never display outdated statuses after a failed refresh.
    statusError.value =
      error.response?.data?.error || "Unable to load your booking requests.";
  } finally {
    statusLoading.value = false;
  }
}

function openWithdrawConfirmation(booking) {
  if (booking.status !== "pending" || withdrawingId.value !== null) return;
  withdrawErrors.value = { ...withdrawErrors.value, [booking.id]: "" };
  withdrawNotice.value = "";
  bookingToWithdraw.value = booking;
}

function cancelWithdrawal() {
  if (withdrawingId.value !== null) return;
  bookingToWithdraw.value = null;
}

async function confirmWithdrawal() {
  const booking = bookingToWithdraw.value;
  if (!booking || withdrawingId.value !== null) return;
  if (booking.status !== "pending") {
    bookingToWithdraw.value = null;
    return;
  }

  withdrawingId.value = booking.id;
  withdrawErrors.value = { ...withdrawErrors.value, [booking.id]: "" };
  try {
    // The server decides whether the booking is still pending and owned by us.
    await venuesApi.withdrawBooking(booking.id);
    bookingToWithdraw.value = null;
    // Re-fetch the authoritative state; do not optimistically mark withdrawn.
    await loadMyBookings();
    if (!statusError.value) {
      withdrawNotice.value = "Booking request withdrawn successfully.";
    }
  } catch (error) {
    bookingToWithdraw.value = null;
    const code = error.response?.status;
    const serverMessage = error.response?.data?.error;
    const message = code === 400 || code === 409
      ? "This booking request has already been decided or can no longer be withdrawn."
      : code === 403
        ? "You are not allowed to withdraw this booking request."
        : serverMessage || "Withdrawal did not go through. Please try again.";
    withdrawErrors.value = { ...withdrawErrors.value, [booking.id]: message };
    // A decision may have happened since the list was loaded. Re-fetch, but
    // keep the withdrawal error visible even if the refresh succeeds.
    if (code === 400 || code === 409 || code === 403) {
      try {
        const response = await venuesApi.getMyBookings();
        myBookings.value = response.data;
      } catch (_) {
        myBookings.value = [];
        statusError.value = "Unable to refresh booking status. Please try again.";
      }
    }
  } finally {
    withdrawingId.value = null;
  }
}

async function switchTab(tab) {
  activeTab.value = tab;
  if (tab === "status") await loadMyBookings();
}

function formatStatus(status) {
  const labels = {
    pending: "Pending",
    approved: "Approved",
    rejected: "Rejected",
    withdrawn: "Withdrawn",
    cancelled: "Cancelled",
    held: "Held",
    expired: "Expired",
    released: "Released",
  };
  return labels[status] || status || "Unknown";
}

function formatBookingDate(value) {
  if (!value) return "N/A";
  // Database DATETIME values are timezone-naive; don't shift their clock times.
  const [date, time = ""] = String(value).replace(" ", "T").split("T");
  return `${date} ${time.slice(0, 5)}`.trim();
}

onMounted(async () => {
  try {
    const eventsResponse = await eventsApi.assignedEvents();
    events.value = eventsResponse.data;
  } catch (error) {
    console.error("EVENTS ERROR:", error);
  }

  try {
    const venuesResponse = await venuesApi.listVenues();
    venues.value = venuesResponse.data;
  } catch (error) {
    console.error("VENUES ERROR:", error);
  }
});
</script>

<style scoped>
.status-pill.held { background: #fef3c7; color: #92400e; }
.status-pill.expired, .status-pill.released { background: #e2e8f0; color: #475569; }

.page-title { margin: 0 0 1rem; font-size: 1.5rem; font-weight: 600; color: var(--text, #2d2a4a); }
.card { background: var(--surface, #fff); border: 1px solid var(--border, #e4defa); border-radius: 14px; box-shadow: 0 4px 16px rgba(109, 91, 208, .08); overflow: hidden; }
.section { padding: 1.25rem; border-bottom: 1px solid var(--border, #e4defa); }
.section:last-child { border-bottom: none; }
.section h3, .status-section h3 { margin: 0 0 1rem; color: var(--text, #2d2a4a); font-size: 1.1rem; font-weight: 600; }
.section-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 1rem; margin-bottom: 1rem; }
.section-heading h3 { margin-bottom: .25rem; }
.section-description { margin: 0; color: var(--text-muted, #6b6890); font-size: .9rem; }
.venue-card { margin-top: 1rem; padding: 1.25rem; background: #faf9ff; border: 1px solid var(--border, #e4defa); border-radius: 12px; }
.venue-heading { display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem; }
.venue-heading h4 { margin: 0; color: var(--lilac-text, #4b3fa0); font-size: 1rem; }
.subheading { margin: 1rem 0 .8rem; color: var(--text, #2d2a4a); font-size: .95rem; font-weight: 600; }
.form-group { display: flex; flex-direction: column; gap: .35rem; margin-bottom: 1rem; }
.form-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 0 1rem; }
label { color: var(--text, #2d2a4a); font-size: .875rem; font-weight: 500; }
input, select, textarea { width: 100%; box-sizing: border-box; padding: .65rem .75rem; border: 1px solid var(--border, #e4defa); border-radius: 8px; background: #fff; color: var(--text, #2d2a4a); font: inherit; }
input:focus, select:focus, textarea:focus { outline: 2px solid var(--primary, #6d5bd0); outline-offset: 1px; border-color: var(--primary, #6d5bd0); }
.hint { margin: 0; color: var(--text-muted, #6b6890); font-size: .78rem; }
.field-error { margin: .25rem 0 0; color: var(--rose-text, #a12b47); font-size: .85rem; }
.error-message { margin-top: 1rem; padding: .8rem 1rem; background: var(--rose-bg, #fde8ee); color: var(--rose-text, #a12b47); border-radius: 8px; font-size: .875rem; }
.error-message p { margin: .2rem 0; }
.success-message { margin-top: 1rem; padding: .9rem 1rem; border-radius: 10px; background: var(--mint-bg, #d3f5e3); color: var(--mint-text, #1e6b47); font-weight: 500; }
.actions { display: flex; justify-content: flex-end; gap: .75rem; padding: 1.25rem; }
.btn { display: inline-block; padding: .55rem 1.1rem; border: none; border-radius: 999px; background: var(--primary, #6d5bd0); color: #fff; font: inherit; font-weight: 500; cursor: pointer; }
.btn:hover:not(:disabled) { background: var(--primary-hover, #5b49bd); }
.btn.secondary { background: var(--lilac-bg, #e9e5fb); color: var(--lilac-text, #4b3fa0); }
.btn.secondary:hover { background: #ddd6fb; }
.btn:disabled { opacity: .6; cursor: not-allowed; }
.remove-btn { border: none; background: transparent; color: var(--rose-text, #a12b47); font: inherit; font-size: .85rem; font-weight: 500; cursor: pointer; }
.remove-btn:hover { text-decoration: underline; }
.requirements-box { margin-top: 1rem; padding: 1rem; background: #faf9ff; border: 1px solid var(--border, #e4defa); border-radius: 10px; }
.requirements-box h4 { margin: 0 0 .8rem; color: var(--lilac-text, #4b3fa0); font-size: .95rem; }
.requirements-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: .8rem 1.5rem; }
.requirements-grid > div { display: flex; flex-direction: column; gap: .2rem; }
.requirement-label { color: var(--text-muted, #6b6890); font-size: .78rem; font-weight: 500; }
.tabs { display: flex; gap: .5rem; margin: 0 0 1.25rem; border-bottom: 1px solid var(--border, #e4defa); }
.tab { padding: .8rem 1rem; border: none; border-bottom: 3px solid transparent; background: transparent; color: var(--text-muted, #6b6890); font: inherit; font-weight: 600; cursor: pointer; }
.tab.active { color: var(--lilac-text, #4b3fa0); border-bottom-color: var(--primary, #6d5bd0); }
.status-section { padding: 1.25rem; }
.status-message { color: var(--text-muted, #6b6890); }
.booking-list { display: grid; gap: 1rem; }
.booking-card { padding: 1.25rem; background: #faf9ff; border: 1px solid var(--border, #e4defa); border-radius: 12px; }
.booking-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 1rem; }
.booking-heading h4 { margin: 0 0 .35rem; color: var(--text, #2d2a4a); }
.venue-label { margin: 0; color: var(--text-muted, #6b6890); }
.booking-details { margin-top: 1rem; display: grid; grid-template-columns: repeat(2, 1fr); gap: .6rem 1rem; }
.booking-details p { margin: 0; font-size: .875rem; }
.status-pill { display: inline-block; border-radius: 999px; padding: .4rem .75rem; font-size: .8rem; font-weight: 600; white-space: nowrap; }
.status-pill.pending { background: #fef3c7; color: #92400e; }
.status-pill.approved { background: #d3f5e3; color: #1e6b47; }
.status-pill.rejected { background: #fde8ee; color: #a12b47; }
.status-pill.cancelled { background: #fde8ee; color: #a12b47; }
.cancellation-reason { margin: 1rem 0 0; padding: .75rem; border-radius: 8px; background: #fde8ee; color: #a12b47; font-size: .875rem; }
.status-pill.withdrawn { background: #e9e5fb; color: #4b3fa0; }
.booking-actions { display: flex; justify-content: flex-end; margin-top: 1rem; }
.withdraw-btn { background: #a12b47; }
.withdraw-btn:hover:not(:disabled) { background: #86223b; }
.modal-backdrop { position: fixed; inset: 0; z-index: 1000; background: rgba(28, 22, 54, .55); display: flex; align-items: center; justify-content: center; padding: 1rem; }
.confirmation-dialog { width: min(100%, 430px); padding: 1.5rem; background: #fff; border-radius: 14px; box-shadow: 0 16px 45px rgba(0, 0, 0, .2); }
.confirmation-dialog h3 { margin: 0 0 .75rem; color: var(--text, #2d2a4a); }
.confirmation-dialog p { line-height: 1.5; }
.confirmation-actions { display: flex; justify-content: flex-end; gap: .75rem; margin-top: 1.25rem; }
.rejection-reason { margin: 1rem 0 0; padding: .75rem; border-radius: 8px; background: #fde8ee; color: #a12b47; font-size: .875rem; }
@media (max-width: 700px) {
  .form-grid, .requirements-grid, .booking-details { grid-template-columns: 1fr; }
  .section-heading { flex-direction: column; }
  .actions { flex-direction: column-reverse; }
  .actions .btn { width: 100%; }
  .tabs { flex-wrap: wrap; }
  .booking-heading { flex-direction: column; }
}

/* Resubmission notice: inset to align with the form sections. */
.resubmission-banner {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  margin: 20px 20px 0;
  padding: 14px 16px;
  background: #f3efff;
  border: 1px solid #d9ceff;
  border-left: 4px solid #7057d8;
  border-radius: 10px;
  color: #4c3c8c;
  font-size: 14px;
  line-height: 1.5;
}
.resubmission-banner-icon { font-size: 18px; line-height: 1.3; flex-shrink: 0; }
.resubmission-banner-detail { display: block; margin-top: 3px; }
.resubmission-banner + .section { padding-top: 16px; }

.advisory { margin: 1rem 0 0; padding: .75rem; border-radius: 8px; font-size: .875rem; }
.advisory p { margin: .2rem 0; }
.advisory.possible_conflict { background: #fffbeb; border: 1px solid #fcd34d; color: #92400e; }
.advisory.venue_confirmed { background: #fde8ee; border: 1px solid #f3b4c4; color: #a12b47; }

/* Venue-to-event requirements comparison */
.suitability-box { margin: 1rem 0 1.25rem; padding: 1rem; border: 1px solid #ddd6fb; background: #f7f5ff; border-radius: 10px; }
.suitability-box .subheading { margin-top: 0; }
.venue-summary { margin: .5rem 0 1rem; color: #4b3fa0; }
.suitability-result { padding: .75rem; border-radius: 8px; font-size: .875rem; font-weight: 600; }
.suitability-result.suitable { background: #d3f5e3; color: #1e6b47; }
.suitability-result.warning { background: #fff1c9; color: #92400e; }
.suitability-result.unknown { background: #e9e5fb; color: #4b3fa0; }
.suitability-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: .75rem; margin: 1rem 0; }
.suitability-check { display: flex; align-items: flex-start; gap: .65rem; padding: .75rem; background: #fff; border: 1px solid #e4defa; border-radius: 8px; }
.suitability-check strong { font-size: .875rem; }
.suitability-check p { margin: .25rem 0 0; font-size: .8rem; color: #6b6890; overflow-wrap: anywhere; }
.check-indicator { flex: 0 0 1.3rem; text-align: center; font-weight: 700; }
.check-indicator.match { color: #1e6b47; }
.check-indicator.mismatch { color: #a12b47; }
.check-indicator.unknown { color: #6b6890; }
@media (max-width: 700px) { .suitability-grid { grid-template-columns: 1fr; } }
.booking-expand-trigger { display: block; width: 100%; padding: 0; text-align: left; border: 0; background: transparent; color: inherit; font: inherit; cursor: pointer; }
.booking-expand-trigger:focus-visible { outline: 2px solid #7159db; outline-offset: 5px; border-radius: 6px; }
.booking-heading-right { display: flex; align-items: center; gap: 1rem; }
.expand-chevron { font-size: 1.5rem; line-height: 1; color: #6c5ab3; transition: transform .2s ease; }
.expand-chevron.expanded { transform: rotate(180deg); }
.booking-expanded { border-top: 1px solid #e4defa; margin-top: 1rem; padding-top: 1rem; }
.booking-expanded h5 { margin: 0 0 .75rem; font-size: .95rem; }
.expanded-details { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: .65rem 1rem; }
.expanded-details p { margin: 0; font-size: .875rem; overflow-wrap: anywhere; }
.expanded-note { color: #71698f; font-size: .85rem; }
@media (max-width: 700px) { .expanded-details { grid-template-columns: 1fr; } }

.event-equipment-section { margin-top: 1.1rem; padding-top: 1rem; border-top: 1px solid #e4defa; }
.event-equipment-section h5 { margin: 0 0 .7rem; }
.equipment-table-wrap { overflow-x: auto; }
.equipment-details-table { width: 100%; border-collapse: collapse; font-size: .85rem; text-align: left; }
.equipment-details-table th, .equipment-details-table td { padding: .65rem .6rem; border-bottom: 1px solid #e8e3f8; vertical-align: top; }
.equipment-details-table th { color: #50458a; background: #f5f2ff; white-space: nowrap; }
.equipment-retry { margin-left: .5rem; border: 0; background: transparent; color: #5946c2; text-decoration: underline; cursor: pointer; }
</style>

