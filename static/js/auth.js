(function (global) {
    "use strict";

    // El JWT vive en una cookie HttpOnly: este script nunca lo ve ni lo guarda.
    // El navegador la adjunta sola en cada petición al mismo origen.
    var currentUser = null;
    var fetchPromise = null;

    // Borra el token que pudo quedar de la versión anterior basada en localStorage.
    try {
        global.localStorage.removeItem("access_token");
    } catch (e) { }

    function clearUserCache() {
        currentUser = null;
        fetchPromise = null;
    }

    function getErrorMessage(body, statusCode) {
        if (body && typeof body.detail === "string") {
            return body.detail;
        }
        if (body && Array.isArray(body.detail)) {
            return body.detail.map(function (error) {
                return error.msg;
            }).join(". ");
        }
        return "No se pudo obtener el usuario actual (HTTP " + statusCode + ").";
    }

    async function readErrorBody(response) {
        var contentType = response.headers.get("content-type") || "";
        if (contentType.indexOf("application/json") === -1) {
            return null;
        }
        return response.json();
    }

    async function getCurrentUser() {
        if (currentUser) {
            return currentUser;
        }
        if (fetchPromise) {
            return fetchPromise;
        }

        var request = (async function () {
            try {
                var response = await global.fetch("/api/usuarios/me", {
                    headers: { "Accept": "application/json" },
                    credentials: "same-origin"
                });

                if (response.status === 401) {
                    return null;
                }

                if (!response.ok) {
                    var errorBody = await readErrorBody(response);
                    throw new Error(getErrorMessage(errorBody, response.status));
                }

                var user = await response.json();
                if (!user || typeof user !== "object" || Array.isArray(user)) {
                    throw new Error("La respuesta del usuario actual no tiene un formato válido.");
                }

                // Si se llamó clearUserCache() mientras tanto, no se guarda un usuario obsoleto.
                if (fetchPromise === request) {
                    currentUser = user;
                }
                return user;
            } finally {
                if (fetchPromise === request) {
                    fetchPromise = null;
                }
            }
        })();

        fetchPromise = request;
        return request;
    }

    async function logout() {
        clearUserCache();
        var response = await global.fetch("/api/usuarios/logout", {
            method: "POST",
            credentials: "same-origin"
        }).catch(function () { return null; });

        // La cookie solo la puede borrar el servidor: si falló, no se finge el logout.
        if (!response || !response.ok) {
            global.alert("No se pudo cerrar la sesión. Inténtalo nuevamente.");
            return;
        }
        global.location.assign("/");
    }

    async function authFetch(url, options) {
        // credentials va al final para que ninguna llamada pueda cambiarlo a "include".
        var response = await global.fetch(
            url,
            Object.assign({}, options, { credentials: "same-origin" })
        );

        if (response.status === 401) {
            clearUserCache();
            global.location.assign("/login");
        }
        return response;
    }

    global.Auth = Object.freeze({
        getCurrentUser: getCurrentUser,
        clearUserCache: clearUserCache,
        logout: logout,
        fetch: authFetch
    });
})(window);
