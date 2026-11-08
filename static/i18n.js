(() => {
  'use strict';
  const messages = JSON.parse(document.getElementById('interface-messages')?.textContent || '{}');
  const language = document.documentElement.lang;
  const t = (key, values = {}) => (messages[key] ?? key).replace(/\{(\w+)\}/g, (match, name) => String(values[name] ?? match));
  class InterfaceError extends Error {}
  window.XLDBI18n = {
    t,
    error: message => new InterfaceError(message),
    message: (error, fallback) => error instanceof InterfaceError ? error.message : t(fallback),
    fetch: (url, options = {}) => {
      const headers = new Headers(options.headers);
      headers.set('X-Interface-Language', language);
      return window.fetch(url, {...options, headers});
    },
  };
  document.addEventListener('htmx:configRequest', event => {
    event.detail.headers['X-Interface-Language'] = language;
  });
  // Browser validation follows the page language, even if the OS/browser is English.
  document.addEventListener('invalid', event => {
    const input = event.target;
    if (input.validity.valueMissing) input.setCustomValidity(t('Please fill in this field.'));
    else if (input.validity.patternMismatch || input.validity.typeMismatch || (input.validity.badInput && input.type !== 'number')) {
      input.setCustomValidity(t('Use the format shown in the instructions.'));
    } else if (input.validity.tooLong) {
      input.setCustomValidity(t('Use no more than {count} characters.', {count:input.maxLength}));
    } else if (input.validity.rangeUnderflow || input.validity.rangeOverflow || input.validity.stepMismatch || input.validity.badInput) {
      input.setCustomValidity(t('Enter a valid number within the indicated limits.'));
    }
  }, true);
  document.addEventListener('input', event => event.target.setCustomValidity?.(''));
  document.addEventListener('reset', event => {
    for (const input of event.target.elements || []) input.setCustomValidity?.('');
  });
})();
