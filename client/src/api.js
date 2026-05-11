// Cliente HTTP hacia el core Java.
// Mientras el core no existe, devolvemos datos en memoria para que la TUI funcione sola.
// Cuando el core Java esté listo, sustituiremos los mocks por fetch() a sus endpoints.

const CHANNELS = ['#general', '#random', '#dev'];

const USERS = {
  '#general': [
    { name: 'alice', online: true },
    { name: 'bob',   online: true },
    { name: 'carol', online: false },
  ],
  '#random': [
    { name: 'alice', online: true },
    { name: 'dave',  online: true },
  ],
  '#dev': [
    { name: 'alice', online: true },
    { name: 'bob',   online: true },
  ],
};

const MESSAGES = {
  '#general': [
    { from: 'alice', text: 'hola' },
    { from: 'bob',   text: 'qué tal' },
    { from: 'alice', text: 'probando E2EE' },
  ],
  '#random': [
    { from: 'dave', text: 'random vibes' },
  ],
  '#dev': [
    { from: 'bob', text: 'merge cuando puedas' },
  ],
};

function getChannels() {
  return CHANNELS.slice();
}

function getUsers(channel) {
  return (USERS[channel] || []).slice();
}

function getMessages(channel) {
  return (MESSAGES[channel] || []).slice();
}

function sendMessage(channel, msg) {
  if (!MESSAGES[channel]) MESSAGES[channel] = [];
  MESSAGES[channel].push(msg);
}

module.exports = { getChannels, getUsers, getMessages, sendMessage };
