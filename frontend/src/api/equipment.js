import apiClient from "./client";

export default {
  // Equipment catalogue (Technical Support Staff)
  listItems: () => apiClient.get("/equipment/items"),
  createItem: (payload) => apiClient.post("/equipment/items", payload),
  markUnavailable: (id, reason) =>
    apiClient.post(`/equipment/items/${id}/mark-unavailable`, { reason }),
  markActive: (id) => apiClient.post(`/equipment/items/${id}/mark-active`),
};