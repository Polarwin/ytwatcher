  // Independent exporter: keeps the current playlist/subtitle UI intact.
  var learnDialog = document.getElementById('learning-export-dialog');
  var learnItem = null, learnDuration = 0, learnJob = null, learnPoll = 0;
  function learnClock(seconds) {
    return Math.floor(seconds / 60) + ':' + String(Math.floor(seconds % 60)).padStart(2, '0');
  }
  function learnSeconds(value) {
    if (!/^\d+(?::\d{1,2}){0,2}(?:\.\d+)?$/.test(value.trim())) return NaN;
    return value.trim().split(':').reduce(function (sum, part) { return sum * 60 + Number(part); }, 0);
  }
  function learnShow(item, current, duration) {
    if (!item) return;
    if (learnDialog.open) return;
    if (learnJob) { learnDialog.showModal(); return; }
    learnItem = item; learnDuration = duration || Number(item.dur) || 0;
    var subs;
    try { subs = JSON.parse(item.subs || '{}'); } catch (error) { subs = {}; }
    var selector = document.getElementById('learning-export-subtitle');
    selector.replaceChildren();
    Object.keys(subs).forEach(function (lang) { selector.append(new Option(lang, subs[lang])); });
    if (subs[plSubLang]) selector.value = subs[plSubLang];
    var from = Math.max(0, Math.floor(current || 0));
    if (learnDuration && from >= learnDuration - 1) from = 0;
    document.getElementById('learning-export-source').textContent = item.name;
    document.getElementById('learning-export-start').value = learnClock(from);
    document.getElementById('learning-export-end').value = learnClock(learnDuration ? Math.min(learnDuration, from + 180) : from + 180);
    document.getElementById('learning-export-whole').disabled = !learnDuration || learnDuration > 7200;
    document.getElementById('learning-export-target').value = plDictToSel.value || 'en';
    if (!document.getElementById('learning-export-target').value) document.getElementById('learning-export-target').value = 'en';
    document.getElementById('learning-export-submit').disabled = !selector.options.length || !!learnJob;
    if (!learnJob) {
      document.getElementById('learning-export-status').textContent = selector.options.length ? '' : 'Download subtitles for this video first.';
      document.getElementById('learning-export-result').hidden = true;
      document.getElementById('learning-export-share').hidden = true;
    }
    learnDialog.showModal();
  }
  document.getElementById('pl-export-learning').onclick = function () {
    if (plIndex >= 0 && pl[plIndex]) {
      plVideo.pause();
      learnShow(pl[plIndex], plVideo.currentTime, Number.isFinite(plVideo.duration) ? plVideo.duration : 0);
    }
  };
  document.getElementById('learning-export-close').onclick = function () { learnDialog.close(); };
  document.getElementById('learning-export-whole').onclick = function () {
    document.getElementById('learning-export-start').value = '0:00';
    document.getElementById('learning-export-end').value = String(learnDuration);
  };
  document.querySelectorAll('li[data-subs]').forEach(function (li) {
    var link = li.querySelector('.entry-row a') || li.querySelector('a[href]');
    if (!link || li.querySelector('.learning-export-row')) return;
    var button = document.createElement('button'); button.type = 'button'; button.className = 'watch-btn learning-export-row'; button.textContent = 'Learn';
    button.onclick = function (event) {
      event.stopPropagation();
      learnShow({href: link.getAttribute('href'), name: link.textContent, subs: li.dataset.subs, dur: li.dataset.dur}, 0, Number(li.dataset.dur));
    };
    var controls = li.querySelector('.entry-actions') || li.querySelector('.pl-add')?.parentElement || li.querySelector('.entry-row') || li;
    controls.append(button);
  });
  function learnDisplay(job) {
    document.getElementById('learning-export-status').textContent = (job.error || job.stage || job.status) +
      (job.sentences ? '\n' + job.sentences + ' sentences' : '') + (job.warnings?.length ? '\n' + job.warnings.join('\n') : '');
    if (job.status === 'done') {
      document.getElementById('learning-export-open').href = job.url;
      document.getElementById('learning-export-result').hidden = false;
      window.ytLearningShare(document.getElementById('learning-export-share'), job.id);
    }
    if (['done', 'failed'].includes(job.status)) {
      learnJob = null; document.getElementById('learning-export-submit').disabled = false;
    }
  }
  async function learnCheck() {
    if (!learnJob) return;
    try {
      var response = await fetch('/ytwatcher/api/learning-export?' + new URLSearchParams({id: learnJob}), {cache: 'no-store'});
      var job = await response.json();
      if (!response.ok) {
        if (response.status === 404) { learnJob = null; document.getElementById('learning-export-submit').disabled = false; }
        throw new Error(job.error || 'Export status unavailable');
      }
      learnDisplay(job);
    } catch (error) {
      document.getElementById('learning-export-status').textContent = error.message + (learnJob ? '. Status will retry when connected.' : '');
    }
    if (learnJob) learnPoll = setTimeout(learnCheck, 1500);
  }
  document.getElementById('learning-export-form').onsubmit = async function (event) {
    event.preventDefault(); if (learnJob || !learnItem) return;
    var begin = learnSeconds(document.getElementById('learning-export-start').value), end = learnSeconds(document.getElementById('learning-export-end').value);
    var status = document.getElementById('learning-export-status'), submit = document.getElementById('learning-export-submit');
    if (!Number.isFinite(begin) || !Number.isFinite(end) || begin < 0 || end <= begin || end - begin > 7200) {
      status.textContent = 'Choose a valid start and end, up to 2 hours apart.'; return;
    }
    submit.disabled = true; status.textContent = 'Starting export…'; document.getElementById('learning-export-result').hidden = true;
    try {
      var response = await fetch('/ytwatcher/api/learning-export', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({
        rel: learnItem.href, subtitle: document.getElementById('learning-export-subtitle').value, start: begin, end: end,
        target: document.getElementById('learning-export-target').value, exercises: document.getElementById('learning-export-exercises').checked
      })});
      var job = await response.json();
      if (!response.ok) throw new Error(job.error || 'Could not start export');
      learnJob = job.id; learnDisplay(job);
      clearTimeout(learnPoll); if (learnJob) learnPoll = setTimeout(learnCheck, 700);
    } catch (error) { status.textContent = error.message; submit.disabled = false; }
  };
