// [B] ALL network calls live here. Add ?mock=1 to the URL to use fixtures in mock/.
// [A] The endpoints below are the PROPOSED contract; adjust once agreed with Partner A.
const MOCK = new URLSearchParams(location.search).has('mock');
const delay = ms => new Promise(r => setTimeout(r, ms));

// [B] Normalises every failure to {error, status}. The UI never sees raw exceptions.
async function request(url, opts, mockFile){
  try{
    if (MOCK){
      await delay(200 + Math.random()*300);
      return await (await fetch('mock/' + mockFile)).json();
    }
    const r = await fetch(url, opts);
    const body = await r.json().catch(() => ({}));
    // [A] ASSUMPTION: errors are {error:"..."} with a proper HTTP status code.
    if (!r.ok) return { error: body.error || r.statusText, status: r.status };
    return body;
  }catch(e){
    return { error: 'Backend unreachable', status: 0 };
  }
}

// [A] GET /api/search?q&w&video&k -> Result[] (CLIP text embedding + transcript FTS, blended by w).
// [A] AGREE the direction of w (1 = all visual? or all text?) so the slider labels are correct.
export function search({q, w, video, k}){
  const p = new URLSearchParams({q, w, k});
  if (video) p.set('video', video);
  return request('/api/search?' + p, {}, 'search.json');
}

// [A] GET /api/similar?shot_id=... -> Result[] (nearest neighbours in CLIP space).
export const similar = shot_id =>
  request('/api/similar?shot_id=' + encodeURIComponent(shot_id), {}, 'similar.json');

// [A] POST /api/image-search, multipart field "file" (assumed) -> Result[] (image embedded with CLIP).
export function imageSearch(file, k = 100){
  const fd = new FormData(); fd.append('file', file); fd.append('k', k);
  return request('/api/image-search', { method: 'POST', body: fd }, 'search.json');
}

// [A] GET /api/video/<id>/shots -> Result[] ordered by n (neighbour strip, "all shots of video").
export const videoShots = id =>
  request(`/api/video/${encodeURIComponent(id)}/shots`, {}, 'video_shots.json');

// [A] POST /api/submit {video_id,start_ms,end_ms}. Backend holds the DRES credentials and forwards.
// [A] PROPOSED response: {status:"ok"|"error", verdict:"CORRECT"|"WRONG"|"DUPLICATE"|"INDETERMINATE"|null, message}
// [B] Mock mode: ?mock=1&fail=wrong|dup|none picks a fixture (default: correct).
export function submit({video_id, start_ms, end_ms}){
  const fail = new URLSearchParams(location.search).get('fail');
  const file = { wrong:'submit_wrong.json', dup:'submit_dup.json', none:'submit_none.json' }[fail] || 'submit_ok.json';
  return request('/api/submit', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({video_id, start_ms, end_ms}),
  }, file);
}

// [A] OPTIONAL GET /api/status -> {logged_in, task_active, task_name, time_left_s}.
// [B] Polled every 5 s so we know if a task is active before submitting.
export const status = () => request('/api/status', {}, 'status.json');
