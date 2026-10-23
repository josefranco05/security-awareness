(function (global) {
    "use strict";

    var TOKEN_KEY = "access_token";
    var currentUser = null;
    var cachedToken = null;
    var hasCachedUser = false;
    var fetchPromise = null;
    var pendingToken = null;
    var requestVersion = 0;

    function getToken() {
        return global.localStorage.getItem(TOKEN_KEY);
    }

    function clearUserCache() {
        requestVersion += 1;
        currentUser = null;
        cachedToken = null;
        hasCachedUser = false;
        fetchPromise = null;
        pendingToken = null;
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
        var token = getToken();
        if (!token) {
            if (hasCachedUser || fetchPromise) {
                clearUserCache();
            }
            return null;
        }

        if (hasCachedUser && cachedToken === token) {
            return currentUser;
        }

        if (fetchPromise && pendingToken === token) {
            return fetchPromise;
        }

        var version = ++requestVersion;
        pendingToken = token;
        var request;

        request = (async function () {
            try {
                var response = await global.fetch("/api/usuarios/me", {
                    headers: {
                        "Accept": "application/json",
                        "Authorization": "Bearer " + token
                    }
                });

                if (response.status === 401) {
                    if (getToken() === token) {
                        global.localStorage.removeItem(TOKEN_KEY);
                        clearUserCache();
                    }
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

                if (version !== requestVersion || getToken() !== token) {
                    return null;
                }

                currentUser = user;
                cachedToken = token;
                hasCachedUser = true;
                return currentUser;
            } finally {
                if (fetchPromise === request) {
                    fetchPromise = null;
                    pendingToken = null;
                }
            }
        })();

        fetchPromise = request;
        return request;
    }

    function setToken(token) {
        if (typeof token !== "string" || !token.trim()) {
            throw new TypeError("El token debe ser una cadena no vacía.");
        }
        global.localStorage.setItem(TOKEN_KEY, token.trim());
        clearUserCache();
    }

    function logout() {
        clearUserCache();
        global.localStorage.removeItem(TOKEN_KEY);
        global.location.assign("/");
    }

    global.Auth = Object.freeze({
        getCurrentUser: getCurrentUser,
        getToken: getToken,
        setToken: setToken,
        clearUserCache: clearUserCache,
        logout: logout
    });

    global.addEventListener("storage", function (event) {
        if (event.key === TOKEN_KEY || event.key === null) {
            clearUserCache();
        }
    });
})(window);
