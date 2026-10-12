# 🪞 AI Smart Mirror

A smart mirror woken up by an **image classification model** instead of a button.

The classification model watches the camera continuously. When it sees the class you picked,
the app grabs the current frame, sends it to the local vision model (VLM) along with your
prompt, and shows the answer beside the live mirror image.

Everything you would want to change during a workshop is editable in the browser — no code,
no restart, no save button.

<img width="1498" height="809" alt="image" src="https://github.com/user-attachments/assets/ad802368-230e-4fd2-a2c3-997e5e848823" />

## Contents

- [Hardware](#hardware)
- [Running it](#running-it)
- [How the trigger works](#how-the-trigger-works)
- [Using your own Edge Impulse model](#using-your-own-edge-impulse-model)
- [Preparing several boards](#preparing-several-boards)
- [How the code is put together](#how-the-code-is-put-together)

## Hardware

- Arduino UNO Q or VENTUNO Q
- A USB camera
- Network Mode, so the UI is reachable from your browser

## Running it

1. Connect the USB camera and start the app from Arduino App Lab.
2. Open `http://<board-name>.local:7000`.
3. Show the trigger class to the camera and hold it. A bar fills over one second, then the
   mirror looks at you and answers.

The panel always lists **what the model sees right now** with its confidence, so it is obvious
why the mirror does or does not fire. While the VLM is generating, the mirror dims and a
spinner appears.

Two controls, both applied on the fly:

| Control | Effect |
| --- | --- |
| **Trigger class** | The class that wakes the mirror. Applies as soon as you pick it. |
| **Mirror prompt** | The prompt sent to the VLM. Applies when you stop typing. |

## How the trigger works

The mirror only ever asks "is the trigger class in view right now" — it does not care which
class came before.

| Phase | Behaviour |
| --- | --- |
| **Hold** | The class must stay in view for `HOLD_SEC` (1 s) before firing. |
| **Flicker** | Gaps shorter than `GRACE_SEC` (0.5 s) do not reset the hold. |
| **Generating** | The hold stops counting and the bar is hidden. |
| **Cooldown** | `COOLDOWN_SEC` (15 s) before the mirror can fire again. |
| **Cooldown cut short** | A *different* class seen for `CLEAR_SEC` (0.5 s) ends the cooldown early. |

In practice: step out of view and back, and the mirror answers again straight away; stand
perfectly still and it waits the full 15 seconds. All five constants are at the top of
`python/main.py`.

## Using your own Edge Impulse model

Train an image classification model on Edge Impulse, add it in Arduino App Lab, then change
two things.

Point the brick at your model — easiest from the brick configuration in App Lab, which writes
it into `app.yaml`:

```yaml
bricks:
  - arduino:video_image_classification:
      model: <your-model-id>
```

List its classes in `python/main.py` so they appear in the dropdown, with the first one
selected at startup:

```python
TRIGGER_CLASSES = ["my-class", "my-other-class"]
```

Forgetting a class is not fatal — it is added to the dropdown the first time the model
reports it.

## Preparing several boards

The VLM models are ~11 GB combined, so downloading them on every board is painful. Prepare one
board through App Lab, then copy from it over ADB.

```bash
./scripts/pull-models.sh          # one prepared board  ->  this computer
./scripts/provision.sh            # this computer  ->  every connected board
```
## How the code is put together

```
┌────────────┐   frames   ┌───────────────────────────┐
│ USB Camera │───────────▶│   Image Classification    │
└────────────┘            │          Brick            │
       │                  └─────────────┬─────────────┘
       │ latest frame                   │ {"label": confidence, ...}
       │ (JPEG)                         ▼
       │                  ┌───────────────────────────┐
       └─────────────────▶│         main.py           │
                          │  trigger class held?      │
                          └─────────────┬─────────────┘
                                        │ frame + prompt
                                        ▼
                          ┌───────────────────────────┐
                          │     VLM Brick (local)     │
                          └─────────────┬─────────────┘
                                        │ answer
                                        ▼
                          ┌───────────────────────────┐
                          │ Web UI (/state, /stream)  │
                          └───────────────────────────┘
```

| Brick | What it does here |
| --- | --- |
| `arduino:video_image_classification` | Classifies the camera stream and calls back on every result |
| `arduino:vlm` | Looks at one camera frame and answers your prompt |
| `arduino:web_ui` | Serves the page, the settings API and the MJPEG mirror stream |

- One `Camera` is shared with the classification brick. `main.py` keeps the newest frame as
  JPEG, used for both the mirror stream and the VLM.
- All app state — prompt, trigger, current detections, hold progress, status, answer — lives in
  a single `state` dictionary, read by the browser from `GET /state` and written with
  `POST /settings`.
- The VLM runs on its own thread so a multi-second generation never stalls classification.
- `assets/app.js` polls `/state` ten times a second. No WebSocket and no JavaScript
  dependencies, so the whole frontend is about 70 lines.
  
| Script | What it does |
| --- | --- |
| `scripts/pull-models.sh [serial]` | Pulls both VLM model directories to `$VLM_MODELS_DIR`. Resumes cleanly: a model already present locally is skipped, and interrupted transfers land in a `.part` directory rather than being mistaken for complete. |
| `scripts/provision.sh` | For every board in `adb devices`: pushes any missing model, then replaces the app directory. Models already on a board are skipped, so re-running costs almost nothing. |

Worth knowing:

- `$VLM_MODELS_DIR` defaults to `~/arduino-workshop-models` and must stay **outside** the app
  folder — App Lab syncs the app folder to the board, and 11 GB of models should not go with it.
- `provision.sh` **replaces** `/home/arduino/ArduinoApps/ai-smart-mirror` on each board. Local
  edits made on a board are lost.
- Only `app.yaml`, `README.md`, `python/`, `assets/`, `sketch/` and `scripts/` are pushed, so
  the `.cache` venv and build output stay put.
- Both scripts run as the `arduino` user, which owns both directories — no root needed.
- Restart App Lab on each board afterwards so it notices the new models.


