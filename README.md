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

## Setup summary

The expected Pi flow is:

1. Clone this repository.
2. Review `config/config.example.yaml`.
3. Run `bash scripts/install.sh`.
4. Answer the interactive prompts for Telegram, Dropbox, and InkyPi.
5. Verify the bot starts and the custom InkyPi plugin is present in the InkyPi web UI.

The scripts support reruns and can keep or replace existing values when reconfiguring a device.

## Two-Pi setup

For a two-Pi deployment (Telegram bot on one Pi, e-ink display on another):

1. On the **display Pi**, run `bash scripts/install_display.sh`.
   Note the IP address printed at the end — you will need it for the next step.
2. On the **server Pi**, run `bash scripts/install_server.sh`.
   When prompted for the display Pi URL, enter `http://<display-pi-ip>`.

To update after pulling new code:

- On the server Pi: `bash scripts/update_server.sh`
- On the display Pi: `bash scripts/update_display.sh`

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
