// [B] One <video> element for the whole app, bounded to the shot.
// [A] Needs video_url served with HTTP Range support, otherwise seeking is slow or broken.
const v = document.getElementById('player');
let bounds = { start: 0, end: 0 };
let loop = false;

// [B] Load a shot. The #t fragment does the first seek; the timeupdate guard enforces the end (test in Firefox).
export function load(shot, {autoplay = true} = {}){
  bounds = { start: shot.start_ms / 1000, end: shot.end_ms / 1000 };
  v.src = `${shot.video_url}#t=${bounds.start.toFixed(2)},${bounds.end.toFixed(2)}`;
  v.playbackRate = 1;
  if (autoplay) v.play().catch(() => {});
}

// [B] Pause or loop at the end of the shot.
v.addEventListener('timeupdate', () => {
  if (v.currentTime >= bounds.end){
    if (loop){ v.currentTime = bounds.start; v.play().catch(()=>{}); }
    else v.pause();
  }
});

export const togglePlay = () => (v.paused ? v.play() : v.pause());
export const toggleLoop = () => (loop = !loop);
export const toggleSlow = () => (v.playbackRate = v.playbackRate === 1 ? 0.5 : 1);

// [B] Move the preview window by delta seconds (negative = pull in the start earlier... see note).
// Convention here: widenContext(+2) extends both sides by 2 s; widenContext(-2) shrinks back.
// NOTE: only changes what is PREVIEWED. The submitted range is still the shot's start_ms/end_ms.
export function widenContext(delta){
  bounds.start = Math.max(0, bounds.start - delta);
  bounds.end = Math.max(bounds.start + 0.5, bounds.end + delta);
  v.currentTime = bounds.start;
  v.play().catch(()=>{});
}
