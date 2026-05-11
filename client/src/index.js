const blessed = require('blessed');
const api = require('./api');

const username = process.env.TFG_USER || 'alice';
let activeChannel = api.getChannels()[0];

const screen = blessed.screen({
  smartCSR: true,
  title: 'TFG Chat — bulletin board E2EE',
  fullUnicode: true,
});

// ---- Layout -----------------------------------------------------------------
//
// ┌─Canales──┬─#general────────────────────┐
// │ #general │ alice: hola                 │
// │ #random  │ bob:   qué tal               │
// │ #dev     │ alice: probando E2EE         │
// │          │                             │
// │─Users────│                             │
// │ ● alice  │                             │
// │ ● bob    │                             │
// │ ○ carol  │                             │
// │          ├─────────────────────────────│
// │          │ > _                         │
// └──────────┴─────────────────────────────┘
//
// -----------------------------------------------------------------------------

const channelsList = blessed.list({
  parent: screen,
  label: ' Canales ',
  top: 0,
  left: 0,
  width: 24,
  height: '50%',
  border: { type: 'line' },
  style: {
    fg: 'white',
    border: { fg: '#a54242' },
    selected: { bg: '#a54242', fg: 'white' },
    label: { fg: '#a54242' },
  },
  keys: true,
  vi: true,
  mouse: true,
  items: api.getChannels(),
});

const usersList = blessed.list({
  parent: screen,
  label: ' Users ',
  top: '50%',
  left: 0,
  width: 24,
  height: '50%-1',
  border: { type: 'line' },
  style: {
    fg: 'white',
    border: { fg: '#a54242' },
    selected: { bg: '#a54242', fg: 'white' },
    label: { fg: '#a54242' },
  },
  keys: true,
  vi: true,
  mouse: true,
  items: [],
});

const messages = blessed.log({
  parent: screen,
  label: ` ${activeChannel} `,
  top: 0,
  left: 24,
  right: 0,
  height: '100%-4',
  border: { type: 'line' },
  style: {
    fg: 'white',
    border: { fg: '#de935f' },
    label: { fg: '#de935f' },
  },
  scrollable: true,
  alwaysScroll: true,
  scrollbar: { ch: '│', style: { fg: '#de935f' } },
  mouse: true,
  tags: true,
});

const input = blessed.textbox({
  parent: screen,
  bottom: 1,
  left: 24,
  right: 0,
  height: 3,
  border: { type: 'line' },
  style: {
    fg: 'white',
    border: { fg: '#de935f' },
  },
  inputOnFocus: true,
});

const status = blessed.box({
  parent: screen,
  bottom: 0,
  left: 0,
  width: '100%',
  height: 1,
  tags: true,
  style: { fg: 'white', bg: '#a54242' },
});

const exitButton = blessed.button({
  parent: screen,
  top: 0,
  right: 2,
  width: 9,
  height: 1,
  align: 'center',
  content: '[ Salir ]',
  mouse: true,
  keys: true,
  shrink: true,
  style: {
    fg: 'white',
    bg: '#a54242',
    hover: { bg: '#de935f', fg: 'black' },
    focus: { bg: '#de935f', fg: 'black' },
  },
});

// ---- Render -----------------------------------------------------------------

function renderStatus() {
  status.setContent(
    ` {bold}${username}{/bold}  ·  ${activeChannel}  ·  Tab=foco  Enter=enviar  Ctrl+C / botón [Salir]=salir `
  );
}

function quit() {
  screen.destroy();
  process.exit(0);
}

function renderMessages() {
  messages.setLabel(` ${activeChannel} `);
  messages.setContent('');
  for (const m of api.getMessages(activeChannel)) {
    const color = m.from === username ? '#de935f-fg' : '#a54242-fg';
    messages.log(`{${color}}${m.from}{/}: ${m.text}`);
  }
}

function renderUsers() {
  const users = api.getUsers(activeChannel);
  usersList.setItems(
    users.map((u) =>
      u.online ? `{#de935f-fg}●{/} ${u.name}` : `{gray-fg}○{/} ${u.name}`
    )
  );
}

function renderAll() {
  renderStatus();
  renderMessages();
  renderUsers();
  screen.render();
}

// ---- Interactions -----------------------------------------------------------

channelsList.on('select', (item) => {
  activeChannel = item.getText();
  renderAll();
});

input.key('enter', () => {
  const text = input.getValue().trim();
  if (text) {
    api.sendMessage(activeChannel, { from: username, text });
    renderMessages();
  }
  input.clearValue();
  input.focus();
  screen.render();
});

// Tab cycles focus: channels -> users -> input -> channels
screen.key(['tab'], () => {
  if (screen.focused === channelsList) usersList.focus();
  else if (screen.focused === usersList) input.focus();
  else channelsList.focus();
  screen.render();
});

screen.key(['C-c'], quit);
screen.key(['q'], () => {
  // Salir con 'q' solo si el foco no está en el input (para no interferir al escribir)
  if (screen.focused !== input) quit();
});

// El textbox en modo readInput se traga Ctrl+C — lo enganchamos también aquí
input.key('C-c', quit);

// Botón [Salir]: click o Enter cuando tiene foco
exitButton.on('press', quit);

// ---- Boot -------------------------------------------------------------------

channelsList.select(0);
renderAll();
input.focus();

// Polling sencillo. Cuando el api.js hable con el core Java, esto ya tirará HTTP real.
setInterval(() => {
  renderMessages();
  renderUsers();
  screen.render();
}, 2000);
