import apiClient from "./client";

export default {
  getForEvent: (eventId) => apiClient.get(`/change-requests/events/${eventId}`),
  submit: (eventId, payload) => apiClient.post(`/change-requests/events/${eventId}`, payload),
  listAssigned: () => apiClient.get("/change-requests/assigned"),
  getCatalogue: () => apiClient.get("/change-requests/catalogue"),
  requestWithdrawal: (eventId, payload) => apiClient.post(`/change-requests/events/${eventId}/withdrawal`, payload),
  getReviewQueue: () => apiClient.get("/change-requests/review"),
  getReviewDetail: (requestId) => apiClient.get(`/change-requests/${requestId}/review`),
  processChange: (requestId, confirmed = false) =>
    apiClient.post(`/change-requests/${requestId}/process`, { confirmed }),
  rejectChange: (id, reason, confirmed = false) =>
    apiClient.post(`/change-requests/${id}/reject`, { reason, confirmed }),
  startReReview: (requestId, confirmed = false) =>
    apiClient.post(`/change-requests/${requestId}/re-review`, { confirmed }),
  applyReReview: (requestId, confirmed = false) =>
    apiClient.post(`/change-requests/${requestId}/apply`, { confirmed }),
};