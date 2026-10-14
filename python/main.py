# AI Smart Mirror
#
# An image classification model watches the camera. When it sees the class you
# picked in the web UI, the mirror sends the current camera frame to the local
# vision model and shows its answer. The trigger class and the prompt are both
# edited in the browser, so the same app works with any Edge Impulse model.

import time
from threading import Lock, Thread

from fastapi.responses import StreamingResponse

from arduino.app_bricks.video_imageclassification import VideoImageClassification
from arduino.app_bricks.vlm import VisionLanguageModel
from arduino.app_bricks.web_ui import WebUI
from arduino.app_peripherals.camera import Camera
from arduino.app_utils import App, Logger
from arduino.app_utils.image import compressed_to_jpeg

logger = Logger("AISmartMirror")

CONFIDENCE = 0.5  # a class counts as detected above this score
HOLD_SEC = 1.0  # the class must stay visible this long before the mirror fires
GRACE_SEC = 0.5  # the class may flicker out for this long without losing the hold
COOLDOWN_SEC = 15  # pause between two mirror answers
CLEAR_SEC = 0.5  # a different class held this long cancels the cooldown
# Classes that mean "nothing interesting here", so the mirror does not start armed on them.
IDLE_LABELS = ("background", "unknown")
DEFAULT_PROMPT = (
    "You are a smart mirror. Look at the person in front of you, say one friendly "
    "sentence about what they are wearing and then give one short styling tip."
)

# Everything the web UI shows and edits lives in this dictionary.
state = {
    "prompt": DEFAULT_PROMPT,
    "trigger": "",  # the class that wakes the mirror, set from the model's classes
    "detected": {},  # what the model sees right now, as {"label": confidence, ...}
    "labels": [],  # the model's classes, offered in the UI
    "hold": 0.0,  # how far through the hold the trigger class is, from 0 to 1
    "status": "waiting",  # waiting | thinking | answered
    "answer": "",
}

ui = WebUI()
vlm = VisionLanguageModel(temperature=0.4, max_tokens=120)
camera = Camera(resolution=(640, 480), fps=30)
# debounce_sec=0 reports every classification, which keeps the hold timer smooth.
classifier = VideoImageClassification(camera=camera, confidence=CONFIDENCE, debounce_sec=0.0)

to_jpeg = compressed_to_jpeg()
frame_lock = Lock()
vlm_lock = Lock()  # the model server answers one request at a time
latest_frame: bytes | None = None
seen_since = 0.0  # when the trigger class first appeared, 0 if it is not in view
last_seen = 0.0  # the last time the trigger class was in view
other_since = 0.0  # when a class other than the trigger first appeared
ready_at = 0.0  # triggers are ignored until this moment
labels_loaded = False  # True once the model announced its own class list
trigger_chosen = False  # True once the trigger was picked in the web UI
warm_up_started = False  # True once the vision model has been given its throwaway question


def load_labels():
    """Read the model's own class list, which the brick learns from the runner.

    The Edge Impulse runner announces the loaded model when the brick connects to it,
    a second or two after startup, so this keeps looking until the list arrives. The
    announced list is the complete one, so it replaces any classes picked up from
    detections in the meantime.
    """
    global labels_loaded

    if labels_loaded:
        return

    model_info = getattr(classifier, "_model_info", None)
    labels = sorted(getattr(model_info, "labels", None) or [])
    if not labels:
        return

    labels_loaded = True
    state["labels"] = labels
    # Keep the class the user picked, replace anything guessed from early detections.
    if not trigger_chosen or state["trigger"] not in labels:
        state["trigger"] = default_trigger(labels)
    logger.info(f"Model classes: {', '.join(labels)}")


def default_trigger(labels: list[str]) -> str:
    """Pick the class the mirror starts armed on.

    Most classifiers have an idle class for "no subject in view", and starting on it
    would fire the mirror at nothing, so the first real class wins when there is one.
    """
    for label in labels:
        if label.strip().lower() not in IDLE_LABELS:
            return label

    return labels[0]


def keep_latest_frame():
    """Store the newest camera frame as JPEG, for the mirror image and the model."""
    global latest_frame

    if not camera.is_started():  # the classification brick starts the camera
        return

    frame = camera.capture()
    if frame is None:
        return

    with frame_lock:
        latest_frame = to_jpeg(frame).tobytes()


def on_classification(results: dict):
    """Called by the classification brick with {"label": confidence, ...}."""
    global seen_since, last_seen, other_since, ready_at

    now = time.monotonic()
    state["detected"] = results

    # Safety net: if the runner never announced its classes, collect them as they appear
    # and arm the mirror on the first one, so the app still works with such a model.
    if not labels_loaded:
        for label in results:
            if label not in state["labels"]:
                state["labels"] = sorted(state["labels"] + [label])
        if not state["trigger"] and state["labels"]:
            state["trigger"] = default_trigger(state["labels"])

    # Seeing a different class for CLEAR_SEC cuts the cooldown short, so stepping out
    # of view and back arms the mirror again without waiting for COOLDOWN_SEC.
    if state["status"] == "answered" and results and state["trigger"] not in results:
        if other_since == 0.0:
            other_since = now
        if now - other_since >= CLEAR_SEC:
            ready_at = 0.0
    else:
        other_since = 0.0

    # Arm the mirror again once the cooldown has passed, keeping the answer on screen.
    if state["status"] == "answered" and now >= ready_at:
        state["status"] = "waiting"

    # Nothing to count while the mirror is answering or cooling down.
    if state["status"] != "waiting" or now < ready_at:
        seen_since = 0.0
        state["hold"] = 0.0
        return

    # The trigger class has to stay in view for HOLD_SEC before the mirror fires.
    # Classification flickers, so short gaps up to GRACE_SEC do not reset the hold.
    if state["trigger"] in results:
        last_seen = now
        if seen_since == 0.0:
            seen_since = now
    elif now - last_seen > GRACE_SEC:
        seen_since = 0.0

    if seen_since == 0.0:
        state["hold"] = 0.0
        return

    state["hold"] = min((now - seen_since) / HOLD_SEC, 1.0)
    if state["hold"] == 1.0:
        wake_mirror()


def wake_mirror():
    """Send the current camera frame to the vision model."""
    global seen_since

    seen_since = 0.0  # the class has to be held again for the next answer
    state["hold"] = 0.0

    with frame_lock:
        frame = latest_frame

    if frame is None:
        return

    state["status"] = "thinking"
    # The model takes a few seconds, so let it answer off the classification thread.
    Thread(target=answer, args=(frame,), daemon=True).start()


def ask_mirror(prompt: str, frame: bytes) -> str:
    """Put one frame and one prompt to the vision model, one request at a time."""
    with vlm_lock:
        return vlm.chat(message=prompt, images=[frame]).strip()


def is_echo(reply: str, prompt: str) -> bool:
    """True if the model handed the prompt back instead of describing the frame."""
    head = prompt.strip()[:40].lower()
    return bool(head) and reply.strip().lower().startswith(head)


def warm_up(frame: bytes):
    """Spend the model's cold first answer on a question nobody sees.

    The local model server loads on its first request, which takes about fifteen
    seconds, and it answers that first request with the prompt itself rather than a
    description. Doing it at startup keeps both out of the mirror.
    """
    try:
        ask_mirror("Reply with OK.", frame)
        logger.info("The mirror is warmed up.")
    except Exception as exc:
        logger.warning(f"Could not warm up the mirror: {exc}")


def answer(frame: bytes):
    global ready_at

    logger.info(f"Triggered by '{state['trigger']}', asking the mirror...")
    prompt = state["prompt"]
    try:
        reply = ask_mirror(prompt, frame)
        if is_echo(reply, prompt):
            # The model server does this on its very first request, so ask once more.
            logger.warning("The mirror repeated the prompt, asking again...")
            reply = ask_mirror(prompt, frame)
        state["answer"] = reply
    except Exception as exc:
        logger.exception(f"The mirror could not answer: {exc}")
        state["answer"] = "The mirror could not answer. Please try again."

    # Start the cooldown before publishing the answer, so the mirror cannot be
    # re-armed for a moment in between.
    ready_at = time.monotonic() + COOLDOWN_SEC
    state["status"] = "answered"


def update_settings(settings: dict):
    """The web UI posts the trigger class and the prompt whenever they change."""
    global seen_since, trigger_chosen

    state["prompt"] = settings.get("prompt", state["prompt"])

    trigger = settings.get("trigger", state["trigger"])
    if trigger:
        trigger_chosen = True
    if trigger != state["trigger"]:
        state["trigger"] = trigger
        state["status"] = "waiting"
        state["answer"] = ""
        state["hold"] = 0.0
        seen_since = 0.0
        logger.info(f"Mirror will now trigger on '{trigger}'")

    return state


def mirror_stream():
    """MJPEG stream of the camera, shown as the mirror image in the browser."""

    def frames():
        while True:
            with frame_lock:
                frame = latest_frame
            if frame is not None:
                yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
            time.sleep(0.05)

    return StreamingResponse(frames(), media_type="multipart/x-mixed-replace; boundary=frame")


classifier.on_detect_all(on_classification)

ui.expose_api("GET", "/state", lambda: state)
ui.expose_api("POST", "/settings", update_settings)
ui.expose_api("GET", "/stream", mirror_stream)

def start_warm_up():
    """Warm the vision model up once, as soon as there is a frame to send it."""
    global warm_up_started

    if warm_up_started:
        return

    with frame_lock:
        frame = latest_frame

    if frame is None:
        return

    warm_up_started = True
    Thread(target=warm_up, args=(frame,), daemon=True).start()


def loop():
    """Runs over and over on the main thread while the app is alive."""
    load_labels()
    keep_latest_frame()
    start_warm_up()


App.run(user_loop=loop)
