// [B] Two-step submit: resolve range -> confirm bar -> POST each target -> verdict + history.
import { state, emit } from './state.js';
import * as api from './api.js';
import * as history from './history.js';
import { refresh } from './grid.js';

const $ = id => document.getElementById(id);
const sec = ms => (ms / 1000).toFixed(1);
let pending = null;      // resolved targets awaiting confirmation
let token = 0;           // lets Esc cancel while ranges are still being resolved
export const evalId = () => $('eval').value.trim();
export const isConfirming = () => pending !== null;

// [B] resolveTarget(item, rangeMode, useFocus) comes from main.js (needs the per-video shot cache).
export async function requestSubmit(resolveTarget){
  if (state.submitting) return;
  if (!evalId()){ showVerdict('ERROR', 'Enter the DRES evaluation ID first (top bar).'); $('eval').focus(); return; }
  const multi = state.mode === 'avs' && state.selected.size > 0;
  const items = multi ? [...state.selected.values()] : (state.active ? [state.active] : []);
  if (!items.length) return;
  const mine = ++token;
  $('confirm').hidden = false; $('confirm').textContent = 'Resolving shot range...';
  const targets = [];
  for (const it of items){
    const t = await resolveTarget(it, $('range').value, !multi);
    if (mine !== token) return;                                   // cancelled meanwhile
    if (!t){ cancel(); showVerdict('ERROR', 'Could not resolve the shot range (video shots failed to load).'); return; }
    targets.push(t);
  }
  pending = targets;
  const t = targets[0];
  $('confirm').textContent = targets.length === 1
    ? `Submit video ${t.video_id}, ${t.label} (${sec(t.start_ms)}-${sec(t.end_ms)} s) to evaluation ${evalId()}? Enter = yes, Esc = no`
    : `Submit ${targets.length} selected items to evaluation ${evalId()}? Enter = yes, Esc = no`;
}
export function cancel(){ token++; pending = null; $('confirm').hidden = true; }

// [B] Sequential, per-item status; the button is locked while in flight.
export async function confirm(){
  if (!pending || state.submitting) return;
  const targets = pending; const evaluation_id = evalId(); cancel();
  state.submitting = true; $('btn-submit').disabled = true;
  const tally = { CORRECT: 0, WRONG: 0, OTHER: 0 };
  for (const t of targets){
    const res = await api.submit({ evaluation_id, video_id: t.video_id, start_ms: t.start_ms, end_ms: t.end_ms });
    const { verdict, message } = normalise(res);
    history.add({ shot_id: t.shot_id, shot_ids: t.shot_ids, video_id: t.video_id, n: t.n,
                  start_ms: t.start_ms, end_ms: t.end_ms, label: t.label, verdict, message });
    tally[verdict] !== undefined ? tally[verdict]++ : tally.OTHER++;
    showVerdict(verdict, message, targets.length > 1 ? tally : null);
  }
  state.submitting = false; $('btn-submit').disabled = false;
  if (targets.length > 1) state.selected.clear();
  refresh(); emit();
}

// [A] Backend returns dres_client's dict: {http_status, accepted, response}. Failures at our API arrive as {error}.
// ASSUMPTION about DRES v2 (verify on the practice server): response.submission = CORRECT | WRONG | INDETERMINATE |
// UNDECIDABLE, response.description = text, and HTTP 412 = no active task.
function normalise(res){
  if (res.error) return { verdict: 'ERROR', message: res.error };
  const raw = res.response || {};
  if (res.accepted === false || (res.http_status && res.http_status >= 400)){
    const hint = res.http_status === 412 ? 'No active task. ' : '';
    return { verdict: 'ERROR', message: `${hint}HTTP ${res.http_status} ${raw.description || raw.raw || ''}`.trim() };
  }
  if (!raw.submission) return { verdict: 'ERROR', message: 'Unexpected DRES response: ' + JSON.stringify(raw).slice(0, 120) };
  return { verdict: raw.submission, message: raw.description || '' };
}

function showVerdict(verdict, message, tally){
  const el = $('verdict');
  el.hidden = false; el.className = verdict;
  const icon = { CORRECT: '✔', WRONG: '✘' }[verdict] || '!';
  el.textContent = `${icon} ${verdict} ${message}` + (tally ? ` (${tally.CORRECT} correct / ${tally.WRONG} wrong)` : '');
}
