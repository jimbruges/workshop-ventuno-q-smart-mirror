const detectedList = document.querySelector('#detected');
const triggerSelect = document.querySelector('#trigger');
const holdBar = document.querySelector('#holdBar');
const promptInput = document.querySelector('#prompt');
const statusText = document.querySelector('#status');
const answerText = document.querySelector('#answer');

let promptLoaded = false;
let promptTimer = null;

// Send the trigger class and the prompt to the board.
const save = () =>
  fetch('/settings', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ trigger: triggerSelect.value, prompt: promptInput.value }),
  });

// Picking a class applies right away, typing applies once you pause.
triggerSelect.onchange = save;
promptInput.oninput = () => {
  clearTimeout(promptTimer);
  promptTimer = setTimeout(save, 600);
};

// Ask the board for its state ten times a second and show it. The hold only
// lasts a second, so polling any slower makes the bar jump instead of fill.
async function refresh() {
  const state = await (await fetch('/state')).json();

  renderDetected(state.detected, state.trigger);
  updateTriggers(state.labels, state.trigger);
  holdBar.style.width = `${state.hold * 100}%`;

  if (!promptLoaded) {
    promptInput.value = state.prompt;
    promptLoaded = true;
  }

  statusText.textContent = {
    waiting: `Waiting for "${state.trigger}"...`,
    thinking: 'The mirror is looking at you...',
    answered: 'The mirror says:',
  }[state.status];
  answerText.textContent = state.answer;

  // Dim the mirror and show the spinner while the vision model is generating.
  document.body.classList.toggle('thinking', state.status === 'thinking');
}

// Show what the classification model sees right now, highest confidence first.
function renderDetected(detected, trigger) {
  const classes = Object.entries(detected).sort((a, b) => b[1] - a[1]);

  detectedList.innerHTML = classes.length
    ? classes
        .map(
          ([label, confidence]) =>
            `<li class="${label === trigger ? 'is-trigger' : ''}">
               <span>${label}</span><b>${Math.round(confidence * 100)}%</b>
             </li>`,
        )
        .join('')
    : '<li class="empty">Nothing detected</li>';
}

// Offer every class the model has reported so far as a possible trigger.
function updateTriggers(labels, selected) {
  if (labels.length === triggerSelect.options.length) return;

  const current = triggerSelect.value || selected;
  triggerSelect.innerHTML = labels.map(label => `<option>${label}</option>`).join('');
  triggerSelect.value = current;
}

setInterval(refresh, 100);
