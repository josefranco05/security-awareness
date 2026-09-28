/* ============================================================================
   Security Awareness — rich text editor helper
   ----------------------------------------------------------------------------
   Small dependency-free WYSIWYG editor used to craft the simulated phishing
   e-mail body on templates/campaigns.html.

   The markup declares the toolbar; this file wires the behaviour. Any element
   inside `toolbar` carrying `data-cmd="<execCommand>"` runs that command, and
   `data-action="<name>"` runs one of the extra actions handled below:
   fontSize, formatBlock, hiliteColor, removeFormat, clearFormat, toggleSource.
   Anything else (e.g. "toggleLink" / "toggleImage", which belong to the page)
   is ignored so the page can handle it with its own listener.

   Usage
   -----
     var rte = new RichTextEditor({
         editor  : document.getElementById("rteEditor"),
         toolbar : document.getElementById("rteToolbar"),
         onChange: function (html) { ... }
     });

     rte.getHtml()                        -> sanitized html string
     rte.setHtml(html)                    -> replaces the content
     rte.insertHtml(html)
     rte.insertImage(src, alt)
     rte.insertLink(url, text)            -> false when there is no selection
     rte.toggleSource()                   -> raw HTML textarea view on/off
     rte.isEmpty()
     RichTextEditor.sanitizeHtml(html)    -> static sanitizer

   Formatting uses document.execCommand(), which is deprecated but remains the
   only library-free way to format a contenteditable region. Its output favours
   classic presentational tags (<font face>, <font color>, <b>, <i>) because
   those are the most compatible with e-mail clients, which is where this HTML
   ends up. Every value leaving the editor is sanitized first.
   ========================================================================== */
(function (global) {
    "use strict";

    /* Elements removed outright: never rendered, never submitted. */
    var BLOCKED_ELEMENTS = [
        "script", "style", "iframe", "frame", "frameset", "object", "embed",
        "applet", "form", "input", "button", "select", "textarea", "option",
        "meta", "link", "base", "svg", "math", "template", "noscript", "title"
    ];

    /* Attributes whose value is a URL and therefore needs scheme validation. */
    var URL_ATTRIBUTES = {
        href: true, src: true, "xlink:href": true, action: true,
        formaction: true, poster: true, background: true, srcset: true, data: true
    };

    /* Commands whose pressed state is mirrored back onto the toolbar. */
    var TOGGLE_COMMANDS = {
        bold: true, italic: true, underline: true, strikeThrough: true,
        insertUnorderedList: true, insertOrderedList: true,
        justifyLeft: true, justifyCenter: true, justifyRight: true, justifyFull: true
    };

    /* Only raster formats: SVG data URLs can carry script. */
    var DATA_IMAGE_RE = /^data:image\/(png|jpe?g|gif|webp|bmp);base64,[a-z0-9+/=\s]+$/i;

    /* ------------------------------------------------------------- utilities */

    function toArray(list) {
        return Array.prototype.slice.call(list || []);
    }

    function escapeText(value) {
        return String(value == null ? "" : value)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;");
    }

    function escapeAttribute(value) {
        return escapeText(value).replace(/"/g, "&quot;");
    }

    /**
     * Scheme allow-list. Whitespace and control characters are removed before
     * comparing so "java\tscript:" style obfuscation does not slip through.
     */
    function isSafeUrl(value, allowDataImage) {
        var normalized = String(value == null ? "" : value)
            .replace(/[\u0000-\u0020\u00a0\u2028\u2029]+/g, "")
            .toLowerCase();

        if (!normalized) return true;

        if (normalized.indexOf("javascript:") === 0 ||
            normalized.indexOf("vbscript:") === 0 ||
            normalized.indexOf("file:") === 0) {
            return false;
        }

        if (normalized.indexOf("data:") === 0) {
            return !!allowDataImage && DATA_IMAGE_RE.test(normalized);
        }

        return true;
    }

    function sanitizeStyleValue(value) {
        var css = String(value == null ? "" : value);
        if (/expression\s*\(/i.test(css) ||
            /javascript:/i.test(css) ||
            /vbscript:/i.test(css) ||
            /behavior\s*:/i.test(css) ||
            /-moz-binding/i.test(css) ||
            /@import/i.test(css) ||
            /url\s*\(/i.test(css)) {
            return "";
        }
        return css.trim();
    }

    function sanitizeSrcset(value) {
        var candidates = String(value).split(",");
        for (var i = 0; i < candidates.length; i++) {
            var url = candidates[i].trim().split(/\s+/)[0];
            if (url && !isSafeUrl(url, false)) return null;
        }
        return value;
    }

    function cleanAttributes(element) {
        toArray(element.attributes).forEach(function (attribute) {
            var name = attribute.name.toLowerCase();
            var value = attribute.value;

            // Inline event handlers are always dropped.
            if (name.indexOf("on") === 0) {
                element.removeAttribute(attribute.name);
                return;
            }

            // id/name would enable DOM clobbering against the host page.
            if (name === "id" || name === "name" || name === "srcdoc") {
                element.removeAttribute(attribute.name);
                return;
            }

            if (name === "style") {
                var css = sanitizeStyleValue(value);
                if (css) {
                    element.setAttribute("style", css);
                } else {
                    element.removeAttribute(attribute.name);
                }
                return;
            }

            if (URL_ATTRIBUTES[name]) {
                var allowDataImage = name === "src" && element.tagName === "IMG";
                var safe = name === "srcset"
                    ? sanitizeSrcset(value)
                    : (isSafeUrl(value, allowDataImage) ? value : null);

                if (safe === null) {
                    element.removeAttribute(attribute.name);
                } else if (name === "srcset") {
                    element.setAttribute(attribute.name, safe);
                }
            }
        });
    }

    /**
     * Sanitizes a fragment inside a detached document, so nothing executes
     * while the markup is being inspected.
     */
    function sanitizeHtml(dirty) {
        var doc = document.implementation.createHTMLDocument("");
        var holder = doc.createElement("div");
        holder.innerHTML = dirty == null ? "" : String(dirty);

        BLOCKED_ELEMENTS.forEach(function (tag) {
            toArray(holder.querySelectorAll(tag)).forEach(function (node) {
                if (node.parentNode) node.parentNode.removeChild(node);
            });
        });

        // Comments can hide conditional-comment / mso payloads.
        var walker = doc.createTreeWalker(holder, 128 /* SHOW_COMMENT */, null);
        var comments = [];
        while (walker.nextNode()) comments.push(walker.currentNode);
        comments.forEach(function (node) {
            if (node.parentNode) node.parentNode.removeChild(node);
        });

        toArray(holder.querySelectorAll("*")).forEach(cleanAttributes);

        return holder.innerHTML;
    }

    /* ---------------------------------------------------------------- editor */

    function RichTextEditor(options) {
        options = options || {};

        if (!options.editor) {
            throw new Error("RichTextEditor: the 'editor' element is required.");
        }

        this.editor = options.editor;
        this.toolbar = options.toolbar || null;
        this.onChange = typeof options.onChange === "function" ? options.onChange : function () { };

        this.savedRange = null;
        this.sourceMode = false;
        this._sourceView = null;

        this._init();
    }

    RichTextEditor.sanitizeHtml = sanitizeHtml;

    RichTextEditor.prototype._init = function () {
        var self = this;

        // The caret lives in the contenteditable, but selects and colour inputs
        // steal focus when used, so remember the last valid range.
        ["keyup", "mouseup", "input", "focus"].forEach(function (name) {
            self.editor.addEventListener(name, function () { self._saveSelection(); });
        });

        document.addEventListener("selectionchange", function () {
            var selection = global.getSelection();
            if (!selection || selection.rangeCount === 0) return;
            if (self.editor.contains(selection.getRangeAt(0).commonAncestorContainer)) {
                self._saveSelection();
                self._syncToolbarState();
            }
        });

        this.editor.addEventListener("input", function () { self._emitChange(); });
        this.editor.addEventListener("paste", function (event) { self._handlePaste(event); });

        if (this.toolbar) this._bindToolbar();
    };

    RichTextEditor.prototype._bindToolbar = function () {
        var self = this;

        // Buttons: prevent the mousedown default so the selection is not
        // collapsed inside the editor before the command runs.
        this.toolbar.addEventListener("mousedown", function (event) {
            var control = event.target.closest("[data-cmd], [data-action]");
            if (!control) return;
            if (control.tagName === "BUTTON") event.preventDefault();
            self._saveSelection();
        });

        this.toolbar.addEventListener("click", function (event) {
            var button = event.target.closest("button[data-cmd], button[data-action]");
            if (!button) return;
            event.preventDefault();
            self._run(button.getAttribute("data-cmd"), button.getAttribute("data-action"), button, null);
        });

        this.toolbar.addEventListener("change", function (event) {
            var control = event.target.closest("[data-cmd], [data-action]");
            if (!control) return;
            self._run(control.getAttribute("data-cmd"), control.getAttribute("data-action"), control, control.value);
        });

        this.toolbar.addEventListener("input", function (event) {
            var control = event.target;
            if (control.matches && control.matches('input[type="color"]')) {
                self._run(control.getAttribute("data-cmd"), control.getAttribute("data-action"), control, control.value);
            }
        });
    };

    RichTextEditor.prototype._handlePaste = function (event) {
        var clipboard = event.clipboardData || global.clipboardData;
        if (!clipboard) return;

        event.preventDefault();

        var html = clipboard.getData("text/html");
        var text = clipboard.getData("text/plain");

        if (html) {
            this.insertHtml(sanitizeHtml(html));
        } else if (text) {
            this.insertHtml(escapeText(text).replace(/\r\n|\r|\n/g, "<br>"));
        }
    };

    RichTextEditor.prototype._saveSelection = function () {
        if (this.sourceMode) return;

        var selection = global.getSelection();
        if (!selection || selection.rangeCount === 0) return;

        var range = selection.getRangeAt(0);
        if (this.editor.contains(range.commonAncestorContainer)) {
            this.savedRange = range.cloneRange();
        }
    };

    RichTextEditor.prototype._restoreSelection = function () {
        if (this.sourceMode) return;

        this.editor.focus({ preventScroll: true });

        var selection = global.getSelection();
        if (!selection) return;

        if (this.savedRange && this.editor.contains(this.savedRange.commonAncestorContainer)) {
            selection.removeAllRanges();
            selection.addRange(this.savedRange);
            return;
        }

        // No stored range: place the caret at the end of the content.
        var range = document.createRange();
        range.selectNodeContents(this.editor);
        range.collapse(false);
        selection.removeAllRanges();
        selection.addRange(range);
        this.savedRange = range.cloneRange();
    };

    RichTextEditor.prototype._exec = function (command, value) {
        var supported = true;
        try {
            supported = !document.queryCommandSupported || document.queryCommandSupported(command);
        } catch (error) {
            supported = false;
        }

        if (!supported) return false;

        try {
            return document.execCommand(command, false, value === undefined ? null : value);
        } catch (error) {
            return false;
        }
    };

    RichTextEditor.prototype._run = function (command, action, control, value) {
        if (action) {
            this._runAction(action, control, value);
            return;
        }

        if (!command) return;

        this._restoreSelection();
        this._exec(command, value);
        this._emitChange();
        this._syncToolbarState();

        if (control && control.tagName === "SELECT") control.selectedIndex = 0;
    };

    RichTextEditor.prototype._runAction = function (action, control, value) {
        switch (action) {
            case "fontSize":
                if (!value) return;
                this._restoreSelection();
                this.applyFontSize(value);
                break;

            case "formatBlock":
                if (!value) return;
                this._restoreSelection();
                this._exec("formatBlock", value);
                this._emitChange();
                if (control && control.tagName === "SELECT") control.selectedIndex = 0;
                break;

            case "hiliteColor":
                this._restoreSelection();
                if (!this._exec("hiliteColor", value)) this._exec("backColor", value);
                this._emitChange();
                break;

            case "removeFormat":
            case "clearFormat":
                this._restoreSelection();
                this._exec("removeFormat");
                if (action === "clearFormat") this._exec("unlink");
                this._emitChange();
                break;

            case "toggleSource":
                this.toggleSource();
                break;

            default:
                // Not an editor action: the page owns it (toggleLink, toggleImage...).
                break;
        }
    };

    /**
     * execCommand("fontSize") only understands the legacy 1..7 scale, so apply
     * the sentinel size and then rewrite the produced <font> elements into
     * pixel-sized spans.
     */
    RichTextEditor.prototype.applyFontSize = function (pixels) {
        var size = parseInt(pixels, 10);
        if (!size || size < 8 || size > 96) return;

        this._exec("fontSize", "7");

        toArray(this.editor.querySelectorAll('font[size="7"]')).forEach(function (node) {
            var span = document.createElement("span");
            span.style.fontSize = size + "px";

            while (node.firstChild) span.appendChild(node.firstChild);
            if (node.parentNode) node.parentNode.replaceChild(span, node);
        });

        this._emitChange();
    };

    RichTextEditor.prototype.insertHtml = function (html) {
        if (!html) return;

        this._restoreSelection();

        var selection = global.getSelection();
        var range = selection && selection.rangeCount ? selection.getRangeAt(0) : null;

        if (!range || !this.editor.contains(range.commonAncestorContainer)) {
            this.editor.insertAdjacentHTML("beforeend", html);
            this._emitChange();
            return;
        }

        range.deleteContents();

        var fragment = range.createContextualFragment(html);
        var lastNode = fragment.lastChild;
        range.insertNode(fragment);

        if (lastNode) {
            range.setStartAfter(lastNode);
            range.collapse(true);
            selection.removeAllRanges();
            selection.addRange(range);
            this.savedRange = range.cloneRange();
        }

        this._emitChange();
    };

    RichTextEditor.prototype.insertImage = function (source, altText) {
        var attributes = ' src="' + escapeAttribute(source) + '"';
        attributes += ' alt="' + escapeAttribute(altText || "") + '"';
        attributes += ' style="max-width:100%;height:auto;"';

        this.insertHtml("<img" + attributes + ">");
    };

    /**
     * With `text`, inserts a brand new link. Without it, converts the current
     * selection into a link and returns false when there is no selection.
     */
    RichTextEditor.prototype.insertLink = function (url, text) {
        if (text) {
            this.insertHtml(
                '<a href="' + escapeAttribute(url) + '">' + escapeText(text) + "</a>"
            );
            return true;
        }

        this._restoreSelection();

        var selection = global.getSelection();
        if (!selection || selection.isCollapsed) return false;

        this._exec("createLink", url);
        this._emitChange();
        return true;
    };

    RichTextEditor.prototype.getHtml = function () {
        if (this.sourceMode && this._sourceView) {
            return sanitizeHtml(this._sourceView.value);
        }
        return sanitizeHtml(this.editor.innerHTML);
    };

    RichTextEditor.prototype.setHtml = function (html) {
        var clean = sanitizeHtml(html);

        if (this.sourceMode && this._sourceView) {
            this._sourceView.value = clean;
            return;
        }

        this.editor.innerHTML = clean;
        this.savedRange = null;
        this._emitChange();
    };

    RichTextEditor.prototype.isEmpty = function () {
        var scope = this.editor;

        // In source mode the live content sits in the textarea, so inspect a
        // parsed copy of it instead of the (stale) contenteditable.
        if (this.sourceMode && this._sourceView) {
            var doc = document.implementation.createHTMLDocument("");
            scope = doc.createElement("div");
            scope.innerHTML = sanitizeHtml(this._sourceView.value);
        }

        if (scope.querySelector("img")) return false;
        return scope.textContent.replace(/[\u200b\s\u00a0]/g, "") === "";
    };

    RichTextEditor.prototype.focus = function () {
        if (this.sourceMode && this._sourceView) {
            this._sourceView.focus();
            return;
        }
        this.editor.focus({ preventScroll: true });
    };

    /**
     * Swaps the WYSIWYG surface for a raw-HTML textarea. The raw view keeps the
     * "craft it with HTML tags" workflow that the screen had before.
     */
    RichTextEditor.prototype.toggleSource = function (force) {
        var self = this;
        var enable = typeof force === "boolean" ? force : !this.sourceMode;
        if (enable === this.sourceMode) return this.sourceMode;

        if (enable) {
            if (!this._sourceView) {
                this._sourceView = document.createElement("textarea");
                this._sourceView.className = "rte-source";
                this._sourceView.setAttribute("spellcheck", "false");
                this._sourceView.setAttribute("aria-label", "Código HTML del correo");
                this.editor.parentNode.insertBefore(this._sourceView, this.editor.nextSibling);

                // Editing the raw HTML must publish changes just like the
                // WYSIWYG surface does, otherwise the value the form submits
                // (and the validation that reads it) would stay stale.
                this._sourceView.addEventListener("input", function () {
                    self._emitChange();
                });
            }

            this._sourceView.value = sanitizeHtml(this.editor.innerHTML);
            this.editor.hidden = true;
            this._sourceView.hidden = false;
            this.sourceMode = true;
        } else {
            if (this._sourceView) {
                this.editor.innerHTML = sanitizeHtml(this._sourceView.value);
                this._sourceView.hidden = true;
            }
            this.editor.hidden = false;
            this.sourceMode = false;
            this.savedRange = null;
        }

        if (this.toolbar) {
            var button = this.toolbar.querySelector('[data-action="toggleSource"]');
            if (button) {
                button.classList.toggle("active", this.sourceMode);
                button.setAttribute("aria-pressed", this.sourceMode ? "true" : "false");
            }
        }

        this._emitChange();
        return this.sourceMode;
    };

    RichTextEditor.prototype._syncToolbarState = function () {
        if (!this.toolbar || this.sourceMode) return;

        toArray(this.toolbar.querySelectorAll("[data-cmd]")).forEach(function (control) {
            var command = control.getAttribute("data-cmd");
            if (!TOGGLE_COMMANDS[command]) return;

            var active = false;
            try {
                active = document.queryCommandState(command);
            } catch (error) {
                active = false;
            }

            control.classList.toggle("active", !!active);
            control.setAttribute("aria-pressed", active ? "true" : "false");
        });
    };

    RichTextEditor.prototype._emitChange = function () {
        this.onChange(this.getHtml());
    };

    global.RichTextEditor = RichTextEditor;
})(window);
