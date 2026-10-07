// Modo usuario: mapa + "Buscar lugares cerca mío".

const COLORES = {
  "HAY LUGAR": "#1e8e3e",
  "CASI LLENO": "#f9ab00",
  "LLENO": "#d93025",
  "SIN DATOS": "#80868b",
};
const REFRESCO_MS = 30000;
const CENTRO_INICIAL = [-34.6037, -58.3816]; // Buenos Aires

const mapa = L.map("mapa", { zoomControl: false, zoomSnap: 0.25 }).setView(CENTRO_INICIAL, 13);
L.control.zoom({ position: "topright" }).addTo(mapa);
L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 19,
  attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
}).addTo(mapa);

const capaCuadras = L.layerGroup().addTo(mapa);
let marcadorYo = null;
let circuloRadio = null;
let puntoBusqueda = null;   // [lat, lng] de la última búsqueda
let eligiendoEnMapa = false;
let temporizador = null;
const porId = {};           // id -> { marcador, linea, datos }

const $ = (id) => document.getElementById(id);
const botonBuscar = $("buscar");
const radioSel = $("radio");

function avisar(texto, ms = 4000) {
  const a = $("aviso");
  a.textContent = texto;
  a.hidden = false;
  clearTimeout(avisar._t);
  if (ms) avisar._t = setTimeout(() => (a.hidden = true), ms);
}

function haceCuanto(min) {
  if (min == null) return "sin datos todavía";
  if (min < 1) return "hace menos de 1 min";
  if (min < 60) return `hace ${Math.round(min)} min`;
  const h = min / 60;
  if (h < 24) return `hace ${Math.round(h)} h`;
  return `hace ${Math.round(h / 24)} días`;
}

function distanciaTxt(m) {
  return m < 1000 ? `${m} m` : `${(m / 1000).toFixed(1)} km`;
}

function escapar(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function textoLibres(c) {
  if (c.estado === "SIN DATOS" || c.libres == null) return "?";
  return c.libres;
}

// --- Ubicación ---

function pedirUbicacion() {
  return new Promise((resolve, reject) => {
    if (!navigator.geolocation) return reject(new Error("sin geolocalización"));
    navigator.geolocation.getCurrentPosition(
      (pos) => resolve([pos.coords.latitude, pos.coords.longitude]),
      reject,
      { enableHighAccuracy: true, timeout: 10000, maximumAge: 30000 }
    );
  });
}

function ponerYo(punto) {
  const icono = L.divIcon({ className: "", html: '<div class="yo"></div>', iconSize: [18, 18], iconAnchor: [9, 9] });
  if (marcadorYo) marcadorYo.setLatLng(punto);
  else marcadorYo = L.marker(punto, { icon: icono, zIndexOffset: 1000, title: "Vos estás acá" }).addTo(mapa);
  const radio = Number(radioSel.value);
  if (circuloRadio) circuloRadio.setLatLng(punto).setRadius(radio);
  else circuloRadio = L.circle(punto, { radius: radio, color: "#1a73e8", weight: 1.5, dashArray: "6 6", fillOpacity: 0.05 }).addTo(mapa);
}

botonBuscar.addEventListener("click", async () => {
  botonBuscar.disabled = true;
  botonBuscar.querySelector("span").textContent = "Buscando tu ubicación…";
  try {
    const punto = await pedirUbicacion();
    eligiendoEnMapa = false;
    await buscar(punto, true);
  } catch (e) {
    eligiendoEnMapa = true;
    avisar("No pudimos obtener tu ubicación. Tocá el mapa en el lugar donde estás.", 0);
  } finally {
    botonBuscar.disabled = false;
    botonBuscar.querySelector("span").textContent = "Buscar lugares cerca mío";
  }
});

mapa.on("click", (e) => {
  if (!eligiendoEnMapa) return;
  eligiendoEnMapa = false;
  $("aviso").hidden = true;
  buscar([e.latlng.lat, e.latlng.lng], true);
});

radioSel.addEventListener("change", () => {
  if (puntoBusqueda) buscar(puntoBusqueda, true);
});

// --- Búsqueda ---

async function buscar(punto, encuadrar) {
  puntoBusqueda = punto;
  ponerYo(punto);
  const radio = Number(radioSel.value);
  let datos;
  try {
    const r = await fetch(`/api/cerca?lat=${punto[0]}&lng=${punto[1]}&radio=${radio}`);
    if (!r.ok) throw new Error(r.status);
    datos = await r.json();
  } catch (e) {
    avisar("No se pudo consultar el servidor. Probá de nuevo en un rato.");
    return;
  }
  dibujar(datos.cuadras);
  listar(datos.cuadras, radio);

  if (encuadrar) {
    const limites = circuloRadio.getBounds();
    datos.cuadras.forEach((c) => limites.extend([c.lat, c.lng]));
    // Que la lista de abajo y el botón no tapen la zona buscada.
    const abajo = $("panel").offsetHeight + botonBuscar.offsetHeight + 40;
    mapa.fitBounds(limites, { paddingTopLeft: [30, 110], paddingBottomRight: [30, abajo], maxZoom: 17 });
  }

  const conLugar = datos.cuadras.filter((c) => c.estado !== "SIN DATOS" && c.libres > 0);
  const totalLibres = conLugar.reduce((s, c) => s + c.libres, 0);
  $("subtitulo").textContent = datos.cuadras.length
    ? `${totalLibres} lugar${totalLibres === 1 ? "" : "es"} libre${totalLibres === 1 ? "" : "s"} en ${datos.cuadras.length} cuadra${datos.cuadras.length === 1 ? "" : "s"}`
    : "No hay cámaras en esta zona";

  clearTimeout(temporizador);
  temporizador = setTimeout(() => buscar(puntoBusqueda, false), REFRESCO_MS);
}

function popupHtml(c) {
  const color = COLORES[c.estado];
  const libres = c.estado === "SIN DATOS"
    ? `<div class="grande">Sin datos recientes</div>`
    : `<div class="grande">${c.libres} libre${c.libres === 1 ? "" : "s"} <span style="font-weight:500;font-size:14px">de ${c.total}</span><span class="chip" style="background:${color}">${c.estado}</span></div>`;
  const alerta = c.prohibidos_bloqueados
    ? `<div class="alerta">⚠ Hay ${c.prohibidos_bloqueados === 1 ? "una entrada de garage bloqueada" : c.prohibidos_bloqueados + " entradas de garage bloqueadas"}</div>`
    : "";
  const img = c.tiene_preview
    ? `<a href="/api/camaras/${encodeURIComponent(c.id)}/preview.jpg?t=${encodeURIComponent(c.actualizado_en || "")}" target="_blank" rel="noopener">
         <img src="/api/camaras/${encodeURIComponent(c.id)}/preview.jpg?t=${encodeURIComponent(c.actualizado_en || "")}" alt="Última foto de la cuadra"></a>`
    : "";
  return `<div class="pop">
      <h3>${escapar(c.nombre)}</h3>
      <div class="dir">${escapar(c.direccion)}${c.distancia_m != null ? " · a " + distanciaTxt(c.distancia_m) : ""}</div>
      ${libres}
      <div class="meta">Actualizado ${haceCuanto(c.minutos_desde_actualizacion)}</div>
      ${alerta}
      ${img}
      <a class="ir" href="https://www.google.com/maps/dir/?api=1&destination=${c.lat},${c.lng}" target="_blank" rel="noopener">Cómo llegar →</a>
    </div>`;
}

function dibujar(cuadras) {
  const abierto = Object.entries(porId).find(([, v]) => v.marcador.isPopupOpen())?.[0];
  capaCuadras.clearLayers();
  for (const k of Object.keys(porId)) delete porId[k];

  for (const c of cuadras) {
    const color = COLORES[c.estado];
    let linea = null;
    if (c.cuadra) {
      L.polyline(c.cuadra, { color: "#fff", weight: 11, opacity: 0.9 }).addTo(capaCuadras);
      linea = L.polyline(c.cuadra, { color, weight: 7, opacity: 0.95, lineCap: "round" }).addTo(capaCuadras);
    }
    const icono = L.divIcon({
      className: "",
      html: `<div class="marcador" style="background:${color}"><span class="p">P</span>${textoLibres(c)}</div>`,
      iconSize: [0, 0],
    });
    const marcador = L.marker([c.lat, c.lng], { icon: icono, title: c.nombre }).addTo(capaCuadras);
    marcador.bindPopup(popupHtml(c), { maxWidth: 300, autoPanPaddingTopLeft: [20, 120], autoPanPaddingBottomRight: [20, 20] });
    marcador.on("popupopen", (e) => {
      const img = e.popup.getElement()?.querySelector("img");
      if (img && !img.complete) img.onload = () => e.popup.update();
    });
    if (linea) linea.on("click", () => marcador.openPopup());
    porId[c.id] = { marcador, linea, datos: c };
  }
  if (abierto && porId[abierto]) porId[abierto].marcador.openPopup();
}

function listar(cuadras, radio) {
  const lista = $("lista");
  lista.innerHTML = "";
  $("panel-titulo").textContent = `Cuadras a menos de ${distanciaTxt(radio)}`;
  if (!cuadras.length) {
    lista.innerHTML = `<li class="vacio">No hay cámaras en este radio. Probá con un radio más grande.</li>`;
  }
  for (const c of cuadras) {
    const li = document.createElement("li");
    const color = COLORES[c.estado];
    const detalle = c.estado === "SIN DATOS"
      ? "Sin datos recientes"
      : `${c.libres} de ${c.total} libres · ${c.estado.toLowerCase()}`;
    li.innerHTML = `
      <div class="libres-badge" style="background:${color}">${textoLibres(c)}<small>libres</small></div>
      <div class="item-texto">
        <strong>${escapar(c.nombre)}</strong>
        <span>${detalle} · a ${distanciaTxt(c.distancia_m)}</span>
      </div>`;
    li.addEventListener("click", () => {
      mapa.flyTo([c.lat, c.lng], Math.max(mapa.getZoom(), 17), { duration: 0.6 });
      porId[c.id]?.marcador.openPopup();
    });
    lista.appendChild(li);
  }
  $("panel").hidden = false;
  document.body.classList.add("con-panel");
  document.body.style.setProperty("--alto-panel", `${$("panel").offsetHeight}px`);
}

$("cerrar-panel").addEventListener("click", () => {
  $("panel").hidden = true;
  document.body.classList.remove("con-panel");
});
