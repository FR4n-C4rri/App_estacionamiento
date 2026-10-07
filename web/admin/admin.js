// Modo admin: login, lista de cámaras y asistente para agregar / editar.

const COLORES = { "HAY LUGAR": "#1e8e3e", "CASI LLENO": "#f9ab00", "LLENO": "#d93025", "SIN DATOS": "#80868b" };
const COLOR_VALIDO = "#00c800";
const COLOR_PROHIBIDO = "#ff8c00";
const COLOR_EN_CURSO = "#ff2020";
const CENTRO_INICIAL = [-34.6037, -58.3816];

const $ = (id) => document.getElementById(id);
const escapar = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// ---------------------------------------------------------------------------
// Sesión y API

let token = null;
try { token = sessionStorage.getItem("token_admin"); } catch {}

function guardarToken(t) {
  token = t;
  try { t ? sessionStorage.setItem("token_admin", t) : sessionStorage.removeItem("token_admin"); } catch {}
}

async function api(ruta, opciones = {}) {
  const headers = { ...(opciones.headers || {}) };
  if (token) headers.Authorization = `Bearer ${token}`;
  let body = opciones.body;
  if (body && !(body instanceof FormData) && typeof body !== "string") {
    body = JSON.stringify(body);
    headers["Content-Type"] = "application/json";
  }
  const r = await fetch(ruta, { ...opciones, headers, body });
  if (r.status === 401 && ruta !== "/api/admin/login") {
    guardarToken(null);
    mostrarVista("login");
    throw new Error("Sesión vencida, volvé a entrar");
  }
  if (!r.ok) {
    let msg = `Error ${r.status}`;
    try { const j = await r.json(); msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail); } catch {}
    throw new Error(msg);
  }
  const tipo = r.headers.get("content-type") || "";
  return tipo.includes("application/json") ? r.json() : r.blob();
}

function avisar(texto, ms = 3500) {
  const a = $("aviso");
  a.textContent = texto;
  a.hidden = false;
  clearTimeout(avisar._t);
  avisar._t = setTimeout(() => (a.hidden = true), ms);
}

// ---------------------------------------------------------------------------
// Vistas

let refrescoLista = null;

function mostrarVista(nombre) {
  for (const v of ["login", "lista", "asistente"]) $(`vista-${v}`).hidden = v !== nombre;
  clearInterval(refrescoLista);
  if (nombre === "lista") {
    cargarLista();
    refrescoLista = setInterval(cargarLista, 15000);
  }
}

$("form-login").addEventListener("submit", async (e) => {
  e.preventDefault();
  $("error-login").hidden = true;
  try {
    const r = await api("/api/admin/login", { method: "POST", body: { password: $("password").value } });
    guardarToken(r.token);
    $("password").value = "";
    mostrarVista("lista");
  } catch (err) {
    $("error-login").textContent = err.message;
    $("error-login").hidden = false;
  }
});

$("salir").addEventListener("click", () => { guardarToken(null); mostrarVista("login"); });

// ---------------------------------------------------------------------------
// Lista de cámaras

function haceCuanto(min) {
  if (min == null) return "nunca";
  if (min < 1) return "hace < 1 min";
  if (min < 60) return `hace ${Math.round(min)} min`;
  if (min < 1440) return `hace ${Math.round(min / 60)} h`;
  return `hace ${Math.round(min / 1440)} días`;
}

async function cargarLista() {
  let camaras;
  try { camaras = await api("/api/admin/camaras"); } catch (e) { avisar(e.message); return; }
  const cont = $("lista-camaras");
  cont.innerHTML = "";
  if (!camaras.length) {
    cont.innerHTML = `<div class="vacio-lista" style="grid-column:1/-1">Todavía no hay cámaras. Tocá <strong>+ Agregar cámara</strong> para dar de alta la primera.</div>`;
    return;
  }
  for (const c of camaras) {
    const estado = c.activa ? c.estado : "SIN DATOS";
    const div = document.createElement("article");
    div.className = "camara";
    const foto = c.tiene_preview
      ? `<div class="foto" style="background-image:url('/api/camaras/${encodeURIComponent(c.id)}/preview.jpg?t=${encodeURIComponent(c.actualizado_en || "")}')"></div>`
      : `<div class="foto">Sin fotos procesadas todavía</div>`;
    const bloqueados = c.prohibidos_bloqueados ? `<div class="linea" style="color:#a50e0e">⚠ ${c.prohibidos_bloqueados} zona(s) prohibida(s) bloqueada(s)</div>` : "";
    const f = c.fuente || { tipo: "envio" };
    let origen = "Fotos: las manda la cámara";
    let claseOrigen = "etiqueta-fuente";
    if (f.tipo !== "envio") {
      origen = `Fotos: el servidor las busca (${f.tipo === "video" ? "video" : "URL de foto"}, cada ${f.intervalo} s)`;
      if (f.captura?.error) { origen += ` · ⚠ ${f.captura.error}`; claseOrigen += " mal"; }
      else if (f.captura?.ultima_captura) origen += ` · última captura ${haceCuanto((Date.now() - Date.parse(f.captura.ultima_captura)) / 60000)}`;
    }
    div.innerHTML = `
      ${foto}
      <div class="cuerpo">
        <div class="linea"><strong>${escapar(c.nombre)}</strong><span class="chip" style="background:${COLORES[estado]}">${c.activa ? estado : "DESACTIVADA"}</span></div>
        <div class="linea suave"><span><code>${escapar(c.id)}</code> · ${escapar(c.direccion) || "sin dirección"}</span></div>
        <div class="linea"><span>${c.libres ?? "?"} libre${c.libres === 1 ? "" : "s"} de ${c.total}</span><span class="suave">${haceCuanto(c.minutos_desde_actualizacion)}</span></div>
        <div class="${claseOrigen}">${escapar(origen)}</div>
        ${bloqueados}
        <div class="botones">
          <button class="boton chico" data-accion="editar">Editar</button>
          <label class="boton chico">Mandar foto de prueba<input type="file" accept="image/jpeg,image/png" hidden data-accion="foto"></label>
          <button class="boton chico" data-accion="activar">${c.activa ? "Desactivar" : "Activar"}</button>
          <button class="boton chico peligro" data-accion="eliminar">Eliminar</button>
        </div>
      </div>`;
    div.querySelector('[data-accion="editar"]').onclick = () => abrirAsistente(c.id);
    div.querySelector('[data-accion="foto"]').onchange = (e) => mandarFotoPrueba(c.id, e.target.files[0]);
    div.querySelector('[data-accion="activar"]').onclick = () => cambiarActiva(c);
    div.querySelector('[data-accion="eliminar"]').onclick = () => eliminarCamara(c);
    cont.appendChild(div);
  }
}

async function mandarFotoPrueba(id, archivo) {
  if (!archivo) return;
  const fd = new FormData();
  fd.append("foto", archivo);
  try {
    await api(`/api/admin/camaras/${id}/fotos`, { method: "POST", body: fd });
    avisar("Foto enviada. El detector la procesa en unos segundos.");
    setTimeout(cargarLista, 6000);
  } catch (e) { avisar(e.message); }
}

async function cambiarActiva(c) {
  try {
    await api(`/api/admin/camaras/${c.id}`, {
      method: "PUT",
      body: { nombre: c.nombre, direccion: c.direccion, lat: c.lat, lng: c.lng, cuadra: c.cuadra, activa: !c.activa },
    });
    cargarLista();
  } catch (e) { avisar(e.message); }
}

async function eliminarCamara(c) {
  if (!confirm(`¿Eliminar "${c.nombre}" (${c.id})?\n\nSe borra su carpeta (espacios, fotos, referencia) y su historial. No se puede deshacer.`)) return;
  try {
    await api(`/api/admin/camaras/${c.id}`, { method: "DELETE" });
    avisar(`Cámara ${c.id} eliminada`);
    cargarLista();
  } catch (e) { avisar(e.message); }
}

$("nueva-camara").addEventListener("click", () => abrirAsistente(null));

// ---------------------------------------------------------------------------
// Asistente (agregar / editar)

const w = {
  modo: "crear",
  id: "",
  paso: 1,
  datos: { lat: null, lng: null, inicio: null, fin: null },
  referencia: null,         // { blob, url, ancho, alto, nueva }
  espacios: [],             // [{ tipo, puntos: [[x,y],...] }]
  actuales: [],
  espaciosCambiaron: false,
  creada: null,
};

async function abrirAsistente(id) {
  Object.assign(w, {
    modo: id ? "editar" : "crear", id: id || "", paso: 1,
    datos: { lat: null, lng: null, inicio: null, fin: null },
    referencia: null, espacios: [], actuales: [], espaciosCambiaron: false, creada: null,
  });
  $("titulo-asistente").textContent = id ? `Editar ${id}` : "Agregar cámara";
  $("campo-id").disabled = !!id;
  $("usar-ultima").hidden = !id;
  $("info-referencia").textContent = "";
  $("vista-referencia").hidden = true;
  $("archivo-referencia").value = "";

  try {
    if (id) {
      const cam = await api(`/api/admin/camaras/${id}`);
      $("campo-id").value = cam.id;
      $("campo-nombre").value = cam.nombre;
      $("campo-direccion").value = cam.direccion || "";
      $("campo-activa").checked = cam.activa !== false;
      w.datos = { lat: cam.lat, lng: cam.lng, inicio: cam.cuadra?.[0] || null, fin: cam.cuadra?.[1] || null };
      w.espacios = cam.espacios.map((e) => ({ tipo: e.tipo, puntos: e.puntos }));
      w.apiKey = cam.api_key;
      ponerFuente(cam.fuente);
      const blob = await api(`/api/admin/camaras/${id}/referencia.jpg`);
      await ponerReferencia(blob, false);
    } else {
      $("campo-id").value = (await api("/api/admin/siguiente_id")).id;
      $("campo-nombre").value = "";
      $("campo-direccion").value = "";
      $("campo-activa").checked = true;
      w.apiKey = null;
      ponerFuente(null);
    }
  } catch (e) { avisar(e.message); return; }

  mostrarVista("asistente");
  irAPaso(1);
}

$("volver").addEventListener("click", () => {
  if (w.creada || confirm("¿Salir sin guardar?")) mostrarVista("lista");
});

function irAPaso(n) {
  w.paso = n;
  document.querySelectorAll(".paso").forEach((p) => p.classList.toggle("visible", Number(p.dataset.paso) === n));
  document.querySelectorAll("#pasos li").forEach((li) => {
    const p = Number(li.dataset.paso);
    li.classList.toggle("actual", p === n);
    li.classList.toggle("hecho", p < n);
  });
  $("error-asistente").hidden = true;
  $("anterior").style.visibility = n === 1 || w.creada ? "hidden" : "visible";
  $("siguiente").textContent = n < 5 ? "Siguiente" : w.creada ? "Volver a la lista" : w.modo === "crear" ? "Crear cámara" : "Guardar cambios";
  if (n === 2) prepararMapa();
  if (n === 4) dibujarLienzo();
  if (n === 5) mostrarResumen();
  window.scrollTo(0, 0);
}

function errorPaso(msg) {
  $("error-asistente").textContent = msg;
  $("error-asistente").hidden = false;
}

function validarPaso(n) {
  if (n === 1) {
    if (!/^[a-z0-9_]{1,40}$/.test($("campo-id").value.trim())) return "El ID solo puede tener minúsculas, números y _";
    if (!$("campo-nombre").value.trim()) return "Poné un nombre para la cuadra";
    const f = leerFuente();
    if (f.tipo !== "envio") {
      if (!f.url) return "Poné la dirección de la cámara (o elegí que la cámara mande las fotos)";
      if (!(f.intervalo >= 2 && f.intervalo <= 300)) return "El intervalo tiene que estar entre 2 y 300 segundos";
    }
  }
  if (n === 2) {
    if (w.datos.lat == null) return "Marcá la posición de la cámara en el mapa";
    if (!!w.datos.inicio !== !!w.datos.fin) return "Marcá los dos extremos de la cuadra (inicio y fin), o ninguno";
  }
  if (n === 3 && !w.referencia) return "Subí una foto de referencia";
  if (n === 4) {
    if (w.actuales.length) return "Tenés un polígono sin cerrar: cerralo o deshacé esos puntos";
    if (!w.espacios.some((e) => e.tipo === "valido")) return "Delimitá al menos un lugar válido";
  }
  return null;
}

$("anterior").addEventListener("click", () => irAPaso(Math.max(1, w.paso - 1)));
$("siguiente").addEventListener("click", async () => {
  if (w.creada) { mostrarVista("lista"); return; }
  const err = validarPaso(w.paso);
  if (err) return errorPaso(err);
  if (w.paso < 5) return irAPaso(w.paso + 1);
  await guardar();
});
document.querySelectorAll("#pasos li").forEach((li) => li.addEventListener("click", () => {
  const destino = Number(li.dataset.paso);
  if (w.creada) return;
  for (let p = 1; p < destino; p++) {
    const err = validarPaso(p);
    if (err) { irAPaso(p); return errorPaso(err); }
  }
  irAPaso(destino);
}));

// --- Paso 1: origen de las fotos ---------------------------------------------

const AYUDA_URL = {
  video: "Ej.: rtsp://usuario:clave@192.168.0.50:554/Streaming/Channels/101 · http://192.168.0.20:8080/video (IP Webcam) · 0 (webcam de esta PC) · C:\\videos\\cuadra.mp4",
  foto: "Ej.: http://usuario:clave@192.168.0.50/ISAPI/Streaming/channels/101/picture · http://192.168.0.20:8080/shot.jpg (IP Webcam)",
};

function tipoFuente() {
  return document.querySelector('input[name="fuente-tipo"]:checked').value;
}

function leerFuente() {
  const tipo = tipoFuente();
  if (tipo === "envio") return { tipo };
  return { tipo, url: $("fuente-url").value.trim(), intervalo: Number($("fuente-intervalo").value) };
}

function ponerFuente(fuente) {
  const f = fuente || { tipo: "envio" };
  document.querySelector(`input[name="fuente-tipo"][value="${f.tipo}"]`).checked = true;
  $("fuente-url").value = f.url || "";
  $("fuente-intervalo").value = f.intervalo || 10;
  $("resultado-prueba").textContent = "";
  $("resultado-prueba").className = "suave chico";
  $("foto-prueba").hidden = true;
  actualizarCamposFuente();
}

function actualizarCamposFuente() {
  const tipo = tipoFuente();
  $("campos-fuente").hidden = tipo === "envio";
  $("tomar-de-camara").hidden = tipo === "envio";
  if (tipo !== "envio") {
    $("ayuda-url").textContent = AYUDA_URL[tipo];
    $("fuente-url").placeholder = tipo === "video" ? "rtsp://..." : "http://...";
  }
}

document.querySelectorAll('input[name="fuente-tipo"]').forEach((r) => r.addEventListener("change", actualizarCamposFuente));

async function fotoDeLaCamara() {
  const f = leerFuente();
  if (!f.url) throw new Error("Poné la dirección de la cámara en el paso 1");
  return api("/api/admin/probar_fuente", { method: "POST", body: f });
}

$("probar-fuente").addEventListener("click", async () => {
  const res = $("resultado-prueba");
  const boton = $("probar-fuente");
  boton.disabled = true;
  res.className = "suave chico";
  res.textContent = "Conectando con la cámara… (puede tardar hasta 15 s)";
  $("foto-prueba").hidden = true;
  try {
    const blob = await fotoDeLaCamara();
    const img = $("foto-prueba");
    if (img.src.startsWith("blob:")) URL.revokeObjectURL(img.src);
    img.src = URL.createObjectURL(blob);
    img.hidden = false;
    res.className = "chico ok";
    res.textContent = "✓ Funciona. Esta es la imagen que llega ahora.";
  } catch (e) {
    res.className = "chico mal";
    res.textContent = "✗ " + e.message;
  } finally {
    boton.disabled = false;
  }
});

// --- Paso 2: mapa -----------------------------------------------------------

let mapa = null;
const pines = {};
let lineaCuadra = null;

function pin(color) {
  return L.divIcon({ className: "", html: `<div class="pin" style="background:${color}"></div>`, iconSize: [18, 18], iconAnchor: [9, 9] });
}

function prepararMapa() {
  if (!mapa) {
    mapa = L.map("mapa-admin").setView(CENTRO_INICIAL, 13);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    }).addTo(mapa);
    mapa.on("click", (e) => {
      const modo = document.querySelector('input[name="modo-mapa"]:checked').value;
      fijarPunto(modo, [e.latlng.lat, e.latlng.lng]);
      const siguiente = { camara: "inicio", inicio: "fin" }[modo];
      if (siguiente) document.querySelector(`input[name="modo-mapa"][value="${siguiente}"]`).checked = true;
    });
  }
  setTimeout(() => {
    mapa.invalidateSize();
    for (const k of ["camara", "inicio", "fin"]) {
      const punto = k === "camara" ? (w.datos.lat != null ? [w.datos.lat, w.datos.lng] : null) : w.datos[k];
      dibujarPin(k, punto);
    }
    dibujarCuadra();
    if (w.datos.lat != null) mapa.setView([w.datos.lat, w.datos.lng], 18);
    document.querySelector(`input[name="modo-mapa"][value="${w.datos.lat == null ? "camara" : "inicio"}"]`).checked = true;
  }, 50);
}

function fijarPunto(modo, punto) {
  if (modo === "camara") [w.datos.lat, w.datos.lng] = punto;
  else w.datos[modo] = punto;
  dibujarPin(modo, punto);
  dibujarCuadra();
}

function dibujarPin(modo, punto) {
  if (pines[modo]) { mapa.removeLayer(pines[modo]); delete pines[modo]; }
  if (!punto) return;
  const color = { camara: "#1a73e8", inicio: "#1e8e3e", fin: "#d93025" }[modo];
  const titulo = { camara: "Cámara", inicio: "Inicio de cuadra", fin: "Fin de cuadra" }[modo];
  pines[modo] = L.marker(punto, { icon: pin(color), draggable: true, title: titulo }).addTo(mapa);
  pines[modo].on("drag", (e) => {
    const ll = e.target.getLatLng();
    if (modo === "camara") [w.datos.lat, w.datos.lng] = [ll.lat, ll.lng];
    else w.datos[modo] = [ll.lat, ll.lng];
    dibujarCuadra();
  });
}

function dibujarCuadra() {
  if (lineaCuadra) { mapa.removeLayer(lineaCuadra); lineaCuadra = null; }
  if (w.datos.inicio && w.datos.fin) {
    lineaCuadra = L.polyline([w.datos.inicio, w.datos.fin], { color: "#1e8e3e", weight: 7, opacity: 0.8 }).addTo(mapa);
  }
  const f = (p) => (p ? `${p[0].toFixed(6)}, ${p[1].toFixed(6)}` : "—");
  $("coords").textContent = `Cámara: ${f(w.datos.lat != null ? [w.datos.lat, w.datos.lng] : null)} · Inicio: ${f(w.datos.inicio)} · Fin: ${f(w.datos.fin)}`;
}

$("mi-ubicacion").addEventListener("click", () => {
  if (!navigator.geolocation) return avisar("El navegador no permite obtener la ubicación");
  navigator.geolocation.getCurrentPosition(
    (p) => mapa.setView([p.coords.latitude, p.coords.longitude], 18),
    () => avisar("No se pudo obtener tu ubicación"),
    { enableHighAccuracy: true, timeout: 10000 }
  );
});

// --- Paso 3: foto de referencia --------------------------------------------

function cargarImagen(url) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error("No se pudo abrir la imagen (si es de iPhone puede ser HEIC: convertila a JPG)"));
    img.src = url;
  });
}

async function ponerReferencia(blob, nueva) {
  const url = URL.createObjectURL(blob);
  const img = await cargarImagen(url);
  const anterior = w.referencia;
  // Si cambia la resolución, se escalan los polígonos que ya había.
  if (anterior && w.espacios.length && (anterior.ancho !== img.naturalWidth || anterior.alto !== img.naturalHeight)) {
    const fx = img.naturalWidth / anterior.ancho, fy = img.naturalHeight / anterior.alto;
    w.espacios = w.espacios.map((e) => ({ ...e, puntos: e.puntos.map(([x, y]) => [Math.round(x * fx), Math.round(y * fy)]) }));
  }
  if (anterior) URL.revokeObjectURL(anterior.url);
  w.referencia = { blob, url, img, ancho: img.naturalWidth, alto: img.naturalHeight, nueva };
  if (nueva) w.espaciosCambiaron = true;
  $("vista-referencia").src = url;
  $("vista-referencia").hidden = false;
  $("info-referencia").textContent = `Resolución ${img.naturalWidth} × ${img.naturalHeight}${nueva ? " · foto nueva" : " · foto actual"}`;
}

$("archivo-referencia").addEventListener("change", async (e) => {
  const archivo = e.target.files[0];
  if (!archivo) return;
  try { await ponerReferencia(archivo, true); } catch (err) { errorPaso(err.message); }
});

$("tomar-de-camara").addEventListener("click", async () => {
  const boton = $("tomar-de-camara");
  boton.disabled = true;
  $("info-referencia").textContent = "Pidiendo la foto a la cámara…";
  try { await ponerReferencia(await fotoDeLaCamara(), true); }
  catch (err) { $("info-referencia").textContent = ""; errorPaso(err.message); }
  finally { boton.disabled = false; }
});

$("usar-ultima").addEventListener("click", async () => {
  try { await ponerReferencia(await api(`/api/admin/camaras/${w.id}/ultima_foto`), true); }
  catch (err) { errorPaso(err.message); }
});

// --- Paso 4: delimitar lugares (como calibrar_espacios.py) ------------------

const lienzo = $("lienzo");
const ctx = lienzo.getContext("2d");

function dibujarLienzo() {
  if (!w.referencia) return;
  const { img, ancho, alto } = w.referencia;
  if (lienzo.width !== ancho || lienzo.height !== alto) { lienzo.width = ancho; lienzo.height = alto; }
  const escala = ancho / (lienzo.clientWidth || ancho);
  ctx.drawImage(img, 0, 0);

  const ids = idsEspacios();
  w.espacios.forEach((e, i) => {
    const color = e.tipo === "valido" ? COLOR_VALIDO : COLOR_PROHIBIDO;
    ctx.beginPath();
    e.puntos.forEach(([x, y], j) => (j ? ctx.lineTo(x, y) : ctx.moveTo(x, y)));
    ctx.closePath();
    ctx.fillStyle = color + "33";
    ctx.fill();
    ctx.lineWidth = 3 * escala;
    ctx.strokeStyle = color;
    ctx.stroke();
    const cx = e.puntos.reduce((s, p) => s + p[0], 0) / e.puntos.length;
    const cy = e.puntos.reduce((s, p) => s + p[1], 0) / e.puntos.length;
    ctx.font = `bold ${Math.round(14 * escala)}px system-ui, sans-serif`;
    ctx.textAlign = "center";
    ctx.lineWidth = 4 * escala;
    ctx.strokeStyle = "rgba(0,0,0,.7)";
    ctx.strokeText(ids[i], cx, cy);
    ctx.fillStyle = color;
    ctx.fillText(ids[i], cx, cy);
  });

  if (w.actuales.length) {
    ctx.beginPath();
    w.actuales.forEach(([x, y], j) => (j ? ctx.lineTo(x, y) : ctx.moveTo(x, y)));
    ctx.lineWidth = 3 * escala;
    ctx.strokeStyle = COLOR_EN_CURSO;
    ctx.stroke();
    ctx.fillStyle = COLOR_EN_CURSO;
    for (const [x, y] of w.actuales) { ctx.beginPath(); ctx.arc(x, y, 5 * escala, 0, Math.PI * 2); ctx.fill(); }
  }
  listarEspacios();
}

function idsEspacios() {
  const n = { valido: 0, prohibido: 0 };
  return w.espacios.map((e) => `${e.tipo === "valido" ? "espacio" : "prohibido"}_${++n[e.tipo]}`);
}

function listarEspacios() {
  const ids = idsEspacios();
  $("cuenta-validos").textContent = w.espacios.filter((e) => e.tipo === "valido").length;
  const ul = $("lista-espacios");
  ul.innerHTML = "";
  w.espacios.forEach((e, i) => {
    const li = document.createElement("li");
    li.innerHTML = `<span><i class="punto" style="background:${e.tipo === "valido" ? COLOR_VALIDO : COLOR_PROHIBIDO}"></i>${ids[i]}</span>`;
    const b = document.createElement("button");
    b.className = "boton chico";
    b.textContent = "Quitar";
    b.onclick = () => { w.espacios.splice(i, 1); w.espaciosCambiaron = true; dibujarLienzo(); };
    li.appendChild(b);
    ul.appendChild(li);
  });
  if (!w.espacios.length) ul.innerHTML = `<li class="suave">Todavía no marcaste ningún lugar.</li>`;
}

lienzo.addEventListener("click", (e) => {
  const r = lienzo.getBoundingClientRect();
  const x = Math.round(((e.clientX - r.left) / r.width) * lienzo.width);
  const y = Math.round(((e.clientY - r.top) / r.height) * lienzo.height);
  w.actuales.push([x, y]);
  dibujarLienzo();
});

function cerrarPoligono(tipo) {
  if (w.actuales.length < 3) return avisar("Necesitás al menos 3 puntos para cerrar un polígono");
  w.espacios.push({ tipo, puntos: w.actuales });
  w.actuales = [];
  w.espaciosCambiaron = true;
  dibujarLienzo();
}

function deshacer() {
  if (w.actuales.length) w.actuales.pop();
  else if (w.espacios.length) { w.espacios.pop(); w.espaciosCambiaron = true; }
  dibujarLienzo();
}

$("cerrar-valido").addEventListener("click", () => cerrarPoligono("valido"));
$("cerrar-prohibido").addEventListener("click", () => cerrarPoligono("prohibido"));
$("deshacer").addEventListener("click", deshacer);
$("borrar-todo").addEventListener("click", () => {
  if (!w.espacios.length && !w.actuales.length) return;
  if (!confirm("¿Borrar todos los polígonos?")) return;
  w.espacios = []; w.actuales = []; w.espaciosCambiaron = true;
  dibujarLienzo();
});
document.addEventListener("keydown", (e) => {
  if (w.paso !== 4 || $("vista-asistente").hidden || e.target.tagName === "INPUT") return;
  const k = e.key.toLowerCase();
  if (k === "n") cerrarPoligono("valido");
  else if (k === "p") cerrarPoligono("prohibido");
  else if (k === "z") deshacer();
});
window.addEventListener("resize", () => { if (w.paso === 4) dibujarLienzo(); });

// --- Paso 5: confirmar y guardar --------------------------------------------

function datosFormulario() {
  return {
    nombre: $("campo-nombre").value.trim(),
    direccion: $("campo-direccion").value.trim(),
    activa: $("campo-activa").checked,
    lat: w.datos.lat,
    lng: w.datos.lng,
    cuadra: w.datos.inicio && w.datos.fin ? [w.datos.inicio, w.datos.fin] : null,
    fuente: leerFuente(),
  };
}

function sinClave(url) {
  // rtsp://usuario:clave@host -> rtsp://usuario:***@host (para no mostrar la contraseña)
  return url.replace(/^([a-z]+:\/\/[^:/@]+):[^@]*@/i, "$1:***@");
}

function textoFuente(f) {
  if (f.tipo === "envio") return "La cámara las manda (POST con API key)";
  return `El servidor las busca (${f.tipo === "video" ? "video" : "URL de foto"}) cada ${f.intervalo} s de <code>${escapar(sinClave(f.url))}</code>`;
}

function descargarIni(id, key) {
  const texto = [
    "; Configuración de la cámara " + id + " (generado desde el modo admin).",
    "; Guardalo como camara.ini dentro de la carpeta cliente_camara.",
    "",
    "[camara]",
    "; Link del servidor. Si se reinicia el túnel cambia: actualizalo acá.",
    "servidor = " + location.origin,
    "id = " + id,
    "key = " + key,
    "",
    "; De dónde sacar la imagen:",
    ";   0                                  webcam de esta compu",
    ";   http://192.168.0.20:8080/video     celular con la app IP Webcam",
    ";   rtsp://usuario:clave@192.168.0.50:554/Streaming/Channels/101   cámara IP",
    "fuente = 0",
    "",
    "; Cada cuántos segundos mandar una foto (bastante menos que 45)",
    "intervalo = 10",
    "",
  ].join("\r\n");
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([texto], { type: "text/plain" }));
  a.download = "camara.ini";
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

function mostrarResumen() {
  const d = datosFormulario();
  const validos = w.espacios.filter((e) => e.tipo === "valido").length;
  const prohibidos = w.espacios.length - validos;
  $("titulo-confirmar").textContent = w.creada ? "Cámara lista" : "5. Confirmar";
  let html = `<div class="resumen"><dl>
      <dt>ID</dt><dd><code>${escapar($("campo-id").value.trim())}</code></dd>
      <dt>Nombre</dt><dd>${escapar(d.nombre)}</dd>
      <dt>Dirección</dt><dd>${escapar(d.direccion) || "—"}</dd>
      <dt>Ubicación</dt><dd>${d.lat.toFixed(6)}, ${d.lng.toFixed(6)}</dd>
      <dt>Cuadra</dt><dd>${d.cuadra ? "marcada en el mapa" : "sin marcar (solo se muestra el punto)"}</dd>
      <dt>Foto</dt><dd>${w.referencia.ancho} × ${w.referencia.alto}${w.referencia.nueva ? " (nueva)" : ""}</dd>
      <dt>Lugares</dt><dd>${validos} válido${validos === 1 ? "" : "s"} · ${prohibidos} zona${prohibidos === 1 ? "" : "s"} prohibida${prohibidos === 1 ? "" : "s"}</dd>
      <dt>Estado</dt><dd>${d.activa ? "Activa" : "Desactivada"}</dd>
      <dt>Fotos</dt><dd>${textoFuente(d.fuente)}</dd>
    </dl>`;
  const key = w.creada?.api_key || w.apiKey;
  if (d.fuente.tipo !== "envio" && w.creada) {
    html += `<p class="suave chico">Listo: en unos segundos el servidor empieza a tomar fotos de la cámara. El estado de la captura se ve en la lista de cámaras.</p>`;
  }
  if (key && d.fuente.tipo === "envio") {
    const id = $("campo-id").value.trim();
    const servidor = location.origin;
    html += `
      <h2>Conexión de la cámara</h2>
      <p class="suave chico">La cámara manda fotos con un POST a esta URL, con su API key en el header <code>X-Camera-Key</code>.</p>
      <dl>
        <dt>URL</dt><dd><code>${servidor}/api/camaras/${id}/fotos</code></dd>
        <dt>API key</dt><dd><span class="secreto">${escapar(key)}</span></dd>
      </dl>
      <p class="suave chico">Para una cámara en otra casa: pasale a esa persona la carpeta <code>cliente_camara/</code> del proyecto
        junto con este archivo, guardado adentro de esa carpeta. Después hace doble clic en <code>iniciar_camara.bat</code>.</p>
      <div class="fila-botones">
        <button id="descargar-ini" class="primario" type="button">Descargar camara.ini</button>
        ${w.modo === "editar" && !w.creada ? `<button id="regenerar" class="boton chico peligro" type="button">Generar una API key nueva</button>` : ""}
      </div>
      ${/^https?:\/\/(localhost|127\.0\.0\.1)/.test(servidor)
        ? `<p class="error">Estás entrando por ${escapar(servidor)}: ese link solo funciona en esta compu. Para una cámara en otra casa,
             abrí la app con <code>iniciar_publico.bat</code> y descargá el archivo entrando desde el link público.</p>` : ""}
      <p class="suave chico">Para probar sin cámara: copiá fotos a <code>camaras/${id}/fotos/</code>, o usá "Mandar foto de prueba" en la lista.</p>`;
  }
  if (w.modo === "editar" && w.espaciosCambiaron && !w.creada) {
    html += `<p class="error">Cambiaste la foto o los lugares: al guardar se reinicia el estado de esta cámara (vuelve a contar desde la próxima foto).</p>`;
  }
  html += "</div>";
  $("resumen").innerHTML = html;
  const descargar = $("descargar-ini");
  if (descargar) descargar.onclick = () => descargarIni($("campo-id").value.trim(), key);
  const regen = $("regenerar");
  if (regen) regen.onclick = async () => {
    if (!confirm("La cámara va a dejar de poder mandar fotos hasta que le cargues la key nueva. ¿Seguir?")) return;
    try { w.apiKey = (await api(`/api/admin/camaras/${w.id}/regenerar_key`, { method: "POST" })).api_key; mostrarResumen(); }
    catch (e) { errorPaso(e.message); }
  };
}

async function guardar() {
  const boton = $("siguiente");
  boton.disabled = true;
  const espacios = w.espacios.map((e) => ({ tipo: e.tipo, puntos: e.puntos }));
  try {
    if (w.modo === "crear") {
      const fd = new FormData();
      fd.append("id", $("campo-id").value.trim());
      fd.append("datos", JSON.stringify(datosFormulario()));
      fd.append("espacios", JSON.stringify(espacios));
      fd.append("referencia", w.referencia.blob, "referencia.jpg");
      w.creada = await api("/api/admin/camaras", { method: "POST", body: fd });
      w.id = w.creada.id;
      avisar("Cámara creada");
    } else {
      await api(`/api/admin/camaras/${w.id}`, { method: "PUT", body: datosFormulario() });
      if (w.referencia.nueva) {
        const fd = new FormData();
        fd.append("referencia", w.referencia.blob, "referencia.jpg");
        await api(`/api/admin/camaras/${w.id}/referencia`, { method: "POST", body: fd });
      }
      if (w.espaciosCambiaron) {
        await api(`/api/admin/camaras/${w.id}/espacios`, { method: "PUT", body: espacios });
      }
      w.creada = { api_key: w.apiKey };
      avisar("Cambios guardados");
    }
    irAPaso(5);
  } catch (e) {
    errorPaso(e.message);
  } finally {
    boton.disabled = false;
  }
}

// ---------------------------------------------------------------------------

mostrarVista(token ? "lista" : "login");
