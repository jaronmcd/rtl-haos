# Development

How to run tests and work on RTL-HAOS locally.

## Local dev environment

To set up the project’s isolated pytest virtualenv without running tests (handy for editors/linters and iterative work):

```bash
./scripts/pytest_venv.sh --no-run
source .venv-pytest/bin/activate
```

After activating, you can run tests normally:

```bash
pytest
```

To leave the venv:

```bash
deactivate
```


## Version strings (base vs build metadata)

RTL-HAOS keeps a single, canonical **base version** in `config.yaml` under `version:`.

- **Base version (what HAOS/Supervisor expects):** `VER.REV.PATCH` (SemVer-ish), e.g. `1.2.0-rc.1`
- **Display version (logs + HA device info):** `vVER.REV.PATCH+BUILD`, e.g. `v1.2.0-rc.1+g3f2a9c1`

Important: **do not append letters** to the base version (for example `1.2.0-rc.1x`). Keep `config.yaml` strictly `X.Y.Z` and use **build metadata** instead.

### Setting the build metadata

RTL-HAOS reads build metadata from the environment variable `RTL_HAOS_BUILD` and appends it as SemVer build metadata (`+...`).

**Local host / venv**

```bash
export RTL_HAOS_BUILD=dev
python -u main.py
# >>> ... (v1.2.0-rc.1+dev) <<<
```

Common pattern (git short SHA):

```bash
export RTL_HAOS_BUILD="$(git rev-parse --short HEAD)"
python -u main.py
```

You can also put it in `.env` for local development:

```ini
RTL_HAOS_BUILD=dev
```

**Docker**

At runtime:

```bash
docker run -e RTL_HAOS_BUILD=dev ...
```

Or at build time (if your build system passes args):

```bash
docker build --build-arg RTL_HAOS_BUILD="$(git rev-parse --short HEAD)" -t rtl-haos:dev .
```

### Docker build options (SoapySDR / HackRF)

The image builds `rtl_433` from upstream git with `ENABLE_SOAPYSDR=ON`.

HackRF support via SoapySDR requires the SoapySDR device module for HackRF (`SoapyHackRF`).
The Dockerfile can build this module from source (controlled by `BUILD_SOAPYHACKRF`).

#### Build args

- `BUILD_SOAPYHACKRF` (default: `1`)
  - `1`: build + install SoapyHackRF into the image
  - `0`: skip building SoapyHackRF (HackRF won’t appear as a Soapy device)

Example:

    docker build --build-arg BUILD_SOAPYHACKRF=0 -t rtl-haos:dev .

#### Note for HAOS add-on builds

Home Assistant Supervisor does not reliably pass custom Docker build args for local add-on builds.
So HAOS builds use the Dockerfile defaults unless you create a separate image/branch with different defaults.


**HAOS add-on (local development)**

Home Assistant Supervisor builds add-ons from the repo contents and does **not** reliably pass custom Docker build args for local add-ons. For local HAOS dev, the simplest options are:

1) **Dev-only `run.sh` export**: temporarily add `export RTL_HAOS_BUILD=...` near the top of `run.sh`, then rebuild/restart the add-on.

2) **Optional UI knob** (if you choose to add it): add a `build:` option in `config.yaml` + `schema`, and in `run.sh` export it as `RTL_HAOS_BUILD`.

After changing build/base version, **rebuild + restart** the add-on so MQTT discovery/device info is republished.

### Update notifications (REV-only)

For update alerts, treat **REV** as the “notify threshold”: patch/build changes can be applied by users who rebuild when needed, but only **REV** bumps should generate broad update notifications.

A simple rule is to derive a notify version like `VER.REV.0` (ignore PATCH/BUILD) for comparison/alerts while still showing the full display version everywhere else.

## Run RTL-HAOS from a development host venv

This runs the same Python app you ship in the add-on, but directly on your dev machine (no Supervisor, no container).
Configuration is read from **environment variables / `.env`** (since `/data/options.json` is add-on-only).

### Prereqs

- **Python**: whatever your venv script selects (recommended: use `./scripts/pytest_venv.sh` below)
- **MQTT broker** reachable from your dev host
  - If you already use Home Assistant’s Mosquitto add-on, point `MQTT_HOST` at your HA box IP
  - Or run a local broker (example below)
- **rtl_433** installed and in `PATH` (or set `RTL_433_BIN` to your custom build)

Quick check:

```bash
rtl_433 -V
```

### 1) Create & activate the venv

Use the same venv helper you already use for tests (it installs RTL-HAOS + deps in editable mode):

```bash
./scripts/pytest_venv.sh --no-run
source .venv-pytest/bin/activate
```

### 2) Create a `.env`

Start from the example:

```bash
cp .env.example .env
```

Minimum settings to get MQTT discovery into Home Assistant:

```ini
# .env
MQTT_HOST=192.168.1.109
MQTT_PORT=1883
MQTT_USER=your_user
MQTT_PASS=your_pass

BRIDGE_ID=42
BRIDGE_NAME=rtl-haos-bridge
# Tip: keep BRIDGE_NAME stable; use BRIDGE_ID to differentiate instances and avoid duplicate devices from retained MQTT discovery
```

Optional (use a custom rtl_433 binary / build):

```ini
RTL_433_BIN=/path/to/rtl_433
```

Optional (pass through any rtl_433 flags globally):

```ini
RTL_433_ARGS=-g 40 -p 0 -t "direct_samp=1"
```

Optional (manual multi-radio config from the host; note JSON string):

```ini
RTL_CONFIG=[{"name":"utility","id":"102","freq":"915M","rate":"1024k","device":":00000001","protocols":"104,105","args":"-g 25 -t \"biastee=1\""},{"name":"weather","id":"201","freq":"433.92M","rate":"250k"}]
```

### 3) Start a local MQTT broker (if you don’t already have one)

```bash
docker run --rm -p 1883:1883 eclipse-mosquitto:2
```

Then set `MQTT_HOST=127.0.0.1` in `.env`.

### 4) Run RTL-HAOS

From repo root:

```bash
python -u main.py
```

Stop with **Ctrl+C**.

### Notes

- **USB permissions**: on Linux you may need udev rules / group membership (or run as root) to access RTL-SDR dongles.
- **No hardware**: RTL-HAOS will warn if no RTL-SDR devices are found. For most development work, unit tests are the fastest path; for end-to-end behavior, run on a host with an SDR attached.

## Testing

### Unit tests (default)

Run the normal unit test suite (fast, deterministic):

```bash
pytest
```

### Opt-in `rtl_433` integration tests

These tests execute the external `rtl_433` binary and are **skipped by default** (so GitHub Actions / CI stays green).

Run the integration tests:

```bash
RUN_RTL433_TESTS=1 pytest -m integration
```

Run only the replay test:

```bash
RUN_RTL433_TESTS=1 pytest -m integration -k rtl433_replay
```

#### Recording a replay fixture (recommended)

Replay fixtures live in `tests/fixtures/rtl433/` (see `tests/fixtures/rtl433/README.md`). Capture files like `.cu8` are intentionally **gitignored**.

Record a short capture:

```bash
mkdir -p tests/fixtures/rtl433
./scripts/record_rtl433_fixture.sh 433.92M 250k 20 tests/fixtures/rtl433/sample.cu8
```

Sanity-check the capture decodes:

```bash
rtl_433 -r tests/fixtures/rtl433/sample.cu8 -F json | head
```

### Opt-in hardware smoke tests (RTL-SDR required)

These require an RTL-SDR device available to the test host. They do **not** require receiving RF events; they only verify `rtl_433` starts and exits cleanly.

```bash
RUN_HARDWARE_TESTS=1 pytest -m hardware
```

### Run everything locally (unit + integration + hardware)

```bash
RUN_RTL433_TESTS=1 RUN_HARDWARE_TESTS=1 pytest
```

### Script argument guardrails (no hardware)

The fixture-recording script supports unit suffixes and a dry-run mode:

```bash
./scripts/record_rtl433_fixture.sh --dry-run 433.92M 250k 10 tests/fixtures/rtl433/test.cu8
```

If you forget a suffix (e.g. `433.92` instead of `433.92M`, or `250` instead of `250k`), the script will fail fast with a helpful hint.

---

## Deploy to Home Assistant OS (HAOS)

RTL-HAOS can be developed as a **local Home Assistant add-on**. Use the single helper script:

- **`scripts/haos.sh`** — deploy / uninstall / logs / status

It reads the add-on slug from `config.yaml` and deploys to:

- `/addons/local/<slug>` (HAOS local add-ons)

### Prereqs

- A Home Assistant OS machine reachable on your network.
- SSH access into HAOS (commonly via the **Terminal & SSH** add-on).
- Password auth can work, but SSH keys are recommended.

Make it executable once:

```bash
chmod +x scripts/haos.sh
```

### Deploy

#### Build metadata (auto)

When you deploy to HAOS using `./scripts/haos.sh deploy`, the script generates an untracked `build.txt` containing the current git short SHA (and `-dirty` if you have local changes). `run.sh` loads this into `RTL_HAOS_BUILD`, so the add-on will display versions like `v1.2.0-rc.1+046cc83` automatically after each deploy/rebuild.


Sync repo contents to HAOS:

```bash
./scripts/haos.sh deploy --host homeassistant.local
```

Deploy, rebuild, restart, then print logs:

```bash
./scripts/haos.sh deploy --host 192.168.1.109 --rebuild --restart --logs
```

If you see an error like “Addon … does not exist in the store”, run once in the HA UI:

**Settings → Add-ons → Add-on store → (⋮) Check for updates**

Then install it under **Local add-ons**. After that, CLI rebuild/restart works reliably.

### Logs

```bash
./scripts/haos.sh logs --host 192.168.1.109
./scripts/haos.sh logs --host 192.168.1.109 --follow
```

### Status / Debug

```bash
./scripts/haos.sh status --host 192.168.1.109
```

### Uninstall

Uninstall (if installed) and remove remote add-on folder(s) under `/addons`:

```bash
./scripts/haos.sh uninstall --host 192.168.1.109
```

Also remove the add-on’s optional `/share/<slug>` directory:

```bash
./scripts/haos.sh uninstall --host 192.168.1.109 --rm-share --yes
```

### Optional: sync a local data folder to /share

Mirror a local folder into HAOS `/share/<slug>`:

```bash
./scripts/haos.sh deploy --host 192.168.1.109 --share ./tx_files
```

### Configuration via environment variables

```bash
export HA_HOST=192.168.1.109
export HA_USER=root
export HA_PORT=22
# export HA_KEY=~/.ssh/haos_ed25519   # recommended
./scripts/haos.sh deploy --rebuild --restart --logs
```

