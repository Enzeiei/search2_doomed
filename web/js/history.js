//  Submission log in localStorage (key v2: entries carry shot_ids, so segment submits mark every shot).
const KEY = 'submissions-v2';
let items = [];
try { items = JSON.parse(localStorage.getItem(KEY) || '[]'); } catch { items = []; }

// entry: {shot_id, shot_ids, video_id, n, start_ms, end_ms, verdict, message, label}
export function add(entry){
  items.unshift({ t: Date.now(), ...entry });
  try { localStorage.setItem(KEY, JSON.stringify(items)); } catch {}
  render();
}

//  Latest non-ERROR verdict per shot, summarised over a list of shot ids.
export function summary(ids){
  const out = { CORRECT: 0, WRONG: 0, OTHER: 0, other: null };
  for (const id of ids){
    const e = items.find(i => i.verdict !== 'ERROR' && i.shot_ids?.includes(id));
    if (!e) continue;
    if (e.verdict === 'CORRECT') out.CORRECT++;
    else if (e.verdict === 'WRONG') out.WRONG++;
    else { out.OTHER++; out.other = e.verdict; }
  }
  return out;
}

export function render(){
  document.getElementById('history').innerHTML = items.slice(0, 50).map(i =>
    `<li>${new Date(i.t).toLocaleTimeString()} ${i.video_id} ${i.label ?? ''} <b>${i.verdict ?? 'ERROR'}</b></li>`).join('');
}