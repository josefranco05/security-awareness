// node --test "extension/tests/*.test.js"
const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { join } = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const contexto = {};
vm.createContext(contexto);
vm.runInContext(readFileSync(join(__dirname, "..", "lector.js"), "utf8"), contexto);

for (const [largo, esperado] of [[0, false], [99, false], [100, true], [101, true]]) {
  test(`un cuerpo de ${largo} caracteres ${esperado ? "se envía" : "no se envía"}`, () => {
    assert.equal(contexto.cuerpoSuficiente({ body: "a".repeat(largo) }), esperado);
  });
}
