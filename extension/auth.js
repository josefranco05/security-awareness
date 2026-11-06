// Traduce Authentication-Results a los cuatro valores que acepta la API (ver ml/README.md).

// Map y no un objeto: el valor viene del correo, y "constructor" existiría en cualquier objeto.
const MAPA_AUTH = new Map([
  ["pass", "pass"],
  ["fail", "fail"],
  ["hardfail", "fail"],
  ["neutral", "none"],
  ["none", "none"],
  ["bestguesspass", "none"],
  // softfail no es "fail": ~all es muy común y el reenvío lo provoca, y spf=fail sube un nivel entero.
]);

function mapearAuth(valor) {
  return MAPA_AUTH.get(valor) ?? "unknown";
}

function authDesdeCabecera(cabecera) {
  const auth = { spf: "unknown", dkim: "unknown", dmarc: "unknown" };
  if (!cabecera) return auth;

  // Los comentarios y las cadenas pueden contener texto del remitente, como "dkim=pass".
  let limpia = cabecera.replace(/"(?:[^"\\]|\\.)*"/g, "");
  for (let previa; previa !== limpia; ) {
    previa = limpia;
    limpia = limpia.replace(/\([^()]*\)/g, "");
  }

  const vistos = new Set();
  for (const parte of limpia.split(";")) {
    const m = parte.match(/^\s*(spf|dkim|dmarc)\s*=\s*([a-z]+)/i);
    if (!m) continue;
    const campo = m[1].toLowerCase();
    const valor = mapearAuth(m[2].toLowerCase());
    // Puede haber varias firmas DKIM: gana cualquier pass. En lo demás cuenta el primer resultado.
    if (!vistos.has(campo) || (campo === "dkim" && valor === "pass")) auth[campo] = valor;
    vistos.add(campo);
  }
  return auth;
}
