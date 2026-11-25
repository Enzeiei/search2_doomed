// [B] Results grid: render, click, arrow navigation, AVS selection (persists across queries), verdict badges.
import { state, emit } from './state.js';
import { summary } from './history.js';
import { label } from './api.js';

const grid = document.getElementById('grid');
let onActivate = () => {};
export const setActivateHandler = fn => (onActivate = fn);

// [A] thumb_url is /thumb/<shot_id>.png, read from the video's zip on each request.
export function render(){
  grid.innerHTML = '';
  state.results.forEach((r, i) => {
    const c = document.createElement('div');
    c.className = 'cell';
    if (r.text) c.title = r.text;
    c.innerHTML = `<img loading="lazy" src="${r.thumb_url}" alt="">
      ${r.shot_ids.length > 1 ? `<span class="grp">+${r.shot_ids.length - 1}</span>` : ''}
      <div class="meta">${i + 1}. ${r.video_id} ${label(r)}</div>`;
    c.addEventListener('click', () => onActivate(i));
    grid.appendChild(c);
  });
  refresh();
}

// [B] Classes only, so thumbnails are not reloaded. A segment is greyed only if ALL its shots were WRONG.
export function refresh(){
  [...grid.children].forEach((c, i) => {
    const r = state.results[i];
    c.classList.toggle('active', i === state.activeIndex);
    c.classList.toggle('selected', state.selected.has(r.key));
    c.classList.remove('CORRECT', 'WRONG');
    c.querySelector('.badge')?.remove();
    const s = summary(r.shot_ids);
    let text = null;
    if (s.CORRECT){ c.classList.add('CORRECT'); text = 'CORRECT'; }
    else if (s.WRONG === r.shot_ids.length){ c.classList.add('WRONG'); text = 'WRONG'; }
    else if (s.WRONG){ text = `WRONG ${s.WRONG}/${r.shot_ids.length}`; }
    else if (s.OTHER){ text = s.other; }
    if (text) c.insertAdjacentHTML('beforeend', `<span class="badge">${text}</span>`);
  });
  grid.children[state.activeIndex]?.scrollIntoView({ block: 'nearest' });
}

export function move(dx, dy){
  if (!state.results.length) return;
  const cols = getComputedStyle(grid).gridTemplateColumns.split(' ').length;
  const from = state.activeIndex < 0 ? 0 : state.activeIndex;
  onActivate(Math.min(state.results.length - 1, Math.max(0, from + dx + dy * cols)));
}

// [B] AVS: toggle the active item in the selection (key X). Stored as items so it survives new queries.
export function toggleSelect(){
  const it = state.active; if (!it) return;
  state.selected.has(it.key) ? state.selected.delete(it.key) : state.selected.set(it.key, it);
  refresh(); emit();
}
