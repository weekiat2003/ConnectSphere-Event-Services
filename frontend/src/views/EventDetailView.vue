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
        <span class="badge" :class="event.status">{{ event.statusLabel || "Unknown status" }}</span>
        <button v-if="canEditEvent && !showEditForm" class="btn btn-grey btn-small" @click="openEditForm">Edit</button>
        <button
          v-if="isAssignedCoordinator && ['approved', 'planning', 'safety_check', 'confirmed'].includes(event.status) && !showCancelForm"
          class="btn btn-rose btn-small" @click="openCancelForm">Cancel Event
        </button>
      </div>
      <div v-if="event.cancellation" class="notice cancelled">
        <strong>Coordinator cancelled this event</strong>
        <p class="decision-meta">
          By {{ event.cancellation.coordinatorName || `Coordinator #${event.cancellation.coordinatorId}` }}
          on {{ formatDate(event.cancellation.timestamp) }}
        </p>
        <p v-if="event.cancellation.reason" class="decision-reason">
          <strong>Reason:</strong> {{ event.cancellation.reason }}
        </p>
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
          <span class="detail-label">Starts</span>
          <span>{{ formatSchedule(event.proposedDate, event.proposedTime) }}</span>
        </div>

        <div class="detail">
          <span class="detail-label">Ends</span>
          <span>{{ formatSchedule(event.proposedEndDate, event.proposedEndTime) }}</span>
        </div>
        <div class="detail">
          <span class="detail-label">Expected attendance</span>
          <span>{{ event.expectedAttendance || "—" }}</span>
        </div>
        <div class="detail">
          <span class="detail-label">Capacity needed</span>
          <span>{{ event.venueRequirements?.capacityNeeded || "—" }}</span>
        </div>
        <div class="detail">
          <span class="detail-label">Required layout</span>
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
      <div class="accessibility">
        <span class="detail-label">Equipment required</span>

        <ul v-if="event.equipmentRequirements?.length">
          <li v-for="item in event.equipmentRequirements" :key="item.id">
            <strong>{{ item.quantity }} × {{ item.type }}</strong>
            <template v-if="item.technicalNotes">
              · {{ item.technicalNotes }}
            </template>
          </li>
        </ul>

        <p v-else>No equipment requested</p>
      </div>
    </div>

    <div
      v-if="event.venueBookings?.length && ['planning', 'safety_check', 'safety_approved', 'confirmed'].includes(event.status)"
      class="equipment-requirements-spacing"
    >
      <VenueRequirementsPanel :bookings="event.venueBookings" :requirements="event.venueRequirements" />
    </div>
    <div
      v-if="event.equipmentRequirements?.length && ['planning', 'safety_check', 'safety_approved', 'confirmed'].includes(event.status)"
      class="equipment-requirements-spacing"
    >
      <EquipmentRequirementsPanel :requirements="event.equipmentRequirements" />
    </div>
    <div v-if="(isAssignedCoordinator || isOwningOrganiser) && event.fieldEditLogs?.length" class="card history">
      <h3 class="section-title">Edit History</h3>
      <ul class="edit-history-list">
        <li v-for="log in event.fieldEditLogs" :key="log.id" class="edit-history-item"
          :class="{ rejected: log.wasRejected }">
          <div class="edit-history-header">
            <span class="edit-history-who">{{ log.changedByName || 'Unknown user' }}</span>
            <span class="edit-history-when">{{ log.createdAt ? formatDate(log.createdAt) : '' }}</span>
            <span v-if="log.wasSignificant" class="badge-pill amber">Significant</span>
            <span v-if="log.wasRejected" class="badge-pill rose">Rejected</span>
          </div>
          <p v-if="log.wasRejected" class="edit-history-rejected-note">
            {{ log.rejectionReason }} </p>
          <ul v-else class="edit-history-fields">
            <li v-for="field in Object.keys(log.newValues || {})" :key="field">
              <span class="edit-history-field-name">{{ EVENT_EDIT_FIELD_LABELS[field] || field }}</span>
              <span class="edit-history-change">
                <span class="edit-history-old">{{ formatHistoryValue(log.oldValues?.[field]) }}</span>
                <span class="edit-history-arrow">→</span>
                <span class="edit-history-new">{{ formatHistoryValue(log.newValues?.[field]) }}</span>
              </span>
            </li>
          </ul>
        </li>
      </ul>
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
          </div>
          <div v-if="item.response" class="thread-message response">
            <span class="thread-meta">Organiser · {{ formatDate(item.response.createdAt) }}</span>
            <p>{{ item.response.comments }}</p>
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
          <p v-if="request.decidedAt" class="change-reason"><strong>Decided:</strong> {{ formatDate(request.decidedAt)
          }}</p>
          <p v-if="request.status === 're_review' && request.reReviewAt" class="change-reason">
            <strong>Sent for re-review</strong> by the assigned Coordinator on {{ formatDate(request.reReviewAt) }}.
            Affected arrangements are flagged for reconsideration; proposed values are not applied yet.
          </p>
        </li>
      </ul>
    </div>

    <!-- Coordinator Assignment (Notification System, ISP-103): every submitted
         request waits Unassigned until an Event Coordinator Lead assigns it. -->
    <section
      v-if="!event.coordinatorId && event.status === 'submitted' && (auth.hasRole('event_coordinator') || auth.hasRole('event_coordinator_lead'))">
      <div class="action-block">
        <p>This request is waiting for an Event Coordinator Lead to assign it.</p>
        <router-link v-if="auth.hasRole('event_coordinator_lead')"
          :to="{ name: 'assignments', query: { event: event.id } }">
          Assign it from the Assignment Queue
        </router-link>
      </div>
    </section>
    <div v-else-if="auth.hasRole('event_coordinator_lead') && event.coordinatorName" class="assigned-note">
      <span>Assigned to {{ event.coordinatorName }}</span>
      <router-link v-if="REASSIGNABLE_STATUSES.includes(event.status)"
        :to="{ name: 'assignments', query: { event: event.id } }">
        {{ reassignmentRequest?.status === "pending" ? "Review reassignment request" : "Reassign in the Assignment Queue" }}
      </router-link>
    </div>

    <!-- Coordinator Actions: Event Review and Approval + Coordinator Assignment + Event Status Management -->
    <section v-if="isAssignedCoordinator && hasCoordinatorActions">
      <h3 class="section-title">Coordinator Actions</h3>

      <div v-if="showCancelForm" id="cancel-form" class="action-block">
        <h3 class="block-title">Cancel Event</h3>
        <textarea v-model="cancelReason" placeholder="Reason for cancelling (required)"></textarea>
        <p v-if="cancelError" class="field-error">{{ cancelError }}</p>
        <div class="actions">
          <button class="btn btn-rose" :disabled="cancelSubmitting" @click="cancelEvent">Confirm Cancellation</button>
          <button class="btn btn-grey" :disabled="cancelSubmitting" @click="showCancelForm = false">Back</button>
        </div>
      </div>

      <div v-if="event.status === 'under_review'" class="action-block">
        <textarea v-model="comment" placeholder="Comments / reason"></textarea>

        <div v-if="event.clarificationFlag" class="notice">
          <strong>Clarification requested:</strong> {{ event.clarificationComments }}
        </div>

        <p v-if="clarificationError" class="field-error">{{ clarificationError }}</p>
        <div class="actions">
          <button class="btn btn-butter" @click="clarify">Request Clarification</button>
          <button class="btn btn-mint" @click="approve">Approve</button>
          <button class="btn btn-rose" @click="reject">Reject</button>
        </div>
        <p v-if="actionError" class="field-error">{{ actionError }}</p>
      </div>

      <div v-if="showEditForm && canEditEvent" class="action-block">
        <h3 class="block-title">Edit Event Information</h3>
        <p v-if="auth.hasRole('event_coordinator')" class="notice-inline">
          To request or update equipment, use the
          <router-link to="/equipment/request">Equipment Booking page</router-link>.
        </p>
<div class="create-aligned-form">
<label class="aligned-field"><span>Name</span><input type="text" v-model="editForm.name"  /><span v-if="editErrors.name" class="field-error">{{ editErrors.name }}</span></label>
<label class="aligned-field"><span>Purpose</span><input type="text" v-model="editForm.purpose"  /><span v-if="editErrors.purpose" class="field-error">{{ editErrors.purpose }}</span></label>
<label class="aligned-field"><span>Event Type</span><select v-model="editForm.category"><option value="">Select a type (optional)</option><option v-for="type in EVENT_TYPES" :key="type" :value="type">{{ type }}</option><option v-if="editForm.category && !EVENT_TYPES.includes(editForm.category)" :value="editForm.category">{{ editForm.category }}</option></select><span v-if="editErrors.category" class="field-error">{{ editErrors.category }}</span></label>
<label class="aligned-field"><span>Description</span><textarea v-model="editForm.description" rows="3" placeholder=""></textarea><span v-if="editErrors.description" class="field-error">{{ editErrors.description }}</span></label>
<label class="aligned-field"><span>Start Date</span><input type="date" v-model="editForm.proposed_date"  /><span v-if="editErrors.proposed_date" class="field-error">{{ editErrors.proposed_date }}</span></label>
<label class="aligned-field"><span>Start Time</span><input type="time" v-model="editForm.proposed_time"  /><span v-if="editErrors.proposed_time" class="field-error">{{ editErrors.proposed_time }}</span></label>
<label class="aligned-field"><span>End Date</span><input type="date" v-model="editForm.proposed_end_date"  /><span v-if="editErrors.proposed_end_date" class="field-error">{{ editErrors.proposed_end_date }}</span></label>
<label class="aligned-field"><span>End Time</span><input type="time" v-model="editForm.proposed_end_time"  /><span v-if="editErrors.proposed_end_time" class="field-error">{{ editErrors.proposed_end_time }}</span></label>
<label class="aligned-field"><span>Expected Attendance</span><input type="number" v-model.number="editForm.expected_attendance" min="1" /><span v-if="editErrors.expected_attendance" class="field-error">{{ editErrors.expected_attendance }}</span></label>
<label class="aligned-field"><span>Capacity Needed</span><input type="number" v-model.number="editForm.capacity_needed" min="1" /><span v-if="editErrors.capacity_needed" class="field-error">{{ editErrors.capacity_needed }}</span></label>
<label class="aligned-field"><span>Required Layout</span><select v-model="editForm.required_layout"><option value="">Select a layout</option><option v-for="layout in venueLayouts" :key="layout" :value="layout">{{ layout }}</option><option v-if="editForm.required_layout && !venueLayouts.includes(editForm.required_layout)" :value="editForm.required_layout">{{ editForm.required_layout }}</option></select><span v-if="editErrors.required_layout" class="field-error">{{ editErrors.required_layout }}</span></label>
<label class="aligned-field"><span>Accessibility Needs</span><textarea v-model="editForm.accessibility_needs" rows="3" placeholder=""></textarea><span v-if="editErrors.accessibility_needs" class="field-error">{{ editErrors.accessibility_needs }}</span></label>
<label class="aligned-field full aligned-checkbox"><input type="checkbox" v-model="editForm.registration_required" />Registration required</label><label v-if="editForm.registration_required" class="aligned-field"><span>Intended Capacity (optional)</span><input type="number" min="1" v-model.number="editForm.intended_capacity" /></label>
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

      <div v-if="event.status === 'approved'" class="action-block">
        <p class="notice-inline">This request is approved. Move it into planning to start arranging the venue and equipment.
        </p>
        <p v-if="actionError" class="field-error">{{ actionError }}</p>
        <div class="actions">
          <button class="btn btn-sky" :disabled="statusBusy" @click="proceedToPlanning">Proceed to Planning</button>
        </div>
      </div>

      <div v-if="event.status === 'planning'" class="action-block">
        <p class="notice-inline">
          {{ event.canSendForSafetyCheck
            ? "All venue and equipment arrangements are complete. Send this event for its safety check."
            : "Complete every venue booking and equipment reservation to send this event for its safety check." }}
        </p>
        <p v-if="actionError" class="field-error">{{ actionError }}</p>
        <div class="actions">
          <button class="btn btn-primary" :disabled="!event.canSendForSafetyCheck || statusBusy"
            @click="sendForSafetyCheck">Send for Safety Check</button>
        </div>
      </div>

      <div v-if="event.status === 'safety_approved'" class="action-block">
        <p class="notice-inline">
          {{ event.awaitingConfirmation ? "The Safety Officer has approved this event. Confirm it to complete planning."
            :
          "Waiting for the Safety Officer's decision." }}
        </p>
        <p v-if="actionError" class="field-error">{{ actionError }}</p>
        <div class="actions">
          <button class="btn btn-mint" :disabled="!event.awaitingConfirmation || statusBusy"
            @click="confirmEvent">Confirm
            Event</button>
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

      <!-- Coordinator Assignment (Week 7): only a Lead can reassign. The
           Coordinator asks, with a reason; hidden once the event is closed. -->
      <div v-if="REASSIGNABLE_STATUSES.includes(event.status)" class="action-block reassignment-block">
        <h3 class="block-title">Coordinator reassignment</h3>
        <template v-if="reassignmentRequest?.status === 'pending'">
          <p class="reassign-status">
            <span class="badge-pending">Waiting for a Coordinator Lead</span>
            You asked on {{ formatDate(reassignmentRequest.createdAt) }}.
          </p>
          <p class="reassign-reason"><strong>Your reason:</strong> {{ reassignmentRequest.reason }}</p>
          <div class="actions">
            <button class="btn btn-grey" :disabled="reassignBusy" @click="withdrawReassignment">Withdraw
              request</button>
          </div>
        </template>
        <template v-else>
          <p v-if="reassignmentRequest?.status === 'declined'" class="reassign-declined">
            Your last request was declined by {{ reassignmentRequest.decidedByName || "a Coordinator Lead" }}
            on {{ formatDate(reassignmentRequest.decidedAt) }}<template v-if="reassignmentRequest.decisionNote">:
              "{{ reassignmentRequest.decisionNote }}"</template><template v-else>.</template>
          </p>
          <p class="hint">
            Can't continue with this event? Ask a Coordinator Lead to reassign it. The Lead chooses who takes over,
            and you keep read-only access afterwards.
          </p>
          <label for="reassign-reason">Reason (required)</label>
          <textarea id="reassign-reason" v-model="reassignReason" maxlength="500" rows="3"
            placeholder="e.g. On leave from 1 Dec, or workload too high this month"></textarea>
          <p v-if="reassignError" class="field-error">{{ reassignError }}</p>
          <div class="actions">
            <button class="btn btn-primary" :disabled="reassignBusy || !reassignReason.trim()"
              @click="requestReassignment">
              Request reassignment
            </button>
          </div>
        </template>
      </div>
    </section>

    <section v-if="auth.hasRole('safety_officer') && event.status === 'safety_check'">
      <h3 class="section-title">Operational Safety Check</h3>
      <div class="action-block">
        <p class="notice-inline">
          This event is awaiting your safety check. Assess each factor and record your decision on the review page.
        </p>
        <div class="actions">
          <router-link class="btn btn-primary" :to="`/safety-reviews/${event.id}`">
            Open safety review
          </router-link>
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

<div class="create-aligned-form">
<label class="aligned-field"><span>Name</span><span class="aligned-current">Current: {{ formatChangeValue('name', eventFieldValue('name')) }}</span><input type="text" v-model="changeForm.name"  /><span v-if="changeErrors.name" class="field-error">{{ changeErrors.name }}</span></label>
<label class="aligned-field"><span>Purpose</span><span class="aligned-current">Current: {{ formatChangeValue('purpose', eventFieldValue('purpose')) }}</span><input type="text" v-model="changeForm.purpose"  /><span v-if="changeErrors.purpose" class="field-error">{{ changeErrors.purpose }}</span></label>
<label class="aligned-field"><span>Event Type</span><span class="aligned-current">Current: {{ formatChangeValue('category', eventFieldValue('category')) }}</span><select v-model="changeForm.category"><option value="">Keep current type</option><option v-for="type in EVENT_TYPES" :key="type" :value="type">{{ type }}</option><option v-if="changeForm.category && !EVENT_TYPES.includes(changeForm.category)" :value="changeForm.category">{{ changeForm.category }}</option></select><span v-if="changeErrors.category" class="field-error">{{ changeErrors.category }}</span></label>
<label class="aligned-field"><span>Description</span><span class="aligned-current">Current: {{ formatChangeValue('description', eventFieldValue('description')) }}</span><textarea v-model="changeForm.description" rows="3" placeholder="Proposed value (leave blank to keep current)"></textarea><span v-if="changeErrors.description" class="field-error">{{ changeErrors.description }}</span></label>
<label class="aligned-field"><span>Start Date</span><span class="aligned-current">Current: {{ formatChangeValue('proposed_date', eventFieldValue('proposed_date')) }}</span><input type="date" v-model="changeForm.proposed_date"  /><span v-if="changeErrors.proposed_date" class="field-error">{{ changeErrors.proposed_date }}</span></label>
<label class="aligned-field"><span>Start Time</span><span class="aligned-current">Current: {{ formatChangeValue('proposed_time', eventFieldValue('proposed_time')) }}</span><input type="time" v-model="changeForm.proposed_time"  /><span v-if="changeErrors.proposed_time" class="field-error">{{ changeErrors.proposed_time }}</span></label>
<label class="aligned-field"><span>End Date</span><span class="aligned-current">Current: {{ formatChangeValue('proposed_end_date', eventFieldValue('proposed_end_date')) }}</span><input type="date" v-model="changeForm.proposed_end_date"  /><span v-if="changeErrors.proposed_end_date" class="field-error">{{ changeErrors.proposed_end_date }}</span></label>
<label class="aligned-field"><span>End Time</span><span class="aligned-current">Current: {{ formatChangeValue('proposed_end_time', eventFieldValue('proposed_end_time')) }}</span><input type="time" v-model="changeForm.proposed_end_time"  /><span v-if="changeErrors.proposed_end_time" class="field-error">{{ changeErrors.proposed_end_time }}</span></label>
<label class="aligned-field"><span>Expected Attendance</span><span class="aligned-current">Current: {{ formatChangeValue('expected_attendance', eventFieldValue('expected_attendance')) }}</span><input type="number" v-model.number="changeForm.expected_attendance" min="1" /><span v-if="changeErrors.expected_attendance" class="field-error">{{ changeErrors.expected_attendance }}</span></label>
<label class="aligned-field"><span>Capacity Needed</span><span class="aligned-current">Current: {{ formatChangeValue('capacity_needed', eventFieldValue('capacity_needed')) }}</span><input type="number" v-model.number="changeForm.capacity_needed" min="1" /><span v-if="changeErrors.capacity_needed" class="field-error">{{ changeErrors.capacity_needed }}</span></label>
<label class="aligned-field"><span>Required Layout</span><span class="aligned-current">Current: {{ formatChangeValue('required_layout', eventFieldValue('required_layout')) }}</span><select v-model="changeForm.required_layout"><option value="">Keep current layout</option><option v-for="layout in venueLayouts" :key="layout" :value="layout">{{ layout }}</option><option v-if="changeForm.required_layout && !venueLayouts.includes(changeForm.required_layout)" :value="changeForm.required_layout">{{ changeForm.required_layout }}</option></select><span v-if="changeErrors.required_layout" class="field-error">{{ changeErrors.required_layout }}</span></label>
<label class="aligned-field"><span>Accessibility Needs</span><span class="aligned-current">Current: {{ formatChangeValue('accessibility_needs', eventFieldValue('accessibility_needs')) }}</span><textarea v-model="changeForm.accessibility_needs" rows="3" placeholder="Proposed value (leave blank to keep current)"></textarea><span v-if="changeErrors.accessibility_needs" class="field-error">{{ changeErrors.accessibility_needs }}</span></label>
<div class="aligned-equipment full"><h3>Equipment Required</h3><p class="aligned-help">Select equipment from the catalogue and specify the quantity needed for your event.</p><p class="aligned-current">Current: {{ currentEquipmentLabel }}</p><button v-if="changeEquipment === null" type="button" class="btn btn-grey" @click="startEquipmentChange">Change equipment</button><template v-else><div v-for="(item, index) in changeEquipment" :key="index" class="aligned-equipment-item"><div class="aligned-item-header"><strong>Equipment {{ index + 1 }}</strong><button type="button" class="aligned-remove" @click="removeEquipmentRow(index)">Remove</button></div><div class="aligned-equipment-fields"><label>Equipment Type *<select v-model="item.type"><option value="">Select equipment</option><option v-if="item.type && !equipmentOptions.some(e => e.name === item.type)" :value="item.type">{{ item.type }}</option><option v-for="eq in equipmentOptions" :key="eq.id" :value="eq.name">{{ eq.name }}</option></select></label><label>Quantity *<input type="number" min="1" v-model.number="item.quantity" /></label></div><label>Technical Requirements<textarea v-model="item.technicalNotes" rows="2" placeholder="e.g. HDMI connection required"></textarea></label></div><button type="button" class="btn btn-grey" @click="addEquipmentRow">+ Add Equipment</button><button type="button" class="btn btn-grey" @click="changeEquipment = null">Keep current equipment</button></template><p v-if="changeErrors.equipment_requirements" class="field-error">{{ changeErrors.equipment_requirements }}</p></div>
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

<div class="create-aligned-form">
<label class="aligned-field"><span>Name</span><input type="text" v-model="revisionForm.name"  /><span v-if="revisionFieldErrors.name" class="field-error">{{ revisionFieldErrors.name }}</span></label>
<label class="aligned-field"><span>Purpose</span><input type="text" v-model="revisionForm.purpose"  /><span v-if="revisionFieldErrors.purpose" class="field-error">{{ revisionFieldErrors.purpose }}</span></label>
<label class="aligned-field"><span>Event Type</span><select v-model="revisionForm.category"><option value="">Select a type (optional)</option><option v-for="type in EVENT_TYPES" :key="type" :value="type">{{ type }}</option><option v-if="revisionForm.category && !EVENT_TYPES.includes(revisionForm.category)" :value="revisionForm.category">{{ revisionForm.category }}</option></select><span v-if="revisionFieldErrors.category" class="field-error">{{ revisionFieldErrors.category }}</span></label>
<label class="aligned-field"><span>Description</span><textarea v-model="revisionForm.description" rows="3" placeholder=""></textarea><span v-if="revisionFieldErrors.description" class="field-error">{{ revisionFieldErrors.description }}</span></label>
<label class="aligned-field"><span>Start Date</span><input type="date" v-model="revisionForm.proposed_date"  /><span v-if="revisionFieldErrors.proposed_date" class="field-error">{{ revisionFieldErrors.proposed_date }}</span></label>
<label class="aligned-field"><span>Start Time</span><input type="time" v-model="revisionForm.proposed_time"  /><span v-if="revisionFieldErrors.proposed_time" class="field-error">{{ revisionFieldErrors.proposed_time }}</span></label>
<label class="aligned-field"><span>End Date</span><input type="date" v-model="revisionForm.proposed_end_date"  /><span v-if="revisionFieldErrors.proposed_end_date" class="field-error">{{ revisionFieldErrors.proposed_end_date }}</span></label>
<label class="aligned-field"><span>End Time</span><input type="time" v-model="revisionForm.proposed_end_time"  /><span v-if="revisionFieldErrors.proposed_end_time" class="field-error">{{ revisionFieldErrors.proposed_end_time }}</span></label>
<label class="aligned-field"><span>Expected Attendance</span><input type="number" v-model.number="revisionForm.expected_attendance" min="1" /><span v-if="revisionFieldErrors.expected_attendance" class="field-error">{{ revisionFieldErrors.expected_attendance }}</span></label>
<label class="aligned-field"><span>Capacity Needed</span><input type="number" v-model.number="revisionForm.capacity_needed" min="1" /><span v-if="revisionFieldErrors.capacity_needed" class="field-error">{{ revisionFieldErrors.capacity_needed }}</span></label>
<label class="aligned-field"><span>Required Layout</span><select v-model="revisionForm.required_layout"><option value="">Select a layout</option><option v-for="layout in venueLayouts" :key="layout" :value="layout">{{ layout }}</option><option v-if="revisionForm.required_layout && !venueLayouts.includes(revisionForm.required_layout)" :value="revisionForm.required_layout">{{ revisionForm.required_layout }}</option></select><span v-if="revisionFieldErrors.required_layout" class="field-error">{{ revisionFieldErrors.required_layout }}</span></label>
<label class="aligned-field"><span>Accessibility Needs</span><textarea v-model="revisionForm.accessibility_needs" rows="3" placeholder=""></textarea><span v-if="revisionFieldErrors.accessibility_needs" class="field-error">{{ revisionFieldErrors.accessibility_needs }}</span></label>
<div class="aligned-equipment full"><h3>Equipment Required</h3><p class="aligned-help">Select equipment from the catalogue and specify the quantity needed for your event.</p><div v-for="(item, index) in revisionEquipment" :key="item.id ?? index" class="aligned-equipment-item"><div class="aligned-item-header"><strong>Equipment {{ index + 1 }}</strong><button type="button" class="aligned-remove" @click="revisionEquipment.splice(index, 1)">Remove</button></div><div class="aligned-equipment-fields"><label>Equipment Type *<select v-model="item.type"><option value="">Select equipment</option><option v-if="item.type && !equipmentOptions.some(e => e.name === item.type)" :value="item.type">{{ item.type }}</option><option v-for="eq in equipmentOptions" :key="eq.id" :value="eq.name">{{ eq.name }}</option></select></label><label>Quantity *<input type="number" min="1" v-model.number="item.quantity" /></label></div><label>Technical Requirements<textarea v-model="item.technicalNotes" rows="2" placeholder="e.g. HDMI connection required"></textarea></label></div><button type="button" class="btn btn-grey" @click="revisionEquipment.push({ id: null, type: '', quantity: 1, technicalNotes: '' })">+ Add Equipment</button></div>
<label class="aligned-field full aligned-checkbox"><input type="checkbox" v-model="revisionForm.registration_required" />Registration required</label><label v-if="revisionForm.registration_required" class="aligned-field"><span>Intended Capacity (optional)</span><input type="number" min="1" v-model.number="revisionForm.intended_capacity" /></label>
</div>
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
import { computed, nextTick, onMounted, reactive, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { useAuthStore } from "../stores/auth";
import eventsApi from "../api/events";
import usersApi from "../api/users";
import { useConfirm } from "../composables/useConfirm";
import changeRequestsApi from "../api/changeRequests";
import equipmentApi from "../api/equipment";
import venuesApi from "../api/venues";
import EquipmentRequirementsPanel from "../components/EquipmentRequirementsPanel.vue";
import VenueRequirementsPanel from "../components/VenueRequirementsPanel.vue";


const route = useRoute();
const router = useRouter();
const auth = useAuthStore();

const event = ref(null);
const comment = ref("");
const newCoordinatorId = ref(null);
const coordinators = ref([]);

const clarificationError = ref("");
const reviewHistory = ref([]);

const confirmState = ref(null); // { message, onConfirm, onCancel }
const actionError = ref("");
const statusBusy = ref(false);

async function runStatusAction(call, fallbackMessage, question = null) {
  if (question && !(await confirm(question))) return;
  actionError.value = "";
  statusBusy.value = true;
  try {
    await call(event.value.id);
    await load();
  } catch (e) {
    actionError.value = e.response?.data?.error || fallbackMessage;
  } finally {
    statusBusy.value = false;
  }
}
const proceedToPlanning = () => runStatusAction(eventsApi.proceedToPlanning, "Could not move this event into planning.");
const sendForSafetyCheck = () => runStatusAction(eventsApi.sendForSafetyCheck, "Could not send this event for safety check.", "Send this event for its safety check?");
const confirmEvent = () => runStatusAction(eventsApi.confirmEvent, "Could not confirm this event.", "Confirm this event?");


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

const latestSafetyReview = computed(() => event.value?.currentSafetyReview || null);

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
  { key: "capacity_needed", label: "Capacity Needed", type: "number" },
  { key: "required_layout", label: "Required Layout", type: "text" },
  { key: "accessibility_needs", label: "Accessibility needs", type: "textarea" },
  { key: "registration_required", label: "Registration required", type: "checkbox" },
];

const EVENT_EDIT_FIELD_OPTIONS = [
  { key: "name", label: "Name" }, { key: "purpose", label: "Purpose" },
  { key: "category", label: "Event Type" }, { key: "description", label: "Description" },
  { key: "proposed_date", label: "Start Date" }, { key: "proposed_time", label: "Start Time" },
  { key: "proposed_end_date", label: "End Date" }, { key: "proposed_end_time", label: "End Time" },
  { key: "expected_attendance", label: "Expected Attendance" },
  { key: "capacity_needed", label: "Capacity Needed" },
  { key: "required_layout", label: "Required Layout" },
  { key: "accessibility_needs", label: "Accessibility Needs" },
  { key: "registration_required", label: "Registration required" },
  { key: "intended_capacity", label: "Intended Capacity" },
];
const EVENT_TYPES = ["Conference", "Seminar", "Workshop", "Meeting", "Panel", "Networking", "Social", "Community", "Competition", "Entertainment", "Exhibition", "Orientation", "Ceremony", "Other"];
const venueLayouts = ref([]);
async function loadVenueLayouts() {
  try {
    const { data } = await venuesApi.listVenues();
    venueLayouts.value = [...new Set((Array.isArray(data) ? data : []).flatMap(v => v.supportedLayouts || []).filter(Boolean))].sort();
  } catch (error) { console.warn("Could not load venue layouts", error); }
}
const revisionEquipment = ref([]);
const revisionFieldErrors = ref({});
function eventFieldValue(key) {
  const e = event.value || {};
  const direct = { name: e.name, purpose: e.purpose, category: e.category, description: e.description,
    proposed_date: e.proposedDate, proposed_time: e.proposedTime,
    proposed_end_date: e.proposedEndDate, proposed_end_time: e.proposedEndTime,
    expected_attendance: e.expectedAttendance, capacity_needed: e.venueRequirements?.capacityNeeded,
    required_layout: e.venueRequirements?.requiredLayout,
    accessibility_needs: e.venueRequirements?.accessibilityNeeds };
  return direct[key];
}
const EVENT_EDIT_FIELD_LABELS = Object.fromEntries(EVENT_EDIT_FIELD_OPTIONS.map((f) => [f.key, f.label]));

const REASSIGNABLE_STATUSES = [
  "under_review",
  "approved",
  "planning",
  "safety_check",
  "safety_approved",
  "confirmed",
];

function formatHistoryValue(value) {
  if (value === null || value === undefined || value === "") return "—";
  if (Array.isArray(value)) {
    if (value.length === 0) return "None";
    if (typeof value[0] === "object") {
      return value.map((v) => `${v.quantity ?? ""} × ${v.type ?? v.equipmentType ?? ""}`.trim()).join(", ");
    }
    return value.join(", ");
  }
  if (typeof value === "boolean") return value ? "Yes" : "No";
  return String(value);
}

const EDITABLE_EVENT_STATUSES = ['under_review', 'approved', 'planning', 'safety_check'];
const canEditEvent = computed(() =>
  isAssignedCoordinator.value && EDITABLE_EVENT_STATUSES.includes(event.value.status)
);

const isAssignedCoordinator = computed(
  () => auth.hasRole("event_coordinator") && event.value?.coordinatorId === auth.user?.id
);
// Every block in "Coordinator Actions" belongs to an active status (Under Review
// to Confirmed), plus the cancel/edit forms and the confirm prompt. Show the
// section only when one of them applies, so it is never an empty heading
// (e.g. Submitted, Completed, Cancelled or Rejected events).
const hasCoordinatorActions = computed(() =>
  isAssignedCoordinator.value && (
    REASSIGNABLE_STATUSES.includes(event.value?.status)
    || showCancelForm.value
    || (showEditForm.value && canEditEvent.value)
    || !!confirmState.value
  )
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
  category: "",
  description: "",
  proposed_date: "",
  proposed_time: "",
  proposed_end_date: "",
  proposed_end_time: "",
  expected_attendance: null,
  capacity_needed: null,
  required_layout: "",
  accessibility_needs: "",
  registration_required: false,
  intended_capacity: null,
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
  { key: "name", label: "Name", type: "text", current: e => e.name },
  { key: "purpose", label: "Purpose", type: "text", current: e => e.purpose },
  { key: "category", label: "Event Type", type: "text", current: e => e.category },
  { key: "description", label: "Description", type: "textarea", current: e => e.description },
  { key: "proposed_date", label: "Start Date", type: "date", current: e => e.proposedDate },
  { key: "proposed_time", label: "Start Time", type: "time", current: e => e.proposedTime },
  { key: "proposed_end_date", label: "End Date", type: "date", current: e => e.proposedEndDate },
  { key: "proposed_end_time", label: "End Time", type: "time", current: e => e.proposedEndTime },
  { key: "expected_attendance", label: "Expected Attendance", type: "number", current: e => e.expectedAttendance },
  { key: "capacity_needed", label: "Capacity Needed", type: "number", current: e => e.venueRequirements?.capacityNeeded },
  { key: "required_layout", label: "Required Layout", type: "text", current: e => e.venueRequirements?.requiredLayout },
  { key: "accessibility_needs", label: "Accessibility Needs", type: "textarea", current: e => e.venueRequirements?.accessibilityNeeds },
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

const statusLabel = (value) =>
  String(value || "").replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());

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

const equipmentOptions = ref([]);

async function loadEquipmentOptions() {
  if (equipmentOptions.value.length) return;
  try {
    const { data } = await equipmentApi.listItems();
    equipmentOptions.value = data.filter((i) => i.status === "active");
  } catch (e) {
    console.error("Could not load equipment options", e.response?.status, e.response?.data || e);
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
  changeEquipment.value = null;
  changeReason.value = "";
  changeErrors.value = {};
}

async function openChangeForm() {
  await Promise.all([loadEquipmentOptions(), loadVenueLayouts()]);
  resetChangeForm();
  showChangeForm.value = true;
}

function startEquipmentChange() {
  changeEquipment.value = (event.value.equipmentRequirements || []).map((e) => ({
    type: e.type ?? e.equipmentType,
    quantity: e.quantity,
    technicalNotes: e.technicalNotes ?? "",
  }));
}
const addEquipmentRow = () => changeEquipment.value.push({ type: "", quantity: 1, technicalNotes: "" });
const removeEquipmentRow = (index) => changeEquipment.value.splice(index, 1);

function buildChanges() {
  const changes = {};
  for (const field of CHANGE_FIELDS) {
    const value = changeForm[field.key];
    if (value !== "" && value !== null && value !== undefined) changes[field.key] = value;
  }
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

// The API sends naive UTC timestamps (see backend app/common/time.py); mark
// them as UTC so the browser shows the viewer's local time, not UTC as local.
const formatDate = (iso) => {
  if (!iso) return "";
  const text = String(iso);
  return new Date(/(?:Z|[+-]\d{2}:\d{2})$/i.test(text) ? text : `${text}Z`).toLocaleString();
};

function formatSchedule(date, time) {
  const dateLabel = date
    ? new Intl.DateTimeFormat("en-SG", {
        day: "numeric",
        month: "short",
        year: "numeric",
        timeZone: "UTC",
      }).format(new Date(`${date}T00:00:00Z`))
    : "";

  const timeLabel = time ? time.slice(0, 5) : "";

  return [dateLabel, timeLabel].filter(Boolean).join(" at ") || "Not specified";
}

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
    await eventsApi.requestClarification(event.value.id, comment.value);
    comment.value = "";
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
    proposed_time: (event.value.proposedTime || "").slice(0, 5),
    proposed_end_date: event.value.proposedEndDate || "",
    proposed_end_time: (event.value.proposedEndTime || "").slice(0, 5),
    expected_attendance: event.value.expectedAttendance,
    capacity_needed: event.value.venueRequirements?.capacityNeeded,
    required_layout: event.value.venueRequirements?.requiredLayout,
    accessibility_needs: event.value.venueRequirements?.accessibilityNeeds,
    registration_required: event.value.registrationRequired,
  };
  const fields = {};
  ([]).forEach((key) => {
    fields[key] = source[key] ?? (key === "registration_required" ? false : "");
  });
  openResponseForms[item.reviewId] = { comments: "", fields };
}

function initRevisionForm() {
  if (event.value?.status !== "rejected") return;
  revisionForm.name = event.value.name || "";
  revisionForm.purpose = event.value.purpose || "";
  revisionForm.category = event.value.category || "";
  revisionForm.description = event.value.description || "";
  revisionForm.proposed_date = event.value.proposedDate || "";
  revisionForm.proposed_time = (event.value.proposedTime || "").slice(0, 5);
  revisionForm.proposed_end_date = event.value.proposedEndDate || "";
  revisionForm.proposed_end_time = (event.value.proposedEndTime || "").slice(0, 5);
  revisionForm.expected_attendance = event.value.expectedAttendance;
  revisionForm.capacity_needed = event.value.venueRequirements?.capacityNeeded;
  revisionForm.required_layout = event.value.venueRequirements?.requiredLayout;
  revisionForm.accessibility_needs = event.value.venueRequirements?.accessibilityNeeds;
  revisionForm.registration_required = event.value.registrationRequired;
  revisionForm.intended_capacity = event.value.intendedCapacity ?? null;
  revisionEquipment.value = (event.value.equipmentRequirements || []).map(item => ({ id: item.id, type: item.type ?? item.equipmentType, quantity: item.quantity, technicalNotes: item.technicalNotes ?? "" }));
  loadEquipmentOptions();
  loadVenueLayouts();
}

const SIGNIFICANT_FIELD_KEYS = [
  "proposed_date",
  "proposed_time",
  "proposed_end_date",
  "proposed_end_time",
  "expected_attendance",
  "capacity_needed",
  "required_layout",
  "accessibility_needs",
  "required_facilities",
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
  loadVenueLayouts();
  if (!canEditEvent.value) return;
  const source = {
    name: event.value.name,
    purpose: event.value.purpose,
    description: event.value.description,
    category: event.value.category,
    proposed_date: event.value.proposedDate,
    proposed_time: event.value.proposedTime,
    proposed_end_date: event.value.proposedEndDate || "",
    proposed_end_time: (event.value.proposedEndTime || "").slice(0, 5),
    expected_attendance: event.value.expectedAttendance,
    capacity_needed: event.value.venueRequirements?.capacityNeeded,
    required_layout: event.value.venueRequirements?.requiredLayout,
    accessibility_needs: event.value.venueRequirements?.accessibilityNeeds,
    registration_required: event.value.registrationRequired,
    intended_capacity: event.value.intendedCapacity,
    required_facilities: [...(event.value.venueRequirements?.requiredFacilities || [])],
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

// function requestActionWithConfirmation(callWithConfirmed) {
//   return new Promise((resolve, reject) => {
//     callWithConfirmed(false)
//       .then(({ data }) => resolve(data))
//       .catch((e) => {
//         if (e.response?.status === 409 && e.response.data?.requiresConfirmation) {
//           confirmState.value = {
//             message: e.response.data.message,
//             onConfirm: () => {
//               confirmState.value = null;
//               callWithConfirmed(true)
//                 .then(({ data }) => resolve(data))
//                 .catch(reject);
//             },
//             onCancel: () => {
//               confirmState.value = null;
//               resolve(null);
//             },
//           };
//         } else {
//           reject(e);
//         }
//       });
//   });
// }

function requestActionWithConfirmation(callWithConfirmed) {
  return new Promise((resolve, reject) => {
    callWithConfirmed(false)
      .then(({ data }) => resolve(data))
      .catch((e) => {
        if (e.response?.status === 409 && e.response.data?.requiresConfirmation) {
          confirmState.value = {
            message: e.response.data.message,

            onConfirm: async () => {
              console.log("Confirm button clicked");
              confirmState.value = null;

              try {
                console.log("Sending confirmed request...");
                const response = await callWithConfirmed(true);
                console.log("Confirmed response:", response);
                resolve(response.data);
              } catch (error) {
                console.error("Confirmed request failed:", error);
                reject(error);
              }
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

const reassignmentRequest = ref(null);
const reassignReason = ref("");
const reassignError = ref("");
const reassignBusy = ref(false);

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
    const { data } = await eventsApi.resubmitEvent(event.value.id, { ...revisionForm, equipment_requirements: revisionEquipment.value.map(({ id, type, quantity, technicalNotes }) => ({ ...(id != null ? { id } : {}), type, quantity: Number(quantity), technicalNotes })) });
    router.push(`/events/${data.id}`);
  } catch (e) {
    revisionError.value = e.response?.data?.error || "Could not resubmit this request.";
  }
}

const showCancelForm = ref(false);
const cancelReason = ref("");
const cancelError = ref("");
const cancelSubmitting = ref(false);

const CANCELLABLE_STATUSES = ["approved", "planning", "safety_check", "confirmed"];
let returnToRequestId = null;

async function openCancelFromWithdrawal() {
  if (route.query.cancel !== "1") return;
  returnToRequestId = Number(route.query.fromRequest) || null;
  router.replace({ query: {} }); // so a refresh doesn't reopen the form
  if (!isAssignedCoordinator.value || !CANCELLABLE_STATUSES.includes(event.value.status)) return;

  openCancelForm();
  const withdrawal = changeRequests.value.find(
    (r) => r.requestType === "withdrawal" && r.status === "pending"
  );
  if (withdrawal) cancelReason.value = `Organiser requested withdrawal: ${withdrawal.reason}`;
  await nextTick();
  document.getElementById("cancel-form")?.scrollIntoView({ block: "center" });
}

function openCancelForm() {
  cancelReason.value = "";
  cancelError.value = "";
  showCancelForm.value = true;
}

async function cancelEvent() {
  cancelError.value = "";
  cancelSubmitting.value = true;
  try {
    const data = await requestActionWithConfirmation((confirmed) =>
      eventsApi.cancelEvent(event.value.id, cancelReason.value, confirmed)
    );
    if (data) {
      showCancelForm.value = false;
      cancelReason.value = "";
      await load();
      if (returnToRequestId) {
        router.push({ name: "change-request-review", query: { id: returnToRequestId } });
      }
    }
  } catch (e) {
    const data = e.response?.data;
    cancelError.value = data?.errors?.reason || data?.error || "Could not cancel this event.";
  } finally {
    cancelSubmitting.value = false;
  }
}

onMounted(async () => {
  await load();
  // /auth/users is coordinator-only server-side; only fetch it if this
  // viewer actually has that role, to avoid a needless 403.
  if (auth.hasRole("event_coordinator")) {
    await loadCoordinators();
  }
  await openCancelFromWithdrawal();
});
</script>

<style scoped>
.equipment-requirements-spacing { margin-top: 1.25rem; margin-bottom: 1.25rem; }

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

.equipment-row select {
  padding: 0.4rem 0.6rem;
  border: 1px solid var(--border, #e4defa);
  border-radius: 8px;
  font: inherit;
  min-width: 0;
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

.notice.cancelled {
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
.assigned-note {
  color: var(--text-muted);
  font-weight: 500;
}

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

.badge.significant {
  background: var(--rose-bg, #fbdcdc);
}

.badge.routine {
  background: var(--sky-bg, #d6ecff);
}

/* Operational safety check */
.safety-checklist {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem 1.25rem;
  margin: 0 0 0.85rem;
  padding: 0.75rem 1rem;
  border: 1px solid var(--border, #e3e3e8);
  border-radius: 10px;
}

.safety-checklist legend {
  padding: 0 0.35rem;
  font-weight: 600;
}

.checklist-count {
  font-weight: 400;
  opacity: 0.75;
}

.safety-errors {
  padding-left: 1.2rem;
}

.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.edit-history-list {
  list-style: none;
  margin: 0.5rem 0 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
}

.edit-history-item {
  padding: 0.65rem 0.8rem;
  border-radius: 10px;
  background: var(--sky-bg, #d6ecff);
}

.edit-history-item.rejected {
  background: var(--rose-bg, #fde2e7);
}

.edit-history-header {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.5rem;
}

.edit-history-who {
  font-weight: 600;
  font-size: 0.85rem;
  color: var(--text, #2d2a4a);
}

.edit-history-when {
  font-size: 0.75rem;
  color: var(--text-muted, #6b6890);
}

.badge-pill {
  font-size: 0.7rem;
  font-weight: 600;
  padding: 0.1rem 0.5rem;
  border-radius: 999px;
}

.badge-pill.amber {
  background: var(--butter-bg, #fef3c7);
  color: #92631a;
}

.badge-pill.rose {
  background: var(--rose-bg, #fde2e7);
  color: var(--rose-text, #a12b47);
}

.edit-history-rejected-note {
  margin: 0.3rem 0 0;
  font-size: 0.82rem;
  color: var(--rose-text, #a12b47);
}

.edit-history-fields {
  list-style: none;
  margin: 0.4rem 0 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.edit-history-fields li {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
  font-size: 0.82rem;
}

.edit-history-field-name {
  font-weight: 600;
  color: var(--text, #2d2a4a);
  min-width: 140px;
}

.edit-history-change {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  color: var(--text, #2d2a4a);
}

.edit-history-old {
  color: var(--text-muted, #6b6890);
  text-decoration: line-through;
}

.edit-history-arrow {
  color: var(--text-muted, #6b6890);
}

.edit-history-new {
  font-weight: 500;
}

.eq-help {
  margin: 0 0 0.5rem;
  font-size: 0.85rem;
  color: var(--text-muted, #6b6890);
}

.eq-row {
  display: grid;
  grid-template-columns: minmax(0, 2fr) 5.5rem minmax(0, 3fr) auto;
  gap: 0.5rem;
  align-items: center;
}

.eq-head {
  margin-bottom: 0.25rem;
  font-size: 0.8rem;
  font-weight: 500;
  color: var(--text-muted, #6b6890);
}

.eq-block {
  margin-bottom: 0.5rem;
}

.eq-row select,
.eq-row input {
  width: 100%;
  min-width: 0;
  box-sizing: border-box;
  padding: 0.4rem 0.6rem;
  border: 1px solid var(--border, #e4defa);
  border-radius: 8px;
  font: inherit;
}

/* Consistent with EventCreateView's two-column event request layout. */
.create-aligned-form { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:1rem 1.1rem; margin:1rem 0 1.5rem; }
.aligned-field { display:flex; flex-direction:column; gap:.4rem; min-width:0; font-size:.92rem; font-weight:600; color:#2d2a4a; }
.aligned-field input:not([type="checkbox"]), .aligned-field select, .aligned-field textarea, .aligned-equipment input, .aligned-equipment select, .aligned-equipment textarea { box-sizing:border-box; width:100%; min-width:0; padding:.75rem .85rem; background:#faf9ff; border:1px solid #ded7ff; border-radius:10px; color:#302b4d; font:inherit; }
/* Match EventCreateView: labels are semibold, entered values are regular. */
.aligned-field input:not([type="checkbox"]),
.aligned-field select,
.aligned-field textarea,
.aligned-equipment input,
.aligned-equipment select,
.aligned-equipment textarea {
  font-weight: 400;
}
.aligned-field textarea { min-height:105px; resize:vertical; }
.aligned-field input:focus, .aligned-field select:focus, .aligned-field textarea:focus, .aligned-equipment input:focus, .aligned-equipment select:focus, .aligned-equipment textarea:focus { outline:2px solid #a89af0; outline-offset:1px; }
.aligned-current { color:#70689c; font-size:.82rem; font-weight:400; }
.create-aligned-form .full { grid-column:1/-1; }
.aligned-checkbox { flex-direction:row; align-items:center; gap:.65rem; }
.aligned-checkbox input { width:auto; }
.aligned-equipment { border:1px solid #e2dcff; border-radius:12px; padding:1.2rem; background:#f9f7ff; }
.aligned-equipment h3 { margin:0 0 .35rem; color:#5140a8; }
.aligned-help { color:#6e6599; margin:.25rem 0 1rem; font-size:.88rem; }
.aligned-equipment-item { border:1px solid #e1dafa; background:#fff; border-radius:10px; padding:1rem; margin:1rem 0; }
.aligned-item-header { display:flex; align-items:center; justify-content:space-between; gap:1rem; margin-bottom:.7rem; }
.aligned-remove { border:0; background:none; color:#a52e5e; cursor:pointer; }
.aligned-equipment-fields { display:grid; grid-template-columns:2fr 1fr; gap:1rem; }
.aligned-equipment-item label { display:block; font-weight:600; font-size:.9rem; margin:.5rem 0; }
.aligned-equipment-item label input, .aligned-equipment-item label select, .aligned-equipment-item label textarea { display:block; margin-top:.35rem; }
.aligned-equipment > .btn { margin:.7rem .5rem 0 0; }
@media(max-width:650px) { .create-aligned-form, .aligned-equipment-fields { grid-template-columns:1fr; } }
</style>