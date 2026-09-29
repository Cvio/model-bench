# Instructions: model-bench, an end-to-end test bench for volis

For Claude Code. Build a Python app that tests **complete volis configurations**, meaning a
speech recognizer (ASR), a translator, a prompt and their settings, end to end, for two
languages: **Iraqi Arabic** and **Persian (Farsi)**. It analyses the results with enough rigour
that the conclusions hold up when a colleague challenges them, and writes a report built to be
defended.

Build it in a new folder: `D:\AI_Data\projects\model-bench`.

Read this whole file before writing any code. Then read `model-converter`'s `README.md` and
`train-and-convert-app.md`, and in the volis repo: `src/translate.rs`, `src/asr.rs`,
`src/varieties.rs`. This app reuses the converter, and it follows the converter's setup style
(uv, everything inside the folder, `STOP:` messages).

---

## What this app is for

The goal isn't a leaderboard. It's a **decision that can be defended**: "for Persian, volis
should use this ASR, this translator and this prompt, and here is the evidence". It should hold
up when a sceptical colleague asks the obvious questions:

- Is the difference real, or luck?
- Does the test look like real use?
- Does the score agree with what a fluent speaker thinks?
- How does it fail, and how badly?
- Does the whole chain work, not just the parts?
- Does it work on the machine volis runs on, fast enough for a conversation?
- Did anything else get worse? Could the model have seen the test before?
- Did you try X?

Every one of those has a section in the report (see "The report").

## How it's used: rounds

The app works in **rounds**. The user runs this loop:

1. The user and Claude (in chat) choose the candidate models and prompts, and write down why.
   **The app never searches for or chooses models.**
2. The app tests every configuration, analyses the results, and writes the report.
3. The user and Claude go through the report and the discussion bundle together.
4. The user takes the report to colleagues and stakeholders, and brings back their questions.
5. Those questions become changes to the candidates, prompts or tests, and the next round
   starts.

Each round has a number and a changelog. Work that hasn't changed is never rerun.

---

## How to work on this

- Build in the milestone order at the end. Stop after each milestone, show its check passing,
  and wait for the user to say go on.
- Before the first milestone, summarise back what you understood, and list anything in this
  file that looks wrong or unclear.
- Commit after each milestone passes.
- **Don't choose models.** `candidates.yaml` ships containing only volis's current models, as
  the baseline. The user fills in the rest.
- The app downloads from the internet and runs on the 5090 desktop. That's fine: it's a tool for
  choosing models, not part of volis. volis's no-internet rules don't apply to it.

---

## Terms

- **ASR:** speech recognition, turning speech into text. In volis: Whisper and Parakeet.
- **Translator:** the language model that turns text in one language into another. In volis:
  Qwen3 1.7B, as a Q4_K_M GGUF file.
- **Configuration:** one complete, runnable setup. The unit everything is tested and reported
  by. See "Configurations".
- **CER (character error rate):** the share of characters an ASR gets wrong, after both texts are
  cleaned the same way.
- **chrF:** a translation score comparing output with a professional reference translation,
  character by character, from 0 to 100.
- **Paired comparison:** two configurations run on the same sentences, compared sentence by
  sentence.
- **Bootstrap:** redrawing the test set thousands of times from its own sentences (some picked
  twice, some left out) and recomputing the result each time. The spread of the results shows
  how much a difference could be luck.
- **Confidence interval (95%):** the range the true difference falls in, in 95% of bootstrap
  redraws. If it includes zero, the difference isn't established.
- **Critical error:** a translation or transcription error that changes what the listener
  understands in a way that matters. See "Failures".
- **Pareto frontier:** the configurations that no other configuration beats on both quality and
  speed. Everything off the frontier is worse than something on it, in both respects at once.
- **Vault set:** the held-out test data, used only for final recommendations. See "Test data".
- **Judge model:** a large language model that sorts errors into categories. Its labels are
  checked against a human's before they're trusted.

---

## Configurations

A configuration is:

| Part | Example |
|---|---|
| Source-language ASR, with its settings | `whisper-large-v3-turbo` int8, language `fa` |
| Translator, file and compression | `qwen3-1.7b-q4_k_m.gguf` |
| Prompt | `volis-current` or a variant from `prompts/` |
| Translator settings | greedy decoding, thinking off (as volis) |
| Direction | `fa → en` |

For English → Iraqi and English → Persian, the ASR is the English one: volis's Parakeet is the
baseline.

Every configuration has an **ID**, a hash of all its parts, including exact model file
revisions and runtime versions. Every result is stored against that ID. Anyone can see exactly
what produced a number and run it again.

**The chain stops at translated text.** Text-to-speech is out of scope. Latency is reported up to
the finished translation, and the report says so.

### What runs, and how

Every number comes from **the same engines volis uses, run the way volis runs them**:

- **ASR:** sherpa-onnx **1.13.8** Python package (plus `sherpa-onnx-core` 1.13.8, see the
  converter's README for why), **on the CPU, int8**, with the settings `volis/src/asr.rs` uses.
  The converter already has this: `transcribe_like_cnverc` and `engine_worker.py`. Reuse them.
  Candidates that aren't ONNX yet are converted with `model-converter` (`convert.ps1` with a
  generated config) before testing.
- **Translator:** `llama-cpp-python` built from, or matching, the llama.cpp version volis links
  (`llama-cpp-sys-2` 0.1.156), **on the CPU**, Q4_K_M. volis's build has no GPU support
  (`Cargo.toml`), so neither does this.
- **Parity check:** before any results count, the app proves it matches volis. Its baseline ASR
  output must equal volis's on 20 clips, and its baseline translator output must equal
  `volis --translate` on 20 sentences, character for character. If `volis --translate` doesn't
  exist yet, stop and say that `volis-additions.md` has to be done first.

**ASR outputs are cached.** Each ASR configuration transcribes each clip once, and every
translator configuration reuses those transcripts.

---

## The candidate list

`candidates.yaml`, edited by the user. The app reads it and never changes it.

```yaml
asr:
  - id: whisper-turbo-volis
    source: volis:models/asr/whisper-large-v3-turbo      # volis's current model
    languages: [ar, fa, en]
    baseline: true
    why: What volis runs today.
  - id: example-persian-whisper
    source: hf:SomeOrg/whisper-large-v3-persian@<commit>  # always pin the commit
    languages: [fa]
    why: Fine-tuned on Persian Common Voice; reports low WER on it.
    risks: Common Voice may overlap our Persian test data.
    added_in_round: 1
    requested_by: ""                                      # a colleague's name, if one asked

translators:
  - id: qwen3-1.7b-volis
    source: volis:models/mt/qwen3-1.7b-q4_k_m.gguf
    baseline: true
    why: What volis runs today.

excluded:                                                 # considered and left out, with why
  - id: SomeOrg/some-model
    why: No GGUF, and its architecture doesn't load in volis's llama.cpp version.
```

The app checks every entry: the source exists, the commit is pinned, the languages are right,
and the model loads in volis's engine. It stops on any failure, with the reason.

**The `excluded` list is part of the proof.** It goes into the report, because "did you try X?"
is so often answered with "yes, and here's why it's not in".

## Prompts

`prompts/` holds one file per prompt variant. Each has the system prompt text, with
`{source_name}` and `{target_name}` where volis puts the language names, plus a note on what it
changes and why.

- `volis-current` is taken from `volis --print-prompt` for every language pair, never retyped.
- A prompt goes inside each translator's own chat format, read from the GGUF's metadata. Qwen3
  also gets the empty `<think></think>` block, as in volis.
- The report marks any winning configuration whose translator isn't Qwen, or whose prompt isn't
  volis's current one, as **needs a volis change**, and describes the change.

### The prompt lab

Improving prompts by hand is the tedious loop this app takes over. For the top translators
(setting: 3 per direction), the app can run an **improvement cycle** on the **development set
only**:

1. Run the configuration. Sort its failures into the categories under "Failures".
2. The **assistant model** reads the worst failures and the current prompt, and proposes **one**
   change aimed at the largest category. For example: *"In transcribed speech, '¿no?' at the end
   of a clause means 'right?'. Never translate it as a negation."*
3. Test the changed prompt. Keep it only if it reduces that category **without increasing
   critical errors in any other category**, and adds no more latency than the limit (setting).
4. Repeat until the budget runs out: a number of rounds, or no improvement three times in a row.

Every step goes in `rounds/<n>/prompt-lab.md`: the prompt before, the change, why it was
proposed, and what it did to each category. The user can reject any change, and the report
shows how the winning prompt got its shape.

**Prompt cost.** volis processes the whole prompt again for every sentence, unless it reuses the
fixed part between sentences. Check `translate.rs` and record which it does. Every prompt's
added latency is measured and reported, because a long prompt that's slightly better can be
worse for a conversation.

**The assistant model** proposes prompt changes and sorts errors as the judge. It's set in
`machine.yaml`: either a local GGUF model on the 5090, or Claude through the API. With the API,
test sentences leave the machine. The report records which was used.

---

## Test data

Two languages, with standard Arabic (MSA) measured **for comparison only**, to show how much
worse each configuration does on Iraqi than on formal Arabic.

| Test | Audio | Reference text | Directions it covers |
|---|---|---|---|
| Persian speech | FLEURS `fa_ir` | FLEURS transcripts; FLORES+ `eng_Latn` for the English | ASR `fa`; end to end `fa → en` |
| English speech | FLEURS `en_us` | FLORES+ `pes_Arab`, `acm_Arab`, `arb_Arab` | End to end `en → fa`, `en → ar-IQ`, `en → ar` |
| MSA speech | FLEURS `ar_eg` | FLEURS transcripts; FLORES+ `eng_Latn` | ASR `ar`; end to end `ar → en` (comparison) |
| Iraqi text | — | FLORES+ `acm_Arab` ↔ `eng_Latn` | Translation only, `ar-IQ ↔ en` |
| Iraqi speech, proxy | `xtz999/iraqi_arabic_speech_youssef` | its transcripts | ASR `ar-IQ` only, **provisional** |
| Iraqi speech, real | `testsets/iraqi-user/` | the user's transcripts and English | ASR `ar-IQ`; end to end `ar-IQ → en` |
| Real use | `testsets/volis-recorded/` | the user's transcripts and translations | End to end, all directions recorded |

**FLEURS and FLORES+ line up.** FLEURS recorded speech of FLORES sentences, so a FLEURS clip in
Persian and a FLORES+ sentence in English can be the same sentence. That's what makes end-to-end
testing with real references possible. Match them by sentence ID, and verify the match by
comparing the FLEURS English transcript with the FLORES+ English text. Report how many matched,
and drop those that don't.

**Gated and scripted datasets.** FLORES+ requires accepting its terms on Hugging Face and
logging in (`uv run huggingface-cli login`). If a download is refused, stop and tell the user.
FLEURS is published as a loading script, so use its automatic Parquet copy
(`refs/convert/parquet`).

**The Iraqi proxy.** `xtz999/iraqi_arabic_speech_youssef` is the same 3,870 rows as
`hnaalbhadly6/iraqi_arabic_speech_youssef`. It has one voice, every word marked with vowel
signs, and Gulf and Levantine words in sentences labelled Iraqi, which looks like
machine-written text read by a synthetic voice. It tests how well an ASR hears that one voice,
not real Iraqi speakers. Every score from it is labelled **provisional — synthetic proxy**. It has
no English translations, so Iraqi end-to-end testing waits for real clips.

**Real Iraqi clips**, when the user has them: `testsets/iraqi-user/speech.csv` (`clip, speaker,
iraqi_text, english_text`) plus `clips/*.wav`. Once it has at least 50 clips, it becomes the main
Iraqi test, and the report keeps the proxy results beside it and says whether the rankings
agree.

**Real use.** `testsets/volis-recorded/`, in the same format, holds clips the user recorded
*through volis on the laptop mic* (`volis --listen --wav`). It's small, but it's the only test
that sounds like real use. The report compares its ranking with the benchmark's. If they
disagree, the report says the benchmark may be measuring the wrong thing.

### Splits: development, selection, vault

Every sentence ID is assigned once, for good, to one of three splits, with a fixed seed:

- **Development (40%):** the prompt lab may use it as often as it likes.
- **Selection (30%):** used to rank configurations and pick finalists.
- **Vault (30%):** used **only** in a **final run**, on at most 3 configurations per slot, when the
  user asks for a recommendation to take to stakeholders.

The split is by **sentence ID across all languages at once**. Because FLEURS and FLORES line up,
a sentence in the development set in Persian must not show up in the vault in English.

The app counts how many times the vault has been used, and the report states it. Each use makes
it a little less clean, because decisions start to steer by it. When new real clips arrive,
they become a fresh vault.

### Contamination

For every candidate, search its model card, tags and listed training datasets for each test
set's name: FLEURS, FLORES, Common Voice, the youssef dataset. If found, that candidate's score on
that test is shown as **may have trained on this test**, and left out of that test's ranking,
while the number is still shown.

---

## Scoring

### Text cleaning

One function per language, used by every score:

- **Arabic:** remove diacritics and tatweel; unify alef forms (أ إ آ → ا); ة → ه; ى → ي; remove
  punctuation; collapse spaces.
- **Persian:** all of the Arabic rules, plus Arabic ي → Persian ی and Arabic ك → Persian ک;
  treat the zero-width non-joiner (the "half-space" inside Persian words) as a space; Persian and
  Arabic-Indic digits → 0–9.
- **English:** lowercase, remove punctuation, collapse spaces.

### Scores per configuration

- **ASR:** CER. Also the empty-output rate and the repetition rate (the same phrase repeated,
  a common Whisper failure).
- **Translation and end to end:** chrF against the reference.
- **Dialect score, into Iraqi only:** in each output, count Iraqi-only words (هسه, شنو, كلش,
  هواي…) and formal-only words (الآن, ماذا, جدا…) from `dialect-words.yaml`, and report the share
  of outputs that lean Iraqi. chrF says how close the words are; this says whether it sounds
  Iraqi.
- **Latency:** ASR time and translation time per sentence, **median and 90th percentile** (the
  time 9 sentences in 10 beat). The slow sentences are what a conversation feels.
- **Memory:** peak memory of each model, and whether ASR + translator fit the laptop's RAM
  (`machine.yaml`), leaving room for volis's voice model.

**Laptop speed.** volis runs on the laptop's CPU. Measure on the desktop's CPU, and scale by a
factor set in `machine.yaml`. Better: an optional **laptop run** copies the finalists to the
laptop and measures there. The app runs on either machine. A translator over 3 seconds (90th
percentile, setting) for a 15-word sentence on the laptop is marked **too slow for
conversation**.

### Failures

Each output is checked in two ways.

**Automatic checks**, exact and cheap:
- empty output; output in the wrong language or script;
- output far longer than the input;
- the output echoes the source, or recites the prompt (volis's own refusal guards,
  `translate.rs`);
- **numbers** in the source missing or changed in the output.

**Judged categories**, by the assistant model:

| Category | Severity |
|---|---|
| Meaning reversed (e.g. a negation added or lost) | critical |
| Wrong person: who did what to whom | critical |
| Invented content: something said that wasn't in the source | critical |
| Dangerous mistranslation: health, medication, numbers, names, places | critical |
| Answered the text instead of translating it | critical |
| Filler or spoken habit treated as a word ("e" as a name) | minor |
| Stiff or unnatural, but correct | minor |
| Formal where dialect was asked for | minor |

The **critical error rate**, per configuration, is reported separately and comes first. **It
decides.** A configuration with a clearly lower critical error rate beats one with a higher chrF.
chrF only separates configurations whose critical error rates are statistically tied.

**The judge must earn trust.** A fluent speaker labels a sample (see "Human review"), and the
report shows how often the judge agrees with the human. Measure it as percentage agreement plus
Cohen's kappa, which corrects for agreement that would happen by chance. If agreement on
critical errors is below 80% (setting), the judged categories are shown as **unconfirmed**, and
only the automatic checks and human labels count.

### Statistics

- **Every comparison is paired**, against the baseline and between finalists, on the same
  sentences.
- **Paired bootstrap**, 10,000 redraws: the 95% confidence interval of the difference in chrF,
  CER and critical error rate. If an interval includes zero, the report says **no established
  difference**, never "slightly better".
- **Win rate:** the share of sentences where A beats B, ties excluded.
- **Many configurations, few winners.** Picking the best of many configurations favours whichever
  got lucky. So the claim in the report comes only from the **vault** run of the finalists, and
  the report states how many configurations were tried to find them.

### Human review

Per round, the app writes review packets for the top configurations: 30 outputs each per
direction, with source, reference and output side by side. A fluent speaker rates each one as
**acceptable**, **minor issue** or **critical error**, and picks a category for critical errors. Ratings
are entered in the window's Review tab, or in the CSV.

The report uses them three ways:
- the human acceptance rate per configuration, with its confidence interval;
- **metric agreement:** does the chrF ranking match the human ranking? If not, the report says
  so plainly, and the human ranking wins;
- judge agreement, above.

For ASR, the packet has 10 clips per top configuration: the audio and every configuration's
transcript side by side, to listen to.

---

## Rounds, resuming and reuse

`rounds/<n>/` holds:
- a snapshot of `candidates.yaml`, `prompts/` and `settings.yaml` as they were that round;
- `changelog.md`: what changed from the previous round and why, in plain words, with who asked,
  if someone did. **The app writes a draft from the file differences, and the user edits it.**
- the report and discussion bundle for that round.

**Reuse.** A result is keyed by configuration ID + test split + data version + runtime versions.
If none of those changed, the result is reused, never rerun. Adding one model to a round runs
only that model's configurations.

**The work queue.** Work is a queue of small jobs in `state/bench.db` (SQLite). Kinds of job:
prepare a dataset, convert a model, transcribe a batch, translate a batch, judge a batch,
compute statistics, write a report. Each job's result is written in the same transaction as its
status.

- **Resume:** on start, any job left `running` goes back to `pending`. Done jobs are never rerun.
- **Pause:** finishes the current job, then stops. **Stop now:** stops at once, and only the
  running job is lost.
- **Each job runs in its own process,** so a crash inside one model marks that job `failed` with
  its error, instead of taking the app down. A failed job is retried once, then left for the
  user.
- **Disk:** downloads go in `cache/` in the app folder. Check free space before each download,
  and pause with a clear message if it runs low.

---

## The report

Two outputs per round, for two audiences.

### `report.html`, for colleagues and stakeholders

One self-contained page that needs no internet to view. It's written as a **decision memo**:

1. **Recommendation, first.** Per language and role, one sentence: which configuration volis
   should use, and a confidence level: **high**, **moderate** or **low**, by these rules:
   - **High:** measured on the vault; its interval versus the baseline excludes zero; its
     critical error rate is no worse; human review agrees; no contamination; no proxy data.
   - **Moderate:** the same, but measured on the selection set only, or with a human sample
     under 30.
   - **Low:** anything resting on the Iraqi proxy, the development set, or unconfirmed judge
     labels.

   Then: what it would take to use it (none, or a volis change, described), and **what would
   change this call**, for example "real Iraqi clips ranking a different ASR first".
2. **What we tested.** The candidates with the reason for each, the excluded models with the
   reason, the prompts, and how many configurations were tried.
3. **The evidence**, one chart per question a colleague would ask:
   - **Quality against speed:** a scatter plot, one dot per configuration, with confidence
     intervals as bars and the Pareto frontier drawn. The laptop's speed limit is a vertical
     line, and the baseline is marked.
   - **Better than today?** Each finalist's difference from the baseline, with its interval. Bars
     that cross zero are shown as "no established difference".
   - **How it fails:** critical and minor errors by category, per finalist.
   - **Do the scores agree with people?** Human acceptance next to chrF, per finalist.
   - **Does the test match real use?** Benchmark ranking against the volis-recorded ranking, when
     that data exists.
   - **Iraqi, formal Arabic and dialect:** the drop from MSA to Iraqi per finalist, and the
     dialect score.
4. **Examples.** For each finalist: three typical outputs, three of its worst, and every critical
   error of a dangerous kind (health, numbers, names). A colleague should see real text, not
   just numbers.
5. **Limitations**, in plain words: the Iraqi proxy, contamination flags, how many times the
   vault has been used, the judge's agreement with humans, what isn't tested (text-to-speech,
   noisy rooms, overlapping speech).
6. **History.** Every round's changelog, so "did you try X?" can be answered by pointing at a
   round.
7. **Reproducibility.** Every model with its pinned revision, every runtime version, every
   setting, and the command that reruns the round.

Charts are drawn as plain SVG inside the page, readable in light and dark themes, with the
baseline always in the same colour and every chart labelled in words, not only by colour.

### `bundle/`, for the user and Claude to discuss

Compact, and meant to be attached to a chat:
- `summary.md`: every table from the report, as text;
- `scores.csv`: one row per configuration × sentence, with every score, the source, the reference
  and the output;
- `failures.csv`: every critical and minor error with its category and text;
- `configs.json`: every configuration ID and what it's made of;
- `changelog.md` for this round.

Keep it under 10 MB, so it can be uploaded. If it's larger, trim `scores.csv` to the finalists and
say so in `summary.md`.

---

## The window

A PySide6 window, the same toolkit planned for volis-py. It's the main way to use the app.

**Top bar:** **Start**, **Pause** and **Retry failed** buttons; the round number; a status in
plain words (*Running*, *Pausing — finishing the current job*, *Paused*, *Waiting for you*); what's
running now; done, left and failed counts; and a time estimate.

**Tabs:**
1. **Round:** the candidates, prompts and excluded list for this round, read from the files, with
   any validation errors. An **Open in editor** button opens each file. **New round** snapshots
   the files, drafts the changelog, and starts a new round.
2. **Results:** per language and role, a sortable table of configurations: scores with
   intervals, critical error rate, latency, memory, fits laptop, and warnings. The baseline is
   highlighted. Screening numbers and vault numbers are in separate columns.
3. **Failures:** browse errors by configuration and category, with the text side by side.
4. **Prompt lab:** each improvement cycle's steps, with **Reject** on any change.
5. **Review:** the human rating packets, with **Play** for audio.
6. **Log.**

Buttons for **Final run** (uses the vault, and asks for confirmation, showing how many times it's
already been used), **Report** (writes and opens the report), and **Bundle** (opens the bundle
folder).

**Behaviour:**
- The window never freezes. It only reads `state/bench.db`, and keeps no state of its own.
- Closing while jobs run asks: *pause after the current job*, *stop now*, or *cancel*.
- One runner at a time, held by a lock file. If the queue is running from the command line, the
  window opens as a viewer with a working Pause.
- **Arabic and Persian display right to left** in every table and review field, including text
  that mixes in English words and numbers. Test with real sentences.
- The window's logic is plain Python without Qt, unit-tested, as with volis's `gui::Session`. Qt
  only draws it.

## Commands

```powershell
.\bench.ps1                     # open the window
.\bench.ps1 start --no-window   # run the queue without the window
.\bench.ps1 pause
.\bench.ps1 status
.\bench.ps1 final               # the vault run, after confirmation
.\bench.ps1 report
.\bench.ps1 new-round
```

## Layout

```
model-bench/
  bench.ps1  setup.ps1  pyproject.toml  uv.lock
  machine.example.yaml   copy to machine.yaml: volis and model-converter paths, laptop RAM and
                         speed factor, assistant model
  settings.yaml          limits, sizes, budgets, thresholds
  candidates.yaml        the models, chosen by the user
  prompts/               the prompt variants
  dialect-words.yaml     Iraqi-only and formal-only words
  bench/                 the code
  bench/gui/             the window (drawing only)
  testsets/              iraqi-user/ and volis-recorded/ (not committed: voices)
  rounds/<n>/            snapshots, changelog, report, bundle
  state/bench.db         the queue and every result (not committed)
  cache/                 downloads and converted models (not committed)
```

The Python environment uses uv with everything inside the folder, like `model-converter`. The
converter is called as its own process (`convert.ps1`), so its carefully checked DLL setup never
mixes with this app's.

---

## Milestones

**B1 — setup, the queue, and the window's frame.** `setup.ps1`, `machine.yaml`, the SQLite queue,
top bar, Log tab, pause, resume, closing behaviour and viewer mode, running dummy jobs.
Check: kill the process mid-job and start again. Done jobs aren't rerun, and the killed job runs
again. Pause finishes the current job. The window stays responsive while a dummy job runs for a
minute.

**B2 — candidates, prompts, rounds and test data.** Reading and validating `candidates.yaml` and
`prompts/`, rounds and changelog drafts, the Round tab. Downloading and preparing every test set,
matching FLEURS to FLORES+, the three-way split by sentence ID, the cleaning functions, and the
contamination check.
Check: counts per test set and split, and how many FLEURS clips matched FLORES+. The Persian
cleaning tests cover ي/ی, ك/ک, the half-space and digits. No sentence ID appears in two splits.

**B3 — parity with volis.** The ASR and translator runners, conversion through `model-converter`,
and the parity check against volis.
Check: baseline ASR and translator outputs match volis's exactly, on 20 clips and 20 sentences.
**Stop here if they don't.** Nothing after this means anything without it.

**B4 — end-to-end runs.** Configurations, ASR caching, the chain, latency and memory, the Results
tab. First with baselines only.
Check: a round with only the baselines runs end to end in every direction the data covers, and
Results shows the numbers.

**B5 — scores and statistics.** CER, chrF, the dialect score, automatic failure checks, paired
bootstrap, intervals and win rates.
Check: a unit test where two configurations differ only by chance gives "no established
difference", and one with a planted real difference is detected.

**B6 — the judge, failures and human review.** Judged categories, the Failures and Review tabs, and
judge-to-human agreement.
Check: the user rates a packet, and agreement and human acceptance appear in Results.

**B7 — the prompt lab.** Prompt variants, the improvement cycle on the development set, its log,
and the Prompt lab tab.
Check: one cycle runs, logs every step, and a rejected change is removed.

**B8 — the report, bundle and vault run.** `report.html` with every section and chart, the bundle,
the final run and its counter.
Check: the user opens the report and can explain the recommendation to someone else without
asking. The bundle uploads to a chat.

**B9 — optional: the laptop run.** Measure the finalists' speed and memory on the laptop itself.
