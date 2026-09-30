"""The two runners: speech recognition and translation, each run the way volis
runs it (model-bench.md, "What runs, and how").

- ASR: the converter's engine worker (sherpa-onnx 1.13.8 + sherpa-onnx-core,
  CPU, the settings volis's asr.rs uses), in the converter's own environment,
  as its own process, so the converter's checked DLL setup never mixes with
  this app's. Whisper, and NeMo transducers (Parakeet).
- Translator: llama-server built from llama.cpp e79e4bf660e1, the commit
  volis's llama-cpp-2 0.1.156 builds, with the same CPU settings (native off:
  AVX, AVX2, FMA, F16C, BMI2, SSE4.2; OpenMP off), CPU only. volis's context
  size, threads and greedy decoding; a fresh context per sentence (no prompt
  cache), as volis creates one per sentence. The raw output then goes through
  volis's clean-up and refusal guards (bench/volis_rules.py).

The prompt is volis's own, from `volis --print-prompt`, never retyped.
"""

import json
import socket
import subprocess
import sys
import time
import tomllib
from pathlib import Path

from bench import config, volis_rules
from bench.config import ROOT

LLAMA_CPP_COMMIT = "e79e4bf660e19f2ad851e06c6913f7a8c5852621"
LLAMA_SERVER = ROOT / "cache" / "llama.cpp" / "build-volis" / "bin" / "Release" / "llama-server.exe"
# volis's src/translate.rs
CONTEXT_TOKENS = 1024
MAX_OUTPUT_TOKENS = 256
THREADS = 6
# How llama-server runs. Part of the parity fingerprint: change any of these
# and parity must be checked again. --reasoning-format none and --no-jinja keep
# the server from interpreting the output (a <think> block made it refuse a
# request); volis takes the model's raw text and cleans it itself.
SERVER_ARGS = ["--ctx-size", str(CONTEXT_TOKENS), "--threads", str(THREADS), "--threads-batch", str(THREADS),
               "--parallel", "1", "--no-warmup", "--reasoning-format", "none", "--no-jinja"]


class RunnerError(Exception):
    pass


class PeakMemory:
    """Samples a process's resident memory in the background; .peak_mb is the
    highest seen. Each model runs in a process of its own, so this is that
    model's footprint."""

    def __init__(self, pid: int, every: float = 0.2):
        import threading

        self.pid, self.every, self.peak = pid, every, 0
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.watch, daemon=True)
        self.thread.start()

    def watch(self):
        import psutil

        try:
            process = psutil.Process(self.pid)
            while not self.stop.is_set():
                self.peak = max(self.peak, process.memory_info().rss)
                self.stop.wait(self.every)
        except psutil.Error:
            pass

    @property
    def peak_mb(self) -> float:
        return self.peak / 1e6

    def finish(self) -> float:
        self.stop.set()
        self.thread.join(timeout=2)
        return self.peak_mb


def volis_exe() -> Path:
    exe = config.volis_root() / "volis.exe"
    if not exe.is_file():
        raise RunnerError(f"volis isn't at {exe} (volis_path in machine.yaml)")
    return exe


def resolve(source: str) -> Path:
    """A candidate's source as a path on this machine."""
    parsed = config.parse_source(source)
    if parsed and parsed[0] == "volis":
        return config.volis_root() / parsed[1]
    raise RunnerError(f"{source}: only volis: sources can be run yet (Hugging Face models are "
                      "converted by model-converter first; that comes with the first such candidate)")


# --- Speech recognition -------------------------------------------------------------


def asr_files(folder: Path) -> dict:
    engine = tomllib.loads((folder / "engine.toml").read_text(encoding="utf-8"))
    files = {role: str(folder / name) for role, name in engine["files"].items()}
    return {"backend": engine["backend"], **files}


def converter_python() -> tuple:
    root = Path(config.machine().get("converter_path") or "")
    python = root / ".venv" / "Scripts" / "python.exe"
    worker = root / "whisper-to-onnx" / "steps" / "engine_worker.py"
    if not python.is_file() or not worker.is_file():
        raise RunnerError(f"model-converter isn't set up at {root} (converter_path in machine.yaml; "
                          "run its setup.ps1)")
    return python, worker


def transcribe(source: str, language: str, wavs: list, measure: bool = False):
    """One transcript per WAV, from the converter's engine worker, the way
    volis's asr.rs runs the recognizer. Whitespace is collapsed to one line per
    transcript, as `volis --transcribe` prints it. With measure, returns
    (texts, seconds per clip, peak memory in MB) instead."""
    import tempfile

    files = asr_files(resolve(source))
    python, worker = converter_python()
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
        f.write("\n".join(str(w) for w in wavs))
        listing = f.name
    command = [str(python), str(worker), "--expect-ort", "1.28.2", "--encoder", files["encoder"],
               "--decoder", files["decoder"], "--tokens", files["tokens"], "--wav-list", listing]
    if files["backend"] == "nemo_transducer":
        command += ["--joiner", files["joiner"]]
    else:
        # Whisper is told the language part only, as volis's asr.rs does.
        command += ["--language", language.split("-")[0]]
    try:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                   encoding="utf-8", errors="replace")
        memory = PeakMemory(process.pid)
        stdout, stderr = process.communicate()
        peak = memory.finish()
    finally:
        Path(listing).unlink(missing_ok=True)
    lines = [l for l in stdout.splitlines() if l.startswith("{")]
    result = json.loads(lines[-1]) if lines else None
    if process.returncode != 0 or not result or not result.get("ok"):
        why = result["error"] if result else stderr.strip()[-800:]
        raise RunnerError(f"the recognizer failed: {why}")
    texts = [" ".join(t.split()) for t in result["texts"]]
    if measure:
        return texts, result.get("seconds") or [None] * len(texts), peak
    return texts


def volis_transcribe(engine_folder: str, language: str, wavs: list) -> list:
    """What volis itself hears (volis --transcribe, M7.9), for the parity check."""
    done = subprocess.run([str(volis_exe()), "--transcribe", engine_folder, language, *map(str, wavs)],
                          capture_output=True)
    if done.returncode != 0:
        raise RunnerError(f"volis --transcribe failed: {done.stderr.decode('utf-8', 'replace').strip()[-800:]}")
    out = done.stdout.decode("utf-8").split("\n")
    return out[:len(wavs)]


# --- Translation ---------------------------------------------------------------------


def volis_prompt(source: str, target: str) -> str:
    """volis's exact prompt template for a pair of tags."""
    done = subprocess.run([str(volis_exe()), "--print-prompt", source, target], capture_output=True)
    if done.returncode != 0:
        raise RunnerError(f"volis --print-prompt {source} {target} failed: "
                          f"{done.stderr.decode('utf-8', 'replace').strip()[-500:]} "
                          "(it needs volis M7.8 or later: the model-bench-work branch)")
    return done.stdout.decode("utf-8")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Translator:
    """llama-server with one GGUF, CPU only, set up as volis's translator."""

    def __init__(self, gguf: Path, log_dir: Path, server_args: list = None):
        if not LLAMA_SERVER.is_file():
            raise RunnerError(f"llama-server isn't built at {LLAMA_SERVER}; run: .\\bench.ps1 build-server")
        self.gguf, self.port = Path(gguf), free_port()
        self.log_path = Path(log_dir) / f"llama-server-{self.gguf.stem}.log"
        self.process = None
        self.server_args = SERVER_ARGS if server_args is None else server_args

    def __enter__(self):
        import requests

        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        log = open(self.log_path, "w", encoding="utf-8", errors="replace")
        self.process = subprocess.Popen(
            [str(LLAMA_SERVER), "--model", str(self.gguf), "--host", "127.0.0.1", "--port", str(self.port),
             *self.server_args],
            stdout=log, stderr=subprocess.STDOUT)
        self.memory = PeakMemory(self.process.pid)
        deadline = time.time() + 300
        while time.time() < deadline:
            if self.process.poll() is not None:
                raise RunnerError(f"llama-server exited while loading; see {self.log_path}")
            try:
                if requests.get(f"http://127.0.0.1:{self.port}/health", timeout=2).status_code == 200:
                    return self
            except requests.RequestException:
                pass
            time.sleep(0.5)
        self.close()
        raise RunnerError(f"llama-server didn't finish loading in 5 minutes; see {self.log_path}")

    def raw(self, prompt: str, n_predict: int = MAX_OUTPUT_TOKENS) -> tuple:
        """(raw output, seconds): greedy, up to 256 tokens or end of generation,
        with a fresh context (no cached prompt), as volis decodes."""
        import requests

        started = time.time()
        r = requests.post(f"http://127.0.0.1:{self.port}/completion", json={
            "prompt": prompt, "n_predict": n_predict, "temperature": 0.0, "top_k": 1,
            "cache_prompt": False, "samplers": ["top_k"], "stream": False,
        }, timeout=600)
        if r.status_code != 200:
            raise RunnerError(f"llama-server refused a request ({r.status_code}): {r.text[:300]}")
        return r.json()["content"], time.time() - started

    def translate(self, text: str, template: str) -> dict:
        """volis's translation of one sentence: text, or '' with the refusal."""
        raw, seconds = self.raw(template.replace("{text}", text.strip()))
        final, refusal = volis_rules.judge(text, raw, template)
        return {"text": final, "refusal": refusal, "raw": raw, "seconds": seconds}

    def peak_mb(self) -> float:
        return self.memory.peak_mb if getattr(self, "memory", None) else 0.0

    def close(self):
        if getattr(self, "memory", None):
            self.memory.finish()
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                self.process.kill()

    def __exit__(self, *exc):
        self.close()
        return False


def volis_translate(source: str, target: str, lines: list) -> list:
    """volis's own translations (volis --translate, M7.8), for the parity check."""
    text = "\n".join(l.replace("\n", " ") for l in lines) + "\n"
    done = subprocess.run([str(volis_exe()), "--translate", source, target], input=text.encode("utf-8"),
                          capture_output=True)
    if done.returncode != 0:
        raise RunnerError(f"volis --translate failed: {done.stderr.decode('utf-8', 'replace').strip()[-800:]}")
    return done.stdout.decode("utf-8").split("\n")[:len(lines)]


if __name__ == "__main__":
    sys.exit(0)
