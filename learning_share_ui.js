'use strict';
(() => {
  const I = window.YtLessonI18n, t = I.t, ui = I.text;
  window.ytLearningShare = function (container, id) {
    if (!container || container.dataset.shareId === id) return;
    container.dataset.shareId = id; container.hidden = false; container.replaceChildren();
    const note = document.createElement('p'); ui(note, 'Share this lesson through Frankfurt. Anyone with the link can open it until expiry. Offline/downloaded copies remain available.');
    const days = document.createElement('select'); I.attribute(days, 'aria-label', 'Share link lifetime');
    const five = new Option('', '5'), one = new Option('', '1'); ui(five, '5 days'); ui(one, '1 day'); days.append(five, one);
    const share = document.createElement('button'); share.type = 'button'; ui(share, 'Create temporary link');
    const status = document.createElement('p'); status.setAttribute('role', 'status'); status.style.minHeight = '1.6em';
    const result = document.createElement('div'); result.hidden = true;
    const link = document.createElement('a'); link.target = '_blank'; link.rel = 'noopener noreferrer'; ui(link, 'Open shared lesson');
    const input = document.createElement('input'); input.type = 'text'; input.readOnly = true; input.style.width = '100%'; I.attribute(input, 'aria-label', 'Temporary lesson link');
    const copy = document.createElement('button'); copy.type = 'button'; ui(copy, 'Copy link');
    const revoke = document.createElement('button'); revoke.type = 'button'; ui(revoke, 'Revoke link');
    result.append(link, input, copy, revoke); container.append(note, days, share, status, result);
    let poll = 0, current = null;
    function render(job) {
      if (container.dataset.shareId !== id) { clearTimeout(poll); return; }
      current = job;
      const active = job.status === 'done' && job.expires * 1000 > Date.now();
      const busy = ['uploading', 'revoking'].includes(job.status);
      share.disabled = busy || active; days.disabled = busy || active; revoke.disabled = busy;
      result.hidden = !active;
      if (active) ui(status, 'Link expires {date}', () => ({date: new Date(job.expires * 1000).toLocaleString(I.language)}));
      else ui(status, job.error || job.stage || ({none: '', expired: 'Link expired. Create a new link.', revoked: 'Link revoked.'}[job.status] || job.status));
      if (active) link.href = input.value = job.url;
      clearTimeout(poll);
      if (busy) poll = setTimeout(refresh, 1500);
    }
    async function refresh() {
      if (container.dataset.shareId !== id) return;
      try {
        const response = await fetch('/ytwatcher/api/learning-share?' + new URLSearchParams({id}), {cache: 'no-store'});
        const job = await response.json();
        if (!response.ok) throw new Error(job.error || 'Share status unavailable');
        render(job);
      } catch (error) {
        ui(status, error.message);
        if (current && ['uploading', 'revoking'].includes(current.status)) poll = setTimeout(refresh, 3000);
      }
    }
    async function submit(remove) {
      share.disabled = revoke.disabled = true; ui(status, remove ? 'Revoking…' : 'Uploading lesson…');
      try {
        const response = await fetch('/ytwatcher/api/learning-share' + (remove ? '/revoke' : ''), {
          method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({id, days: Number(days.value)})
        });
        const job = await response.json();
        if (!response.ok) throw new Error(job.error || 'Sharing unavailable');
        render(job);
      } catch (error) { ui(status, error.message); share.disabled = false; revoke.disabled = false; }
    }
    share.onclick = () => submit(false); revoke.onclick = () => submit(true);
    copy.onclick = async () => {
      try { await navigator.clipboard.writeText(input.value); ui(status, 'Link copied. Expires {date}', () => ({date: new Date(current.expires * 1000).toLocaleString(I.language)})); }
      catch (error) { input.focus(); input.select(); ui(status, 'Link selected. Use Copy from the browser menu.'); }
    };
    refresh();
  };
})();
