# LLD Prep — the phone app

Your `LLD Interview Prep` notes, packaged as an offline study app: problems, solutions,
HLD companions, diagrams, full-text search, and spaced-repetition flashcards generated
from your own notes. No network, no account, no data leaves the phone.

```
mobile/
  build.py          notes -> app content bundle   (run this after editing notes)
  serve.py          serve it on your Wi-Fi to read on the phone right now
  www/              the app itself (this is what gets installed)
  android/          Android WebView project -> the APK
  test/             renderer + whole-app tests (no browser needed)
  dist/             LLD-Prep-single.html, one self-contained file
```

---

## Getting it onto your phone

Three ways, cheapest first.

### 1. One file, right now (30 seconds, no accounts)

```
python mobile/build.py --single
```

Copy `mobile/dist/LLD-Prep-single.html` to the phone (USB cable, Google Drive, WhatsApp
to yourself) and open it. Everything — notes, diagrams, flashcards — is inside that one
file, so it works with the phone in airplane mode. Progress is saved in the browser.

No app icon and no home-screen entry, but it is the fastest route to reading on the
train tonight.

### 2. Installed app via GitHub Pages (recommended)

This is a real installed app: own icon, own window, no browser bar, fully offline.

1. Push this folder to a GitHub repo.
2. Repo **Settings → Pages → Source: GitHub Actions**.
3. The `Deploy study app` workflow runs and prints a URL.
4. Open that URL on the phone → Chrome menu → **Install app** / **Add to Home screen**.

After the first load it never needs the network again. Push a notes change and the app
picks up the new version next time it is opened online.

### 3. APK

Requires no Android tooling on your laptop — GitHub builds it.

1. Push to GitHub (same as above).
2. **Actions → Build APK → Run workflow**.
3. Download the `LLD-Prep-apk` artifact, unzip, copy the `.apk` to the phone, tap it.
   Android will ask you to allow installing from that app once.

The APK is debug-signed, which is fine for your own device. It ships with no `INTERNET`
permission at all — the notes are in the package.

To build it locally instead you would need JDK 17 and the Android SDK, then:

```
python mobile/build.py --android
cd mobile/android && gradle assembleDebug
```

---

## After you add a problem

The app is generated from the notes, so nothing needs editing by hand:

```
python mobile/build.py
```

It picks up any `NN-name/` folder and any new top-level `.md`, re-derives the flashcards,
re-stamps the service worker version, and prints what it found. Then push (Pages and the
APK rebuild themselves), or re-run `--single` for the one-file version.

Reading on the phone while editing on the laptop:

```
python mobile/serve.py
```

Prints a `http://192.168.x.x:8000` address to open on the phone. Same Wi-Fi on both.
(Install is not offered over plain http — that needs https, i.e. option 2.)

---

## What the app does

**Home** — a fork, not a list. Two tiles: **LLD** (one machine: classes, responsibilities,
patterns, working code) and **HLD** (many machines: scale, storage, tradeoffs, failure).
Each carries its own progress bar, so it is obvious which track you have been neglecting.
Tapping one opens that track's reading list and its mocks.

**Problems** — each problem is a card with its pattern tags and a dot per section, filled
in as you go. Inside, the sections (Problem / Solution / Explained / HLD / Diagrams) are
tabs; swipe left and right to move between them. Cross-references between your notes
(`solution.py`, `../HLD-method-bank.md`) are live links inside the app.

**Concepts** — the reference docs, grouped: start-here, LLD, HLD.

**Revise** — flashcards built from your notes, no invention:

| Deck | Front | Back |
|---|---|---|
| Naive code to pattern | the first-attempt code | what it's telling you |
| Patterns & principles | pattern name | your definition of it |
| HLD method bank | the phase | the menu of options |
| Entity-finding playbook | the step | your checklist |
| Clarifying questions | the interviewer's one-liner | what you ask |
| Scope & entities | problem + step | what you locked |

Leitner scheduling: "Got it" moves a card to the next box (1 → 3 → 7 → 21 days), "Again"
sends it back to today. The home screen shows what is due.

**Mock** — the interview, not the notes. 21 rounds: 11 LLD (generated from the problem
folders) and 10 HLD (from `../interview-mode/hld/`).

A run goes: the prompt on its own → a clock starts → your clarifying questions → then one
step at a time. **Nothing is revealed until you have answered out loud** — that is the
whole point; reading the checkpoints first turns it back into studying. After each step you
tick what you actually said, and the traps and follow-up questions appear.

The score is self-reported, so the number is not the output — **the "missed" list is**. It
groups everything you did not say, by step, and that is your homework. Best score and run
count are kept per problem.

**Search** — full text across every problem and reference; tapping a hit opens the doc
with the term highlighted.

**Where your progress lives.** Sections revised, stars, card scheduling and settings are
kept in the phone's local storage, under the app's own origin. It survives closing the
app, restarting the phone, and going offline; it is written through immediately whenever
the app is backgrounded, so nothing is lost if Android kills the process. The app also
asks the browser to mark the storage persistent so it is not evicted when space runs low.

It does *not* survive clearing browser data, or uninstalling the APK. So the settings
sheet has **Backup**: it shows your whole progress as text you can copy somewhere safe,
and paste back later to restore. (Text rather than a file download, because a WebView
inside an APK cannot start a download.)

The three delivery routes differ slightly: the installed PWA and the APK each get their
own private, stable storage. The single-file HTML opened straight from the filesystem is
the weakest - some browsers treat `file://` storage as throwaway, so use Backup there.

---

## Tests

There is no Node or browser on this machine, so the suites run under Windows Script Host
against a stubbed DOM. Both are worth re-running after editing `www/app.js`:

```
python mobile/test/make_harness.py && cscript //Nologo //E:JScript mobile/test/_harness.js
python mobile/test/make_smoke.py   && cscript //Nologo //E:JScript mobile/test/_smoke.js
```

- `_harness` renders every doc and card through the markdown renderer and checks the HTML
  is well-formed (balanced tags, no leaked placeholders, every code fence survived).
- `_smoke` drives every view: all 50 problem docs, all references, search, deep links,
  a full flashcard session, backup/restore (including rejecting corrupt backups), and a
  save/reload round trip of your progress.

Three more, for the diagrams and the look of the thing:

```
python mobile/test/check_content.py                     # every note is in the app, byte for byte
python mobile/test/make_diagram_test.py --type all --out out-all
cscript //Nologo //E:JScript mobile/test/_diag-all.js   # render all 24 diagrams
python mobile/test/check_svg.py mobile/test/out-all     # validate the geometry
python mobile/test/gallery.py --in out-all              # ...and look at them
python mobile/test/shoot.py --all                       # screenshot the app at phone size
```

`shoot.py` and `gallery.py` drive headless Edge, so the app can be seen without a phone
in hand. Screenshots land in `mobile/test/shots/`.

---

## Notes on the build

- `www/content.js` is generated. Edit the notes, not that file.
- Diagrams are `mermaid` blocks in your notes, drawn by `www/diagram/*.js` - a small
  purpose-built SVG renderer for the exact syntax these notes use (class, flowchart,
  state and sequence diagrams). It replaced mermaid.js, which was 3.3 MB, loaded
  asynchronously, and silently hung. The renderer is synchronous, ~80 KB, and colours
  itself with CSS variables, so diagrams follow the light/dark theme with no redraw.
  Anything it cannot parse degrades to showing the diagram source rather than nothing.
- The service worker cache key is stamped with a hash of the content, so a rebuild
  invalidates the old bundle instead of serving stale notes.
- Pattern tags on each problem are inferred from how often a pattern is named in that
  problem's own files — a passing mention is not enough to earn a tag.
