'use strict';
(() => {
  const pack = JSON.parse(document.getElementById('pack-data').textContent);
  const $ = id => document.getElementById(id), media = $('media'), own = $('my-voice');
  const API = '/ytwatcher/api', sentences = pack.sentences, shared = !!pack.shared;
  const root = new URL('./', location.href).href, cacheName = 'ytwatcher-lesson:' + root + ':v1';
  const labels = {en: 'English', de: 'Deutsch', es: 'Español', zh: '中文', fr: 'Français', it: 'Italiano', pt: 'Português'};
  const uid = () => Array.from(crypto.getRandomValues(new Uint8Array(16)), b => b.toString(16).padStart(2, '0')).join('');
  const normalize = value => value.normalize('NFC').trim().toLocaleLowerCase().replace(/\s+/g, ' ').replace(/[.!?。！？]+$/g, '');
  const wordKey = value => pack.source === 'de' ? value.normalize('NFC') : value.normalize('NFC').toLowerCase();
  const clock = value => `${Math.floor(value / 60)}:${String(Math.floor(value % 60)).padStart(2, '0')}`;
  let selected = 0, target = pack.target, progress = {reviewed: [], answers: {}, cloze: {}, quiz: {}, attempts: {}};
  let lookupSerial = 0, translationWanted = false;
  let manualSeeking = false;
  let translationSerial = 0, forceOne = false, issuedPlay = false, holding = false;
  let frame = 0, endTimer = 0, loopTimer = 0, afterOriginal = null, seekGuardUntil = 0;
  let recorder = null, stream = null, recording = false, startingRecord = false, recordClock = 0, recordLimit = 0;
  let recordingUrl = null, activeAttempt = null, recordStopPromise = null, recordingGeneration = 0;
  let flushing = null, quizCard = null, quizStarted = 0, quizAnswered = false, lastQuiz = '';
  let landscape = false, landscapeFullscreen = false;
  const sentenceButtons = [], memoryKV = new Map(), memoryRecordings = new Map(), memoryQueue = new Map();
  let storageAvailable = true;
  const dbPromise = new Promise((resolve, reject) => {
    if (!window.indexedDB) return reject(new Error('Browser storage unavailable'));
    const request = indexedDB.open('ytwatcher-learning-v1', 1);
    request.onupgradeneeded = () => {
      const db = request.result;
      db.createObjectStore('kv');
      db.createObjectStore('queue', {keyPath: 'id'});
      const store = db.createObjectStore('recordings', {keyPath: 'id'});
      store.createIndex('sentence', 'sentence');
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error || new Error('Cannot open browser storage'));
    request.onblocked = () => reject(new Error('Browser storage is busy'));
  }).catch(() => { storageAvailable = false; return null; });
  async function transaction(store, write, action) {
    const db = await dbPromise;
    if (!db) throw new Error('Browser storage unavailable');
    return new Promise((resolve, reject) => {
      const tx = db.transaction(store, write ? 'readwrite' : 'readonly');
      let result;
      try {
        const request = action(tx.objectStore(store));
        request.onsuccess = () => { result = request.result; };
      } catch (error) { tx.abort(); reject(error); return; }
      tx.oncomplete = () => resolve(result);
      tx.onerror = tx.onabort = () => reject(tx.error || new Error('Could not save on this device'));
    });
  }
  async function getValue(key) {
    if (memoryKV.has(key)) return memoryKV.get(key);
    try { return await transaction('kv', false, store => store.get(key)); }
    catch (error) { return memoryKV.get(key); }
  }
  async function putValue(key, value) {
    memoryKV.set(key, value);
    try { await transaction('kv', true, store => store.put(value, key)); return true; }
    catch (error) { storageAvailable = false; return false; }
  }
  function saveProgress() {
    const value = JSON.parse(JSON.stringify({...progress, selected, target, speed: media.playbackRate,
      pauseEach: $('pause-each').checked, loop: $('loop-sentence').checked}));
    putValue('progress:' + pack.id, value);
  }
  let deckPromise = null;
  function getDeck() {
    if (!deckPromise) deckPromise = loadDeck();
    return deckPromise;
  }
  async function loadDeck() {
    let value = '';
    try { value = localStorage.getItem('ytwatcher:study-deck:v1') || ''; } catch (error) {}
    if (!/^[a-f0-9]{32}$/.test(value)) value = await getValue('study-deck') || uid();
    try { localStorage.setItem('ytwatcher:study-deck:v1', value); } catch (error) {}
    await putValue('study-deck', value);
    return value;
  }
  async function remember(data) {
    if (shared) return;
    const event = {id: uid(), created: Date.now() / 1000, kind: data.kind,
      source: data.source, translation: data.translation, src: pack.source, dst: target,
      pos: (data.pos || '').slice(0, 100), inf: (data.inf || '').slice(0, 100),
      meanings: (data.meanings || []).slice(0, 10).map(v => String(v).slice(0, 500)),
      context: sentences[selected].text.slice(0, 2000), video_title: pack.title.slice(0, 500), video_href: root};
    if (event.kind === 'sentence' && event.source.length > 2000) return;
    const row = {id: event.id, deck: await getDeck(), event};
    memoryQueue.set(row.id, row);
    try { await transaction('queue', true, store => store.put(row)); } catch (error) {}
    flushLookups();
  }
  function flushLookups() {
    if (shared || flushing || !navigator.onLine || location.protocol === 'file:') return flushing;
    flushing = (async () => {
      let rows;
      try { rows = await transaction('queue', false, store => store.getAll()); }
      catch (error) { rows = [...memoryQueue.values()]; }
      rows = [...new Map([...rows, ...memoryQueue.values()].map(row => [row.id, row])).values()];
      rows.sort((a, b) => a.event.created - b.event.created);
      while (rows.length) {
        const deck = rows[0].deck, batch = rows.filter(row => row.deck === deck).slice(0, 50);
        const response = await fetch(API + '/flashcards/record', {method: 'POST', headers: {
          'Content-Type': 'application/json', 'X-Study-Deck': deck
        }, body: JSON.stringify({events: batch.map(row => row.event)})});
        if (!response.ok) throw new Error('Flashcards will sync when connected');
        for (const row of batch) {
          memoryQueue.delete(row.id);
          try { await transaction('queue', true, store => store.delete(row.id)); } catch (error) {}
        }
        const sent = new Set(batch.map(row => row.id));
        rows = rows.filter(row => !sent.has(row.id));
      }
    })().catch(() => {}).finally(() => { flushing = null; });
    return flushing;
  }
  function makeWordText(element, text) {
    const nodes = [], pattern = /[\p{L}\p{M}]+(?:['’\-][\p{L}\p{M}]+)*/gu;
    let end = 0;
    for (const match of text.matchAll(pattern)) {
      if (match.index > end) nodes.push(document.createTextNode(text.slice(end, match.index)));
      const word = document.createElement('span');
      word.className = 'word'; word.dataset.word = match[0]; word.textContent = match[0];
      nodes.push(word); end = match.index + match[0].length;
    }
    if (end < text.length) nodes.push(document.createTextNode(text.slice(end)));
    element.replaceChildren(...nodes);
  }
  function dictionaryEntry(word) {
    const entries = pack.dictionary[target] || {};
    return entries[wordKey(word)] || entries[word.toLowerCase()] ||
      (pack.source === 'de' && entries[word.charAt(0).toUpperCase() + word.slice(1).toLowerCase()]);
  }
  async function lookup(word, dialog = false) {
    pauseAll();
    const chosenTarget = target, chosenSentence = selected, serial = ++lookupSerial;
    let value = dictionaryEntry(word);
    if (!value && !shared && navigator.onLine && location.protocol !== 'file:') {
      try {
        const response = await fetch(API + '/dictionary?' + new URLSearchParams({word, from: pack.source, to: target}));
        if (response.ok) value = await response.json();
      } catch (error) {}
    }
    if (serial !== lookupSerial || chosenTarget !== target || chosenSentence !== selected) return;
    const message = value ? value.en + (value.meanings?.length ? '\nAlso: ' + value.meanings.join(' · ') : '') +
      (value.pos ? '\n' + value.pos : '') + (value.inf ? ' ← ' + value.inf : '') : (shared ? 'Not in this shared clip’s dictionary.' : 'Not in this clip’s offline dictionary. Connect to look up this word.');
    if (dialog) {
      $('word-dialog-title').textContent = word;
      $('word-dialog-body').textContent = message;
      if (!$('word-dialog').open) $('word-dialog').showModal ? $('word-dialog').showModal() : $('word-dialog').setAttribute('open', '');
    } else {
      $('dictionary-word').textContent = word;
      $('dictionary-result').textContent = message;
      $('dictionary-panel').style.visibility = 'visible';
      $('dictionary-close').hidden = false;
    }
    if (value) remember({kind: 'word', source: word, translation: value.en, ...value}).catch(() => {});
  }
  $('word-dialog-close').onclick = () => $('word-dialog').close();
  $('dictionary-close').onclick = () => { $('dictionary-panel').style.visibility = 'hidden'; };
  $('sentence-text').addEventListener('pointerdown', pauseAll);
  $('sentence-text').addEventListener('click', event => { const word = event.target.closest('[data-word]'); if (word) lookup(word.dataset.word); });
  function clearMonitor() { cancelAnimationFrame(frame); clearTimeout(endTimer); frame = endTimer = 0; }
  function pauseAll() {
    clearTimeout(loopTimer); loopTimer = 0; afterOriginal = null;
    media.pause(); own.pause(); clearMonitor();
  }
  function seek(value) { seekGuardUntil = performance.now() + 300; media.currentTime = Math.max(0, value); }
  function indexAt(value) {
    let low = 0, high = sentences.length - 1, found = 0;
    while (low <= high) {
      const middle = (low + high) >> 1;
      if (sentences[middle].start <= value + .005) { found = middle; low = middle + 1; } else high = middle - 1;
    }
    return found;
  }
  function guardRecording() {
    if (!recording && !startingRecord) return false;
    $('record-status').textContent = 'Stop and save the recording before changing sentences or playing audio.';
    return true;
  }
  function select(index, move = true) {
    if (guardRecording()) return false;
    index = Math.max(0, Math.min(sentences.length - 1, index));
    pauseAll(); holding = false; forceOne = false;
    if (selected !== index) { ++translationSerial; translationWanted = false; }
    ++lookupSerial;
    selected = index;
    if (move && media.readyState) seek(sentences[selected].start);
    makeWordText($('sentence-text'), sentences[selected].text);
    $('sentence-panel').scrollTop = 0;
    $('sentence-counter').textContent = `${selected + 1} / ${sentences.length} sentences`;
    $('previous').disabled = selected === 0;
    $('next').disabled = $('continue').disabled = selected === sentences.length - 1;
    $('dictionary-panel').style.visibility = 'hidden';
    $('play-status').textContent = '';
    sentenceButtons.forEach((button, i) => button.setAttribute('aria-current', String(i === selected)));
    $('mark-reviewed').textContent = progress.reviewed.includes(selected) ? '✓ Reviewed' : 'Mark reviewed';
    $('sentence-translation').textContent = '';
    loadTranslation(); loadAttempts(); saveProgress();
    return true;
  }
  function markReviewed() {
    if (!progress.reviewed.includes(selected)) progress.reviewed.push(selected);
    $('mark-reviewed').textContent = '✓ Reviewed';
    sentenceButtons[selected]?.classList.add('reviewed');
    $('review-progress').textContent = `· ${progress.reviewed.length}/${sentences.length} reviewed`;
    saveProgress();
  }
  function boundary() {
    if (media.seeking || manualSeeking || media.paused || !(forceOne || $('pause-each').checked || $('loop-sentence').checked)) return false;
    if (media.currentTime < sentences[selected].end - .015) return false;
    const callback = afterOriginal; afterOriginal = null;
    media.pause(); clearMonitor(); holding = true;
    seek(sentences[selected].end);
    markReviewed();
    $('play-status').textContent = 'Sentence finished. Review, repeat, or continue.';
    if (callback) callback();
    else if ($('loop-sentence').checked) loopTimer = setTimeout(() => playSelected(true), 200);
    return true;
  }
  function monitor() {
    clearMonitor();
    if (media.paused) return;
    if (boundary()) return;
    if (!forceOne && !$('loop-sentence').checked) {
      const index = indexAt(media.currentTime);
      if (index !== selected) {
        selected = index; ++translationSerial; ++lookupSerial; translationWanted = false;
        makeWordText($('sentence-text'), sentences[index].text);
        $('sentence-panel').scrollTop = 0;
        $('sentence-counter').textContent = `${selected + 1} / ${sentences.length} sentences`;
        $('previous').disabled = index === 0;
        $('next').disabled = $('continue').disabled = index === sentences.length - 1;
        $('dictionary-panel').style.visibility = 'hidden';
        sentenceButtons.forEach((button, i) => button.setAttribute('aria-current', String(i === index)));
        $('mark-reviewed').textContent = progress.reviewed.includes(index) ? '✓ Reviewed' : 'Mark reviewed';
        $('sentence-translation').textContent = '';
        loadTranslation(); loadAttempts(); saveProgress();
      }
    }
    if (forceOne || $('pause-each').checked || $('loop-sentence').checked) {
      const delay = (sentences[selected].end - media.currentTime) * 1000 / media.playbackRate;
      endTimer = setTimeout(() => { if (!boundary()) monitor(); }, Math.max(10, delay));
    }
    frame = requestAnimationFrame(monitor);
  }
  async function playSelected(one = true, callback = null) {
    if (guardRecording()) return;
    pauseAll(); forceOne = one; holding = false; afterOriginal = callback;
    seek(sentences[selected].start); issuedPlay = true;
    try { await media.play(); }
    catch (error) { issuedPlay = false; $('play-status').textContent = 'Tap the player to start audio on this device.'; }
  }
  media.addEventListener('play', () => {
    if (recording || startingRecord) { media.pause(); return; }
    own.pause(); clearTimeout(loopTimer);
    if (!issuedPlay) {
      forceOne = false; afterOriginal = null;
      if (holding && $('pause-each').checked && selected + 1 < sentences.length) { select(selected + 1); issuedPlay = true; media.play().catch(() => {}); return; }
    }
    issuedPlay = false; holding = false;
  });
  media.addEventListener('playing', monitor);
  media.addEventListener('pause', clearMonitor);
  media.addEventListener('timeupdate', () => { if (!media.paused) boundary(); });
  media.addEventListener('seeking', () => {
    if (performance.now() >= seekGuardUntil) { manualSeeking = true; clearMonitor(); }
  });
  media.addEventListener('seeked', () => {
    const external = manualSeeking;
    manualSeeking = false;
    if (external && !recording && !startingRecord) {
      const playing = !media.paused, index = indexAt(media.currentTime);
      if (index !== selected) select(index, false);
      forceOne = false; holding = false;
      if (playing) { issuedPlay = true; media.play().then(monitor).catch(() => {}); }
    }
  });
  media.addEventListener('ratechange', () => { saveProgress(); if (!media.paused) monitor(); });
  media.addEventListener('ended', () => { clearMonitor(); markReviewed(); $('play-status').textContent = 'Clip finished. Choose a sentence to review.'; });
  $('previous').onclick = () => select(selected - 1);
  $('next').onclick = () => select(selected + 1);
  $('play-sentence').onclick = () => playSelected(true);
  $('continue').onclick = () => { if (select(selected + 1)) playSelected(false); };
  $('mark-reviewed').onclick = markReviewed;
  $('pause-each').onchange = $('loop-sentence').onchange = () => { saveProgress(); if (!media.paused) monitor(); };
  $('speed').onchange = () => { media.playbackRate = Number($('speed').value); saveProgress(); };
  $('copy-sentence').onclick = async () => {
    pauseAll(); const text = sentences[selected].text;
    try { await navigator.clipboard.writeText(text); $('play-status').textContent = 'Sentence copied.'; }
    catch (error) {
      $('copy-field').value = text; $('copy-dialog').showModal(); $('copy-field').focus(); $('copy-field').select();
      $('play-status').textContent = 'Sentence selected. Use Copy from the browser menu.';
    }
  };
  $('copy-dialog-close').onclick = () => $('copy-dialog').close();
  function translationKey(index = selected, language = target) { return `translation:${pack.id}:${language}:${index}`; }
  async function loadTranslation() {
    const index = selected, language = target, serial = translationSerial;
    const text = language === pack.target && sentences[index].translation || await getValue(translationKey(index, language));
    if (serial !== translationSerial || selected !== index || target !== language) return;
    $('sentence-translation').textContent = text || '';
  }
  $('translate-sentence').onclick = async () => {
    translationWanted = true;
    pauseAll();
    const index = selected, language = target, serial = ++translationSerial;
    let text = language === pack.target && sentences[index].translation || await getValue(translationKey(index, language));
    if (serial !== translationSerial) return;
    if (!text) {
      if (shared || !navigator.onLine || location.protocol === 'file:') {
        $('play-status').textContent = shared ? 'This sentence has no translation in the shared package. Ask the sender to include translations when exporting.' : 'No saved translation for this sentence. Translate while connected to keep it offline.'; return;
      }
      $('sentence-translation').textContent = 'Translating…';
      try {
        let response = await fetch(API + '/translate-sentence', {method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({text: sentences[index].text, from: pack.source, to: language})});
        let job = await response.json();
        if (!response.ok) throw new Error(job.error || 'Translation unavailable');
        const deadline = Date.now() + 390000;
        while (['queued', 'translating'].includes(job.status)) {
          if (serial !== translationSerial) return;
          if (Date.now() > deadline) throw new Error('Translation timed out. Try again.');
          await new Promise(resolve => setTimeout(resolve, 1000));
          response = await fetch(API + '/sentence-translation?' + new URLSearchParams({id: job.id}), {cache: 'no-store'});
          job = await response.json();
          if (!response.ok) throw new Error(job.error || 'Translation unavailable');
        }
        if (job.status !== 'done') throw new Error(job.error || 'Translation unavailable');
        text = job.translation; await putValue(translationKey(index, language), text);
      } catch (error) {
        if (serial === translationSerial) $('sentence-translation').textContent = error.message;
        return;
      }
    }
    if (serial !== translationSerial || selected !== index || target !== language) return;
    $('sentence-translation').textContent = text;
    remember({kind: 'sentence', source: sentences[index].text, translation: text}).catch(() => {});
  };
  $('target').onchange = () => {
    target = $('target').value; ++translationSerial; ++lookupSerial;
    loadTranslation(); renderVocabulary(); renderReadingTranslation(); saveProgress();
    if (translationWanted) setTimeout(() => $('translate-sentence').onclick(), 0);
    $('dictionary-panel').style.visibility = 'hidden';
    if (quizCard) { quizCard = null; $('quiz-question').textContent = ''; $('quiz-choices').replaceChildren(); $('quiz-result').textContent = ''; }
  };
  function recordingButtons() {
    $('record').disabled = recording || startingRecord;
    $('stop-record').disabled = !recording;
    document.querySelectorAll('[data-tab], .playback button, #speed, #copy-sentence, #translate-sentence, #target, #pause-each, #loop-sentence').forEach(button => { button.disabled = recording || startingRecord; });
    if (!recording && !startingRecord) {
      $('previous').disabled = selected === 0; $('next').disabled = $('continue').disabled = selected === sentences.length - 1;
    }
    media.controls = own.controls = !recording && !startingRecord;
    $('attempts').disabled = recording || startingRecord || !activeAttempt;
    $('delete-recording').disabled = $('compare').disabled = recording || startingRecord || !activeAttempt;
  }
  async function attemptsFor(index) {
    const key = pack.id + ':' + index;
    let rows = [];
    try { rows = await transaction('recordings', false, store => store.index('sentence').getAll(key)); } catch (error) {}
    const merged = new Map(rows.map(row => [row.id, row]));
    for (const row of memoryRecordings.values()) if (row.sentence === key) merged.set(row.id, row);
    return [...merged.values()];
  }
  async function loadAttempts() {
    const index = selected, rows = await attemptsFor(index);
    if (index !== selected || recording) return;
    rows.sort((a, b) => a.created - b.created);
    $('attempts').replaceChildren();
    if (!rows.length) $('attempts').append(new Option('No recording yet', ''));
    rows.forEach((row, i) => $('attempts').append(new Option(`Attempt ${i + 1} · ${new Date(row.created).toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'})}`, row.id)));
    const preferred = progress.attempts[index];
    activeAttempt = rows.find(row => row.id === preferred) || rows.at(-1) || null;
    $('attempts').value = activeAttempt?.id || '';
    $('attempts').disabled = !activeAttempt;
    showAttempt();
  }
  function showAttempt() {
    own.pause();
    if (recordingUrl) URL.revokeObjectURL(recordingUrl);
    recordingUrl = activeAttempt ? URL.createObjectURL(activeAttempt.blob) : null;
    own.hidden = !activeAttempt;
    $('download-recording').hidden = !activeAttempt;
    $('delete-recording').disabled = $('compare').disabled = !activeAttempt || recording;
    if (activeAttempt) {
      own.src = recordingUrl;
      const extension = activeAttempt.mime.includes('mp4') ? 'm4a' : activeAttempt.mime.includes('ogg') ? 'ogg' : 'webm';
      $('download-recording').href = recordingUrl;
      $('download-recording').download = `learning-${pack.id.slice(0, 8)}-sentence-${selected + 1}-${activeAttempt.id.slice(0, 6)}.${extension}`;
    } else { own.removeAttribute('src'); $('download-recording').removeAttribute('href'); }
  }
  $('attempts').onchange = async () => {
    const rows = await attemptsFor(selected);
    activeAttempt = rows.find(row => row.id === $('attempts').value) || null;
    progress.attempts[selected] = activeAttempt?.id || '';
    showAttempt(); saveProgress();
  };
  $('delete-recording').onclick = async () => {
    if (!activeAttempt || recording || startingRecord) return;
    const id = activeAttempt.id;
    memoryRecordings.delete(id);
    try { await transaction('recordings', true, store => store.delete(id)); }
    catch (error) { $('record-status').textContent = 'Could not delete this recording from browser storage.'; return; }
    delete progress.attempts[selected]; saveProgress(); await loadAttempts();
    $('record-status').textContent = 'Recording deleted.';
  };
  $('record').onclick = async () => {
    if (recording || startingRecord) return;
    if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
      $('record-status').textContent = 'Recording needs a trusted HTTPS page and microphone support. Open the hosted page, then save it offline.'; return;
    }
    pauseAll(); startingRecord = true; recordingButtons();
    const generation = ++recordingGeneration, index = selected;
    try {
      stream = await navigator.mediaDevices.getUserMedia({audio: true, video: false});
      if (generation !== recordingGeneration || document.hidden) { stream.getTracks().forEach(track => track.stop()); return; }
      const mime = ['audio/mp4', 'audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus'].find(type => MediaRecorder.isTypeSupported(type));
      recorder = mime ? new MediaRecorder(stream, {mimeType: mime}) : new MediaRecorder(stream);
      const chunks = [], started = Date.now(), id = uid(), currentRecorder = recorder, currentStream = stream;
      let finishStop;
      recordStopPromise = new Promise(resolve => { finishStop = resolve; });
      recorder.ondataavailable = event => { if (event.data.size) chunks.push(event.data); };
      recorder.onerror = () => { $('record-status').textContent = 'Recording failed. Your previous attempts are still saved.'; stopRecording(); };
      recorder.onstop = async () => {
        clearInterval(recordClock); clearTimeout(recordLimit);
        currentStream.getTracks().forEach(track => track.stop());
        const type = currentRecorder.mimeType || chunks[0]?.type || 'audio/webm';
        recording = false; startingRecord = true; recordingButtons();
        if (chunks.length) {
          const row = {id, sentence: pack.id + ':' + index, created: started, mime: type, blob: new Blob(chunks, {type})};
          memoryRecordings.set(id, row);
          let saved = true;
          try { await transaction('recordings', true, store => store.put(row)); } catch (error) { saved = false; }
          progress.attempts[index] = id; saveProgress();
          if (selected === index) await loadAttempts();
          $('record-status').textContent = saved ? 'Recording saved on this device. Compare it with the original.' :
            'Recording is ready, but browser storage is unavailable. Download it now to keep it.';
        } else $('record-status').textContent = 'No audio was captured. Check microphone access and try again.';
        startingRecord = false; recordingButtons();
        finishStop();
      };
      recorder.start(); recording = true; startingRecord = false; recordingButtons();
      $('record-status').textContent = 'Recording… 0:00';
      recordClock = setInterval(() => { $('record-status').textContent = 'Recording… ' + clock((Date.now() - started) / 1000); }, 500);
      recordLimit = setTimeout(stopRecording, 180000);
    } catch (error) {
      stream?.getTracks().forEach(track => track.stop());
      $('record-status').textContent = error.name === 'NotAllowedError' ? 'Microphone access was not allowed. Enable it for this page and try again.' : 'Could not start recording: ' + error.message;
    } finally { if (!recording) { startingRecord = false; recordingButtons(); } }
  };
  function stopRecording() {
    if (recorder && recorder.state !== 'inactive') recorder.stop();
    stream?.getTracks().forEach(track => track.stop());
    clearInterval(recordClock); clearTimeout(recordLimit);
    return recordStopPromise || Promise.resolve();
  }
  $('stop-record').onclick = stopRecording;
  own.addEventListener('play', () => {
    if (recording || startingRecord) { own.pause(); return; }
    media.pause(); clearMonitor();
  });
  $('compare').onclick = () => {
    if (!activeAttempt || recording || startingRecord) return;
    const id = activeAttempt.id;
    playSelected(true, () => {
      if (activeAttempt?.id !== id) return;
      own.currentTime = 0;
      own.play().catch(() => { $('record-status').textContent = 'Tap Play on your recording to hear it.'; });
    });
  };
  document.addEventListener('visibilitychange', () => {
    if (document.hidden && (recording || startingRecord)) { ++recordingGeneration; stopRecording(); }
  });
  window.addEventListener('pagehide', () => { ++recordingGeneration; stopRecording(); });
  function showTab(name) {
    if (guardRecording()) return;
    if (name !== 'listen') { pauseAll(); if (landscape) exitLandscape(); }
    if (name === 'read') renderReadingTranslation();
    document.querySelectorAll('[data-tab]').forEach(button => button.setAttribute('aria-selected', String(button.dataset.tab === name)));
    document.querySelectorAll('.tab-panel').forEach(panel => { panel.hidden = panel.id !== 'tab-' + name; });
  }
  document.querySelectorAll('[data-tab]').forEach(button => { button.onclick = () => showTab(button.dataset.tab); });
  function renderReading() {
    $('reading').replaceChildren(); $('sentence-list').replaceChildren();
    for (const sentence of sentences) {
      const row = document.createElement('article'); row.className = 'reading-row';
      const text = document.createElement('p'); makeWordText(text, sentence.text);
      text.addEventListener('click', event => { const word = event.target.closest('[data-word]'); if (word) lookup(word.dataset.word, true); });
      const listen = document.createElement('button'); listen.type = 'button'; listen.textContent = `Listen · ${clock(sentence.start)}`;
      listen.onclick = () => { showTab('listen'); if (select(sentence.id)) playSelected(true); };
      row.append(text, listen); $('reading').append(row);
      const li = document.createElement('li'), button = document.createElement('button');
      button.type = 'button'; button.textContent = sentence.text;
      button.classList.toggle('reviewed', progress.reviewed.includes(sentence.id));
      button.onclick = () => select(sentence.id);
      li.append(button); $('sentence-list').append(li); sentenceButtons.push(button);
    }
    const hasSections = sentences.some(sentence => sentence.section);
    $('timing-note').hidden = !hasSections;
    $('timing-note').textContent = 'Long subtitle passages without sentence punctuation are divided into short review sections. Timing follows subtitle word timestamps where available.';
    $('question-note').textContent = pack.questions.length ? 'Answer in your own words, then compare with the suggested answer.' :
      'This package includes the original reading and vocabulary exercises. Select the optional local-LLM exercises when exporting to include comprehension questions and a reading translation.';
    $('generated-note').hidden = !pack.generated;
    for (let i = 0; i < pack.questions.length; i++) {
      const question = pack.questions[i], box = document.createElement('article'); box.className = 'question';
      const prompt = document.createElement('strong'); prompt.textContent = `${i + 1}. ${question.question}`;
      const answer = document.createElement('textarea'); answer.rows = 3; answer.setAttribute('aria-label', 'Your answer to question ' + (i + 1));
      answer.value = progress.answers[i] || '';
      answer.oninput = () => { progress.answers[i] = answer.value; saveProgress(); };
      const reveal = document.createElement('button'); reveal.type = 'button'; reveal.textContent = 'Show suggested answer';
      const solution = document.createElement('p'); solution.className = 'answer'; solution.hidden = true; solution.textContent = question.answer;
      reveal.onclick = () => { solution.hidden = !solution.hidden; };
      box.append(prompt, answer, reveal, solution); $('questions').append(box);
    }
    for (let i = 0; i < pack.practice.length; i++) {
      const item = pack.practice[i], box = document.createElement('article'); box.className = 'cloze-row';
      const prompt = document.createElement('p'); prompt.textContent = item.prompt;
      const input = document.createElement('input'); input.type = 'text'; input.setAttribute('aria-label', 'Missing word ' + (i + 1)); input.value = progress.cloze[i] || '';
      input.oninput = () => { progress.cloze[i] = input.value; saveProgress(); };
      const check = document.createElement('button'); check.type = 'button'; check.textContent = 'Check word';
      const result = document.createElement('p'); result.className = 'answer';
      check.onclick = () => { result.textContent = normalize(input.value) === normalize(item.answer) ? 'Correct.' : 'Saved subtitle word: ' + item.answer; };
      box.append(prompt, input, check, result); $('cloze').append(box);
    }
    $('review-progress').textContent = `· ${progress.reviewed.length}/${sentences.length} reviewed`;
    renderReadingTranslation();
  }
  async function renderReadingTranslation() {
    const language = target;
    const texts = await Promise.all(sentences.map(sentence => language === pack.target && sentence.translation || getValue(translationKey(sentence.id, language))));
    if (language !== target) return;
    const container = $('full-translation'); container.replaceChildren();
    if (!texts.some(Boolean)) { container.textContent = 'No saved reading translation for this language. Translate sentences while connected, or export with optional LLM exercises.'; return; }
    texts.forEach((text, i) => {
      const paragraph = document.createElement('p'); paragraph.className = 'translated';
      paragraph.textContent = text || `[Sentence ${i + 1}: translation not saved]`; container.append(paragraph);
    });
  }
  function renderVocabulary() {
    const search = $('word-search').value.trim().toLocaleLowerCase(), rows = [];
    const notes = new Map((pack.vocabulary_notes || []).map(note => [note.word.toLowerCase(), note.explanation]));
    const words = [...new Set([...pack.vocabulary, ...Object.keys(pack.dictionary[target] || {})])];
    for (const word of words) {
      const entry = dictionaryEntry(word);
      if (!entry || search && !(word + ' ' + entry.en).toLocaleLowerCase().includes(search)) continue;
      const row = document.createElement('tr'), source = document.createElement('td'), meaning = document.createElement('td'), note = document.createElement('td');
      const button = document.createElement('button'); button.type = 'button'; button.textContent = word; button.onclick = () => lookup(word, true);
      source.append(button); meaning.textContent = entry.en + (entry.meanings?.length ? '\n' + entry.meanings.join(' · ') : '');
      note.textContent = [notes.get(word.toLowerCase()), entry.pos, entry.inf ? '← ' + entry.inf : ''].filter(Boolean).join(' · ');
      row.append(source, meaning, note); rows.push(row);
      if (rows.length >= 300) break;
    }
    if (!rows.length) {
      const row = document.createElement('tr'), cell = document.createElement('td'); cell.colSpan = 3; cell.textContent = 'No saved dictionary entries match this language or search.'; row.append(cell); rows.push(row);
    }
    $('vocabulary').replaceChildren(...rows);
    quizStats();
  }
  $('word-search').oninput = renderVocabulary;
  function quizStats() {
    const values = Object.values(progress.quiz), correct = values.reduce((sum, value) => sum + value.correct, 0), wrong = values.reduce((sum, value) => sum + value.wrong, 0);
    $('quiz-stats').textContent = `${correct} correct · ${wrong} to practise again · progress saved on this device`;
  }
  function nextQuiz() {
    const entries = pack.dictionary[target] || {}, words = Object.keys(entries);
    if (words.length < 2) { $('quiz-result').textContent = 'Not enough distinct vocabulary for this language yet.'; return; }
    const weights = words.map(word => {
      const score = progress.quiz[target + ':' + word] || {correct: 0, wrong: 0};
      return word === lastQuiz && words.length > 1 ? 0 : 1 + score.wrong * 3 + 2 / (score.correct + 1) + Math.min(3, (score.seconds || 0) / 10);
    });
    let pick = Math.random() * weights.reduce((a, b) => a + b, 0), chosen = words[0];
    for (let i = 0; i < words.length; i++) { pick -= weights[i]; if (pick <= 0) { chosen = words[i]; break; } }
    const expected = entries[chosen].en, used = new Set([expected, ...(entries[chosen].meanings || [])].map(normalize));
    const wrong = words.filter(word => word !== chosen && !used.has(normalize(entries[word].en)));
    wrong.sort(() => Math.random() - .5);
    const options = [expected];
    for (const word of wrong) { const value = entries[word].en; if (!options.some(option => normalize(option) === normalize(value))) options.push(value); if (options.length === 4) break; }
    if (options.length < 2) { $('quiz-result').textContent = 'These words share the same meaning. Try another language or review the vocabulary table.'; return; }
    for (let i = options.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [options[i], options[j]] = [options[j], options[i]]; }
    quizCard = chosen; lastQuiz = chosen; quizStarted = performance.now(); quizAnswered = false;
    $('quiz-question').textContent = chosen + ' → ' + (labels[target] || target); $('quiz-result').textContent = ''; $('quiz-choices').replaceChildren();
    options.forEach(value => {
      const button = document.createElement('button'); button.type = 'button'; button.textContent = value;
      button.onclick = () => {
        if (quizAnswered) return;
        quizAnswered = true; const correct = normalize(value) === normalize(expected), elapsed = (performance.now() - quizStarted) / 1000;
        for (const option of $('quiz-choices').querySelectorAll('button')) { option.disabled = true; if (normalize(option.textContent) === normalize(expected)) option.classList.add('correct'); }
        if (!correct) button.classList.add('incorrect');
        const key = target + ':' + chosen, score = progress.quiz[key] || {correct: 0, wrong: 0};
        if (correct) score.correct++; else score.wrong++;
        score.seconds = elapsed; progress.quiz[key] = score; saveProgress(); quizStats();
        $('quiz-result').textContent = (correct ? 'Correct' : 'Answer: ' + expected) + ` · ${elapsed.toFixed(1)} seconds. ` + (correct ? 'Choose Random question to continue.' : 'This word will appear more often.');
      };
      $('quiz-choices').append(button);
    });
  }
  $('quiz-next').onclick = nextQuiz;
  async function offlineState() {
    if (!('caches' in window) || location.protocol === 'file:') return;
    const cache = await caches.open(cacheName);
    let files = await getValue('offline-files:' + pack.id);
    if (!files) {
      const list = await cache.match(new URL('offline-files.json', root).href);
      if (list) files = (await list.json()).files;
    }
    if (!files) return;
    const saved = await Promise.all(files.map(file => cache.match(new URL(file, root).href, {ignoreSearch: true})));
    $('offline-status').textContent = saved.every(Boolean) ? 'Saved offline on this device: player, media, reading and vocabulary. Recordings stay in browser storage.' :
      `${saved.filter(Boolean).length}/${files.length} files saved. Choose Save offline to complete this clip.`;
  }
  $('save-offline').onclick = async () => {
    const button = $('save-offline'); button.disabled = true;
    try {
      if (!window.isSecureContext || !('serviceWorker' in navigator) || !('caches' in window) || location.protocol === 'file:') throw new Error('Open the hosted HTTPS learning page to save it offline.');
      const registration = await navigator.serviceWorker.register('learning_sw.js', {scope: './', updateViaCache: 'none'});
      for (let i = 0; !registration.active && i < 60; i++) await new Promise(resolve => setTimeout(resolve, 250));
      if (!registration.active) throw new Error('The offline player is not ready yet. Try again.');
      let files = await getValue('offline-files:' + pack.id);
      if (!files) { const response = await fetch('offline-files.json'); if (!response.ok) throw new Error('The package file list is unavailable.'); files = (await response.json()).files; }
      const cache = await caches.open(cacheName);
      for (let i = 0; i < files.length; i++) {
        $('offline-status').textContent = `Saving offline ${i + 1}/${files.length}: ${files[i]}…`;
        const url = new URL(files[i], root).href;
        if (await cache.match(url, {ignoreSearch: true})) continue;
        const response = await fetch(url, {cache: 'reload'});
        if (!response.ok || response.status !== 200) throw new Error('Could not save ' + files[i]);
        await cache.put(url, response);
      }
      await putValue('offline-files:' + pack.id, files);
      if (navigator.storage?.persist) await navigator.storage.persist().catch(() => false);
      await offlineState();
    } catch (error) { $('offline-status').textContent = 'Offline save incomplete. ' + error.message; }
    finally { button.disabled = false; }
  };
  $('remove-offline').onclick = async () => {
    if (!('caches' in window)) return;
    await caches.delete(cacheName);
    $('offline-status').textContent = 'Offline copy removed. Voice recordings and study progress have been kept.';
  };
  function sizeLandscape() {
    if (!landscape) return;
    const view = window.visualViewport, w = view?.width || innerWidth, h = view?.height || innerHeight, portrait = h > w;
    const stage = $('lesson-stage');
    stage.style.setProperty('--view-x', ((view?.offsetLeft || 0) + w / 2) + 'px');
    stage.style.setProperty('--view-y', ((view?.offsetTop || 0) + h / 2) + 'px');
    stage.style.setProperty('--view-w', (portrait ? h : w) + 'px'); stage.style.setProperty('--view-h', (portrait ? w : h) + 'px');
    stage.style.setProperty('--view-angle', portrait ? '90deg' : '0deg');
  }
  function exitLandscape() {
    landscape = false; landscapeFullscreen = false; $('lesson-player').classList.remove('landscape'); document.body.classList.remove('landscape-open');
    $('landscape').textContent = 'Landscape'; $('landscape').setAttribute('aria-pressed', 'false');
    if (document.fullscreenElement === $('lesson-player') && document.exitFullscreen) document.exitFullscreen().catch(() => {});
  }
  $('landscape').onclick = () => {
    if (landscape) { exitLandscape(); return; }
    landscape = true; $('lesson-player').classList.add('landscape'); document.body.classList.add('landscape-open'); $('landscape').textContent = 'Exit landscape'; $('landscape').setAttribute('aria-pressed', 'true'); sizeLandscape();
    if ($('lesson-player').requestFullscreen && !document.fullscreenElement) $('lesson-player').requestFullscreen().then(() => { landscapeFullscreen = true; sizeLandscape(); }).catch(() => {});
  };
  document.addEventListener('fullscreenchange', () => { if (landscapeFullscreen && document.fullscreenElement !== $('lesson-player')) exitLandscape(); });
  document.addEventListener('keydown', event => { if (event.key === 'Escape' && landscape) exitLandscape(); });
  window.addEventListener('resize', sizeLandscape); window.visualViewport?.addEventListener('resize', sizeLandscape);
  window.visualViewport?.addEventListener('scroll', sizeLandscape);
  window.addEventListener('online', () => { flushLookups(); offlineState().catch(() => {}); });
  setInterval(() => { if (!document.hidden) flushLookups(); }, 30000);
  (async () => {
    const saved = await getValue('progress:' + pack.id);
    if (saved && typeof saved === 'object') progress = {...progress, ...saved};
    selected = Math.max(0, Math.min(sentences.length - 1, Number(progress.selected) || 0));
    target = progress.target || pack.target;
    const targets = [...new Set([pack.target, ...Object.keys(pack.dictionary)])];
    if (!targets.includes(target)) target = pack.target;
    targets.forEach(code => $('target').append(new Option(labels[code] || code, code)));
    $('target').value = target;
    $('pause-each').checked = progress.pauseEach !== false;
    $('loop-sentence').checked = !!progress.loop;
    media.src = pack.media;
    media.classList.toggle('audio-only', !pack.has_video);
    media.playbackRate = Number(progress.speed) || 1; $('speed').value = String(media.playbackRate);
    media.addEventListener('loadedmetadata', () => seek(sentences[selected].start), {once: true});
    $('clip-summary').textContent = `${sentences.length} sentences · ${clock(pack.duration)} clip · original ${clock(pack.source_start)}–${clock(pack.source_end)}`;
    renderReading(); renderVocabulary(); select(selected, false);
    if (shared) {
      document.querySelectorAll('header > a').forEach(link => { link.hidden = true; });
      const note = document.createElement('p'); note.className = 'muted';
      note.textContent = 'Shared learning clip · Link expires ' + new Date(pack.share_expires * 1000).toLocaleString() + '. Save offline before expiry. Your voice and progress stay on this device.';
      document.querySelector('header').append(note);
      const wordsNote = $('tab-words').querySelector('.muted');
      if (wordsNote) wordsNote.textContent = 'Dictionary entries are included in this lesson. Your practice stays on this device.';
    } else if (location.protocol !== 'file:' && window.ytLearningShare) {
      window.ytLearningShare($('learning-share-tools'), pack.id);
    }
    if (!storageAvailable) $('record-status').textContent = 'Browser storage is unavailable. You can still record and download attempts, but progress may not survive closing this page.';
    if ('serviceWorker' in navigator && window.isSecureContext && location.protocol !== 'file:') navigator.serviceWorker.register('learning_sw.js', {scope: './', updateViaCache: 'none'}).catch(() => {});
    offlineState().catch(() => {}); flushLookups();
  })().catch(error => { $('play-status').textContent = 'Could not open this learning clip: ' + error.message; });
})();
