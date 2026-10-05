# Smart School Bag

A Python + RFID packing assistant. Pick a school day, tap each book's RFID card on the reader, and the
dashboard shows what is **present**, what is **missing**, anything **extra**, and whether the bag is **ready**.

Runs on a Raspberry Pi 3B+ (Flask + SQLite + vanilla JavaScript, no build step) and works completely
offline. It is regular decision logic and a database, not AI.

## Contents
1. [Requirements](#1-requirements) · 2. [Install](#2-install) · 3. [Run](#3-run) · 4. [Use from a phone or laptop](#4-use-from-a-phone-or-laptop)
5. [Demo / Exhibition mode](#5-demo--exhibition-mode) · 6. [Connecting the RFID reader](#6-connecting-the-rfid-reader)
7. [Settings, PIN, backups](#7-settings-admin-pin-and-backups) · 8. [Run on boot](#8-run-automatically-on-boot) · 9. [Troubleshooting](#9-troubleshooting)
10. [Project layout](#10-project-layout) · 11. [Tests](#11-tests) · 12. [Upgrading from the old version](#12-upgrading-from-the-first-version)

## 1. Requirements
* **Hardware:** Raspberry Pi 3B+, 125 kHz USB RFID reader, TK4100 cards. (None of the hardware is needed to try the app: use demo mode.)
* **OS:** Raspberry Pi OS Lite 64-bit (any Linux, macOS or Windows also works for development).
* **Python:** 3.11 or newer (developed for 3.13; tested here on 3.12).
* **Internet:** only to download the dependencies once. The app itself never uses the Internet: no CDN, fonts or external APIs.

## 2. Install
```bash
cd smart-school-bag
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```
The database needs no setup step. On first start the app creates `data/schoolbag.db` with the demo books and
timetable, and on later starts it only applies pending upgrades (after making a backup). It never recreates the database.

## 3. Run
```bash
source .venv/bin/activate
python run.py
```
Open **http://localhost:5000**. Stop with `Ctrl+C`. Settings such as the port are environment variables:

| Variable | Default | Meaning |
|---|---|---|
| `SCHOOLBAG_PORT` | `5000` | Port to listen on |
| `SCHOOLBAG_HOST` | `0.0.0.0` | `127.0.0.1` = this device only; `0.0.0.0` = whole network |
| `SCHOOLBAG_DATA_DIR` | `./data` | Where the database, backups, logs and secret key live |
| `SCHOOLBAG_DATABASE` | `<data dir>/schoolbag.db` | Database file |
| `SCHOOLBAG_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`... |
| `FLASK_SECRET_KEY` | generated | Optional. By default a random key is created once in `data/secret_key` |

Example: `SCHOOLBAG_PORT=8080 python run.py`

## 4. Use from a phone or laptop
The app listens on the whole network by default. Find the Pi's address with `hostname -I`, then browse to
`http://<that address>:5000` from any device on the same Wi-Fi/LAN. Anyone on that network can open the app, so set an
[admin PIN](#7-settings-admin-pin-and-backups) if the network is shared.

## 5. Demo / Exhibition mode
Open **Exhibition** in the menu (visible while *Demo mode* is on in Settings). Suggested flow:

1. Tap **Monday**, then **Start packing session**.
2. Tap a few books. Each tap is a *simulated card* sent through the same pipeline as a real card.
3. The band shows progress and exactly which books are still missing. Tap a book twice to show duplicate detection.
4. Tap the missing books. The band turns green: **BAG READY**.
5. **Complete session** shows the summary.

Simulated scans are always labelled **Simulated** in the dashboard, history and session summary. A session that mixes
real and simulated scans says so. The demo works with no reader attached.

## 6. Connecting the RFID reader
The reader's USB protocol is not known until you plug it in, so nothing is assumed. The app has a reader abstraction and
two **experimental, untested** adapters. The dashboard only says **Connected** after the device was genuinely opened.

**Step 1: find out how your reader appears.** Plug it in, then:
```bash
lsusb                       # is it listed?
ls -l /dev/input/by-id/     # a "...-event-kbd" entry  => it behaves like a USB keyboard
ls -l /dev/serial/by-id/    # an entry here           => it is a serial device
```
Most cheap 125 kHz readers act as a **keyboard** and "type" the card number followed by Enter.

**Step 2: configure it** in *Settings > RFID reader & demo mode*:

| Your reader | Reader type | Device path (example) | Extra |
|---|---|---|---|
| Keyboard-style | USB keyboard-style reader | `/dev/input/by-id/usb-XXXX-event-kbd` | Needs the `input` group |
| Serial text lines | USB serial reader | `/dev/ttyUSB0` | `pip install -r requirements-serial.txt`; needs the `dialout` group; set the baud rate |

Add yourself to the groups (the installer does this for you), then log out and in again:
`sudo usermod -aG input,dialout $USER`

**Step 3: check it.** Hold a card to the reader and watch the **Live read log** in Settings: it shows the raw text the
reader sends. If the log stays empty or looks wrong (binary data, other framing), the reader needs a different adapter;
see `app/hardware/` (one small class, `open / read_uid / close`).

**Step 4: assign cards.** *Books > Manage > Scan card*, hold the book's card to the reader, then **Save card**.

Card UIDs are normalised (upper-case, separators removed) and stored as text, so leading zeros survive. Whatever format the
reader prints (hex or decimal) works, as long as it is consistent.

Reader states: **Not set up** (type = none) · **Unavailable** (something is missing, such as permissions or pyserial) ·
**Disconnected** (device not found or unplugged; retried automatically) · **Connected** · **Error**.

## 7. Settings, admin PIN and backups
*Settings* holds the school/student name, default day, timezone, repeat-scan window, auto-start behaviour, reader and
demo options, the optional **admin PIN**, backups and a recent-events log.

* **Admin PIN** (off by default): when on, Books, Timetable, Settings and backups need the PIN (4-12 digits, unlocked for 30 minutes).
  The dashboard, Exhibition and History stay open, so demonstrations stay quick.
* **Backups:** *Create backup now*, download, restore (also from an uploaded file) or delete. A safety copy is made automatically before
  upgrades, restores and *Clear history*.
* **Manual copy:** `data/schoolbag.db` is the whole database; copy it while the app is stopped, or use *Create backup now*.

## 8. Run automatically on boot
```bash
./scripts/install.sh        # run as your normal user, not with sudo
```
This creates the virtual environment, installs the dependencies, adds your user to the `input`/`dialout` groups, installs
`smart-school-bag.service` (starts after the network, restarts on failure, logs to the journal) and starts it.

```bash
sudo systemctl status smart-school-bag
journalctl -u smart-school-bag -f      # live logs
sudo systemctl restart smart-school-bag
```
To change the port for the service: `echo 'SCHOOLBAG_PORT=8080' | sudo tee /etc/default/smart-school-bag` and restart it.

## 9. Troubleshooting
| Symptom | What to do |
|---|---|
| Page won't open from a phone | Same Wi-Fi? Use the address from `hostname -I`. Check `SCHOOLBAG_HOST` isn't `127.0.0.1`. |
| Header says *Reader: Not set up* | Pick a reader type in Settings (section 6). Use Demo mode meanwhile. |
| *Unavailable: No permission...* | `sudo usermod -aG input,dialout $USER`, then reboot or log in again. |
| *Disconnected: ... not found* | Re-plug the reader and re-check the path with `ls /dev/input/by-id` / `ls /dev/serial/by-id`. |
| Live read log is empty | The reader isn't sending through that device; try the other reader type. |
| Card scans but is "Unknown RFID card" | Assign that card to a book (Books > Manage > Scan card). |
| Same card ignored when tapped twice quickly | Intentional: repeat reads within the *repeat-scan window* (default 3 s) are ignored. |
| "Database needs attention" page | The database file was damaged. Restore a backup from that page. Nothing is deleted automatically. |
| Times look wrong | Set the correct timezone in Settings (default Asia/Kolkata). |
| `waitress is not installed` in the log | `pip install -r requirements.txt` (the app still works without it). |
| Anything else | `journalctl -u smart-school-bag -n 100`, or `data/logs/app.log`. Error pages show a short *Reference* code you can find in the log. |

## 10. Project layout
```
run.py                  start the server
app/
  __init__.py           create_app() factory
  config.py, defaults.py  deployment config; seed data for brand-new databases only
  db.py, migrations.py  SQLite access, integrity check, versioned upgrades
  repositories/         ALL SQL lives here
  services/             business rules (scan pipeline, sessions, timetable, books, backup ...)
  hardware/             reader interface, manager thread, keyboard + serial adapters, demo cards
  routes/               thin Flask handlers: pages, JSON api, admin forms, auth, recovery
  templates/, static/   Jinja templates, one CSS file, small vanilla JS files (all local)
tests/                  automated tests (python -m unittest)
deploy/, scripts/       systemd unit and installer
data/                   database, backups, logs (created automatically)
```
The scan pipeline is in one place: `services/scan_service.py`. Real reads and simulated reads both call `ScanService.process()`.

## 11. Tests
```bash
python -m unittest discover -s tests -t .
```
They use temporary databases and never touch `data/`.

## 12. Upgrading from the first version
Copy your old `data/schoolbag.db` into `data/` and start the app. It is upgraded in place after an automatic backup
(`data/backups/*-auto-upgrade.db`): your books, card assignments, timetable and scan history are kept. Old scans appear in History
as *Earlier version*. The old environment variables `DEMO_MODE` and `DEFAULT_DAY` are now settings in the app.

## Deployment

This repository is a Flask backend with Jinja + vanilla JavaScript in the browser; there is no Vite/React frontend build in the repo itself. It is served from the Raspberry Pi, and the public API is exposed through Cloudflare Tunnel.

- Pi: run `sudo bash smartbag-tunnel-install.sh`, then start the backend with the commands below.
- Cloudflare Pages: connect the repo to a Pages project, set the build command to the static frontend command if you add one, set the output directory to `dist`, and add the env var `VITE_API_URL` or `NEXT_PUBLIC_API_URL` with the value `https://api2.cssiddheesh.in`.
- Custom domain: add `smartbag.cssiddheesh.in` in the Pages project custom domains.
- Quick test: `curl https://api2.cssiddheesh.in/health`

Backend start on the Pi:
```bash
cd /home/<your-user>/smart-school-bag-v2
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
PORT=8000 ALLOWED_ORIGINS="https://smartschoolbag.pages.dev,https://smartbag.cssiddheesh.in,http://localhost:5173,http://localhost:3000" python run.py
```
