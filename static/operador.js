/* Vista de trabajo del operador (entrega a sucursal · Fase 5).
 *
 * El servidor entrega la pantalla completa y las acciones funcionan como formularios sin JavaScript. Este script la
 * mantiene al día sin recargar:
 *   - estado en vivo: WebSocket /ws/eventos como señal y GET /api/operador/estado como fuente; si el socket cae,
 *     consulta cada 5 s, y siempre cada 30 s como red de seguridad;
 *   - acciones (llamar, iniciar, finalizar) con fetch a la API, mostrando el motivo si el servidor las rechaza;
 *   - cuenta regresiva y cronómetros locales, avisos de turnos preferenciales y atajos de teclado.
 * Todo el texto que viene de datos se inserta con textContent: nunca se interpreta como HTML.
 */
(function () {
  "use strict";

  var raiz = document.getElementById("oper");
  var inicial = document.getElementById("estado-inicial");
  if (!raiz || !inicial) { return; }

  var BASE = raiz.getAttribute("data-base") || "";
  var VENT = raiz.getAttribute("data-ventanilla");
  var ES_OPERADOR = raiz.getAttribute("data-operador") === "1";
  var CONFIG = JSON.parse(document.getElementById("config-operador").textContent);
  var estado = JSON.parse(inicial.textContent);
  var desfase = estado.servidor_ms - Date.now();      // reloj del servidor menos reloj de este equipo
  var vistos = {};                                    // turnos de la cola ya vistos, para avisar los nuevos
  var primeraVez = true;
  var enCurso = false;

  function $(id) { return document.getElementById(id); }
  function ahora() { return Date.now() + desfase; }

  function mmss(seg) {
    seg = Math.max(0, Math.floor(seg));
    var m = Math.floor(seg / 60), s = seg % 60;
    return (m < 10 ? "0" : "") + m + ":" + (s < 10 ? "0" : "") + s;
  }

  function el(etiqueta, props, hijos) {
    var n = document.createElement(etiqueta);
    Object.keys(props || {}).forEach(function (k) {
      var v = props[k];
      if (v === false || v === null || v === undefined) { return; }
      if (k === "text") { n.textContent = v; }
      else if (v === true) { n.setAttribute(k, ""); }
      else { n.setAttribute(k, v); }
    });
    (hijos || []).forEach(function (h) {
      if (h === null || h === undefined) { return; }
      n.appendChild(typeof h === "string" ? document.createTextNode(h) : h);
    });
    return n;
  }

  function etiqueta(texto) { return String(texto || "").replace(/_/g, " "); }
  function insignia(clase, texto) { return el("span", { "class": "badge badge-" + clase, text: etiqueta(texto) }); }

  /* ---------- avisos para quien lee con lector de pantalla ---------- */
  function anunciar(texto) {
    var v = $("vivo");
    v.textContent = "";
    window.setTimeout(function () { v.textContent = texto; }, 30);
  }
  function alerta(texto) { $("alertas").textContent = texto; }
  function limpiarAlerta() { $("alertas").textContent = ""; }

  /* ---------- sonido opcional para turnos preferenciales ---------- */
  var sonido = false;
  var audio = null;
  try { sonido = window.localStorage.getItem("qline_sonido") === "1"; } catch (e) { sonido = false; }
  function pitido() {
    try {
      var C = window.AudioContext || window.webkitAudioContext;
      if (!C) { return; }
      audio = audio || new C();
      var o = audio.createOscillator(), g = audio.createGain();
      o.type = "sine"; o.frequency.value = 880; g.gain.value = 0.08;
      o.connect(g); g.connect(audio.destination);
      o.start(); o.stop(audio.currentTime + 0.18);
    } catch (e) { /* sin audio: no pasa nada */ }
  }
  var casilla = $("sonido");
  if (casilla) {
    casilla.parentNode.hidden = false;
    casilla.checked = sonido;
    casilla.addEventListener("change", function () {
      sonido = casilla.checked;
      try { window.localStorage.setItem("qline_sonido", sonido ? "1" : "0"); } catch (e) { /* sin almacenamiento */ }
      if (sonido) { pitido(); }
    });
  }

  /* ---------- construcción del turno en curso ---------- */
  function formulario(accion, api, ok, campos) {
    var f = el("form", { "class": "js-accion", method: "post", action: BASE + accion, "data-api": api, "data-ok": ok });
    campos.forEach(function (c) { f.appendChild(el("input", { type: "hidden", name: c[0], value: c[1] })); });
    return f;
  }

  function boton(id, clase, texto, tecla, deshabilitado) {
    return el("button", { type: "submit", id: id, "class": "oper-boton " + clase, disabled: !!deshabilitado }, [
      el("span", { "class": "oper-boton__texto", text: texto }), " ", el("kbd", { text: tecla })]);
  }

  function vistaLibre(e) {
    var f = formulario("/cola/llamar", "/api/llamar", "llamar", [["ventanilla", VENT]]);
    f.appendChild(boton("btn-llamar", "oper-boton--llamar", "Llamar siguiente", "N", !e.en_espera));
    return el("div", { "class": "oper-libre" }, [
      el("p", { "class": "oper-vacio", text: "Sin turno en curso" }), f,
      el("p", { id: "resumen-cola", "class": "nota op-nota" })]);
  }

  function cabeceraTurno(t) {
    return [el("div", { "class": "oper-codigo", id: "codigo-actual", text: t.codigo }),
            el("div", { "class": "oper-etiquetas" }, [insignia(t.estado, t.estado), insignia(t.prioridad, t.prioridad)])];
  }

  function vistaLlamado(e) {
    var t = e.turno;
    var f = formulario("/panel/iniciar", "/api/atencion/iniciar", "iniciar", [["codigo", t.codigo], ["ventanilla", VENT]]);
    f.appendChild(boton("btn-iniciar", "oper-boton--iniciar", "Iniciar atención", "I"));
    var cuenta = t.segundos_restantes !== null && t.segundos_restantes !== undefined
      ? el("p", { "class": "oper-cuenta" }, ["El cliente tiene ", el("strong", { id: "cuenta" }),
          " para presentarse; si no llega, el turno pasa a abandonado."])
      : el("p", { "class": "oper-cuenta", text: "Espere a que el cliente se presente en la ventanilla." });
    return el("div", { "class": "oper-turno", "data-estado": t.estado }, cabeceraTurno(t).concat([cuenta, f]));
  }

  function vistaEnAtencion(e) {
    var t = e.turno;
    var f = formulario("/panel/finalizar", "/api/atencion/finalizar", "finalizar", [["codigo", t.codigo], ["ventanilla", VENT]]);
    f.id = "form-cierre";
    var motivo = el("select", { name: "motivo", id: "motivo-actual" }, [el("option", { value: "", text: "Sin motivo" })]);
    Object.keys(CONFIG.motivos).forEach(function (k) { motivo.appendChild(el("option", { value: k, text: CONFIG.motivos[k] })); });
    f.appendChild(el("details", { "class": "op-cierre" }, [
      el("summary", { text: "Motivo y nota (opcional)" }),
      el("label", { "for": "motivo-actual", text: "Motivo" }), motivo,
      el("label", { "for": "nota-actual", text: "Nota (hasta " + CONFIG.nota_max + " caracteres)" }),
      el("input", { type: "text", name: "nota", id: "nota-actual", maxlength: String(CONFIG.nota_max), autocomplete: "off" })]));
    f.appendChild(boton("btn-finalizar", "oper-boton--finalizar", "Finalizar atención", "F"));
    var cron = el("p", { "class": "oper-cuenta" }, ["En atención desde hace ", el("strong", { id: "cron" })]);
    return el("div", { "class": "oper-turno", "data-estado": t.estado }, cabeceraTurno(t).concat([cron, f]));
  }

  function firma(e) { return e.turno ? e.turno.codigo + "|" + e.turno.estado : "libre"; }

  function textoResumen(e) {
    var pref = e.preferenciales ? " · " + e.preferenciales + (e.preferenciales === 1 ? " preferencial" : " preferenciales") : "";
    return e.en_espera + " en espera" + pref;
  }

  function actualizarActual(e) {
    var libre = $("btn-llamar");
    if (libre) {
      libre.disabled = !e.en_espera;
      libre.querySelector(".oper-boton__texto").textContent = e.en_espera ? "Llamar siguiente" : "No hay turnos en espera";
    }
    var resumen = $("resumen-cola");
    if (resumen) { resumen.textContent = textoResumen(e); }
    tick();
  }

  function renderActual(e) {
    var cuerpo = $("actual-cuerpo");
    if (cuerpo.getAttribute("data-firma") === firma(e)) { actualizarActual(e); return; }
    var teniaFoco = cuerpo.contains(document.activeElement);   // si el operador estaba actuando, el foco sigue al botón nuevo
    cuerpo.textContent = "";
    cuerpo.setAttribute("data-firma", firma(e));
    cuerpo.appendChild(!e.turno ? vistaLibre(e) : (e.turno.puede_iniciar ? vistaLlamado(e) : vistaEnAtencion(e)));
    actualizarActual(e);
    if (teniaFoco) {
      var primero = cuerpo.querySelector("button:not([disabled])");
      if (primero) { primero.focus(); }
    }
  }

  /* ---------- cola de espera y números ---------- */
  function renderCola(e) {
    var lista = $("cola-lista");
    lista.textContent = "";
    e.cola.forEach(function (c) {
      var li = el("li", { "class": "oper-item oper-item--" + c.prioridad, "data-creado-ms": c.creado_ms ? String(c.creado_ms) : false }, [
        el("span", { "class": "oper-pos", text: String(c.posicion) }),
        el("span", { "class": "oper-cod", text: c.codigo }),
        insignia(c.prioridad, c.prioridad),
        el("span", { "class": "oper-espera" })]);
      lista.appendChild(li);
    });
    $("cola-vacia").hidden = e.cola.length > 0;
    $("st-espera").textContent = String(e.en_espera);
    $("st-pref").textContent = String(e.preferenciales);
    $("st-hoy").textContent = String(e.mis_atendidos_hoy);
    $("st-medio").textContent = e.mi_atencion_media_seg === null || e.mi_atencion_media_seg === undefined
      ? "—" : mmss(e.mi_atencion_media_seg);
    var avisos = $("avisos-estado");
    avisos.textContent = "";
    (e.avisos || []).forEach(function (a) { avisos.appendChild(el("div", { "class": "aviso", text: a })); });
  }

  function avisarPreferenciales(e) {
    var nuevos = e.cola.filter(function (c) { return c.prioridad === "preferencial" && !vistos[c.codigo]; });
    var actuales = {};
    e.cola.forEach(function (c) { actuales[c.codigo] = true; });
    vistos = actuales;
    if (primeraVez || !nuevos.length) { return; }
    var texto = (nuevos.length === 1 ? "Entró un turno preferencial: " : "Entraron turnos preferenciales: ")
      + nuevos.map(function (c) { return c.codigo; }).join(", ");
    var caja = $("pref-aviso");
    caja.textContent = texto;
    caja.hidden = false;
    window.clearTimeout(avisarPreferenciales.temporizador);
    avisarPreferenciales.temporizador = window.setTimeout(function () { caja.hidden = true; }, 15000);
    anunciar(texto);
    if (sonido) { pitido(); }
  }

  function aplicar(e) {
    estado = e;
    desfase = e.servidor_ms - Date.now();
    avisarPreferenciales(e);
    primeraVez = false;
    renderActual(e);
    renderCola(e);
    tick();
  }

  /* ---------- relojes locales ---------- */
  function tick() {
    var t = estado.turno;
    var cuenta = $("cuenta");
    if (cuenta && t && t.vence_ms) {
      var r = Math.round((t.vence_ms - ahora()) / 1000);
      cuenta.textContent = r > 0 ? r + " s" : "0 s (tiempo agotado)";
    }
    var cron = $("cron");
    if (cron && t && t.inicio_ms) { cron.textContent = mmss((ahora() - t.inicio_ms) / 1000); }
    var items = document.querySelectorAll("#cola-lista [data-creado-ms]");
    for (var i = 0; i < items.length; i++) {
      var ms = Number(items[i].getAttribute("data-creado-ms"));
      var celda = items[i].querySelector(".oper-espera");
      if (ms && celda) { celda.textContent = mmss((ahora() - ms) / 1000); }
    }
  }

  /* ---------- lectura del estado ---------- */
  var pidiendo = false, pendiente = false;

  function irAlIngreso() {
    var destino = "/cola" + (ES_OPERADOR ? "" : "?ventanilla=" + encodeURIComponent(VENT));
    window.location.href = BASE + "/login?siguiente=" + encodeURIComponent(destino);
  }

  function mensajeDe(cuerpo, status) {
    var m = cuerpo && (cuerpo.error || cuerpo.detail);
    if (typeof m === "string" && m) { return m; }
    return status === 422 ? "Revise los datos enviados." : "No se pudo completar la operación (" + status + ").";
  }

  function refrescar() {
    if (pidiendo) { pendiente = true; return Promise.resolve(); }
    pidiendo = true;
    var url = BASE + "/api/operador/estado" + (ES_OPERADOR ? "" : "?ventanilla=" + encodeURIComponent(VENT));
    return fetch(url, { credentials: "same-origin", cache: "no-store", headers: { "Accept": "application/json" } })
      .then(function (r) {
        if (r.status === 401) { irAlIngreso(); return null; }
        return r.json().catch(function () { return {}; }).then(function (j) { return { r: r, j: j }; });
      })
      .then(function (x) {
        if (!x) { return; }
        if (x.r.ok && x.j.ok) { aplicar(x.j); } else { alerta(mensajeDe(x.j, x.r.status)); }
      })
      .catch(function () { /* sin red: el indicador de conexión ya lo muestra y se reintenta */ })
      .then(function () {
        pidiendo = false;
        if (pendiente) { pendiente = false; return refrescar(); }
      });
  }

  /* ---------- acciones ---------- */
  function ocupar(si) {
    raiz.setAttribute("aria-busy", si ? "true" : "false");
    var botones = raiz.querySelectorAll(".oper-boton");
    for (var i = 0; i < botones.length; i++) {
      // Al terminar se reactivan todos (si la acción fue rechazada el turno no cambia y no se reconstruye la vista),
      // salvo «llamar» cuando no hay nadie en espera.
      botones[i].disabled = si ? true : (botones[i].id === "btn-llamar" && !estado.en_espera);
    }
  }

  function textoDeExito(tipo, j) {
    if (tipo === "llamar") { return j.codigo ? "Llamó al turno " + j.codigo + "." : (j.mensaje || "No hay turnos en espera."); }
    if (tipo === "iniciar") { return "Atención iniciada para " + j.codigo + "."; }
    return "Atención de " + j.codigo + " finalizada" + (j.atencion_seg !== undefined && j.atencion_seg !== null ? " (" + j.atencion_seg + " s)." : ".");
  }

  function accion(api, datos, tipo) {
    if (enCurso) { return; }
    enCurso = true;
    ocupar(true);
    limpiarAlerta();
    var cuerpo = new FormData();
    Object.keys(datos).forEach(function (k) { cuerpo.append(k, datos[k]); });
    fetch(BASE + api, { method: "POST", body: cuerpo, credentials: "same-origin", headers: { "Accept": "application/json" } })
      .then(function (r) { return r.json().catch(function () { return {}; }).then(function (j) { return { r: r, j: j }; }); })
      .then(function (x) {
        if (x.r.status === 401) { irAlIngreso(); return; }
        if (!x.r.ok || x.j.ok === false) { alerta(mensajeDe(x.j, x.r.status)); } else { anunciar(textoDeExito(tipo, x.j)); }
      })
      .catch(function () { alerta("No hay conexión con el servidor. Reintente en unos segundos."); })
      .then(function () { enCurso = false; ocupar(false); return refrescar(); })
      .then(function () { actualizarActual(estado); });
  }

  raiz.addEventListener("submit", function (ev) {
    var f = ev.target;
    if (!f.classList || !f.classList.contains("js-accion")) { return; }
    ev.preventDefault();
    var datos = {};
    new FormData(f).forEach(function (valor, clave) { datos[clave] = valor; });
    accion(f.getAttribute("data-api"), datos, f.getAttribute("data-ok"));
  });

  /* ---------- atajos de teclado ---------- */
  function pulsar(id) { var b = $(id); if (b && !b.disabled) { b.click(); } }

  document.addEventListener("keydown", function (ev) {
    if (ev.ctrlKey || ev.metaKey || ev.altKey || ev.defaultPrevented) { return; }
    var destino = ev.target || {};
    var etiquetaDestino = (destino.tagName || "").toLowerCase();
    if (etiquetaDestino === "input" || etiquetaDestino === "textarea" || etiquetaDestino === "select" || destino.isContentEditable) { return; }
    var tecla = (ev.key || "").toLowerCase();
    if (tecla === "n") { pulsar("btn-llamar"); }
    else if (tecla === "i") { pulsar("btn-iniciar"); }
    else if (tecla === "f") {          // finalizar no se dispara con una sola tecla: se lleva el foco y se confirma con Intro
      var b = $("btn-finalizar");
      if (b) { ev.preventDefault(); b.focus(); anunciar("Pulse Intro para finalizar la atención."); }
    }
  });

  /* ---------- tiempo real ---------- */
  function indicador(modo, texto) {
    var c = $("conexion");
    c.setAttribute("data-estado", modo);
    c.textContent = texto;
  }

  var socket = null, espera = 2000, sondeo = null, programado = null;

  function programar() {
    if (programado) { return; }
    programado = window.setTimeout(function () { programado = null; refrescar(); }, 300);
  }
  function empezarSondeo() { if (!sondeo) { sondeo = window.setInterval(refrescar, 5000); } }
  function detenerSondeo() { if (sondeo) { window.clearInterval(sondeo); sondeo = null; } }

  function abrirSocket() {
    var url = (window.location.protocol === "https:" ? "wss://" : "ws://") + window.location.host + BASE + "/ws/eventos";
    try { socket = new WebSocket(url); } catch (e) { socket = null; indicador("reconectando", "Sin tiempo real: se actualiza cada 5 s"); empezarSondeo(); return; }
    socket.onopen = function () { espera = 2000; indicador("vivo", "En vivo"); detenerSondeo(); refrescar(); };
    socket.onmessage = function (m) {
      var ev;
      try { ev = JSON.parse(m.data); } catch (e) { return; }
      if (ev && ev.tipo && ev.tipo !== "latido" && ev.tipo !== "conectado") { programar(); }
    };
    socket.onclose = function () {
      socket = null;
      indicador("reconectando", "Reconectando… se actualiza cada 5 s");
      empezarSondeo();
      window.setTimeout(abrirSocket, espera);
      espera = Math.min(espera * 2, 15000);
    };
    socket.onerror = function () { try { socket.close(); } catch (e) { /* ya cerrado */ } };
  }

  document.addEventListener("visibilitychange", function () { if (!document.hidden) { refrescar(); } });
  window.setInterval(refrescar, 30000);    // red de seguridad aunque el socket parezca vivo
  window.setInterval(tick, 1000);

  avisarPreferenciales(estado);            // anota la cola inicial sin avisar
  primeraVez = false;
  actualizarActual(estado);
  indicador("conectando", "Conectando…");
  abrirSocket();
})();
