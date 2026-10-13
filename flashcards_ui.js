// Embedded in the player script by generate_index_html; uses no external library.
function initStudy(api, beforeOpen) {
  var dialog = document.getElementById("study-dialog");
  var saveStatus = document.getElementById("study-save-status");
  var status = document.getElementById("study-status");
  var statsEl = document.getElementById("study-stats");
  var kindEl = document.getElementById("study-kind");
  var targetEl = document.getElementById("study-target");
  var directionEl = document.getElementById("study-direction");
  var modeEl = document.getElementById("study-mode");
  var scoringEl = document.getElementById("study-scoring");
  var choicesEl = document.getElementById("study-choices");
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
  var assessment = null, answered = false, elapsedMs = 0, startedAt = null;
  function hex() {
    var bytes = new Uint8Array(16);
    crypto.getRandomValues(bytes);
    return Array.from(bytes).map(function (b) { return b.toString(16).padStart(2, "0"); }).join("");
  }
  function stored(key, fallback) {
    try { return localStorage.getItem(key) || fallback; } catch (e) { return fallback; }
  }
  scoringEl.value = stored("ytwatcher:study-scoring:v1", "auto") === "manual" ? "manual" : "auto";
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
    assessment = null;
    answered = false;
    startedAt = null;
    elapsedMs = 0;
    nextEl.textContent = "Random quiz";
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
      answerEl.readOnly = false;
      solutionEl.hidden = true;
      revealEl.hidden = false;
      document.getElementById("study-comparison").textContent = "";
      document.getElementById("study-context").hidden = true;
      quizEl.hidden = false;
      ratingsEl.querySelectorAll("button").forEach(function (button) { button.disabled = false; });
      choicesEl.replaceChildren();
      var options = data.choices && data.choices[reverse ? "reverse" : "forward"] || [];
      var multiple = modeEl.value === "choice" && options.length >= 2;
      choicesEl.hidden = !multiple;
      answerEl.hidden = multiple;
      revealEl.hidden = multiple;
      if (multiple) options.forEach(function (value, index) {
        var button = document.createElement("button");
        button.type = "button";
        button.textContent = String.fromCharCode(65 + index) + ". " + value;
        button.addEventListener("click", function () {
          if (revealed) return;
          var correct = normalized(value) === normalized(expected);
          choicesEl.querySelectorAll("button").forEach(function (option, optionIndex) {
            option.disabled = true;
            if (normalized(options[optionIndex]) === normalized(expected)) option.classList.add("study-correct");
          });
          if (!correct) button.classList.add("study-wrong");
          assessment = {correct: correct, seconds: answerSeconds(), mode: "choice"};
          revealAnswer(correct ? "Correct." : "Incorrect. This card will return sooner.");
          if (!correct && scoringEl.value === "manual") ratingsEl.querySelectorAll("button").forEach(function (rating) {
            rating.disabled = rating.dataset.studyRating !== "again";
          });
        });
        choicesEl.appendChild(button);
      });
      var instruction = multiple ? "Choose the correct answer." :
        modeEl.value === "choice" ? "Not enough distinct saved answers yet. Type an answer to check it." :
        scoringEl.value === "auto" ? "Type an answer to check it against the saved translation." :
        "Try recalling the answer, then reveal it.";
      revealEl.textContent = scoringEl.value === "auto" ? "Check answer" : "Show answer";
      startedAt = document.hidden ? null : performance.now();
      status.textContent = (data.practice ? "Extra practice: no cards are due. " : "") + instruction;
    } catch (e) {
      if (requestSerial === serial) status.textContent = e.message || "Review unavailable. Try again when connected.";
    } finally {
      if (requestSerial === serial) nextEl.disabled = false;
    }
  }
  function normalized(text) { return text.normalize("NFC").trim().toLocaleLowerCase().replace(/[.!?。！？]+$/g, "").replace(/\s+/g, " ").trim(); }
  function answerSeconds() {
    return Math.min(86400, (elapsedMs + (startedAt === null ? 0 : performance.now() - startedAt)) / 1000);
  }
  document.addEventListener("visibilitychange", function () {
    if (!current || revealed) return;
    if (document.hidden && startedAt !== null) {
      elapsedMs += performance.now() - startedAt;
      startedAt = null;
    } else if (!document.hidden && startedAt === null) startedAt = performance.now();
  });
  function saveReview(rating) {
    if (answered) return;
    var event = {id: hex(), card: current.id, rating: rating};
    if (assessment) event.assessment = assessment;
    pending.push({action: "review", deck: deck, event: event});
    answered = true;
    savePending();
    flush();
  }
  function revealAnswer(feedback) {
    if (!current || revealed) return;
    var typed = normalized(answerEl.value);
    if (!assessment && scoringEl.value === "auto" && !typed) {
      status.textContent = "Type an answer first, or select Manual ratings for mental recall.";
      answerEl.focus();
      return;
    }
    if (!assessment && typed) assessment = {
      correct: [expected].concat(alternatives).some(function (v) { return normalized(v) === typed; }),
      seconds: answerSeconds(), mode: "typed"
    };
    revealed = true;
    solutionEl.textContent = expected + (alternatives.length ? "\nAlso: " + alternatives.join(" · ") : "") +
      (current.pos ? "\n" + current.pos : "") + (current.inf ? " · " + current.inf : "");
    solutionEl.hidden = false;
    revealEl.hidden = true;
    ratingsEl.hidden = scoringEl.value === "auto";
    answerEl.readOnly = true;
    document.getElementById("study-comparison").textContent = feedback || (typed && [expected].concat(alternatives).some(function (v) {
      return normalized(v) === typed;
    }) ? "Your answer matches. Rate how easily you recalled it." : "Compare your answer, then rate your recall.");
    var context = document.getElementById("study-context");
    context.textContent = (current.context ? "Subtitle context: " + current.context : "") +
      (current.video_title ? "\nFrom: " + current.video_title : "");
    context.hidden = !context.textContent;
    if (scoringEl.value === "auto") {
      document.getElementById("study-comparison").textContent = (assessment.correct ? "Correct" :
        assessment.mode === "typed" ? "Does not match the saved answer" : "Incorrect") +
        " · " + assessment.seconds.toFixed(1) + " seconds";
      saveReview("auto");
      nextEl.textContent = "Next card";
      status.textContent = "Result recorded automatically. Choose Next card to continue.";
    } else status.textContent = "Choose a recall rating to save this result and continue.";
  }
  revealEl.addEventListener("click", function () { revealAnswer(); });
  ratingsEl.addEventListener("click", async function (event) {
    var button = event.target.closest("[data-study-rating]");
    if (!button || !current || !revealed || button.disabled) return;
    ratingsEl.querySelectorAll("button").forEach(function (b) { b.disabled = true; });
    saveReview(button.dataset.studyRating);
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
  [kindEl, targetEl, directionEl, modeEl, scoringEl].forEach(function (select) {
    select.addEventListener("change", function () { clearRequest(); renderLibrary(); status.textContent = "Choose Random quiz to start."; });
  });
  scoringEl.addEventListener("change", function () {
    try { localStorage.setItem("ytwatcher:study-scoring:v1", scoringEl.value); } catch (e) {}
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
