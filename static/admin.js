/* Optional enhancements; the administrator forms also work without JavaScript. */
(() => {
  'use strict';
  const data = document.getElementById('import-name-suggestions');
  if (!data) return;
  const suggestions = new Map(Object.entries(JSON.parse(data.textContent)));
  const sheet = document.getElementById('sheet'), name = document.getElementById('name');
  const defaultName = document.getElementById('default-name');
  let previous = suggestions.get(sheet.value);
  sheet.addEventListener('change', () => {
    const suggestion = suggestions.get(sheet.value);
    if (suggestion !== undefined && (!name.value.trim() || name.value === previous)) {
      name.value = suggestion;
      name.setCustomValidity('');
    }
    previous = suggestion;
    defaultName.value = suggestion ?? '';
  });
})();
