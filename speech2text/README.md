# Speech2Text: install, set up, and transcribe

Turn an audio recording into timestamped transcripts on your computer. Audio stays local, and the original recording is preserved. Internet is needed only to install missing packages and download a model.

**Already installed? Start at [2. Check the setup](#2-check-the-setup).**

All commands below run from the **project folder containing `speech2text/`**, not from inside `speech2text/`. Put quotation marks around paths containing spaces.

1. [Install](#1-install-once)
2. [Check the setup](#2-check-the-setup)
3. [Transcribe and open the results](#3-transcribe-a-recording)
4. [Common tasks](#4-common-tasks)
5. [All transcription parameters](#5-transcribepy-complete-parameter-reference)
6. [Saved configuration](#6-save-your-preferred-settings)
7. [Model setup parameters](#7-setup-scripts-and-model-parameters)
8. [Troubleshooting and cleanup](#8-troubleshooting-and-cleanup)

## 1. Install once

These instructions target Ubuntu/Linux and the tested Python 3.12 environment.

The repository ships source files, pinned dependencies, default configuration and example hints only. Run setup on each new machine; virtual environments, downloaded models and caches are generated locally and excluded from Git. The defaults use relative paths, CPU processing and automatic language detection, with no personal hints or speaker names.

**Step 1 — Install system prerequisites if missing:**

```bash
sudo apt update
sudo apt install python3 python3-venv ffmpeg
```

FFmpeg provides both `ffmpeg` and `ffprobe`. Skip this step if the prerequisites are already installed.

**Step 2 — Install the Python packages and default speech model:**

```bash
bash speech2text/setup.sh
```

Wait for the command to finish successfully. It creates or updates `speech2text/.venv`, installs the pinned packages, downloads/verifies the default model, and runs a setup check. You can rerun it after an interrupted installation. Valid model files are reused; missing packages or files require internet.

The default model is **Whisper base**, executed by faster-whisper on the CPU. No account or API key is required. Allow approximately **1 GB** for the Python environment, default model and download cache; actual usage varies by platform. Transcription also needs output space: about **115 MB per hour per processed audio channel**, plus text and diagnostic files.

## 2. Check the setup

```bash
speech2text/.venv/bin/python speech2text/transcribe.py --preflight
```

Success prints a JSON report with software versions, supported compute types and model information. It does not transcribe anything or download a model. If it prints `Error:`, use the [troubleshooting table](#8-troubleshooting-and-cleanup).

**Optional activation:** the environment is configured for `speech2text/`. To activate it in your terminal:

```bash
source speech2text/.venv/bin/activate
python speech2text/transcribe.py --preflight
```

Activate again in each new terminal. Run `deactivate` to leave the environment. The rest of this guide uses the direct Python path so activation is optional.

## 3. Transcribe a recording

For an English recording:

```bash
speech2text/.venv/bin/python speech2text/transcribe.py "recording.m4a" --language en
```

Replace the quoted filename with your recording. M4A, MP3, WAV and FLAC are supported. Defaults are **careful mode**, **CPU**, and **int8** processing. Omitting `--language` enables automatic language detection. Transcription is always offline; you do not need to add `--offline`.

If the recording has multiple channels, the script asks you to choose how to handle them. Use [the channel examples below](#choose-how-to-handle-stereo-or-multichannel-audio).

Progress messages show preparation, model loading, transcription and review. When finished, the `Complete` message gives the output folder:

```text
transcription-output/<recording-name>-<settings-id>/
```

**Open `readable.md` first, then check `review.md`.**

| File | What it contains |
|---|---|
| `readable.md` | Timestamped transcript with simple paragraph and whitespace formatting. |
| `faithful.md` | Recognized wording, timestamps and uncertainty markers. |
| `review.md` | Flagged passages and any alternative recognition results to check by listening. |
| `transcript.txt` | Plain-text transcript. |
| `transcript.srt` | Timestamped subtitles. |
| `transcript.json` | Structured segments and word timestamps. |
| `review.json` | Review information in structured form. |
| `manifest.json` | Input identity, settings, software/model versions, status and timings. |
| `artifacts/` | Prepared audio and saved progress used for resume. |

Both Markdown versions retain recognized wording and fillers. Readable output does not rewrite what speakers said. Automatic recognition can be wrong even when no uncertainty is flagged. Review alternatives never automatically replace the first pass. Summaries are not generated.

## 4. Common tasks

### Choose speed or additional review

```bash
# Faster first pass; still reports uncertainties
speech2text/.venv/bin/python speech2text/transcribe.py "recording.m4a" --mode draft

# More thorough decoding and selective retries (the default)
speech2text/.venv/bin/python speech2text/transcribe.py "recording.m4a" --mode careful
```

Careful mode retries up to **8 flagged passages per job**, each using at most **30 seconds of audio** with default settings. It takes longer and does not guarantee correctness.

### Select a language or output location

```bash
# Bulgarian
speech2text/.venv/bin/python speech2text/transcribe.py "recording.m4a" --language bg

# Automatic language detection
speech2text/.venv/bin/python speech2text/transcribe.py "recording.m4a" --language auto

# Save results elsewhere
speech2text/.venv/bin/python speech2text/transcribe.py "recording.m4a" --output-dir "./my transcripts"
```

Use a known language when possible. Automatic detection runs separately for each chunk and can be unreliable on short passages.

### Resume an interrupted recording

Repeat your **original command with all the same options**, adding `--resume`:

```bash
speech2text/.venv/bin/python speech2text/transcribe.py "recording.m4a" --language en --resume
```

Completed chunks and review attempts are reused. If no matching job exists, a new one starts. Changing the audio, settings, hint contents, speaker mapping, model or relevant software/code can create a different job rather than resume the old one. Moving the toolkit can also change stored paths and job identity.

To start the same job again from scratch:

```bash
speech2text/.venv/bin/python speech2text/transcribe.py "recording.m4a" --language en --overwrite
```

The previous job is preserved in a `.backup-…` folder. Without either flag, the script refuses to replace an existing matching job. Do not combine `--resume` and `--overwrite`.

### Supply names and technical terms

Copy the supplied templates to local files, then replace the placeholders with information relevant to your recording:

```bash
cp speech2text/config/glossary.example.txt speech2text/config/glossary.txt
cp speech2text/config/context.example.txt speech2text/config/context.txt
```

- `speech2text/config/glossary.example.txt`: the names and terms relevant to your recording.
- `speech2text/config/context.example.txt`: a short description of the recording topic.

```bash
speech2text/.venv/bin/python speech2text/transcribe.py "recording.m4a" \
  --language en \
  --glossary speech2text/config/glossary.txt \
  --context speech2text/config/context.txt
```

The example files are templates, not built-in topic assumptions. Neither is loaded unless you explicitly select it. Either file can be used alone. Keep their combined text, including the separating newline, within **1,800 characters**. These are recognition hints, not instructions; the model may truncate hints or recognize a suggested term incorrectly.

### Choose how to handle stereo or multichannel audio

If voices are mixed together, or the channels contain the same conversation:

```bash
speech2text/.venv/bin/python speech2text/transcribe.py "stereo recording.wav" --mix-channels
```

If you know that each participant was recorded on a separate channel:

```bash
speech2text/.venv/bin/python speech2text/transcribe.py "separate channels.wav" --speakers channels
```

This labels the first channel `Speaker 1`, the second `Speaker 2`, and so on. It does **not** identify people by voice. Mono or mixed audio uses `Speaker unknown`; automatic voice diarization is not implemented. Channel bleed can produce duplicate or incorrectly attributed speech.

To show confirmed names or roles, save a UTF-8 JSON file, for example `speech2text/config/speakers.json`:

```json
{
  "Speaker 1": "Person A",
  "Speaker 2": "Person B"
}
```

Then run:

```bash
speech2text/.venv/bin/python speech2text/transcribe.py "separate channels.wav" \
  --speakers channels --speaker-map speech2text/config/speakers.json
```

Names appear in text exports; structured transcript JSON retains neutral labels. Adding or changing the mapping creates a new job and repeats recognition.

## 5. `transcribe.py`: complete parameter reference

Syntax:

```text
speech2text/.venv/bin/python speech2text/transcribe.py [AUDIO_FILE] [OPTIONS]
```

Values shown below are the **shipped defaults**. A selected configuration file can change the settings marked “from config.” Command-line values override those settings. Flags such as `--resume` take no value: include the flag to enable it, omit it to disable it.

| Parameter | Accepted value | Default / behavior |
|---|---|---|
| `AUDIO_FILE` | Path to an existing audio file. | Required for transcription; omit for `--preflight` or `--help`. |
| `--config` | Path to a complete JSON configuration file. | `speech2text/config/default.json`. |
| `--mode` | `draft` or `careful`. | `careful`; selected only through this option, not config. |
| `--language` | `auto` or a supported language code, e.g. `en`, `bg`, `de`, `fr`, `es`. | Automatic detection (`null` in config). See the command below for the complete installed list. |
| `--output-dir` | Directory path; created if missing. | Project's `transcription-output/`, from config. Each job gets its own subfolder. |
| `--glossary` | Path to a UTF-8 text file. | No glossary (`null`), from config. |
| `--context` | Path to a UTF-8 text file. | No context (`null`), from config. |
| `--speakers` | `none` or `channels`. | `none`, from config. `channels` requires at least two audio channels. |
| `--mix-channels` | Flag; no value. | Off. Explicitly combines channels; conflicts with `--speakers channels` or config `speakers: "channels"`. |
| `--speaker-map` | Path to a JSON object mapping labels to string names. | No mapping. See the example above. |
| `--chunk-seconds` | Number of seconds, at least `5`, and greater than four times `overlap_seconds`. | `120`, from config. With the default 2-second overlap, must be greater than `8`. |
| `--model-path` | Local model directory containing its files and `receipt.json` from `setup_model.py`. | `speech2text/models/base`, from config. A model name or download URL is not accepted. |
| `--device` | `cpu` or `cuda`. | `cpu`, from config. CUDA requires a configured compatible NVIDIA GPU. |
| `--compute-type` | A precision supported by the selected device; see preflight's `compute_types`. | `int8`, from config. Possible CPU values include `int8`, `int8_float32`, `int16` and `float32`; availability depends on hardware. |
| `--preflight` | Flag; no value. | Off. Checks setup and exits without transcribing, even if an audio path is supplied. |
| `--offline` | Flag; no value. | Offline operation is enforced with or without this flag. |
| `--resume` | Flag; no value. | Off. Reuse a matching job's completed checkpoints; otherwise start a new job. |
| `--overwrite` | Flag; no value. | Off. Back up a matching job and restart. Mutually exclusive with `--resume`. |
| `-h`, `--help` | Flag; no value. | Show command help and exit. |

Print **every supported language code** from the installed software:

```bash
speech2text/.venv/bin/python -c 'from faster_whisper.tokenizer import _LANGUAGE_CODES; print(" ".join(_LANGUAGE_CODES))'
```

All relative command-line paths are interpreted from your current terminal directory. Absolute paths also work.

## 6. Save your preferred settings

You can use the defaults without editing anything. To save different settings:

1. Copy the complete default file:

   ```bash
   cp speech2text/config/default.json speech2text/config/my-settings.json
   ```

2. Open `my-settings.json` in a text editor. For example, set `"language": "en"`, `"threads": 2`, or `"review_max_attempts": 12`. Keep valid JSON: double quotes, no comments, no trailing commas.
3. Select it when running:

   ```bash
   speech2text/.venv/bin/python speech2text/transcribe.py "recording.m4a" --config speech2text/config/my-settings.json
   ```

**Keep every original key.** Custom configurations replace the whole file; missing keys are not filled in. `--mode`, `--speaker-map`, `--resume` and `--overwrite` are command-line options, not configuration keys.

Keep `default.json` and the `*.example.txt` templates generic. Other files under `speech2text/config/` are ignored by Git, including personal settings, hints and speaker maps.

The table lists supported usage ranges. Some numeric ranges are guidance rather than fully checked by the script; keep defaults unless you need to tune behavior.

| Configuration key | Default | Accepted value and purpose |
|---|---|---|
| `model_path` | `"models/base"` | Installed model directory. Relative to `speech2text/`, even for a custom config elsewhere. |
| `output_dir` | `"../transcription-output"` | Output directory. Relative to `speech2text/`. |
| `device` | `"cpu"` | `"cpu"` or `"cuda"`. |
| `compute_type` | `"int8"` | A precision reported by preflight for that device. |
| `threads` | `2` | Integer at least `1`; CPU threads. Start with `2`; adjust for available CPU resources. |
| `language` | `null` | `null` or `"auto"` for detection; otherwise a supported language code. |
| `glossary` | `null` | `null` or a text-file path, relative to the current terminal directory. |
| `context` | `null` | `null` or a text-file path, relative to the current terminal directory. |
| `speakers` | `"none"` | `"none"`, `"channels"`, or `"mix"` (the config equivalent of `--mix-channels`). |
| `formats` | `["md", "txt", "json", "srt"]` | List containing any of these values. `md` creates both Markdown versions. `[]` skips transcript exports; review and manifest files are still written. |
| `chunk_seconds` | `120` | Maximum padded chunk length in seconds. At least `5` and greater than four times `overlap_seconds`. |
| `overlap_seconds` | `2` | Padding on each side, in seconds. At least `0`, less than `chunk_seconds / 4`. |
| `boundary_search_seconds` | `15` | Nonnegative search window in seconds for a nearby silence boundary. `0` disables looking backward. |
| `silence_db` | `-38` | Silence threshold in dB, normally negative. More negative values require quieter audio to count as silence. |
| `silence_seconds` | `0.4` | Positive minimum silence duration for choosing chunk boundaries. Separate from speech detection below. |
| `vad_threshold` | `0.5` | Number strictly between `0` and `1`. Higher values make speech detection more selective and may miss quiet speech. |
| `review_logprob` | `-0.8` | Normally a nonpositive number. Flag segments below this model score; a value closer to `0` flags more. |
| `review_word_probability` | `0.45` | Number from `0` to `1`. Flag words below this model score; a higher value flags more. Not a calibrated correctness probability. |
| `review_max_attempts` | `8` | Integer at least `0`. Maximum passages retried per careful-mode job; `0` disables retries. |
| `review_padding_seconds` | `3` | Nonnegative extra audio before/after a flagged passage, subject to the retry length cap. |
| `review_max_seconds` | `30` | Positive maximum audio length for each retry, including padding. |

## 7. Setup scripts and model parameters

### `setup.sh`: install everything needed for the default setup

```bash
bash speech2text/setup.sh
```

This runs Python environment creation, package installation, model setup and default preflight in that order. It accepts the three model parameters below and passes them to `setup_model.py`. **Use the default command for normal installation.** For an additional model, use `setup_model.py` directly; `setup.sh` still checks the default configured model afterward and does not change your transcription configuration.

### `setup_model.py`: download or verify a model only

Requires the installed Python environment:

```bash
speech2text/.venv/bin/python speech2text/setup_model.py
```

With no arguments, it installs or verifies the same default model. Valid completed files are checksum-verified and reused without network access. Interrupted downloads can be resumed by repeating the command.

| Parameter | Accepted value | Default |
|---|---|---|
| `--repo` | Hugging Face repository ID in `owner/model` form. Must contain a compatible CTranslate2 model with `model.bin`, `config.json`, `tokenizer.json`, and `vocabulary.txt`. | `Systran/faster-whisper-base` |
| `--revision` | Full immutable commit hash from that repository. The underlying downloader also accepts branch/tag names, but use a full hash for repeatable setup and receipt checks. | `ebe41f70d5b6dfa9166e2c581c45c9c0cfc57b66` |
| `--destination` | A new simple folder name beneath `speech2text/models/`, e.g. `small`. | `base` |
| `-h`, `--help` | Flag; show help and exit. Call on `setup_model.py` directly to avoid running the installer first. | Off |

To install another compatible model, obtain its full commit hash from its Hugging Face repository's commit history, then replace `FULL_COMMIT_HASH` below. This is a placeholder, not a runnable revision:

```bash
speech2text/.venv/bin/python speech2text/setup_model.py \
  --repo Systran/faster-whisper-small \
  --revision FULL_COMMIT_HASH \
  --destination small

speech2text/.venv/bin/python speech2text/transcribe.py "recording.m4a" \
  --model-path speech2text/models/small --language en
```

Changing `--repo` does not automatically change the default revision or destination: supply all three when adding a model. Setup does not select the new model automatically; use `--model-path` or update your config. Whisper small needs more disk and memory and is not installed by the default setup. Models using `vocabulary.json` instead of `vocabulary.txt` are not supported by this setup script.

The default model revision and file checksums are recorded in `speech2text/models/base/receipt.json`. The model, faster-whisper and CTranslate2 use MIT licenses. Dependencies are pinned in `requirements.lock`. References: [default model](https://huggingface.co/Systran/faster-whisper-base), [faster-whisper](https://github.com/SYSTRAN/faster-whisper), [hardware support](https://opennmt.net/CTranslate2/hardware_support.html).

## 8. Troubleshooting and cleanup

| Problem | What to do |
|---|---|
| Python cannot find the script | Run from the project folder containing `speech2text/`. Use the paths shown in this guide. |
| Activation points to an old folder after a future move | Use the direct Python path, or refresh activation with `python3 -m venv speech2text/.venv`. Existing package launchers can also retain old paths; use `python -m pip` instead of a stale `pip` launcher. |
| Missing Python package or default model | Run `bash speech2text/setup.sh`, then preflight. Installation may need internet. |
| Missing `ffmpeg` or `ffprobe` | Install `ffmpeg` using the command in section 1. |
| Model receipt mismatch or checksum error | Do not bypass verification. Download into a fresh destination, then select it with `--model-path`. |
| “Results exist” | Repeat the exact command with `--resume`, or use `--overwrite` to back up and restart. |
| Multichannel input rejected | Choose `--mix-channels`, or `--speakers channels` if each participant has a separate channel. |
| Memory error or very slow processing | Close other applications; use the default base model, `--device cpu --compute-type int8`, and `threads: 2`. |
| CUDA/GPU error | Use `--device cpu --compute-type int8`. There is no automatic fallback. GPU setup is not included or tested here; this pinned stack needs compatible NVIDIA hardware and CUDA 12/cuDNN 9 libraries. |
| Missing or questionable words | Check `review.md` and listen to the original timestamps. Try an explicit language and short glossary. Careful mode cannot guarantee correct wording. |
| Empty or silent input | Empty/invalid input is rejected. Silence may correctly produce no transcript text. |

Files are stored in:

| Location | Contents / cleanup |
|---|---|
| `speech2text/.venv/` | Installed Python packages. Keep for future use. |
| `speech2text/models/` | Downloaded models and integrity receipts. Keep to avoid redownloading. |
| `speech2text/cache/` | Download caches. `cache/pip/` can be removed when no installation is running; later installs may redownload packages. |
| `transcription-output/<job>/artifacts/` | Prepared audio and progress. After verifying final outputs, you may remove a specific completed job's `artifacts/` folder to save space; cached resume is then lost. |
| `transcription-output/<job>/` | Final transcripts, reports and manifest. Keep the outputs you need. |
| `transcription-output/<job>.backup-…/` | Old jobs preserved by `--overwrite`. Remove only when you no longer need them. |

The project `.gitignore` excludes `speech2text/.venv/`, `speech2text/models/` and `speech2text/cache/`, along with the default output folder and common audio formats.

Optional software checks (no model download):

```bash
speech2text/.venv/bin/python -m pip check
speech2text/.venv/bin/python -m unittest discover -s speech2text/tests -v
```

The test suite covers timestamp mapping, overlap handling, output formatting, file protection, cache invalidation and interruption recovery. Processing speed and recognition quality depend on the recording, model and hardware. Check important passages by listening to the source audio.
