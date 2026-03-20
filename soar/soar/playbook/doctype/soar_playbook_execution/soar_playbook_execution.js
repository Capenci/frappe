// SOAR Playbook Execution — visual execution flow & node result viewer
frappe.ui.form.on("SOAR Playbook Execution", {
	refresh(frm) {
		_render_execution_graph(frm);
		_add_actions(frm);
		_maybe_auto_refresh(frm);
	},
});

/* ─── Actions ──────────────────────────────────────────── */
function _add_actions(frm) {
	if (frm.doc.status === "Running" || frm.doc.status === "Queued") {
		frm.add_custom_button(__("Cancel Execution"), () => {
			frappe.confirm(__("Cancel this execution?"), () => {
				frm.call("cancel_execution").then(() => frm.reload_doc());
			});
		}, __("Actions"));
	}
	if (frm.doc.playbook) {
		frm.add_custom_button(__("Open Playbook"), () => {
			frappe.set_route("Form", "SOAR Playbook", frm.doc.playbook);
		}, __("Actions"));
	}
}

/* ─── Auto-refresh for running executions ──────────────── */
function _maybe_auto_refresh(frm) {
	if (frm._exec_timer) {
		clearInterval(frm._exec_timer);
		frm._exec_timer = null;
	}
	if (frm.doc.status === "Running" || frm.doc.status === "Queued") {
		frm._exec_timer = setInterval(() => {
			if (frm.doc.status !== "Running" && frm.doc.status !== "Queued") {
				clearInterval(frm._exec_timer);
				frm._exec_timer = null;
				return;
			}
			frm.reload_doc();
		}, 3000);
	}
}

/* ─── Visual Execution Graph ───────────────────────────── */
function _render_execution_graph(frm) {
	const wrapper = frm.fields_dict.execution_graph?.$wrapper;
	if (!wrapper) return;
	wrapper.empty();

	const steps = frm.doc.step_results || [];
	if (!steps.length && frm.doc.status === "Queued") {
		wrapper.html(`
			<div class="exec-flow-empty text-muted text-center" style="padding:40px 0">
				<i class="fa fa-clock-o fa-2x mb-2" style="display:block"></i>
				Waiting to start execution…
			</div>
		`);
		return;
	}
	if (!steps.length) {
		wrapper.html(`
			<div class="exec-flow-empty text-muted text-center" style="padding:40px 0">
				No step results recorded yet.
			</div>
		`);
		return;
	}

	// Summary bar
	const total = steps.length;
	const completed = steps.filter(s => s.status === "Completed").length;
	const failed = steps.filter(s => s.status === "Failed").length;
	const running = steps.filter(s => s.status === "Running").length;
	const skipped = steps.filter(s => s.status === "Skipped").length;
	const pending = steps.filter(s => s.status === "Pending").length;

	let html = `<div class="exec-flow">`;

	// ── Summary strip ──
	html += `<div class="exec-summary">`;
	html += `<span class="exec-summary-item"><strong>${total}</strong> Steps</span>`;
	if (completed) html += `<span class="exec-summary-item exec-s-completed">${completed} Completed</span>`;
	if (failed) html += `<span class="exec-summary-item exec-s-failed">${failed} Failed</span>`;
	if (running) html += `<span class="exec-summary-item exec-s-running">${running} Running</span>`;
	if (skipped) html += `<span class="exec-summary-item exec-s-skipped">${skipped} Skipped</span>`;
	if (pending) html += `<span class="exec-summary-item exec-s-pending">${pending} Pending</span>`;
	if (frm.doc.duration) html += `<span class="exec-summary-item" style="margin-left:auto"><strong>${_fmt_dur(frm.doc.duration)}</strong> total</span>`;
	html += `</div>`;

	// ── Step cards (vertical timeline) ──
	html += `<div class="exec-timeline">`;
	for (let i = 0; i < steps.length; i++) {
		const s = steps[i];
		const st = s.status || "Pending";
		const icon = _status_icon(st);
		const dur = s.duration ? _fmt_dur(s.duration) : "";
		const hasOutput = !!(s.output_data && s.output_data.trim());
		const hasError = !!(s.error && s.error.trim());
		const nodeType = s.node_type || "";

		html += `<div class="exec-step exec-step--${st.toLowerCase()}" data-idx="${i}">`;
		html += `  <div class="exec-step-line">`;
		html += `    <div class="exec-step-dot">${icon}</div>`;
		if (i < steps.length - 1) html += `<div class="exec-step-connector"></div>`;
		html += `  </div>`;
		html += `  <div class="exec-step-body">`;
		html += `    <div class="exec-step-header">`;
		html += `      <span class="exec-step-name">${frappe.utils.escape_html(s.node_name || s.node_id)}</span>`;
		if (nodeType) html += `<span class="exec-step-type">${frappe.utils.escape_html(nodeType)}</span>`;
		html += `      <span class="exec-step-badge exec-badge--${st.toLowerCase()}">${st}</span>`;
		if (dur) html += `<span class="exec-step-dur">${dur}</span>`;
		if (hasOutput || hasError) html += `<span class="exec-step-toggle" data-idx="${i}">▶ Details</span>`;
		html += `    </div>`; // header

		// Expandable detail panel
		if (hasOutput || hasError) {
			html += `<div class="exec-step-detail" id="exec-detail-${i}" style="display:none">`;
			if (hasOutput) {
				html += `<div class="exec-detail-section">`;
				html += `  <div class="exec-detail-label">Output</div>`;
				html += `  <pre class="exec-detail-code">${frappe.utils.escape_html(_pretty_json(s.output_data))}</pre>`;
				html += `</div>`;
			}
			if (hasError) {
				html += `<div class="exec-detail-section exec-detail-error">`;
				html += `  <div class="exec-detail-label">Error</div>`;
				html += `  <pre class="exec-detail-code">${frappe.utils.escape_html(s.error)}</pre>`;
				html += `</div>`;
			}
			html += `</div>`; // detail
		}

		html += `  </div>`; // body
		html += `</div>`; // step
	}
	html += `</div>`; // timeline
	html += `</div>`; // exec-flow

	wrapper.html(html);

	// Toggle detail panels
	wrapper.find(".exec-step-toggle").on("click", function () {
		const idx = $(this).data("idx");
		const panel = wrapper.find(`#exec-detail-${idx}`);
		const isVisible = panel.is(":visible");
		panel.slideToggle(200);
		$(this).text(isVisible ? "▶ Details" : "▼ Details");
	});

	// Click entire step header to toggle too
	wrapper.find(".exec-step-header").on("click", function (e) {
		if ($(e.target).hasClass("exec-step-toggle")) return;
		const idx = $(this).closest(".exec-step").data("idx");
		const toggle = wrapper.find(`.exec-step-toggle[data-idx="${idx}"]`);
		if (toggle.length) toggle.trigger("click");
	});
}

/* ─── Helpers ──────────────────────────────────────────── */
function _status_icon(st) {
	const map = {
		Completed: '<svg width="16" height="16" viewBox="0 0 16 16"><circle cx="8" cy="8" r="7" fill="#27ae60"/><path d="M5 8l2 2 4-4" stroke="#fff" stroke-width="1.5" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>',
		Failed: '<svg width="16" height="16" viewBox="0 0 16 16"><circle cx="8" cy="8" r="7" fill="#e74c3c"/><path d="M5.5 5.5l5 5M10.5 5.5l-5 5" stroke="#fff" stroke-width="1.5" stroke-linecap="round"/></svg>',
		Running: '<svg width="16" height="16" viewBox="0 0 16 16"><circle cx="8" cy="8" r="7" fill="#3498db"/><circle cx="8" cy="8" r="3" fill="none" stroke="#fff" stroke-width="1.5" stroke-dasharray="4 3"><animateTransform attributeName="transform" type="rotate" values="0 8 8;360 8 8" dur="1s" repeatCount="indefinite"/></circle></svg>',
		Pending: '<svg width="16" height="16" viewBox="0 0 16 16"><circle cx="8" cy="8" r="7" fill="#bdc3c7"/><circle cx="8" cy="8" r="2" fill="#fff"/></svg>',
		Skipped: '<svg width="16" height="16" viewBox="0 0 16 16"><circle cx="8" cy="8" r="7" fill="#95a5a6"/><path d="M6 5l5 3-5 3z" fill="#fff"/></svg>',
	};
	return map[st] || map.Pending;
}

function _fmt_dur(secs) {
	if (secs == null) return "";
	const n = parseFloat(secs);
	if (n < 0.001) return "<1ms";
	if (n < 1) return Math.round(n * 1000) + "ms";
	if (n < 60) return n.toFixed(2) + "s";
	const m = Math.floor(n / 60);
	const s = (n % 60).toFixed(1);
	return m + "m " + s + "s";
}

function _pretty_json(raw) {
	if (!raw) return "";
	try {
		const obj = JSON.parse(raw);
		return JSON.stringify(obj, null, 2);
	} catch {
		return raw;
	}
}
