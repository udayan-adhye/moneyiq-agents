"""
Workflow Dashboard
==================
Clean, mobile-friendly interface for daily action items and follow-up queue.
Served at /workflow from server.py.
"""

WORKFLOW_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>MoneyIQ Workflow</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { background: #f1f5f9; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; color: #1e293b; -webkit-font-smoothing: antialiased; }

        /* Header */
        .header { background: white; border-bottom: 1px solid #e2e8f0; position: sticky; top: 0; z-index: 20; }
        .header-inner { max-width: 720px; margin: 0 auto; padding: 12px 16px; }
        .header-top { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
        .header-top h1 { font-size: 17px; font-weight: 700; }
        .header-right { display: flex; align-items: center; gap: 10px; }
        .logout { font-size: 12px; color: #94a3b8; text-decoration: none; }
        .logout:hover { color: #ef4444; }

        /* Tabs */
        .tabs { display: flex; gap: 0; border-bottom: none; }
        .tab { flex: 1; text-align: center; padding: 8px 0; font-size: 13px; font-weight: 600; color: #94a3b8; cursor: pointer; border-bottom: 2px solid transparent; transition: all 0.2s; background: none; border-top: none; border-left: none; border-right: none; }
        .tab.active { color: #2563eb; border-bottom-color: #2563eb; }
        .tab-badge { font-size: 11px; background: #e2e8f0; color: #64748b; padding: 1px 7px; border-radius: 10px; margin-left: 4px; }
        .tab.active .tab-badge { background: #dbeafe; color: #2563eb; }

        /* Content */
        .content { max-width: 720px; margin: 0 auto; padding: 12px 16px 80px; }
        .panel { display: none; }
        .panel.active { display: block; }

        /* View toggle */
        .view-toggle { display: flex; gap: 4px; background: #e2e8f0; border-radius: 8px; padding: 3px; margin-bottom: 14px; }
        .view-btn { flex: 1; text-align: center; padding: 6px 0; font-size: 12px; font-weight: 500; color: #64748b; border: none; background: none; border-radius: 6px; cursor: pointer; }
        .view-btn.active { background: white; color: #1e293b; box-shadow: 0 1px 2px rgba(0,0,0,0.06); }

        /* Section */
        .section { margin-bottom: 18px; }
        .section-header { font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; color: #94a3b8; padding: 0 2px 6px; display: flex; align-items: center; gap: 6px; }
        .section-count { background: #e2e8f0; color: #64748b; font-size: 10px; padding: 1px 6px; border-radius: 8px; }
        .section-header.overdue { color: #dc2626; }
        .section-header.overdue .section-count { background: #fee2e2; color: #dc2626; }
        .section-header.today { color: #d97706; }
        .section-header.today .section-count { background: #fef3c7; color: #d97706; }

        /* Task card */
        .task { background: white; border-radius: 10px; padding: 12px; margin-bottom: 6px; display: flex; align-items: flex-start; gap: 10px; box-shadow: 0 1px 2px rgba(0,0,0,0.04); transition: opacity 0.3s, transform 0.3s; }
        .task.completing { opacity: 0.3; transform: scale(0.98); }
        .task-check { width: 20px; height: 20px; border: 2px solid #cbd5e1; border-radius: 6px; cursor: pointer; flex-shrink: 0; display: flex; align-items: center; justify-content: center; transition: all 0.2s; margin-top: 1px; }
        .task-check:hover { border-color: #22c55e; background: #f0fdf4; }
        .task-check svg { display: none; width: 12px; height: 12px; }
        .task-check:hover svg { display: block; color: #22c55e; }
        .task-body { flex: 1; min-width: 0; }
        .task-text { font-size: 13px; line-height: 1.4; color: #334155; }
        .task-meta { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin-top: 5px; }
        .pill { font-size: 10px; padding: 2px 7px; border-radius: 6px; font-weight: 600; white-space: nowrap; }
        .pill-client { background: #f1f5f9; color: #475569; }
        .pill-overdue { background: #fee2e2; color: #dc2626; }
        .pill-today { background: #fef3c7; color: #d97706; }
        .pill-upcoming { background: #f1f5f9; color: #94a3b8; }
        .pill-high { background: #fee2e2; color: #dc2626; }
        .pill-medium { background: #fef3c7; color: #d97706; }
        .pill-advisor { background: #ede9fe; color: #7c3aed; }
        .priority-dot { width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; }
        .priority-dot.high { background: #ef4444; }
        .priority-dot.medium { background: #f59e0b; }

        /* Follow-up client group */
        .fu-group { background: white; border-radius: 12px; margin-bottom: 12px; box-shadow: 0 1px 2px rgba(0,0,0,0.04); overflow: hidden; }
        .fu-group-header { padding: 12px 14px 8px; border-bottom: 1px solid #f1f5f9; }
        .fu-client-name { font-size: 14px; font-weight: 700; color: #1e293b; }
        .fu-client-info { font-size: 11px; color: #94a3b8; margin-top: 2px; }

        /* Follow-up item */
        .fu-item { padding: 12px 14px; border-bottom: 1px solid #f8fafc; }
        .fu-item:last-child { border-bottom: none; }
        .fu-item.future { opacity: 0.45; }
        .fu-item.sent { opacity: 0.35; }
        .fu-item-top { display: flex; align-items: center; justify-content: space-between; margin-bottom: 6px; }
        .fu-label { font-size: 12px; font-weight: 600; color: #475569; }
        .fu-badges { display: flex; gap: 4px; }
        .pill-wa { background: #dcfce7; color: #16a34a; }
        .pill-email { background: #dbeafe; color: #2563eb; }
        .pill-sent { background: #f1f5f9; color: #94a3b8; text-decoration: line-through; }
        .fu-msg { width: 100%; border: 1px solid #e2e8f0; border-radius: 8px; padding: 8px 10px; font-size: 12px; color: #334155; font-family: inherit; resize: vertical; line-height: 1.5; min-height: 60px; }
        .fu-msg:focus { outline: none; border-color: #93c5fd; }
        .fu-actions { display: flex; gap: 6px; margin-top: 8px; flex-wrap: wrap; }

        /* Buttons */
        .btn { font-size: 12px; font-weight: 600; padding: 6px 12px; border-radius: 8px; border: none; cursor: pointer; display: inline-flex; align-items: center; gap: 4px; transition: all 0.15s; text-decoration: none; }
        .btn-wa { background: #25D366; color: white; }
        .btn-wa:hover { background: #1da851; }
        .btn-email { background: #2563eb; color: white; }
        .btn-email:hover { background: #1d4ed8; }
        .btn-done { background: #10b981; color: white; }
        .btn-done:hover { background: #059669; }
        .btn-skip { background: #f1f5f9; color: #64748b; }
        .btn-skip:hover { background: #e2e8f0; }
        .btn-snooze { background: #f1f5f9; color: #64748b; }
        .btn-snooze:hover { background: #e2e8f0; }

        /* Empty state */
        .empty { text-align: center; padding: 48px 16px; color: #94a3b8; }
        .empty-icon { font-size: 36px; margin-bottom: 8px; }
        .empty-text { font-size: 14px; }

        /* Refresh */
        .refresh-btn { background: none; border: 1px solid #e2e8f0; border-radius: 8px; padding: 6px 10px; font-size: 12px; color: #94a3b8; cursor: pointer; }
        .refresh-btn:hover { background: #f8fafc; color: #64748b; }

        /* Advisor filter */
        .advisor-select { font-size: 12px; border: 1px solid #e2e8f0; border-radius: 8px; padding: 5px 8px; background: white; color: #475569; }

        .loading-overlay { pointer-events: none; opacity: 0.5; }

        @media (max-width: 480px) {
            .fu-actions { flex-direction: column; }
            .btn { justify-content: center; }
        }
    </style>
</head>
<body>
    <div class="header">
        <div class="header-inner">
            <div class="header-top">
                <h1>MoneyIQ</h1>
                <div class="header-right">
                    <select id="advisorFilter" onchange="loadAll()" class="advisor-select">
                        <option value="">All</option>
                        <option value="Udayan Adhye">Udayan</option>
                        <option value="Rishabh Mishra">Rishabh</option>
                    </select>
                    <button onclick="loadAll()" class="refresh-btn">Refresh</button>
                    <a href="/workflow/logout" class="logout">Logout</a>
                </div>
            </div>
            <div class="tabs">
                <button class="tab active" onclick="switchTab('tasks')" id="tab-tasks">
                    Action Items<span class="tab-badge" id="tasks-count">0</span>
                </button>
                <button class="tab" onclick="switchTab('followups')" id="tab-followups">
                    Follow-ups<span class="tab-badge" id="followups-count">0</span>
                </button>
            </div>
        </div>
    </div>

    <div class="content">
        <!-- Tasks Panel -->
        <div class="panel active" id="panel-tasks">
            <div class="view-toggle">
                <button class="view-btn active" onclick="setView('date')" id="view-date">By Date</button>
                <button class="view-btn" onclick="setView('client')" id="view-client">By Client</button>
            </div>
            <div id="tasks-container"></div>
        </div>

        <!-- Follow-ups Panel -->
        <div class="panel" id="panel-followups">
            <div id="followups-container"></div>
        </div>
    </div>

    <script>
    let currentTab = 'tasks';
    let taskView = 'date';
    let tasksData = [];
    let followupsData = [];

    // Role-based filtering (CURRENT_USER injected by server)
    const isAdmin = typeof CURRENT_USER !== 'undefined' && CURRENT_USER.role === 'admin';
    if (typeof CURRENT_USER !== 'undefined' && !isAdmin) {
        const sel = document.getElementById('advisorFilter');
        sel.value = CURRENT_USER.role;
        sel.disabled = true;
        sel.style.opacity = '0.5';
    }

    function getAdvisor() {
        if (typeof CURRENT_USER !== 'undefined' && !isAdmin) return CURRENT_USER.role;
        return document.getElementById('advisorFilter').value;
    }

    function switchTab(tab) {
        currentTab = tab;
        document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
        document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
        document.getElementById('panel-' + tab).classList.add('active');
        document.getElementById('tab-' + tab).classList.add('active');
    }

    function setView(v) {
        taskView = v;
        document.getElementById('view-date').classList.toggle('active', v === 'date');
        document.getElementById('view-client').classList.toggle('active', v === 'client');
        renderTasks();
    }

    function relDate(d) {
        if (!d) return '';
        const dt = new Date(d + 'T00:00:00');
        const today = new Date(); today.setHours(0,0,0,0);
        const diff = Math.round((dt - today) / 86400000);
        if (diff === 0) return 'Today';
        if (diff === -1) return 'Yesterday';
        if (diff === 1) return 'Tomorrow';
        if (diff < -1) return Math.abs(diff) + 'd overdue';
        return 'In ' + diff + 'd';
    }

    function datePill(d) {
        if (!d) return '';
        const dt = new Date(d + 'T00:00:00');
        const today = new Date(); today.setHours(0,0,0,0);
        const diff = Math.round((dt - today) / 86400000);
        if (diff < 0) return '<span class="pill pill-overdue">' + Math.abs(diff) + 'd overdue</span>';
        if (diff === 0) return '<span class="pill pill-today">Today</span>';
        return '<span class="pill pill-upcoming">' + relDate(d) + '</span>';
    }

    function esc(s) { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }

    // ── Tasks ──
    async function loadTasks() {
        const a = getAdvisor();
        const url = a ? '/api/workflow/tasks?advisor=' + encodeURIComponent(a) : '/api/workflow/tasks';
        const r = await fetch(url);
        tasksData = await r.json();
        document.getElementById('tasks-count').textContent = tasksData.length;
        renderTasks();
    }

    function renderTasks() {
        const c = document.getElementById('tasks-container');
        if (!tasksData.length) {
            c.innerHTML = '<div class="empty"><div class="empty-icon">&#10003;</div><div class="empty-text">All caught up!</div></div>';
            return;
        }
        if (taskView === 'date') renderTasksByDate(c);
        else renderTasksByClient(c);
    }

    function renderTasksByDate(c) {
        const today = new Date(); today.setHours(0,0,0,0);
        const groups = { overdue: [], today: [], tomorrow: [], week: [], later: [] };

        tasksData.forEach(t => {
            if (!t.due_date) { groups.later.push(t); return; }
            const dt = new Date(t.due_date + 'T00:00:00');
            const diff = Math.round((dt - today) / 86400000);
            if (diff < 0) groups.overdue.push(t);
            else if (diff === 0) groups.today.push(t);
            else if (diff === 1) groups.tomorrow.push(t);
            else if (diff <= 7) groups.week.push(t);
            else groups.later.push(t);
        });

        let html = '';
        const sections = [
            ['overdue', 'Overdue', 'overdue'],
            ['today', 'Due Today', 'today'],
            ['tomorrow', 'Tomorrow', ''],
            ['week', 'This Week', ''],
            ['later', 'Later', '']
        ];

        sections.forEach(([key, label, cls]) => {
            if (!groups[key].length) return;
            html += '<div class="section">'
                + '<div class="section-header ' + cls + '">' + label
                + '<span class="section-count">' + groups[key].length + '</span></div>';
            groups[key].forEach(t => { html += taskCard(t, true); });
            html += '</div>';
        });
        c.innerHTML = html;
    }

    function renderTasksByClient(c) {
        const grouped = {};
        tasksData.forEach(t => {
            const k = t.contact_name || 'General';
            if (!grouped[k]) grouped[k] = [];
            grouped[k].push(t);
        });

        let html = '';
        Object.keys(grouped).sort().forEach(client => {
            const items = grouped[client];
            html += '<div class="section">'
                + '<div class="section-header">' + esc(client)
                + '<span class="section-count">' + items.length + '</span></div>';
            items.sort((a, b) => (a.due_date || 'z').localeCompare(b.due_date || 'z'));
            items.forEach(t => { html += taskCard(t, false); });
            html += '</div>';
        });
        c.innerHTML = html;
    }

    function taskCard(t, showClient) {
        const pDot = t.priority === 'High' ? '<div class="priority-dot high"></div>'
            : t.priority === 'Medium' ? '<div class="priority-dot medium"></div>' : '';
        return '<div class="task" id="task-' + t.id + '">'
            + '<div class="task-check" onclick="completeTask(\\'' + t.id + '\\')">'
            + '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><path d="M5 13l4 4L19 7"/></svg></div>'
            + '<div class="task-body">'
            + '<div class="task-text">' + esc(t.task) + '</div>'
            + '<div class="task-meta">' + pDot
            + (showClient && t.contact_name ? '<span class="pill pill-client">' + esc(t.contact_name) + '</span>' : '')
            + datePill(t.due_date)
            + (t.assigned_to ? '<span class="pill pill-advisor">' + esc(t.assigned_to.split(' ')[0]) + '</span>' : '')
            + '</div></div></div>';
    }

    async function completeTask(id) {
        const el = document.getElementById('task-' + id);
        if (el) el.classList.add('completing');
        await fetch('/api/workflow/tasks/' + id + '/complete', { method: 'POST' });
        setTimeout(() => { tasksData = tasksData.filter(t => t.id !== id); document.getElementById('tasks-count').textContent = tasksData.length; renderTasks(); }, 400);
    }

    // ── Follow-ups ──
    async function loadFollowups() {
        const a = getAdvisor();
        const url = a ? '/api/workflow/followups?advisor=' + encodeURIComponent(a) : '/api/workflow/followups';
        const r = await fetch(url);
        followupsData = await r.json();
        document.getElementById('followups-count').textContent = followupsData.length;
        renderFollowups();
    }

    function renderFollowups() {
        const c = document.getElementById('followups-container');
        if (!followupsData.length) {
            c.innerHTML = '<div class="empty"><div class="empty-icon">&#9993;</div><div class="empty-text">No follow-ups pending</div></div>';
            return;
        }

        // Group by client
        const grouped = {};
        followupsData.forEach(f => {
            const k = f.client_name || 'Unknown';
            if (!grouped[k]) grouped[k] = { items: [], email: f.client_email, advisor: f.advisor };
            grouped[k].items.push(f);
        });

        let html = '';
        Object.keys(grouped).sort().forEach(client => {
            const g = grouped[client];
            // Sort by sequence number
            g.items.sort((a, b) => (a.sequence_num || 0) - (b.sequence_num || 0));

            // Find the first due item (lowest sequence that's not sent)
            let firstDueIdx = 0;

            html += '<div class="fu-group">'
                + '<div class="fu-group-header">'
                + '<div class="fu-client-name">' + esc(client) + '</div>'
                + '<div class="fu-client-info">' + esc(g.advisor || '') + (g.email ? ' &middot; ' + esc(g.email) : '') + '</div>'
                + '</div>';

            g.items.forEach((f, i) => {
                const isWA = f.channel === 'WhatsApp';
                const isFuture = i > firstDueIdx;
                const channelPill = isWA
                    ? '<span class="pill pill-wa">WhatsApp</span>'
                    : '<span class="pill pill-email">Email</span>';
                const msgEscaped = (f.message || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');

                html += '<div class="fu-item' + (isFuture ? ' future' : '') + '" id="fu-' + f.id + '">'
                    + '<div class="fu-item-top">'
                    + '<div class="fu-label">' + esc(f.touchpoint || '') + '</div>'
                    + '<div class="fu-badges">' + channelPill + datePill(f.scheduled_date) + '</div>'
                    + '</div>'
                    + '<textarea class="fu-msg" id="msg-' + f.id + '">' + msgEscaped + '</textarea>'
                    + '<div class="fu-actions">';

                if (isWA && f.whatsapp_link) {
                    html += '<a href="' + f.whatsapp_link + '" target="_blank" class="btn btn-wa">'
                        + '<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347z"/><path d="M12 0C5.373 0 0 5.373 0 12c0 2.625.846 5.059 2.284 7.034L.789 23.492l4.627-1.475A11.932 11.932 0 0012 24c6.627 0 12-5.373 12-12S18.627 0 12 0zm0 21.818c-2.168 0-4.19-.581-5.938-1.593l-.424-.252-2.748.877.877-2.687-.276-.44A9.787 9.787 0 012.182 12c0-5.414 4.404-9.818 9.818-9.818S21.818 6.586 21.818 12s-4.404 9.818-9.818 9.818z"/></svg>'
                        + 'Send on WhatsApp</a>';
                }
                if (!isWA && f.client_email) {
                    html += '<button onclick="sendEmail(\\'' + f.id + '\\')" class="btn btn-email">Send Email</button>';
                }
                if (isWA) {
                    html += '<button onclick="markSent(\\'' + f.id + '\\')" class="btn btn-done">Mark Sent</button>';
                }
                html += '<button onclick="skipFU(\\'' + f.id + '\\')" class="btn btn-skip">Skip</button>';
                html += '<button onclick="snoozeFU(\\'' + f.id + '\\')" class="btn btn-snooze">Snooze 2d</button>';
                html += '</div></div>';
            });
            html += '</div>';
        });
        c.innerHTML = html;
    }

    async function sendEmail(id) {
        const el = document.getElementById('fu-' + id);
        if (el) el.classList.add('loading-overlay');
        const msg = document.getElementById('msg-' + id).value;
        await fetch('/api/workflow/followups/' + id + '/send', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ message: msg })
        });
        followupsData = followupsData.filter(f => f.id !== id);
        document.getElementById('followups-count').textContent = followupsData.length;
        renderFollowups();
    }

    async function markSent(id) {
        const el = document.getElementById('fu-' + id);
        if (el) el.classList.add('loading-overlay');
        await fetch('/api/workflow/followups/' + id + '/send', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({})
        });
        followupsData = followupsData.filter(f => f.id !== id);
        document.getElementById('followups-count').textContent = followupsData.length;
        renderFollowups();
    }

    async function skipFU(id) {
        const el = document.getElementById('fu-' + id);
        if (el) el.classList.add('loading-overlay');
        await fetch('/api/workflow/followups/' + id + '/skip', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ reason: 'Skipped from dashboard' })
        });
        followupsData = followupsData.filter(f => f.id !== id);
        document.getElementById('followups-count').textContent = followupsData.length;
        renderFollowups();
    }

    async function snoozeFU(id) {
        const el = document.getElementById('fu-' + id);
        if (el) el.classList.add('loading-overlay');
        await fetch('/api/workflow/followups/' + id + '/snooze', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ days: 2 })
        });
        followupsData = followupsData.filter(f => f.id !== id);
        document.getElementById('followups-count').textContent = followupsData.length;
        renderFollowups();
    }

    // ── Init ──
    function loadAll() { loadTasks(); loadFollowups(); }
    loadAll();
    setInterval(loadAll, 60000);
    </script>
</body>
</html>"""
