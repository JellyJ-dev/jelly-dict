// One media element per text target. Anki's native AV queue is not used.
(function () {
  var root = (document.currentScript && document.currentScript.closest('.jellydict-card')) ||
    document.querySelector('.jellydict-card');
  if (!root) return;
  if (window.jellyDictAudioCleanup) window.jellyDictAudioCleanup();
  var disposed = false;
  var toggle = root.querySelector('#tts-toggle');

  function persisted() {
    try { return localStorage.getItem('jellydict.tts') !== '0'; }
    catch (e) { return true; }
  }

  function allowed() { return toggle ? toggle.checked : persisted(); }

  function stop() {
    root.querySelectorAll('audio').forEach(function (audio) {
      audio.pause();
      try { audio.currentTime = 0; } catch (e) {}
    });
  }

  function playBank(id) {
    if (disposed || !root.isConnected || !allowed()) return;
    var bank = document.getElementById(id);
    if (!bank || !root.contains(bank)) return;
    var audio = bank.querySelector('audio');
    if (!audio) return;
    stop();
    try {
      var pending = audio.play();
      if (pending && pending.catch) pending.catch(function () {});
    } catch (e) {}
  }

  function activate(event) {
    if (event.type === 'keydown' && event.key !== 'Enter' && event.key !== ' ') return;
    var target = event.target.closest('[data-audio-bank]');
    if (!target || !root.contains(target)) return;
    event.preventDefault();
    event.stopPropagation();
    playBank(target.getAttribute('data-audio-bank'));
  }

  function changeToggle() {
    try { localStorage.setItem('jellydict.tts', toggle.checked ? '1' : '0'); }
    catch (e) {}
    if (!toggle.checked) stop();
  }

  if (toggle) {
    toggle.checked = persisted();
    toggle.addEventListener('change', changeToggle);
  }
  root.addEventListener('click', activate);
  root.addEventListener('keydown', activate);
  window.addEventListener('pagehide', stop);

  // Desktop/mobile clients may replace card HTML inside the same webview.
  var observer = new MutationObserver(function () {
    if (!root.isConnected) cleanup();
  });
  observer.observe(document.documentElement, {childList: true, subtree: true});
  function cleanup() {
    if (disposed) return;
    disposed = true;
    stop();
    observer.disconnect();
    root.removeEventListener('click', activate);
    root.removeEventListener('keydown', activate);
    window.removeEventListener('pagehide', stop);
    if (toggle) toggle.removeEventListener('change', changeToggle);
    if (window.jellyDictAudioCleanup === cleanup) window.jellyDictAudioCleanup = null;
  }
  window.jellyDictAudioCleanup = cleanup;

  // Explicit word-only autoplay preference; examples are always click-only.
  if (root.getAttribute('data-auto-word') === '1') playBank('word-audio');
})();
