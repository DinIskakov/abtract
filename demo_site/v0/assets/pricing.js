/* Pricing page: GPU rate card (canvas) + plan tabs */
(function () {
  var FONT = 'ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif';
  var GPUS = [
    { name: 'H100', memory: '80 GB HBM3', price: 3.95 },
    { name: 'A100', memory: '80 GB HBM2e', price: 2.78 },
    { name: 'L40S', memory: '48 GB GDDR6', price: 1.95 },
    { name: 'T4',   memory: '16 GB GDDR6', price: 0.59 }
  ];

  function drawRates() {
    var canvas = document.getElementById('gpu-rates');
    if (!canvas) return;
    var W = 720, headH = 52, rowH = 56, H = headH + rowH * GPUS.length;
    var dpr = window.devicePixelRatio || 1;
    canvas.width = W * dpr; canvas.height = H * dpr;
    canvas.style.width = W + 'px'; canvas.style.height = H + 'px';
    var ctx = canvas.getContext('2d');
    ctx.scale(dpr, dpr);
    ctx.textBaseline = 'middle';

    ctx.fillStyle = '#ffffff'; ctx.fillRect(0, 0, W, H);
    ctx.fillStyle = '#f6f7fb'; ctx.fillRect(0, 0, W, headH);
    ctx.strokeStyle = '#e5e7ee'; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(0, headH + 0.5); ctx.lineTo(W, headH + 0.5); ctx.stroke();

    var colGpu = 28, colMem = 260, right = W - 28;
    ctx.font = '600 12px ' + FONT; ctx.fillStyle = '#5b6478';
    ctx.textAlign = 'left';
    ctx.fillText('GPU', colGpu, headH / 2);
    ctx.fillText('MEMORY', colMem, headH / 2);
    ctx.textAlign = 'right';
    ctx.fillText('ON-DEMAND PRICE', right, headH / 2);

    GPUS.forEach(function (g, i) {
      var y = headH + rowH * i, cy = y + rowH / 2;
      if (i > 0) { ctx.beginPath(); ctx.moveTo(0, y + 0.5); ctx.lineTo(W, y + 0.5); ctx.stroke(); }
      ctx.textAlign = 'left';
      ctx.fillStyle = '#0f172a'; ctx.font = '700 18px ' + FONT;
      ctx.fillText('NVIDIA ' + g.name, colGpu, cy);
      ctx.fillStyle = '#5b6478'; ctx.font = '400 16px ' + FONT;
      ctx.fillText(g.memory, colMem, cy);
      ctx.textAlign = 'right';
      ctx.font = '400 15px ' + FONT; ctx.fillStyle = '#5b6478';
      var unit = '/ GPU-hour';
      ctx.fillText(unit, right, cy);
      var w = ctx.measureText(unit).width;
      ctx.font = '700 20px ' + FONT; ctx.fillStyle = '#0f172a';
      ctx.fillText('$' + g.price.toFixed(2), right - w - 8, cy);
    });
  }

  var PLANS = {
    starter: {
      name: 'Starter', price: '$0', period: '/ month',
      tagline: 'For individuals, students and side projects.',
      bullets: [
        'Includes $30 of free compute credit every month',
        'Pay-as-you-go GPU and CPU usage beyond the credit',
        'Up to 10 concurrent GPU containers',
        'Community support on Discord'
      ],
      cta: ['Join the waitlist', 'waitlist.html']
    },
    team: {
      name: 'Team', price: '$99', period: '/ month per workspace',
      tagline: 'For startups and small ML teams shipping to production.',
      bullets: [
        'Usage billed at the on-demand rates above',
        'Up to 50 concurrent GPU containers',
        'Shared secrets and volumes across the workspace',
        'Email support with a one business day response target',
        'SSO with Google Workspace and Okta'
      ],
      cta: ['Join the waitlist', 'waitlist.html']
    },
    enterprise: {
      name: 'Enterprise', price: 'Custom', period: '',
      tagline: 'For companies running large production workloads.',
      bullets: [
        'Reserved and dedicated GPU capacity with volume discounts',
        'Unlimited concurrent containers',
        'Private networking and VPC peering',
        'Priority support with a one hour response target',
        'SOC 2 Type II report and HIPAA BAA available'
      ],
      cta: ['Talk to sales', 'contact.html']
    }
  };

  function renderPlan(key) {
    var p = PLANS[key], panel = document.getElementById('plan-panel');
    if (!p || !panel) return;
    var html = '<div class="plan-head"><span class="plan-name">' + p.name + '</span>' +
      '<span class="plan-price">' + p.price + '</span>' +
      (p.period ? '<span class="plan-period">' + p.period + '</span>' : '') + '</div>' +
      '<p class="plan-tagline">' + p.tagline + '</p><ul class="plan-bullets">' +
      p.bullets.map(function (b) { return '<li>' + b + '</li>'; }).join('') + '</ul>' +
      '<a class="btn btn-primary" href="' + p.cta[1] + '">' + p.cta[0] + '</a>';
    panel.innerHTML = html;
    Array.prototype.forEach.call(document.querySelectorAll('#plan-tabs [role=tab]'), function (b) {
      var on = b.getAttribute('data-plan') === key;
      b.classList.toggle('active', on);
      b.setAttribute('aria-selected', on ? 'true' : 'false');
    });
  }

  function initTabs() {
    var tabs = document.getElementById('plan-tabs');
    if (!tabs) return;
    tabs.addEventListener('click', function (e) {
      var b = e.target.closest('[role=tab]');
      if (b) renderPlan(b.getAttribute('data-plan'));
    });
  }

  drawRates();
  initTabs();
})();
