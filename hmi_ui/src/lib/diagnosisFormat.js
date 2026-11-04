// Turn the seven-section diagnosis markdown into blocks for rendering.
// Kept tiny and dependency-free; only the shapes the backend produces.

const LABEL = /^(CONFIRMED|HYPOTHESIS|UNKNOWN)\b[:\s-]*/i;

export function parseDiagnosis(text = '') {
  const sections = [];
  let current = null;
  let note = '';
  for (const raw of String(text).split(/\r?\n/)) {
    const line = raw.trim();
    if (!line) continue;
    if (line.startsWith('>')) { note = line.replace(/^>\s*/, ''); continue; }
    const heading = line.match(/^#{1,4}\s*(?:\d+[.)]\s*)?(.+)$/);
    if (heading) {
      current = { title: heading[1].replace(/\*\*/g, '').trim(), items: [] };
      sections.push(current);
      continue;
    }
    if (!current) { current = { title: '', items: [] }; sections.push(current); }
    let body = line.replace(/^([-*•]|\d+[.)])\s*/, '').replace(/\*\*/g, '');
    let label = null;
    const m = body.match(LABEL);
    if (m) { label = m[1].toUpperCase(); body = body.slice(m[0].length); }
    current.items.push({ label, text: body });
  }
  return { note, sections };
}
