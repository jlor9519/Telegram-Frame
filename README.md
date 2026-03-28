# Telegram-to-InkyPi Photo Frame

This project turns a Raspberry Pi Zero 2 W and a Waveshare 7.3 inch Spectra 6 display into a remotely controlled photo frame.

The companion app in this repository handles:

- Telegram bot polling and conversations
- whitelist and admin access control
- SQLite persistence for users and image history
- local storage for originals, rendered bridge images, and current InkyPi payload
- Dropbox uploads for long-term storage
- setup automation and systemd integration

InkyPi remains the display backend. During setup, this project injects a custom InkyPi plugin into a cloned InkyPi checkout so that panel-specific image handling stays on the InkyPi side.

By default, the setup expects the standard upstream InkyPi layout:

- source checkout: `~/InkyPi`
- runtime install path: `/usr/local/inkypi`
- active source tree: `/usr/local/inkypi/src`, which resolves back to the checkout `src/` directory

## High-level flow

1. A whitelisted user sends a photo to the Telegram bot.
2. The bot asks for location, date, and caption.
3. The app saves the original photo and metadata locally.
4. The app renders a captioned RGB bridge image and writes a canonical bridge payload.
5. The app triggers the configured InkyPi refresh command.
6. The custom InkyPi plugin reads the bridge payload and returns a `PIL.Image` for display.
7. The app stores the result in SQLite and optionally uploads files to Dropbox.

## Layout

```text
app/                         Python companion app
config/                      Example config and systemd unit
integrations/inkypi_plugin/  Injected InkyPi plugin source
scripts/                     Install, update, and debug helpers
tests/                       Unit tests for core behavior
```

## Prerequisites

Before setting up either Pi, you will need:

- A **Telegram bot token** from [@BotFather](https://t.me/BotFather)
- Your **Telegram user ID** (send `/start` to [@userinfobot](https://t.me/userinfobot) to find it)
- (Optional) A **Dropbox app** for cloud backup — see `config/config.example.yaml` for details

## Two-Pi setup

For a two-Pi deployment (Telegram bot on one Pi, e-ink display on another), set up the display Pi first.

### Display Pi

1. Enable SPI (required for the e-ink display):
   ```bash
   sudo raspi-config nonint do_spi 0
   ```
2. Clone this repository and run the display installer:
   ```bash
   git clone https://github.com/jlor9519/Telegram-Frame.git ~/EInkProject && cd ~/EInkProject
   bash scripts/install_display.sh
   ```
   The script automatically clones InkyPi, injects the custom plugin, and starts the InkyPi service.
   Note the IP address printed at the end.

### Server Pi

1. Clone this repository and run the server installer:
   ```bash
   git clone https://github.com/jlor9519/Telegram-Frame.git ~/EInkProject && cd ~/EInkProject
   bash scripts/install_server.sh
   ```
   Run the installer as your normal user, not with `sudo`. The script uses `sudo` internally
   for apt and systemd when needed.
2. Have these ready before you start:
   - Telegram bot token
   - your Telegram user ID
   - Dropbox App key
   - Dropbox App secret
   - a browser session for Dropbox authorization
   - the authorization code returned by Dropbox after approval
3. If you only care about getting the Telegram bot and Dropbox sync working first:
   - answer `"no"` when asked whether the display Pi is on the same local network
   - answer `"yes"` when asked to enable Dropbox
   - do not enter a display Pi URL; that mode does not need one
4. In this off-network mode, the bot writes local state under `data/` and uploads the sync
   payload to Dropbox under `/photo-frame` by default. The installer stores the Dropbox App
   secret in `.env` as `DROPBOX_APP_SECRET` and creates the required Dropbox folders
   automatically.
5. `/settings` is intentionally unavailable on the server Pi in Dropbox mode. Photo uploads,
   database backups, and display payload sync still work.

### Server Pi checklist

When you are setting up the server Pi for `Telegram bot + SQLite + Dropbox uploader`, keep
these points in mind:

- Make sure the Pi has outbound internet access and a correct system clock. Telegram polling
  and Dropbox OAuth both depend on that.
- Install the repo in the directory where you want to keep it. The generated systemd unit
  points at the current checkout path, so if you move the repo later, rerun the installer.
- If you answer `"no"` to the same-network question, Dropbox is mandatory. The installer will
  refuse a remote setup without Dropbox enabled.
- You do not need SPI, InkyPi, or the display installer on the server Pi.
- Local state is stored under `data/`, including the SQLite database at
  `data/db/photo_frame.db`. Make sure the repo directory has enough free space and remains
  writable by the user running the bot.
- By default the Dropbox root path is `/photo-frame`. Change `dropbox.root_path` in
  `config/config.yaml` if you want a different folder.
- If you already set up Dropbox before this fix, rerun `bash scripts/setup_dropbox.sh` once so
  the missing `DROPBOX_APP_SECRET` is saved into `.env`.

### Validate the server Pi install

After the installer finishes:

1. Check the service:
   ```bash
   systemctl status photo-frame.service
   ```
2. In Telegram, run `/myid` and `/status`, then send one test photo.
3. Confirm your Telegram user ID is both an admin and whitelisted. If those values were entered
   incorrectly, the bot may start but reject your uploads.
4. Confirm Dropbox now contains:
   - `/photo-frame/images/originals/...`
   - `/photo-frame/display/current.json`
   - `/photo-frame/display/current.png`
   - `/photo-frame/backup/photo_frame.db`
   - `/photo-frame/images/rendered/...` if `dropbox.upload_rendered` is still enabled
5. If you later switch to a same-network display Pi, rerun `bash scripts/install_server.sh`
   and answer `"yes"` to the same-network question.

### Updating

- On the server Pi: `bash scripts/update_server.sh`
- On the display Pi: `bash scripts/update_display.sh`

## Single-Pi setup

To run everything on a single Pi (both the Telegram bot and the e-ink display):

1. Enable SPI: `sudo raspi-config nonint do_spi 0`
2. Clone this repository.
3. Review `config/config.example.yaml`.
4. Run `bash scripts/install.sh`.
5. Answer the interactive prompts for Telegram, Dropbox, and InkyPi.
6. Verify the bot starts and the custom InkyPi plugin is present in the InkyPi web UI.

The scripts support reruns and can keep or replace existing values when reconfiguring a device.

If you want to rehearse the shell prompt flow on a development machine without touching system services, run:

```bash
bash scripts/mock_install.sh
```

That mock flow writes its state under `mock-installation/`, injects the plugin into a fake InkyPi checkout, and skips privileged system changes.

If you want to test only the Telegram bot flow on a development machine in the foreground, run:

```bash
bash scripts/test_telegram_bot.sh
```

That runner uses isolated state under `telegram-bot-test/`, disables Dropbox, mocks display refresh with `echo`, and stops the bot as soon as you end the script with `Ctrl-C` or close the terminal.

## Notes

- The default Waveshare model is set to `epd7in3e`, which matches the Waveshare 7.3 inch E6 documentation.
- The default render size is `800x480`.
- The default InkyPi source checkout path is `~/InkyPi`, and the default runtime install path is `/usr/local/inkypi`.
- Exact InkyPi refresh behavior is intentionally configurable because the validated local command may differ between installations.
