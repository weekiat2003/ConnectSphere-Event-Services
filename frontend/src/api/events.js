import apiClient from "./client";

export default {
  createEvent: (payload) => apiClient.post("/events", payload),
  saveDraft: (payload) => apiClient.post("/events/drafts", payload),
  listDrafts: () => apiClient.get("/events/drafts"),
  updateDraft: (id, payload) => apiClient.put(`/events/drafts/${id}`, payload),
  deleteDraft: (id) => apiClient.delete(`/events/drafts/${id}`),
  updateEvent: (id, payload) => apiClient.put(`/events/${id}/update`, payload),
  submitEvent: (id) => apiClient.post(`/events/${id}/submit`),
  confirmEvent: (id) => apiClient.post(`/events/${id}/confirm`),
  myEvents: () => apiClient.get("/events/mine"),
  assignedEvents: () => apiClient.get("/events/assigned"),
  allEvents: () => apiClient.get("/events"),
  getEvent: (id) => apiClient.get(`/events/${id}`),
  getOutcome: (id) => apiClient.get(`/events/${id}/outcome`),
  requestClarification: (id, comments) => apiClient.post(`/events/${id}/clarification`, { comments }),
  respondClarification: (id, payload) => apiClient.post(`/events/${id}/clarification/response`, payload),
  approveEvent: (id, comments, confirmed = false) => apiClient.post(`/events/${id}/approve`, { comments, confirmed }),
  rejectEvent: (id, reason, confirmed = false) => apiClient.post(`/events/${id}/reject`, { reason, confirmed }),
  cancelEvent: (id, reason, confirmed = false) => apiClient.post(`/events/${id}/cancel`, { reason, confirmed }),
  deleteClarification: (eventId, reviewId) => apiClient.delete(`/events/${eventId}/clarification/${reviewId}`),
  resubmitEvent: (id, payload) => apiClient.post(`/events/${id}/resubmit`, payload),
  changeStatus: (id, statusValue, reason) => apiClient.post(`/events/${id}/status`, { status: statusValue, reason }),
  reviewSafety: (id, payload) => apiClient.post(`/events/${id}/safety-review`, payload),
  // Operational Safety Check (Safety Officer only)
  listSafetyReviews: () => apiClient.get("/events/safety-reviews"),
  getSafetyAssessment: (id) => apiClient.get(`/events/${id}/safety-assessment`),
  saveSafetyAssessment: (id, factorAssessments) =>
    apiClient.put(`/events/${id}/safety-assessment`, { factorAssessments }),

  // Added: Coordinators view unassigned events for planning visibility (view-only, no claim/self-assign)
  unassignedEvents: () => apiClient.get("/events/unassigned"),

  // Added: Previous coordinator retains read-only visibility after reassignment
  coordinatorCalendar: () => apiClient.get("/events/calendar"),

  // Event Coordinator Lead (Notification System, ISP-103/105).
  // autoAssign: the Lead lets the system pick the least-busy Coordinator.
  autoAssign: (id) => apiClient.post(`/events/${id}/auto-assign`),
  listCoordinators: () => apiClient.get("/events/coordinators"),
  leadAssign: (id, coordinatorId, confirmed = false) =>
    apiClient.post(`/events/${id}/assign`, { coordinatorId, confirmed }),
  leadReassign: (id, coordinatorId, confirmed = false) =>
    apiClient.post(`/events/${id}/lead-reassign`, { coordinatorId, confirmed }),
  supervision: () => apiClient.get("/events/supervision"),

  // Reassignment requests: a Coordinator asks, a Lead decides (Week 7).
  requestReassignment: (id, reason) => apiClient.post(`/events/${id}/reassignment-request`, { reason }),
  getReassignmentRequest: (id) => apiClient.get(`/events/${id}/reassignment-request`),
  withdrawReassignmentRequest: (id) => apiClient.delete(`/events/${id}/reassignment-request`),
  declineReassignmentRequest: (id, note) =>
    apiClient.post(`/events/${id}/reassignment-request/decline`, { note }),
  listReassignmentRequests: () => apiClient.get("/events/reassignment-requests"),
  assignmentHistory: (id) => apiClient.get(`/events/${id}/assignment-history`),
};
