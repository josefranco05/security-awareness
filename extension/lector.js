// leerCorreo se inyecta en la pestaña: Chrome serializa solo esta función, así que todo
// lo que usa debe estar dentro de ella. Corre en el mundo aislado, fuera del alcance del
// JavaScript de la página, y nunca recibe el token.

// Con tan poco texto el modelo no es fiable: un cuerpo casi vacío puede salir como phishing.
const MIN_CARACTERES_CUERPO = 100;

function cuerpoSuficiente(correo) {
  return correo.body.length >= MIN_CARACTERES_CUERPO;
}

async function leerCorreo(proveedor, ikGmail) {
  // 3 bytes UTF-8 como máximo por unidad UTF-16: siempre cabe en los 100 KB de la API.
  const MAX_CUERPO = 33000;
  const MAX_ASUNTO = 500;
  const MAX_URLS = 50;
  const MAX_URL = 2048;

  const visibles = (selector, raiz = document) =>
    [...raiz.querySelectorAll(selector)].filter((el) => el.offsetParent !== null);

  // Gmail añade su propia cabecera arriba del todo. Las de más abajo o de otro
  // servidor pudo escribirlas el remitente, así que no se aceptan.
  function cabeceraDelReceptor(crudo) {
    const encabezados = crudo.split(/\r?\n\r?\n/, 1)[0].replace(/\r?\n[ \t]+/g, " ");
    const valor = encabezados.match(/^Authentication-Results:[ \t]*(.*)$/im)?.[1];
    return valor && /^mx\.google\.com\s*;/i.test(valor) ? valor : null;
  }

  // Sin cabecera el análisis sigue: auth_results queda en unknown, que no cambia el resultado.
  async function cabeceraGmail(mensaje) {
    const id = mensaje.getAttribute("data-message-id")?.match(/msg-[a-z]:\d+/)?.[0];
    if (!id || !ikGmail) return null;
    try {
      const parametros = new URLSearchParams({ ik: ikGmail, view: "om", permmsgid: id });
      const r = await fetch(`${location.origin}${location.pathname}?${parametros}`);
      if (!r.ok) return null;
      const pagina = new DOMParser().parseFromString(await r.text(), "text/html");
      const crudo = pagina.querySelector("#raw_message_text")?.textContent;
      return crudo ? cabeceraDelReceptor(crudo) : null;
    } catch {
      return null;
    }
  }

  let asunto, cuerpo, cabecera = null;
  if (proveedor === "gmail") {
    const mensaje = visibles(".adn.ads").at(-1);
    if (!mensaje) return null;
    cuerpo = visibles(".a3s", mensaje).at(-1);
    asunto = visibles("h2.hP")[0];
    cabecera = await cabeceraGmail(mensaje);
  } else {
    cuerpo = visibles('[role="document"]').at(-1);
    asunto = visibles('[role="main"] [role="heading"]')[0];
  }

  const texto = cuerpo?.innerText?.trim();
  if (!texto) return null;

  const urls = [...cuerpo.querySelectorAll("a[href]")]
    .filter((a) => /^https?:/i.test(a.href) && a.href.length <= MAX_URL)
    .slice(0, MAX_URLS)
    .map((a) => ({ text: a.innerText.trim().slice(0, MAX_URL), href: a.href }));

  return {
    subject: (asunto?.innerText ?? "").trim().slice(0, MAX_ASUNTO),
    body: texto.slice(0, MAX_CUERPO),
    urls,
    cabecera,
  };
}
