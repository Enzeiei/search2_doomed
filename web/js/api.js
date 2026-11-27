const params = new URLSearchParams(location.search);
export const MOCK = params.has('mock');
const delay = ms => new Promise(r => setTimeout(r, ms));

export const videoUrl = id => (MOCK ? `mock/videos/${id}.mp4` : `/video/${id}.mp4`);
export const shotNumber = id => { const m = /^shot(\d+)_(\d+)$/.exec(id); return m ? +m[2] : null; };
export const label = it => it.shot_ids.length > 1
  ? `shots ${shotNumber(it.shot_ids[0])}-${shotNumber(it.shot_ids[it.shot_ids.length - 1])}`
  : `shot ${it.n}`;

// FastAPI errors are {"detail": "..."} (or a list for 422); flatten to one string.
function describe(body){
  const d = body && (body.detail ?? body.error);
  if (!d) return '';
  return Array.isArray(d) ? d.map(x => `${(x.loc || []).slice(1).join('.')}: ${x.msg}`).join('; ') : String(d);
}

// Never throws. Failures come back as {error, status}.
async function request(url, opts, mockFile){
  try{
    if (MOCK){
      await delay(150 + Math.random() * 250);
      const r = await fetch('mock/' + mockFile);
      return await r.json();
    }
    const r = await fetch(url, opts);
    const body = await r.json().catch(() => ({}));
    if (!r.ok) return { error: describe(body) || r.statusText, status: r.status };
    return body;
  }catch(e){
    return { error: 'Backend unreachable', status: 0 };
  }
}

//  A grouped segment has no shot_id. We key it by its middle shot, which is also the shot the
// backend uses for thumb_url (shot_ids[len // 2]).
export function segmentToItem(seg){
  const ids = seg.shot_ids, rep = ids[Math.floor(ids.length / 2)];
  return { key: rep, shot_id: rep, shot_ids: ids, video_id: seg.video_id, n: shotNumber(rep),
           start_ms: seg.start_ms, end_ms: seg.end_ms, score: seg.score,
           thumb_url: seg.thumb_url, video_url: seg.video_url, text: seg.text || '' };
}
//  /api/video/<id>/shots returns bare shots, with no n and no video_url.
export function shotToItem(video_id, s){
  return { key: s.shot_id, shot_id: s.shot_id, shot_ids: [s.shot_id], video_id, n: shotNumber(s.shot_id),
           start_ms: s.start_ms, end_ms: s.end_ms, score: null,
           thumb_url: s.thumb_url, video_url: videoUrl(video_id), text: '' };
}
const asItems = res => (res.error ? res : { items: res.results.map(segmentToItem) });

// GET /api/search?q&mode&video_id&limit -> {query, took_ms, results: segment[]}.
export async function search({ q, mode, w, video_id, video, limit}){
  const p = new URLSearchParams({ q, limit: limit ?? k ?? 60 });
  if (mode) p.set('mode', mode);
  if (w !== undefined && w !== null) p.set('w', w);
  const v = video_id ?? video;
  if (v) p.set('video_id', v);
  return asItems(await request('/api/search?' + p, {}, 'search.json'));
}

export async function similar(shot_id, limit = 60){
  return asItems(await request(`/api/similar/${encodeURIComponent(shot_id)}?limit=${limit}`, {}, 'similar.json'));
}
//  GET /api/video/{id}/shots -> {video_id, shots:[{shot_id,start_ms,end_ms,thumb_url}]}; 404 if unknown.
export async function   videoShots(id){
  const res = await request(`/api/video/${encodeURIComponent(id)}/shots`, {}, `video_shots/${id}.json`);
  return res.error ? res : { items: res.shots.map(s => shotToItem(res.video_id ?? id, s)) };
}

// POST /api/submit {evaluation_id, video_id, start_ms, end_ms} ->
// {http_status, accepted, response:{...DRES body}}. should resolve to 503 if DRES credentials are not set on the server.
export async function submit({ evaluation_id, video_id, start_ms, end_ms }){
  const fail = params.get('fail');
  if (MOCK && fail === 'net') return { error: 'Backend unreachable', status: 0 };
  const file = { wrong: 'submit_wrong.json', indet: 'submit_indet.json', none: 'submit_none.json' }[fail] || 'submit_ok.json';
  return request('/api/submit', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ evaluation_id, video_id, start_ms, end_ms }),
  }, file);
}