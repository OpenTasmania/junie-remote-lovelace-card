/*! SPDX-License-Identifier: MIT | Copyright (c) 2026 Peter Lawler */
/**
 * @license
 * Copyright 2019 Google LLC
 * SPDX-License-Identifier: BSD-3-Clause
 */
const X = globalThis, at = X.ShadowRoot && (X.ShadyCSS === void 0 || X.ShadyCSS.nativeShadow) && "adoptedStyleSheets" in Document.prototype && "replace" in CSSStyleSheet.prototype, ct = Symbol(), Ct = /* @__PURE__ */ new WeakMap();
let Lt = class {
  constructor(t, e, s) {
    if (this._$cssResult$ = !0, s !== ct) throw Error("CSSResult is not constructable. Use `unsafeCSS` or `css` instead.");
    this.cssText = t, this.t = e;
  }
  get styleSheet() {
    let t = this.o;
    const e = this.t;
    if (at && t === void 0) {
      const s = e !== void 0 && e.length === 1;
      s && (t = Ct.get(e)), t === void 0 && ((this.o = t = new CSSStyleSheet()).replaceSync(this.cssText), s && Ct.set(e, t));
    }
    return t;
  }
  toString() {
    return this.cssText;
  }
};
const Zt = (c) => new Lt(typeof c == "string" ? c : c + "", void 0, ct), Bt = (c, ...t) => {
  const e = c.length === 1 ? c[0] : t.reduce((s, i, r) => s + ((o) => {
    if (o._$cssResult$ === !0) return o.cssText;
    if (typeof o == "number") return o;
    throw Error("Value passed to 'css' function must be a 'css' function result: " + o + ". Use 'unsafeCSS' to pass non-literal values, but take care to ensure page security.");
  })(i) + c[r + 1], c[0]);
  return new Lt(e, c, ct);
}, Xt = (c, t) => {
  if (at) c.adoptedStyleSheets = t.map((e) => e instanceof CSSStyleSheet ? e : e.styleSheet);
  else for (const e of t) {
    const s = document.createElement("style"), i = X.litNonce;
    i !== void 0 && s.setAttribute("nonce", i), s.textContent = e.cssText, c.appendChild(s);
  }
}, Pt = at ? (c) => c : (c) => c instanceof CSSStyleSheet ? ((t) => {
  let e = "";
  for (const s of t.cssRules) e += s.cssText;
  return Zt(e);
})(c) : c;
/**
 * @license
 * Copyright 2017 Google LLC
 * SPDX-License-Identifier: BSD-3-Clause
 */
const { is: Yt, defineProperty: Qt, getOwnPropertyDescriptor: te, getOwnPropertyNames: ee, getOwnPropertySymbols: se, getPrototypeOf: ie } = Object, E = globalThis, Tt = E.trustedTypes, re = Tt ? Tt.emptyScript : "", st = E.reactiveElementPolyfillSupport, N = (c, t) => c, Y = { toAttribute(c, t) {
  switch (t) {
    case Boolean:
      c = c ? re : null;
      break;
    case Object:
    case Array:
      c = c == null ? c : JSON.stringify(c);
  }
  return c;
}, fromAttribute(c, t) {
  let e = c;
  switch (t) {
    case Boolean:
      e = c !== null;
      break;
    case Number:
      e = c === null ? null : Number(c);
      break;
    case Object:
    case Array:
      try {
        e = JSON.parse(c);
      } catch {
        e = null;
      }
  }
  return e;
} }, lt = (c, t) => !Yt(c, t), Ut = { attribute: !0, type: String, converter: Y, reflect: !1, useDefault: !1, hasChanged: lt };
Symbol.metadata ?? (Symbol.metadata = Symbol("metadata")), E.litPropertyMetadata ?? (E.litPropertyMetadata = /* @__PURE__ */ new WeakMap());
let H = class extends HTMLElement {
  static addInitializer(t) {
    this._$Ei(), (this.l ?? (this.l = [])).push(t);
  }
  static get observedAttributes() {
    return this.finalize(), this._$Eh && [...this._$Eh.keys()];
  }
  static createProperty(t, e = Ut) {
    if (e.state && (e.attribute = !1), this._$Ei(), this.prototype.hasOwnProperty(t) && ((e = Object.create(e)).wrapped = !0), this.elementProperties.set(t, e), !e.noAccessor) {
      const s = Symbol(), i = this.getPropertyDescriptor(t, s, e);
      i !== void 0 && Qt(this.prototype, t, i);
    }
  }
  static getPropertyDescriptor(t, e, s) {
    const { get: i, set: r } = te(this.prototype, t) ?? { get() {
      return this[e];
    }, set(o) {
      this[e] = o;
    } };
    return { get: i, set(o) {
      const a = i == null ? void 0 : i.call(this);
      r == null || r.call(this, o), this.requestUpdate(t, a, s);
    }, configurable: !0, enumerable: !0 };
  }
  static getPropertyOptions(t) {
    return this.elementProperties.get(t) ?? Ut;
  }
  static _$Ei() {
    if (this.hasOwnProperty(N("elementProperties"))) return;
    const t = ie(this);
    t.finalize(), t.l !== void 0 && (this.l = [...t.l]), this.elementProperties = new Map(t.elementProperties);
  }
  static finalize() {
    if (this.hasOwnProperty(N("finalized"))) return;
    if (this.finalized = !0, this._$Ei(), this.hasOwnProperty(N("properties"))) {
      const e = this.properties, s = [...ee(e), ...se(e)];
      for (const i of s) this.createProperty(i, e[i]);
    }
    const t = this[Symbol.metadata];
    if (t !== null) {
      const e = litPropertyMetadata.get(t);
      if (e !== void 0) for (const [s, i] of e) this.elementProperties.set(s, i);
    }
    this._$Eh = /* @__PURE__ */ new Map();
    for (const [e, s] of this.elementProperties) {
      const i = this._$Eu(e, s);
      i !== void 0 && this._$Eh.set(i, e);
    }
    this.elementStyles = this.finalizeStyles(this.styles);
  }
  static finalizeStyles(t) {
    const e = [];
    if (Array.isArray(t)) {
      const s = new Set(t.flat(1 / 0).reverse());
      for (const i of s) e.unshift(Pt(i));
    } else t !== void 0 && e.push(Pt(t));
    return e;
  }
  static _$Eu(t, e) {
    const s = e.attribute;
    return s === !1 ? void 0 : typeof s == "string" ? s : typeof t == "string" ? t.toLowerCase() : void 0;
  }
  constructor() {
    super(), this._$Ep = void 0, this.isUpdatePending = !1, this.hasUpdated = !1, this._$Em = null, this._$Ev();
  }
  _$Ev() {
    var t;
    this._$ES = new Promise((e) => this.enableUpdating = e), this._$AL = /* @__PURE__ */ new Map(), this._$E_(), this.requestUpdate(), (t = this.constructor.l) == null || t.forEach((e) => e(this));
  }
  addController(t) {
    var e;
    (this._$EO ?? (this._$EO = /* @__PURE__ */ new Set())).add(t), this.renderRoot !== void 0 && this.isConnected && ((e = t.hostConnected) == null || e.call(t));
  }
  removeController(t) {
    var e;
    (e = this._$EO) == null || e.delete(t);
  }
  _$E_() {
    const t = /* @__PURE__ */ new Map(), e = this.constructor.elementProperties;
    for (const s of e.keys()) this.hasOwnProperty(s) && (t.set(s, this[s]), delete this[s]);
    t.size > 0 && (this._$Ep = t);
  }
  createRenderRoot() {
    const t = this.shadowRoot ?? this.attachShadow(this.constructor.shadowRootOptions);
    return Xt(t, this.constructor.elementStyles), t;
  }
  connectedCallback() {
    var t;
    this.renderRoot ?? (this.renderRoot = this.createRenderRoot()), this.enableUpdating(!0), (t = this._$EO) == null || t.forEach((e) => {
      var s;
      return (s = e.hostConnected) == null ? void 0 : s.call(e);
    });
  }
  enableUpdating(t) {
  }
  disconnectedCallback() {
    var t;
    (t = this._$EO) == null || t.forEach((e) => {
      var s;
      return (s = e.hostDisconnected) == null ? void 0 : s.call(e);
    });
  }
  attributeChangedCallback(t, e, s) {
    this._$AK(t, s);
  }
  _$ET(t, e) {
    var r;
    const s = this.constructor.elementProperties.get(t), i = this.constructor._$Eu(t, s);
    if (i !== void 0 && s.reflect === !0) {
      const o = (((r = s.converter) == null ? void 0 : r.toAttribute) !== void 0 ? s.converter : Y).toAttribute(e, s.type);
      this._$Em = t, o == null ? this.removeAttribute(i) : this.setAttribute(i, o), this._$Em = null;
    }
  }
  _$AK(t, e) {
    var r, o;
    const s = this.constructor, i = s._$Eh.get(t);
    if (i !== void 0 && this._$Em !== i) {
      const a = s.getPropertyOptions(i), l = typeof a.converter == "function" ? { fromAttribute: a.converter } : ((r = a.converter) == null ? void 0 : r.fromAttribute) !== void 0 ? a.converter : Y;
      this._$Em = i;
      const p = l.fromAttribute(e, a.type);
      this[i] = p ?? ((o = this._$Ej) == null ? void 0 : o.get(i)) ?? p, this._$Em = null;
    }
  }
  requestUpdate(t, e, s, i = !1, r) {
    var o;
    if (t !== void 0) {
      const a = this.constructor;
      if (i === !1 && (r = this[t]), s ?? (s = a.getPropertyOptions(t)), !((s.hasChanged ?? lt)(r, e) || s.useDefault && s.reflect && r === ((o = this._$Ej) == null ? void 0 : o.get(t)) && !this.hasAttribute(a._$Eu(t, s)))) return;
      this.C(t, e, s);
    }
    this.isUpdatePending === !1 && (this._$ES = this._$EP());
  }
  C(t, e, { useDefault: s, reflect: i, wrapped: r }, o) {
    s && !(this._$Ej ?? (this._$Ej = /* @__PURE__ */ new Map())).has(t) && (this._$Ej.set(t, o ?? e ?? this[t]), r !== !0 || o !== void 0) || (this._$AL.has(t) || (this.hasUpdated || s || (e = void 0), this._$AL.set(t, e)), i === !0 && this._$Em !== t && (this._$Eq ?? (this._$Eq = /* @__PURE__ */ new Set())).add(t));
  }
  async _$EP() {
    this.isUpdatePending = !0;
    try {
      await this._$ES;
    } catch (e) {
      Promise.reject(e);
    }
    const t = this.scheduleUpdate();
    return t != null && await t, !this.isUpdatePending;
  }
  scheduleUpdate() {
    return this.performUpdate();
  }
  performUpdate() {
    var s;
    if (!this.isUpdatePending) return;
    if (!this.hasUpdated) {
      if (this.renderRoot ?? (this.renderRoot = this.createRenderRoot()), this._$Ep) {
        for (const [r, o] of this._$Ep) this[r] = o;
        this._$Ep = void 0;
      }
      const i = this.constructor.elementProperties;
      if (i.size > 0) for (const [r, o] of i) {
        const { wrapped: a } = o, l = this[r];
        a !== !0 || this._$AL.has(r) || l === void 0 || this.C(r, void 0, o, l);
      }
    }
    let t = !1;
    const e = this._$AL;
    try {
      t = this.shouldUpdate(e), t ? (this.willUpdate(e), (s = this._$EO) == null || s.forEach((i) => {
        var r;
        return (r = i.hostUpdate) == null ? void 0 : r.call(i);
      }), this.update(e)) : this._$EM();
    } catch (i) {
      throw t = !1, this._$EM(), i;
    }
    t && this._$AE(e);
  }
  willUpdate(t) {
  }
  _$AE(t) {
    var e;
    (e = this._$EO) == null || e.forEach((s) => {
      var i;
      return (i = s.hostUpdated) == null ? void 0 : i.call(s);
    }), this.hasUpdated || (this.hasUpdated = !0, this.firstUpdated(t)), this.updated(t);
  }
  _$EM() {
    this._$AL = /* @__PURE__ */ new Map(), this.isUpdatePending = !1;
  }
  get updateComplete() {
    return this.getUpdateComplete();
  }
  getUpdateComplete() {
    return this._$ES;
  }
  shouldUpdate(t) {
    return !0;
  }
  update(t) {
    this._$Eq && (this._$Eq = this._$Eq.forEach((e) => this._$ET(e, this[e]))), this._$EM();
  }
  updated(t) {
  }
  firstUpdated(t) {
  }
};
H.elementStyles = [], H.shadowRootOptions = { mode: "open" }, H[N("elementProperties")] = /* @__PURE__ */ new Map(), H[N("finalized")] = /* @__PURE__ */ new Map(), st == null || st({ ReactiveElement: H }), (E.reactiveElementVersions ?? (E.reactiveElementVersions = [])).push("2.1.2");
/**
 * @license
 * Copyright 2017 Google LLC
 * SPDX-License-Identifier: BSD-3-Clause
 */
const L = globalThis, Mt = (c) => c, Q = L.trustedTypes, zt = Q ? Q.createPolicy("lit-html", { createHTML: (c) => c }) : void 0, Dt = "$lit$", S = `lit$${Math.random().toFixed(9).slice(2)}$`, Wt = "?" + S, oe = `<${Wt}>`, z = document, B = () => z.createComment(""), D = (c) => c === null || typeof c != "object" && typeof c != "function", dt = Array.isArray, ne = (c) => dt(c) || typeof (c == null ? void 0 : c[Symbol.iterator]) == "function", it = `[ 	
\f\r]`, O = /<(?:(!--|\/[^a-zA-Z])|(\/?[a-zA-Z][^>\s]*)|(\/?$))/g, Rt = /-->/g, Ht = />/g, P = RegExp(`>|${it}(?:([^\\s"'>=/]+)(${it}*=${it}*(?:[^ 	
\f\r"'\`<>=]|("|')|))|$)`, "g"), It = /'/g, qt = /"/g, Gt = /^(?:script|style|textarea|title)$/i, ae = (c) => (t, ...e) => ({ _$litType$: c, strings: t, values: e }), h = ae(1), R = Symbol.for("lit-noChange"), _ = Symbol.for("lit-nothing"), jt = /* @__PURE__ */ new WeakMap(), T = z.createTreeWalker(z, 129);
function Ft(c, t) {
  if (!dt(c) || !c.hasOwnProperty("raw")) throw Error("invalid template strings array");
  return zt !== void 0 ? zt.createHTML(t) : t;
}
const ce = (c, t) => {
  const e = c.length - 1, s = [];
  let i, r = t === 2 ? "<svg>" : t === 3 ? "<math>" : "", o = O;
  for (let a = 0; a < e; a++) {
    const l = c[a];
    let p, n, d = -1, u = 0;
    for (; u < l.length && (o.lastIndex = u, n = o.exec(l), n !== null); ) u = o.lastIndex, o === O ? n[1] === "!--" ? o = Rt : n[1] !== void 0 ? o = Ht : n[2] !== void 0 ? (Gt.test(n[2]) && (i = RegExp("</" + n[2], "g")), o = P) : n[3] !== void 0 && (o = P) : o === P ? n[0] === ">" ? (o = i ?? O, d = -1) : n[1] === void 0 ? d = -2 : (d = o.lastIndex - n[2].length, p = n[1], o = n[3] === void 0 ? P : n[3] === '"' ? qt : It) : o === qt || o === It ? o = P : o === Rt || o === Ht ? o = O : (o = P, i = void 0);
    const f = o === P && c[a + 1].startsWith("/>") ? " " : "";
    r += o === O ? l + oe : d >= 0 ? (s.push(p), l.slice(0, d) + Dt + l.slice(d) + S + f) : l + S + (d === -2 ? a : f);
  }
  return [Ft(c, r + (c[e] || "<?>") + (t === 2 ? "</svg>" : t === 3 ? "</math>" : "")), s];
};
class W {
  constructor({ strings: t, _$litType$: e }, s) {
    let i;
    this.parts = [];
    let r = 0, o = 0;
    const a = t.length - 1, l = this.parts, [p, n] = ce(t, e);
    if (this.el = W.createElement(p, s), T.currentNode = this.el.content, e === 2 || e === 3) {
      const d = this.el.content.firstChild;
      d.replaceWith(...d.childNodes);
    }
    for (; (i = T.nextNode()) !== null && l.length < a; ) {
      if (i.nodeType === 1) {
        if (i.hasAttributes()) for (const d of i.getAttributeNames()) if (d.endsWith(Dt)) {
          const u = n[o++], f = i.getAttribute(d).split(S), g = /([.?@])?(.*)/.exec(u);
          l.push({ type: 1, index: r, name: g[2], strings: f, ctor: g[1] === "." ? de : g[1] === "?" ? pe : g[1] === "@" ? he : tt }), i.removeAttribute(d);
        } else d.startsWith(S) && (l.push({ type: 6, index: r }), i.removeAttribute(d));
        if (Gt.test(i.tagName)) {
          const d = i.textContent.split(S), u = d.length - 1;
          if (u > 0) {
            i.textContent = Q ? Q.emptyScript : "";
            for (let f = 0; f < u; f++) i.append(d[f], B()), T.nextNode(), l.push({ type: 2, index: ++r });
            i.append(d[u], B());
          }
        }
      } else if (i.nodeType === 8) if (i.data === Wt) l.push({ type: 2, index: r });
      else {
        let d = -1;
        for (; (d = i.data.indexOf(S, d + 1)) !== -1; ) l.push({ type: 7, index: r }), d += S.length - 1;
      }
      r++;
    }
  }
  static createElement(t, e) {
    const s = z.createElement("template");
    return s.innerHTML = t, s;
  }
}
function q(c, t, e = c, s) {
  var o, a;
  if (t === R) return t;
  let i = s !== void 0 ? (o = e._$Co) == null ? void 0 : o[s] : e._$Cl;
  const r = D(t) ? void 0 : t._$litDirective$;
  return (i == null ? void 0 : i.constructor) !== r && ((a = i == null ? void 0 : i._$AO) == null || a.call(i, !1), r === void 0 ? i = void 0 : (i = new r(c), i._$AT(c, e, s)), s !== void 0 ? (e._$Co ?? (e._$Co = []))[s] = i : e._$Cl = i), i !== void 0 && (t = q(c, i._$AS(c, t.values), i, s)), t;
}
class le {
  constructor(t, e) {
    this._$AV = [], this._$AN = void 0, this._$AD = t, this._$AM = e;
  }
  get parentNode() {
    return this._$AM.parentNode;
  }
  get _$AU() {
    return this._$AM._$AU;
  }
  u(t) {
    const { el: { content: e }, parts: s } = this._$AD, i = ((t == null ? void 0 : t.creationScope) ?? z).importNode(e, !0);
    T.currentNode = i;
    let r = T.nextNode(), o = 0, a = 0, l = s[0];
    for (; l !== void 0; ) {
      if (o === l.index) {
        let p;
        l.type === 2 ? p = new G(r, r.nextSibling, this, t) : l.type === 1 ? p = new l.ctor(r, l.name, l.strings, this, t) : l.type === 6 && (p = new ue(r, this, t)), this._$AV.push(p), l = s[++a];
      }
      o !== (l == null ? void 0 : l.index) && (r = T.nextNode(), o++);
    }
    return T.currentNode = z, i;
  }
  p(t) {
    let e = 0;
    for (const s of this._$AV) s !== void 0 && (s.strings !== void 0 ? (s._$AI(t, s, e), e += s.strings.length - 2) : s._$AI(t[e])), e++;
  }
}
class G {
  get _$AU() {
    var t;
    return ((t = this._$AM) == null ? void 0 : t._$AU) ?? this._$Cv;
  }
  constructor(t, e, s, i) {
    this.type = 2, this._$AH = _, this._$AN = void 0, this._$AA = t, this._$AB = e, this._$AM = s, this.options = i, this._$Cv = (i == null ? void 0 : i.isConnected) ?? !0;
  }
  get parentNode() {
    let t = this._$AA.parentNode;
    const e = this._$AM;
    return e !== void 0 && (t == null ? void 0 : t.nodeType) === 11 && (t = e.parentNode), t;
  }
  get startNode() {
    return this._$AA;
  }
  get endNode() {
    return this._$AB;
  }
  _$AI(t, e = this) {
    t = q(this, t, e), D(t) ? t === _ || t == null || t === "" ? (this._$AH !== _ && this._$AR(), this._$AH = _) : t !== this._$AH && t !== R && this._(t) : t._$litType$ !== void 0 ? this.$(t) : t.nodeType !== void 0 ? this.T(t) : ne(t) ? this.k(t) : this._(t);
  }
  O(t) {
    return this._$AA.parentNode.insertBefore(t, this._$AB);
  }
  T(t) {
    this._$AH !== t && (this._$AR(), this._$AH = this.O(t));
  }
  _(t) {
    this._$AH !== _ && D(this._$AH) ? this._$AA.nextSibling.data = t : this.T(z.createTextNode(t)), this._$AH = t;
  }
  $(t) {
    var r;
    const { values: e, _$litType$: s } = t, i = typeof s == "number" ? this._$AC(t) : (s.el === void 0 && (s.el = W.createElement(Ft(s.h, s.h[0]), this.options)), s);
    if (((r = this._$AH) == null ? void 0 : r._$AD) === i) this._$AH.p(e);
    else {
      const o = new le(i, this), a = o.u(this.options);
      o.p(e), this.T(a), this._$AH = o;
    }
  }
  _$AC(t) {
    let e = jt.get(t.strings);
    return e === void 0 && jt.set(t.strings, e = new W(t)), e;
  }
  k(t) {
    dt(this._$AH) || (this._$AH = [], this._$AR());
    const e = this._$AH;
    let s, i = 0;
    for (const r of t) i === e.length ? e.push(s = new G(this.O(B()), this.O(B()), this, this.options)) : s = e[i], s._$AI(r), i++;
    i < e.length && (this._$AR(s && s._$AB.nextSibling, i), e.length = i);
  }
  _$AR(t = this._$AA.nextSibling, e) {
    var s;
    for ((s = this._$AP) == null ? void 0 : s.call(this, !1, !0, e); t !== this._$AB; ) {
      const i = Mt(t).nextSibling;
      Mt(t).remove(), t = i;
    }
  }
  setConnected(t) {
    var e;
    this._$AM === void 0 && (this._$Cv = t, (e = this._$AP) == null || e.call(this, t));
  }
}
class tt {
  get tagName() {
    return this.element.tagName;
  }
  get _$AU() {
    return this._$AM._$AU;
  }
  constructor(t, e, s, i, r) {
    this.type = 1, this._$AH = _, this._$AN = void 0, this.element = t, this.name = e, this._$AM = i, this.options = r, s.length > 2 || s[0] !== "" || s[1] !== "" ? (this._$AH = Array(s.length - 1).fill(new String()), this.strings = s) : this._$AH = _;
  }
  _$AI(t, e = this, s, i) {
    const r = this.strings;
    let o = !1;
    if (r === void 0) t = q(this, t, e, 0), o = !D(t) || t !== this._$AH && t !== R, o && (this._$AH = t);
    else {
      const a = t;
      let l, p;
      for (t = r[0], l = 0; l < r.length - 1; l++) p = q(this, a[s + l], e, l), p === R && (p = this._$AH[l]), o || (o = !D(p) || p !== this._$AH[l]), p === _ ? t = _ : t !== _ && (t += (p ?? "") + r[l + 1]), this._$AH[l] = p;
    }
    o && !i && this.j(t);
  }
  j(t) {
    t === _ ? this.element.removeAttribute(this.name) : this.element.setAttribute(this.name, t ?? "");
  }
}
class de extends tt {
  constructor() {
    super(...arguments), this.type = 3;
  }
  j(t) {
    this.element[this.name] = t === _ ? void 0 : t;
  }
}
class pe extends tt {
  constructor() {
    super(...arguments), this.type = 4;
  }
  j(t) {
    this.element.toggleAttribute(this.name, !!t && t !== _);
  }
}
class he extends tt {
  constructor(t, e, s, i, r) {
    super(t, e, s, i, r), this.type = 5;
  }
  _$AI(t, e = this) {
    if ((t = q(this, t, e, 0) ?? _) === R) return;
    const s = this._$AH, i = t === _ && s !== _ || t.capture !== s.capture || t.once !== s.once || t.passive !== s.passive, r = t !== _ && (s === _ || i);
    i && this.element.removeEventListener(this.name, this, s), r && this.element.addEventListener(this.name, this, t), this._$AH = t;
  }
  handleEvent(t) {
    var e;
    typeof this._$AH == "function" ? this._$AH.call(((e = this.options) == null ? void 0 : e.host) ?? this.element, t) : this._$AH.handleEvent(t);
  }
}
class ue {
  constructor(t, e, s) {
    this.element = t, this.type = 6, this._$AN = void 0, this._$AM = e, this.options = s;
  }
  get _$AU() {
    return this._$AM._$AU;
  }
  _$AI(t) {
    q(this, t);
  }
}
const rt = L.litHtmlPolyfillSupport;
rt == null || rt(W, G), (L.litHtmlVersions ?? (L.litHtmlVersions = [])).push("3.3.3");
const fe = (c, t, e) => {
  const s = (e == null ? void 0 : e.renderBefore) ?? t;
  let i = s._$litPart$;
  if (i === void 0) {
    const r = (e == null ? void 0 : e.renderBefore) ?? null;
    s._$litPart$ = i = new G(t.insertBefore(B(), r), r, void 0, e ?? {});
  }
  return i._$AI(c), i;
};
/**
 * @license
 * Copyright 2017 Google LLC
 * SPDX-License-Identifier: BSD-3-Clause
 */
const M = globalThis;
let I = class extends H {
  constructor() {
    super(...arguments), this.renderOptions = { host: this }, this._$Do = void 0;
  }
  createRenderRoot() {
    var e;
    const t = super.createRenderRoot();
    return (e = this.renderOptions).renderBefore ?? (e.renderBefore = t.firstChild), t;
  }
  update(t) {
    const e = this.render();
    this.hasUpdated || (this.renderOptions.isConnected = this.isConnected), super.update(t), this._$Do = fe(e, this.renderRoot, this.renderOptions);
  }
  connectedCallback() {
    var t;
    super.connectedCallback(), (t = this._$Do) == null || t.setConnected(!0);
  }
  disconnectedCallback() {
    var t;
    super.disconnectedCallback(), (t = this._$Do) == null || t.setConnected(!1);
  }
  render() {
    return R;
  }
};
var Nt;
I._$litElement$ = !0, I.finalized = !0, (Nt = M.litElementHydrateSupport) == null || Nt.call(M, { LitElement: I });
const ot = M.litElementPolyfillSupport;
ot == null || ot({ LitElement: I });
(M.litElementVersions ?? (M.litElementVersions = [])).push("4.2.2");
/**
 * @license
 * Copyright 2017 Google LLC
 * SPDX-License-Identifier: BSD-3-Clause
 */
const ge = { attribute: !0, type: String, converter: Y, reflect: !1, hasChanged: lt }, be = (c = ge, t, e) => {
  const { kind: s, metadata: i } = e;
  let r = globalThis.litPropertyMetadata.get(i);
  if (r === void 0 && globalThis.litPropertyMetadata.set(i, r = /* @__PURE__ */ new Map()), s === "setter" && ((c = Object.create(c)).wrapped = !0), r.set(e.name, c), s === "accessor") {
    const { name: o } = e;
    return { set(a) {
      const l = t.get.call(this);
      t.set.call(this, a), this.requestUpdate(o, l, c, !0, a);
    }, init(a) {
      return a !== void 0 && this.C(o, void 0, c, a), a;
    } };
  }
  if (s === "setter") {
    const { name: o } = e;
    return function(a) {
      const l = this[o];
      t.call(this, a), this.requestUpdate(o, l, c, !0, a);
    };
  }
  throw Error("Unsupported decorator location: " + s);
};
function pt(c) {
  return (t, e) => typeof e == "object" ? be(c, t, e) : ((s, i, r) => {
    const o = i.hasOwnProperty(r);
    return i.constructor.createProperty(r, s), o ? Object.getOwnPropertyDescriptor(i, r) : void 0;
  })(c, t, e);
}
/**
 * @license
 * Copyright 2017 Google LLC
 * SPDX-License-Identifier: BSD-3-Clause
 */
function v(c) {
  return pt({ ...c, state: !0, attribute: !1 });
}
var _e = Object.defineProperty, Vt = (c, t, e, s) => {
  for (var i = void 0, r = c.length - 1, o; r >= 0; r--)
    (o = c[r]) && (i = o(t, e, i) || i);
  return i && _e(t, e, i), i;
};
class ht extends I {
  setConfig(t) {
    this._config = { ...t };
  }
  _valueChanged(t) {
    if (!this._config)
      return;
    const e = t.target, s = e.getAttribute("data-field");
    if (!s)
      return;
    const i = e.value;
    if (this._config[s] === i)
      return;
    const r = {
      ...this._config,
      [s]: i
    };
    this._config = r, this.dispatchEvent(
      new CustomEvent("config-changed", {
        detail: { config: r },
        bubbles: !0,
        composed: !0
      })
    );
  }
  static get styles() {
    return Bt`
      .card-config {
        display: flex;
        flex-direction: column;
        gap: 16px;
        padding: 8px 0;
      }
      .form-row {
        display: flex;
        flex-direction: column;
        gap: 6px;
      }
      .form-label {
        font-weight: 500;
        font-size: 0.95rem;
        color: var(--primary-text-color, #212121);
      }
      .form-help {
        font-size: 0.8rem;
        color: var(--secondary-text-color, #757575);
      }
      .editor-input,
      .editor-select {
        box-sizing: border-box;
        width: 100%;
        padding: 10px 12px;
        border-radius: 4px;
        border: 1px solid var(--divider-color, #e0e0e0);
        background: var(--card-background-color, #ffffff);
        color: var(--primary-text-color, #212121);
        font-size: 0.95rem;
        outline: none;
        transition: border-color 0.2s;
      }
      .editor-input:focus,
      .editor-select:focus {
        border-color: var(--primary-color, #0288d1);
      }
    `;
  }
  render() {
    var s, i, r, o, a, l, p, n;
    if (!this.hass)
      return h`<div>Home Assistant instance not available</div>`;
    const t = ((s = this._config) == null ? void 0 : s.entity) || "", e = [];
    if (this.hass.states) {
      for (const [d, u] of Object.entries(this.hass.states))
        if (d.startsWith("sensor.") && (((i = u.attributes) == null ? void 0 : i.host_key) !== void 0 || ((r = u.attributes) == null ? void 0 : r.tunnel_id) !== void 0 || d.includes("junie"))) {
          const f = ((o = u.attributes) == null ? void 0 : o.friendly_name) || ((a = u.attributes) == null ? void 0 : a.title) || ((l = u.attributes) == null ? void 0 : l.host_key) || d;
          e.push({ id: d, name: `${f} (${d})` });
        }
    }
    return t && !e.some((d) => d.id === t) && e.unshift({ id: t, name: t }), h`
      <div class="card-config">
        <div class="form-row">
          <label class="form-label" for="entity-picker">Status Sensor Entity (required)</label>
          ${e.length > 0 ? h`
                <select
                  id="entity-picker"
                  class="editor-select"
                  data-field="entity"
                  .value="${t}"
                  @change="${this._valueChanged}"
                >
                  <option value="" disabled ?selected="${!t}">
                    Select a Junie Remote sensor
                  </option>
                  ${e.map(
      (d) => h`
                      <option
                        value="${d.id}"
                        ?selected="${d.id === t}"
                      >
                        ${d.name}
                      </option>
                    `
    )}
                </select>
              ` : ""}
          <input
            class="editor-input"
            type="text"
            data-field="entity"
            .value="${t}"
            placeholder="sensor.alice_linux_my_project_status"
            @input="${this._valueChanged}"
          />
          <span class="form-help">
            The Home Assistant sensor entity tracking your Junie CLI session.
          </span>
        </div>

        <div class="form-row">
          <label class="form-label" for="card-title">Card Title (optional)</label>
          <input
            id="card-title"
            class="editor-input"
            type="text"
            data-field="title"
            .value="${((p = this._config) == null ? void 0 : p.title) || ""}"
            placeholder="JetBrains Junie Remote (default)"
            @input="${this._valueChanged}"
          />
          <span class="form-help">
            Custom card header title override.
          </span>
        </div>

        <div class="form-row">
          <label class="form-label" for="max-height">Max Height (optional)</label>
          <input
            id="max-height"
            class="editor-input"
            type="text"
            data-field="max_height"
            .value="${((n = this._config) == null ? void 0 : n.max_height) || "520px"}"
            placeholder="520px"
            @input="${this._valueChanged}"
          />
          <span class="form-help">
            Maximum CSS height for the scrollable transcript container (e.g., 520px or 60vh).
          </span>
        </div>
      </div>
    `;
  }
}
Vt([
  pt({ attribute: !1 })
], ht.prototype, "hass");
Vt([
  v()
], ht.prototype, "_config");
customElements.get("junie-remote-card-editor") || customElements.define("junie-remote-card-editor", ht);
/**
 * @license
 * Copyright 2017 Google LLC
 * SPDX-License-Identifier: BSD-3-Clause
 */
const ye = { CHILD: 2 }, me = (c) => (...t) => ({ _$litDirective$: c, values: t });
class ve {
  constructor(t) {
  }
  get _$AU() {
    return this._$AM._$AU;
  }
  _$AT(t, e, s) {
    this._$Ct = t, this._$AM = e, this._$Ci = s;
  }
  _$AS(t, e) {
    return this.update(t, e);
  }
  update(t, e) {
    return this.render(...e);
  }
}
/**
 * @license
 * Copyright 2017 Google LLC
 * SPDX-License-Identifier: BSD-3-Clause
 */
class nt extends ve {
  constructor(t) {
    if (super(t), this.it = _, t.type !== ye.CHILD) throw Error(this.constructor.directiveName + "() can only be used in child bindings");
  }
  render(t) {
    if (t === _ || t == null) return this._t = void 0, this.it = t;
    if (t === R) return t;
    if (typeof t != "string") throw Error(this.constructor.directiveName + "() called with a non-string value");
    if (t === this.it) return this._t;
    this.it = t;
    const e = [t];
    return e.raw = e, this._t = { _$litType$: this.constructor.resultType, strings: e, values: [] };
  }
}
nt.directiveName = "unsafeHTML", nt.resultType = 1;
const xe = me(nt);
function U(c) {
  return c.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}
function $e(c) {
  const t = c.trim();
  if (!t)
    return null;
  const e = t.toLowerCase();
  return e.startsWith("javascript:") || e.startsWith("vbscript:") || e.startsWith("data:") ? null : e.startsWith("http://") || e.startsWith("https://") || e.startsWith("mailto:") || e.startsWith("/") || e.startsWith("#") || e.startsWith("./") ? U(t) : null;
}
function A(c) {
  const t = [];
  let e = c.replace(/`([^`]+)`/g, (s, i) => {
    const r = t.length;
    return t.push(`<code>${U(i)}</code>`), `INLINECODE${r}`;
  });
  return e = U(e), e = e.replace(
    /\[([^\]]+)\]\(([^)]+)\)/g,
    (s, i, r) => {
      const o = $e(r);
      return o ? `<a href="${o}" target="_blank" rel="noopener noreferrer">${i}</a>` : i;
    }
  ), e = e.replace(
    /\*\*\*([^*]+)\*\*\*/g,
    "<strong><em>$1</em></strong>"
  ), e = e.replace(/___([^_]+)___/g, "<strong><em>$1</em></strong>"), e = e.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>"), e = e.replace(/__([^_]+)__/g, "<strong>$1</strong>"), e = e.replace(/\*([^*]+)\*/g, "<em>$1</em>"), e = e.replace(/_([^_]+)_/g, "<em>$1</em>"), e = e.replace(/~~([^~]+)~~/g, "<del>$1</del>"), t.forEach((s, i) => {
    e = e.replace(`INLINECODE${i}`, s);
  }), e;
}
function we(c) {
  if (!c)
    return "";
  const e = c.replace(/\r\n/g, `
`).replace(/\r/g, `
`).split(`
`), s = [];
  let i = !1, r = "", o = [], a = null, l = !1, p = [];
  const n = () => {
    a && (s.push(`</${a}>`), a = null);
  }, d = () => {
    if (l) {
      const u = p.map(A).join("<br/>");
      s.push(`<blockquote>${u}</blockquote>`), l = !1, p = [];
    }
  };
  for (let u = 0; u < e.length; u++) {
    const f = e[u], g = f.trim(), b = f.match(/^```(\w+)?/);
    if (b)
      if (i) {
        i = !1;
        const V = o.join(`
`), J = U(V), K = U(r);
        s.push(
          `<div class="code-block-wrapper"><div class="code-header"><span class="code-lang">${K}</span><button class="copy-btn" type="button" aria-label="Copy code">Copy</button></div><pre><code class="language-${K}">${J}</code></pre></div>`
        ), r = "", o = [];
        continue;
      } else {
        n(), d(), i = !0, r = b[1] || "code", o = [];
        continue;
      }
    if (i) {
      o.push(f);
      continue;
    }
    if (/^(---|___|\*\*\*)$/.test(g)) {
      n(), d(), s.push('<hr class="markdown-hr" />');
      continue;
    }
    if (f.startsWith(">")) {
      n(), l = !0, p.push(f.replace(/^>\s?/, ""));
      continue;
    } else
      d();
    const y = f.match(/^(\s*)[-*+]\s+(.*)$/);
    if (y) {
      a !== "ul" && (n(), s.push("<ul>"), a = "ul"), s.push(`<li>${A(y[2])}</li>`);
      continue;
    }
    const $ = f.match(/^(\s*)\d+\.\s+(.*)$/);
    if ($) {
      a !== "ol" && (n(), s.push("<ol>"), a = "ol"), s.push(`<li>${A($[2])}</li>`);
      continue;
    }
    n();
    const w = f.match(/^#\s+(.*)$/);
    if (w) {
      s.push(`<h3>${A(w[1])}</h3>`);
      continue;
    }
    const k = f.match(/^##\s+(.*)$/);
    if (k) {
      s.push(`<h4>${A(k[1])}</h4>`);
      continue;
    }
    const C = f.match(/^###\s+(.*)$/);
    if (C) {
      s.push(`<h5>${A(C[1])}</h5>`);
      continue;
    }
    const F = f.match(/^####+\s+(.*)$/);
    if (F) {
      s.push(`<h6>${A(F[1])}</h6>`);
      continue;
    }
    g && s.push(`<p>${A(f)}</p>`);
  }
  if (i) {
    const u = o.join(`
`), f = U(u), g = U(r || "code");
    s.push(
      `<div class="code-block-wrapper"><div class="code-header"><span class="code-lang">${g}</span><button class="copy-btn" type="button" aria-label="Copy code">Copy</button></div><pre><code class="language-${g}">${f}</code></pre></div>`
    );
  }
  return n(), d(), s.join(`
`);
}
function Z(c) {
  const t = we(c);
  return h`<div class="markdown-body">${xe(t)}</div>`;
}
function ke(c) {
  return !c || !Array.isArray(c) || c.length === 0 ? h`` : h`
    <div class="changes-summary-container">
      <div class="changes-summary-title">📁 Changed Files:</div>
      <div class="changes-summary-badges">
        ${c.map((t) => {
    let e = "", s = "modified", i, r;
    return typeof t == "string" ? e = t : t && typeof t == "object" && (e = t.path || t.file || "", s = t.action || "modified", i = t.added, r = t.deleted), h`
            <span class="change-badge ${s === "created" || s === "added" ? "action-created" : s === "deleted" || s === "removed" ? "action-deleted" : s === "renamed" ? "action-renamed" : "action-modified"}">
              <span class="change-action">${s}</span>
              <span class="change-path">${e}</span>
              ${i !== void 0 ? h`<span class="change-diff added">+${i}</span>` : ""}
              ${r !== void 0 ? h`<span class="change-diff deleted">-${r}</span>` : ""}
            </span>
          `;
  })}
      </div>
    </div>
  `;
}
var Ae = Object.defineProperty, Se = Object.getOwnPropertyDescriptor, x = (c, t, e, s) => {
  for (var i = s > 1 ? void 0 : s ? Se(t, e) : t, r = c.length - 1, o; r >= 0; r--)
    (o = c[r]) && (i = (s ? o(t, e, i) : o(i)) || i);
  return s && i && Ae(t, e, i), i;
};
window.customCards = window.customCards || [];
window.customCards.some((c) => c.type === "junie-remote-card") || window.customCards.push({
  type: "junie-remote-card",
  name: "Junie Remote Card",
  description: "Control JetBrains Junie CLI sessions from Home Assistant Lovelace. Reload the page after updating the card.",
  preview: !0,
  documentationURL: "https://gitlab.com/opentasmania/junie-remote-lovelace-card"
});
const Ee = "/api/junie_remote/transcripts/";
function Ot(c) {
  return c.startsWith(Ee);
}
class m extends I {
  constructor() {
    super(...arguments), this._transcript = null, this._transcriptLoading = !1, this._transcriptError = null, this._actionError = null, this._showScrollBottom = !1, this._isKicking = !1, this._promptText = "", this._inputMode = "normal", this._isSending = !1, this._bravePending = !1, this._planViewMode = "summary", this._selectedPlanSection = 0, this._askInputs = {}, this._askAsyncSelections = {}, this._askAsyncInputs = {}, this._lastFetchedUrl = null, this._lastFetchedUpdatedAt = null, this._transcriptRequestId = 0, this._entityGeneration = 0, this._renderedGeneration = -1, this._entityPresent = !1, this._entityHasUrl = !1, this._observedUrl = null, this._observedVersion = null, this._userScrolledUp = !1;
  }
  get hass() {
    return this._hass;
  }
  set hass(t) {
    const e = this._hass;
    this._hass = t, this._syncEntityAvailability(), this.requestUpdate("hass", e);
  }
  static getConfigElement() {
    return document.createElement("junie-remote-card-editor");
  }
  static getStubConfig(t) {
    var s, i;
    let e = "sensor.junie_remote_status";
    if (t != null && t.states) {
      for (const [r, o] of Object.entries(t.states))
        if (r.startsWith("sensor.") && (((s = o.attributes) == null ? void 0 : s.host_key) !== void 0 || ((i = o.attributes) == null ? void 0 : i.tunnel_id) !== void 0 || r.includes("junie"))) {
          e = r;
          break;
        }
    }
    return {
      type: "custom:junie-remote-card",
      entity: e
    };
  }
  setConfig(t) {
    var e;
    if (!t)
      throw new Error(
        "Invalid configuration: configuration object is required"
      );
    if (!t.entity)
      throw new Error("Invalid configuration: 'entity' is required");
    ((e = this._config) == null ? void 0 : e.entity) !== t.entity && (this._resetEntityState(), this._entityPresent = !1, this._entityHasUrl = !1, this._observedUrl = null, this._observedVersion = null), this._config = { ...t }, this._syncEntityAvailability();
  }
  _resetEntityState() {
    var t;
    this._entityGeneration++, this._transcriptRequestId++, this._lastFetchedUrl = null, this._lastFetchedUpdatedAt = null, this._transcript = null, this._transcriptLoading = !1, this._transcriptError = null, this._actionError = null, this._showScrollBottom = !1, this._userScrolledUp = !1, this._isKicking = !1, this._promptText = "", this._inputMode = "normal", this._isSending = !1, this._bravePending = !1, this._planViewMode = "summary", this._selectedPlanSection = 0, this._askInputs = {}, this._askAsyncSelections = {}, this._askAsyncInputs = {}, (t = this.shadowRoot) == null || t.querySelectorAll(
      ".prompt-textarea, .ask-input, .ask-async-input"
    ).forEach((e) => {
      e.value = "";
    });
  }
  _syncEntityAvailability() {
    var a, l, p, n, d;
    const t = (a = this._config) == null ? void 0 : a.entity, e = t ? (p = (l = this._hass) == null ? void 0 : l.states) == null ? void 0 : p[t] : void 0, s = !!e, i = ((n = e == null ? void 0 : e.attributes) == null ? void 0 : n.transcript_json_url) || null, r = ((d = e == null ? void 0 : e.attributes) == null ? void 0 : d.transcript_updated_at) || null, o = !!i;
    this._entityPresent && !s || this._entityHasUrl && !o ? this._resetEntityState() : this._entityHasUrl && o && (i !== this._observedUrl || r !== this._observedVersion) && (this._transcriptRequestId++, this._lastFetchedUrl = null, this._lastFetchedUpdatedAt = null, this._transcriptLoading = !1), this._entityPresent = s, this._entityHasUrl = o, this._observedUrl = i, this._observedVersion = r;
  }
  getCardSize() {
    return 6;
  }
  willUpdate(t) {
    super.willUpdate(t), (t.has("hass") || t.has("_config")) && this._checkTranscriptUpdate();
  }
  firstUpdated(t) {
    super.firstUpdated(t);
    for (const e of ["click", "input", "change", "keydown"])
      this.renderRoot.addEventListener(e, (s) => {
        if (this._renderedGeneration === this._entityGeneration) return;
        const i = s.target;
        (i instanceof HTMLInputElement || i instanceof HTMLTextAreaElement) && (i.value = ""), s.preventDefault(), s.stopImmediatePropagation();
      }, !0);
  }
  updated(t) {
    super.updated(t), this._renderedGeneration = this._entityGeneration, this._userScrolledUp || this._scrollToBottom(!1);
  }
  _checkTranscriptUpdate() {
    var r;
    if (!this.hass || !((r = this._config) != null && r.entity))
      return;
    const t = this.hass.states[this._config.entity];
    if (!t)
      return;
    const e = t.attributes || {}, s = e.transcript_json_url, i = e.transcript_updated_at || null;
    s && (s !== this._lastFetchedUrl || i !== this._lastFetchedUpdatedAt) && (this._lastFetchedUrl = s, this._lastFetchedUpdatedAt = i, this._fetchTranscript(s, ++this._transcriptRequestId));
  }
  _fetchLocalTranscript(t) {
    var s;
    const e = (s = this.hass) == null ? void 0 : s.fetchWithAuth;
    return typeof e != "function" ? Promise.reject(
      new Error("Home Assistant authenticated fetch is unavailable")
    ) : e.call(this.hass, t, { cache: "no-store" });
  }
  async _downloadTranscript(t) {
    var o, a, l, p;
    const e = (o = this._config) == null ? void 0 : o.entity, s = e ? (p = (l = (a = this.hass) == null ? void 0 : a.states) == null ? void 0 : l[e]) == null ? void 0 : p.attributes : void 0, i = t === "json" ? s == null ? void 0 : s.transcript_json_url : s == null ? void 0 : s.transcript_md_url;
    if (!this.hass || !i)
      return;
    const r = this._entityGeneration;
    this._actionError = null;
    try {
      let n = i;
      if (Ot(i)) {
        const u = `${i}${i.includes("?") ? "&" : "?"}download=1`;
        if (typeof this.hass.callWS != "function")
          throw new Error("Home Assistant WebSocket signing is unavailable");
        const f = await this.hass.callWS({
          type: "auth/sign_path",
          path: u,
          expires: 30
        });
        if (r !== this._entityGeneration)
          return;
        n = f.path;
      }
      const d = document.createElement("a");
      d.href = n, d.rel = "noopener noreferrer", d.target = "_blank", d.download = "", d.click();
    } catch (n) {
      r === this._entityGeneration && (this._actionError = n instanceof Error ? n.message : String(n));
    }
  }
  async _fetchTranscript(t, e) {
    const s = this._entityGeneration;
    this._transcriptLoading = !0, this._transcriptError = null;
    try {
      const i = Ot(t), r = i ? await this._fetchLocalTranscript(t) : await fetch(t, { cache: "no-store" });
      if (!r.ok)
        throw i && r.status === 403 ? new Error(
          "Administrator access is required to view local transcripts"
        ) : new Error(`HTTP ${r.status} ${r.statusText}`);
      const o = await r.json();
      if (s !== this._entityGeneration || e !== this._transcriptRequestId)
        return;
      this._transcript = o, this._userScrolledUp && (this._showScrollBottom = !0);
    } catch (i) {
      s === this._entityGeneration && e === this._transcriptRequestId && (this._transcriptError = (i == null ? void 0 : i.message) || String(i), this._lastFetchedUrl = null, this._lastFetchedUpdatedAt = null);
    } finally {
      s === this._entityGeneration && e === this._transcriptRequestId && (this._transcriptLoading = !1);
    }
  }
  async _executeService(t, e, s = !1) {
    var o, a, l;
    if (!this.hass || this._renderedGeneration !== this._entityGeneration || e.entity_id !== ((o = this._config) == null ? void 0 : o.entity) || !this.hass.states[e.entity_id])
      return !1;
    const i = this._entityGeneration;
    this._actionError = null;
    const r = (l = (a = this.hass.states[e.entity_id]) == null ? void 0 : a.attributes) == null ? void 0 : l.connection_status;
    if (!s && r !== "connected")
      return this._actionError = "Controls are unavailable while disconnected.", !1;
    try {
      return await this.hass.callService("junie_remote", t, e), i === this._entityGeneration;
    } catch (p) {
      return i === this._entityGeneration && (this._actionError = p instanceof Error ? p.message : String(p)), !1;
    }
  }
  _onTranscriptScroll(t) {
    const e = t.target;
    e.scrollHeight - e.scrollTop - e.clientHeight <= 40 ? (this._userScrolledUp = !1, this._showScrollBottom = !1) : this._userScrolledUp = !0;
  }
  _scrollToBottom(t = !0) {
    var s;
    const e = (s = this.shadowRoot) == null ? void 0 : s.querySelector(
      ".transcript-container"
    );
    e && (t ? e.scrollTo({
      top: e.scrollHeight,
      behavior: "smooth"
    }) : e.scrollTop = e.scrollHeight), this._showScrollBottom && (this._showScrollBottom = !1), this._userScrolledUp = !1;
  }
  async _handleTakeover() {
    var i;
    if (!this.hass || !((i = this._config) != null && i.entity))
      return;
    const t = this.hass.states[this._config.entity], e = (t == null ? void 0 : t.attributes) || {}, s = this._entityGeneration;
    this._isKicking = !0;
    try {
      await this._executeService(
        "kick_client",
        {
          entity_id: this._config.entity,
          host_key: e.host_key
        },
        !0
      );
    } finally {
      s === this._entityGeneration && (this._isKicking = !1);
    }
  }
  async _handleContainerClick(t) {
    const s = t.target.closest(".copy-btn");
    if (s) {
      const i = s.closest(".code-block-wrapper"), r = i == null ? void 0 : i.querySelector("pre code");
      if (r) {
        const o = r.textContent || "";
        try {
          await navigator.clipboard.writeText(o);
          const a = s.textContent;
          s.textContent = "Copied!", s.classList.add("copied"), setTimeout(() => {
            s.textContent = a, s.classList.remove("copied");
          }, 2e3);
        } catch (a) {
          console.error("Failed to copy code to clipboard:", a);
        }
      }
    }
  }
  static get styles() {
    return Bt`
      :host {
        display: block;
      }
      ha-card {
        padding: 0;
        overflow: hidden;
        display: flex;
        flex-direction: column;
        border-radius: var(--ha-card-border-radius, 12px);
        background: var(--ha-card-background, var(--card-background-color, #ffffff));
        box-shadow: var(--ha-card-box-shadow, 0 2px 8px rgba(0, 0, 0, 0.08));
        color: var(--primary-text-color, #212121);
      }

      /* Host Status Header Bar */
      .header-bar {
        padding: 14px 16px;
        background: var(--secondary-background-color, #f7f9fa);
        border-bottom: 1px solid var(--divider-color, #e0e0e0);
        display: flex;
        flex-direction: column;
        gap: 8px;
      }
      .header-main-row {
        display: flex;
        justify-content: space-between;
        align-items: center;
        flex-wrap: wrap;
        gap: 8px;
      }
      .card-title-group {
        display: flex;
        align-items: center;
        gap: 8px;
      }
      .card-icon {
        font-size: 1.3rem;
      }
      .card-title {
        font-size: 1.1rem;
        font-weight: 600;
        color: var(--primary-text-color, #212121);
      }
      .header-sub-row {
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        gap: 10px;
        font-size: 0.85rem;
        color: var(--secondary-text-color, #616161);
      }
      .host-identity {
        display: flex;
        align-items: center;
        gap: 4px;
        font-weight: 500;
      }
      .git-badges {
        display: flex;
        align-items: center;
        gap: 6px;
      }
      .git-repo-badge,
      .git-branch-badge {
        display: inline-flex;
        align-items: center;
        gap: 4px;
        background: rgba(0, 0, 0, 0.06);
        padding: 2px 8px;
        border-radius: 4px;
        font-family: monospace;
        font-size: 0.8rem;
      }
      .transcript-downloads {
        display: inline-flex;
        gap: 4px;
      }
      .transcript-download {
        font-size: 0.75rem;
        cursor: pointer;
        border: 1px solid var(--divider-color, #888);
        border-radius: 4px;
        background: transparent;
        color: var(--primary-text-color);
        padding: 1px 6px;
      }
      .working-dir {
        font-family: monospace;
        font-size: 0.8rem;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
        max-width: 320px;
      }

      /* Status Pill */
      .status-pill-container {
        display: flex;
        align-items: center;
        gap: 8px;
      }
      .status-pill {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        padding: 4px 10px;
        border-radius: 12px;
        font-size: 0.8rem;
        font-weight: 600;
        text-transform: capitalize;
      }
      .status-pill.status-idle {
        background: #e8f5e9;
        color: #2e7d32;
      }
      .status-pill.status-working {
        background: #e1f5fe;
        color: #0277bd;
      }
      .status-pill.status-waiting {
        background: #fff8e1;
        color: #f57f17;
      }
      .status-pill.status-rejected {
        background: #ffebee;
        color: #c62828;
      }
      .status-pill.status-kicked {
        background: #eceff1;
        color: #455a64;
      }
      .status-pill.status-connecting,
      .status-pill.status-reconnecting {
        background: #ede7f6;
        color: #512da8;
      }
      .status-pill.status-disconnected,
      .status-pill.status-tunnel-not-found {
        background: #fafafa;
        border: 1px solid #e0e0e0;
        color: #757575;
      }

      .status-dot {
        width: 8px;
        height: 8px;
        border-radius: 50%;
        background: currentColor;
      }
      .status-working .status-dot {
        animation: pulse 1.5s infinite;
      }
      @keyframes pulse {
        0% { transform: scale(0.9); opacity: 0.6; }
        50% { transform: scale(1.2); opacity: 1; }
        100% { transform: scale(0.9); opacity: 0.6; }
      }

      /* Takeover button */
      .takeover-btn {
        background: var(--warning-color, #f57f17);
        color: #ffffff;
        border: none;
        border-radius: 4px;
        padding: 5px 10px;
        font-size: 0.8rem;
        font-weight: 600;
        cursor: pointer;
        transition: opacity 0.2s, background-color 0.2s;
      }
      .takeover-btn:hover {
        opacity: 0.9;
      }
      .takeover-btn:disabled {
        opacity: 0.5;
        cursor: not-allowed;
      }

      /* Integration quick-link buttons */
      .integration-buttons {
        display: inline-flex;
        gap: 4px;
        margin-left: 8px;
      }
      .integration-btn {
        font-size: 0.75rem;
        color: var(--primary-color, #0288d1);
        text-decoration: none;
        padding: 2px 6px;
        border-radius: 3px;
        transition: background-color 0.2s;
        white-space: nowrap;
      }
      .integration-btn:hover {
        background: var(--primary-color, #0288d1);
        color: #ffffff;
      }

      /* Transcript Container */
      .transcript-container-wrapper {
        position: relative;
        flex: 1;
      }
      .card-action-error,
      .transcript-error {
        margin: 8px 16px;
        padding: 8px 12px;
        border: 1px solid var(--error-color, #db4437);
        border-radius: 6px;
        background: var(--card-background-color, #ffffff);
        color: var(--error-color, #db4437);
        font-size: 0.9rem;
      }
      .connection-warning {
        margin: 8px 16px;
        padding: 8px 12px;
        border: 1px solid var(--warning-color, #ff9800);
        border-radius: 6px;
        color: var(--primary-text-color, #212121);
        font-size: 0.9rem;
      }
      .transcript-container {
        overflow-y: auto;
        padding: 16px;
        display: flex;
        flex-direction: column;
        gap: 14px;
        scroll-behavior: smooth;
      }

      /* Floating Scroll to Bottom button */
      .scroll-bottom-btn {
        position: absolute;
        bottom: 16px;
        right: 16px;
        z-index: 10;
        background: var(--primary-color, #0288d1);
        color: #ffffff;
        border: none;
        border-radius: 20px;
        padding: 8px 14px;
        font-size: 0.85rem;
        font-weight: 600;
        box-shadow: 0 3px 8px rgba(0, 0, 0, 0.25);
        cursor: pointer;
        display: flex;
        align-items: center;
        gap: 6px;
        transition: transform 0.2s, background-color 0.2s;
      }
      .scroll-bottom-btn:hover {
        transform: translateY(-2px);
      }

      /* Transcript Items */
      .transcript-item {
        display: flex;
        flex-direction: column;
        max-width: 90%;
      }
      .item-user-prompt,
      .item-user-response {
        align-self: flex-end;
        background: var(--primary-color, #0288d1);
        color: #ffffff;
        border-radius: 14px 14px 2px 14px;
        padding: 10px 14px;
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
      }
      .item-user-response {
        background: #455a64;
      }
      .bubble-header {
        font-size: 0.75rem;
        opacity: 0.85;
        margin-bottom: 4px;
        display: flex;
        justify-content: space-between;
        gap: 8px;
      }
      .bubble-role {
        font-weight: 600;
        text-transform: uppercase;
      }
      .bubble-content {
        font-size: 0.95rem;
        line-height: 1.45;
        word-break: break-word;
        white-space: pre-wrap;
      }
      .response-prompt,
      .item-system-message-details,
      .skills-detail,
      .step-description,
      .step-error-code,
      .progressing-step-description {
        font-size: 0.88rem;
        line-height: 1.4;
      }
      .response-prompt {
        margin-bottom: 6px;
        opacity: 0.9;
      }
      .step-description,
      .step-error-code {
        margin: 4px 0 8px;
      }
      .step-error-code {
        color: var(--error-color, #db4437);
        font-weight: 600;
      }
      .progressing-step-content {
        display: flex;
        flex-direction: column;
        gap: 2px;
      }
      .progressing-step-description {
        color: var(--secondary-text-color, #757575);
        font-weight: 400;
      }

      /* Step / Result Items */
      .item-step {
        align-self: flex-start;
        width: 100%;
        max-width: 100%;
        background: var(--card-background-color, #ffffff);
        border: 1px solid var(--divider-color, #e0e0e0);
        border-radius: 8px;
        padding: 12px 14px;
        box-sizing: border-box;
      }
      .step-header {
        display: flex;
        align-items: center;
        gap: 8px;
        margin-bottom: 8px;
      }
      .step-title {
        font-weight: 600;
        font-size: 0.95rem;
        color: var(--primary-text-color, #212121);
      }
      .step-badge {
        font-size: 0.75rem;
        font-weight: 700;
        padding: 2px 6px;
        border-radius: 4px;
        text-transform: uppercase;
      }
      .badge-result {
        background: #e8f5e9;
        color: #2e7d32;
      }
      .badge-error {
        background: #ffebee;
        color: #c62828;
      }
      .badge-cancelled {
        background: #fff3e0;
        color: #e65100;
      }
      .badge-step {
        background: #e0f2f1;
        color: #00695c;
      }

      /* System Message */
      .item-system-message {
        align-self: center;
        width: 100%;
        box-sizing: border-box;
        padding: 8px 12px;
        border-radius: 6px;
        font-size: 0.85rem;
        display: flex;
        align-items: center;
        gap: 8px;
        background: var(--secondary-background-color, #f5f5f5);
        color: var(--secondary-text-color, #616161);
        border-left: 3px solid #9e9e9e;
      }
      .item-system-message.level-error {
        background: #ffebee;
        color: #c62828;
        border-left-color: #c62828;
      }
      .item-system-message.level-warning {
        background: #fffde7;
        color: #f57f17;
        border-left-color: #f57f17;
      }

      /* Skills Status */
      .item-skills-status {
        align-self: center;
        padding: 4px 10px;
        border-radius: 12px;
        font-size: 0.8rem;
        background: rgba(0, 0, 0, 0.04);
        color: var(--secondary-text-color, #757575);
        display: inline-flex;
        align-items: center;
        gap: 6px;
      }
      .skills-label {
        font-weight: 600;
      }
      .skills-detail {
        display: block;
      }

      /* Progressing Steps */
      .progressing-steps-wrapper {
        border-top: 1px dashed var(--divider-color, #e0e0e0);
        padding-top: 10px;
        display: flex;
        flex-direction: column;
        gap: 6px;
      }
      .progressing-step-item {
        display: flex;
        align-items: center;
        gap: 8px;
        font-size: 0.88rem;
        color: var(--primary-color, #0288d1);
        font-weight: 500;
      }
      .spinner {
        width: 14px;
        height: 14px;
        border: 2px solid rgba(2, 136, 209, 0.2);
        border-top-color: var(--primary-color, #0288d1);
        border-radius: 50%;
        animation: spin 0.8s linear infinite;
      }
      @keyframes spin {
        to { transform: rotate(360deg); }
      }

      /* Welcome Empty State */
      .welcome-empty-state {
        text-align: center;
        padding: 36px 16px;
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 8px;
      }
      .welcome-icon {
        font-size: 2.2rem;
      }
      .welcome-title {
        font-size: 1.15rem;
        font-weight: 600;
        color: var(--primary-text-color, #212121);
      }
      .welcome-subtitle {
        font-size: 0.9rem;
        color: var(--secondary-text-color, #757575);
        max-width: 380px;
      }

      /* Last Step Preview */
      .last-step-preview-box {
        padding: 12px;
        background: var(--secondary-background-color, #f9f9f9);
        border-radius: 6px;
        border: 1px solid var(--divider-color, #e0e0e0);
        font-size: 0.9rem;
        color: var(--secondary-text-color, #424242);
      }
      .preview-label {
        font-weight: 600;
        font-size: 0.75rem;
        text-transform: uppercase;
        color: var(--secondary-text-color, #757575);
        margin-bottom: 4px;
      }

      /* Markdown & Code Block Styles */
      .markdown-body {
        font-size: 0.95rem;
        line-height: 1.5;
        color: var(--primary-text-color, #212121);
        word-break: break-word;
      }
      .markdown-body p {
        margin: 0 0 8px 0;
      }
      .markdown-body p:last-child {
        margin-bottom: 0;
      }
      .markdown-body h3,
      .markdown-body h4,
      .markdown-body h5,
      .markdown-body h6 {
        margin: 12px 0 6px 0;
        font-weight: 600;
      }
      .markdown-body code {
        font-family: monospace;
        font-size: 0.88rem;
        background: rgba(0, 0, 0, 0.06);
        padding: 2px 5px;
        border-radius: 3px;
      }
      .markdown-body pre {
        margin: 0;
        padding: 10px 12px;
        background: #1e1e1e;
        color: #d4d4d4;
        overflow-x: auto;
        font-family: monospace;
        font-size: 0.85rem;
        border-radius: 0 0 6px 6px;
      }
      .markdown-body pre code {
        background: none;
        padding: 0;
        color: inherit;
      }
      .code-block-wrapper {
        margin: 10px 0;
        border-radius: 6px;
        overflow: hidden;
        border: 1px solid #333333;
      }
      .code-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        background: #2d2d2d;
        color: #cccccc;
        padding: 4px 10px;
        font-size: 0.75rem;
        font-family: monospace;
      }
      .code-lang {
        text-transform: lowercase;
      }
      .copy-btn {
        background: rgba(255, 255, 255, 0.12);
        color: #ffffff;
        border: none;
        border-radius: 3px;
        padding: 2px 8px;
        font-size: 0.75rem;
        cursor: pointer;
        transition: background 0.2s;
      }
      .copy-btn:hover {
        background: rgba(255, 255, 255, 0.25);
      }
      .copy-btn.copied {
        background: #2e7d32;
      }

      /* Changes Summary Badges */
      .changes-summary-container {
        margin-top: 10px;
        padding-top: 8px;
        border-top: 1px dashed var(--divider-color, #e0e0e0);
      }
      .changes-summary-title {
        font-size: 0.8rem;
        font-weight: 600;
        color: var(--secondary-text-color, #757575);
        margin-bottom: 6px;
      }
      .changes-summary-badges {
        display: flex;
        flex-wrap: wrap;
        gap: 6px;
      }
      .change-badge {
        display: inline-flex;
        align-items: center;
        gap: 4px;
        padding: 2px 8px;
        border-radius: 4px;
        font-size: 0.8rem;
        font-family: monospace;
      }
      .change-action {
        font-weight: 600;
        text-transform: uppercase;
        font-size: 0.7rem;
      }
      .change-badge.action-created {
        background: #e8f5e9;
        color: #2e7d32;
      }
      .change-badge.action-deleted {
        background: #ffebee;
        color: #c62828;
      }
      .change-badge.action-modified {
        background: #e3f2fd;
        color: #1565c0;
      }
      .change-badge.action-renamed {
        background: #fff8e1;
        color: #f57f17;
      }
      .change-diff.added {
        color: #2e7d32;
        font-weight: 600;
      }
      .change-diff.deleted {
        color: #c62828;
        font-weight: 600;
      }

      /* Plan Proposal Drawer */
      .plan-proposal-drawer {
        border-top: 1px solid var(--divider-color, #e0e0e0);
        background: var(--secondary-background-color, #f8fafc);
        display: flex;
        flex-direction: column;
      }
      .plan-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 10px 16px;
        background: var(--secondary-background-color, #f1f5f9);
        border-bottom: 1px solid var(--divider-color, #e2e8f0);
        flex-wrap: wrap;
        gap: 8px;
      }
      .plan-title-group {
        display: flex;
        align-items: center;
        gap: 8px;
      }
      .plan-title {
        font-weight: 600;
        font-size: 0.95rem;
        color: var(--primary-text-color, #1e293b);
      }
      .plan-badge {
        font-size: 0.72rem;
        font-weight: 700;
        padding: 2px 7px;
        border-radius: 4px;
        text-transform: uppercase;
      }
      .plan-badge.ready-badge {
        background: #e8f5e9;
        color: #2e7d32;
        border: 1px solid #c8e6c9;
      }
      .plan-view-toggles {
        display: flex;
        align-items: center;
        gap: 4px;
      }
      .plan-tab-btn,
      .plan-collapse-btn {
        background: transparent;
        border: 1px solid var(--divider-color, #cbd5e1);
        border-radius: 4px;
        padding: 4px 10px;
        font-size: 0.8rem;
        font-weight: 500;
        color: var(--secondary-text-color, #475569);
        cursor: pointer;
        transition: background 0.15s, color 0.15s, border-color 0.15s;
      }
      .plan-tab-btn:hover,
      .plan-collapse-btn:hover {
        background: rgba(0, 0, 0, 0.05);
      }
      .plan-tab-btn.active {
        background: var(--primary-color, #0288d1);
        color: #ffffff;
        border-color: var(--primary-color, #0288d1);
      }
      .plan-body {
        padding: 14px 16px;
        display: flex;
        flex-direction: column;
        gap: 12px;
      }
      .plan-file-path {
        font-family: monospace;
        font-size: 0.8rem;
        color: var(--secondary-text-color, #64748b);
        background: rgba(0, 0, 0, 0.04);
        padding: 4px 8px;
        border-radius: 4px;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }
      .plan-delivery-steps {
        display: flex;
        flex-direction: column;
        gap: 8px;
      }
      .delivery-steps-title {
        font-size: 0.85rem;
        font-weight: 600;
        color: var(--secondary-text-color, #475569);
        text-transform: uppercase;
      }
      .delivery-steps-list {
        margin: 0;
        padding-left: 20px;
        display: flex;
        flex-direction: column;
        gap: 6px;
      }
      .delivery-step-item {
        font-size: 0.88rem;
        line-height: 1.4;
      }
      .delivery-step-name {
        font-weight: 600;
        color: var(--primary-text-color, #1e293b);
      }
      .delivery-step-desc {
        color: var(--secondary-text-color, #475569);
        margin-top: 2px;
      }
      .plan-section-previews {
        display: flex;
        flex-direction: column;
        gap: 10px;
      }
      .section-preview-item {
        background: var(--card-background-color, #ffffff);
        border: 1px solid var(--divider-color, #e2e8f0);
        border-radius: 6px;
        padding: 10px 12px;
      }
      .section-preview-title {
        margin: 0 0 6px 0;
        font-size: 0.9rem;
        font-weight: 600;
        color: var(--primary-text-color, #1e293b);
      }
      .plan-section-tabs {
        display: flex;
        gap: 6px;
        overflow-x: auto;
        padding-bottom: 4px;
        border-bottom: 1px solid var(--divider-color, #e2e8f0);
      }
      .plan-section-tab-btn {
        background: transparent;
        border: none;
        border-bottom: 2px solid transparent;
        padding: 6px 12px;
        font-size: 0.85rem;
        font-weight: 500;
        color: var(--secondary-text-color, #64748b);
        cursor: pointer;
        white-space: nowrap;
      }
      .plan-section-tab-btn:hover {
        color: var(--primary-text-color, #1e293b);
      }
      .plan-section-tab-btn.active {
        color: var(--primary-color, #0288d1);
        border-bottom-color: var(--primary-color, #0288d1);
        font-weight: 600;
      }
      .plan-section-content {
        background: var(--card-background-color, #ffffff);
        border: 1px solid var(--divider-color, #e2e8f0);
        border-radius: 6px;
        padding: 12px;
        min-height: 60px;
        max-height: 240px;
        overflow-y: auto;
      }
      .plan-actions {
        display: flex;
        gap: 8px;
        padding-top: 6px;
      }
      .confirm-plan-btn {
        background: var(--primary-color, #0288d1);
        color: #ffffff;
        border: none;
        border-radius: 4px;
        padding: 8px 14px;
        font-size: 0.85rem;
        font-weight: 600;
        cursor: pointer;
        transition: opacity 0.2s;
      }
      .confirm-plan-btn:hover {
        opacity: 0.9;
      }
      .refine-plan-btn {
        background: transparent;
        color: var(--primary-color, #0288d1);
        border: 1px solid var(--primary-color, #0288d1);
        border-radius: 4px;
        padding: 8px 14px;
        font-size: 0.85rem;
        font-weight: 600;
        cursor: pointer;
        transition: background 0.2s;
      }
      .refine-plan-btn:hover {
        background: rgba(2, 136, 209, 0.08);
      }

      /* Active Requests Widgets */
      .active-requests-container {
        padding: 12px 16px;
        display: flex;
        flex-direction: column;
        gap: 10px;
        border-top: 1px solid var(--divider-color, #e0e0e0);
        background: var(--secondary-background-color, #fdf8f4);
      }
      .active-request-card {
        background: var(--card-background-color, #ffffff);
        border: 1px solid var(--divider-color, #e0e0e0);
        border-left: 4px solid var(--accent-color, #ff9800);
        border-radius: 6px;
        padding: 12px 14px;
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
        display: flex;
        flex-direction: column;
        gap: 8px;
      }
      .active-request-title {
        font-weight: 600;
        font-size: 0.92rem;
        color: var(--primary-text-color, #212121);
      }
      .active-request-subtitle {
        font-size: 0.85rem;
        color: var(--secondary-text-color, #616161);
      }
      .active-request-input-row,
      .ask-async-input-row {
        display: flex;
        gap: 8px;
        align-items: center;
      }
      .ask-input,
      .ask-async-input {
        flex: 1;
        padding: 8px 10px;
        border: 1px solid var(--divider-color, #cccccc);
        border-radius: 4px;
        font-size: 0.9rem;
        font-family: inherit;
        outline: none;
      }
      .ask-input:focus,
      .ask-async-input:focus {
        border-color: var(--primary-color, #0288d1);
      }
      .ask-send-btn,
      .ask-async-submit-btn,
      .action-ok-btn {
        background: var(--primary-color, #0288d1);
        color: #ffffff;
        border: none;
        border-radius: 4px;
        padding: 8px 14px;
        font-size: 0.85rem;
        font-weight: 600;
        cursor: pointer;
        transition: opacity 0.2s;
        white-space: nowrap;
      }
      .ask-send-btn:hover,
      .ask-async-submit-btn:hover,
      .action-ok-btn:hover {
        opacity: 0.9;
      }
      .choice-options,
      .approve-options,
      .ask-async-options {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
      }
      .choice-opt-btn {
        background: var(--secondary-background-color, #f5f5f5);
        border: 1px solid var(--divider-color, #e0e0e0);
        border-radius: 4px;
        padding: 8px 12px;
        text-align: left;
        cursor: pointer;
        display: flex;
        flex-direction: column;
        gap: 2px;
        transition: background 0.15s, border-color 0.15s;
      }
      .choice-opt-btn:hover {
        background: #e3f2fd;
        border-color: #90caf9;
      }
      .choice-opt-btn .opt-title {
        font-weight: 600;
        font-size: 0.85rem;
        color: var(--primary-text-color, #212121);
      }
      .choice-opt-btn .opt-desc {
        font-size: 0.78rem;
        color: var(--secondary-text-color, #616161);
      }
      .approve-opt-btn {
        border: 1px solid transparent;
        border-radius: 4px;
        padding: 7px 12px;
        font-size: 0.85rem;
        font-weight: 600;
        cursor: pointer;
        transition: opacity 0.2s;
      }
      .approve-opt-btn.opt-allow-once {
        background: #e3f2fd;
        color: #1565c0;
        border-color: #bbdefb;
      }
      .approve-opt-btn.opt-always-allow {
        background: #e8f5e9;
        color: #2e7d32;
        border-color: #c8e6c9;
      }
      .approve-opt-btn.opt-deny {
        background: #ffebee;
        color: #c62828;
        border-color: #ffcdd2;
      }
      .approve-opt-btn:hover {
        opacity: 0.85;
      }
      .ask-async-opt-btn {
        background: var(--secondary-background-color, #f5f5f5);
        border: 1px solid var(--divider-color, #e0e0e0);
        border-radius: 4px;
        padding: 6px 12px;
        font-size: 0.85rem;
        cursor: pointer;
        transition: background 0.15s, border-color 0.15s;
      }
      .ask-async-opt-btn:hover {
        background: #e0e0e0;
      }
      .ask-async-opt-btn.selected {
        background: #e3f2fd;
        color: #0d47a1;
        border-color: #2196f3;
        font-weight: 600;
      }

      /* Card Footer & Controls */
      .card-footer {
        padding: 12px 16px;
        border-top: 1px solid var(--divider-color, #e0e0e0);
        background: var(--card-background-color, #ffffff);
        display: flex;
        flex-direction: column;
        gap: 10px;
      }
      .plan-mode-banner {
        display: flex;
        justify-content: space-between;
        align-items: center;
        background: #fff8e1;
        border: 1px solid #ffe082;
        border-radius: 4px;
        padding: 6px 10px;
        font-size: 0.85rem;
        color: #b78103;
      }
      .plan-mode-label {
        font-weight: 600;
      }
      .cancel-plan-mode-btn {
        background: transparent;
        border: 1px solid #fbc02d;
        border-radius: 3px;
        padding: 2px 8px;
        font-size: 0.75rem;
        font-weight: 600;
        color: #b78103;
        cursor: pointer;
      }
      .cancel-plan-mode-btn:hover {
        background: rgba(0, 0, 0, 0.05);
      }
      .footer-control-row {
        display: flex;
        align-items: center;
        gap: 8px;
      }
      .brave-toggle-btn {
        background: var(--secondary-background-color, #f5f5f5);
        color: var(--secondary-text-color, #616161);
        border: 1px solid var(--divider-color, #e0e0e0);
        border-radius: 4px;
        padding: 6px 10px;
        font-size: 0.85rem;
        font-weight: 600;
        cursor: pointer;
        display: inline-flex;
        align-items: center;
        gap: 4px;
        white-space: nowrap;
        transition: background 0.2s, color 0.2s, border-color 0.2s;
      }
      .brave-toggle-btn:hover {
        background: #e0e0e0;
      }
      .brave-toggle-btn.brave-active {
        background: #ffebee;
        color: #d32f2f;
        border-color: #ef9a9a;
      }
      .brave-toggle-btn:disabled {
        opacity: 0.6;
        cursor: not-allowed;
      }
      .model-select {
        flex: 1;
        padding: 6px 10px;
        border: 1px solid var(--divider-color, #cccccc);
        border-radius: 4px;
        background: var(--card-background-color, #ffffff);
        color: var(--primary-text-color, #212121);
        font-size: 0.85rem;
        outline: none;
      }
      .model-select:focus {
        border-color: var(--primary-color, #0288d1);
      }
      .prompt-input-row {
        display: flex;
        gap: 8px;
        align-items: flex-end;
      }
      .prompt-textarea {
        flex: 1;
        border: 1px solid var(--divider-color, #cccccc);
        border-radius: 6px;
        padding: 8px 10px;
        font-size: 0.9rem;
        font-family: inherit;
        resize: vertical;
        min-height: 40px;
        outline: none;
        background: var(--card-background-color, #ffffff);
        color: var(--primary-text-color, #212121);
      }
      .prompt-textarea:focus {
        border-color: var(--primary-color, #0288d1);
      }
      .prompt-actions {
        display: flex;
        gap: 6px;
        align-items: center;
      }
      .send-btn,
      .steer-btn {
        background: var(--primary-color, #0288d1);
        color: #ffffff;
        border: none;
        border-radius: 4px;
        padding: 8px 14px;
        font-size: 0.85rem;
        font-weight: 600;
        cursor: pointer;
        transition: opacity 0.2s;
      }
      .steer-btn {
        background: #2e7d32;
      }
      .stop-btn {
        background: var(--error-color, #d32f2f);
        color: #ffffff;
        border: none;
        border-radius: 4px;
        padding: 8px 14px;
        font-size: 0.85rem;
        font-weight: 600;
        cursor: pointer;
        transition: opacity 0.2s;
      }
      .send-btn:hover,
      .steer-btn:hover,
      .stop-btn:hover {
        opacity: 0.9;
      }
      .send-btn:disabled,
      .steer-btn:disabled,
      .stop-btn:disabled {
        opacity: 0.5;
        cursor: not-allowed;
      }
    `;
  }
  _resolveStatus(t, e, s) {
    return e === "rejected" || t === "rejected" ? { text: "Rejected (In Use)", cssClass: "status-rejected" } : e === "kicked" || t === "kicked" ? {
      text: "Session Taken Over (Kicked)",
      cssClass: "status-kicked"
    } : e === "tunnel-not-found" || t === "tunnel-not-found" ? {
      text: "Tunnel Not Found",
      cssClass: "status-tunnel-not-found"
    } : e === "connecting" || t === "connecting" ? { text: "Connecting…", cssClass: "status-connecting" } : e === "reconnecting" || t === "reconnecting" ? { text: "Reconnecting…", cssClass: "status-reconnecting" } : e === "disconnected" || e === "offline" || t === "disconnected" || t === "offline" ? { text: "Disconnected", cssClass: "status-disconnected" } : s === "working" || t === "working" ? { text: "Working…", cssClass: "status-working" } : s === "waiting-for-input" || t === "waiting-for-input" ? { text: "Waiting for Input", cssClass: "status-waiting" } : { text: "Connected · Idle", cssClass: "status-idle" };
  }
  _formatRepoDisplay(t) {
    if (!t) return "N/A";
    const s = t.replace(/\.git$/, "").split(/[/:]/);
    return s.length >= 2 ? s.slice(-2).join("/") : t;
  }
  render() {
    var ft, gt, bt, _t, yt, mt, vt, xt, $t, wt, kt, At, St, Et;
    if (!this._config)
      return h`<ha-card><div style="padding: 16px;">Invalid configuration</div></ha-card>`;
    const t = (ft = this.hass) == null ? void 0 : ft.states[this._config.entity];
    if (!t)
      return h`
        <ha-card>
          <div style="padding: 16px;">
            Entity not found: <code>${this._config.entity}</code>
          </div>
        </ha-card>
      `;
    const e = t.attributes || {}, s = t.state || "disconnected", i = e.connection_status || s, r = e.session_status || s, o = this._resolveStatus(s, i, r), a = this._config.title || e.title || "JetBrains Junie Remote", l = e.user_name || "N/A", p = e.os_name || "N/A", n = e.git_repo || "", d = e.git_branch || "N/A", u = e.working_dir || "N/A", f = this._config.max_height || "520px", g = ((gt = this._transcript) == null ? void 0 : gt.history) || [], b = ((bt = this._transcript) == null ? void 0 : bt.progressing_steps) || [], y = r === "working" || s === "working", $ = i === "connected", w = this._config.entity, k = e.host_key || ((_t = this._transcript) == null ? void 0 : _t.host_key), C = r === "working" || r === "waiting-for-input" || s === "working" || s === "waiting-for-input", F = !!(e.brave_mode ?? ((yt = this._transcript) == null ? void 0 : yt.brave_mode) ?? !1), V = ((mt = this._transcript) == null ? void 0 : mt.plan_proposal) || e.plan_summary, J = (xt = (vt = this._transcript) == null ? void 0 : vt.active_requests) != null && xt.length ? this._transcript.active_requests : e.active_requests || [], K = e.model_options || ((wt = ($t = this._transcript) == null ? void 0 : $t.model_selection) == null ? void 0 : wt.options) || [], et = e.current_model_id || ((At = (kt = this._transcript) == null ? void 0 : kt.model_selection) == null ? void 0 : At.current_model_id), ut = e.current_effort_id || ((Et = (St = this._transcript) == null ? void 0 : St.model_selection) == null ? void 0 : Et.current_effort_id), Jt = e.selected_model_effort || (et ? ut ? `${et}:${ut}` : et : "");
    return h`
      <ha-card>
        ${$ ? "" : h`<div class="connection-warning" role="status">
              Controls are unavailable while disconnected.
            </div>`}
        ${this._actionError ? h`<div class="card-action-error" role="alert">
              ${this._actionError}
            </div>` : ""}
        <!-- Host Status Header Bar -->
        <div class="header-bar">
          <div class="header-main-row">
            <div class="card-title-group">
              <span class="card-icon">🤖</span>
              <span class="card-title">${a}</span>
            </div>
            <div class="status-pill-container">
              <span class="status-pill ${o.cssClass}">
                <span class="status-dot"></span>
                <span class="status-text">${o.text}</span>
              </span>
              <button
                class="takeover-btn"
                type="button"
                ?disabled="${this._isKicking}"
                @click="${this._handleTakeover}"
                title="Disconnect conflicting clients and take over this session"
              >
                ${this._isKicking ? "Disconnecting…" : "🔑 Take Over"}
              </button>
            </div>
          </div>

          <div class="header-sub-row">
            <span class="host-identity" title="Host User & OS">
              👤 <strong>${l}</strong> · ${p}
            </span>
            ${n ? h`
                  <span class="git-badges">
                    <span class="git-repo-badge" title="${n}">
                      📦 ${this._formatRepoDisplay(n)}
                    </span>
                    <span class="git-branch-badge" title="Git Branch">
                      🌿 ${d}
                    </span>
                  </span>
                ` : ""}
            <span class="working-dir" title="Working Directory: ${u}">
              📂 ${u}
            </span>
            ${e.transcript_json_url || e.transcript_md_url ? h`<span class="transcript-downloads">
                  ${e.transcript_json_url ? h`<button class="transcript-download" type="button"
                        @click=${() => this._downloadTranscript("json")}>⬇ JSON</button>` : ""}
                  ${e.transcript_md_url ? h`<button class="transcript-download" type="button"
                        @click=${() => this._downloadTranscript("md")}>⬇ Markdown</button>` : ""}
                </span>` : ""}
            <span class="integration-buttons">
              <a
                class="integration-btn"
                href="https://my.home-assistant.io/redirect/integration/?domain=junie_remote"
                target="_blank"
                rel="noopener noreferrer"
                title="Open Junie Remote integration settings"
              >
                ⚙️ Integration
              </a>
              <a
                class="integration-btn"
                href="https://my.home-assistant.io/redirect/marketplace_repository/?owner=OpenTasmania&repository=junie-remote-lovelace-card&category=integration"
                target="_blank"
                rel="noopener noreferrer"
                title="Open in HACS / Marketplace"
              >
                📦 HACS
              </a>
              <a
                class="integration-btn"
                href="https://my.home-assistant.io/redirect/integrations/"
                target="_blank"
                rel="noopener noreferrer"
                title="Open Integrations dashboard"
              >
                🔌 Integrations
              </a>
            </span>
          </div>
        </div>

        <!-- Transcript Viewer -->
        <div class="transcript-container-wrapper">
          ${this._transcriptError ? h`<div class="transcript-error" role="alert">
                Transcript could not be loaded: ${this._transcriptError}
              </div>` : ""}
          <div
            class="transcript-container"
            style="max-height: ${f};"
            @scroll="${this._onTranscriptScroll}"
            @click="${this._handleContainerClick}"
          >
            ${g.length > 0 ? h`
                  ${g.map((j) => this._renderTranscriptItem(j))}
                ` : $ && r === "idle" ? h`
                  <div class="welcome-empty-state">
                    <div class="welcome-icon">✨</div>
                    <div class="welcome-title">
                      Welcome to Junie — What shall we build today?
                    </div>
                    <div class="welcome-subtitle">
                      Ask questions, plan features, or request code changes.
                    </div>
                  </div>
                ` : e.last_step_preview ? h`
                  <div class="last-step-preview-box">
                    <div class="preview-label">Last Activity Preview</div>
                    <div>${e.last_step_preview}</div>
                  </div>
                ` : h`
                  <div style="padding: 16px; color: var(--secondary-text-color);">
                    ${this._transcriptLoading ? "Loading transcript…" : "No transcript recorded for this session."}
                  </div>
                `}

            <!-- In-progress steps -->
            ${y || b.length > 0 ? h`
                  <div class="progressing-steps-wrapper">
                    ${b.length > 0 ? b.map(
      (j) => this._renderProgressingStep(j)
    ) : h`
                          <div class="progressing-step-item">
                            <span class="spinner"></span>
                            <span>Working on task…</span>
                          </div>
                        `}
                  </div>
                ` : ""}
          </div>

          ${this._showScrollBottom ? h`
                <button
                  class="scroll-bottom-btn"
                  type="button"
                  @click="${() => this._scrollToBottom(!0)}"
                >
                  ↓ New messages
                </button>
              ` : ""}
        </div>

        <!-- Plan Proposal Drawer -->
        ${V ? this._renderPlanProposal(V, w, k, $) : ""}

        <!-- Active Requests Widgets -->
        ${J.length > 0 ? h`
              <div class="active-requests-container">
                ${J.map(
      (j, Kt) => this._renderActiveRequest(
        j,
        Kt,
        k,
        w,
        $
      )
    )}
              </div>
            ` : ""}

        <!-- Footer Control Bar & Prompt Input -->
        ${this._renderFooter(
      e,
      k,
      w,
      C,
      F,
      Jt,
      K,
      $
    )}
      </ha-card>
    `;
  }
  _renderPlanProposal(t, e, s, i) {
    const r = !!(t.ready_for_review ?? t.readyForReview), o = !!(t.show_actions ?? t.showActions), a = t.plan_file_path || t.planFilePath || null, l = t.delivery_steps || t.deliverySteps || [], p = t.sections && t.sections.length > 0 ? t.sections : (t.section_names || []).map((n) => ({
      name: n,
      content: ""
    }));
    return h`
      <div class="plan-proposal-drawer">
        <div class="plan-header">
          <div class="plan-title-group">
            <span class="plan-title">📋 Plan Proposal</span>
            ${r ? h`<span class="plan-badge ready-badge">Ready for review</span>` : ""}
          </div>
          <div class="plan-view-toggles">
            <button
              class="plan-tab-btn plan-btn-summary ${this._planViewMode === "summary" ? "active" : ""}"
              type="button"
              @click="${() => this._planViewMode = "summary"}"
            >
              Summary
            </button>
            <button
              class="plan-tab-btn plan-btn-full ${this._planViewMode === "full" ? "active" : ""}"
              type="button"
              @click="${() => this._planViewMode = "full"}"
            >
              Full Plan
            </button>
            <button
              class="plan-collapse-btn"
              type="button"
              @click="${this._togglePlanCollapse}"
            >
              ${this._planViewMode === "collapsed" ? "Review Plan" : "Collapse"}
            </button>
          </div>
        </div>

        ${this._planViewMode !== "collapsed" ? h`
              <div class="plan-body">
                ${a ? h`
                      <div class="plan-file-path" title="${a}">
                        📄 ${a}
                      </div>
                    ` : ""}
                ${this._planViewMode === "summary" ? h`
                      <div class="plan-summary-view">
                        ${l.length > 0 ? h`
                              <div class="plan-delivery-steps">
                                <div class="delivery-steps-title">
                                  Delivery Steps
                                </div>
                                <ol class="delivery-steps-list">
                                  ${l.map(
      (n, d) => h`
                                      <li class="delivery-step-item">
                                        <span class="delivery-step-name"
                                          >${n.name || n.title || `Step ${d + 1}`}</span
                                        >
                                        ${n.description || n.text ? h`<div class="delivery-step-desc">
                                              ${n.description || n.text}
                                            </div>` : ""}
                                      </li>
                                    `
    )}
                                </ol>
                              </div>
                            ` : h`
                              <div class="plan-section-previews">
                                ${p.slice(0, 2).map(
      (n) => h`
                                    <div class="section-preview-item">
                                      <h4 class="section-preview-title">
                                        ${n.name || n.title || "Section"}
                                      </h4>
                                      <div class="section-preview-content">
                                        ${n.content ? Z(n.content) : h`<em>No preview available</em>`}
                                      </div>
                                    </div>
                                  `
    )}
                              </div>
                            `}
                      </div>
                    ` : h`
                      <div class="plan-full-view">
                        <div class="plan-section-tabs">
                          ${p.map(
      (n, d) => h`
                              <button
                                class="plan-section-tab-btn ${this._selectedPlanSection === d ? "active" : ""}"
                                type="button"
                                @click="${() => this._selectedPlanSection = d}"
                              >
                                ${n.name || n.title || `Section ${d + 1}`}
                              </button>
                            `
    )}
                          ${l.length > 0 ? h`
                                <button
                                  class="plan-section-tab-btn ${this._selectedPlanSection === "delivery-steps" ? "active" : ""}"
                                  type="button"
                                  @click="${() => this._selectedPlanSection = "delivery-steps"}"
                                >
                                  Delivery Steps
                                </button>
                              ` : ""}
                        </div>

                        <div class="plan-section-content">
                          ${this._selectedPlanSection === "delivery-steps" ? h`
                                <div class="plan-delivery-steps">
                                  <ol class="delivery-steps-list">
                                    ${l.map(
      (n, d) => h`
                                        <li class="delivery-step-item">
                                          <span class="delivery-step-name"
                                            >${n.name || n.title || `Step ${d + 1}`}</span
                                          >
                                          ${n.description || n.text ? h`<div
                                                class="delivery-step-desc"
                                              >
                                                ${n.description || n.text}
                                              </div>` : ""}
                                        </li>
                                      `
    )}
                                  </ol>
                                </div>
                              ` : h`
                                ${(() => {
      const n = typeof this._selectedPlanSection == "number" && p[this._selectedPlanSection] || p[0];
      return n != null && n.content ? Z(n.content) : h`<div>
                                        ${(n == null ? void 0 : n.name) || (n == null ? void 0 : n.title) || "Section content"}
                                      </div>`;
    })()}
                              `}
                        </div>
                      </div>
                    `}
                ${o ? h`
                      <div class="plan-actions">
                        <button
                          class="confirm-plan-btn"
                          type="button"
                          ?disabled="${!i}"
                          @click="${() => this._handleConfirmPlan(e, s)}"
                        >
                          Confirm and Implement
                        </button>
                        <button
                          class="refine-plan-btn"
                          type="button"
                          ?disabled="${!i}"
                          @click="${this._handleRefinePlan}"
                        >
                          Refine Plan
                        </button>
                      </div>
                    ` : ""}
              </div>
            ` : ""}
      </div>
    `;
  }
  _togglePlanCollapse() {
    this._planViewMode === "collapsed" ? this._planViewMode = "summary" : this._planViewMode = "collapsed";
  }
  async _handleConfirmPlan(t, e) {
    var a, l;
    if (!this.hass || !((a = this._config) != null && a.entity)) return;
    const s = t || this._config.entity, i = this.hass.states[s], r = (i == null ? void 0 : i.attributes) || {}, o = e || r.host_key || ((l = this._transcript) == null ? void 0 : l.host_key);
    await this._executeService("confirm_plan", {
      entity_id: s,
      host_key: o
    });
  }
  _handleRefinePlan() {
    this._inputMode = "plan", this.updateComplete.then(() => {
      var e;
      const t = (e = this.shadowRoot) == null ? void 0 : e.querySelector(
        ".prompt-textarea"
      );
      t == null || t.focus();
    });
  }
  _renderActiveRequest(t, e, s, i, r) {
    var l;
    const o = (t.type || "").toLowerCase(), a = t.requestId || t.id || `req_${e}`;
    if (o === "ask") {
      const p = t.question || t.prompt || t.message || "Input required";
      return h`
        <div
          class="active-request-card active-request-ask"
          data-request-id="${a}"
        >
          <div class="active-request-title">${p}</div>
          <div class="active-request-input-row">
            <input
              type="text"
              class="ask-input"
              ?disabled="${!r}"
              placeholder="Type your answer…"
              .value="${this._askInputs[a] || ""}"
              @input="${(n) => {
        this._askInputs = {
          ...this._askInputs,
          [a]: n.target.value
        };
      }}"
              @keydown="${(n) => {
        n.key === "Enter" && (n.preventDefault(), this._submitAsk(t, a, s, i));
      }}"
            />
            <button
              class="ask-send-btn"
              type="button"
              ?disabled="${!r}"
              @click="${() => this._submitAsk(t, a, s, i)}"
            >
              Send
            </button>
          </div>
        </div>
      `;
    }
    if (o === "choice") {
      const p = t.title || t.question || t.message || "Select an option", n = t.options || [];
      return h`
        <div
          class="active-request-card active-request-choice"
          data-request-id="${a}"
        >
          <div class="active-request-title">${p}</div>
          <div class="choice-options">
            ${n.map(
        (d) => h`
                <button
                  class="choice-opt-btn"
                  type="button"
                  ?disabled="${!r}"
                  @click="${() => this._submitChoice(t, a, d, s, i)}"
                >
                  <span class="opt-title"
                    >${d.title || d.label || d.name || d.id}</span
                  >
                  ${d.description ? h`<span class="opt-desc">${d.description}</span>` : ""}
                </button>
              `
      )}
          </div>
        </div>
      `;
    }
    if (o === "approve") {
      const p = t.title || t.message || t.question || "Approval required", n = (l = t.options) != null && l.length ? t.options : [
        { type: "allow-once", label: "Allow once", optionIndex: 0 },
        { type: "always-allow", label: "Always allow", optionIndex: 1 },
        { type: "deny", label: "Deny", optionIndex: 2 }
      ];
      return h`
        <div
          class="active-request-card active-request-approve"
          data-request-id="${a}"
        >
          <div class="active-request-title">${p}</div>
          <div class="approve-options">
            ${n.map((d, u) => {
        let f = d.label;
        return f || (d.type === "deny" ? f = "Deny" : d.type === "always-allow" ? f = "Always allow" : f = "Allow once"), h`
                <button
                  class="approve-opt-btn opt-${d.type || "allow-once"}"
                  type="button"
                  ?disabled="${!r}"
                  @click="${() => this._submitApprove(
          t,
          a,
          d,
          u,
          s,
          i
        )}"
                >
                  ${f}
                </button>
              `;
      })}
          </div>
        </div>
      `;
    }
    if (o === "action") {
      const p = t.title || t.message || "Notice";
      return h`
        <div
          class="active-request-card active-request-action"
          data-request-id="${a}"
        >
          <div class="active-request-title">${p}</div>
          <button
            class="action-ok-btn"
            type="button"
            ?disabled="${!r}"
            @click="${() => this._submitAction(t, a, s, i)}"
          >
            OK
          </button>
        </div>
      `;
    }
    if (o === "ask-async") {
      const p = t.name || t.title || "Request", n = t.question || t.prompt || "", d = t.options || [], u = !!(t.allowMultiple ?? t.allow_multiple), f = this._askAsyncSelections[a] || [];
      return h`
        <div
          class="active-request-card active-request-ask-async"
          data-request-id="${a}"
        >
          <div class="active-request-title">${p}</div>
          ${n ? h`<div class="active-request-subtitle">${n}</div>` : ""}
          ${d.length > 0 ? h`
                <div class="ask-async-options">
                  ${d.map((g) => {
        const b = g.id || "", y = f.includes(b);
        return h`
                      <button
                        class="ask-async-opt-btn ${y ? "selected" : ""}"
                        type="button"
                        ?disabled="${!r}"
                        @click="${() => this._toggleAskAsyncOption(
          a,
          b,
          u
        )}"
                      >
                        ${y ? "✓ " : ""}${g.label || g.title || g.name || g.id}
                      </button>
                    `;
      })}
                </div>
              ` : ""}
          <div class="ask-async-input-row">
            <input
              type="text"
              class="ask-async-input"
              ?disabled="${!r}"
              placeholder="Type your response…"
              .value="${this._askAsyncInputs[a] || ""}"
              @input="${(g) => {
        this._askAsyncInputs = {
          ...this._askAsyncInputs,
          [a]: g.target.value
        };
      }}"
              @keydown="${(g) => {
        g.key === "Enter" && (g.preventDefault(), this._submitAskAsync(t, a, s, i));
      }}"
            />
            <button
              class="ask-async-submit-btn"
              type="button"
              ?disabled="${!r}"
              @click="${() => this._submitAskAsync(t, a, s, i)}"
            >
              Submit
            </button>
          </div>
        </div>
      `;
    }
    return h``;
  }
  async _submitAsk(t, e, s, i) {
    var g, b, y, $;
    if (!this.hass || !((g = this._config) != null && g.entity)) return;
    const r = this._entityGeneration, o = i || this._config.entity, a = this.hass.states[o], l = (a == null ? void 0 : a.attributes) || {}, p = s || l.host_key || ((b = this._transcript) == null ? void 0 : b.host_key), n = ((y = this.shadowRoot) == null ? void 0 : y.querySelector(
      `.active-request-ask[data-request-id="${e}"] .ask-input`
    )) || (($ = this.shadowRoot) == null ? void 0 : $.querySelector(".ask-input")), d = ((n == null ? void 0 : n.value) || this._askInputs[e] || "").trim();
    if (!await this._executeService("respond_request", {
      entity_id: o,
      host_key: p,
      request_id: e,
      method: "ask",
      display_text: d,
      response: d
    }) || r !== this._entityGeneration) return;
    const f = { ...this._askInputs };
    delete f[e], this._askInputs = f, n && (n.value = "");
  }
  async _submitChoice(t, e, s, i, r) {
    var d, u;
    if (!this.hass || !((d = this._config) != null && d.entity)) return;
    const o = r || this._config.entity, a = this.hass.states[o], l = (a == null ? void 0 : a.attributes) || {}, p = i || l.host_key || ((u = this._transcript) == null ? void 0 : u.host_key), n = s.title || s.label || s.name || s.id;
    await this._executeService("respond_request", {
      entity_id: o,
      host_key: p,
      request_id: e,
      method: "choice",
      option_id: s.id || "",
      display_text: n
    });
  }
  async _submitApprove(t, e, s, i, r, o) {
    var b, y;
    if (!this.hass || !((b = this._config) != null && b.entity)) return;
    const a = o || this._config.entity, l = this.hass.states[a], p = (l == null ? void 0 : l.attributes) || {}, n = r || p.host_key || ((y = this._transcript) == null ? void 0 : y.host_key), d = s.type === "deny", u = s.type === "always-allow", f = s.optionIndex !== void 0 ? s.optionIndex : i, g = d ? "Deny" : u ? s.label || "Always allow" : "Allow once";
    await this._executeService("respond_request", {
      entity_id: a,
      host_key: n,
      request_id: e,
      method: "approve",
      approve: !d,
      add_to_allow_list: u,
      option_index: f,
      display_text: g
    });
  }
  async _submitAction(t, e, s, i) {
    var p, n;
    if (!this.hass || !((p = this._config) != null && p.entity)) return;
    const r = i || this._config.entity, o = this.hass.states[r], a = (o == null ? void 0 : o.attributes) || {}, l = s || a.host_key || ((n = this._transcript) == null ? void 0 : n.host_key);
    await this._executeService("respond_request", {
      entity_id: r,
      host_key: l,
      request_id: e,
      method: "cancel",
      display_text: "OK"
    });
  }
  _toggleAskAsyncOption(t, e, s) {
    const i = this._askAsyncSelections[t] || [];
    let r;
    s ? i.includes(e) ? r = i.filter((o) => o !== e) : r = [...i, e] : r = i.includes(e) ? [] : [e], this._askAsyncSelections = {
      ...this._askAsyncSelections,
      [t]: r
    };
  }
  async _submitAskAsync(t, e, s, i) {
    var $, w, k, C;
    if (!this.hass || !(($ = this._config) != null && $.entity)) return;
    const r = this._entityGeneration, o = i || this._config.entity, a = this.hass.states[o], l = (a == null ? void 0 : a.attributes) || {}, p = s || l.host_key || ((w = this._transcript) == null ? void 0 : w.host_key), n = Array.from(
      this._askAsyncSelections[e] || []
    ), d = ((k = this.shadowRoot) == null ? void 0 : k.querySelector(
      `.active-request-ask-async[data-request-id="${e}"] .ask-async-input`
    )) || ((C = this.shadowRoot) == null ? void 0 : C.querySelector(
      ".ask-async-input"
    )), u = ((d == null ? void 0 : d.value) || this._askAsyncInputs[e] || "").trim(), f = u || (n.length > 0 ? n.join(", ") : "Submit");
    if (!await this._executeService("respond_request", {
      entity_id: o,
      host_key: p,
      request_id: e,
      method: "ask-async",
      option_ids: n,
      response: u || null,
      display_text: f
    }) || r !== this._entityGeneration) return;
    const b = { ...this._askAsyncSelections };
    delete b[e], this._askAsyncSelections = b;
    const y = { ...this._askAsyncInputs };
    delete y[e], this._askAsyncInputs = y, d && (d.value = "");
  }
  _renderFooter(t, e, s, i, r, o, a, l) {
    var p;
    return h`
      <div class="card-footer">
        ${this._inputMode === "plan" ? h`
              <div class="plan-mode-banner">
                <span class="plan-mode-label"
                  >Plan &gt; Iterating on plan</span
                >
                <button
                  class="cancel-plan-mode-btn"
                  type="button"
                  @click="${this._cancelPlanMode}"
                >
                  Esc to cancel
                </button>
              </div>
            ` : ""}

        <div class="footer-control-row">
          <button
            class="brave-toggle-btn ${r ? "brave-active" : ""}"
            type="button"
            aria-pressed="${r ? "true" : "false"}"
            ?disabled="${!l || this._bravePending}"
            @click="${() => this._handleToggleBraveMode(s, e, r)}"
          >
            ${this._bravePending ? "Saving…" : "⚑ Brave"}
          </button>

          <select
            class="model-select"
            ?disabled="${!l}"
            .value="${o}"
            @change="${(n) => this._handleModelSelectChange(n, s, e)}"
          >
            ${a.length > 0 ? a.map(
      (n) => h`
                    <option
                      value="${n.value || n.id}"
                      ?selected="${(n.value || n.id) === o}"
                    >
                      ${n.label || n.name || n.value || n.id}
                    </option>
                  `
    ) : h`<option value="">Default Model</option>`}
          </select>
        </div>

        <div class="prompt-input-row">
          <textarea
            class="prompt-textarea"
            ?disabled="${!l}"
            placeholder="${this._inputMode === "plan" ? "Describe how to refine the plan..." : "Type a message..."}"
            .value="${this._promptText}"
            @input="${this._onPromptInput}"
            @keydown="${(n) => this._onPromptKeydown(n, s, e)}"
            rows="2"
          ></textarea>

          <div class="prompt-actions">
            ${i ? h`
                  ${this._promptText.trim().length > 0 ? h`
                        <button
                          class="steer-btn"
                          type="button"
                          ?disabled="${!l}"
                          @click="${() => this._submitPrompt(s, e)}"
                        >
                          Steer
                        </button>
                      ` : ""}
                  <button
                    class="stop-btn"
                    type="button"
                    title="Stop"
                    ?disabled="${!l}"
                    @click="${() => this._handleStopTask(s, e)}"
                  >
                    Stop
                  </button>
                ` : h`
                  <button
                    class="send-btn"
                    type="button"
                    title="Send"
                    ?disabled="${!l || this._isSending || (t.can_send_prompt ?? ((p = this._transcript) == null ? void 0 : p.can_send_prompt)) === !1}"
                    @click="${() => this._submitPrompt(s, e)}"
                  >
                    Send
                  </button>
                `}
          </div>
        </div>
      </div>
    `;
  }
  _onPromptInput(t) {
    this._promptText = t.target.value;
  }
  _onPromptKeydown(t, e, s) {
    if (t.key === "Escape" && this._inputMode === "plan") {
      t.preventDefault(), this._cancelPlanMode();
      return;
    }
    t.key === "Enter" && !t.shiftKey && (t.preventDefault(), this._submitPrompt(e, s));
  }
  _cancelPlanMode() {
    this._inputMode = "normal";
  }
  async _submitPrompt(t, e) {
    var n, d, u;
    const s = (n = this.shadowRoot) == null ? void 0 : n.querySelector(
      ".prompt-textarea"
    ), i = ((s == null ? void 0 : s.value) || this._promptText || "").trim();
    if (!i || !this.hass || !((d = this._config) != null && d.entity))
      return;
    const r = t || this._config.entity;
    if (r !== this._config.entity || !this.hass.states[r]) return;
    const o = this._entityGeneration, a = this.hass.states[r], l = (a == null ? void 0 : a.attributes) || {}, p = e || l.host_key || ((u = this._transcript) == null ? void 0 : u.host_key);
    this._isSending = !0;
    try {
      if (this._inputMode === "plan") {
        if (!await this._executeService("send_plan_prompt", {
          entity_id: r,
          host_key: p,
          prompt: i
        }) || o !== this._entityGeneration) return;
        this._inputMode = "normal";
      } else if (!await this._executeService("send_prompt", {
        entity_id: r,
        host_key: p,
        prompt: i
      }) || o !== this._entityGeneration) return;
      this._promptText = "", s && (s.value = "");
    } finally {
      o === this._entityGeneration && (this._isSending = !1);
    }
  }
  async _handleToggleBraveMode(t, e, s) {
    var n, d, u;
    if (!this.hass || !((n = this._config) != null && n.entity)) return;
    const i = t || this._config.entity;
    if (i !== this._config.entity || !this.hass.states[i]) return;
    const r = this._entityGeneration, o = this.hass.states[i], a = (o == null ? void 0 : o.attributes) || {}, l = e || a.host_key || ((d = this._transcript) == null ? void 0 : d.host_key), p = s !== void 0 ? s : !!(a.brave_mode ?? ((u = this._transcript) == null ? void 0 : u.brave_mode) ?? !1);
    this._bravePending = !0;
    try {
      await this._executeService("toggle_brave_mode", {
        entity_id: i,
        host_key: l,
        enabled: !p
      });
    } finally {
      r === this._entityGeneration && (this._bravePending = !1);
    }
  }
  async _handleModelSelectChange(t, e, s) {
    var f, g;
    const r = t.target.value;
    if (!this.hass || !((f = this._config) != null && f.entity)) return;
    const o = e || this._config.entity, a = this.hass.states[o], l = (a == null ? void 0 : a.attributes) || {}, p = s || l.host_key || ((g = this._transcript) == null ? void 0 : g.host_key), n = r.indexOf(":");
    let d = r, u = null;
    n !== -1 && (d = r.slice(0, n), u = r.slice(n + 1) || null), await this._executeService("select_model", {
      entity_id: o,
      host_key: p,
      model_id: d,
      effort_id: u
    });
  }
  async _handleStopTask(t, e) {
    var a, l;
    if (!this.hass || !((a = this._config) != null && a.entity)) return;
    const s = t || this._config.entity, i = this.hass.states[s], r = (i == null ? void 0 : i.attributes) || {}, o = e || r.host_key || ((l = this._transcript) == null ? void 0 : l.host_key);
    await this._executeService("cancel_task", {
      entity_id: s,
      host_key: o
    });
  }
  _renderProgressingStep(t) {
    const e = t.title || t.name || t.text || "Working…";
    return h`
      <div class="progressing-step-item">
        <span class="spinner"></span>
        <span class="progressing-step-content">
          <span>${e}</span>
          ${t.description ? h`<span class="progressing-step-description"
                >${t.description}</span
              >` : ""}
        </span>
      </div>
    `;
  }
  _renderTranscriptItem(t) {
    const e = t.type;
    if (e === "user-prompt") {
      const u = t.prompt || t.text || "";
      return h`
        <div class="transcript-item item-user-prompt">
          <div class="bubble-header">
            <span class="bubble-role">User</span>
          </div>
          <div class="bubble-content">${u}</div>
        </div>
      `;
    }
    if (e === "user-response") {
      const u = t.prompt || "", f = t.displayText || t.text || "";
      return h`
        <div class="transcript-item item-user-response">
          <div class="bubble-header">
            <span class="bubble-role">Response</span>
          </div>
          ${u && f ? h`<div class="response-prompt">Prompt: ${u}</div>` : ""}
          <div class="bubble-content">${f || u}</div>
        </div>
      `;
    }
    if (e === "system-message") {
      const u = t.text || t.message || "", f = t.level || "info";
      return h`
        <div class="transcript-item item-system-message level-${f}">
          <span>${f === "error" ? "❌" : f === "warning" ? "⚠️" : "ℹ️"}</span>
          <span>${u}</span>
          ${t.details ? h`<span class="item-system-message-details"
                >${t.details}</span
              >` : ""}
        </div>
      `;
    }
    if (e === "skills-status") {
      const u = t.status || t.text || "", f = Array.isArray(t.newSkills) ? t.newSkills : [], g = Array.isArray(t.failedSkills) ? t.failedSkills : [];
      return h`
        <div class="transcript-item item-skills-status">
          <span class="skills-label">Skills:</span>
          <span>${u}</span>
          ${f.length > 0 ? h`<span class="skills-detail"
                >New: ${f.join(", ")}</span
              >` : ""}
          ${g.length > 0 ? h`<span class="skills-detail"
                >Failed: ${g.map((b) => {
        if (typeof b == "string") return b;
        const y = b.error || b.message || b.reason || "";
        return [b.path || b.name, y].filter(Boolean).join(": ");
      }).join(", ")}</span
              >` : ""}
        </div>
      `;
    }
    const s = t.vm, i = (s == null ? void 0 : s.type) === "result" || t.type === "result" || t.status === "result" || t.result !== void 0;
    let r = "Step", o = "badge-step";
    if (i) {
      const u = ((s == null ? void 0 : s.status) || t.status || "").toLowerCase(), f = (s == null ? void 0 : s.errorCode) || t.errorCode, g = !!(s != null && s.cancelled || t.cancelled);
      f || u === "error" || u === "failed" ? (r = "Task Error", o = "badge-error") : g || u === "cancelled" ? (r = "Task Cancelled", o = "badge-cancelled") : (r = "Task Result:", o = "badge-result");
    }
    const a = (s == null ? void 0 : s.title) || (s == null ? void 0 : s.name) || t.title || t.name || (i ? "Task Result" : "Step"), l = (s == null ? void 0 : s.description) || t.description, p = (s == null ? void 0 : s.errorCode) || t.errorCode, n = (s == null ? void 0 : s.text) || (s == null ? void 0 : s.result) || t.text || t.result || "", d = (s == null ? void 0 : s.changesSummary) || t.changesSummary;
    return h`
      <div class="transcript-item item-step">
        <div class="step-header">
          <span class="step-badge ${o}">${r}</span>
          <span class="step-title">${a}</span>
        </div>
        ${p ? h`<div class="step-error-code">Error: ${p}</div>` : ""}
        ${l ? h`<div class="step-description">
              ${Z(l)}
            </div>` : ""}
        ${n ? Z(n) : ""}
        ${d ? ke(d) : ""}
      </div>
    `;
  }
}
x([
  pt({ attribute: !1 })
], m.prototype, "hass", 1);
x([
  v()
], m.prototype, "_config", 2);
x([
  v()
], m.prototype, "_transcript", 2);
x([
  v()
], m.prototype, "_transcriptLoading", 2);
x([
  v()
], m.prototype, "_transcriptError", 2);
x([
  v()
], m.prototype, "_actionError", 2);
x([
  v()
], m.prototype, "_showScrollBottom", 2);
x([
  v()
], m.prototype, "_isKicking", 2);
x([
  v()
], m.prototype, "_promptText", 2);
x([
  v()
], m.prototype, "_inputMode", 2);
x([
  v()
], m.prototype, "_isSending", 2);
x([
  v()
], m.prototype, "_bravePending", 2);
x([
  v()
], m.prototype, "_planViewMode", 2);
x([
  v()
], m.prototype, "_selectedPlanSection", 2);
x([
  v()
], m.prototype, "_askInputs", 2);
x([
  v()
], m.prototype, "_askAsyncSelections", 2);
x([
  v()
], m.prototype, "_askAsyncInputs", 2);
customElements.get("junie-remote-card") || customElements.define("junie-remote-card", m);
export {
  m as JunieRemoteCard
};
