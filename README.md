# model-bench

model-bench tests **complete volis setups**, meaning a speech recognizer, a translator and a
prompt together, end to end, for Iraqi Arabic and Persian (Farsi). It produces a recommendation
that holds up when a colleague asks "is that difference real?".

The full plan is in [model-bench.md](model-bench.md). It's being built milestone by milestone;
**B1, the job queue and the window's frame, is done.** The testing itself comes in later milestones.

## Words used here

- **volis:** the offline speech translator this bench chooses models for.
- **Job:** one small piece of work, such as "transcribe these 50 clips". The bench keeps a list
  of jobs (the **queue**) and works through it one at a time.
- **Runner:** the background process that works through the queue. Only one runs at a time.
- **PowerShell:** the Windows program where you type commands (Start menu, type `PowerShell`).

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
