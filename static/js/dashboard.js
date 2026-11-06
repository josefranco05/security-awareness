/* Gráficas del dashboard. Los datos llegan del servidor en #datos-graficas;
   una tarjeta sin datos no tiene <canvas> y se omite. */
(function () {
    "use strict";

    var MAX_CARACTERES_NOMBRE = 18;
    var datos = JSON.parse(document.getElementById("datos-graficas").textContent);
    var estilos = getComputedStyle(document.documentElement);

    function token(nombre) {
        return estilos.getPropertyValue(nombre).trim();
    }

    var COLOR = {
        alto: token("--chart-alto"),
        medio: token("--chart-medio"),
        bajo: token("--chart-bajo"),
        pendiente: token("--chart-pendiente")
    };

    Chart.defaults.font.family = token("--font");
    Chart.defaults.color = token("--text-secondary");
    Chart.defaults.animation = false;
    Chart.defaults.maintainAspectRatio = false;
    Chart.defaults.plugins.legend.position = "bottom";
    Chart.defaults.plugins.legend.labels.usePointStyle = true;
    Chart.defaults.plugins.legend.labels.boxHeight = 8;

    function serie(etiqueta, valores, color) {
        return {
            label: etiqueta,
            data: valores,
            backgroundColor: color,
            // El borde del color de la tarjeta separa los segmentos apilados.
            borderColor: token("--bg-surface"),
            borderWidth: 2,
            borderRadius: 4,
            maxBarThickness: 28
        };
    }

    function ejeConteo() {
        return {
            beginAtZero: true,
            ticks: { precision: 0 },
            grid: { color: token("--border-soft") },
            border: { display: false }
        };
    }

    function ejeCategorias(opciones) {
        return Object.assign({ grid: { display: false }, border: { color: token("--border") } }, opciones);
    }

    function dibujar(id, config) {
        var lienzo = document.getElementById(id);
        if (lienzo) new Chart(lienzo, config);
    }

    function sinCeros(item) {
        return item.parsed[item.chart.options.indexAxis === "y" ? "x" : "y"] !== 0;
    }

    dibujar("chart-detecciones", {
        type: "bar",
        data: {
            labels: datos.detecciones.dias,
            datasets: [
                serie("Alto", datos.detecciones.alto, COLOR.alto),
                serie("Medio", datos.detecciones.medio, COLOR.medio),
                serie("Bajo", datos.detecciones.bajo, COLOR.bajo)
            ]
        },
        options: {
            interaction: { mode: "index", intersect: false },
            plugins: { tooltip: { filter: sinCeros } },
            scales: {
                x: ejeCategorias({ stacked: true, ticks: { maxTicksLimit: 8, maxRotation: 0 } }),
                y: Object.assign(ejeConteo(), { stacked: true })
            }
        }
    });

    dibujar("chart-campanas", {
        type: "bar",
        data: {
            labels: datos.campanas.nombres,
            datasets: [
                serie("Entregados", datos.campanas.entregados, COLOR.bajo),
                serie("Pendientes", datos.campanas.pendientes, COLOR.pendiente),
                serie("Fallidos", datos.campanas.fallidos, COLOR.alto)
            ]
        },
        options: {
            indexAxis: "y",
            interaction: { mode: "index", intersect: false },
            plugins: { tooltip: { filter: sinCeros } },
            scales: {
                x: Object.assign(ejeConteo(), { stacked: true }),
                y: ejeCategorias({
                    stacked: true,
                    ticks: {
                        // El nombre completo se ve en el tooltip.
                        callback: function (valor) {
                            var nombre = this.getLabelForValue(valor);
                            return nombre.length > MAX_CARACTERES_NOMBRE
                                ? nombre.slice(0, MAX_CARACTERES_NOMBRE - 1) + "…"
                                : nombre;
                        }
                    }
                })
            }
        }
    });

    dibujar("chart-senales", {
        type: "bar",
        data: {
            labels: datos.senales.nombres,
            datasets: [serie("Correos", datos.senales.totales, COLOR.pendiente)]
        },
        options: {
            indexAxis: "y",
            plugins: { legend: { display: false } },
            scales: { x: ejeConteo(), y: ejeCategorias({}) }
        }
    });
})();
