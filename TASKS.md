# TASKS.md

## Purpose

This file breaks the project into concrete implementation tasks for the initial **single Raspberry Pi** version, where one codebase handles:

- Telegram bot
- user whitelist/auth
- metadata collection
- local storage
- Dropbox upload
- image rendering
- Inkypi display integration
- setup automation

The goal is to get a working end-to-end MVP first, then improve structure and reliability.

---

## Working Rules

1. Favor a working MVP over broad abstractions.
2. Keep Inkypi-specific logic isolated.
3. Keep Dropbox logic isolated.
4. Keep the first implementation small.
5. Do not build the future two-Pi architecture yet.
6. Use polling for Telegram, not webhooks.
7. Use SQLite for persistence.
8. Use clear TODO markers where exact Inkypi details still need manual adjustment.

---

## Phase -1 — Discovery and Decision Gate

Do these tasks before writing the main application code.

## Task -1.1 — Verify exact hardware target
Confirm:
- the exact Waveshare 7.3 inch model name
- the driver identifier required by Inkypi installation
- the real panel resolution and orientation we will target

### Acceptance criteria
- exact display model is written down in project notes
- Inkypi install command can be stated precisely for this hardware

---

## Task -1.2 — Validate stock Inkypi on the Raspberry Pi
On the actual Pi Zero 2 W:
- install Raspberry Pi OS
- install Inkypi
- verify the panel can refresh successfully at least once
- record any manual setup or dependency quirks

### Acceptance criteria
- stock Inkypi can drive the display on the real hardware
- setup notes are captured for automation later

---

## Task -1.3 — Choose the integration shape
Evaluate the two realistic integration options:

### Option A — Preferred
- a custom Inkypi plugin reads the latest Telegram photo payload from shared local storage

### Option B — Fallback
- the app renders the final image itself and calls Inkypi only through a display hook/adapter

### Acceptance criteria
- one approach is explicitly chosen before implementation continues
- the contract between app output and Inkypi input is written down

---

## Task -1.4 — Create a rendering test fixture
Pick one or two sample photos and use them throughout early development.

### Acceptance criteria
- the same fixture images are used for renderer and display tests
- image quality can be compared consistently between approaches

---

## Recommended Implementation Order

Follow tasks roughly in this order:

1. discovery and hardware validation
2. project skeleton
3. config and logging
4. database
5. Telegram bot startup
6. auth and whitelist
7. photo conversation flow
8. local metadata persistence
9. rendering pipeline
10. display integration
11. Dropbox upload
12. setup scripts
13. systemd service
14. polish and cleanup

---

# Phase 0 — Project Skeleton

## Task 0.1 — Create repository structure
Create the following folders and files:

```text
photo-frame/
├─ PLANS.md
├─ TASKS.md
├─ README.md
├─ requirements.txt
├─ .env.example
├─ config/
│  ├─ config.example.yaml
│  └─ systemd/
│     └─ photo-frame.service
├─ scripts/
│  ├─ install.sh
│  ├─ update.sh
│  ├─ setup_inkypi.sh
│  ├─ setup_dropbox.sh
│  ├─ display_hook.py
│  └─ test_display.py
├─ app/
│  ├─ __init__.py
│  ├─ main.py
│  ├─ config.py
│  ├─ auth.py
│  ├─ bot.py
│  ├─ commands.py
│  ├─ conversations.py
│  ├─ storage.py
│  ├─ dropbox_client.py
│  ├─ render.py
│  ├─ display.py
│  ├─ inkypi_adapter.py
│  ├─ database.py
│  ├─ models.py
│  └─ logging_setup.py
├─ data/
│  ├─ incoming/
│  ├─ rendered/
│  ├─ cache/
│  ├─ archive/
│  └─ db/
└─ logs/
```

### Acceptance criteria
- repo structure exists
- placeholder files exist
- app can be started without import errors once stubs are created

---

## Task 0.2 — Add Python dependencies
Create `requirements.txt` with the initial dependencies.

### Initial dependencies
- `python-telegram-bot`
- `Pillow`
- `dropbox`
- `PyYAML`
- `python-dotenv`

### Acceptance criteria
- dependencies install cleanly in a virtualenv on Raspberry Pi OS

---

## Task 0.3 — Add README placeholder
Create a basic README with:
- project purpose
- high-level architecture
- setup summary
- note that exact Inkypi integration may require local tuning

### Acceptance criteria
- README exists and is not empty

---

# Phase 1 — Configuration and Logging

## Task 1.1 — Implement config loading
Create `app/config.py`.

### Responsibilities
- load `.env`
- load YAML config
- merge environment variables and config
- validate required keys
- expose a typed or structured config object

### Required config domains
- telegram
- security
- database
- storage
- dropbox
- display

### Acceptance criteria
- app fails clearly if config is missing
- config can be loaded from example file with minimal edits

---

## Task 1.2 — Create config example
Create `config/config.example.yaml`.

### Include settings for
- bot token placeholder
- admin user IDs
- DB path
- local folders
- Dropbox root path
- display dimensions
- display command
- font path

### Acceptance criteria
- example config is complete enough to guide setup

---

## Task 1.3 — Create `.env.example`
Add placeholders for:
- `TELEGRAM_BOT_TOKEN`
- `DROPBOX_ACCESS_TOKEN`

### Acceptance criteria
- secrets are not hardcoded into the repository

---

## Task 1.4 — Implement logging setup
Create `app/logging_setup.py`.

### Responsibilities
- configure root logger
- log to stdout
- use readable format with timestamp and level
- keep implementation simple

### Acceptance criteria
- startup logs are visible
- modules can import and use logger cleanly

---

# Phase 2 — Database

## Task 2.1 — Implement SQLite connection
Create `app/database.py`.

### Responsibilities
- open SQLite DB
- create schema if missing
- expose helper functions or repository-style access

### Acceptance criteria
- DB file is created automatically
- schema initialization is idempotent

---

## Task 2.2 — Create initial schema
Implement tables:

### `users`
- `telegram_user_id` INTEGER PRIMARY KEY
- `username` TEXT
- `display_name` TEXT
- `is_admin` INTEGER
- `is_whitelisted` INTEGER
- `created_at` TEXT

### `images`
- `image_id` TEXT PRIMARY KEY
- `telegram_file_id` TEXT
- `local_original_path` TEXT
- `local_rendered_path` TEXT
- `dropbox_original_path` TEXT
- `dropbox_rendered_path` TEXT
- `location` TEXT
- `taken_at` TEXT
- `caption` TEXT
- `uploaded_by` INTEGER
- `created_at` TEXT

### `settings`
- `key` TEXT PRIMARY KEY
- `value` TEXT

### Acceptance criteria
- tables exist after first app start
- schema can be recreated without breaking

---

## Task 2.3 — Seed admin users
On startup, ensure admin user IDs from config exist in the DB and are marked:
- `is_admin = 1`
- `is_whitelisted = 1`

### Acceptance criteria
- configured admin users can use the bot immediately

---

# Phase 3 — Auth and User Management

## Task 3.1 — Implement auth layer
Create `app/auth.py`.

### Responsibilities
- check whether a Telegram user is whitelisted
- check whether a Telegram user is admin
- add user to whitelist
- optionally get/create user record

### Acceptance criteria
- user access decisions come from one central module

---

## Task 3.2 — Define auth rules
Use these rules:

- whitelisted users may send photos
- whitelisted users may use `/help`, `/status`, `/myid`
- only admin users may use `/whitelist <userID>`

### Acceptance criteria
- auth behavior is consistent across commands and photo flow

---

# Phase 4 — Telegram Bot Skeleton

## Task 4.1 — Implement application entrypoint
Create `app/main.py`.

### Responsibilities
- load config
- initialize logging
- initialize DB
- seed admins
- create Telegram application
- register handlers
- run polling loop

### Acceptance criteria
- bot starts with `python -m app.main` or equivalent

---

## Task 4.2 — Create bot setup module
Create `app/bot.py`.

### Responsibilities
- construct Telegram application
- register handlers from other modules
- keep bootstrapping code organized

### Acceptance criteria
- handlers are not all defined in `main.py`

---

# Phase 5 — Commands

## Task 5.1 — Implement `/help`
Create handler in `app/commands.py`.

### Expected behavior
Return:
- how to submit a photo
- required photo metadata flow
- supported commands

### Acceptance criteria
- whitelisted user receives useful help text
- unauthorized user gets a clear rejection

---

## Task 5.2 — Implement `/status`
Return:
- bot is running
- current timestamp
- number of whitelisted users
- optionally last image info if available

### Acceptance criteria
- command works without requiring a photo upload first

---

## Task 5.3 — Implement `/whitelist <userID>`
### Rules
- admin-only
- validate that input is numeric
- create/update user row
- mark user as whitelisted

### Acceptance criteria
- valid ID is added successfully
- invalid usage returns helpful message
- non-admin user is rejected

---

## Task 5.4 — Optional `/cancel`
If easy, add `/cancel` to stop the current conversation flow.

### Acceptance criteria
- current conversation state resets cleanly

---

# Phase 6 — Storage Utilities

## Task 6.1 — Implement storage path helpers
Create `app/storage.py`.

### Responsibilities
- generate file paths for originals
- generate file paths for rendered outputs
- create directories if missing
- provide deterministic folder handling

### Suggested naming
Use image IDs such as:

```text
20260318_153000_abcd1234
```

### Acceptance criteria
- code does not hardcode file paths in multiple places

---

## Task 6.2 — Implement temp/local save helpers
### Responsibilities
- save downloaded Telegram photo
- save rendered image
- support future cleanup policy

### Acceptance criteria
- original and rendered paths are predictable and safe

---

# Phase 7 — Photo Intake Conversation

## Task 7.1 — Implement conversation state machine
Create `app/conversations.py`.

### States
- waiting for location
- waiting for taken_at
- waiting for caption

### Entry point
- user sends a photo

### Acceptance criteria
- conversation starts when a photo is received

---

## Task 7.2 — Download photo locally
When a whitelisted user sends a photo:
- get the best available size
- download it to local incoming storage
- create a new image ID
- store temporary state in conversation context

### Acceptance criteria
- original photo is saved locally
- conversation continues after download

---

## Task 7.3 — Ask for location
Bot prompt:
`Where was this photo taken?`

### Acceptance criteria
- user response is stored in conversation state

---

## Task 7.4 — Ask for date
Bot prompt:
`When was it taken? For example: 2026-03-15 or Summer 2025`

### Acceptance criteria
- user response is stored in conversation state

---

## Task 7.5 — Ask for caption
Bot prompt:
`What caption should be shown under the photo?`

### Acceptance criteria
- user response is stored in conversation state

---

## Task 7.6 — Finalize intake
After the caption is received:
- persist metadata to DB
- trigger Dropbox upload
- trigger rendering
- trigger display update
- reply with success or error

### Acceptance criteria
- all steps are called in the correct order
- failure messages are understandable

---

# Phase 8 — Rendering Pipeline

## Task 8.1 — Implement render module
Create `app/render.py`.

### Responsibilities
- open original image
- convert to grayscale
- resize to configured display area
- create bottom caption band
- draw location and date
- draw wrapped caption
- save final image

### Acceptance criteria
- given an original image and metadata, a valid final image is produced

---

## Task 8.2 — Implement text wrapping
### Requirements
- wrap caption within configured width
- support one or two lines initially
- avoid text overflow as much as possible

### Acceptance criteria
- long captions do not break rendering

---

## Task 8.3 — Make output size configurable
Read from config:
- width
- height
- caption height
- font path
- font sizes
- margin

### Acceptance criteria
- render behavior is driven by config, not hardcoded magic numbers everywhere

---

## Task 8.4 — Add local render test
Create a simple local test helper, either:
- `scripts/test_display.py`
- or a small render test mode

### Acceptance criteria
- one command can generate a sample rendered file for visual inspection

---

# Phase 9 — Display Integration

This phase depends on the decision made in Phase -1.

Use one of these paths:
- preferred: Inkypi plugin reads the latest approved photo payload and renders/displays it
- fallback: app renders the final image and `display_hook.py` asks Inkypi to display it

Keep the rest of the app insulated from that choice.

## Task 9.1 — Implement display abstraction
Create `app/display.py`.

### Responsibilities
- accept a rendered image path
- delegate to Inkypi adapter
- raise or return clear success/failure result

### Acceptance criteria
- rest of app does not call Inkypi directly

---

## Task 9.2 — Implement Inkypi adapter
Create `app/inkypi_adapter.py`.

### Responsibilities
- isolate all display-specific invocation logic
- use configured display command or wrapper
- keep internals hidden from the rest of the app

### Acceptance criteria
- one module owns all Inkypi-specific behavior

---

## Task 9.3 — Create `scripts/display_hook.py`
### Initial goal
Provide a stable integration point for the rest of the app.

### Behavior
- accept image path as argument
- either:
  - call the real Inkypi pipeline
  - or temporarily log the image path and exit successfully with a TODO note

### Acceptance criteria
- app can call display hook without knowing Inkypi internals
- exact integration details are isolated to this script and adapter

---

## Task 9.4 — Trigger display after render
In the photo intake flow:
- after render succeeds
- call display layer
- if display succeeds, persist rendered path and confirm success
- if display fails, report error and keep files for debugging

### Acceptance criteria
- end-to-end flow reaches display trigger

---

# Phase 10 — Dropbox Integration

## Task 10.1 — Implement Dropbox client
Create `app/dropbox_client.py`.

### Responsibilities
- upload original photo
- optionally upload rendered image
- create folder structure if needed
- return remote paths

### Acceptance criteria
- app can upload a local file to configured Dropbox project folder

---

## Task 10.2 — Define Dropbox folder paths
Use paths such as:

```text
/photo-frame/images/originals/
/photo-frame/images/rendered/
/photo-frame/archive/2026/
/photo-frame/metadata/
```

### Acceptance criteria
- remote paths are centralized and not duplicated throughout code

---

## Task 10.3 — Upload original after metadata collection
During intake finalization:
- upload original image to Dropbox
- store returned path in DB
- if upload fails, keep local copy and continue according to chosen error policy

### Recommended initial error policy
- report Dropbox failure to user
- do not delete local original
- still allow local render/display if possible

### Acceptance criteria
- Dropbox outage does not destroy local work

---

## Task 10.4 — Optional rendered upload
If easy, upload rendered file too and save remote path.

### Acceptance criteria
- optional feature does not block MVP if skipped

---

# Phase 11 — Local Persistence of Images

## Task 11.1 — Save image records to DB
For every successfully processed photo:
- store original path
- store rendered path
- store Dropbox paths if available
- store metadata fields

### Acceptance criteria
- DB reflects the current image history

---

## Task 11.2 — Optional helper to retrieve latest image
Add utility to get latest image record for future `/latest` or `/refresh`.

### Acceptance criteria
- helper exists even if command is not exposed yet

---

# Phase 12 — Setup Scripts

## Task 12.1 — Create `scripts/install.sh`
### Responsibilities
- install OS dependencies
- create app directory if needed
- create virtualenv
- install Python packages
- create local folders
- initialize config
- initialize DB
- call Inkypi setup helper
- call Dropbox setup helper
- install systemd service
- enable and start service

### Acceptance criteria
- script is readable and reasonably idempotent
- major failures exit with clear messages

---

## Task 12.2 — Create `scripts/setup_inkypi.sh`
### Responsibilities
- clone Inkypi into a known path if missing
- install or prepare its dependencies if possible
- create a stable local integration point for `display_hook.py`
- document any manual follow-up needed

### Important
Do not spread Inkypi-specific logic across the repository.

### Acceptance criteria
- script prepares the environment for display integration
- any manual assumptions are documented clearly

---

## Task 12.3 — Create `scripts/setup_dropbox.sh`
### Responsibilities
- guide or prepare Dropbox configuration
- verify presence of credentials
- optionally create or verify remote folder structure

### Acceptance criteria
- Dropbox setup path is documented and repeatable

---

## Task 12.4 — Create `scripts/update.sh`
### Responsibilities
- pull latest code
- update Python dependencies
- restart service

### Acceptance criteria
- update flow is straightforward on the Pi

---

# Phase 13 — Systemd Service

## Task 13.1 — Create service file
Create `config/systemd/photo-frame.service`.

### Responsibilities
- run app on boot
- restart on failure
- use correct working directory
- use the project virtualenv

### Acceptance criteria
- service file is valid
- can be enabled via `systemctl enable`

---

## Task 13.2 — Install service from script
`install.sh` should:
- copy service file to systemd location
- reload daemon
- enable service
- start service

### Acceptance criteria
- bot starts after reboot without manual action

---

# Phase 14 — Error Handling and Reliability

## Task 14.1 — Unauthorized user handling
Ensure unauthorized users:
- cannot use photo intake
- cannot use protected commands
- receive clear message

### Acceptance criteria
- unauthorized access is consistent everywhere

---

## Task 14.2 — Handle command misuse
Examples:
- `/whitelist` without argument
- `/whitelist abc`
- sending text when no conversation is active

### Acceptance criteria
- user receives a helpful response
- bot does not crash

---

## Task 14.3 — Handle processing failures
Handle failures in:
- Telegram download
- DB write
- Dropbox upload
- rendering
- display invocation

### Acceptance criteria
- failures are logged
- user gets a readable message
- partial files are preserved if useful for debugging

---

# Phase 15 — Polish

## Task 15.1 — Improve `/status`
If easy, return a health summary of the main system components, including::
- bot runtime
- database
- Dropbox connectivity and metadata
- local storage
- display/Inkypi integration
- latest processed image info

The command must not trigger a real display refresh by default.

### Acceptance criteria
- status is informative but concise

---

## Task 15.2 — Add `/refresh` or `/latest` if easy
Only after core flow works.

### `/latest`
Redisplay the last successful rendered image.

### `/refresh`
Force re-run of display for current rendered image.

### Acceptance criteria
- optional commands do not destabilize the MVP

---

## Task 15.3 — Add local cleanup policy
If easy:
- keep only recent rendered files locally
- do not delete files still needed for current display or debugging
- never delete originals before Dropbox upload succeeds

### Acceptance criteria
- no dangerous cleanup behavior

---

# Phase 16 — Validation Checklist

Use this checklist before considering the initial version done.

## Bot and auth
- [ ] bot starts successfully
- [ ] `/help` works
- [ ] `/status` works
- [ ] `/myid` works
- [ ] `/whitelist <userID>` works for admin
- [ ] non-admin cannot whitelist others
- [ ] unauthorized users are blocked

## Photo flow
- [ ] sending a photo starts the conversation
- [ ] bot asks location
- [ ] bot asks date
- [ ] bot asks caption
- [ ] `/cancel` works if implemented

## Persistence
- [ ] DB initializes automatically
- [ ] admin users are seeded
- [ ] image metadata is stored in DB
- [ ] file paths are stored correctly

## Rendering
- [ ] rendered image is produced locally
- [ ] longish captions do not break the layout
- [ ] output dimensions match config

## Display
- [ ] display layer can be called from app code
- [ ] display hook receives the rendered file path
- [ ] Inkypi integration is isolated to adapter/hook

## Dropbox
- [ ] original image uploads successfully
- [ ] remote path is stored
- [ ] local workflow still behaves sensibly if Dropbox upload fails

## Setup and operations
- [ ] install script exists
- [ ] update script exists
- [ ] Inkypi setup helper exists
- [ ] Dropbox setup helper exists
- [ ] systemd service exists
- [ ] app starts on boot

---

# Phase 17 — Explicit Anti-Tasks

Do **not** spend time on these before the MVP works:

- splitting into two Raspberry Pis
- webhooks
- web dashboard
- multiple display devices
- advanced archive browsing
- slideshow scheduling
- favorites
- image tagging/search
- complex background job queues
- deep refactors before end-to-end success

---

# First Concrete Build Target

The first real milestone to hit is:

1. start bot on Raspberry Pi
2. admin can run `/myid`
3. admin can whitelist another user
4. whitelisted user sends photo
5. bot asks all three metadata questions
6. photo is saved locally
7. rendered image is generated locally
8. display hook is called
9. success message is returned

Once that works, add Dropbox upload and setup automation.

---

# Suggested Commit Sequence

If using small commits, use a sequence like:

1. `init repo skeleton and config loading`
2. `add sqlite setup and admin seeding`
3. `add telegram bot startup and basic commands`
4. `add whitelist auth logic`
5. `add photo conversation flow`
6. `add local storage helpers`
7. `add image renderer`
8. `add display abstraction and hook`
9. `add dropbox upload client`
10. `add install and update scripts`
11. `add systemd service and docs`

---

# Handoff Note for the Coding Agent

Focus on reaching one clean end-to-end path first.

A correct first version should prefer:
- simple structure
- isolated external integrations
- clear TODOs
- reliable logging
- straightforward install steps

Do not over-engineer early.