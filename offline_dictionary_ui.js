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
