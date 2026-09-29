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
