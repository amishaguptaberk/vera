// Display labels for the actors the server records (people keep their name; service and specialist
// identifiers such as "specialist:charge_investigator" or "policy_controller" read as titles).
const SMALL = new Set(['and', 'of', 'the']);

export function actorLabel(name: string): string {
  if (/\s/.test(name) && !name.includes(':')) return name;
  const raw = name.includes(':') ? name.slice(name.indexOf(':') + 1) : name;
  const words = raw.replace(/^svc[-_]/, '').split(/[_\-\s]+/).filter(Boolean);
  if (!words.length) return name;
  return words.map((w, i) => (i > 0 && SMALL.has(w) ? w : w.charAt(0).toUpperCase() + w.slice(1))).join(' ');
}

/** Role as shown after a person's name; empty for service actors whose label already says what they are. */
export function roleLabel(role: string, name: string): string {
  if (name.includes(':') || !/\s/.test(name)) return '';
  return role.replace(/_/g, ' ');
}

/**
 * Day heading for grouped activity ("Nov 10"). Absolute on purpose: the server runs its own (demo) clock and
 * sends none, so a browser-relative "Today" could contradict the case's own due labels.
 */
export function dayLabel(iso: string): string {
  return new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

/** Server identifiers read as text: `receipt_required_above_threshold` → "Receipt required above threshold". */
export function sentence(id: string): string {
  const t = id.replace(/_/g, ' ');
  return t.charAt(0).toUpperCase() + t.slice(1);
}
