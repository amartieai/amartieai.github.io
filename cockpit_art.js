/* ============================================================
   COCKPIT ART PASS — scene switcher
   Freeze-safe: pure DOM, no fetch, no loops. Injects a scene
   selector into the header, sets body[data-scene], persists
   the choice. Scenes are styled entirely in cockpit_art.css.
   ============================================================ */
(function () {
  'use strict';
  var SCENES = [
    { id: 'bridge',  icon: '\u25C6', title: 'Spaceship bridge — command blue & gold' },
    { id: 'kitchen', icon: '\u2668', title: 'Kitchen — warm copper & stainless' },
    { id: 'jungle',  icon: '\u2740', title: 'Jungle — bioluminescent canopy' },
    { id: 'beach',   icon: '\u26F1', title: 'Beach — dusk horizon, coral & surf' }
  ];
  var KEY = 'cockpit-scene';

  function current() {
    try {
      var m = location.search.match(/[?&]scene=([a-z]+)/);
      if (m) return m[1];
    } catch (e) {}
    try { return localStorage.getItem(KEY) || 'bridge'; } catch (e) { return 'bridge'; }
  }
  function apply(id) {
    document.body.setAttribute('data-scene', id);
    try { localStorage.setItem(KEY, id); } catch (e) {}
    var btns = document.querySelectorAll('.scene-btn');
    for (var i = 0; i < btns.length; i++) {
      btns[i].classList.toggle('active', btns[i].getAttribute('data-scene') === id);
    }
  }

  function init() {
    if (document.getElementById('scene-switch')) return;
    var host = document.getElementById('refresh-meta') || document.querySelector('header');
    if (!host) return;
    var box = document.createElement('div');
    box.className = 'scene-switch';
    box.id = 'scene-switch';
    box.title = 'Cockpit scene — the room changes, the work does not';
    var lbl = document.createElement('span');
    lbl.className = 'sc-label';
    lbl.textContent = 'scene';
    box.appendChild(lbl);
    SCENES.forEach(function (s) {
      var b = document.createElement('button');
      b.className = 'scene-btn';
      b.setAttribute('data-scene', s.id);
      b.title = s.title;
      b.textContent = s.icon;
      b.addEventListener('click', function () { apply(s.id); });
      box.appendChild(b);
    });
    host.insertBefore(box, host.firstChild);
    apply(current());
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
