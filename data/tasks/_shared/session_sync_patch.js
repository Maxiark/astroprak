/**
 * Патч синхронизации ключа сессии и разблокировки кнопки при ошибке сдачи (Сценарии №6, №8, №24).
 * Автоматически подключается или встраивается в legacy_widget.js.
 */
(function () {
  window.addEventListener('message', function (event) {
    if (!event.data || typeof event.data !== 'object') return;

    // Обновление кода сессии на лету и при успешной сдаче
    if (event.data.type === 'ASTROSITE_SESSION_UPDATE' || event.data.type === 'ASTROSITE_SUBMIT_SUCCESS') {
      if (event.data.session_code) {
        window.__astrositeSessionCode = event.data.session_code;
        var codeEls = document.querySelectorAll('[data-session-code], #lw-session-code, .lw-session-code');
        codeEls.forEach(function (el) {
          el.textContent = event.data.session_code;
        });
      }
    }

    // Разблокировка кнопки сдачи при ошибке (исправление Сценария №8)
    if (event.data.type === 'ASTROSITE_SUBMIT_ERROR') {
      var btns = document.querySelectorAll('.lw-submit-btn, #btn-submit, #btn-final-submit, button[type="submit"]');
      btns.forEach(function (btn) {
        btn.disabled = false;
        if (btn.textContent && btn.textContent.indexOf('Проверка') !== -1) {
          btn.textContent = 'Сдать решение';
        }
      });
    }
  });
})();
