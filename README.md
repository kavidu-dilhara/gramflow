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

The boolean flags (`--delete_on_success`, `--fd`, `--progress`) are plain
on/off switches — include the flag to enable it, omit it to disable it.
`--delete_on_success True` does **not** work; just pass `--delete_on_success`
on its own.

By default, files are sent **without** a caption. To get the old
file-name-as-caption behaviour back, pass `--caption "<filename>"` yourself.

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
| `GF_TG_MMC`        | Max message cache size                                | `0`     |
| `GF_TG_MBUC`       | Max business-user-connection cache size               | `0`     |

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

## Contributing

Issues and pull requests are welcome at
[github.com/kavidu-dilhara/gramflow](https://github.com/kavidu-dilhara/gramflow/issues).

## License

AGPL-3.0 — see [LICENSE](LICENSE). GramFlow is a fork of `uploadgram`;
original copyright is preserved in file headers alongside the new
copyright for this fork.

## Author

**Kavidu Dilhara**
GitHub: [@kavidu-dilhara](https://github.com/kavidu-dilhara)
Repository: [github.com/kavidu-dilhara/gramflow](https://github.com/kavidu-dilhara/gramflow)
