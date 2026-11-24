// [B] Wiring: events, search flow, shortcuts, status polling.
import { state } from './state.js';
import * as api from './api.js';
import * as grid from './grid.js';
import * as player from './player.js';
import * as submit from './submit.js';
import * as history from './history.js';

const $ = id => document.getElementById(id);

// ---------- results / active shot ----------
function setResults(res){
  if (res.error){ $('results-info').textContent = 'Error: ' + res.error; return; }
  state.results = res; state.activeIndex = -1; state.active = null;
  grid.render();
  if (!res.length) $('results-info').textContent = 'No results. Try other words or move the slider.';
}

// [B] Select a shot: preview, info line, neighbour strip.
function activate(i){
  state.activeIndex = i; state.active = state.results[i];
  const s = state.active; if (!s) return;
  player.load(s);
  $('shot-info').textContent =
    `${s.video_title ?? ''} ${s.video_id} #${s.n} (${(s.start_ms/1000).toFixed(1)}-${(s.end_ms/1000).toFixed(1)} s)`;
  grid.refresh();
  loadStrip(s.video_id);
}
grid.setActivateHandler(activate);

// ---------- searches ----------
async function runSearch(){
  const q = $('q').value.trim(); if (!q) return;
  setResults(await api.search({ q, w: $('w').value, video: state.videoFilter, k: $('k').value }));
}
async function moreLikeThis(){ if (state.active) setResults(await api.similar(state.active.shot_id)); }
async function showVideoShots(){ if (state.active) setResults(await api.videoShots(state.active.video_id)); }

// [B] Neighbour strip. [A] /api/video/<id>/shots must return shots ordered by n.
async function loadStrip(video_id){
  if (state.videoShots[0]?.video_id === video_id) return markStrip();
  const res = await api.videoShots(video_id);
  if (res.error) return;
  state.videoShots = res;
  $('strip').innerHTML = res.map((s, j) =>
    `<img data-j="${j}" src="${s.thumb_url}" loading="lazy" alt="shot ${s.n}">`).join('');
  markStrip();
}
function markStrip(){
  [...$('strip').children].forEach(el =>
    el.classList.toggle('active', state.videoShots[el.dataset.j]?.shot_id === state.active?.shot_id));
}
$('strip').addEventListener('click', e => {
  const j = e.target.dataset?.j; if (j === undefined) return;
  state.active = state.videoShots[j]; player.load(state.active); markStrip();  // neighbour need not be in grid
});

// [B] Previous/next shot in the same video (, and .).
function stepShot(d){
  const j = state.videoShots.findIndex(s => s.shot_id === state.active?.shot_id) + d;
  if (state.videoShots[j]){ state.active = state.videoShots[j]; player.load(state.active); markStrip(); }
}

// [B] Video filter chip. [A] search must honour ?video=<id>.
function filterToActiveVideo(){
  state.videoFilter = state.videoFilter ? null : (state.active?.video_id ?? null);
  const chip = $('video-chip');
  chip.hidden = !state.videoFilter; chip.textContent = 'video ' + state.videoFilter + ' ✕';
}

// ---------- DRES status (optional [A] /api/status) ----------
async function pollStatus(){
  const s = await api.status();
  $('dres-status').textContent = s.error ? 'DRES: unknown'
    : `DRES: ${s.task_active ? 'task active ' + (s.task_name ?? '') : 'no active task'}`;
}

// ---------- controls ----------
$('w').addEventListener('input', e => $('w-out').value = e.target.value);
$('mode').addEventListener('change', e => { state.mode = e.target.value; $('btn-submit-sel').hidden = state.mode !== 'avs'; });
$('img').addEventListener('change', async e => e.target.files[0] && setResults(await api.imageSearch(e.target.files[0], $('k').value)));
$('btn-similar').onclick = moreLikeThis;
$('btn-video').onclick = showVideoShots;
$('btn-submit').onclick = submit.requestSubmit;
$('btn-submit-sel').onclick = submit.requestSubmit;
$('btn-loop').onclick = player.toggleLoop;
$('btn-slow').onclick = player.toggleSlow;
$('btn-ctx-').onclick = () => player.widenContext(-2);
$('btn-ctx+').onclick = () => player.widenContext(2);
$('video-chip').onclick = filterToActiveVideo;
$('help-btn').onclick = () => toggleHelp();

function toggleHelp(){
  const h = $('help'); h.hidden = !h.hidden;
  h.innerHTML = `<h2>Shortcuts</h2><pre>/  focus query      Enter  search / confirm submit
Arrows  move        Space  play/pause
S  submit           M  more like this
V  video shots      F  filter to this video
X  select (AVS)     [ ]  weight -/+
, .  prev/next shot in video
?  this help        Esc  cancel/close</pre>`;
}

// ---------- shortcuts ----------
const nudgeW = d => { const w = $('w'); w.value = Math.min(1, Math.max(0, +w.value + d)).toFixed(1); $('w-out').value = w.value; };
document.addEventListener('keydown', e => {
  const typing = document.activeElement.tagName === 'INPUT' || document.activeElement.tagName === 'SELECT';
  if (e.key === 'Escape'){ submit.cancel(); $('help').hidden = true; document.activeElement.blur(); return; }
  if (e.key === 'Enter'){
    if (submit.isConfirming()){ e.preventDefault(); submit.confirm(); }
    else if (document.activeElement === $('q')) runSearch();
    return;
  }
  if (typing) return;   // other shortcuts are ignored while typing
  const map = {
    '/': () => $('q').focus(),
    ArrowRight: () => grid.move(1, 0), ArrowLeft: () => grid.move(-1, 0),
    ArrowDown: () => grid.move(0, 1),  ArrowUp: () => grid.move(0, -1),
    ' ': player.togglePlay, s: submit.requestSubmit, m: moreLikeThis, v: showVideoShots,
    f: filterToActiveVideo, x: grid.toggleSelect,
    '[': () => nudgeW(-0.1), ']': () => nudgeW(0.1),
    ',': () => stepShot(-1), '.': () => stepShot(1), '?': toggleHelp,
  };
  const fn = map[e.key] || map[e.key.toLowerCase()];
  if (fn){ e.preventDefault(); fn(); }
});

history.render();
pollStatus(); setInterval(pollStatus, 5000);
