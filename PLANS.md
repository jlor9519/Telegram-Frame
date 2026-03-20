# PLANS.md

## Project Goal

Build a single Raspberry Pi application for a gift photo frame based on:

- Raspberry Pi Zero 2 W
- Waveshare 7.3 inch e-ink display
- Raspberry Pi OS
- Inkypi for the display pipeline
- Telegram bot for sending photos from a phone
- Dropbox for long-term image storage and archive

In this initial version, **everything runs on the same Raspberry Pi**:

- Telegram bot
- photo intake flow
- metadata collection
- Dropbox upload
- image rendering
- image display on the e-ink panel
- local persistence
- setup/install automation

The codebase should be structured so it can later be split into:
- a display client
- a separate always-on server Pi

But for now, it must be a single deployable project.

---

## Primary Use Case

A whitelisted user sends a photo to the Telegram bot.

The bot then asks:
1. where the image was taken
2. when it was taken
3. what caption should be written under the photo

After that, the application should:
- save the original image
- store metadata
- upload the original image to Dropbox
- render a display-ready image with caption text
- pass the rendered image into the Inkypi display pipeline
- refresh the e-ink display
- confirm success to the user

---

## Non-Goals for the Initial Version

Do **not** build these yet unless needed for the MVP to work:

- separate server Pi
- web dashboard
- multi-device support
- slideshow mode
- favorites
- advanced archive browsing
- image search
- remote admin beyond a few Telegram commands
- complex retry workers
- direct Dropbox-to-display syncing without the bot flow
- programming of the e-ink display logic, this will be handled by Inkypi

---

## Design Principles

1. Keep the first version small and reliable.
2. Keep Inkypi-specific logic isolated behind one adapter layer.
3. Use Dropbox for long-term storage, but do not depend on Dropbox for every display action.
4. Keep enough local files to survive simple restarts.
5. Structure the code so future split into bot/server and display client is easy.
6. Make the setup reproducible on a fresh Raspberry Pi with a setup script.
7. Use simple local persistence first. SQLite is preferred over scattered JSON files once the basic MVP works.

## Required High-Level Features

### 1. Telegram Bot
The bot must:
- receive photos
- restrict access to whitelisted Telegram user IDs
- ask follow-up questions after a photo is sent
- support a small set of useful commands

### 2. Metadata Collection Flow
After a photo is sent, the bot must ask:
- Where was this photo taken?
- When was it taken?
- What caption should be shown under the photo?

### 3. Local Image Pipeline
The app must:
- download the photo locally
- store metadata locally
- generate a final display-ready image with caption text
- keep a small local cache of recent rendered files

### 4. Inkypi Integration
The app must integrate with Inkypi through a single adapter or wrapper.

The rest of the codebase must **not** depend on Inkypi internals directly.

### 5. Dropbox Integration
The app must:
- upload original photos to Dropbox
- optionally upload rendered versions
- support an archive folder layout for long-term storage
- avoid unbounded SD card growth

### 6. Setup Automation
A setup script must:
- install dependencies
- clone/configure Inkypi
- configure the local project
- set up Dropbox credentials/config
- create folders
- install systemd service(s)
- make the app start automatically on boot

---

## Repository Structure

Use a structure like this:

```text
photo-frame/
├─ PLANS.md
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

---

## Architecture

The application should be organized into these layers.

### 1. Bot Layer
Responsible for:
- Telegram bot startup
- message handlers
- command handlers
- photo intake
- conversation state flow

Files:
- `bot.py`
- `commands.py`
- `conversations.py`

### 2. Auth Layer
Responsible for:
- whitelist checks
- admin checks
- adding/removing trusted users

Files:
- `auth.py`

### 3. Storage Layer
Responsible for:
- local file paths
- temp file handling
- rendered image output paths
- local cleanup policy
- archive movement
- Dropbox upload coordination

Files:
- `storage.py`
- `dropbox_client.py`

### 4. Rendering Layer
Responsible for:
- grayscale conversion
- resize/crop logic
- caption band
- text wrapping
- writing final display-ready image

Files:
- `render.py`

### 5. Display Layer
Responsible for:
- calling the display hook
- isolating Inkypi-specific integration
- keeping the rest of the app independent from Inkypi details

Files:
- `display.py`
- `inkypi_adapter.py`
- `scripts/display_hook.py`

### 6. Persistence Layer
Responsible for:
- SQLite connection
- schema setup
- CRUD functions for users, images, jobs, and settings

Files:
- `database.py`
- `models.py`

---

## Inkypi Integration Strategy

The project should include setup automation for Inkypi, but the application code should not be tightly coupled to Inkypi internals.
### Inkypi Project Source Code
https://github.com/fatihak/InkyPi

### Rules
1. The application must treat Inkypi as an external display backend.
2. Inkypi-specific logic must live only in:
   - `app/inkypi_adapter.py`
   - `scripts/display_hook.py`
3. The rest of the app should only know:
   - there is a final rendered image file
   - a display function is called with that file path

### Required contract
The display layer should support a call conceptually like:

```python
display_image("/path/to/final_rendered_image.png")
```

Internally, this may:
- call a Python wrapper
- call an Inkypi script
- call a shell command
- use a copied or adapted integration script

### Important implementation note
If exact Inkypi invocation is unknown during implementation, create a clearly marked placeholder wrapper and TODOs, while still structuring the code correctly.

---

## Dropbox Integration Strategy

Dropbox should be used for long-term storage and archive, not as the only source of truth for the running application.

### Store in Dropbox
- original uploads
- optionally rendered display-ready images
- archived older images
- optional metadata export

### Store locally
- SQLite database
- current displayed image
- recent rendered files
- temp incoming files during processing

### Suggested Dropbox layout

```text
/photo-frame/
  /images/
    /originals/
    /rendered/
  /archive/
    /2026/
    /2027/
  /metadata/
```

### Dropbox expectations
- use a dedicated app/folder for this project
- keep credentials out of Git
- fail gracefully if Dropbox is temporarily unavailable
- do not block all local display behavior just because Dropbox is down

### Initial behavior
For the first working version:
- upload original image after successful intake
- if Dropbox upload fails, report it and keep local files
- do not delete local originals until Dropbox upload is confirmed

---

## Local Database

Use SQLite for the main implementation.

### Suggested tables

#### `users`
Fields:
- `telegram_user_id` primary key
- `username`
- `display_name`
- `is_admin`
- `is_whitelisted`
- `created_at`

#### `images`
Fields:
- `image_id`
- `telegram_file_id`
- `local_original_path`
- `local_rendered_path`
- `dropbox_original_path`
- `dropbox_rendered_path`
- `location`
- `taken_at`
- `caption`
- `uploaded_by`
- `created_at`

#### `settings`
Fields:
- `key`
- `value`

#### `events` or `logs` (optional)
Fields:
- `event_type`
- `payload`
- `created_at`

### Database goals
- keep whitelist state
- keep image history
- support future commands like `/latest`, `/previous`, `/archive`
- survive restarts cleanly

---

## Telegram Bot Behavior

### Access control
Only whitelisted users may submit photos or run most commands.

### Admin model
Use two levels:
- admin users
- normal whitelisted users

### Recommendation
- any whitelisted user may send photos
- only admin users may run `/whitelist <userID>`

---

## Required Commands

### `/help`
Shows:
- how to send a photo
- supported commands
- short explanation of the metadata flow

### `/status`
Returns a health summary of the main system components, including:
- bot runtime
- database
- Dropbox connectivity
- local storage
- display/Inkypi integration
- latest processed image info

The command must not trigger a real display refresh by default.

### `/myid`
Returns the sender’s Telegram numeric user ID.

### `/whitelist <userID>`
Adds a user ID to the whitelist.

This should be admin-only.

### Optional but useful if easy
- `/latest` — redisplay latest image
- `/refresh` — refresh current displayed image
- `/cancel` — cancel current conversation

Do not let optional commands delay the MVP.

---

## Photo Intake Conversation

### Expected flow

1. User sends a photo.
2. Bot checks authorization.
3. Bot downloads the photo locally.
4. Bot asks: `Where was this photo taken?`
5. User replies.
6. Bot asks: `When was it taken? For example: 2026-03-15 or Summer 2025`
7. User replies.
8. Bot asks: `What caption should be shown under the photo?`
9. User replies.
10. App:
    - stores metadata
    - uploads original to Dropbox
    - renders final image
    - triggers display update
    - stores final result paths and metadata in database
11. Bot replies with success or a meaningful error.

### Requirements
- use Telegram conversation state handling
- allow `/cancel`
- avoid losing state between the three questions during normal operation
- keep error handling simple but clear

---

## Rendering Requirements

The renderer must:
- open the original photo
- convert to grayscale
- resize to fit the display image area
- reserve a lower area for text
- draw metadata and caption text
- save a final display-ready image

### Suggested layout
- image at top
- caption band at bottom
- first line: `LOCATION | DATE`
- next one or two lines: caption

### Priorities
- readability on e-ink
- simple layout
- robust text wrapping
- predictable output dimensions

### Configurable values
- render width
- render height
- caption height
- font path
- font sizes
- text margin

---

## Setup Script Requirements

The setup script is an important part of the project and must be included.

Create at least:

- `scripts/install.sh`
- `scripts/setup_inkypi.sh`
- `scripts/setup_dropbox.sh`
- `scripts/update.sh`

### `install.sh`
Responsibilities:
1. install apt packages
2. create application directory if needed
3. create Python virtual environment
4. install Python dependencies
5. create local data directories
6. copy config templates if missing
7. run Inkypi setup helper
8. run Dropbox setup helper
9. initialize SQLite database
10. install systemd service
11. enable and start service
12. optionally run a test command

### `setup_inkypi.sh`
Responsibilities:
- clone Inkypi if not already present
- place it in a known location
- install any required dependencies
- perform whatever local configuration is needed
- leave behind a stable integration point for `display_hook.py`

If some Inkypi details are not fully automatable, clearly document them and isolate them behind TODO comments and setup documentation.

### `setup_dropbox.sh`
Responsibilities:
- guide configuration of Dropbox credentials
- create required local config placeholders
- optionally verify connection
- create expected remote folder structure if practical

### `update.sh`
Responsibilities:
- pull latest app code
- update Python dependencies
- restart systemd service

---

## Configuration

Use:
- `.env` for secrets
- YAML config for non-secret settings

### `.env` should contain
- Telegram bot token
- Dropbox access token or credentials
- admin Telegram user IDs if preferred here

### `config.yaml` should contain
- local data paths
- display dimensions
- font path
- Inkypi/display command settings
- cleanup policy
- Dropbox folder paths

### Example config shape

```yaml
telegram:
  bot_token: "REPLACE_ME"

security:
  admin_user_ids:
    - 123456789

database:
  path: "./data/db/photo_frame.db"

storage:
  incoming_dir: "./data/incoming"
  rendered_dir: "./data/rendered"
  cache_dir: "./data/cache"
  archive_dir: "./data/archive"
  keep_recent_rendered: 20

dropbox:
  enabled: true
  root_path: "/photo-frame"

display:
  width: 800
  height: 480
  caption_height: 80
  font_path: "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
  command: "python scripts/display_hook.py \"{image_path}\""
```

---

## Systemd Service

The application should run as a systemd service on boot.

### Service goals
- start automatically after reboot
- restart on failure
- log to journalctl
- run under a dedicated working directory

### Expected service
One service is enough for the initial version:
- `photo-frame.service`

Do not overcomplicate this with multiple services yet.

---

## Logging and Error Handling

At minimum, log:
- startup
- bot connected
- unauthorized access attempts
- photo received
- metadata collected
- Dropbox upload success/failure
- render success/failure
- display success/failure
- whitelist changes

### Failure cases to handle gracefully
- unauthorized user sends photo
- invalid `/whitelist` usage
- Telegram download failure
- missing config
- Dropbox upload failure
- render failure
- Inkypi/display command failure
- database initialization failure

On failure:
- tell the user something useful
- log details
- keep as much recoverable state as practical

---

## Development Phases

Implement in phases. Keep the first working version small.

### Phase 0 — Project Skeleton
Create:
- repo structure
- requirements
- config loading
- logging
- basic startup

### Phase 1 — Telegram MVP
Implement:
- bot startup
- `/help`
- `/status`
- `/myid`
- whitelist logic
- `/whitelist`

### Phase 2 — Conversation Flow
Implement:
- receive photo
- ask location
- ask date
- ask caption
- store metadata locally

### Phase 3 — Rendering
Implement:
- grayscale rendering
- caption band
- saved rendered output
- local test rendering command

### Phase 4 — Inkypi/Display Integration
Implement:
- display wrapper
- integration adapter
- call display after successful render

### Phase 5 — Dropbox Integration
Implement:
- upload original photo
- record remote path in database
- optional upload of rendered image

### Phase 6 — Setup Automation
Implement:
- install script
- Inkypi setup helper
- Dropbox setup helper
- systemd service install

### Phase 7 — Polish
Add only if time allows:
- `/latest`
- `/refresh`
- cleanup policy
- better status reporting
- archive helpers

---

## Development Order

Build in this exact order unless there is a strong reason not to:

1. repo skeleton and config loading
2. Telegram bot with `/myid`
3. whitelist and `/whitelist`
4. photo intake conversation
5. local metadata persistence
6. render final display image
7. display wrapper and local display call
8. Dropbox upload
9. setup scripts
10. systemd service
11. cleanup/refactor

Do **not** start by deeply integrating Inkypi internals.
Do **not** start by optimizing Dropbox archival logic.
Do **not** start by adding many commands.

---

## Definition of Done for the Initial Version

The initial version is done when all of the following are true:

- the project can be installed on a Raspberry Pi using the provided setup scripts
- Inkypi is installed/configured by the setup flow or clearly prepared by it
- the Telegram bot runs on the same Raspberry Pi
- a whitelisted user can send a photo
- the bot asks for location, date, and caption
- the photo is stored locally
- metadata is stored in SQLite
- the original image is uploaded to Dropbox
- a rendered display-ready image is created locally
- the rendered image is sent through the display adapter to Inkypi
- the e-ink display updates successfully
- `/myid` works
- `/whitelist <userID>` works for admins
- the app restarts automatically on boot via systemd

---

## Notes for Future Refactor

Structure the code now so it can later be split into two components:

### Future server component
Would own:
- Telegram bot
- Dropbox upload
- whitelist logic
- queue creation

### Future display component
Would own:
- image fetch
- rendering
- display update

To make that future split easier:
- isolate Dropbox logic
- isolate display logic
- keep Telegram-specific code out of rendering and storage modules
- keep clear interfaces between modules

---

## First Concrete Task for the Coding Agent

Start by implementing the smallest useful end-to-end local version:

- create project skeleton
- create config loading
- implement Telegram bot startup
- implement `/myid`
- implement admin whitelist logic
- implement photo intake conversation
- save local metadata
- render a captioned image locally
- create a display hook abstraction
- leave a clear Inkypi adapter placeholder if exact integration needs tuning

After that, add Dropbox upload and setup scripts.

Do not try to solve every future architecture concern in the first pass.
