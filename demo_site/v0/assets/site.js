/* Zephyr Compute — shared site behaviour (nav, cookie consent, custom select, API helpers) */
(function () {
  var body = document.body;
  var root = body.getAttribute('data-root') || '';
  var page = body.getAttribute('data-page') || '';
  var ZC = (window.ZC = window.ZC || {});

  // ---- attribution: forward ?abtract_ep=<id> to the site API so events can be attributed
  var params = new URLSearchParams(location.search);
  ZC.ep = params.get('abtract_ep');
  ZC.apiUrl = function (name) {
    var url = root + 'api/' + name;
    if (ZC.ep) url += '?abtract_ep=' + encodeURIComponent(ZC.ep);
    return url;
  };
  if (ZC.ep) {
    Array.prototype.forEach.call(document.querySelectorAll('form[action]'), function (f) {
      var a = f.getAttribute('action');
      if (a.indexOf('api/') !== -1) {
        f.setAttribute('action', a + (a.indexOf('?') !== -1 ? '&' : '?') + 'abtract_ep=' + encodeURIComponent(ZC.ep));
      }
    });
  }
  ZC.postEvent = function (name, payload) {
    var headers = { 'Content-Type': 'application/json' };
    if (ZC.ep) headers['X-Abtract-Episode'] = ZC.ep;
    return fetch(ZC.apiUrl('event'), {
      method: 'POST',
      headers: headers,
      body: JSON.stringify({ name: name, payload: payload })
    });
  };

  // ---- main navigation: rendered client-side once the page has settled
  var NAV = [
    ['Pricing', 'pricing.html', 'pricing'],
    ['Docs', 'docs/index.html', 'docs'],
    ['Regions', 'docs/regions.html', 'regions'],
    ['Changelog', 'changelog.html', 'changelog'],
    ['About', 'about.html', 'about']
  ];
  function renderNav() {
    var nav = document.getElementById('main-nav');
    if (!nav) return;
    var html = NAV.map(function (item) {
      var cls = page === item[2] ? ' class="active"' : '';
      return '<a href="' + root + item[1] + '"' + cls + '>' + item[0] + '</a>';
    }).join('');
    html += '<a class="btn btn-primary btn-sm" href="' + root + 'waitlist.html">Join the waitlist</a>';
    nav.innerHTML = html;
  }
  setTimeout(renderNav, 800);

  // ---- cookie consent overlay (blocks the page until accepted)
  function hasConsent() {
    try { return localStorage.getItem('zc_consent') === '1'; } catch (e) { return false; }
  }
  function showConsent() {
    if (hasConsent()) return;
    var ov = document.createElement('div');
    ov.className = 'cookie-overlay';
    ov.id = 'cookie-overlay';
    ov.innerHTML =
      '<div class="cookie-modal" role="dialog" aria-modal="true" aria-labelledby="cookie-title">' +
      '<h2 id="cookie-title">We value your privacy</h2>' +
      '<p>Zephyr Compute uses cookies to keep you signed in, remember your preferences and understand how our site is used. ' +
      'By clicking &ldquo;Accept all&rdquo; you agree to the storing of cookies on your device.</p>' +
      '<div class="cookie-actions"><button type="button" class="btn btn-primary" id="cookie-accept">Accept all</button></div>' +
      '</div>';
    document.body.appendChild(ov);
    document.getElementById('cookie-accept').addEventListener('click', function () {
      try { localStorage.setItem('zc_consent', '1'); } catch (e) {}
      ov.parentNode.removeChild(ov);
    });
  }
  showConsent();

  // ---- custom dropdown (.zc-select). Options are only inserted into the DOM when the menu is opened.
  ZC.initSelect = function (el, options, onChange) {
    var trigger = el.querySelector('.zc-select-trigger');
    var label = el.querySelector('.zc-select-label');
    var menu = el.querySelector('.zc-select-menu');
    var state = { value: null, label: null };
    function close() { el.classList.remove('open'); menu.hidden = true; }
    function open() {
      if (!menu.childElementCount) {
        options.forEach(function (opt) {
          var li = document.createElement('li');
          li.className = 'zc-option';
          li.setAttribute('role', 'option');
          li.setAttribute('data-value', opt.value);
          li.textContent = opt.label;
          li.addEventListener('click', function (e) { e.stopPropagation(); select(opt); close(); });
          menu.appendChild(li);
        });
      }
      el.classList.add('open');
      menu.hidden = false;
    }
    function select(opt) {
      state.value = opt.value;
      state.label = opt.label;
      el.setAttribute('data-value', opt.value);
      label.textContent = opt.label;
      el.classList.add('has-value');
      Array.prototype.forEach.call(menu.querySelectorAll('.zc-option'), function (li) {
        li.classList.toggle('selected', li.getAttribute('data-value') === opt.value);
      });
      if (onChange) onChange(opt);
    }
    trigger.addEventListener('click', function (e) {
      e.stopPropagation();
      if (el.classList.contains('open')) close(); else open();
    });
    trigger.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); trigger.click(); }
    });
    document.addEventListener('click', close);
    return state;
  };
})();
