// [B] Results grid: render, click select, arrow navigation, AVS multi-select, verdict badges.
import { state, emit } from './state.js';
import { verdictFor } from './history.js';

const grid = document.getElementById('grid');
let onActivate = () => {};
export const setActivateHandler = fn => (onActivate = fn);

// [B] Rebuild from state.results. Fixed aspect ratio + lazy loading avoids reflow with 100+ thumbs.
// [A] thumb_url must be a relative URL served by the backend, e.g. /media/thumb/<video>/<n>.png.
export function render(){
  grid.innerHTML = '';
  state.results.forEach((r, i) => {
    const c = document.createElement('div');
    c.className = 'cell';
    c.innerHTML = `<img loading="lazy" src="${r.thumb_url}" alt="">
      <div class="meta">${r.video_id} #${r.n} · ${(r.score ?? 0).toFixed(2)}</div>`;
    c.addEventListener('click', () => onActivate(i));
    grid.appendChild(c);
  });
  refresh();
  document.getElementById('results-info').textContent = state.results.length + ' results';
}

// [B] Update classes only (active / selected / verdict), without reloading thumbnails.
export function refresh(){
  [...grid.children].forEach((c, i) => {
    const r = state.results[i];
    c.classList.toggle('active', i === state.activeIndex);
    c.classList.toggle('selected', state.selected.has(r.shot_id));
    c.classList.remove('CORRECT','WRONG','DUPLICATE');
    c.querySelector('.badge')?.remove();
    const v = verdictFor(r.shot_id);
    if (v){ c.classList.add(v); c.insertAdjacentHTML('beforeend', `<span class="badge">${v}</span>`); }
  });
  grid.children[state.activeIndex]?.scrollIntoView({block:'nearest'});
}

// [B] Arrow keys. Column count is read from the CSS grid, so it adapts to window width.
export function move(dx, dy){
  if (!state.results.length) return;
  const cols = getComputedStyle(grid).gridTemplateColumns.split(' ').length;
  const from = state.activeIndex < 0 ? 0 : state.activeIndex;
  onActivate(Math.min(state.results.length - 1, Math.max(0, from + dx + dy * cols)));
}

// [B] AVS: toggle the active shot in the selection (key X).
export function toggleSelect(){
  const id = state.active?.shot_id; if (!id) return;
  state.selected.has(id) ? state.selected.delete(id) : state.selected.add(id);
  refresh(); emit();
}

// [B] TODO (nice-to-have): "group adjacent shots": collapse consecutive n of the same video_id into one cell.
