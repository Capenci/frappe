// SOAR Playbook - Workflow-Builder-Style Graph View
// ==================================================

frappe.ui.form.on("SOAR Playbook", {
refresh(frm) {
if (!frm.is_new() && frm.doc.is_active) {
frm.add_custom_button(
__("Execute Now"),
() => {
frappe.confirm(
__("Execute playbook <b>{0}</b> now?", [frm.doc.title]),
() => {
frm.call("execute").then((r) => {
if (r.message)
frappe.set_route("Form", "SOAR Playbook Execution", r.message);
});
}
);
},
__("Actions")
);
frm.add_custom_button(
__("View Executions"),
() =>
frappe.set_route("List", "SOAR Playbook Execution", {
playbook: frm.doc.name,
}),
__("Actions")
);
}

setTimeout(() => {
var w = frm.fields_dict.graph_canvas && frm.fields_dict.graph_canvas.$wrapper;
if (!w || !w.length) return;
if (!frm._pgv) frm._pgv = new PGV(w[0], frm);
frm._pgv.render();
}, 250);
},

validate(frm) {
var seen = new Set();
(frm.doc.nodes || []).forEach(function(r) {
if (seen.has(r.node_id)) frappe.throw(__("Duplicate Node ID: {0}", [r.node_id]));
seen.add(r.node_id);
});
},
});

/* --- Node types & visual mapping --- */
var NTYPES = {
Start:            { shape: "state", bg: "#27ae60", fg: "#fff",     border: "#1e8449" },
End:              { shape: "state", bg: "#e74c3c", fg: "#fff",     border: "#c0392b" },
Action:           { shape: "action", bg: "#687178", fg: "#fff",    border: "#4a5157" },
Condition:        { shape: "state", bg: "#f39c12", fg: "#fff",     border: "#d68910" },
"Parallel Split": { shape: "action", bg: "#8e44ad", fg: "#fff",    border: "#6c3483" },
"Parallel Join":  { shape: "action", bg: "#8e44ad", fg: "#fff",    border: "#6c3483" },
Wait:             { shape: "state", bg: "#fff",     fg: "#687178", border: "#687178" },
};
var NTYPE_LIST = Object.keys(NTYPES);

/* --- Main Class --- */
class PGV {
constructor(wrapper, frm) {
this.wrap = wrapper;
this.frm = frm;
this.sel = null;
this.selEdge = null;
this.connecting = null; // { fromId, handle }
this._built = false;
this._connectMouseMove = null;
this._connectMouseUp = null;
}

get N() { return this.frm.doc.nodes || []; }
get E() { return this.frm.doc.edges || []; }
nRow(id) { return this.N.find(function(n) { return n.node_id === id; }); }
eKey(e) { return e.from_node + ">" + e.to_node; }
uid() { return "n" + Math.random().toString(36).slice(2, 10); }

/* -- measure node -- */
nW(n) {
var meta = NTYPES[n.node_type] || NTYPES.Action;
if (meta.shape === "state")
return Math.max(120, (n.node_name || n.node_type || "").length * 9 + 50);
return Math.max(100, (n.node_name || n.node_type || "").length * 7 + 30);
}
nH(n) {
return (NTYPES[n.node_type] || NTYPES.Action).shape === "state" ? 48 : 32;
}

/* -- handle positions (T R B L) -- */
handles(n) {
var w = this.nW(n), h = this.nH(n);
var x = n.position_x || 0, y = n.position_y || 0;
return {
top:    { x: x + w / 2, y: y },
right:  { x: x + w,     y: y + h / 2 },
bottom: { x: x + w / 2, y: y + h },
left:   { x: x,         y: y + h / 2 },
};
}

/* -- build DOM -- */
_build() {
if (this._built && this.root && this.root.isConnected) return;
this._built = true;
this.wrap.innerHTML = "";

this.root = mk("div", "pgv");
this.wrap.appendChild(this.root);

this.canvas = mk("div", "pgv-canvas");
this.root.appendChild(this.canvas);

// SVG for edges
this.svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
this.svg.classList.add("pgv-svg");
this.svg.setAttribute("xmlns", "http://www.w3.org/2000/svg");
this.svg.innerHTML =
'<defs>' +
'<marker id="pgv-arr" viewBox="0 0 10 10" refX="10" refY="5" markerWidth="12" markerHeight="12" orient="auto-start-reverse" markerUnits="strokeWidth">' +
'<path d="M0,0 L10,5 L0,10" fill="none" stroke="#687178" stroke-width="1"/>' +
'</marker>' +
'<marker id="pgv-arr-sel" viewBox="0 0 10 10" refX="10" refY="5" markerWidth="12" markerHeight="12" orient="auto-start-reverse" markerUnits="strokeWidth">' +
'<path d="M0,0 L10,5 L0,10" fill="none" stroke="#2490EF" stroke-width="1"/>' +
'</marker>' +
'<marker id="pgv-arr-tmp" viewBox="0 0 10 10" refX="10" refY="5" markerWidth="10" markerHeight="10" orient="auto-start-reverse" markerUnits="strokeWidth">' +
'<path d="M0,0 L10,5 L0,10" fill="none" stroke="#2490EF" stroke-width="1"/>' +
'</marker>' +
'</defs>';
this.canvas.appendChild(this.svg);

// Temp edge (for connecting)
this.tmpEdge = document.createElementNS("http://www.w3.org/2000/svg", "path");
this.tmpEdge.classList.add("pgv-tmp");
this.tmpEdge.setAttribute("marker-end", "url(#pgv-arr-tmp)");
this.tmpEdge.style.display = "none";
this.svg.appendChild(this.tmpEdge);

// Node container
this.nodeBox = mk("div", "pgv-nodes");
this.canvas.appendChild(this.nodeBox);

// Label overlay
this.lblBox = mk("div", "pgv-lbls");
this.canvas.appendChild(this.lblBox);

this._mkToolbar();
this._mkZoom();

// Click on background: deselect or cancel connect
var self = this;
this.root.addEventListener("click", function(e) {
if (e.target === self.root || e.target === self.canvas || e.target === self.nodeBox) {
self._desel();
}
});
document.addEventListener("keydown", function(e) { self._onKey(e); });
}

/* -- toolbar -- */
_mkToolbar() {
var bar = mk("div", "pgv-bar");
var sel = mk("select", "pgv-tsel");
NTYPE_LIST.forEach(function(t) {
var o = mk("option");
o.value = t; o.textContent = t;
if (t === "Action") o.selected = true;
sel.appendChild(o);
});
bar.appendChild(sel);

var self = this;
var addBtn = mk("button", "btn btn-xs btn-primary");
addBtn.textContent = "+ " + __("Add Node");
addBtn.onclick = function() {
var cx = self.root.scrollLeft + self.root.clientWidth / 2;
var cy = self.root.scrollTop + self.root.clientHeight / 2;
self._addNode(sel.value || "Action", cx, cy);
};
bar.appendChild(addBtn);

var layBtn = mk("button", "btn btn-xs btn-default");
layBtn.textContent = __("Auto Layout");
layBtn.onclick = function() { self._layout(); self._paint(); self.frm.dirty(); };
bar.appendChild(layBtn);

var delBtn = mk("button", "btn btn-xs btn-danger");
delBtn.textContent = __("Delete");
delBtn.onclick = function() { self._delSel(); };
bar.appendChild(delBtn);

this.root.appendChild(bar);
}

_mkZoom() {
var z = mk("div", "pgv-zoom");
var self = this;
["+", "\u2212", __("Fit")].forEach(function(label) {
var b = mk("button", "btn btn-xs btn-default pgv-zbtn");
b.textContent = label;
b.onclick = function() {
var cur = parseFloat(self.canvas.style.transform.replace("scale(","").replace(")","") || "1") || 1;
if (label === "+") cur = Math.min(2, cur + 0.1);
else if (label === "\u2212") cur = Math.max(0.3, cur - 0.1);
else cur = 1;
self.canvas.style.transform = "scale(" + cur + ")";
self.canvas.style.transformOrigin = "0 0";
};
z.appendChild(b);
});
this.root.appendChild(z);
}

/* -- render -- */
render() {
this._build();
if (this.N.length && this.N.every(function(n) { return !n.position_x && !n.position_y; }))
this._layout();
this._paint();
}

_paint() {
this._paintNodes();
this._paintEdges();
this._paintLabels();
this._sizeCanvas();
}

_sizeCanvas() {
var mx = 900, my = 500;
var self = this;
this.N.forEach(function(n) {
mx = Math.max(mx, (n.position_x || 0) + self.nW(n) + 120);
my = Math.max(my, (n.position_y || 0) + self.nH(n) + 120);
});
this.canvas.style.width = mx + "px";
this.canvas.style.height = my + "px";
this.svg.setAttribute("width", mx);
this.svg.setAttribute("height", my);
this.svg.style.width = mx + "px";
this.svg.style.height = my + "px";
this.nodeBox.style.width = mx + "px";
this.nodeBox.style.height = my + "px";
this.lblBox.style.width = mx + "px";
this.lblBox.style.height = my + "px";
}

/* -- paint nodes -- */
_paintNodes() {
this.nodeBox.innerHTML = "";
var self = this;
this.N.forEach(function(n) { self._mkNode(n); });
}

_mkNode(n) {
var t = NTYPES[n.node_type] || NTYPES.Action;
var w = this.nW(n), h = this.nH(n);
var isState = t.shape === "state";

var el = mk("div", "pgv-node " + (isState ? "pgv-state" : "pgv-action"));
el.dataset.nid = n.node_id;
el.style.left = (n.position_x || 0) + "px";
el.style.top = (n.position_y || 0) + "px";
el.style.width = w + "px";
el.style.height = h + "px";
el.style.lineHeight = h + "px";
el.style.backgroundColor = t.bg;
el.style.borderColor = t.border;
el.style.color = t.fg;

if (n.node_id === this.sel) el.classList.add("pgv-sel");

// Label
var lbl = mk("span", "pgv-nlbl");
lbl.textContent = n.node_name || n.node_type;
el.appendChild(lbl);

// 4 connection handles
var positions = ["top", "right", "bottom", "left"];
var self = this;
positions.forEach(function(pos) {
if (n.node_type === "Start" && (pos === "top" || pos === "left")) return;
if (n.node_type === "End" && (pos === "bottom" || pos === "right")) return;
var hd = mk("div", "pgv-h pgv-h-" + pos);
// Drag-based connection: mousedown on handle starts it
hd.addEventListener("mousedown", function(e) {
e.stopPropagation();
e.preventDefault();
self._startDragConnect(n.node_id, pos);
});
el.appendChild(hd);
});

// Click to select (or finish connection if connecting)
el.addEventListener("click", function(e) {
e.stopPropagation();
self._selNode(n.node_id);
});
// Dbl-click to edit
el.addEventListener("dblclick", function(e) {
e.stopPropagation();
self._editNode(n.node_id);
});
// Drag to move node
this._drag(el, n);

this.nodeBox.appendChild(el);
}

/* -- paint edges -- */
_paintEdges() {
var old = this.svg.querySelectorAll(".pgv-eg");
for (var i = 0; i < old.length; i++) old[i].remove();

var self = this;
this.E.forEach(function(e) {
var from = self.nRow(e.from_node), to = self.nRow(e.to_node);
if (!from || !to) return;
var key = self.eKey(e), isSel = (key === self.selEdge);

var g = document.createElementNS("http://www.w3.org/2000/svg", "g");
g.classList.add("pgv-eg");
if (isSel) g.classList.add("pgv-esel");
g.dataset.key = key;

var result = self._edgePath(from, to);

// Visible line
var p = document.createElementNS("http://www.w3.org/2000/svg", "path");
p.setAttribute("d", result.d);
p.classList.add("pgv-eline");
p.setAttribute("marker-end", isSel ? "url(#pgv-arr-sel)" : "url(#pgv-arr)");
g.appendChild(p);

// Hit area (wider invisible path for clicking)
var hit = document.createElementNS("http://www.w3.org/2000/svg", "path");
hit.setAttribute("d", result.d);
hit.classList.add("pgv-ehit");
hit.addEventListener("click", function(ev) { ev.stopPropagation(); self._selEdge(key); });
g.appendChild(hit);

g._mid = { x: result.mx, y: result.my };
g._data = e;
self.svg.appendChild(g);
});
}

/* -- smooth step edge path -- */
_edgePath(from, to) {
var fh = this.handles(from), th = this.handles(to);
var fc = { x: (from.position_x||0) + this.nW(from)/2, y: (from.position_y||0) + this.nH(from)/2 };
var tc = { x: (to.position_x||0) + this.nW(to)/2, y: (to.position_y||0) + this.nH(to)/2 };
var dx = tc.x - fc.x, dy = tc.y - fc.y;

var fp, tp;
if (Math.abs(dy) >= Math.abs(dx)) {
fp = dy >= 0 ? "bottom" : "top";
tp = dy >= 0 ? "top" : "bottom";
} else {
fp = dx >= 0 ? "right" : "left";
tp = dx >= 0 ? "left" : "right";
}

var s = fh[fp], e = th[tp];
var R = 20;
var d, mx, my;

if ((fp === "bottom" && tp === "top") || (fp === "top" && tp === "bottom")) {
var midY = (s.y + e.y) / 2;
d = this._stepV(s.x, s.y, e.x, e.y, midY, R);
mx = (s.x + e.x) / 2; my = midY;
} else if ((fp === "right" && tp === "left") || (fp === "left" && tp === "right")) {
var midX = (s.x + e.x) / 2;
d = this._stepH(s.x, s.y, e.x, e.y, midX, R);
mx = midX; my = (s.y + e.y) / 2;
} else {
var off = 50;
d = "M" + s.x + "," + s.y + " C" + s.x + "," + (s.y+off) + " " + e.x + "," + (e.y-off) + " " + e.x + "," + e.y;
mx = (s.x+e.x)/2; my = (s.y+e.y)/2;
}
return { d: d, mx: mx, my: my };
}

_stepV(sx, sy, tx, ty, my, R) {
if (sx === tx) return "M" + sx + "," + sy + " L" + tx + "," + ty;
var r = Math.min(R, Math.abs(my-sy)/2, Math.abs(ty-my)/2, Math.abs(tx-sx)/2);
if (r < 1) r = 1;
var d1 = my > sy ? 1 : -1, dxDir = tx > sx ? 1 : -1, d2 = ty > my ? 1 : -1;
return "M" + sx + "," + sy +
" L" + sx + "," + (my - r*d1) +
" Q" + sx + "," + my + " " + (sx + r*dxDir) + "," + my +
" L" + (tx - r*dxDir) + "," + my +
" Q" + tx + "," + my + " " + tx + "," + (my + r*d2) +
" L" + tx + "," + ty;
}

_stepH(sx, sy, tx, ty, mx, R) {
if (sy === ty) return "M" + sx + "," + sy + " L" + tx + "," + ty;
var r = Math.min(R, Math.abs(mx-sx)/2, Math.abs(tx-mx)/2, Math.abs(ty-sy)/2);
if (r < 1) r = 1;
var d1 = mx > sx ? 1 : -1, dyDir = ty > sy ? 1 : -1, d2 = tx > mx ? 1 : -1;
return "M" + sx + "," + sy +
" L" + (mx - r*d1) + "," + sy +
" Q" + mx + "," + sy + " " + mx + "," + (sy + r*dyDir) +
" L" + mx + "," + (ty - r*dyDir) +
" Q" + mx + "," + ty + " " + (mx + r*d2) + "," + ty +
" L" + tx + "," + ty;
}

/* -- paint edge labels -- */
_paintLabels() {
this.lblBox.innerHTML = "";
var self = this;
var groups = this.svg.querySelectorAll(".pgv-eg");
for (var i = 0; i < groups.length; i++) {
var g = groups[i];
var e = g._data;
if (!e || !e.label) continue;
var mid = g._mid, isSel = (self.eKey(e) === self.selEdge);
var b = mk("div", "pgv-lbl" + (isSel ? " pgv-lbl-sel" : ""));
b.style.left = mid.x + "px";
b.style.top = mid.y + "px";
b.textContent = e.label;
(function(key) {
b.addEventListener("click", function(ev) { ev.stopPropagation(); self._selEdge(key); });
})(self.eKey(e));
self.lblBox.appendChild(b);
}
}

/* -- drag to move nodes -- */
_drag(el, n) {
var self = this;
var dragging = false, sx, sy, ox, oy;
el.addEventListener("mousedown", function(e) {
// Don't drag if clicking on a handle
if (e.target.classList.contains("pgv-h") || e.button !== 0) return;
// Don't drag if in connecting mode
if (self.connecting) return;
e.preventDefault();
dragging = true;
sx = e.clientX; sy = e.clientY;
ox = n.position_x || 0; oy = n.position_y || 0;
el.classList.add("pgv-dragging");

function onmove(ev) {
if (!dragging) return;
n.position_x = Math.max(0, Math.round(ox + ev.clientX - sx));
n.position_y = Math.max(0, Math.round(oy + ev.clientY - sy));
el.style.left = n.position_x + "px";
el.style.top = n.position_y + "px";
self._paintEdges();
self._paintLabels();
self._sizeCanvas();
}
function onup() {
dragging = false;
el.classList.remove("pgv-dragging");
document.removeEventListener("mousemove", onmove);
document.removeEventListener("mouseup", onup);
if (n.position_x !== ox || n.position_y !== oy) self.frm.dirty();
}
document.addEventListener("mousemove", onmove);
document.addEventListener("mouseup", onup);
});
}

/* ============================================================
   EDGE CONNECTION (drag-based: mousedown handle -> drag -> mouseup on target)
   Works in both directions: A->B and B->A
   ============================================================ */
_startDragConnect(fromId, handle) {
var self = this;

// Store connection state
this.connecting = { fromId: fromId, handle: handle };
this.tmpEdge.style.display = "";
this.root.classList.add("pgv-conn");

var h = this.handles(this.nRow(fromId))[handle];
this.tmpEdge.setAttribute("d", "M" + h.x + "," + h.y + " L" + h.x + "," + h.y);

// mousemove: draw temp edge towards cursor
function onMouseMove(ev) {
if (!self.connecting) return;
var rect = self.canvas.getBoundingClientRect();
var mx = ev.clientX - rect.left;
var my = ev.clientY - rect.top;
var hn = self.handles(self.nRow(self.connecting.fromId))[self.connecting.handle];
var d;
if (Math.abs(my - hn.y) >= Math.abs(mx - hn.x)) {
d = self._stepV(hn.x, hn.y, mx, my, (hn.y + my) / 2, 12);
} else {
d = self._stepH(hn.x, hn.y, mx, my, (hn.x + mx) / 2, 12);
}
self.tmpEdge.setAttribute("d", d);
}

// mouseup: complete connection if on a target node, otherwise cancel
function onMouseUp(ev) {
document.removeEventListener("mousemove", onMouseMove);
document.removeEventListener("mouseup", onMouseUp);

if (!self.connecting) return;
var srcId = self.connecting.fromId;
self._cancelConnect();

// Walk up from the mouseup target to find a .pgv-node
var target = document.elementFromPoint(ev.clientX, ev.clientY);
var nodeEl = target ? target.closest(".pgv-node") : null;
var toId = nodeEl ? nodeEl.dataset.nid : null;

if (toId && toId !== srcId) {
self._promptEdge(srcId, toId);
}
}

document.addEventListener("mousemove", onMouseMove);
document.addEventListener("mouseup", onMouseUp);
}

_cancelConnect() {
this.connecting = null;
this.tmpEdge.style.display = "none";
this.root.classList.remove("pgv-conn");
}

_promptEdge(fromId, toId) {
var self = this;
// Check if this exact edge already exists
var exists = this.E.find(function(e) { return e.from_node === fromId && e.to_node === toId; });
if (exists) {
frappe.show_alert({ message: __("Edge already exists"), indicator: "orange" });
return;
}
var fn = this.nRow(fromId);
if (fn && fn.node_type === "Condition") {
var dlg = new frappe.ui.Dialog({
title: __("Edge from Condition"),
fields: [
{ fieldname: "label", fieldtype: "Data", label: __("Label (e.g. True / False)") },
{ fieldname: "condition", fieldtype: "Code", label: __("Condition"), options: "PythonExpression" },
],
primary_action_label: __("Create"),
primary_action: function(v) { self._mkEdge(fromId, toId, v.label, v.condition); dlg.hide(); },
});
dlg.show();
} else {
this._mkEdge(fromId, toId);
}
}

_mkEdge(fromId, toId, label, condition) {
var r = frappe.model.add_child(this.frm.doc, "SOAR Playbook Edge", "edges");
r.from_node = fromId;
r.to_node = toId;
if (label) r.label = label;
if (condition) r.condition = condition;
this.frm.dirty();
this._refreshTbl();
this._paint();
}

/* -- add/edit nodes -- */
_addNode(type, cx, cy) {
var id = this.uid();
var cnt = this.N.filter(function(n) { return n.node_type === type; }).length + 1;
var fields = [{ fieldname: "node_name", fieldtype: "Data", label: __("Node Name"), "default": type + " " + cnt, reqd: 1 }];
if (type === "Action") fields.push({
fieldname: "action_type", fieldtype: "Select", label: __("Action Type"),
options: "\nScript\nAPI Call\nSend Email\nSend Notification\nUpdate Document\nCreate Document\nCustom",
});
var self = this;
var dlg = new frappe.ui.Dialog({
title: __("Add {0} Node", [type]),
fields: fields,
primary_action_label: __("Add"),
primary_action: function(v) {
var r = frappe.model.add_child(self.frm.doc, "SOAR Playbook Node", "nodes");
r.node_id = id; r.node_name = v.node_name; r.node_type = type;
if (v.action_type) r.action_type = v.action_type;
r.timeout_seconds = 300; r.retry_count = 0;
r.position_x = Math.max(20, Math.round(cx - 60));
r.position_y = Math.max(20, Math.round(cy - 24));
self.frm.dirty();
self._refreshTbl();
self._paint();
self._selNode(id);
dlg.hide();
},
});
dlg.show();
}

_editNode(nid) {
var n = this.nRow(nid);
if (!n) return;
var self = this;
var dlg = new frappe.ui.Dialog({
title: __("Edit Node") + " \u2013 " + n.node_name,
fields: [
{ fieldname: "node_name", fieldtype: "Data", label: __("Name"), "default": n.node_name, reqd: 1 },
{ fieldname: "node_type", fieldtype: "Select", label: __("Type"), "default": n.node_type, options: NTYPE_LIST.join("\n"), reqd: 1 },
{ fieldname: "action_type", fieldtype: "Select", label: __("Action Type"), "default": n.action_type || "",
  options: "\nScript\nAPI Call\nSend Email\nSend Notification\nUpdate Document\nCreate Document\nCustom",
  depends_on: "eval:doc.node_type=='Action'" },
{ fieldname: "sb1", fieldtype: "Section Break", label: __("Execution") },
{ fieldname: "timeout_seconds", fieldtype: "Int", label: __("Timeout (s)"), "default": n.timeout_seconds || 300 },
{ fieldname: "retry_count", fieldtype: "Int", label: __("Retry Count"), "default": n.retry_count || 0 },
{ fieldname: "sb2", fieldtype: "Section Break", label: __("Script / Config") },
{ fieldname: "script", fieldtype: "Code", label: __("Script"), "default": n.script || "", options: "Python" },
{ fieldname: "configuration", fieldtype: "Code", label: __("Configuration"), "default": n.configuration || "", options: "JSON" },
],
size: "large",
primary_action_label: __("Save"),
primary_action: function(v) {
n.node_name = v.node_name;
n.node_type = v.node_type;
n.action_type = v.action_type || "";
n.timeout_seconds = v.timeout_seconds;
n.retry_count = v.retry_count;
n.script = v.script;
n.configuration = v.configuration;
self.frm.dirty();
self._refreshTbl();
self._paint();
dlg.hide();
},
});
dlg.show();
}

/* -- selection -- */
_selNode(id) { this.sel = id; this.selEdge = null; this._applySel(); }
_selEdge(key) { this.selEdge = key; this.sel = null; this._applySel(); }
_desel() { this.sel = null; this.selEdge = null; this._applySel(); }

_applySel() {
var self = this;
var nodes = this.nodeBox.querySelectorAll(".pgv-node");
for (var i = 0; i < nodes.length; i++) {
nodes[i].classList.toggle("pgv-sel", nodes[i].dataset.nid === self.sel);
}
var groups = this.svg.querySelectorAll(".pgv-eg");
for (var j = 0; j < groups.length; j++) {
var g = groups[j];
var s = (g.dataset.key === self.selEdge);
g.classList.toggle("pgv-esel", s);
var p = g.querySelector(".pgv-eline");
if (p) p.setAttribute("marker-end", s ? "url(#pgv-arr-sel)" : "url(#pgv-arr)");
}
this._paintLabels();
}

/* -- delete -- */
_delSel() {
var self = this;
if (this.sel) {
frappe.confirm(__("Delete this node and its edges?"), function() {
var id = self.sel;
self.frm.doc.edges = (self.frm.doc.edges || []).filter(function(e) {
return e.from_node !== id && e.to_node !== id;
});
self.frm.doc.edges.forEach(function(e, i) { e.idx = i + 1; });
self.frm.doc.nodes = self.frm.doc.nodes.filter(function(n) { return n.node_id !== id; });
self.frm.doc.nodes.forEach(function(n, i) { n.idx = i + 1; });
self.sel = null;
self.frm.dirty();
self._refreshTbl();
self._paint();
});
} else if (this.selEdge) {
var parts = this.selEdge.split(">");
var f = parts[0], t = parts[1];
this.frm.doc.edges = (this.frm.doc.edges || []).filter(function(e) {
return !(e.from_node === f && e.to_node === t);
});
this.frm.doc.edges.forEach(function(e, i) { e.idx = i + 1; });
this.selEdge = null;
this.frm.dirty();
this._refreshTbl();
this._paint();
} else {
frappe.show_alert({ message: __("Select a node or edge first"), indicator: "yellow" });
}
}

/* -- keyboard -- */
_onKey(e) {
if (!this.wrap.offsetParent) return;
var tag = document.activeElement && document.activeElement.tagName;
if ((e.key === "Delete" || e.key === "Backspace") && tag !== "INPUT" && tag !== "TEXTAREA" && tag !== "SELECT") {
if (this.sel || this.selEdge) { e.preventDefault(); this._delSel(); }
}
if (e.key === "Escape") { this._cancelConnect(); this._desel(); }
}

/* -- auto layout (BFS layers) -- */
_layout() {
var nodes = this.N, edges = this.E;
if (!nodes.length) return;
var adj = {};
nodes.forEach(function(n) { adj[n.node_id] = []; });
edges.forEach(function(e) { if (adj[e.from_node]) adj[e.from_node].push(e.to_node); });
var start = nodes.find(function(n) { return n.node_type === "Start"; });
var layers = {}, vis = new Set();
if (start) {
var q = [[start.node_id, 0]];
vis.add(start.node_id);
while (q.length) {
var item = q.shift();
var id = item[0], l = item[1];
if (!layers[l]) layers[l] = [];
layers[l].push(id);
var nexts = adj[id] || [];
nexts.forEach(function(next) {
if (!vis.has(next)) { vis.add(next); q.push([next, l + 1]); }
});
}
}
var ml = 0;
Object.keys(layers).forEach(function(k) { ml = Math.max(ml, parseInt(k)); });
var self = this;
nodes.forEach(function(n) {
if (!vis.has(n.node_id)) {
ml++;
if (!layers[ml]) layers[ml] = [];
layers[ml].push(n.node_id);
}
});
var gx = 220, gy = 110;
Object.keys(layers).forEach(function(l) {
var ids = layers[l];
var total = ids.length * gx;
var sx = Math.max(60, 500 - total / 2 + gx / 2 - 60);
ids.forEach(function(id, i) {
var nd = self.nRow(id);
if (nd) {
nd.position_x = Math.round(sx + i * gx);
nd.position_y = Math.round(50 + parseInt(l) * gy);
}
});
});
}

/* -- helper -- */
_refreshTbl() {
this.frm.refresh_field("nodes");
this.frm.refresh_field("edges");
}
}

function mk(tag, cls) {
var e = document.createElement(tag);
if (cls) e.className = cls;
return e;
}
