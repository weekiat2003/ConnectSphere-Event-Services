// Shared display helpers.

export const NOT_SPECIFIED = "Not specified";

export function isMissing(value) {
  return (
    value === null ||
    value === undefined ||
    (typeof value === "string" && !value.trim()) ||
    (Array.isArray(value) && value.length === 0)
  );
}

// Show a value, or "Not specified" when it is missing.
export function orNotSpecified(value) {
  return isMissing(value) ? NOT_SPECIFIED : value;
}

// The API sends naive UTC timestamps (backend app/common/time.py); mark them
// as UTC so the browser shows the viewer's local time.
export function formatTimestamp(iso) {
  if (!iso) return "";
  const text = String(iso);
  return new Date(/(?:Z|[+-]\d{2}:\d{2})$/i.test(text) ? text : `${text}Z`).toLocaleString();
}

// Event dates are calendar dates (no timezone); show them as written.
export function formatEventDate(date, time) {
  if (!date) return NOT_SPECIFIED;
  const [y, m, d] = date.split("-").map(Number);
  const label = new Date(y, m - 1, d).toLocaleDateString(undefined, {
    weekday: "short",
    day: "numeric",
    month: "short",
    year: "numeric",
  });
  return time ? `${label}, ${time}` : label;
}
