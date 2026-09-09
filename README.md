# GramFlow

<div align="center">
  <p>
    
![GitHub Repo stars](https://img.shields.io/github/stars/kavidu-dilhara/gramflow)
![GitHub watchers](https://img.shields.io/github/watchers/kavidu-dilhara/gramflow)
![GitHub forks](https://img.shields.io/github/forks/kavidu-dilhara/gramflow)
![GitHub License](https://img.shields.io/github/license/kavidu-dilhara/gramflow)
![PyPI - Downloads](https://img.shields.io/pypi/dm/gramflow)
![PyPI - Format](https://img.shields.io/pypi/format/gramflow)
![PyPI - Status](https://img.shields.io/pypi/status/gramflow)
[![PyPI version](https://badge.fury.io/py/gramflow.svg)](https://badge.fury.io/py/gramflow)
[![Python versions](https://img.shields.io/pypi/pyversions/gramflow.svg)](https://pypi.org/project/gramflow/)


  </p>
</div>

GramFlow uses your own Telegram account to upload files up to 4 GiB (2 GiB on
non-Premium accounts) straight from the terminal — no bot, no Saved Messages
gymnastics, no browser upload limits.

It started as a maintenance-focused fork of the unmaintained
[`uploadgram`](https://github.com/SpEcHiDe/UploadGram) project, migrated to
an actively maintained Telegram client library, and picked up a long list of
bug fixes along the way.

- Heavily inspired by [telegram-upload](https://github.com/Nekmo/telegram-upload)

## Features

- Uploads any file or a whole directory tree (recursively) to a chat, group,
  channel, or forum topic
- Sends images as real Telegram photos, videos as videos (with an
  auto-generated thumbnail), audio with proper metadata — everything else as
  a document
- Groups consecutive photos/videos into Telegram albums (media groups)
  instead of one message per file
- Resumes an interrupted batch — re-running the same folder against the
  same destination skips files already uploaded
- Batch-wide progress in a single status message, alongside the existing
  per-file progress bar
- `gramflow login` / `gramflow logout` to manage the saved session explicitly
- Optional delete-on-success, custom captions, custom thumbnails, and a live
  console progress bar
- Skips oversized files with a clear notice instead of failing silently
- Natural file ordering (`file2` before `file10`) and dotfiles ignored

## Installation

```sh
pip install gramflow
```

### Requirements

- Python 3.10+
- [`ffmpeg`](https://ffmpeg.org/) on your `PATH` (optional — only needed to
  auto-generate video thumbnails; uploads still work without it)
- [`kurigram`](https://github.com/KurimuzonAkuma/kurigram) — installed
  automatically as a dependency. It's an actively maintained drop-in
  replacement for `pyrogram`, and is still imported as `pyrogram` in code,
  per its own convention.

On first run, GramFlow will ask for a Telegram `api_id` and `api_hash`. Get
both for free at [my.telegram.org](https://my.telegram.org) (API development
tools) and they'll be saved to `~/.config/gramflow/config.env` for future
runs.

## Usage

### Authentication

```sh
gramflow login    # authenticate once and save the session
gramflow logout   # revoke the session with Telegram and remove it locally
```

You don't need to run `login` explicitly — the first upload will prompt for
phone number / code / 2FA password automatically if there's no saved
session. `login`/`logout` exist as explicit, discoverable commands for
managing that session on demand (e.g. switching accounts, or fully logging
out of a shared machine).

### Uploading

```sh
gramflow <chat_id> <path> [options]
```

```sh
$ gramflow 7351948 /path/to/dir/or/file --delete_on_success --fd -t /path/to/custom/thumbnail --caption "A Custom Caption" --topic 1
```

| Argument               | Description                                                      |
| ---------------------- | ------------------------------------------------------------------ |
| `chat_id`               | Destination chat: numeric id, `-100...` channel/supergroup id, legacy `-` group id, or `@username` |
| `dir_path`              | File or directory to upload                                       |
| `--delete_on_success`   | Delete each file locally after it uploads successfully            |
| `--fd`                  | Force every file to be sent as a plain document                   |
| `--t <path>`            | Custom thumbnail to use for videos                                 |
| `--caption "text"`      | Caption applied to every uploaded file (default: no caption)       |
| `--progress`            | Show a live progress bar in the terminal                          |
| `--topic <id>`          | Forum topic id to upload into                                     |
| `--no-resume`           | Don't skip previously uploaded files for this folder/destination  |
| `--fresh`               | Clear saved resume progress for this folder/destination first     |
| `--no-albums`           | Send every photo/video as its own message instead of grouping into albums |

The boolean flags (`--delete_on_success`, `--fd`, `--progress`, `--no-resume`,
`--fresh`, `--no-albums`) are plain on/off switches — include the flag to
enable it, omit it to disable it. `--delete_on_success True` does **not**
work; just pass `--delete_on_success` on its own.

By default, files are sent **without** a caption. To get the old
file-name-as-caption behaviour back, pass `--caption "<filename>"` yourself.

### Resuming an interrupted upload

If a batch is interrupted (crash, Ctrl+C, lost connection), just run the
exact same command again — files already confirmed uploaded (matched by
path, size, and modified time) are skipped automatically, and the batch
picks up where it left off. Pass `--fresh` if you want to force a full
re-upload of that same folder/destination instead.

## Configuration

Environment variables (all optional besides the two credentials, which will
be prompted for interactively if missing):

| Variable          | Purpose                                              | Default |
| ----------------- | ----------------------------------------------------- | ------- |
| `GF_TG_APP_ID`     | Telegram `api_id`                                     | —       |
| `GF_TG_API_HASH`   | Telegram `api_hash`                                   | —       |
| `GF_TG_ST`         | `sleep_threshold` passed to the client                | `10`    |
| `GF_TG_WS`         | Number of worker threads                              | `10`    |
| `GF_TG_MCTS`       | Max concurrent transmissions                          | `4`     |
| `GF_TG_MMC`        | Max message cache size                                | `10000` |
| `GF_TG_MBUC`       | Max business-user-connection cache size               | `200`   |

## Security note

GramFlow logs in as **your own Telegram account**, not a bot. The session
file it creates under `~/.config/gramflow/` grants full access to that
account — treat it like a password (don't commit it, don't share it, don't
upload it anywhere). Automating a personal account also falls under
Telegram's own Terms of Service for user accounts, so keep usage reasonable
(avoid extremely high message/upload rates) to stay within normal limits.

## Troubleshooting

- **`FLOOD_WAIT_X` errors** — Telegram is rate-limiting your account; wait
  the number of seconds it reports before retrying. Sending very large
  batches back-to-back makes this more likely.
- **No video thumbnail generated** — make sure `ffmpeg` is installed and on
  your `PATH`. Without it, uploads still work, just without a thumbnail.
- **Asked for `api_id`/`api_hash` every run** — check that
  `~/.config/gramflow/config.env` is writable and isn't being wiped by
  another process (e.g. a container that resets `$HOME` on restart).
- **Asked to log in again unexpectedly** — the session file lives at
  `~/.config/gramflow/GramFlow.session`. If it's missing or was deleted,
  the next upload (or `gramflow login`) will re-prompt for authentication.
- **A file re-uploads even though it succeeded before** — resume matching
  is based on path, size, and modified time; if any of those changed (e.g.
  the file was re-saved or moved), it's treated as a new file. Use
  `--fresh` to intentionally clear resume history for a folder.

## Contributing

Issues and pull requests are welcome at
[github.com/kavidu-dilhara/gramflow](https://github.com/kavidu-dilhara/gramflow/issues).

## License

MIT [LICENSE](LICENSE). GramFlow is a fork of `uploadgram`;
original copyright is preserved in file headers alongside the new
copyright for this fork.

## Author

**Kavidu Dilhara**
GitHub: [@kavidu-dilhara](https://github.com/kavidu-dilhara)
Repository: [github.com/kavidu-dilhara/gramflow](https://github.com/kavidu-dilhara/gramflow)
