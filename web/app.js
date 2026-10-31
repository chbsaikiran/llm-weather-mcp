const $ = (selector) => document.querySelector(selector);
const form = $('#form'), question = $('#question'), conversation = $('#conversation');
let busy = false, currentTurn = null, currentAnswer = null;
const surfaces = new Map();

// Google Material Web is progressive enhancement: the app remains usable if the CDN fails.
async function enhanceMaterial() {
  try {
    await import('https://esm.run/@material/web@2.3.0/all.js');
    const send = document.createElement('md-filled-button');
    send.id = 'send'; send.type = 'button'; send.textContent = 'Ask ↗';
    send.setAttribute('aria-label', 'Send question');
    send.addEventListener('click', () => form.requestSubmit());
    send.disabled = busy;
    $('#send').replaceWith(send);
    const reset = document.createElement('md-outlined-button');
    reset.id = 'reset'; reset.textContent = '＋ New conversation';
    reset.addEventListener('click', resetConversation);
    reset.disabled = busy;
    $('#reset').replaceWith(reset);
  } catch { /* Native buttons provide the offline fallback. */ }
}
enhanceMaterial();

function node(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}
function setBusy(value) {
  busy = value;
  $('#send').disabled = value; $('#reset').disabled = value;
  $('#demo').disabled = value; question.disabled = value;
  document.querySelectorAll('.suggestion').forEach(button => button.disabled = value);
  $('#progress').hidden = !value;
}
function showError(message) { $('#error').textContent = message; $('#error').hidden = false; }

// Deliberately small A2UI v0.8 subset: literal Text, Row, Column, Card.
// Components are allowlisted. No HTML strings, eval, scripts, or arbitrary URLs.
function renderComponent(id, components, visited = new Set()) {
  if (visited.has(id) || visited.size > 100) throw new Error('Invalid component tree');
  const next = new Set(visited); next.add(id);
  const definition = components.get(id)?.component;
  if (!definition) throw new Error('Missing component');
  const [kind, props] = Object.entries(definition)[0];
  if (kind === 'Text') {
    const hint = ['h1','h2','h3','caption','body'].includes(props.usageHint) ? props.usageHint : 'body';
    return node('p', `a2ui-text ${hint}`, props.text.literalString);
  }
  if (kind === 'Card') {
    const card = node('div', 'a2ui-card');
    card.append(renderComponent(props.child, components, next)); return card;
  }
  if (kind === 'Row' || kind === 'Column') {
    const group = node('div', `a2ui-${kind.toLowerCase()}`);
    for (const child of props.children.explicitList) group.append(renderComponent(child, components, next));
    return group;
  }
  throw new Error('Unsupported UI component');
}
function a2ui(message) {
  if (message.surfaceUpdate) {
    const {surfaceId, components} = message.surfaceUpdate;
    surfaces.set(surfaceId, new Map(components.map(c => [c.id, c])));
  }
  if (message.beginRendering) {
    const {surfaceId, root} = message.beginRendering;
    const region = node('div', 'surface');
    region.append(renderComponent(root, surfaces.get(surfaceId)));
    const cities = [...surfaces.get(surfaceId).values()]
      .filter(c => c.component.Text?.usageHint === 'h2')
      .map(c => c.component.Text.text.literalString);
    const actions = node('div', 'surface-actions');
    for (const city of cities) {
      for (const [label, prompt] of [['5-day outlook', `Show the next 5 days of weather in ${city}`],
                                    ['Next 12 hours', `Show the next 12 hours of weather in ${city}`]]) {
        const button = node('button', 'followup', cities.length > 1 ? `${city} · ${label}` : label);
        button.addEventListener('click', () => submit(prompt));
        actions.append(button);
      }
    }
    region.append(actions);
    currentTurn.append(region);
  }
}
function eventReceived(event) {
  switch (event.type) {
    case 'RUN_STARTED': $('#progress-text').textContent = 'Understanding your question…'; break;
    case 'TOOL_CALL_START': $('#progress-text').textContent = 'Checking the weather with Open-Meteo…'; break;
    case 'TOOL_CALL_RESULT': $('#progress-text').textContent = 'Putting your outlook together…'; break;
    case 'CUSTOM':
      if (event.name === 'a2ui') a2ui(event.value);
      if (event.name === 'demo') currentTurn.append(node('div', 'demo-badge', 'DEMO · Illustrative data, not a live forecast'));
      break;
    case 'TEXT_MESSAGE_START':
      currentAnswer = node('div', 'answer');
      currentAnswer.setAttribute('aria-live', 'polite');
      currentTurn.append(currentAnswer); break;
    case 'TEXT_MESSAGE_CONTENT': currentAnswer.append(document.createTextNode(event.delta)); break;
    case 'RUN_ERROR': throw new Error(event.message);
  }
}
async function submit(message) {
  if (busy || !message.trim()) return;
  const demo = $('#demo').checked;
  setBusy(true); $('#error').hidden = true; $('#welcome').hidden = true;
  $('#progress-text').textContent = demo ? 'Preparing your preview…' : 'Understanding your question…';
  currentTurn = node('article', 'turn');
  const user = node('div', 'user-message');
  user.append(node('span', 'avatar', 'YOU'), node('span', '', message));
  currentTurn.append(user); conversation.append(currentTurn);
  question.value = ''; currentAnswer = null;
  currentTurn.scrollIntoView({behavior:'smooth', block:'start'});
  let finished = false;
  try {
    const response = await fetch(demo ? '/api/demo' : '/api/chat', {
      method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({message})
    });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(typeof body.detail === 'string' ? body.detail : 'Could not send your question. Please retry.');
    }
    const reader = response.body.getReader(), decoder = new TextDecoder();
    let buffer = '';
    try {
      while (true) {
        const {value, done} = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, {stream:true});
        let boundary;
        while ((boundary = buffer.indexOf('\n\n')) >= 0) {
          const frame = buffer.slice(0, boundary); buffer = buffer.slice(boundary+2);
          const payload = frame.split('\n').filter(line => line.startsWith('data:')).map(line => line.slice(5).trimStart()).join('\n');
          if (payload) {
            const event = JSON.parse(payload);
            eventReceived(event);
            if (event.type === 'RUN_FINISHED') finished = true;
          }
        }
      }
    } finally { await reader.cancel(); reader.releaseLock(); }
    if (!finished) throw new Error('Connection interrupted. Please try your question again.');
  } catch (error) { showError(error.message); question.value = message; }
  finally { surfaces.clear(); setBusy(false); question.focus(); }
}
async function resetConversation() {
  if (busy) return;
  try {
    const response = await fetch('/api/reset', {method:'POST'});
    if (!response.ok) throw new Error('Could not reset this conversation. Please retry.');
    conversation.replaceChildren(); surfaces.clear(); $('#welcome').hidden = false;
    $('#error').hidden = true; question.value = ''; question.focus();
  } catch (error) { showError(error.message); }
}
form.addEventListener('submit', event => { event.preventDefault(); submit(question.value.trim()); });
question.addEventListener('keydown', event => {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); form.requestSubmit(); }
});
$('#reset').addEventListener('click', resetConversation);
document.querySelectorAll('.suggestion').forEach(button => button.addEventListener('click', () => submit(button.dataset.query)));
// Changing between illustrative data and real weather starts a separate visual conversation.
$('#demo').addEventListener('change', resetConversation);
