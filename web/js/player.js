//  One <video> for the whole app, bounded to a shot or segment.
//  /video/<id>.mp4 must answer Range requests (206), otherwise seeking is slow or broken.
const v = document.getElementById('player');
let bounds = { start: 0, end: 0 };
let loop = false;

//  Accepts any item (segment or shot). The #t fragment seeks; timeupdate enforces the end (check in Firefox).
export function load(item, { autoplay = true } = {}){
  bounds = { start: item.start_ms / 1000, end: item.end_ms / 1000 };
  v.src = `${item.video_url}#t=${bounds.start.toFixed(2)},${bounds.end.toFixed(2)}`;
  v.playbackRate = 1;
  if (autoplay) v.play().catch(() => {});
}
v.addEventListener('timeupdate', () => {
  if (v.currentTime >= bounds.end){
    if (loop){ v.currentTime = bounds.start; v.play().catch(() => {}); }
    else v.pause();
  }
});
export const togglePlay = () => (v.paused ? v.play() : v.pause());
export const toggleLoop = () => (loop = !loop);
export const toggleSlow = () => (v.playbackRate = v.playbackRate === 1 ? 0.5 : 1);

//  +delta widens the preview window on both sides, -delta narrows it. Preview only: the submitted
// range is decided in submit.js, never by this window.
export function widenContext(delta){
  bounds.start = Math.max(0, bounds.start - delta);
  bounds.end = Math.max(bounds.start + 0.5, bounds.end + delta);
  v.currentTime = bounds.start;
  v.play().catch(() => {});
}
