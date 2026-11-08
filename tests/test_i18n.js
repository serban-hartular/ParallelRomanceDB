/* Translation helpers and browser failures, without a browser/server dependency. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {test} = require('node:test');
const root = path.resolve(__dirname, '..');
const catalog = JSON.parse(fs.readFileSync(path.join(root, 'translations.json'), 'utf8'));
function interfaceFor(language) {
  const events = {}, calls = [], window = {fetch: (url, options) => {calls.push({url, options}); return Promise.resolve({ok:true});}};
  const document = {
    documentElement: {lang:language},
    getElementById: () => ({textContent:JSON.stringify(Object.fromEntries(Object.entries(catalog).map(([key, value]) => [key, value[language]])))}),
    addEventListener: (name, handler) => {events[name] = handler;},
  };
  vm.runInNewContext(fs.readFileSync(path.join(root, 'static/i18n.js'), 'utf8'), {window, document, Headers});
  return {...window.XLDBI18n, events, calls};
}
test('translated substitutions preserve literal names and text', () => {
  const ui = interfaceFor('ro');
  assert.equal(ui.t('Cancel'), 'Anulează');
  assert.equal(ui.t('Text for {column}', {column:'Search <script> {count}'}), 'Text pentru Search <script> {count}');
  assert.equal(interfaceFor('en').t('Cancel'), 'Cancel');
});
test('native network/JSON errors use the page language; application messages survive', () => {
  const ui = interfaceFor('ro');
  assert.equal(ui.message(new TypeError('Failed to fetch'), 'Could not reach the server.'), 'Serverul nu a putut fi contactat.');
  assert.equal(ui.message(new SyntaxError('Unexpected token'), 'Could not save. Please try again.'), 'Salvarea nu a reușit. Încercați din nou.');
  const validation = ui.error('Copiați textul nesalvat, apoi anulați și reîncărcați pagina.');
  assert.equal(ui.message(validation, 'Could not reach the server.'), validation.message);
});
test('fetch and htmx pin language without losing security headers or options', async () => {
  const ui = interfaceFor('ro');
  const signal = new AbortController().signal;
  await ui.fetch('/auth/login', {method:'POST', headers:{'X-CSRF-Token':'disposable-csrf'}, keepalive:true, signal});
  assert.equal(ui.calls[0].options.headers.get('X-Interface-Language'), 'ro');
  assert.equal(ui.calls[0].options.headers.get('X-CSRF-Token'), 'disposable-csrf');
  assert.equal(ui.calls[0].options.signal, signal);
  assert.equal(ui.calls[0].options.keepalive, true);
  const event = {detail:{headers:{'HX-Request':'true'}}};
  ui.events['htmx:configRequest'](event);
  assert.equal(event.detail.headers['X-Interface-Language'], 'ro');
  assert.equal(event.detail.headers['HX-Request'], 'true');
});
test('required, format, number, and length validation use editable Romanian messages', () => {
  const ui = interfaceFor('ro');
  for (const [validity, message] of [
    [{valueMissing:true}, 'Completați acest câmp.'],
    [{patternMismatch:true}, 'Folosiți formatul indicat în instrucțiuni.'],
    [{typeMismatch:true}, 'Folosiți formatul indicat în instrucțiuni.'],
    [{rangeUnderflow:true}, 'Introduceți un număr valid în limitele indicate.'],
    [{tooLong:true}, 'Folosiți cel mult 12 caractere.'],
  ]) {
    let displayed;
    const target = {validity, maxLength:12, setCustomValidity: text => {displayed = text;}};
    ui.events.invalid({target});
    assert.equal(displayed, message);
    ui.events.input({target});
    assert.equal(displayed, '');
    ui.events.invalid({target});
    ui.events.reset({target:{elements:[target]}});
    assert.equal(displayed, '');
  }
});
