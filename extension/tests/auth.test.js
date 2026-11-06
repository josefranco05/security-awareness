// node --test "extension/tests/*.test.js"
const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { join } = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const contexto = {};
vm.createContext(contexto);
vm.runInContext(readFileSync(join(__dirname, "..", "auth.js"), "utf8"), contexto);
const auth = (cabecera) => ({ ...contexto.authDesdeCabecera(cabecera) });

test("sin cabecera todo queda unknown", () => {
  assert.deepEqual(auth(null), { spf: "unknown", dkim: "unknown", dmarc: "unknown" });
});

test("cabecera real de Gmail", () => {
  const cabecera = "mx.google.com; dkim=pass header.i=@a.com header.s=s1 header.b=abc; " +
    "spf=softfail (google.com: domain of transitioning x@a.com does not designate 1.2.3.4 as permitted sender) " +
    "smtp.mailfrom=x@a.com; dmarc=fail (p=REJECT sp=REJECT dis=NONE) header.from=a.com";
  assert.deepEqual(auth(cabecera), { spf: "unknown", dkim: "pass", dmarc: "fail" });
});

for (const [crudo, esperado] of [
  ["pass", "pass"], ["fail", "fail"], ["hardfail", "fail"],
  ["neutral", "none"], ["none", "none"], ["bestguesspass", "none"],
  ["softfail", "unknown"], ["temperror", "unknown"], ["permerror", "unknown"],
  ["policy", "unknown"], ["inventado", "unknown"], ["constructor", "unknown"],
]) {
  test(`${crudo} -> ${esperado}`, () => {
    assert.equal(auth(`mx.google.com; spf=${crudo} smtp.mailfrom=a.com`).spf, esperado);
  });
}

test("no distingue mayúsculas", () => {
  assert.equal(auth("mx.google.com; DMARC=FAIL header.from=a.com").dmarc, "fail");
});

test("con varias firmas DKIM gana cualquier pass", () => {
  assert.equal(auth("mx.google.com; dkim=fail header.i=@a.com; dkim=pass header.i=@b.com").dkim, "pass");
  assert.equal(auth("mx.google.com; dkim=pass header.i=@b.com; dkim=fail header.i=@a.com").dkim, "pass");
});

test("ignora resultados escritos en comentarios y cadenas", () => {
  const cabecera = 'mx.google.com; spf=fail (; dkim=pass; (dmarc=pass)) smtp.mailfrom="; dmarc=pass"; dmarc=fail';
  assert.deepEqual(auth(cabecera), { spf: "fail", dkim: "unknown", dmarc: "fail" });
});

test("no acepta un valor en el medio de una propiedad", () => {
  assert.equal(auth("mx.google.com; x-spf=pass; foo spf=pass").spf, "unknown");
});
