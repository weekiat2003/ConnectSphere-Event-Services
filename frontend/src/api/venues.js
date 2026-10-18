import apiClient from "./client";

function toSearchQuery(criteria) {
  const params = new URLSearchParams();

  for (const [key, value] of Object.entries(criteria)) {
    if (Array.isArray(value)) {
      for (const item of value) {
        params.append(key, item);
      }
    } else if (
      value !== "" &&
      value !== null &&
      value !== undefined
    ) {
      params.append(key, value);
    }
  }

  return params.toString();
}

export default {
  // Get all venues
  listVenues: () => apiClient.get("/venues"),

  // Venue catalogue
  getVenue: (id) => apiClient.get(`/venues/${id}`),

  create: (payload) =>
    apiClient.post("/venues", payload),

  update: (id, payload) =>
    apiClient.put(`/venues/${id}`, payload),

  deactivate: (id) =>
    apiClient.delete(`/venues/${id}`),

  // Availability calendar
  getCalendar: (id, start, end) =>
    apiClient.get(`/venues/${id}/calendar`, {
      params: { start, end },
    }),

  getCombinedCalendar: (start, end) =>
    apiClient.get("/venues/calendar", {
      params: { start, end },
    }),

  addUnavailability: (id, payload) =>
    apiClient.post(`/venues/${id}/unavailability`, payload),

  removeUnavailability: (id, blockId) =>
    apiClient.delete(
      `/venues/${id}/unavailability/${blockId}`
    ),

  myFlags: () =>
    apiClient.get("/venues/flags/mine"),

  resolveFlag: (id) =>
    apiClient.post(`/venues/flags/${id}/resolve`),

  // Search venues
  search: (criteria) =>
    apiClient.get(
      `/venues/search?${toSearchQuery(criteria)}`
    ),

  searchOptions: () =>
    apiClient.get("/venues/search/options"),

  // Submit booking request
  submitBooking: (payload) =>
    apiClient.post("/venues/bookings", payload),

  // Event Coordinator: booking requests
  getMyBookings: () =>
    apiClient.get("/venues/bookings/my"),

  withdrawBooking: (bookingId) =>
    apiClient.post(
      `/venues/bookings/${bookingId}/withdraw`
    ),

  // Venue Staff: pending booking requests
  getPendingBookings: () =>
    apiClient.get("/venues/bookings/pending"),

  // Venue Staff: approve booking
  approveBooking: (bookingId) =>
    apiClient.post(
      `/venues/bookings/${bookingId}/approve`
    ),

  // Venue Staff: reject booking
  // Both reason and alternativeSuggestion are optional
  rejectBooking: (bookingId, payload = {}) =>
    apiClient.post(
      `/venues/bookings/${bookingId}/reject`,
      payload
    ),

  // Event Coordinator: approval notifications
  getConfirmationNotices: () =>
    apiClient.get(
      "/venues/bookings/confirmation-notices"
    ),

  // Event Coordinator: rejection notifications
  getRejectionNotices: () =>
    apiClient.get(
      "/venues/bookings/rejection-notices"
    ),

  getApprovedBookings: () =>
    apiClient.get("/venues/bookings/approved"),

  cancelBooking: (bookingId, payload = {}) =>
    apiClient.post(
      `/venues/bookings/${bookingId}/cancel`,
      payload
    ),
};
