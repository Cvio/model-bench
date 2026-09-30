# model-bench

model-bench tests **complete volis setups**, meaning a speech recognizer, a translator and a
prompt together, end to end, for Iraqi Arabic and Persian (Farsi). It produces a recommendation
that holds up when a colleague asks "is that difference real?".

The full plan is in [model-bench.md](model-bench.md). It's being built milestone by milestone;
**B1 (the job queue and window), B2 (candidates, rounds and test data) and B3 (the parity check)
are done.** Scoring whole configurations comes in the next milestones.

## Words used here

- **volis:** the offline speech translator this bench chooses models for.
- **Job:** one small piece of work, such as "transcribe these 50 clips". The bench keeps a list
  of jobs (the **queue**) and works through it one at a time.
- **Runner:** the background process that works through the queue. Only one runs at a time.
- **PowerShell:** the Windows program where you type commands (Start menu, type `PowerShell`).
- **Candidate:** a model being tested. `candidates.yaml` lists them; it starts with only what volis
  runs today (the **baseline**), and you add the rest.
- **Round:** one pass of testing. Each round keeps a copy of the files as they were and a
  **changelog** saying what changed and why, so "did you try X?" can be answered later.
- **FLEURS and FLORES+:** public test data. FLORES+ is the same 2,009 sentences professionally
  translated into 200+ languages; FLEURS is people reading those sentences aloud. Together they
  give real speech with real reference translations.
- **Split:** each sentence is put, once and for good, in one of three piles: **development**
  (for trying things), **selection** (for ranking) and **vault** (kept back for the final
  recommendation, so the final numbers aren't ones the choices were tuned on).

## Set up (once per computer)

1. **Install uv** (it installs Python and everything the bench needs, inside this folder only):

   ```powershell
   winget install astral-sh.uv
   ```

   Close PowerShell and open a new one afterwards.

2. **Set up the bench,** from this folder:

   ```powershell
   .\setup.ps1
   ```

   **Expect** it to end with `OK. model-bench is set up.` It takes a few minutes the first time.
   If PowerShell refuses to run it, use `powershell -ExecutionPolicy Bypass -File .\setup.ps1`.

3. **Tell it about this computer.** Copy `machine.example.yaml` to `machine.yaml` and open it in
   Notepad. Set `volis_path` to the folder with `volis.exe` in it, and `converter_path` to the
   model-converter folder. Each setting in the file says what it's for.

## Choose what to test

1. **Candidates:** open `candidates.yaml` in Notepad (or the window's **Round** tab, **Open
   candidates.yaml**). Each model has an `id`, a `source` (a model volis already has, or one on
   Hugging Face pinned to an exact version), the languages to test it on, and **why** it's in.
   Models you considered and left out go under `excluded`, with the reason: the report shows them.
2. **Prompts:** each file in `prompts\` is one way of instructing the translator. `volis-current`
   is volis's own, taken from volis itself.
3. **Check them:**

   ```powershell
   .\bench.ps1 validate
   ```

   **Expect** `OK: candidates.yaml, prompts/ and settings.yaml are sound.` Otherwise it lists every
   problem in plain words (a typo in a source, a model that isn't pinned, a missing reason).
4. **Start a round** when the list changes: **New round** in the Round tab, or
   `.\bench.ps1 new-round`. It saves a copy of the files and drafts `rounds\<n>\changelog.md` from
   what changed. Open it and write why, in your words, and who asked if a colleague did.

## Get the test data (once)

```powershell
.\bench.ps1 prepare
.\bench.ps1 start --no-window
```

The first command lists the jobs (downloading FLEURS and FLORES+, the Iraqi test recordings, and
checking each candidate's model card); the second runs them. It downloads about 3 GB and takes a
while. FLORES+ is only shared with logged-in users who accepted its terms: if it stops saying so,
accept them at <https://huggingface.co/datasets/openlanguagedata/flores_plus> and run
`uv run hf auth login`. Then see what you have:

```powershell
.\bench.ps1 data
```

**Expect** a table of recordings per test set and split, how many FLEURS recordings were matched
to their FLORES+ sentence (each match is checked by its English and its own language; any that
don't match are left out), and for each candidate whether its model card says it trained on a
test set. "No mention" means the card doesn't say; it doesn't prove the model never saw the data.

**Your own recordings,** when you have them, go in `testsets\iraqi-user\` (Iraqi speakers) or
`testsets\volis-recorded\` (recorded through volis): a `speech.csv` with the columns `clip`,
`speaker`, `iraqi_text` and `english_text`, and the recordings in a `clips\` folder. Run
`.\bench.ps1 prepare` again to add them.

## Prove the bench matches volis (once per volis version)

Every number the bench reports is only worth anything if it runs the models exactly the way volis
does. So before anything else counts, the bench proves it: it runs volis's own speech recognizers
on 20 recordings, and volis's translator on 20 sentences in three directions, both through its own
machinery and through volis itself, and checks every result is **identical, letter for letter**.
This is the **parity check**.

**What you need first:**
- **volis with the bench commands** (`--print-prompt`, `--translate`, `--transcribe`): the
  `model-bench-work` branch, built. `machine.yaml`'s `volis_path` points at its `target\release`
  folder.
- **model-converter set up** (its `setup.ps1`), with `converter_path` in `machine.yaml`. The bench
  borrows its speech engine, which is set up exactly like volis's.
- **The translator's engine,** built the same way volis builds it (the same llama.cpp version and
  the same processor settings). Once:

  ```powershell
  .\bench.ps1 build-server
  ```

  **Expect** `OK. llama-server is built` after a few minutes. It needs the Visual Studio Build
  Tools, the same ones that build volis.

**Then run the check:**

```powershell
.\bench.ps1 parity
.\bench.ps1 start --no-window
.\bench.ps1 parity-report
```

**Expect** `Parity with volis: PASSED`, with every line reading 20 of 20 identical. It takes a
few minutes. If anything differs, the report shows the bench's output and volis's side by side,
and nothing the bench measures counts until that's fixed.

Run it again whenever volis or its models change: the bench notices a new volis version and asks
for a fresh check.

## Use it

```powershell
.\bench.ps1
```

opens the window. **Start** begins working through the queue; **Pause** lets the current job
finish, then stops; **Retry failed** gives failed jobs another go. The top bar says what's
happening in plain words, and the **Log** tab lists everything that happened.

**It's safe to close, or to lose power.** Closing the window while jobs run asks whether to
pause after the current job or stop now. If the computer crashes or the bench is killed, the
next Start picks up where it left off: finished jobs are never redone, and the interrupted one
runs again.

The same things from the command line:

| Command | What it does |
|---|---|
| `.\bench.ps1 start --no-window` | Work through the queue without the window |
| `.\bench.ps1 pause` | Finish the current job, then stop |
| `.\bench.ps1 stop` | Stop at once; the running job will run again next time |
| `.\bench.ps1 status` | What's running, how much is left, the latest log lines |
| `.\bench.ps1 retry-failed` | Put failed jobs back in the queue |

If the queue is already running (say from the command line), the window opens as a **viewer**: it
shows everything and Pause works, but Start waits until that run ends.

## Measure the baseline (how well volis does today)

**What this does:** it runs volis's current models on the test data in every direction the bench
cares about (Persian ↔ English, English → Iraqi Arabic, plus a few comparisons), and scores the
results. Later rounds are compared against these numbers, so this is the starting line.

```powershell
.\bench.ps1 run
.\bench.ps1 start --no-window
.\bench.ps1 results
```

`run` puts the work in the queue (it refuses until the parity check has passed). `start` does the
work; **expect** a few hours on a laptop, and it's fine to pause and carry on later. `results`
prints the table. The window's **Results** tab shows the same table.

**Reading the table** (each word, briefly):
- **CER** (character error rate): of every 100 letters the speech recognizer wrote, how many were
  wrong. **Lower is better.**
- **chrF**: how closely the translation matches a human one, from 0 to 100. **Higher is better.**
- **refused**: how often the translator gave no usable answer (volis's guards caught it).
- **median s / p90 s**: seconds from the end of speech to the finished translation; half the
  sentences are faster than the median, 9 in 10 faster than p90.
- **memory / fits**: the most memory the models used, and whether that plus room for the voice and
  Windows fits the laptop.
- **comparison**: rows kept only to compare with (standard Arabic, not the dialect).
- **PROVISIONAL**: the Iraqi Arabic speech test uses computer-made recordings, so treat it as a
  rough guide only.

### How sure are these numbers?

Each score comes with a **95% range** (for example chrF `44.7 [42.9–46.4]`). **What it means:** the
test uses a few hundred sentences, and a different few hundred would give a slightly different
number. The bench works out how much by **re-drawing** the sentences 10,000 times (some picked
twice, some left out) and scoring each draw. The true score almost certainly sits inside the range.

More columns:
- **failed**: outputs that fail a simple automatic check: refused, empty, in the wrong alphabet,
  far too long, or a number from the source lost or changed (7th becoming 10th). Lower is better.
- **Iraqi**: for output into Iraqi Arabic, the share that *sounds* Iraqi: more Iraqi-only words
  (هسه, شنو, كلش…) than formal ones (الآن, ماذا, جدا…), from `dialect-words.yaml`. Add words
  there freely; more words make it steadier.

**Comparing with today's setup.** Every new configuration is compared with the baseline **on the
same sentences** ("vs baseline" in the window, and the list under the table from
`.ench.ps1 results`). You get the difference with its range, and the **win rate**: of the
sentences where the two differ, how often the new one did better.

**If the range includes zero, the bench says "no established difference".** That means the
gap could just be luck, so don't call it better, even "slightly". Only a range entirely above (or
below) zero counts.

## The judge, and your ratings

Scores like chrF can't tell a harmless wording change from a translation that says the opposite
of the source. Two things fill that gap.

**The judge** is a larger AI model (the **assistant model**) that reads each translation beside
its source and a professional reference, and names the worst problem, if there is one:

- **Critical:** meaning reversed, wrong person (who did what to whom), invented content,
  dangerous mistranslation (health, medication, numbers, names, places), answered the text
  instead of translating it.
- **Minor:** a filler word treated as a real word, stiff but correct, formal where the dialect
  was asked for.

```powershell
.\bench.ps1 judge
.\bench.ps1 start --no-window
```

**Expect** about 10 seconds per output on the laptop. It judges a fixed sample of 100 outputs per
configuration (`judge: items_per_config` in `settings.yaml`), the same sentences for each
configuration, so comparisons stay fair. That's roughly 2 hours for the baseline.

**Your ratings** check the judge. A judge is only useful if it agrees with a person who knows the
language, so:

1. Open the window (`.\bench.ps1`), go to the **Review** tab, and press **Load packets**. A
   **packet** is 30 outputs from one configuration in one direction (10 clips for speech
   recognition).
2. For each output, read the source (and the reference, for help) and press **1** acceptable,
   **2** minor issue, or **3** critical error. For a critical error, pick what kind from the list
   first. It moves on to the next unrated output by itself. Rate the packets in languages you
   can read; skip the rest.
3. **Results** then shows **you accepted** (the share you rated acceptable, with its range), and
   under the table how often the judge agreed with you on critical errors.

If you'd rather use a spreadsheet: `.\bench.ps1 review-packets` writes each packet as a CSV in
the round's `review` folder. Fill the `rating` column (`acceptable`, `minor` or `critical`), then
run `.\bench.ps1 review-import <file>`.

**When the judge doesn't agree with you** on critical errors at least 80% of the time
(`judge: min_critical_agreement`), its numbers are marked **unconfirmed** (a `?` on the command
line), and only the automatic checks and your ratings count. If chrF ranks two configurations
differently from your ratings, Results says so, and your ratings win.

The **Failures** tab lists the outputs that failed, per configuration: pick a check (for example
*numbers*) or *judged critical* to see them side by side with the source and reference.

### Change the judge

**What:** the judge is whatever model `machine.yaml` names. For now it's **Qwen3-8B**, the
model already on this laptop (model-converter's teacher). It's small, so it's weak at Persian and
Iraqi Arabic, and its labels may well come out *unconfirmed*.

**How to use a stronger one** (for example on the desktop with the big graphics card):

1. Download a larger instruction model as a `.gguf` file (a Qwen3 of 14B or more handles Persian
   and Arabic better).
2. In `machine.yaml`, set `assistant_gguf:` to that file's full path.
3. Run `.\bench.ps1 judge` and **Start** again.

**What to expect:** each judge keeps its own labels, so nothing is overwritten. Results use the
judge named in `machine.yaml`. Your ratings stay, and the new judge's agreement with them is
worked out automatically. It only runs on the processor for now (the same engine volis uses), so a
bigger model is slower; `items_per_config` can be lowered to save time.
