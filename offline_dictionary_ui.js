// Embedded in the player: cache subtitle word dictionaries by source language.
function plBaseLanguage(code) { return (code || "es").toLowerCase().split("-")[0]; }
function plDictionaryKey(item, source) { return item.href + "|" + plBaseLanguage(source); }
function plDictionaryURL(url) { return url.replace(/\.vtt(\?.*)?$/, ".dict.json"); }
function plWordKey(source, word) {
  word = word.normalize("NFC");
  return plBaseLanguage(source) === "de" ? word : word.toLowerCase();
}
function plLocalEntry(local, source, word) {
  if (!local) return null;
  return local[plWordKey(source, word)] || local[word.toLowerCase()] ||
    (plBaseLanguage(source) === "de" && local[word.charAt(0).toUpperCase() + word.slice(1).toLowerCase()]);
}
function plDictEscape(value) {
  var span = document.createElement("span");
  span.textContent = String(value || "");
  return span.innerHTML;
}
function plLocalDictionary(item, source, target) {
  if (!item) return null;
  var data = plDictCache[plDictionaryKey(item, source)];
  if (!data || data._meta && data._meta.source !== plBaseLanguage(source)) return null;
  return target === "en" ? data : data._targets && data._targets[target];
}
var plDictionaryLoads = {};
async function plLoadDictionary(item, source, url, force) {
  var key = plDictionaryKey(item, source);
  if (!force && plDictCache[key]) return plDictCache[key];
  if (plDictionaryLoads[key]) return plDictionaryLoads[key];
  plDictionaryLoads[key] = (async function () {
    var response = await fetch(plDictionaryURL(url), {cache: "no-cache"});
    if (!response.ok) throw new Error("Offline word dictionary unavailable");
    var data = await response.json();
    plDictCache[key] = data;
    return data;
  })().finally(function () { delete plDictionaryLoads[key]; });
  return plDictionaryLoads[key];
}
function plEnsureDictionary(item, source) {
  if (!item) return Promise.resolve(null);
  var subs;
  try { subs = JSON.parse(item.subs || "{}"); } catch (e) { return Promise.resolve(null); }
  var lang = Object.keys(subs).find(function (lang) { return lang === source; }) ||
    Object.keys(subs).find(function (lang) { return plBaseLanguage(lang) === plBaseLanguage(source); });
  return lang ? plLoadDictionary(item, source, subs[lang]) : Promise.resolve(null);
}
async function plPrepareDictionary(item, source, url, cache) {
  var deadline = Date.now() + 60000, job, buildError = null;
  try {
    do {
      var response = await fetch(API + "/build-dict", {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({path: decodeURIComponent(url.replace(/\?.*$/, ""))})
      });
      if (!response.ok) throw new Error("Offline dictionary build unavailable");
      job = await response.json();
      if (job.status === "failed") throw new Error(job.error || "Dictionary build failed");
      if (job.status === "done") break;
      await new Promise(function (resolve) { setTimeout(resolve, 500); });
    } while (Date.now() < deadline);
    if (job.status !== "done") throw new Error("Dictionary still building");
  } catch (e) { buildError = e; }
  var dictUrl = plDictionaryURL(url);
  var downloaded = await fetch(dictUrl, {cache: "reload"});
  if (!downloaded.ok) throw new Error("Offline dictionary unavailable");
  var data = await downloaded.clone().json();
  if (!data._meta || data._meta.version < 2) throw buildError || new Error("Word dictionaries need rebuilding");
  await cache.put(dictUrl, downloaded);
  plDictCache[plDictionaryKey(item, source)] = data;
  return data;
}
// Keep each grammatical meaning together; noun and verb entries must not
// share one POS label or a verb infinitive inherited by an unrelated noun.
function plDictionaryBody(data) {
  if (data.senses && data.senses.length) {
    return data.senses.map(function (sense) {
      var meanings = sense.meanings || [];
      var body = '<b>' + meanings.map(plDictEscape).join(' · ') + '</b>';
      if (sense.pos) body += '<span class="pl-dict-pos">' + plDictEscape(sense.pos) + '</span>';
      var tags = (sense.tags || []).filter(function (tag) { return tag !== 'form-of' && tag !== 'alt-of'; });
      if (tags.length) body += '<span class="pl-dict-pos"> · ' + tags.map(plDictEscape).join(', ') + '</span>';
      var method = sense.translation_method || sense.method;
      var label = method === 'reviewed' ? 'Reviewed meaning' : method === 'aligned' ? 'Via English' : '';
      if (label) body += '<span class="pl-dict-pos"> · ' + plDictEscape(window.YtLessonI18n.t(label)) + '</span>';
      if (sense.form) body += '<div class="pl-dict-form">' + plDictEscape(sense.form) + '</div>';
      if (sense.inf) body += '<span class="pl-dict-inf">← ' + plDictEscape(sense.inf) + '</span>';
      if (sense.source_url && sense.source_url.startsWith('https://en.wiktionary.org/wiki/')) {
        body += ' <a class="pl-dict-source" target="_blank" rel="noopener noreferrer" href="' + plDictEscape(sense.source_url) + '">Wiktionary</a>';
      }
      if (sense.translation_source_url && sense.translation_source_url.startsWith('https://en.wiktionary.org/wiki/')) body += ' <a class="pl-dict-source" target="_blank" rel="noopener noreferrer" href="' + plDictEscape(sense.translation_source_url) + '">English</a>';
      return '<div class="pl-dict-sense">' + body + '</div>';
    }).join('');
  }
  var body = '<b>' + plDictEscape(data.en) + '</b>';
  if (data.meanings && data.meanings.length) body += '<span class="pl-dict-alt"> · ' + data.meanings.map(plDictEscape).join(' · ') + '</span>';
  if (data.pos) body += '<span class="pl-dict-pos">' + plDictEscape(data.pos) + '</span>';
  if (data.inf) body += '<span class="pl-dict-inf">← ' + plDictEscape(data.inf) + '</span>';
  return body;
}
