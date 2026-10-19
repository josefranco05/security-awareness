/* ============================================================================
   Security Awareness — utilidades de UI
   ----------------------------------------------------------------------------
   Modales:
     showModal(id)   abre el modal y devuelve el elemento
     hideModal(id)   cierra el modal indicado (o el último abierto)

   Se puede usar desde JS o de forma declarativa en el HTML:
     <button data-modal-open="modalX">Abrir</button>
     <button data-modal-close>Cancelar</button>
     <div class="modal-backdrop" data-modal-close></div>

   Pestañas: contenedor [data-tabs] con botones [data-tab="clave"] y
   paneles [data-tab-panel="clave"]. Se inicializan solas al cargar.
   ========================================================================== */
(function (global) {
    "use strict";

    var openStack = [];
    var lastFocused = null;

    function getErrorMessage(error) {
        if (typeof error.detail === "string") {
            return error.detail;
        } else if (Array.isArray(error.detail)) {
            return error.detail.map((err) => err.msg).join(". ");
        }
        return "An error occurred. Please try again.";
    }

    function toArray(list) { return Array.prototype.slice.call(list || []); }

    function getModal(id) {
        return typeof id === "string" ? document.getElementById(id) : id;
    }

    function setVisible(element, visible) {
        if (!element) return;
        element.hidden = !visible;
        element.style.display = visible ? "" : "none";
    }

    var FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), ' +
        'select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

    function focusable(scope) {
        return toArray(scope.querySelectorAll(FOCUSABLE)).filter(function (el) {
            return el.offsetWidth > 0 || el.offsetHeight > 0;
        });
    }

    function showModal(id) {
        var modal = getModal(id);
        if (!modal || openStack.indexOf(modal) !== -1) return null;

        if (!openStack.length) {
            lastFocused = document.activeElement;
            document.body.classList.add("modal-open");
        }

        setVisible(modal, true);
        openStack.push(modal);

        var card = modal.querySelector(".modal-card") || modal;
        var first = focusable(card)[0];
        if (first) first.focus();

        modal.dispatchEvent(new CustomEvent("modal:open", { bubbles: true }));
        return modal;
    }

    function hideModal(id) {
        var modal = getModal(id) || openStack[openStack.length - 1];
        if (!modal) return null;

        var index = openStack.indexOf(modal);
        if (index !== -1) openStack.splice(index, 1);

        setVisible(modal, false);
        modal.dispatchEvent(new CustomEvent("modal:close", { bubbles: true }));

        if (!openStack.length) {
            document.body.classList.remove("modal-open");
            if (lastFocused && lastFocused.focus) lastFocused.focus();
            lastFocused = null;
        }
        return modal;
    }

    /* ---------------------------------------------------------- declarativo */
    document.addEventListener("click", function (event) {
        var opener = event.target.closest("[data-modal-open]");
        if (opener) {
            event.preventDefault();
            showModal(opener.getAttribute("data-modal-open"));
            return;
        }

        var closer = event.target.closest("[data-modal-close]");
        if (closer) {
            var modal = closer.closest(".modal");
            if (modal) {
                event.preventDefault();
                hideModal(modal);
            }
            return;
        }

        if (event.target.classList.contains("modal-backdrop")) {
            hideModal(event.target.closest(".modal"));
        }
    });

    document.addEventListener("keydown", function (event) {
        if (!openStack.length) return;

        var modal = openStack[openStack.length - 1];

        if (event.key === "Escape") {
            event.preventDefault();
            hideModal(modal);
            return;
        }

        if (event.key !== "Tab") return;

        var items = focusable(modal.querySelector(".modal-card") || modal);
        if (items.length < 2) return;

        var first = items[0];
        var last = items[items.length - 1];

        if (event.shiftKey && document.activeElement === first) {
            event.preventDefault();
            last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
            event.preventDefault();
            first.focus();
        }
    });

    /* ------------------------------------------------------------- pestañas */
    function initTabs(root) {
        toArray((root || document).querySelectorAll("[data-tabs]")).forEach(function (group) {
            var tabs = toArray(group.querySelectorAll("[data-tab]"));
            var panels = toArray(group.querySelectorAll("[data-tab-panel]"));

            tabs.forEach(function (tab) {
                tab.addEventListener("click", function () {
                    var target = tab.getAttribute("data-tab");

                    tabs.forEach(function (other) {
                        var active = other === tab;
                        other.classList.toggle("active", active);
                        other.setAttribute("aria-selected", active ? "true" : "false");
                    });

                    panels.forEach(function (panel) {
                        setVisible(panel, panel.getAttribute("data-tab-panel") === target);
                    });
                });
            });
        });
    }

    global.showModal = showModal;
    global.hideModal = hideModal;
    global.initTabs = initTabs;
    global.setVisible = global.setVisible || setVisible;
    global.getErrorMessage = getErrorMessage;

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", function () { initTabs(document); });
    } else {
        initTabs(document);
    }
})(window);
