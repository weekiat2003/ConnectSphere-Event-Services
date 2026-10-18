<template>
  <div v-if="event">
    <div v-if="isOwningOrganiser && canRespondToClarifications && openClarifications.length" class="notice">
      <strong>
        {{ openClarifications.length }} clarification request<span v-if="openClarifications.length > 1">s</span>
        awaiting your response.
      </strong>
    </div>

    <div v-if="!event.coordinatorId" class="notice">
      <strong>Unassigned.</strong> No Coordinator is currently assigned to this event.
    </div>

    <div v-if="priorDecisions.length" class="card history">
      <h3 class="section-title">Previous Submission History</h3>
      <p class="notice-inline">
        This is resubmission #{{ priorDecisions.length + 1 }}. Earlier attempts are shown below for reference.
      </p>
      <ul class="thread-list">
        <li v-for="decision in priorDecisions" :key="decision.eventId" class="thread-item">
          <div class="thread-message" :class="decision.outcome">
            <span class="thread-meta">
              {{ decision.outcome === "approved" ? "Approved" : "Rejected" }} by
              {{ decision.coordinatorName || `Coordinator #${decision.coordinatorId}` }}
              · {{ formatDate(decision.timestamp) }}
            </span>
            <p v-if="decision.reason">{{ decision.reason }}</p>
          </div>
        </li>
      </ul>
    </div>

    <!-- Event summary -->
    <div class="card summary">
      <div class="title-row">
        <h2 class="page-title">{{ event.name }}</h2>
        <span class="badge" :class="event.status">{{ statusLabel(event.status) }}</span>
        <button
          v-if="isAssignedCoordinator && !showEditForm && ['under_review', 'approved', 'planning'].includes(event.status)"
          class="btn btn-grey btn-small" @click="openEditForm">Edit
        </button>
        <button v-if="isAssignedCoordinator && ['approved', 'planning'].includes(event.status)"
          class="btn btn-rose btn-small" @click="cancelEvent">Cancel Event
        </button>
      </div>
      <div v-if="event.reviewDecision?.outcome" class="notice" :class="event.reviewDecision.outcome">
        <strong>
          Coordinator {{ event.reviewDecision.outcome === "approved" ? "approved" : "rejected" }} request
        </strong>
        <p class="decision-meta">
          By {{ event.reviewDecision.coordinatorName || `Coordinator #${event.reviewDecision.coordinatorId}` }}
          on {{ formatDate(event.reviewDecision.timestamp) }}
        </p>
        <p v-if="event.reviewDecision.reason" class="decision-reason">
          <strong>Reason:</strong> {{ event.reviewDecision.reason }}
        </p>
      </div>
      <div v-if="latestSafetyReview" class="notice"
        :class="latestSafetyReview.decision === 'approved' ? 'approved' : 'rejected'">
        <strong>{{ safetyDecisionHeading(latestSafetyReview.decision) }}</strong>
        <p class="decision-meta">
          By {{ latestSafetyReview.safetyOfficerName || `Safety Officer #${latestSafetyReview.safetyOfficerId}` }}
          on {{ formatDate(latestSafetyReview.createdAt) }}
        </p>
        <p v-if="latestSafetyReview.comments" class="decision-reason">
          <strong>Reason:</strong> {{ latestSafetyReview.comments }}
        </p>
        <p v-if="latestSafetyReview.concernFactors?.length" class="decision-reason">
          <strong>Concerns:</strong> {{ formatSafetyFactors(latestSafetyReview.concernFactors) }}
        </p>
        <p v-if="latestSafetyReview.affectedArrangements?.length" class="decision-reason">
          <strong>Affected arrangements:</strong> {{ formatArrangements(latestSafetyReview.affectedArrangements) }}
        </p>
      </div>
      <p class="description">{{ event.description }}</p>
      <div class="details">
        <div class="detail">
          <span class="detail-label">Proposed Date and Time</span>
          <span>{{ event.proposedDate || "—" }} {{ event.proposedTime || "" }}</span>
        </div>
        <div class="detail">
          <span class="detail-label">Expected attendance</span>
          <span>{{ event.expectedAttendance || "—" }}</span>
        </div>
        <div class="detail">
          <span class="detail-label">Equipment required</span>
          <span>{{ event.venueRequirements?.capacityNeeded || "—" }}</span>
        </div>
        <div class="detail">
          <span class="detail-label">Venue Required</span>
          <span>{{ event.venueRequirements?.requiredLayout || "—" }}</span>
        </div>
        <div class="detail">
          <span class="detail-label">Registration</span>
          <span class="reg-pill" :class="{ required: event.registrationRequired }">
            {{ event.registrationRequired ? "Required" : "Not required" }}
          </span>
        </div>
      </div>

      <div class="accessibility">
        <span class="detail-label">Accessibility needs</span>
        <p>{{ event.venueRequirements?.accessibilityNeeds || "None specified" }}</p>
      </div>
    </div>

    <div>
      <p></p>
    </div>

    <div v-if="clarificationThread.length" class="card history">
      <h3 class="section-title">Clarification Thread</h3>
      <ul class="thread-list">
        <li v-for="item in clarificationThread" :key="item.reviewId" class="thread-item">
          <div class="thread-message request">
            <span class="thread-meta">Coordinator · {{ formatDate(item.request.createdAt) }}</span>
            <p>{{ item.request.comments }}</p>
            <p v-if="item.request.editableFields?.length" class="thread-fields">
              Fields opened for editing: {{ formatFieldNames(item.request.editableFields) }}
            </p>
          </div>
          <div v-if="item.response" class="thread-message response">
            <span class="thread-meta">Organiser · {{ formatDate(item.response.createdAt) }}</span>
            <p>{{ item.response.comments }}</p>
            <p v-if="Object.keys(item.response.updatedFields || {}).length" class="thread-fields">
              Updated: {{ formatFieldNames(Object.keys(item.response.updatedFields)) }}
            </p>
          </div>
          <div v-else-if="item.withdrawn" class="thread-withdrawn">Withdrawn by coordinator</div>
          <div v-else class="thread-pending">
            <span>Awaiting organiser's response</span>
            <button v-if="isAssignedCoordinator" class="btn btn-grey btn-small"
              @click="deleteClarificationRequest(item.reviewId)">
              Delete request
            </button>
          </div>
        </li>
      </ul>

    </div>

    <div v-if="changeRequests.length" class="card history">
      <h3 class="section-title">Change and Withdrawal Requests</h3>
      <ul class="thread-list">
        <li v-for="request in changeRequests" :key="request.id" class="thread-item">
          <div class="change-header">
            <span class="badge" :class="request.status">{{ statusLabel(request.status) }}</span>
            <span v-if="request.requestType === 'withdrawal'" class="badge withdrawal">Withdrawal</span>
            <span v-else class="badge" :class="request.isSignificant ? 'significant' : 'routine'">
              {{ request.isSignificant ? "Significant" : "Routine" }}
            </span>
            <span class="thread-meta">Requested {{ formatDate(request.createdAt) }} </span>
          </div>
          <p class="change-reason"><strong>Reason:</strong> {{ request.reason }}</p>
          <ul v-if="request.requestType !== 'withdrawal'" class="change-list">
            <li v-for="(change, key) in request.requestedChanges" :key="key">
              <strong>{{ CHANGE_LABELS[key] || key }}:</strong>
              {{ formatChangeValue(key, change.from) }} → {{ formatChangeValue(key, change.to) }}
            </li>
          </ul>
          <p v-if="request.decisionReason" class="change-reason">
            <strong>Coordinator's reason:</strong> {{ request.decisionReason }}
          </p>
          <router-link v-if="isAssignedCoordinator"
            :to="{ name: 'change-request-review', query: { id: request.id } }">Open in review</router-link>
          <p v-if="request.decidedAt" class="change-reason"><strong>Processed:</strong> {{ formatDate(request.decidedAt)
          }}</p>
          <p v-if="request.status === 're_review' && request.reReviewAt" class="change-reason">
            <strong>Sent for re-review</strong> by the assigned Coordinator on {{ formatDate(request.reReviewAt) }}.
            Affected arrangements are flagged for reconsideration; proposed values are not applied yet.
          </p>
        </li>
      </ul>
    </div>

    <!-- Coordinator Assignment: visible to any Coordinator when the event has
         no assigned Coordinator yet. Still fully rule-based — the caller
         doesn't pick who it goes to, they just trigger the automatic retry
         (see try_assign_and_advance). Not gated by isAssignedCoordinator
         since, by definition, nobody is assigned yet. -->
    <section v-if="auth.hasRole('event_coordinator') && !event.coordinatorId && event.status === 'submitted'">
      <div class="action-block">
        <p>No Coordinator was available when this was submitted.</p>
        <button @click="autoAssign">Assign a Coordinator now</button>
      </div>
    </section>

    <!-- Coordinator Actions: Event Review and Approval + Coordinator Assignment + Event Status Management -->
    <section v-if="isAssignedCoordinator">
      <h3 class="section-title">Coordinator Actions</h3>

      <div v-if="event.status === 'under_review'" class="action-block">
        <textarea v-model="comment" placeholder="Comments / reason"></textarea>

        <div class="field-select">
          <span class="detail-label">Allow organiser to edit:</span>
          <div class="checkbox-grid">
            <label v-for="opt in EDITABLE_FIELD_OPTIONS" :key="opt.key" class="checkbox-option">
              <input type="checkbox" :value="opt.key" v-model="editableFields" />
              {{ opt.label }}
            </label>
          </div>
        </div>

        <div v-if="event.clarificationFlag" class="notice">
          <strong>Clarification requested:</strong> {{ event.clarificationComments }}
          <div v-if="event.clarificationEditableFields?.length" class="editable-fields-note">
            Organiser can edit: {{ formatFieldNames(event.clarificationEditableFields) }}
          </div>
        </div>

        <p v-if="clarificationError" class="field-error">{{ clarificationError }}</p>
        <div class="actions">
          <button class="btn btn-butter" @click="clarify">Request Clarification</button>
          <button class="btn btn-mint" @click="approve">Approve</button>
          <button class="btn btn-rose" @click="reject">Reject</button>
          <button class="btn btn-grey" @click="reject">Reassign Coordinator</button>
        </div>
        <p v-if="actionError" class="field-error">{{ actionError }}</p>
      </div>

      <div v-if="showEditForm && ['under_review', 'approved', 'planning'].includes(event.status)" class="action-block">
        <h3 class="block-title">Edit Event Information</h3>
        <div class="edit-event-form">
          <div v-for="field in EVENT_EDIT_FIELD_OPTIONS" :key="field.key" class="edit-field"
            :class="{ 'edit-field-wide': field.type === 'textarea' || field.type === 'checkbox', 'edit-field-inline': field.type === 'checkbox' }">
            <template v-if="field.type === 'checkbox'">
              <label :for="`edit-${field.key}`" class="inline-checkbox-label">
                <input :id="`edit-${field.key}`" type="checkbox" v-model="editForm[field.key]" />
                {{ field.label }}
              </label>
            </template>
            <template v-else>
              <label :for="`edit-${field.key}`">{{ field.label }}</label>
              <textarea v-if="field.type === 'textarea'" :id="`edit-${field.key}`" v-model="editForm[field.key]"
                rows="3"></textarea>
              <input v-else-if="field.type === 'number'" :id="`edit-${field.key}`" type="number" min="1"
                v-model.number="editForm[field.key]" />
              <input v-else :id="`edit-${field.key}`" :type="field.type" v-model="editForm[field.key]" />
            </template>
            <p v-if="editErrors[field.key]" class="field-error">{{ editErrors[field.key] }}</p>
          </div>
        </div>

        <div class="edit-field edit-field-wide">
          <label>Required facilities</label>
          <div v-for="(facility, index) in editForm.required_facilities" :key="index" class="facility-row">
            <input type="text" v-model="editForm.required_facilities[index]" placeholder="e.g. Projector" />
            <button type="button" class="btn btn-grey btn-small"
              @click="editForm.required_facilities.splice(index, 1)">Remove</button>
          </div>
          <button type="button" class="btn btn-grey btn-small" @click="editForm.required_facilities.push('')">+ Add
            facility</button>
          <p v-if="editErrors.required_facilities" class="field-error">{{ editErrors.required_facilities }}</p>
        </div>

        <div class="edit-field edit-field-wide">
          <label>Equipment requirements</label>
          <div v-for="(item, index) in editForm.equipment_requirements" :key="item.id ?? `new-${index}`"
            class="equipment-row">
            <input type="text" v-model="item.type" placeholder="Equipment type" />
            <input type="number" min="1" v-model.number="item.quantity" placeholder="Qty" />
            <input type="text" v-model="item.technicalNotes" placeholder="Technical notes (optional)" />
            <button type="button" class="btn btn-grey btn-small"
              @click="editForm.equipment_requirements.splice(index, 1)">Remove</button>
            <p v-if="editErrors[`equipment_requirements[${index}].type`]" class="field-error">{{
              editErrors[`equipment_requirements[${index}].type`] }}</p>
            <p v-if="editErrors[`equipment_requirements[${index}].quantity`]" class="field-error">{{
              editErrors[`equipment_requirements[${index}].quantity`] }}</p>
          </div>
          <button type="button" class="btn btn-grey btn-small"
            @click="editForm.equipment_requirements.push({ id: null, type: '', quantity: 1, technicalNotes: '' })">+ Add
            equipment requirement</button>
          <p v-if="editErrors.equipment_requirements" class="field-error">{{ editErrors.equipment_requirements }}</p>
        </div>

        <div v-if="editTouchesSignificantField" class="offline-review-callout">
          <label class="checkbox-option">
            <input type="checkbox" v-model="offlineReviewConfirmed" />
            I confirm the offline review for this change has been done
          </label>
          <p class="offline-review-hint">
            You're changing a field that may affect existing venue or equipment arrangements
            (date, time, attendance, capacity, layout, or accessibility needs). Confirm you've
            coordinated this outside the system before saving.
          </p>
        </div>

        <p v-if="editErrors.event" class="field-error">{{ editErrors.event }}</p>

        <div class="actions">
          <button class="btn btn-primary" :disabled="editSubmitting" @click="submitEdit">
            {{ editSubmitting ? "Saving..." : "Save Changes" }}
          </button>
          <button class="btn btn-grey" :disabled="editSubmitting" @click="showEditForm = false">Cancel</button>
        </div>
      </div>




      <div v-if="event.status === 'confirmed'" class="action-block">
        <textarea v-model="comment" placeholder="Reason for reverting to planning"></textarea>
        <div class="actions">
          <button class="btn btn-sky" @click="revertToPlanning">
            Revert to Planning (major change)
          </button>
        </div>
      </div>

      <div v-if="confirmState" class="confirm-overlay">
        <div class="confirm-box">
          <p>{{ confirmState.message }}</p>
          <div class="actions">
            <button class="btn btn-rose" @click="confirmState.onConfirm">Yes, continue</button>
            <button class="btn btn-grey" @click="confirmState.onCancel">Cancel</button>
          </div>
        </div>
      </div>

      <div class="action-block">

        <label>
          Reassign to
          <select v-model.number="newCoordinatorId">
            <option disabled :value="null">Select a coordinator</option>
            <option v-for="c in otherCoordinators" :key="c.id" :value="c.id">{{ c.name }}</option>
          </select>
        </label>
        <div class="actions">
          <button class="btn btn-primary" :disabled="!newCoordinatorId" @click="reassign">Reassign (after offline
            agreement)</button>
        </div>

      </div>
    </section>

    <section v-if="auth.hasRole('safety_officer') && event.status === 'safety_check'">
      <h3 class="section-title">Operational Safety Check</h3>
      <div class="action-block">
        <p class="notice-inline">This event is awaiting your safety check.</p>
        <div class="actions">
          <router-link class="btn btn-primary" :to="`/safety-reviews/${event.id}`">Open safety assessment</router-link>
        </div>
      </div>
    </section>

    <!-- Organiser Actions: Event Review and Approval -->
    <section v-if="isOwningOrganiser">
      <template v-if="canRespondToClarifications && openClarifications.length">
        <h3 class="section-title">Clarification Requests Awaiting Your Response</h3>
        <div v-for="item in openClarifications" :key="item.reviewId" class="action-block">
          <p class="request-question">{{ item.request.comments }}</p>
          <span class="thread-meta">Asked {{ formatDate(item.request.createdAt) }}</span>

          <label class="field-row">
            Your response
            <div>
              <textarea v-model="openResponseForms[item.reviewId].comments"
                placeholder="Explain what you changed, or answer the coordinator's question"></textarea>
            </div>
          </label>

          <template v-if="item.request.editableFields?.length">
            <div v-for="field in EDITABLE_FIELD_OPTIONS.filter((o) => item.request.editableFields.includes(o.key))"
              :key="field.key" class="field-row">
              <label>
                {{ field.label }}
                <input v-if="field.type === 'checkbox'" type="checkbox"
                  v-model="openResponseForms[item.reviewId].fields[field.key]" />
                <textarea v-else-if="field.type === 'textarea'"
                  v-model="openResponseForms[item.reviewId].fields[field.key]"></textarea>
                <input v-else-if="field.type === 'number'" type="number"
                  v-model.number="openResponseForms[item.reviewId].fields[field.key]" />
                <input v-else :type="field.type" v-model="openResponseForms[item.reviewId].fields[field.key]" />
              </label>
            </div>
          </template>
          <p v-else class="notice-inline">
            The coordinator hasn't opened any fields for editing on this request. You can still respond in words.
          </p>

          <p v-if="respondErrors[item.reviewId]" class="field-error">{{ respondErrors[item.reviewId] }}</p>
          <div class="actions">
            <button class="btn btn-primary" @click="respondToItem(item.reviewId)">Send Response</button>
          </div>
        </div>
      </template>
      <div v-if="canRequestChange" class="action-block">
        <template v-if="!showChangeForm">
          <h3 class="block-title">Need to change something?</h3>
          <p class="notice-inline">Your event stays as it is until the coordinator decides on your request.</p>
          <div class="actions">
            <button class="btn btn-primary" @click="openChangeForm">Request a Change</button>
          </div>
        </template>

        <template v-else>
          <h3 class="block-title">Request a Change</h3>
          <p class="notice-inline">Fill in only what you want to change and leave everything else blank.</p>

          <div v-for="field in CHANGE_FIELDS" :key="field.key" class="change-row">
            <span class="detail-label">{{ field.label }}</span>
            <span class="change-current">Current: {{ formatChangeValue(field.key, field.current(event)) }}</span>
            <textarea v-if="field.type === 'textarea'" v-model="changeForm[field.key]"
              placeholder="Proposed value"></textarea>
            <input v-else-if="field.type === 'number'" v-model.number="changeForm[field.key]" type="number" min="1"
              placeholder="Proposed value" />
            <input v-else v-model="changeForm[field.key]" :type="field.type" placeholder="Proposed value" />
            <p v-if="changeErrors[field.key]" class="field-error">{{ changeErrors[field.key] }}</p>
          </div>

          <div class="change-row">
            <span class="detail-label">Venue</span>
            <span class="change-current">Current: {{ currentVenueLabel }}</span>
            <select v-model="changeForm.venue_id">
              <option value="">Keep current venue</option>
              <option v-for="venue in venues" :key="venue.id" :value="venue.id">
                {{ venue.name }} (capacity {{ venue.capacity }})
              </option>
            </select>
            <p v-if="changeErrors.venue_id" class="field-error">{{ changeErrors.venue_id }}</p>
          </div>

          <div class="change-row">
            <span class="detail-label">Equipment</span>
            <span class="change-current">Current: {{ currentEquipmentLabel }}</span>
            <button v-if="changeEquipment === null" type="button" class="btn btn-grey btn-small"
              @click="startEquipmentChange">
              Change equipment
            </button>
            <template v-else>
              <div v-for="(item, index) in changeEquipment" :key="index" class="equipment-row">
                <select v-model="item.type">
                  <option value="" disabled>Choose equipment</option>
                  <option v-if="item.type && !equipmentCatalogue.some((e) => e.name === item.type)" :value="item.type">
                    {{ item.type }} (not in catalogue)
                  </option>
                  <option v-for="entry in equipmentCatalogue" :key="entry.id" :value="entry.name">
                    {{ entry.name }}
                  </option>
                </select>
                <input v-model.number="item.quantity" type="number" min="1" />
                <button type="button" class="btn btn-grey btn-small" @click="removeEquipmentRow(index)">Remove</button>
              </div>
              <div class="actions">
                <button type="button" class="btn btn-grey btn-small" @click="addEquipmentRow">Add item</button>
                <button type="button" class="btn btn-grey btn-small" @click="changeEquipment = null">Keep current
                  equipment</button>
              </div>
            </template>
            <p v-if="changeErrors.equipment_requirements" class="field-error">{{ changeErrors.equipment_requirements }}
            </p>
          </div>

          <label class="field-row">
            Reason for the change
            <textarea v-model="changeReason" placeholder="Why do you need this change?"></textarea>
          </label>
          <p v-if="changeErrors.reason" class="field-error">{{ changeErrors.reason }}</p>
          <p v-if="changeErrors.changes" class="field-error">{{ changeErrors.changes }}</p>
          <p v-if="changeErrors.event" class="field-error">{{ changeErrors.event }}</p>

          <div class="actions">
            <button class="btn btn-primary" :disabled="changeSubmitting" @click="submitChangeRequest">Submit Change
              Request</button>
            <button class="btn btn-grey" :disabled="changeSubmitting" @click="showChangeForm = false">Cancel</button>
          </div>
        </template>
      </div>

      <div v-if="canRequestWithdrawal" class="action-block">
        <template v-if="!showWithdrawalForm">
          <h3 class="block-title">No longer need this event?</h3>
          <p class="notice-inline">Ask the coordinator to withdraw it. Your event stays as it is until they decide.</p>
          <div class="actions">
            <button class="btn btn-grey" @click="openWithdrawalForm">Request Withdrawal</button>
          </div>
        </template>

        <template v-else>
          <h3 class="block-title">Request Withdrawal</h3>
          <label class="field-row">
            Reason for withdrawing
            <textarea v-model="withdrawalReason" placeholder="Why do you want to withdraw this event?"></textarea>
          </label>
          <p v-if="withdrawalErrors.reason" class="field-error">{{ withdrawalErrors.reason }}</p>
          <p v-if="withdrawalErrors.request" class="field-error">{{ withdrawalErrors.request }}</p>
          <p v-if="withdrawalErrors.event" class="field-error">{{ withdrawalErrors.event }}</p>
          <div class="actions">
            <button class="btn btn-rose" :disabled="withdrawalSubmitting" @click="submitWithdrawalRequest">
              Submit Withdrawal Request
            </button>
            <button class="btn btn-grey" :disabled="withdrawalSubmitting"
              @click="showWithdrawalForm = false">Cancel</button>
          </div>
        </template>
      </div>

      <div v-if="event.status === 'rejected' && event.canResubmit" class="action-block">
        <h3 class="block-title">Revise and Resubmit</h3>
        <p class="notice-inline">Update the details below, then resubmit for review.</p>

        <label class="field-row">
          Event name
          <p></p>
          <input v-model="revisionForm.name" />
        </label>
        <label class="field-row">
          Purpose
          <p></p>
          <input v-model="revisionForm.purpose" />
        </label>
        <label class="field-row">
          Description
          <p></p>
          <textarea v-model="revisionForm.description"></textarea>
        </label>
        <label class="field-row">
          Proposed date
          <p></p>
          <input v-model="revisionForm.proposed_date" type="date" />
        </label>
        <label class="field-row">
          Proposed time
          <p></p>
          <input v-model="revisionForm.proposed_time" type="time" />
        </label>
        <label class="field-row">
          Expected attendance
          <p></p>
          <input v-model.number="revisionForm.expected_attendance" type="number" min="1" />
        </label>
        <label class="field-row">
          Equipment Required
          <p></p>
          <input v-model.number="revisionForm.capacity_needed" type="number" min="1" />
        </label>
        <label class="field-row">
          Venue Required
          <p></p>
          <input v-model="revisionForm.required_layout" />
        </label>
        <label class="field-row">
          Accessibility needs
          <p></p>
          <textarea v-model="revisionForm.accessibility_needs"></textarea>
        </label>
        <label class="checkbox-option">
          <input v-model="revisionForm.registration_required" type="checkbox" />
          Registration required
        </label>

        <p v-if="revisionError" class="field-error">{{ revisionError }}</p>
        <div class="actions">
          <button class="btn btn-primary" @click="resubmit">Resubmit for Review</button>
        </div>
      </div>
      <div v-else-if="event.status === 'rejected' && !event.canResubmit" class="action-block">
        <h3 class="block-title">Revise and Resubmit</h3>
        <p class="notice-inline">
          This request has already been resubmitted. Open the latest resubmission from your Dashboard to see its status.
        </p>
      </div>
    </section>
  </div>
  <p v-else class="loading">Loading…</p>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { useAuthStore } from "../stores/auth";
import eventsApi from "../api/events";
import usersApi from "../api/users";
import { useConfirm } from "../composables/useConfirm";
import changeRequestsApi from "../api/changeRequests";

const route = useRoute();
const router = useRouter();
const auth = useAuthStore();

const event = ref(null);
const comment = ref("");
const responseNotes = ref("");
const newCoordinatorId = ref(null);
const coordinators = ref([]);

const clarificationError = ref("");
const reviewHistory = ref([]);

const confirmState = ref(null); // { message, onConfirm, onCancel }
const actionError = ref("");
const { confirm } = useConfirm();

const safetyFactors = [
  { key: "expected_attendance", label: "Expected attendance" },
  { key: "venue_capacity", label: "Venue capacity" },
  { key: "venue_layout", label: "Venue layout" },
  { key: "emergency_access", label: "Emergency access" },
  { key: "accessibility", label: "Accessibility requirements" },
  { key: "equipment_placement", label: "Equipment placement" },
  { key: "crowd_movement", label: "Crowd movement" },
  { key: "venue_restrictions", label: "Known venue restrictions" },
];
const SAFETY_FACTOR_LABELS = Object.fromEntries(safetyFactors.map((f) => [f.key, f.label]));

const latestSafetyReview = computed(() => event.value?.safetyReviews?.at(-1) || null);

function safetyDecisionHeading(decision) {
  if (decision === "approved") return "Safety approved: cleared for preparation";
  if (decision === "rejected") return "Safety arrangement rejected: returned to planning";
  return "Safety changes requested: returned to planning";
}

function formatSafetyFactors(keys) {
  return keys.map((key) => SAFETY_FACTOR_LABELS[key] || key).join(", ");
}

function formatArrangements(keys) {
  return keys.map((key) => key.charAt(0).toUpperCase() + key.slice(1)).join(" and ");
}

const EDITABLE_FIELD_OPTIONS = [
  { key: "name", label: "Event name", type: "text" },
  { key: "purpose", label: "Purpose", type: "text" },
  { key: "description", label: "Description", type: "textarea" },
  { key: "proposed_date", label: "Proposed date", type: "date" },
  { key: "proposed_time", label: "Proposed time", type: "time" },
  { key: "expected_attendance", label: "Expected attendance", type: "number" },
  { key: "capacity_needed", label: "Equipment Required", type: "number" },
  { key: "required_layout", label: "Venue Required", type: "text" },
  { key: "accessibility_needs", label: "Accessibility needs", type: "textarea" },
  { key: "registration_required", label: "Registration required", type: "checkbox" },
];

const EVENT_EDIT_FIELD_OPTIONS = [
  { key: "name", label: "Event name", type: "text" },
  { key: "purpose", label: "Purpose", type: "text" },
  { key: "description", label: "Description", type: "textarea" },
  { key: "category", label: "Category", type: "text" },
  { key: "proposed_date", label: "Proposed date", type: "date" },
  { key: "proposed_time", label: "Proposed time", type: "time" },
  { key: "expected_attendance", label: "Expected attendance", type: "number" },
  { key: "capacity_needed", label: "Capacity needed", type: "number" },
  { key: "required_layout", label: "Required layout", type: "text" },
  { key: "accessibility_needs", label: "Accessibility needs", type: "textarea" },
  { key: "registration_required", label: "Registration required", type: "checkbox" },
  { key: "intended_capacity", label: "Intended capacity (registration cap)", type: "number" },

];

const editableFields = ref([]);       // coordinator's selection when requesting clarification

// "under_review" -> "under review"
const statusLabel = (status) => {
  const labels = {
    re_review: "Under re-review",
  };
  return labels[status] || String(status || "")
    .replace(/_/g, " ")
    .replace(/^./, (c) => c.toUpperCase());
};

const isAssignedCoordinator = computed(
  () => auth.hasRole("event_coordinator") && event.value?.coordinatorId === auth.user?.id
);
const isOwningOrganiser = computed(
  () => auth.hasRole("event_organiser") && event.value?.organiserId === auth.user?.id
);
// Exclude yourself — reassigning "to" the coordinator who already owns it is a no-op the backend rejects anyway.
const otherCoordinators = computed(() => coordinators.value.filter((c) => c.id !== auth.user?.id));

const clarificationThread = ref([]);
const openResponseForms = reactive({}); // keyed by reviewId -> { comments, fields }
const respondErrors = reactive({});     // keyed by reviewId -> error string

const canRespondToClarifications = computed(
  () => !["approved", "rejected", "cancelled"].includes(event.value?.status)
);

const openClarifications = computed(() =>
  clarificationThread.value.filter((item) => item.response === null && !item.withdrawn)
);

const priorDecisions = ref([]);
const revisionForm = reactive({
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
});
const revisionError = ref("");

// ---- Event change requests ----
const changeRequests = ref([]);
const canRequestChange = ref(false);
const currentVenueId = ref(null);
const venues = ref([]);
const equipmentCatalogue = ref([]);
const showChangeForm = ref(false);
const changeForm = reactive({}); // only fields that have a value are sent
const changeEquipment = ref(null); // null = keep the current equipment
const changeReason = ref("");
const changeErrors = ref({}); // field -> message from the server
const changeSubmitting = ref(false);

// ---- Event withdrawal requests ----
const canRequestWithdrawal = ref(false);
const showWithdrawalForm = ref(false);
const withdrawalReason = ref("");
const withdrawalErrors = ref({});
const withdrawalSubmitting = ref(false);

const CHANGE_FIELDS = [
  { key: "proposed_date", label: "Date", type: "date", current: (e) => e.proposedDate },
  { key: "proposed_time", label: "Time", type: "time", current: (e) => e.proposedTime },
  { key: "expected_attendance", label: "Expected attendance", type: "number", current: (e) => e.expectedAttendance },
  { key: "capacity_needed", label: "Equipment Required", type: "number", current: (e) => e.venueRequirements?.capacityNeeded },
  { key: "required_layout", label: "Venue Required", type: "text", current: (e) => e.venueRequirements?.requiredLayout },
  { key: "accessibility_needs", label: "Accessibility needs", type: "textarea", current: (e) => e.venueRequirements?.accessibilityNeeds },
  { key: "name", label: "Event name", type: "text", current: (e) => e.name },
  { key: "description", label: "Description", type: "textarea", current: (e) => e.description },
];

const CHANGE_LABELS = {
  ...Object.fromEntries(CHANGE_FIELDS.map((f) => [f.key, f.label])),
  venue_id: "Venue",
  equipment_requirements: "Equipment",
};

const venueName = (id) => venues.value.find((v) => v.id === id)?.name || (id ? `Venue #${id}` : "None");

function formatChangeValue(key, value) {
  if (value === null || value === undefined || value === "") return "—";
  if (key === "venue_id") return venueName(value);
  if (key === "equipment_requirements") {
    return value.length ? value.map((i) => `${i.quantity} × ${i.type}`).join(", ") : "None";
  }
  if (key === "proposed_time") return String(value).slice(0, 5);
  return Array.isArray(value) ? value.join(", ") : String(value);
}

const currentVenueLabel = computed(() => (currentVenueId.value ? venueName(currentVenueId.value) : "—"));
const currentEquipmentLabel = computed(() =>
  formatChangeValue(
    "equipment_requirements",
    (event.value?.equipmentRequirements || []).map((e) => ({ type: e.type, quantity: e.quantity }))
  )
);

async function ensureCatalogue() {
  if (venues.value.length || equipmentCatalogue.value.length) return;
  try {
    const { data } = await changeRequestsApi.getCatalogue();
    venues.value = data.venues || [];
    equipmentCatalogue.value = data.equipment || [];
  } catch (e) {
    console.error("Could not load the catalogue", e.response?.status, e.response?.data || e);
  }
}

async function loadChangeRequests() {
  try {
    if (isOwningOrganiser.value) {
      const { data } = await changeRequestsApi.getForEvent(event.value.id);
      canRequestChange.value = data.canRequestChange;
      canRequestWithdrawal.value = data.canRequestWithdrawal;
      currentVenueId.value = data.currentVenueId ?? null;
      changeRequests.value = data.requests || [];
    } else if (isAssignedCoordinator.value) {
      const { data } = await changeRequestsApi.listAssigned();
      changeRequests.value = data.filter((r) => r.eventId === event.value.id).sort((a, b) => b.id - a.id);
      canRequestChange.value = false;
      canRequestWithdrawal.value = false;
    } else {
      changeRequests.value = [];
      canRequestChange.value = false;
      canRequestWithdrawal.value = false;
    }
  } catch (e) {
    changeRequests.value = [];
    canRequestChange.value = false;
    canRequestWithdrawal.value = false;
  }
  if (changeRequests.value.some((r) => r.requestedChanges?.venue_id)) await ensureCatalogue();
}

function resetChangeForm() {
  for (const field of CHANGE_FIELDS) changeForm[field.key] = field.type === "number" ? null : "";
  changeForm.venue_id = "";
  changeEquipment.value = null;
  changeReason.value = "";
  changeErrors.value = {};
}

async function openChangeForm() {
  await ensureCatalogue();
  resetChangeForm();
  showChangeForm.value = true;
}

function startEquipmentChange() {
  changeEquipment.value = (event.value.equipmentRequirements || []).map((e) => ({
    type: e.type,
    quantity: e.quantity,
  }));
}
const addEquipmentRow = () => changeEquipment.value.push({ type: "", quantity: 1 });
const removeEquipmentRow = (index) => changeEquipment.value.splice(index, 1);

function buildChanges() {
  const changes = {};
  for (const field of CHANGE_FIELDS) {
    const value = changeForm[field.key];
    if (value !== "" && value !== null && value !== undefined) changes[field.key] = value;
  }
  if (changeForm.venue_id !== "") changes.venue_id = changeForm.venue_id;
  if (changeEquipment.value !== null) changes.equipment_requirements = changeEquipment.value;
  return changes;
}

async function submitChangeRequest() {
  changeErrors.value = {};
  const confirmed = await confirm(
    "Submit this change request? Your event stays exactly as it is until the coordinator decides."
  );
  if (!confirmed) return;

  changeSubmitting.value = true;
  try {
    await changeRequestsApi.submit(event.value.id, { changes: buildChanges(), reason: changeReason.value });
    showChangeForm.value = false;
    resetChangeForm();
    await load();
  } catch (e) {
    const data = e.response?.data;
    changeErrors.value = data?.errors || { event: data?.error || "Could not submit the change request." };
  } finally {
    changeSubmitting.value = false;
  }
}

function openWithdrawalForm() {
  withdrawalReason.value = "";
  withdrawalErrors.value = {};
  showWithdrawalForm.value = true;
}

async function submitWithdrawalRequest() {
  withdrawalErrors.value = {};
  const confirmed = await confirm(
    "Ask the coordinator to withdraw this event? Nothing changes until they decide."
  );
  if (!confirmed) return;

  withdrawalSubmitting.value = true;
  try {
    await changeRequestsApi.requestWithdrawal(event.value.id, { reason: withdrawalReason.value });
    showWithdrawalForm.value = false;
    await load();
  } catch (e) {
    const data = e.response?.data;
    withdrawalErrors.value = data?.errors || { event: data?.error || "Could not submit the withdrawal request." };
  } finally {
    withdrawalSubmitting.value = false;
  }
}

const formatFieldNames = (keys) =>
  (keys || []).map((k) => EDITABLE_FIELD_OPTIONS.find((o) => o.key === k)?.label || k).join(", ");

// The API sends naive UTC timestamps (see backend app/common/time.py); mark
// them as UTC so the browser shows the viewer's local time, not UTC as local.
const formatDate = (iso) => {
  if (!iso) return "";
  const text = String(iso);
  return new Date(/(?:Z|[+-]\d{2}:\d{2})$/i.test(text) ? text : `${text}Z`).toLocaleString();
};

async function load() {
  const { data } = await eventsApi.getEvent(route.params.id);
  event.value = data;
  initRevisionForm();

  try {
    const { data: outcome } = await eventsApi.getOutcome(route.params.id);
    reviewHistory.value = outcome.reviewHistory || [];
    clarificationThread.value = outcome.clarificationThread || [];
    priorDecisions.value = outcome.priorDecisions || [];
  } catch (e) {
    reviewHistory.value = [];
    clarificationThread.value = [];
    priorDecisions.value = [];
  }

  clarificationThread.value.filter((item) => item.response === null).forEach(ensureResponseForm);
  await loadChangeRequests();
}

async function loadCoordinators() {
  const { data } = await usersApi.listCoordinators();
  coordinators.value = data;
}

async function clarify() {
  clarificationError.value = "";
  try {
    await eventsApi.requestClarification(event.value.id, comment.value, editableFields.value);
    comment.value = "";
    editableFields.value = [];
    await load();
  } catch (e) {
    clarificationError.value = e.response?.data?.error || "Could not request clarification.";
  }
}

function ensureResponseForm(item) {
  if (openResponseForms[item.reviewId]) return;
  const source = {
    name: event.value.name,
    purpose: event.value.purpose,
    description: event.value.description,
    proposed_date: event.value.proposedDate,
    proposed_time: event.value.proposedTime,
    expected_attendance: event.value.expectedAttendance,
    capacity_needed: event.value.venueRequirements?.capacityNeeded,
    required_layout: event.value.venueRequirements?.requiredLayout,
    accessibility_needs: event.value.venueRequirements?.accessibilityNeeds,
    registration_required: event.value.registrationRequired,
  };
  const fields = {};
  (item.request.editableFields || []).forEach((key) => {
    fields[key] = source[key] ?? (key === "registration_required" ? false : "");
  });
  openResponseForms[item.reviewId] = { comments: "", fields };
}

function initRevisionForm() {
  if (event.value?.status !== "rejected") return;
  revisionForm.name = event.value.name || "";
  revisionForm.purpose = event.value.purpose || "";
  revisionForm.description = event.value.description || "";
  revisionForm.proposed_date = event.value.proposedDate || "";
  revisionForm.proposed_time = event.value.proposedTime || "";
  revisionForm.expected_attendance = event.value.expectedAttendance;
  revisionForm.capacity_needed = event.value.venueRequirements?.capacityNeeded;
  revisionForm.required_layout = event.value.venueRequirements?.requiredLayout;
  revisionForm.accessibility_needs = event.value.venueRequirements?.accessibilityNeeds;
  revisionForm.registration_required = event.value.registrationRequired;
}

const SIGNIFICANT_FIELD_KEYS = [
  "proposed_date", "proposed_time", "expected_attendance",
  "capacity_needed", "required_layout", "accessibility_needs",
  "required_facilities", "equipment_requirements",
];

function valuesEqual(a, b) {
  if (Array.isArray(a) || Array.isArray(b) || (typeof a === "object" && a !== null) || (typeof b === "object" && b !== null)) {
    return JSON.stringify(a) === JSON.stringify(b);
  }
  return a === b;
}

const showEditForm = ref(false);
const editForm = reactive({});
const editErrors = ref({});
const editSubmitting = ref(false);
const offlineReviewConfirmed = ref(false);

const editTouchesSignificantField = computed(() =>
  SIGNIFICANT_FIELD_KEYS.some((key) => !valuesEqual(editForm[key], initialEditValues[key]))
);

let initialEditValues = {};

function openEditForm() {
  const source = {
    name: event.value.name,
    purpose: event.value.purpose,
    description: event.value.description,
    category: event.value.category,
    proposed_date: event.value.proposedDate,
    proposed_time: event.value.proposedTime,
    expected_attendance: event.value.expectedAttendance,
    capacity_needed: event.value.venueRequirements?.capacityNeeded,
    required_layout: event.value.venueRequirements?.requiredLayout,
    accessibility_needs: event.value.venueRequirements?.accessibilityNeeds,
    registration_required: event.value.registrationRequired,
    intended_capacity: event.value.intendedCapacity,
    required_facilities: [...(event.value.venueRequirements?.requiredFacilities || [])],
    equipment_requirements: (event.value.equipmentRequirements || []).map((item) => ({
      id: item.id,
      type: item.equipmentType ?? item.type,
      quantity: item.quantity,
      technicalNotes: item.technicalNotes ?? "",
    })),
  };
  Object.keys(editForm).forEach((key) => delete editForm[key]);
  Object.assign(editForm, source);
  initialEditValues = JSON.parse(JSON.stringify(source));
  editErrors.value = {};
  offlineReviewConfirmed.value = false;
  showEditForm.value = true;
}

function buildChangedFields() {
  const changed = {};
  for (const key of Object.keys(editForm)) {
    let value = editForm[key];

    if (key === "required_facilities" && Array.isArray(value)) {
      value = value.map((v) => String(v || "").trim()).filter(Boolean);
    }

    if (key === "equipment_requirements" && Array.isArray(value)) {
      value = value
        .filter((item) => (item.type && item.type.trim()) || item.id != null)
        .map((item) => ({
          ...(item.id != null ? { id: item.id } : {}),
          type: (item.type || "").trim(),
          quantity: item.quantity,
          technicalNotes: (item.technicalNotes || "").trim() || undefined,
        }));
    }

    if (!valuesEqual(value, initialEditValues[key])) {
      changed[key] = value;
    }
  }
  return changed;
}

async function submitEdit() {
  editErrors.value = {};
  const changedFields = buildChangedFields();
  if (Object.keys(changedFields).length === 0) {
    showEditForm.value = false;
    return; // nothing to save
  }
  editSubmitting.value = true;
  try {
    await eventsApi.updateEvent(event.value.id, {
      fields: changedFields,
      offlineReviewConfirmed: offlineReviewConfirmed.value,
    });
    showEditForm.value = false;
    await load();
  } catch (e) {
    const data = e.response?.data;
    if (e.response?.status === 423) {
      editErrors.value = { event: data?.error || "This event is confirmed and can no longer be edited directly." };
    } else {
      editErrors.value = data?.errors || { event: data?.error || "Could not save changes." };
    }
  } finally {
    editSubmitting.value = false;
  }
}

function requestActionWithConfirmation(callWithConfirmed) {
  return new Promise((resolve, reject) => {
    callWithConfirmed(false)
      .then(({ data }) => resolve(data))
      .catch((e) => {
        if (e.response?.status === 409 && e.response.data?.requiresConfirmation) {
          confirmState.value = {
            message: e.response.data.message,
            onConfirm: () => {
              confirmState.value = null;
              callWithConfirmed(true)
                .then(({ data }) => resolve(data))
                .catch(reject);
            },
            onCancel: () => {
              confirmState.value = null;
              resolve(null);
            },
          };
        } else {
          reject(e);
        }
      });
  });
}

async function respondToItem(reviewId) {
  respondErrors[reviewId] = "";
  const form = openResponseForms[reviewId];
  try {
    await eventsApi.respondClarification(event.value.id, {
      reviewId,
      comments: form.comments,
      ...form.fields,
    });
    delete openResponseForms[reviewId];
    delete respondErrors[reviewId];
    await load();
  } catch (e) {
    respondErrors[reviewId] = e.response?.data?.error || "Could not send response.";
  }
}

async function approve() {
  actionError.value = "";
  try {
    const data = await requestActionWithConfirmation((confirmed) =>
      eventsApi.approveEvent(event.value.id, comment.value, confirmed)
    );
    if (data) {
      comment.value = "";
      await load();
    }
  } catch (e) {
    actionError.value = e.response?.data?.error || "Could not approve this request.";
  }
}

async function reject() {
  actionError.value = "";
  try {
    const data = await requestActionWithConfirmation((confirmed) =>
      eventsApi.rejectEvent(event.value.id, comment.value, confirmed)
    );
    if (data) {
      comment.value = "";
      await load();
    }
  } catch (e) {
    actionError.value = e.response?.data?.error || "Could not reject this request.";
  }
}

async function cancelEvent() {
  actionError.value = "";
  try {
    const data = await requestActionWithConfirmation((confirmed) =>
      eventsApi.cancelEvent(event.value.id, comment.value, confirmed)
    );
    if (data) {
      comment.value = "";
      await load();
    }
  } catch (e) {
    actionError.value = e.response?.data?.error || "Could not cancel this event.";
  }
}

async function deleteClarificationRequest(reviewId) {
  actionError.value = "";

  const confirmed = await confirm(
    "Delete this clarification request? The organiser will no longer be able to respond to it."
  );
  if (!confirmed) return;

  try {
    await eventsApi.deleteClarification(event.value.id, reviewId);
    await load();
  } catch (e) {
    actionError.value = e.response?.data?.error || "Could not delete this clarification request.";
  }
}

async function revertToPlanning() {
  const confirmed = await confirm(
    "Revert this confirmed event back to Planning? This should only be done for a major change."
  );
  if (!confirmed) return;

  await eventsApi.changeStatus(event.value.id, "planning", comment.value);
  comment.value = "";
  await load();
}

async function reassign() {
  if (!newCoordinatorId.value) return;

  const confirmed = await confirm("Reassign this event to the selected coordinator?");
  if (!confirmed) return;

  await eventsApi.reassign(event.value.id, newCoordinatorId.value);
  newCoordinatorId.value = null;
  await load();
}

async function resubmit() {
  revisionError.value = "";

  const confirmed = await confirm("Resubmit this request for review with your changes?");
  if (!confirmed) return;

  try {
    const { data } = await eventsApi.resubmitEvent(event.value.id, { ...revisionForm });
    router.push(`/events/${data.id}`);
  } catch (e) {
    revisionError.value = e.response?.data?.error || "Could not resubmit this request.";
  }
}

async function autoAssign() {
  await eventsApi.autoAssign(event.value.id);
  await load();
}

onMounted(async () => {
  await load();
  // /auth/users is coordinator-only server-side; only fetch it if this
  // viewer actually has that role, to avoid a needless 403.
  if (auth.hasRole("event_coordinator")) {
    await loadCoordinators();
  }
});
</script>

<style scoped>
.page-title {
  margin: 0;
  font-size: 1.5rem;
  font-weight: 600;
  color: var(--text, #2d2a4a);
}

.section-title {
  margin: 1.5rem 0 0;
  font-size: 1.1rem;
  font-weight: 600;
  color: var(--text, #2d2a4a);
}

.block-title {
  margin: 0;
  font-size: 1rem;
  font-weight: 600;
  color: var(--text, #2d2a4a);
}

.loading {
  color: var(--text-muted, #6b6890);
}

.history-list {
  list-style: none;
  margin: 0.5rem 0 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.history-list li {
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
  padding: 0.6rem 0.75rem;
  border-radius: 10px;
  background: var(--sky-bg, #d6ecff);
}

.history-date {
  font-size: 0.75rem;
  color: var(--sky-text, #1f5f99);
}

.history-comment {
  color: var(--text, #2d2a4a);
}

.field-error {
  margin: 0;
  color: var(--rose-text, #a12b47);
  font-size: 0.85rem;
}

.field-select {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
}

.checkbox-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
  gap: 0.4rem 1rem;
}

.checkbox-option {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.85rem;
  font-weight: 400;
}

.field-row label {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  font-size: 0.85rem;
  font-weight: 500;
  color: var(--text, #2d2a4a);
}

.editable-fields-note {
  margin-top: 0.35rem;
  font-size: 0.85rem;
  font-weight: 500;
}

.edit-event-form {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 1rem 1.25rem;
  margin: 0.75rem 0 1rem;
  align-items: start;
}

.edit-field {
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
}

.edit-field-inline {
  flex-direction: row;
  align-items: center;
  gap: 0.5rem;
}

.inline-checkbox-label {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-weight: 600;
  font-size: 0.85rem;
}

.edit-field-wide {
  grid-column: 1 / -1;
}

.edit-field label {
  font-weight: 600;
  font-size: 0.85rem;
}

.edit-field input[type="text"],
.edit-field input[type="date"],
.edit-field input[type="time"],
.edit-field input[type="number"],
.edit-field textarea {
  box-sizing: border-box;
  width: 100%;
  padding: 0.55rem 0.7rem;
  border: 1px solid var(--border, #e4defa);
  border-radius: 8px;
  font: inherit;
}

.facility-row,
.equipment-row {
  display: flex;
  gap: 0.5rem;
  align-items: center;
  margin-bottom: 0.5rem;
}

.facility-row input,
.equipment-row input {
  flex: 1;
}


.edit-field textarea {
  resize: vertical;
}

.edit-checkbox {
  width: 1rem;
  height: 1rem;
  align-self: flex-start;
}

.offline-review-callout {
  background: var(--butter-bg, #fef3c7);
  border: 1px solid #f3d98b;
  border-radius: 10px;
  padding: 0.85rem 1rem;
  margin-bottom: 1rem;
}

.offline-review-callout .checkbox-option {
  font-weight: 600;
  margin-bottom: 0.3rem;
}

.offline-review-hint {
  margin: 0;
  font-size: 0.82rem;
  color: var(--text-muted, #6b6890);
}

@media (max-width: 560px) {
  .edit-event-form {
    grid-template-columns: 1fr;
  }
}

.notice-inline {
  margin: 0;
  font-size: 0.9rem;
  color: var(--text-muted, #6b6890);
}

.thread-list {
  list-style: none;
  margin: 0.5rem 0 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.thread-item {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
  padding-bottom: 0.6rem;
  border-bottom: 1px solid var(--border, #e4defa);
}

.thread-item:last-child {
  border-bottom: none;
  padding-bottom: 0;
}

.thread-message {
  padding: 0.6rem 0.75rem;
  border-radius: 10px;
}

.thread-message.request {
  background: var(--butter-bg, #fff1c2);
}

.thread-message.response {
  background: var(--sky-bg, #d6ecff);
  margin-left: 1rem;
}

.thread-message p {
  margin: 0.2rem 0 0;
  color: var(--text, #2d2a4a);
}

.thread-meta {
  font-size: 0.75rem;
  font-weight: 600;
  opacity: 0.75;
}

.thread-fields {
  font-size: 0.8rem;
  font-style: italic;
}

.thread-pending {
  margin-left: 1rem;
  font-size: 0.85rem;
  color: var(--text-muted, #6b6890);
}

.confirm-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.4);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 50;
}

.confirm-box {
  background: #fff;
  border-radius: 12px;
  padding: 1.25rem 1.5rem;
  max-width: 360px;
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.thread-withdrawn {
  margin-left: 1rem;
  font-size: 0.85rem;
  font-style: italic;
  color: var(--text-muted, #6b6890);
}

.thread-pending {
  margin-left: 1rem;
  display: flex;
  align-items: center;
  gap: 0.75rem;
  font-size: 0.85rem;
  color: var(--text-muted, #6b6890);
}

.btn-small {
  padding: 0.2rem 0.6rem;
  font-size: 0.8rem;
}

.notice.approved {
  background: var(--mint-bg, #d3f5e3);
  color: var(--mint-text, #1e6b47);
}

.notice.rejected {
  background: var(--rose-bg, #fbdcdc);
  color: var(--rose-text, #a12b47);
}

.decision-meta {
  margin: 0.25rem 0 0;
  font-size: 0.85rem;
  font-weight: 400;
  opacity: 0.85;
}

.decision-reason {
  margin: 0.35rem 0 0;
  font-weight: 400;
}

.thread-message.approved {
  background: var(--mint-bg, #d3f5e3);
}

.thread-message.rejected {
  background: var(--rose-bg, #fbdcdc);
}

/* Summary card */
.card {
  padding: 1.25rem 1.5rem;
  background: var(--surface, #ffffff);
  border: 1px solid var(--border, #e4defa);
  border-radius: 14px;
  box-shadow: 0 4px 16px rgba(109, 91, 208, 0.08);
}

.title-row {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 0.75rem;
}

.title-row .badge {
  padding: 0.3rem 0.9rem;
  font-size: 0.95rem;
}

.description {
  margin: 0.75rem 0 1rem;
  line-height: 1.5;
  color: var(--text, #2d2a4a);
}

.details {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 0.75rem;
}

.detail {
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
  padding: 0.7rem 0.9rem;
  border-radius: 12px;
  background: var(--sky-bg, #d6ecff);
  color: var(--sky-text, #1f5f99);
  font-weight: 500;
}

.detail-label {
  font-size: 0.8rem;
  font-weight: 400;
}

.reg-pill {
  display: inline-block;
  padding: 0.1rem 0.6rem;
  border-radius: 999px;
  font-size: 0.85rem;
  font-weight: 600;
  background: #e2e5ea;
  color: #55585e;
  width: fit-content;
}

.reg-pill.required {
  background: var(--mint-bg, #d3f5e3);
  color: var(--mint-text, #1e6b47);
}

.accessibility {
  margin-top: 0.85rem;
  padding-top: 0.85rem;
  border-top: 1px solid var(--border, #e4defa);
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.accessibility p {
  margin: 0;
  color: var(--text, #2d2a4a);
  line-height: 1.5;
}

.request-question {
  margin: 0;
  font-weight: 600;
  color: var(--text, #2d2a4a);
}

/* Status badges */
.badge {
  display: inline-block;
  padding: 0.15rem 0.65rem;
  border-radius: 999px;
  background: var(--lilac-bg, #e9e5fb);
  color: var(--lilac-text, #4b3fa0);
  font-size: 0.8rem;
  font-weight: 500;
  text-transform: capitalize;
  white-space: nowrap;
}

.badge.approved,
.badge.confirmed,
.badge.completed {
  background: var(--mint-bg, #d3f5e3);
  color: var(--mint-text, #1e6b47);
}

.badge.rejected,
.badge.cancelled {
  background: var(--rose-bg, #ffdce3);
  color: var(--rose-text, #a12b47);
}

.badge.under_review,
.badge.submitted {
  background: var(--butter-bg, #fff1c2);
  color: var(--butter-text, #8a5a00);
}

.badge.planning {
  background: var(--sky-bg, #d6ecff);
  color: var(--sky-text, #1f5f99);
}

/* Notices */
.notice {
  margin: 1rem 0;
  padding: 0.85rem 1rem;
  border-radius: 12px;
  background: var(--butter-bg, #fff1c2);
  color: var(--butter-text, #8a5a00);
}

.notice.error {
  background: var(--rose-bg, #ffdce3);
  color: var(--rose-text, #a12b47);
}

/* Action blocks */
.action-block {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  margin: 0.75rem 0 0;
  padding: 1.1rem 1.25rem;
  background: var(--surface, #ffffff);
  border: 1px solid var(--border, #e4defa);
  border-radius: 14px;
  box-shadow: 0 4px 16px rgba(109, 91, 208, 0.06);
}

.detail-block {
  margin: 1rem 0;
  padding: 1rem;
  background: #fafafa;
  border: 1px solid #eee;
  border-radius: 6px;
}

.detail-block h3 {
  margin-top: 0;
}

.detail-block ul {
  margin: 0;
  padding-left: 1.25rem;
}

.actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}

textarea,
input {
  padding: 0.6rem 0.75rem;
  border: 1px solid var(--border, #e4defa);
  border-radius: 10px;
  background: #fcfbff;
  color: var(--text, #2d2a4a);
  font: inherit;
}

textarea::placeholder,
input::placeholder {
  color: #a5a2c2;
}

textarea:focus,
input:focus {
  outline: none;
  border-color: var(--primary, #6d5bd0);
  background: #ffffff;
  box-shadow: 0 0 0 3px var(--primary-tint, #ebe7ff);
}

textarea {
  min-height: 4.5rem;
  resize: vertical;
}

/* Buttons: colour matches meaning */
.btn {
  padding: 0.5rem 1.1rem;
  border: none;
  border-radius: 999px;
  font: inherit;
  font-size: 0.9rem;
  font-weight: 500;
  cursor: pointer;
}

.btn:focus-visible {
  outline: 2px solid var(--primary, #6d5bd0);
  outline-offset: 2px;
}

.btn-primary {
  background: var(--primary, #6d5bd0);
  color: #ffffff;
}

.btn-primary:hover {
  background: var(--primary-hover, #5b49bd);
}

.btn-mint {
  background: var(--mint-bg, #d3f5e3);
  color: var(--mint-text, #1e6b47);
}

.btn-mint:hover {
  background: #bdeed3;
}

.btn-rose {
  background: var(--rose-bg, #ffdce3);
  color: var(--rose-text, #a12b47);
}

.btn-rose:hover {
  background: #ffc9d4;
}

.btn-butter {
  background: var(--butter-bg, #fff1c2);
  color: var(--butter-text, #8a5a00);
}

.btn-butter:hover {
  background: #ffe8a0;
}

.btn-sky {
  background: var(--sky-bg, #d6ecff);
  color: var(--sky-text, #1f5f99);
}

.btn-sky:hover {
  background: #bfe0ff;
}

.btn-grey {
  background: #c6cfd7;
  color: #626364;
}

.btn-grey:hover {
  background: #b0b3b6;
}

.change-row {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  margin-bottom: 0.75rem;
}

.change-current {
  font-size: 0.85rem;
  color: var(--text-muted, #6b6890);
}

.equipment-row {
  display: flex;
  gap: 0.5rem;
  align-items: center;
}

.equipment-row input:first-child {
  flex: 1;
}

.equipment-row input[type="number"] {
  width: 5rem;
}

.change-header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-wrap: wrap;
}

.change-list {
  margin: 0.4rem 0;
  padding-left: 1.2rem;
}

.change-reason {
  margin: 0.4rem 0 0;
}

.badge.pending {
  background: var(--butter-bg, #fff1c2);
}

.badge.processed {
  background: var(--mint-bg, #d3f5e3);
}

.badge.re_review {
  background: var(--butter-bg, #fff1c2);
  color: var(--butter-text, #8a5a00);
}

.badge.cannot_accommodate,
.badge.significant { background: var(--rose-bg, #fbdcdc); }
.badge.routine { background: var(--sky-bg, #d6ecff); }
.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>