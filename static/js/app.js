/* Moucharaka front-end helpers. No build step, no framework. */
(function () {
  "use strict";
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
  const lang = document.documentElement.lang || "fr";
  const fmt = (n) => new Intl.NumberFormat(lang === "ar" ? "ar-MR-u-nu-latn" : "fr-FR", { maximumFractionDigits: 0 }).format(Math.round(n));

  // Mobile menu
  const toggle = $(".menu-toggle");
  if (toggle) toggle.addEventListener("click", () => {
    const nav = $(".nav");
    nav.classList.toggle("open");
    toggle.setAttribute("aria-expanded", nav.classList.contains("open"));
  });

  // Moughataa list follows the selected wilaya
  $$("select[data-depends-on]").forEach((child) => {
    const form = child.form;
    const parent = form && form.querySelector(`[name$="${child.dataset.dependsOn}"]`);
    if (!parent) return;
    const all = $$("option", child).map((o) => o.cloneNode(true));
    const apply = () => {
      const keep = child.value;
      child.innerHTML = "";
      all.forEach((o) => {
        if (!o.value || !parent.value || o.dataset.wilaya === parent.value) child.appendChild(o.cloneNode(true));
      });
      if ($$("option", child).some((o) => o.value === keep)) child.value = keep;
    };
    parent.addEventListener("change", apply);
    apply();
  });

  // Live total on the invest form
  const inv = $("#invest-form");
  if (inv) {
    const price = parseFloat(inv.dataset.sharePrice);
    const balance = parseFloat(inv.dataset.balance || "0");
    const input = inv.querySelector("[name=shares]");
    const out = $("#invest-total");
    const warn = $("#invest-warn");
    const upd = () => {
      const total = (parseInt(input.value || "0", 10) || 0) * price;
      out.textContent = fmt(total);
      if (warn) warn.hidden = total <= balance;
    };
    input.addEventListener("input", upd);
    upd();
  }

  // Boutique simulator: what would my share earn per month?
  const sim = $("#simulator");
  if (sim) {
    const d = JSON.parse(sim.dataset.model);
    const amount = $("#sim-amount", sim);
    const amountOut = $("#sim-amount-out", sim);
    let factor = 1;
    $$(".seg button", sim).forEach((b) => b.addEventListener("click", () => {
      $$(".seg button", sim).forEach((x) => x.setAttribute("aria-pressed", "false"));
      b.setAttribute("aria-pressed", "true");
      factor = parseFloat(b.dataset.factor);
      run();
    }));
    function run() {
      const a = parseFloat(amount.value);
      amountOut.textContent = fmt(a);
      const parts = a / d.capital;
      let monthly, yearly;
      if (d.model === "mourabaha") {
        const total = a * (1 + d.marginPct / 100);
        monthly = (total - a) / d.months;
        yearly = monthly * 12;
        $("#sim-total", sim).textContent = fmt(total);
      } else {
        const revenue = d.revenue * (1 + d.uplift / 100) * factor;
        const net = revenue * d.margin / 100 - d.fixed;
        monthly = Math.max(net, 0) * d.share / 100 * parts;
        yearly = monthly * 12;
        $("#sim-total", sim).textContent = fmt(a + yearly * (d.months / 12));
      }
      $("#sim-monthly", sim).textContent = fmt(monthly);
      $("#sim-yearly", sim).textContent = (a ? (yearly / a * 100) : 0).toFixed(1) + " %";
    }
    amount.addEventListener("input", run);
    run();
  }

  // Charts (Chart.js loaded only on pages that need it)
  const css = getComputedStyle(document.documentElement);
  const color = (v) => css.getPropertyValue(v).trim();
  function lineChart(el, cfg) {
    if (!window.Chart || !el) return;
    Chart.defaults.font.family = color("--font") || "sans-serif";
    Chart.defaults.color = color("--muted");
    return new Chart(el, cfg);
  }
  const rev = $("#revenue-chart");
  if (rev) {
    const d = JSON.parse(rev.dataset.chart);
    if (d.labels.length) lineChart(rev, {
      type: "bar",
      data: { labels: d.labels, datasets: [
        { label: rev.dataset.lDeclared, data: d.declared, backgroundColor: color("--flow-cogs"), borderRadius: 4 },
        { label: rev.dataset.lActual, data: d.actual, backgroundColor: color("--ink"), borderRadius: 4 },
        { label: rev.dataset.lProfit, data: d.profit, type: "line", borderColor: color("--palm"), backgroundColor: color("--palm"), spanGaps: true, tension: .3 },
      ] },
      options: { maintainAspectRatio: false, plugins: { legend: { position: "bottom" } },
        scales: { y: { ticks: { callback: (v) => fmt(v) } }, x: { grid: { display: false } } } },
    });
  }
  const price = $("#price-chart");
  if (price) {
    const d = JSON.parse(price.dataset.chart);
    if (d.prices.length) lineChart(price, {
      type: "line",
      data: { labels: d.labels, datasets: [
        { label: price.dataset.lPrice, data: d.prices, borderColor: color("--palm"), backgroundColor: color("--palm-soft"), fill: true, tension: .25 },
        { label: price.dataset.lNominal, data: d.prices.map(() => d.nominal), borderColor: color("--line-2"), borderDash: [4, 4], pointRadius: 0 },
      ] },
      options: { maintainAspectRatio: false, plugins: { legend: { position: "bottom" } } },
    });
  }

  // Maps (Leaflet + OpenStreetMap tiles)
  const map = $("#shop-map");
  if (map && window.L) {
    const lat = parseFloat(map.dataset.lat), lng = parseFloat(map.dataset.lng);
    const m = L.map(map, { scrollWheelZoom: false }).setView([lat, lng], map.dataset.zoom ? +map.dataset.zoom : 15);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", { attribution: "© OpenStreetMap", maxZoom: 19 }).addTo(m);
    const marker = L.marker([lat, lng], { draggable: map.dataset.pick === "1" }).addTo(m);
    if (map.dataset.pick === "1") {
      const latIn = $("[name=latitude]"), lngIn = $("[name=longitude]");
      const set = (ll) => { latIn.value = ll.lat.toFixed(6); lngIn.value = ll.lng.toFixed(6); };
      marker.on("dragend", () => set(marker.getLatLng()));
      m.on("click", (e) => { marker.setLatLng(e.latlng); set(e.latlng); });
      const geo = $("#use-my-location");
      if (geo && navigator.geolocation) geo.addEventListener("click", (e) => {
        e.preventDefault();
        navigator.geolocation.getCurrentPosition((p) => {
          const ll = { lat: p.coords.latitude, lng: p.coords.longitude };
          marker.setLatLng(ll); m.setView(ll, 17); set(ll);
        });
      });
    }
  }

  // Favorite toggle without reload
  $$("form[data-fav]").forEach((f) => f.addEventListener("submit", async (e) => {
    e.preventDefault();
    const r = await fetch(f.action, { method: "POST", body: new FormData(f), headers: { "X-Requested-With": "fetch" } });
    if (r.ok) {
      const j = await r.json();
      const b = f.querySelector("button");
      b.setAttribute("aria-pressed", j.favorite);
      b.querySelector("span").textContent = j.favorite ? b.dataset.on : b.dataset.off;
    }
  }));

  // Copy-to-clipboard buttons (share links, IDs)
  $$("[data-copy]").forEach((b) => b.addEventListener("click", async () => {
    const value = b.dataset.copy;
    try { await navigator.clipboard.writeText(value); }
    catch (e) {
      const t = document.createElement("textarea"); t.value = value; document.body.appendChild(t);
      t.select(); document.execCommand("copy"); t.remove();
    }
    const old = b.textContent; b.textContent = b.dataset.done || "✓";
    setTimeout(() => { b.textContent = old; }, 1800);
  }));

  // Native share sheet on phones (WhatsApp, Telegram, SMS…)
  $$("[data-native-share]").forEach((b) => {
    if (!navigator.share) return;
    b.hidden = false;
    b.addEventListener("click", () => navigator.share({ title: b.dataset.title, text: b.dataset.text, url: b.dataset.url }).catch(() => {}));
  });

  // Upload as soon as a file is chosen (no "Add" button): data-autosubmit="<name of the action>"
  $$("input[type=file][data-autosubmit]").forEach((input) => input.addEventListener("change", () => {
    if (!input.files || !input.files.length || !input.form) return;
    const flag = document.createElement("input");
    flag.type = "hidden";
    flag.name = input.dataset.autosubmit;
    flag.value = "1";
    input.form.appendChild(flag);
    input.form.noValidate = true;
    input.form.submit();
  }));

  // Confirm dangerous actions
  $$("[data-confirm]").forEach((el) => el.addEventListener("click", (e) => {
    if (!window.confirm(el.dataset.confirm)) e.preventDefault();
  }));

  // Formset helpers: "add a row" clones the empty form
  $$("[data-formset-add]").forEach((btn) => btn.addEventListener("click", () => {
    const prefix = btn.dataset.formsetAdd;
    const total = $(`#id_${prefix}-TOTAL_FORMS`);
    const tpl = $(`#${prefix}-empty`);
    const body = $(`#${prefix}-rows`);
    const idx = parseInt(total.value, 10);
    const row = document.createElement("tbody");
    row.innerHTML = tpl.innerHTML.replace(/__prefix__/g, idx);
    body.appendChild(row.firstElementChild);
    total.value = idx + 1;
  }));
})();
