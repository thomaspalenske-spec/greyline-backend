# Running GreyLine as a resilient service

GreyLine's job is to accumulate trustworthy data continuously. A `nohup uvicorn`
in a terminal dies on crash, on closing the terminal, and on reboot. This service
fixes those.

## What the LaunchAgent does

`deploy/com.greyline.backend.plist` runs the backend under macOS `launchd`:

| Failure | `nohup` | LaunchAgent |
|---|---|---|
| Process crashes | dead until you notice | **auto-restarts** (KeepAlive) |
| You close the terminal | survives (nohup) | survives |
| You log out / reboot | dead | **auto-starts on login** (RunAtLoad) |
| Mac idle-sleeps on your desk | data gap | **prevented** (`caffeinate -i`) |
| You **close the lid** on battery | data gap | **still a data gap** — see below |

## Install

```bash
cp deploy/com.greyline.backend.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.greyline.backend.plist
```

## Stop / start / remove

KeepAlive means `kill` does **not** stop it — launchd relaunches the process.

```bash
# stop (and prevent restart)
launchctl unload ~/Library/LaunchAgents/com.greyline.backend.plist

# start again
launchctl load ~/Library/LaunchAgents/com.greyline.backend.plist

# remove entirely
launchctl unload ~/Library/LaunchAgents/com.greyline.backend.plist
rm ~/Library/LaunchAgents/com.greyline.backend.plist
```

## Status

```bash
launchctl list | grep greyline          # PID + last exit code
tail -f logs/launchd.err.log             # live logs
curl -s localhost:8000/data-integrity    # is it actually working
```

## The ceiling: this is still a laptop

`caffeinate -i` stops *idle* sleep, but closing the lid on battery sleeps the whole
machine and pauses every process. There is no laptop-side fix for that. For genuine
24/7 accumulation, move to an always-on host:

- **Cheapest real fix:** a small cloud VM (~$5–10/mo). Copy the repo, the `.venv`
  (or rebuild it), and the `.env`, then run the same service under `systemd`.
- **No monthly cost:** a Mac mini or Raspberry Pi at home that never sleeps.

Either way the app is unchanged — it already reads `.env` and persists all state to
files on disk, so it's portable as-is. The only migration work is moving credentials
and the data directory.
