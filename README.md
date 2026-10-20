# ytwatcher

A small YouTube subscription watcher. It polls subscribed channels for new
videos and downloads the ones that match each subscription's filter using
[yt-dlp](https://github.com/yt-dlp/yt-dlp).

## Requirements

- Python 3.10+
- `yt-dlp`, `PyYAML`, `requests`, and `python-dotenv` (all installed in the project `.venv`)
- `ffmpeg` on PATH (for merging video+audio formats)
- `deno` on PATH (JavaScript runtime; recent yt-dlp needs it to extract
  some videos). Install to `~/.local/bin` — the service unit adds it to
  PATH:

  ```bash
  mkdir -p ~/.local/bin
  curl -fsSL https://github.com/denoland/deno/releases/latest/download/deno-x86_64-unknown-linux-gnu.zip -o /tmp/deno.zip
  unzip -o /tmp/deno.zip -d ~/.local/bin && rm /tmp/deno.zip
  ```

## Setup

```bash
python -m venv .venv
.venv/bin/pip install yt-dlp PyYAML requests python-dotenv
```

## Configuration

Edit `subscriptions.yaml` (copy `subscriptions.sample.yaml` to get started;
the real file is gitignored):

- `settings.download_dir` — root directory for downloads; each channel gets
  its own subdirectory (`download_dir/<channel name>/`).
- `settings.check_interval_minutes` — how often to scan in loop mode.
- `settings.recent_videos_to_scan` — how many recent videos per channel to
  inspect each round.
- `settings.api_host` / `settings.api_port` — where the watched-mark
  endpoint listens (defaults `127.0.0.1` / `8791`; loopback is enough
  when nginx proxies on the same host).
- `settings.api_allowed_hosts` — optional list of extra `Host` header
  names the API answers for: exact hostnames, CIDR networks
  (`100.64.0.0/10`), or IP-prefix wildcards (`192.168.0.*`). The server's
  own addresses are always allowed.
- `settings.site_title` — title of the generated `index.html` page, used for
  both `<title>` and `<h1>` (default `Downloads`).
- Each subscription has:
  - `name` — used for logging and the download subdirectory.
  - `url` — channel URL (the `/videos` and `/streams` tabs are appended
    automatically), or a list of channel URLs to combine under one `name`.
  - `match` — `all` to download everything, or a list of keywords; a video
    matches if any keyword appears in its title (case-insensitive).
  - `exclude` — optional list of keywords; a video is skipped if any
    keyword appears in its title (case-insensitive). Takes precedence
    over `match`.
  - `quality` — yt-dlp format string passed via `-f`.
  - `skip_shorts` — when `true`, skip titles tagged `#shorts`, `#short`,
    `#shortvideo`, or `#shortsfeed` (case-insensitive), regardless of duration.
    Also skip videos at or below `shorts_max_duration` seconds (default `60`).
    Original titles are checked too when fetched for matching or exclusions.
  - `subtitles` — optional subtitle language selectors, such as `["es.*"]`;
    download published captions, with automatic captions as fallback.
  - `require_subtitles` — optional (default `false`); requires `subtitles`.
    Fetch and validate at least one subtitle file in the requested languages
    before downloading audio/video. If captions are missing or cannot be fetched,
    skip the media and retry on later scans without marking the video as seen.
    Published and automatic captions both qualify. Existing files are unaffected.
  - `keep_watched` — optional (default `false`); when `true`, files you
    mark as watched are moved into a `watched` subdirectory of the
    channel folder instead of being deleted.

If a listing title does not match, ytwatcher checks the single-video title
before rejecting it. This catches original-language keywords when YouTube
translates a channel's listing. If that lookup fails, the video stays eligible
for a later retry. Exclusion keywords still take precedence, and the original
title lookup is reused for exclusions rather than fetched twice.

## Usage

Static folder links are configured separately from subscriptions:

```yaml
static:
  - name: ReinforceLearning
    path: /srv/files/static/ReinforceLearning
    url: /ytwatcher/static/ReinforceLearning/
```

The index renders these links under **Static** in configuration order. Changes
are picked up during the next index rebuild, including when the media listing
has not changed. Use `static: []` or omit the section to hide it. If `url` is
omitted, folders under `/srv/files/static/` use their relative path under
`/ytwatcher/static/`. One shared nginx route serves this entire static root;
additional subfolders need no nginx changes. Folders elsewhere require an
explicit existing route or a symlink inside the static root. Only put folders
you want web-accessible inside that root, including symlink targets.
Run `sudo python3 install_static_route.py --apply` once to migrate the original
ReinforceLearning folder and replace its individual route with the shared route.
Static folders are listed recursively for playable video/audio files, with
**+ Playlist** buttons and support for matching WebVTT subtitle files. Incomplete
downloads are omitted. Removing a static item from the playlist only removes
the queue entry: it never marks the media watched or deletes it, even if its
filename contains a YouTube ID. Static folders remain outside download state
and watched-file cleanup. Folder links still provide access to other file types.

Single test round:

```bash
.venv/bin/python main.py --once
```

Dry run (list new videos and match decisions without downloading or
touching `state.json`):

```bash
.venv/bin/python main.py --scan
```

Continuous watching (scans every `check_interval_minutes`):

```bash
.venv/bin/python main.py
```

Regenerate the download index from existing files without scanning YouTube:

```bash
.venv/bin/python main.py --generate-index
```

Validate `subscriptions.yaml` (exits non-zero and lists the problems if
invalid):

```bash
.venv/bin/python main.py --check
```

## Manual downloads

Dictionary lookups keep the subtitle language fixed, including `es-orig` → `es`.
Fallback-cache entries record their provider, language pair, and lookup version.
Legacy fallback answers from the former language-detection path are rechecked
before reuse; offline lexicon entries and reviewed corrections take precedence.


Each library item with a YouTube ID has a **⇩ Subtitles** button alongside
**⇩ Video**. It fetches published subtitles, falling back to auto-generated
captions for each requested language, and saves WebVTT files next to the media.
It uses the subscription's `subtitles` setting (for example `es.*` or
`[es, en]`). Without that setting, it prefers YouTube's original-language
captions, using published subtitles before automatic captions in that language.
If the original language is unknown, it selects an available published track,
then English automatic captions or another available automatic track. The button shows
progress/errors; the library and active player's subtitle tracks refresh when
the job completes. The media itself is not downloaded again.

The index page has a download form at the top: paste a video URL, pick a
quality (720p / Best / Audio only), and click **Download**. The page polls
the API for the job status and reloads once the file appears.

The same thing from the command line: `manual_download.py` downloads a
single video by URL into `download_dir/manually/`, using the best quality
up to 720p by default
(`bestvideo[height<=720]+bestaudio/best[height<=720]`). Override the
quality with `-f` or `-S`, passed through to yt-dlp exactly as-is:

```bash
.venv/bin/python manual_download.py "https://www.youtube.com/watch?v=..."
.venv/bin/python manual_download.py -f "bestvideo+bestaudio/best" URL
.venv/bin/python manual_download.py -S "res:1080" URL
```

The filename carries the YouTube `[id]`, so the entry on the index page
can be marked watched and the file is deleted at the next scan round like
any other download. The video ID is also added to `state.json` so the
watcher never re-downloads it afterwards, and `index.html` is rebuilt
right away.

## Private Frankfurt downloader

The separate `yt_dl_temp.py` app isolates downloads by login account. Each
account has its own files, job history, last-access times, and retention
setting. Download and playback URLs verify the login too; knowing another
account's filename does not grant access. Responses are private and are
not stored in browser/proxy caches.

Install its extra dependency with
`.venv/bin/pip install -r requirements-tempdl.txt`. Store `username bcrypt-hash`
records in `.web-users` beside the script, or set `YT_TEMP_USERS_FILE` to that
file. This file is gitignored and should have mode `600`. Caddy passes the
original `Authorization` header to the app (its default proxy behavior).
Account-file changes take effect without restarting the app.

### Account management

`justin` is the only administrator. The **Konto / Passwort ändern** page lets
justin add users and lets everyone change their own password by entering their
current password and confirming the new one. Usernames are case-sensitive;
new usernames accept 1–64 ASCII letters, digits, dots, underscores or hyphens.
Passwords must contain at least 8 characters and at most 72 UTF-8 bytes. Only bcrypt hashes are saved, using
atomic writes and a lock; duplicate accounts cannot overwrite existing users.
Account forms have CSRF protection. Changing a password immediately invalidates
the old credentials and sessions, and keeps that browser signed in using a
Secure, HttpOnly, SameSite cookie for up to 12 hours. After expiry or a backend
restart, log in with the new password if prompted. Each new account starts with
its own private downloads and the default retention setting.

Caddy must not keep a separate `basic_auth` password list for this site.
For the existing Frankfurt deployment, first deploy the updated backend, then
prepare the narrow proxy migration with:

```sh
.venv/bin/python enable_tempdl_accounts.py --stage
sudo .venv/bin/python enable_tempdl_accounts.py
```

The helper validates the complete Caddyfile, checks that it has not changed
since staging, backs it up outside the configuration directory, removes only
this site's duplicate Basic auth, persists the change and reloads Caddy.
It then creates `.account-management-enabled`; the UI and account mutations
stay disabled until this marker exists. Other routes remain unchanged. This
one-time activation requires sudo; later account changes require no reload
or restart. New installations should proxy directly to the authenticated app
and create the marker after configuring HTTPS.

`YT_TEMP_DIR` defaults to `/srv/files/yt-dl-private` and must be outside the
shared `/srv/files/static` root. Each login uses a separate private subfolder.
Existing shared files have no recorded owner, so they are hidden from all
accounts and expire through the existing cleanup. New downloads retain the
same download/play buttons and user-configurable retention period.

## Cookies

Some videos (members-only, age-restricted, bot-checked) only download
with a logged-in session. If a download — manual or from a subscription —
fails, yt-dlp automatically retries it once with `cookies.txt` from the
project directory, when that file exists.

The easiest way to set it up is the **Cookies for yt-dlp** section on the
index page: export your YouTube cookies in Netscape format (e.g. with a
"Get cookies.txt" browser extension) and upload the file there — or paste
the text into the box. Saving replaces the current cookies; saving an
empty box removes them. The file
is stored with mode `0600`, is gitignored, and its content is never shown
in the UI or returned by the API (`GET /cookies` only reports whether
cookies are set) — paste it only over a connection you trust, since the
API itself has no encryption or authentication. You can also create
`cookies.txt` by hand; no restart is needed either way.

## Download index

After any round that completes a download, `main.py` rebuilds
`download_dir/index.html` from the files already on disk. The page groups
videos by channel subfolder, newest first within each group, and links to each
file with a relative path so it works behind nginx. It only rewrites the file
when the listing actually changes, so `index.html` is not touched on rounds
with no new downloads. Each entry shows its duration (reported by yt-dlp
at download time and cached in `durations.json`, keyed by path and
validated by size+mtime; files that didn't go through the downloader
simply show no duration), upload date, and size.

Each entry has a **Mark watched** button. Watched videos are dimmed,
struck through, and moved to the bottom of their list. The watched state
is kept in the browser's `localStorage` (keyed by the YouTube video ID in
the filename), so it survives index rebuilds.

Playlist rows use the same title, metadata, and media tools as Latest. The separate
Latest list starts collapsed; use **Show** to open it. **Add latest** and
**Auto-add latest** work while it is collapsed.

Each entry also has a **+ Playlist** button. Queued entries are marked
without relying on color: the button reads **✓ In playlist** (click it
again to remove the video) and the link gets a "≡" marker and bold text.
The playlist lives in the browser's `localStorage` and is shown in the
**Playlist** section at the top of the page: **Play** starts an embedded
player that plays the queued videos one after another, **Repeat** loops
the playlist indefinitely, and **Clear** empties it. Clicking a queued
item jumps to it; the ✕ button removes it. The queue and the repeat
setting survive page reloads, but are per-browser, like the watched
marks.

During playback, **Landscape** opens a landscape view of the player and
its subtitle tools. When the screen stays portrait because rotation is
locked, the view rotates sideways. Android uses browser fullscreen when
available; iPhone uses an overlay within the page, so Safari's bars may
remain visible. Original subtitles, text selection/copy, and word translation
remain available. **Exit landscape** returns to the normal page. The view
is optional and is not enabled automatically or saved across page reloads.

**Translate sentence** pauses playback and translates the sentence at the
current position using the local LLM gateway. Sentences are assembled from
subtitle punctuation across cue boundaries. Every complete sentence touched
by the current subtitle is included, even when a cue contains the end of one
sentence and the beginning of another. The original Spanish text stays available alongside
the translation, and word lookup/copy continue to work. Changing the target
language immediately requests a new translation for the displayed sentence.
Caption and translation panels reserve their height to avoid page movement on
mobile. This also works with audio-only captions and Landscape view.

**Copy sentence** pauses playback and copies all complete original sentences
covered by the current subtitle, joining cues up to punctuation boundaries.
It uses the same sentence selection as translation and needs no LLM request.
**Copy subtitles** still copies the currently displayed cue. If clipboard
access is unavailable, a selectable field offers the complete sentence for
manual copying without replacing the subtitle text.

Sentence translations are requested only on button clicks or target-language
changes for an already requested sentence. No sentence translation jobs run on
download or offline preload. Results are reused in memory for up to an hour;
they are not added to the offline cache. The gateway is configured through
`YTWATCHER_LLM_URL` (default `http://127.0.0.1:8349`). Sentence requests omit
the model name so the gateway chooses its configured default model. The app uses
short job-status requests while generation runs, so loading the model does not
hold the web proxy connection open.

### Offline word dictionaries

`build_lexicon.py` downloads and caches [Kaikki/Wiktionary data](https://kaikki.org/)
and builds these compact language pairs:

| Source | Target | Local file |
| --- | --- | --- |
| Spanish | English | `lexicon-es-en.json` |
| Spanish | German | `lexicon-es-de.json` |
| German | Spanish | `lexicon-de-es.json` |
| Spanish | Chinese (Mandarin) | `lexicon-es-zh.json` |

```bash
.venv/bin/python build_lexicon.py --all
.venv/bin/python refresh_offline_dictionaries.py
```

Use `--lang es --to de` to rebuild one pair. Downloaded source files remain in
`.cache/lexicon-source/` so repeat builds reuse the same data. To download a
newer dump, remove the corresponding cached JSONL file before rebuilding.
`lexicon-build-info.json` records source sizes/dates and resulting word counts.
Built files replace the previous versions atomically and load lazily on use;
the server notices updated files without a restart. The old `lexicon-es.json`
is retained only as a fallback when the new English pair is absent.
Full lexicons rebuild only when the build command is explicitly run. Saved
per-video word lists are reused across server restarts and preload requests;
they refresh only when their subtitles, lexicon revision, or format changes.
The refresh command also updates dictionaries and UI assets in existing local
learning clips, preserving their media, sentences, and clip IDs. Existing device
caches need another Preload offline / Save offline to receive the new data.

Dictionary format 3 keeps each source part of speech and sense separately,
including grammatical tags, source sense IDs, and same-POS lemma references.
For example, `criados` keeps both the plural noun linked to `criado` (servant)
and the participle linked through `criado` to `criar`; a verb cannot overwrite
the noun. Alternative forms and abbreviations also retain their source links.
No six-meaning limit is applied. Source order is retained, with rare/archaic
senses labelled and reviewed defaults retained as labelled additional senses.

Other pairs prefer direct translations. English-pivot translations fill gaps
only for source words with the same part of speech, and only within one English
sense. They are labelled separately and link back to the pivot source. The
lookup UI displays grammatical meanings separately and links to Wiktionary.
An exact source English definition can bridge to the primary matching English
sense when its part of speech also matches; that path is labelled Via English.
A cached projection of the relevant English translation groups is pinned to
the original dump size/mtime, and preserves sense labels, tags, and source IDs.
Downloaded sources are reused for this one-time rebuild; rebuilding does not
call Google or a language model. Old lookup caches cannot override source data.

Downloads and **Preload offline** build/cache the subtitle's word list for every
supported target of its source language. English entries retain their old
top-level format; other targets live in `_targets`, with source/revision/coverage
under `_meta`. Switching target language uses the corresponding cached map.
Preload waits for dictionary building to finish and reports word coverage;
words absent from the source data need a connection for the existing online
lookup fallback. No LLM or Google calls are made during lexicon building or
offline preload. Sentence translations remain on demand. Refresh the page and
run **Preload offline** again to update dictionaries already cached on a phone.

### Vocabulary and sentence flashcards

The offline lexicon builder uses the source word's ordered English definitions
from Kaikki/English Wiktionary before reverse translation-table fallbacks.
Reviewed defaults in `dictionary_corrections.py` take precedence over old API
and browser dictionary caches, including offline lookups. Rebuilding a subtitle
dictionary also applies these corrections. The `ubicado` family defaults to
**located / situated**; existing cards with the old **seemly** answer are repaired
without resetting study progress or changing historical lookup events.

Every successful word lookup (including offline/cached dictionary answers) and
displayed sentence translation is automatically recorded. Repeated lookups
update the same card and its lookup count; target languages and word/sentence
cards are kept separate. Records include the original subtitle context and
video title, shown after revealing a quiz answer. Only user lookups are recorded;
building or preloading a dictionary does not fill the deck with unstudied words.

Open **Flashcards** above the playlist or beside the subtitle tools, then choose
**Random quiz**. Filter words/sentences or target languages, and optionally
reverse the translation direction. **Multiple choice** offers up to four shuffled
answers from your own saved cards of the same type and language pair. Known
duplicate translations and overlapping meanings are excluded as distractors.
With fewer than two distinct answers, the quiz falls back to typed recall.
**Automatic scoring** is the default: choosing an option or checking a typed
answer records correctness and response time immediately, without a rating step.
Time spent with the page hidden is excluded. Incorrect answers use **Forgot**;
correct word answers within 5/15 seconds use **Easy**/**Remembered**, with slower
answers using **Hard**. Sentence thresholds are 15/45 seconds. Choose **Next card**
after reading the feedback. Typed answers are compared with the saved answer and
known alternative meanings, ignoring case, whitespace, and trailing sentence
punctuation; other valid paraphrases may not match.
Choose **Manual ratings** for optional self-assessment or mental recall, then
rate **Forgot**, **Hard**, **Remembered**, or **Easy**. Incorrect multiple-choice
answers only offer **Forgot**. The scoring preference is saved on the device.
Quiz answers use saved translations and do not call the LLM. Due cards
are randomized with extra weight for forgotten/frequently consulted cards;
when nothing is due, extra practice remains available. Forgot schedules another
review in 10 minutes; first Remembered/Easy reviews schedule 1/4 days, and later
intervals grow with successful recall. Looking a card up again brings it due.

Decks and the complete lookup/review event history are saved in SQLite at
`.flashcards.sqlite3` beside the app, outside the served media directory and
gitignored (`YTWATCHER_FLASHCARDS_DB` overrides the path). Each browser gets a
separate random deck key; APIs require that key and never expose other decks.
**Copy sync link for another device** shares the same deck and progress with
that device. The key is in the link fragment, not the HTTP URL, and is sent to
the API in a private header. Anyone who has the link can access that deck.
Opening a sync link selects that deck; it does not merge existing decks.

Lookup records and recall ratings waiting to sync are saved in browser storage
and retried on reconnect, later page visits, or while the page is visible.
Unique event IDs make retries idempotent. Quizzes and the saved-card browser
need a connection to ytwatcher. Playback pauses when opening the review dialog;
caption nodes, word tools, sentence translation, and Landscape playback remain
available. Save-status space is reserved so recording a lookup does not move
the player on mobile.

Manually downloaded videos work too: drop the file anywhere under
`download_dir` and it appears in the index after the next rebuild. Since
its filename has no YouTube `[id]`, it gets a stable pseudo-ID derived
from its path, so it can be marked watched like any other entry. The
pseudo-ID changes if you rename or move the file. Unlike watcher
downloads, manual files are **never auto-deleted** when marked watched —
deletion only applies to files whose filename carries a real YouTube ID.

Every mark is also reported to a small HTTP API embedded in the watcher
(`POST /watched` on `settings.api_port`, default `8791`), which records
the video ID in `watched.json`. At the start of each scan round, the
watcher deletes every downloaded file whose video ID is in
`watched.json`, and the index loses those entries on the next rebuild.
For subscriptions with `keep_watched: true`, the file is moved into a
`watched` subdirectory of the channel folder instead of being deleted;
archived files no longer appear in the index. Because removal only
happens when a round runs, a mark can be undone (un-watch the video)
any time before the next round. If the watcher is down when a mark is
made, the mark stays browser-local only and no removal happens.

The same API also backs the two tools at the top of the index page:

- `POST /download` with `{"url": "...", "quality": "720"|"best"|"audio"}`
  starts a background manual download (same behavior as
  `manual_download.py`); `GET /downloads` reports job status.
- `GET /config` returns the raw `subscriptions.yaml`; `POST /config` with
  the raw YAML in the body validates it (400 with a problem list on
  failure) and atomically replaces the file. The watcher re-reads the
  config every round, so saved edits apply from the next round on — no
  restart needed.
- `GET /cookies` reports whether `cookies.txt` is set (never its
  content); `POST /cookies` with a Netscape cookie export in the body
  replaces it, or removes it when the body is empty.

The API binds to `settings.api_host` (default `127.0.0.1`), so the only
client path is the nginx proxy on the same host. It has **no
authentication** — the security posture is "unauthenticated,
network-trusted": any device that can reach nginx (your LAN, plus any
network in `api_allowed_hosts`, e.g. a Tailnet) can mark IDs for
deletion, rewrite `subscriptions.yaml`, and start arbitrary downloads.
The `Host` allowlist only guards against DNS-rebinding from browsers;
it is not access control. Do not expose nginx to untrusted networks
without adding authentication there (e.g. `auth_basic`).

## Telegram notifications

Create a `.env` file next to `main.py` with your Telegram credentials:

```bash
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
```

After each round that completes one or more downloads, a single summary
message is sent to the chat. No messages are sent for skipped or
matched-but-not-downloaded videos. If the credentials are missing, the
watcher prints one warning at startup and continues silently.

Test the notification setup without touching YouTube or `state.json`:

```bash
.venv/bin/python main.py --test-notify
```

## How it works

Each round, for every subscription, the watcher runs
`yt-dlp --flat-playlist` on the channel's `/videos` and `/streams` tabs
(the latter covers channels that publish as live streams) and merges the
listings. Video IDs already in `state.json` are skipped. Live streams and
upcoming premieres are not marked as seen — they are retried each round
and downloaded only once the stream has ended. Other new videos are
marked as seen immediately (even if they don't match or the download
fails) so they are never re-evaluated. Matching videos are downloaded with
the subscription's quality format string. A failure in one channel is
logged and does not abort the round.

`state.json` is created automatically and tracks every video ID ever
scanned. Delete it to re-scan (and re-download) everything.

## Export an offline learning clip

Use **Learn** beside a video with subtitles, or **Export learning page** in the
player. Select a time range and subtitle language. The export expands the range
to complete sentences and creates an independent media clip: removing or marking
the original video watched does not remove the exported lesson. Audio-only files
are supported. Exports are available under `/ytwatcher/static/LearningClips/`.

Each lesson includes:

- Playback that pauses after each punctuated sentence, repeat/loop, slower speed,
  original subtitles, optional translation, copying, and landscape display.
- Microphone recording with multiple attempts per sentence, playback, comparison
  with the original, and downloads of your recordings.
- Original transcript reading, the clip’s offline dictionary entries, gap-fill
  exercises, and multiple-choice vocabulary practice. Quiz choices favor words
  answered incorrectly or slowly. Progress is saved on this browser/device.
- Offline lookup records queued for your existing ytwatcher flashcard deck and
  synced when the server is reachable again.

On the finished lesson choose **Save offline** and wait for the completion message
before disconnecting. Bookmark that lesson URL (or add it to the home screen).
The page, clip, reading, and included dictionaries then work without the server.
Sentence translations requested while connected are stored locally too. Missing
word meanings or sentence translations still require a connection.

Optionally select **Generate reading translations and comprehension questions**
at export time. This uses the gateway’s default model, shares the sentence
translation queue, and can take several minutes. Short clips (roughly 3–5 minutes,
maximum 80 sentences) work best. If the model is busy or fails, the base lesson is
still exported with a warning; export the same selection again to retry. Existing
media is reused. No LLM work is triggered automatically by downloads or preload.
Unpunctuated passages are divided into shorter review sections instead.

Lessons open directly in the browser, including on phones. No ZIP download or
unzipping is needed. Use **Save offline** on the hosted HTTPS page to keep the
lesson on the device. Microphone recording needs a trusted HTTPS origin (or
localhost) and microphone permission.

Voice recordings and answers stay in IndexedDB on the device. They are not
uploaded, and clearing browser storage can remove
them. Download important recordings separately. There is no automatic
pronunciation score: compare the original and your recording by listening.

Exports live outside the watcher’s download cleanup. Identical completed exports
are reused; dictionaries are extracted from the existing local lexicons. Only
explicit export requests create packages; at most two jobs can be pending and
one media conversion runs at a time. Export errors are recorded in the server log.

### Temporary Frankfurt links

On an exported lesson, or in the finished export dialog, choose **Create temporary
link**. This copies only that lesson to Frankfurt and returns an unguessable HTTPS
URL. No downloader login is needed to open that link. Existing private downloader
files, accounts and API routes still require authentication.

Links default to **5 days** (also selectable: 1 day). Five days is the maximum;
opening a link never extends its lifetime. Expired files are removed by the
Frankfurt cleanup loop within about 30 seconds. **Revoke link** removes the copy
early. Offline copies recipients already saved cannot be revoked.
Frankfurt holds at most 2 GB of learning shares; revoke old links or choose shorter
clips if that limit is reached. The original home export remains available. Only lesson files are stored; no
duplicate ZIP archives are created.

Shared pages include only the exported media, subtitles, reading, dictionary and
included exercises/translations. Recordings, answers, progress and flashcard deck
keys are never uploaded. Recipients’ recording/practice works locally; the shared
page does not use the home translation or flashcard API. Include desired reading
translations during export before sharing.

The home API publishes/revokes through the existing `frankfurt` SSH alias, using
`learning_share.py`. The SSH destination can be overridden with
`YTWATCHER_SHARE_SSH`. Link tokens/expiry are kept in gitignored
`.learning-shares.json`. On Frankfurt, `learning_share_server.py` stores copies in
`.learning-shares/` alongside the downloader project and serves only whitelisted
assets under `/learn/<token>/`. It is mounted in the existing `yt_dl_temp.py`
HTTP handler, behind the existing `ytwatcher.duckdns.org` HTTPS proxy. No home
API or library route is exposed. Deploy both Python files together; the remote
module uses only the Python standard library. Public links are excluded from
indexing and send a no-referrer policy.

### Learning-page interface languages

Learning pages, the lesson library, export dialogs, and sharing controls support
English, Spanish, German, and Chinese, including all lesson buttons, recording
controls, quiz feedback, offline-save messages, and accessibility labels. Use
**Interface language** to switch immediately; the preference is remembered on
that browser. Changing it does not restart playback or reset recorded attempts,
answers, or quiz progress. Shared pages and offline copies include the same
translation catalog and need no network request or LLM for the interface.

The interface language is independent of the subtitle and translation language.
Original subtitle/reading text, vocabulary meanings, and generated questions keep
their content language; use the separate **Translation** selector for meanings
and sentence translations. Switching interface language does not generate extra
LLM translations.

The Learning clips library groups lessons by their original subtitle language:
**English**, **Deutsch**, **Español**, and **中文**, with counts and links to each
section. Newest lessons appear first within each language. Empty groups remain
visible. Interface and translation language choices do not move a lesson between
groups. Existing lesson URLs and sharing links stay the same.

### Default lesson translation languages

The export dialog defaults to these targets, based on the selected subtitle:

| Original subtitle | Default translations |
| --- | --- |
| Spanish | English and Chinese |
| English | Chinese |
| Chinese | English |
| German | Spanish |

An explicit language selection overrides the preset for that export. With local
LLM generation enabled, Spanish clips generate both sentence/reading translations
in sequence; comprehension questions and vocabulary explanations are generated
once. All generated languages are embedded in the lesson and are available through
its **Translation** selector, including offline and on shared links. A failure in
one language does not discard valid translations in another. Existing lessons
keep their saved languages; these defaults apply to new exports.

Reviewed dictionary overrides also cover Spanish weather **DANA** ("depresión
aislada en niveles altos"): English "cut-off low", Chinese "高空孤立低压", and
German "abgetrenntes Höhentief", with a short explanation. These take precedence
over an old unchanged-name lookup ("Dana"). Known echoed-word flashcards are
corrected without resetting their review progress.

**Compare my voice → original** plays the selected saved recording first, then
plays the original sentence once. Changing the sentence, recording attempt, or
activity cancels the pending comparison.

### Sentence translation fallback

The main player and learning lessons offer **Open Google Translate** while a
local sentence translation is pending or unavailable. The link opens a new tab
with the complete sentence and the selected source/target languages already set.
Shared lessons can use the same link when no translation was included. Opening
it pauses playback. Google Translate requires internet access; its results are
not automatically imported into the lesson’s offline translations or flashcards.
Saved local translations continue to work offline without this fallback.

On Frankfurt shared lessons, **Translate sentence** opens Google Translate
directly when that sentence has no saved translation and the device is online.
The tab opens inside the original button click so mobile browsers can allow it.
Saved translations still display within the lesson. The separate Google link
remains available if the browser blocks the new tab.
