// Embedded in the player script by generate_index_html; uses no external library.
function initStudy(api, beforeOpen) {
  var dialog = document.getElementById("study-dialog");
  var saveStatus = document.getElementById("study-save-status");
  var status = document.getElementById("study-status");
  var statsEl = document.getElementById("study-stats");
  var kindEl = document.getElementById("study-kind");
  var targetEl = document.getElementById("study-target");
  var directionEl = document.getElementById("study-direction");
  var quizEl = document.getElementById("study-quiz");
  var questionEl = document.getElementById("study-question");
  var solutionEl = document.getElementById("study-solution");
  var answerEl = document.getElementById("study-answer-input");
  var revealEl = document.getElementById("study-reveal");
  var ratingsEl = document.getElementById("study-ratings");
  var nextEl = document.getElementById("study-next");
  var searchEl = document.getElementById("study-search");
  var libraryEl = document.getElementById("study-library");
  var pendingKey = "ytwatcher:study-pending:v1", deckKey = "ytwatcher:study-deck:v1";
  var pending = [], flushing = null, pendingDurable = true, cards = [], current = null;
  var recent = [], expected = "", alternatives = [], serial = 0, revealed = false;
  function hex() {
    var bytes = new Uint8Array(16);
    crypto.getRandomValues(bytes);
    return Array.from(bytes).map(function (b) { return b.toString(16).padStart(2, "0"); }).join("");
  }
  function stored(key, fallback) {
    try { return localStorage.getItem(key) || fallback; } catch (e) { return fallback; }
  }
  var incoming = new URLSearchParams(location.hash.slice(1)).get("study");
  var previousDeck = stored(deckKey, "");
  var deck = incoming && /^[a-f0-9]{32}$/.test(incoming) ? incoming : previousDeck;
  if (!/^[a-f0-9]{32}$/.test(deck)) deck = hex();
  try {
    if (previousDeck && previousDeck !== deck) localStorage.setItem("ytwatcher:study-previous-deck:v1", previousDeck);
    localStorage.setItem(deckKey, deck);
    var data = JSON.parse(stored(pendingKey, "[]"));
    if (Array.isArray(data)) pending = data;
  } catch (e) { saveStatus.textContent = "Keep this page open until your lookups have synced."; }
  if (incoming && /^[a-f0-9]{32}$/.test(incoming)) {
    history.replaceState(null, "", location.pathname + location.search);
    saveStatus.textContent = "Shared flashcard deck connected.";
  }
  function savePending() {
    try {
      localStorage.setItem(pendingKey, JSON.stringify(pending));
      pendingDurable = true;
    } catch (e) {
      pendingDurable = false;
      saveStatus.textContent = "Keep this page open until your lookups have synced.";
    }
  }
  async function request(path, body, selectedDeck) {
    var controller = new AbortController();
    var timeout = setTimeout(function () { controller.abort(); }, 20000);
    var options = {method: body === undefined ? "GET" : "POST", cache: "no-store",
      headers: {"X-Study-Deck": selectedDeck || deck}, signal: controller.signal};
    if (body !== undefined) {
      options.headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(body);
    }
    try {
      var response = await fetch(api + path, options);
      var data = await response.json();
      if (!response.ok) throw new Error(data.error || "Flashcards unavailable");
      return data;
    } catch (e) {
      if (e.name === "AbortError") throw new Error("Flashcards unavailable. Please try again.");
      throw e;
    } finally { clearTimeout(timeout); }
  }
  function flush() {
    if (flushing) return flushing;
    if (!pending.length) return Promise.resolve(true);
    flushing = (async function () {
      while (pending.length) {
        var first = pending[0], batch = [];
        if (first.action === "record") {
          for (var i = 0; i < pending.length && batch.length < 50; i++) {
            if (pending[i].action !== "record" || pending[i].deck !== first.deck) break;
            batch.push(pending[i].event);
          }
          await request("/flashcards/record", {events: batch}, first.deck);
          pending.splice(0, batch.length);
        } else {
          await request("/flashcards/review", first.event, first.deck);
          pending.shift();
        }
        savePending();
      }
      saveStatus.textContent = "Saved to flashcards.";
      return true;
    })().catch(function () {
      saveStatus.textContent = pendingDurable ? "Saved on this device; waiting to sync." :
        "Waiting to sync; keep this page open.";
      return false;
    }).finally(function () { flushing = null; });
    return flushing;
  }
  function record(data) {
    try {
    if (!data.source || !data.translation) return;
    var event = {
      id: hex(), created: Date.now() / 1000, kind: data.kind,
      source: String(data.source), translation: String(data.translation),
      src: String(data.src || "es").toLowerCase(), dst: String(data.dst || "en").toLowerCase(),
      pos: String(data.pos || "").slice(0, 100), inf: String(data.inf || "").slice(0, 100),
      meanings: Array.isArray(data.meanings) ? data.meanings.slice(0, 10).map(function (v) { return String(v).slice(0, 500); }) : [],
      context: String(data.context || "").slice(0, 2000),
      video_title: String(data.video_title || "").slice(0, 500),
      video_href: String(data.video_href || "").slice(0, 2000)
    };
    pending.push({action: "record", deck: deck, event: event});
    savePending();
    saveStatus.textContent = "Saving lookup…";
    flush();
    } catch (e) {
      saveStatus.textContent = "Could not record this lookup. Please try again.";
    }
  }
  function showStats(stats) {
    statsEl.textContent = stats.total + " cards · " + stats.words + " words · " + stats.sentences +
      " sentences · " + stats.due + " due · " + stats.learned + " remembered";
  }
  function language(code) {
    try { return new Intl.DisplayNames([navigator.language || "en"], {type: "language"}).of(code.split("-")[0]); }
    catch (e) { return code; }
  }
  function renderLibrary() {
    libraryEl.replaceChildren();
    var search = searchEl.value.trim().toLocaleLowerCase();
    var matching = cards.filter(function (card) {
      return (kindEl.value === "all" || card.kind === kindEl.value) &&
        (targetEl.value === "all" || card.dst === targetEl.value) &&
        (!search || (card.source + " " + card.translation).toLocaleLowerCase().includes(search));
    });
    if (!matching.length) {
      libraryEl.textContent = "No matching cards yet. Look up a word or translate a sentence to add one.";
      return;
    }
    if (matching.length > 200) {
      var notice = document.createElement("p");
      notice.textContent = "Showing the first 200 matching cards. Use search to find others.";
      libraryEl.appendChild(notice);
    }
    matching.slice(0, 200).forEach(function (card) {
      var row = document.createElement("div");
      row.className = "study-card";
      var source = document.createElement("strong");
      source.textContent = card.source;
      var translation = document.createElement("div");
      translation.textContent = card.translation;
      var meta = document.createElement("small");
      meta.textContent = language(card.src) + " → " + language(card.dst) + " · " + card.lookups +
        " lookups · " + card.reviews + " reviews";
      row.append(source, translation, meta);
      libraryEl.appendChild(row);
    });
  }
  async function load() {
    await flush();
    var data = await request("/flashcards");
    cards = data.cards;
    showStats(data.stats);
    renderLibrary();
  }
  function resetQuiz() {
    current = null;
    revealed = false;
    quizEl.hidden = true;
    ratingsEl.hidden = true;
  }
  async function next() {
    var requestSerial = ++serial;
    resetQuiz();
    nextEl.disabled = true;
    status.textContent = "Choosing a card…";
    try {
      await flush();
      var data = await request("/flashcards/quiz", {kind: kindEl.value, target: targetEl.value, exclude: recent.slice(-5)});
      if (requestSerial !== serial) return;
      showStats(data.stats);
      if (!data.card) {
        status.textContent = "No cards for these filters yet. Look up words or translate sentences while watching.";
        return;
      }
      current = data.card;
      recent.push(current.id);
      if (recent.length > 20) recent.shift();
      var reverse = directionEl.value === "reverse" || (directionEl.value === "mixed" && Math.random() < .5);
      questionEl.textContent = reverse ? current.translation : current.source;
      expected = reverse ? current.source : current.translation;
      alternatives = reverse ? [] : current.meanings || [];
      document.getElementById("study-prompt").textContent = (current.kind === "word" ? "Word" : "Sentence") +
        " · " + language(reverse ? current.dst : current.src) + " → " + language(reverse ? current.src : current.dst);
      answerEl.value = "";
      solutionEl.hidden = true;
      revealEl.hidden = false;
      document.getElementById("study-comparison").textContent = "";
      document.getElementById("study-context").hidden = true;
      quizEl.hidden = false;
      ratingsEl.querySelectorAll("button").forEach(function (button) { button.disabled = false; });
      status.textContent = data.practice ? "Extra practice: no cards are due for these filters." : "Try recalling the answer, then reveal it.";
    } catch (e) {
      if (requestSerial === serial) status.textContent = e.message || "Review unavailable. Try again when connected.";
    } finally {
      if (requestSerial === serial) nextEl.disabled = false;
    }
  }
  function normalized(text) { return text.trim().toLocaleLowerCase().replace(/[.!?。！？]+$/g, "").replace(/\s+/g, " "); }
  revealEl.addEventListener("click", function () {
    if (!current) return;
    revealed = true;
    solutionEl.textContent = expected + (alternatives.length ? "\nAlso: " + alternatives.join(" · ") : "") +
      (current.pos ? "\n" + current.pos : "") + (current.inf ? " · " + current.inf : "");
    solutionEl.hidden = false;
    revealEl.hidden = true;
    ratingsEl.hidden = false;
    var typed = normalized(answerEl.value);
    document.getElementById("study-comparison").textContent = typed && [expected].concat(alternatives).some(function (v) {
      return normalized(v) === typed;
    }) ? "Your answer matches. Rate how easily you recalled it." : "Compare your answer, then rate your recall.";
    var context = document.getElementById("study-context");
    context.textContent = (current.context ? "Subtitle context: " + current.context : "") +
      (current.video_title ? "\nFrom: " + current.video_title : "");
    context.hidden = !context.textContent;
  });
  ratingsEl.addEventListener("click", async function (event) {
    var button = event.target.closest("[data-study-rating]");
    if (!button || !current || !revealed || button.disabled) return;
    ratingsEl.querySelectorAll("button").forEach(function (b) { b.disabled = true; });
    pending.push({action: "review", deck: deck,
      event: {id: hex(), card: current.id, rating: button.dataset.studyRating}});
    savePending();
    status.textContent = "Saving your recall…";
    await next();
  });
  function clearRequest() { ++serial; nextEl.disabled = false; resetQuiz(); }
  function close() {
    clearRequest();
    if (dialog.open && dialog.close) dialog.close();
    else dialog.removeAttribute("open");
    dialog.classList.remove("study-fallback");
  }
  document.getElementById("study-close").addEventListener("click", close);
  dialog.addEventListener("cancel", clearRequest);
  document.querySelectorAll(".study-open").forEach(function (button) {
    button.addEventListener("click", async function () {
      beforeOpen();
      clearRequest();
      if (!dialog.open) {
        if (dialog.showModal) dialog.showModal();
        else { dialog.setAttribute("open", ""); dialog.classList.add("study-fallback"); }
      }
      status.textContent = "Loading your deck…";
      try { await load(); status.textContent = "Choose Random quiz to start. Your recall determines when each card returns."; }
      catch (e) { status.textContent = e.message || "Deck unavailable. Try again when connected."; }
    });
  });
  nextEl.addEventListener("click", next);
  [kindEl, targetEl, directionEl].forEach(function (select) {
    select.addEventListener("change", function () { clearRequest(); renderLibrary(); status.textContent = "Choose Random quiz to start."; });
  });
  searchEl.addEventListener("input", renderLibrary);
  document.getElementById("study-saved").addEventListener("toggle", function () {
    if (this.open) load().catch(function (e) { status.textContent = e.message; });
  });
  document.getElementById("study-sync").addEventListener("click", async function () {
    var url = new URL(location.href);
    url.hash = "study=" + deck;
    try {
      await navigator.clipboard.writeText(url.href);
      status.textContent = "Sync link copied. Open it on your other device. Anyone with this link can access this deck.";
    } catch (e) {
      var field = document.createElement("textarea");
      field.readOnly = true;
      field.value = url.href;
      dialog.appendChild(field);
      field.focus(); field.select();
      status.textContent = "Copy the selected link and open it on your other device. Share it only with people who may access your deck.";
    }
  });
  window.addEventListener("online", flush);
  setInterval(function () { if (pending.length && !document.hidden) flush(); }, 30000);
  flush();
  return {record: record};
}
