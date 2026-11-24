// [B] Submission log, persisted in localStorage so a page refresh does not lose it.
const KEY = 'submissions-v1';
let items = [];
try { items = JSON.parse(localStorage.getItem(KEY) || '[]'); } catch { items = []; }

// [B] Record: {shot_id, video_id, n, start_ms, end_ms, verdict, message}
export function add(entry){
  items.unshift({ t: Date.now(), ...entry });
  try { localStorage.setItem(KEY, JSON.stringify(items)); } catch {}
  render();
}

// [B] Latest verdict for a shot (grid badges; WRONG shots get greyed out so nobody resubmits).
export const verdictFor = shot_id => items.find(i => i.shot_id === shot_id)?.verdict || null;

export function render(){
  document.getElementById('history').innerHTML = items.slice(0, 50).map(i =>
    `<li>${new Date(i.t).toLocaleTimeString()} ${i.video_id} #${i.n} <b>${i.verdict ?? 'ERROR'}</b></li>`).join('');
}

// [B] Clear between practice runs and the live event.
export function clear(){ items = []; localStorage.removeItem(KEY); render(); }
