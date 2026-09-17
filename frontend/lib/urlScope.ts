/** The property a link asked for (`?property_id=`), read once at load time
 * inside a fetch callback so pages that own their own scope state can honor
 * a deep link from the setup checklist without a Suspense boundary. */
export function requestedPropertyId(): number | null {
  if (typeof window === "undefined") return null;
  const raw = new URLSearchParams(window.location.search).get("property_id");
  const id = raw ? Number(raw) : NaN;
  return Number.isInteger(id) && id > 0 ? id : null;
}
