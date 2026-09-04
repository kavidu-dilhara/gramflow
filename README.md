# GramFlow

GramFlow uses your own Telegram account to upload files up to 4 GiB (2 GiB on
non-Premium accounts) straight from the terminal — no bot, no Saved Messages
gymnastics, no browser upload limits.

It started as a maintenance-focused fork of the unmaintained
[`uploadgram`](https://github.com/SpEcHiDe/UploadGram) project, migrated to
an actively maintained Telegram client library, and picked up a long list of
bug fixes along the way (see [Changelog](#changelog) below).

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

- Python 3.9+
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

## Changelog

### 1.0.0 — Renamed to GramFlow, migrated off the unmaintained upstream

Forked from `uploadgram`, renamed throughout (package, CLI command, config
directory, env var prefix), and rebuilt on top of an actively maintained
Telegram client. This release also fixes a long list of real bugs found
while going through the codebase.

#### Migrated Telegram client: `pyrotgfork` → `kurigram`

`pyrotgfork` is no longer maintained. All code now targets
[`kurigram`](https://github.com/KurimuzonAkuma/kurigram), a drop-in API
replacement (still `import pyrogram`) that isn't 100% identical under the
hood:

- `Client(...)` no longer accepts `max_business_user_connection_cache_size`
  in current kurigram releases. The client now inspects `Client.__init__`'s
  real signature at runtime and only forwards kwargs it actually supports,
  so a future rename/removal degrades gracefully instead of crashing on
  startup.
- `reply_document(...)` / `send_document(...)` no longer has
  `disable_content_type_detection` — it's `force_document` now.
- Every `reply_*` call previously passed `quote=True`, which is deprecated
  in kurigram and printed a warning on every upload. Removed — the reply
  context is already implicit.

#### Images now upload as photos

`.jpg`, `.jpeg`, `.png`, and `.webp` files are sent with `reply_photo`, so
they show up as an actual inline Telegram photo instead of always falling
back to a generic document (which is what happened before — there was no
image branch at all). If Telegram rejects a particular image as a photo
(odd color profile, unsupported encoding, etc.), it's caught and the file
falls back to being sent as a document instead of failing the whole batch.

A photo still arrives as a document when:

1. **`--fd` is passed** — forces every file, including images, to be sent
   as a generic document (useful for preserving the original bytes exactly).
2. **The extension isn't a Telegram photo format** — anything besides
   `.jpg`/`.jpeg`/`.png`/`.webp` (e.g. `.gif`, `.bmp`, `.tiff`, `.heic`) is
   always sent as a document. That's a Telegram limitation, not a tool
   choice.
3. **Telegram rejects the photo upload** (corrupt JPEG, CMYK color profile,
   an absurdly large pixel count, ...) — GramFlow logs a warning and falls
   back automatically.

#### File name is no longer sent as a caption by default

Previously every upload sent the file name as the caption. The default is
now an empty caption; pass `--caption "text"` to set one explicitly.

#### Other bug fixes

- **Broken boolean flags** — `--delete_on_success`, `--fd`, and `--progress`
  were declared with `type=bool` in argparse, which just calls
  `bool("whatever you typed")`. Any non-empty string (including the literal
  text `"False"`) evaluated to `True`. They're now proper
  `action="store_true"` flags.
- **Broken console progress bar** — `tqdm`'s bar was updated with
  `(current / total) * 1024 * 1024` per callback, which isn't a byte delta
  and had no real relationship to file size. It's now updated with the
  correct `current - pbar.n` delta, and properly closed after each file.
- **Wasted `ffmpeg` thumbnail generation** — a video thumbnail was
  screenshotted even when a `--t` thumbnail was already supplied. Now
  skipped in that case.
- **Silent skip of oversized files** — files larger than the account's max
  upload size were skipped with zero feedback. A notice is now printed and
  sent to the destination chat.
- **Missing `ffmpeg` crashed the upload** — a missing `ffmpeg` binary now
  degrades to "no thumbnail" instead of raising an unhandled
  `FileNotFoundError`.
- **`humanbytes()` off-by-one** — exactly `1024` bytes printed as
  `"1024.0  B"` instead of `"1.0 KiB"`; also guarded against a `KeyError`
  for sizes beyond `Ti`.
- **Bare `except:` swallowed `Ctrl+C`** — the progress-message editor used
  a bare `except:`, which also catches `KeyboardInterrupt` and
  `asyncio.CancelledError`. Now only catches the expected
  `MessageNotModified` case.
- **Deprecated event loop API** — `asyncio.get_event_loop()` outside a
  running loop is deprecated as of Python 3.10+; replaced with
  `asyncio.run()`.
- **Session left running after an error** — if anything failed mid-run
  (bad chat id, network error, `Ctrl+C`), the client was never stopped,
  leaving the local session file locked for the next run. Now always
  stopped in a `finally` block.
- **Negative, non-`-100`-prefixed chat ids** (legacy basic groups) were
  never converted to `int`, since `str.isnumeric()` is `False` for anything
  starting with `-`. Chat id parsing now just tries `int()` and falls back
  to the raw string for `@usernames`.
- **Invalid second argument to `get_chat`** — `get_chat(dest_chat, False)`
  passed an unknown second positional that raised `TypeError`. Now called
  with a single `chat_id` argument.
- **Video thumbnail leaked on upload failure** — the generated `.jpg` was
  only deleted on the success path; a failed upload (FloodWait, network
  error, ...) left the temp thumbnail behind. Now cleaned up in a `finally`
  block.
- **Bad progress-message throttle** — `round(diff % 10.00) == 0` also
  matched small fractional remainders, firing the very first callback
  immediately and risking Telegram's edit rate limit. Now uses a proper
  10-second boundary check.
- **Sleep-after-skip** — a blanket 10-second pause after every iteration
  slowed down runs with mostly oversized files. The pause now only fires
  after an actual upload attempt.
- **Dotfile uploads** — `.DS_Store`, `.Thumbs.db`, etc. were uploaded as
  cruft. Now filtered out.
- **Lexicographic file ordering** — numbered files came out as
  `file1, file10, file2`; now sorted with a natural-order key.
- **Thumbnail filename collisions** — back-to-back screenshots could
  produce identical file names. Now uses a millisecond + uuid suffix.
- **Destructive config migration** — the legacy `config.ini` was deleted
  at *module import time* on every run, silently destroying any existing
  file at that path. The migration now only fires when the new
  `config.env` is actually being created for the first time.
- Config prompt whitespace bug that produced `"enter app_id 's value: "` —
  fixed.

### Dependencies bumped to latest

| package        | before      | now       |
| -------------- | ----------- | --------- |
| pyrotgfork     | 2.1.33.8    | (removed) |
| kurigram       | -           | ^2.2.25   |
| python-dotenv  | 0.10        | ^1.2.3    |
| hachoir        | 3.1.1       | ^3.3.0    |
| tqdm           | 4.62.3      | ^4.70.0   |
| TgCrypto       | 1.2.5       | ^1.2.5    |

## License

AGPL-3.0 — see [LICENSE](LICENSE). GramFlow is a fork of `uploadgram`;
original copyright is preserved in file headers alongside the new
copyright for this fork.

## Author

**Kavidu Dilhara**
GitHub: [@kavidu-dilhara](https://github.com/kavidu-dilhara)
Repository: [github.com/kavidu-dilhara/gramflow](https://github.com/kavidu-dilhara/gramflow)
