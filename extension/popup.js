// El popup llama a la API por sí mismo: con host_permissions no le aplica CORS, así que
// no hace falta service worker. El token solo sale hacia API_URL.
const API_URL = "https://sentinel-web.nicedune-21623311.northcentralus.azurecontainerapps.io/api/phishing/analizar";

const PROVEEDORES = {
  "mail.google.com": "gmail",
  "outlook.live.com": "outlook",
  "outlook.office.com": "outlook",
  "outlook.office365.com": "outlook",
  "outlook.cloud.microsoft": "outlook",
};
const TITULOS = { alto: "Riesgo alto: probable phishing", medio: "Riesgo medio: sospechoso", bajo: "Riesgo bajo" };
const ERRORES = {
  401: "El token no es válido. Genera uno nuevo en Sentinel.",
  413: "El correo es demasiado grande para analizarlo.",
  422: "El servidor no aceptó los datos de este correo.",
  429: "Demasiados análisis. Intenta de nuevo en un momento.",
};

const $ = (id) => document.getElementById(id);

function mostrarEstado(texto) {
  $("estado").textContent = texto;
}

async function hayToken() {
  const { token } = await chrome.storage.local.get("token");
  return token || null;
}

async function pintarToken() {
  const guardado = Boolean(await hayToken());
  $("token").value = "";
  $("token").placeholder = guardado ? "Token guardado" : "Token de la extensión";
  $("eliminar").hidden = !guardado;
}

// En Gmail, ik solo existe en el JavaScript de la página, y hace falta para pedir las cabeceras.
async function leerIkGmail(tabId) {
  try {
    const [{ result }] = await chrome.scripting.executeScript({
      target: { tabId },
      world: "MAIN",
      func: () => window.GLOBALS?.[9] ?? null,
    });
    return typeof result === "string" && /^\w+$/.test(result) ? result : null;
  } catch {
    return null;
  }
}

async function leerPestaña() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  let proveedor;
  try {
    proveedor = PROVEEDORES[new URL(tab.url).hostname];
  } catch {}
  if (!proveedor) throw new Error("Abre un correo en Gmail u Outlook.");

  const ik = proveedor === "gmail" ? await leerIkGmail(tab.id) : null;
  const [{ result }] = await chrome.scripting.executeScript({
    target: { tabId: tab.id },
    func: leerCorreo,
    args: [proveedor, ik],
  });
  if (!result) throw new Error("No encontré ningún correo abierto en esta pestaña.");
  return result;
}

async function llamarApi(token, correo) {
  const respuesta = await fetch(API_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify({
      subject: correo.subject,
      body: correo.body,
      urls: correo.urls,
      auth_results: authDesdeCabecera(correo.cabecera),
    }),
    signal: AbortSignal.timeout(20000),
  });
  if (!respuesta.ok) throw new Error(ERRORES[respuesta.status] ?? "El servidor no pudo analizar el correo.");
  return respuesta.json();
}

function pintarResultado(resultado, conAuth) {
  // textContent, nunca innerHTML: las razones citan términos del correo.
  $("nivel").textContent = TITULOS[resultado.nivel] ?? resultado.nivel;
  $("nivel").className = resultado.nivel;
  $("razones").replaceChildren(
    ...resultado.razones.map((razon) => {
      const li = document.createElement("li");
      li.textContent = razon;
      return li;
    }),
  );
  $("aviso").hidden = conAuth;
  $("resultado").hidden = false;
}

async function analizar() {
  $("analizar").disabled = true;
  $("resultado").hidden = true;
  mostrarEstado("Analizando…");
  try {
    const token = await hayToken();
    if (!token) throw new Error("Primero guarda el token que generaste en Sentinel.");
    const correo = await leerPestaña();
    if (!cuerpoSuficiente(correo)) {
      throw new Error(`Este correo tiene menos de ${MIN_CARACTERES_CUERPO} caracteres y no se puede analizar. Eso no significa que sea seguro.`);
    }
    pintarResultado(await llamarApi(token, correo), Boolean(correo.cabecera));
    mostrarEstado("");
  } catch (e) {
    const sinRed = e instanceof TypeError || e.name === "TimeoutError";
    mostrarEstado(sinRed ? "No se pudo conectar con Sentinel." : e.message);
  } finally {
    $("analizar").disabled = false;
  }
}

$("form-token").addEventListener("submit", async (evento) => {
  evento.preventDefault();
  const token = $("token").value.trim();
  if (!token) return;
  await chrome.storage.local.set({ token });
  await pintarToken();
  mostrarEstado("Token guardado.");
});

$("eliminar").addEventListener("click", async () => {
  await chrome.storage.local.remove("token");
  await pintarToken();
  mostrarEstado("Token eliminado.");
});

$("analizar").addEventListener("click", analizar);

pintarToken();
