//  Wiring: queries, active item / focused shot, strip, shortcuts.
import { state, subscribe } from './state.js';
import * as api from './api.js';
import * as grid from './grid.js';
import * as player from './player.js';
import * as submit from './submit.js';
import * as history from './history.js';

const $ = id => document.getElementById(id);
const sec = ms => (ms / 1000).toFixed(1);
const MODES = ['visual', 'text', 'both'];

try { $('eval').value = localStorage.getItem('eval-id') || ''; } catch {}
$('eval').addEventListener('change', () => { try { localStorage.setItem('eval-id', submit.evalId()); } catch {} });

// queries
/* Latest query wins: a slow earlier response must never overwrite a newer one. The round-trip time
shown is measured here (end to end), which is the number to use for the report. The server's took_ms
includes the transcript lookups. */
let token = 0;
async function runQuery(fn){
  const mine = ++token, t0 = performance.now();
  $('results-info').textContent = 'Searching...';
  const res = await fn();
  if (mine !== token) return;
  setResults(res, Math.round(performance.now() - t0));
}
function setResults(res, ms){
  if (res.error){ $('results-info').textContent = 'Error: ' + res.error; return; }
  state.results = res.items; state.activeIndex = -1; state.active = null; state.shot = null;
  grid.render(); updateTarget();
  $('results-info').textContent = res.items.length
    ? `${res.items.length} results` + (ms != null ? ` · ${ms} ms round trip` : '')
    : 'No results. Try other words or another search mode.';
}
const runSearch = () => {
  const q = $('q').value.trim(); if (!q) return;
  runQuery(() => api.search({ q, mode: $('smode').value, video_id: state.videoFilter, limit: $('limit').value }));
};
//  "More like this" uses the focused shot (strip click) if there is one, else the active item's middle shot.
const moreLikeThis = () => {
  const id = state.shot?.shot_id ?? state.active?.shot_id; if (!id) return;
  runQuery(() => api.similar(id, $('limit').value));
};
const showVideoShots = () => {
  const v = state.active?.video_id ?? state.shot?.video_id; if (!v) return;
  runQuery(async () => { const s = await ensureVideoShots(v); return Array.isArray(s) ? { items: s } : s; });
};

// per-video shot cache (strip, shot-level submit)
// /api/video/<id>/shots. Resolves to an item[] or {error}.
const shotCache = new Map();
async function ensureVideoShots(id){
  if (!shotCache.has(id)){
    shotCache.set(id, api.videoShots(id).then(r => { if (r.error){ shotCache.delete(id); return r; } return r.items; }));
  }
  return shotCache.get(id);
}

// active item / focused shot 
function activate(i){
  const it = state.results[i]; if (!it) return;
  state.activeIndex = i; state.active = it;
  state.shot = it.shot_ids.length === 1 ? it : null;      // multi-shot segment: set once the strip loads
  player.load(it);                                        // preview the whole segment
  showInfo(it); grid.refresh(); updateTarget();
  loadStrip(it);
}
grid.setActivateHandler(activate);

function showInfo(it){
  $('shot-info').textContent = `video ${it.video_id}, ${api.label(it)} (${sec(it.start_ms)}-${sec(it.end_ms)} s)`;
  $('shot-text').textContent = (it.text || '').slice(0, 300);
}

let stripVideo = null;
async function loadStrip(it){
  const shots = await ensureVideoShots(it.video_id);
  if (!Array.isArray(shots) || state.active?.key !== it.key) return;
  state.videoShots = shots;
  if (stripVideo !== it.video_id){
    stripVideo = it.video_id;
    $('strip').innerHTML = shots.map((s, j) =>
      `<img data-j="${j}" src="${s.thumb_url}" loading="lazy" alt="shot ${s.n}">`).join('');
  }
  if (!state.shot) state.shot = shots.find(s => s.shot_id === it.shot_id) ?? null;
  markStrip(); updateTarget();
}
function markStrip(){
  [...$('strip').children].forEach(el => {
    const s = state.videoShots[el.dataset.j];
    el.classList.toggle('active', s?.shot_id === state.shot?.shot_id);
    el.classList.toggle('member', !!state.active?.shot_ids.includes(s?.shot_id));
  });
}
function focusShot(s){
  if (!s) return;
  state.shot = s; player.load(s);
  $('shot-info').textContent = `video ${s.video_id}, shot ${s.n} (${sec(s.start_ms)}-${sec(s.end_ms)} s)`;
  markStrip(); updateTarget();
}
$('strip').addEventListener('click', e => { const j = e.target.dataset?.j; if (j !== undefined) focusShot(state.videoShots[j]); });
const stepShot = d => {
  const j = state.videoShots.findIndex(s => s.shot_id === state.shot?.shot_id) + d;
  if (state.videoShots[j]) focusShot(state.videoShots[j]);
};

// what must be submitted 
const shotTarget = s => ({ shot_id: s.shot_id, shot_ids: [s.shot_id], video_id: s.video_id, n: s.n,
                           start_ms: s.start_ms, end_ms: s.end_ms, label: `shot ${s.n}` });
const segTarget = it => ({ shot_id: it.shot_id, shot_ids: it.shot_ids, video_id: it.video_id, n: it.n,
                           start_ms: it.start_ms, end_ms: it.end_ms,
                           label: it.shot_ids.length > 1 ? `segment of ${it.shot_ids.length} shots` : `shot ${it.n}` });

/* Shot mode: the focused shot (strip click or default middle shot). Segment mode: the merged range.
    For a non-active item (AVS selection) the middle shot's own range is looked up from the video's shot list.
    Returns null if that lookup fails, and submit.js then refuses to continue. */
async function resolveTarget(it, rangeMode, useFocus){
  if (rangeMode === 'shot' && useFocus && state.shot && state.shot.video_id === it.video_id) return shotTarget(state.shot);
  if (rangeMode === 'segment' || it.shot_ids.length === 1) return segTarget(it);
  const shots = await ensureVideoShots(it.video_id);
  const s = Array.isArray(shots) && shots.find(x => x.shot_id === it.shot_id);
  return s ? shotTarget(s) : null;
}
function updateTarget(){
  const el = $('target-info'), it = state.active;
  if (!it){ el.textContent = ''; return; }
  const mode = $('range').value;
  const t = (mode === 'shot' && state.shot?.video_id === it.video_id) ? shotTarget(state.shot)
          : (mode === 'segment' || it.shot_ids.length === 1) ? segTarget(it) : null;
  el.textContent = t ? `Will submit: ${t.label}, ${sec(t.start_ms)}-${sec(t.end_ms)} s` : 'Will submit: loading shot range...';
}
$('range').addEventListener('change', updateTarget);
const doSubmit = () => submit.requestSubmit(resolveTarget);

// controls for ease of use
$('mode').addEventListener('change', e => { state.mode = e.target.value; $('btn-submit-sel').hidden = state.mode !== 'avs'; });
$('btn-similar').onclick = moreLikeThis;
$('btn-video').onclick = showVideoShots;
$('btn-submit').onclick = doSubmit;
$('btn-submit-sel').onclick = doSubmit;
$('btn-loop').onclick = player.toggleLoop;
$('btn-slow').onclick = player.toggleSlow;
$('btn-ctx-').onclick = () => player.widenContext(-2);
$('btn-ctx+').onclick = () => player.widenContext(2);
$('help-btn').onclick = () => toggleHelp();
subscribe(() => { $('btn-submit-sel').textContent = `Submit selected (${state.selected.size})`; });

function filterToActiveVideo(){
  state.videoFilter = state.videoFilter ? null : (state.active?.video_id ?? null);
  const chip = $('video-chip');
  chip.hidden = !state.videoFilter; chip.textContent = `video ${state.videoFilter} ✕`;
}
$('video-chip').onclick = filterToActiveVideo;
const cycleMode = d => { const s = $('smode'); s.value = MODES[(MODES.indexOf(s.value) + d + MODES.length) % MODES.length]; };

function toggleHelp(){
  const h = $('help'); h.hidden = !h.hidden;
  h.innerHTML = `<h2>Shortcuts</h2><pre>/  focus query      Enter  search / confirm submit
Arrows  move        Space  play/pause
S  submit           M  more like this (focused shot)
V  video shots      F  filter next searches to this video
X  select (AVS)     [ ]  search mode prev/next
, .  prev/next shot in video (strip)
?  this help        Esc  cancel/close</pre>`;
}

// keyboard shortcuts
document.addEventListener('keydown', e => {
  const tag = document.activeElement.tagName;
  const typing = tag === 'INPUT' || tag === 'SELECT';
  if (e.key === 'Escape'){ submit.cancel(); $('help').hidden = true; document.activeElement.blur(); return; }
  if (e.key === 'Enter'){
    if (submit.isConfirming()){ e.preventDefault(); submit.confirm(); }
    else if (document.activeElement === $('q')) runSearch();
    return;
  }
  if (typing) return;
  const map = {
    '/': () => $('q').focus(),
    ArrowRight: () => grid.move(1, 0), ArrowLeft: () => grid.move(-1, 0),
    ArrowDown: () => grid.move(0, 1),  ArrowUp: () => grid.move(0, -1),
    ' ': player.togglePlay, s: doSubmit, m: moreLikeThis, v: showVideoShots,
    f: filterToActiveVideo, x: grid.toggleSelect,
    '[': () => cycleMode(-1), ']': () => cycleMode(1),
    ',': () => stepShot(-1), '.': () => stepShot(1), '?': toggleHelp,
  };
  const fn = map[e.key] || map[e.key.toLowerCase()];
  if (fn){ e.preventDefault(); fn(); }
});

history.render();
