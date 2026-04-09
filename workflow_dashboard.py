"""
Workflow Dashboard
==================
Clean, mobile-friendly interface for daily action items and follow-up queue.
Served as a Flask blueprint at /workflow.
"""

WORKFLOW_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>MoneyIQ Workflow</title>
    <link href="https://cdn.jsdelivr.net/npm/tailwindcss@2.2.19/dist/tailwind.min.css" rel="stylesheet">
    <style>
        body { background: #f8fafc; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; }
        .tab-active { border-bottom: 3px solid #2563eb; color: #2563eb; font-weight: 600; }
        .tab-inactive { color: #64748b; }
        .card { background: white; border-radius: 12px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }
        .overdue { border-left: 4px solid #ef4444; }
        .due-today { border-left: 4px solid #f59e0b; }
        .upcoming { border-left: 4px solid #94a3b8; }
        .whatsapp-btn { background: #25D366; }
        .whatsapp-btn:hover { background: #1da851; }
        .email-btn { background: #2563eb; }
        .email-btn:hover { background: #1d4ed8; }
        .skip-btn { background: #94a3b8; }
        .skip-btn:hover { background: #64748b; }
        .done-btn { background: #10b981; }
        .done-btn:hover { background: #059669; }
        .badge { font-size: 11px; padding: 2px 8px; border-radius: 9999px; font-weight: 600; }
        .badge-overdue { background: #fee2e2; color: #dc2626; }
        .badge-today { background: #fef3c7; color: #d97706; }
        .badge-upcoming { background: #f1f5f9; color: #475569; }
        .badge-whatsapp { background: #dcfce7; color: #16a34a; }
        .badge-email { background: #dbeafe; color: #2563eb; }
        .msg-preview { max-height: 80px; overflow: hidden; transition: max-height 0.3s; }
        .msg-preview.expanded { max-height: 600px; }
        textarea { resize: vertical; }
        .loading { opacity: 0.5; pointer-events: none; }
    </style>
</head>
<body class="min-h-screen">
    <!-- Header -->
    <div class="bg-white border-b sticky top-0 z-10">
        <div class="max-w-3xl mx-auto px-4 py-3">
            <div class="flex items-center justify-between mb-3">
                <h1 class="text-lg font-bold text-gray-900">MoneyIQ Workflow</h1>
                <div class="flex items-center gap-3">
                    <select id="advisorFilter" onchange="loadAll()" class="text-sm border rounded-lg px-3 py-1.5 bg-white">
                        <option value="">All Advisors</option>
                        <option value="Udayan Adhye">Udayan</option>
                        <option value="Rishabh Mishra">Rishabh</option>
                    </select>
                    <a href="/workflow/logout" class="text-xs text-gray-400 hover:text-red-500">Logout</a>
                </div>
            </div>
            <!-- Tabs -->
            <div class="flex gap-6">
                <button onclick="switchTab('tasks')" id="tab-tasks" class="pb-2 text-sm tab-active">
                    Action Items <span id="tasks-count" class="ml-1 text-xs bg-blue-100 text-blue-700 px-1.5 py-0.5 rounded-full">0</span>
                </button>
                <button onclick="switchTab('followups')" id="tab-followups" class="pb-2 text-sm tab-inactive">
                    Follow-ups <span id="followups-count" class="ml-1 text-xs bg-green-100 text-green-700 px-1.5 py-0.5 rounded-full">0</span>
                </button>
            </div>
        </div>
    </div>

    <!-- Tasks Tab -->
    <div id="panel-tasks" class="max-w-3xl mx-auto px-4 py-4">
        <div id="tasks-list"></div>
        <div id="tasks-empty" class="hidden text-center py-12 text-gray-400">
            <div class="text-4xl mb-2">&#10003;</div>
            <p>All caught up! No pending action items.</p>
        </div>
    </div>

    <!-- Follow-ups Tab -->
    <div id="panel-followups" class="max-w-3xl mx-auto px-4 py-4 hidden">
        <div id="followups-list"></div>
        <div id="followups-empty" class="hidden text-center py-12 text-gray-400">
            <div class="text-4xl mb-2">&#9993;</div>
            <p>No follow-ups due right now.</p>
        </div>
    </div>

    <script>
    let currentTab = 'tasks';

    function switchTab(tab) {
        currentTab = tab;
        document.getElementById('panel-tasks').classList.toggle('hidden', tab !== 'tasks');
        document.getElementById('panel-followups').classList.toggle('hidden', tab !== 'followups');
        document.getElementById('tab-tasks').className = 'pb-2 text-sm ' + (tab === 'tasks' ? 'tab-active' : 'tab-inactive');
        document.getElementById('tab-followups').className = 'pb-2 text-sm ' + (tab === 'followups' ? 'tab-active' : 'tab-inactive');
    }

    // Role-based filtering: non-admin users can only see their own data
    // CURRENT_USER is injected by the server (e.g. {username: "rishabh", role: "Rishabh Mishra"})
    const isAdmin = typeof CURRENT_USER !== 'undefined' && CURRENT_USER.role === 'admin';
    if (typeof CURRENT_USER !== 'undefined' && !isAdmin) {
        // Lock filter to their advisor name
        const sel = document.getElementById('advisorFilter');
        sel.value = CURRENT_USER.role;
        sel.disabled = true;
        sel.style.opacity = '0.6';
    }

    function getAdvisor() {
        if (typeof CURRENT_USER !== 'undefined' && !isAdmin) return CURRENT_USER.role;
        return document.getElementById('advisorFilter').value;
    }

    function formatDate(d) {
        if (!d) return '';
        const dt = new Date(d + 'T00:00:00');
        const today = new Date(); today.setHours(0,0,0,0);
        const diff = Math.round((dt - today) / 86400000);
        if (diff === 0) return 'Today';
        if (diff === -1) return 'Yesterday';
        if (diff === 1) return 'Tomorrow';
        if (diff < 0) return Math.abs(diff) + ' days ago';
        return 'In ' + diff + ' days';
    }

    // ── Tasks ──
    async function loadTasks() {
        const advisor = getAdvisor();
        const url = advisor ? '/api/workflow/tasks?advisor=' + encodeURIComponent(advisor) : '/api/workflow/tasks';
        const resp = await fetch(url);
        const tasks = await resp.json();

        document.getElementById('tasks-count').textContent = tasks.length;
        const list = document.getElementById('tasks-list');
        const empty = document.getElementById('tasks-empty');

        if (!tasks.length) { list.innerHTML = ''; empty.classList.remove('hidden'); return; }
        empty.classList.add('hidden');

        // Group by contact
        const grouped = {};
        tasks.forEach(t => {
            const key = t.contact_name || 'General';
            if (!grouped[key]) grouped[key] = [];
            grouped[key].push(t);
        });

        let html = '';
        for (const [contact, items] of Object.entries(grouped)) {
            html += '<div class="mb-4"><div class="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2 px-1">' + contact + '</div>';
            items.forEach(t => {
                const cls = t.overdue ? 'overdue' : t.due_today ? 'due-today' : 'upcoming';
                const badge = t.overdue ? '<span class="badge badge-overdue">Overdue</span>'
                    : t.due_today ? '<span class="badge badge-today">Today</span>'
                    : '<span class="badge badge-upcoming">' + formatDate(t.due_date) + '</span>';
                const priorityColor = t.priority === 'High' ? 'text-red-500' : t.priority === 'Medium' ? 'text-yellow-600' : 'text-gray-400';

                html += '<div class="card ' + cls + ' p-3 mb-2 flex items-start gap-3" id="task-' + t.id + '">'
                    + '<button onclick="completeTask(\\'' + t.id + '\\')" class="mt-0.5 w-5 h-5 rounded border-2 border-gray-300 hover:border-green-500 hover:bg-green-50 flex-shrink-0 flex items-center justify-center text-xs text-transparent hover:text-green-500">&#10003;</button>'
                    + '<div class="flex-1 min-w-0">'
                    + '<div class="text-sm text-gray-900">' + t.task + '</div>'
                    + '<div class="flex items-center gap-2 mt-1">'
                    + badge
                    + '<span class="text-xs text-gray-400">' + (t.assigned_to || '') + '</span>'
                    + '<span class="text-xs ' + priorityColor + '">' + (t.priority || '') + '</span>'
                    + '</div></div></div>';
            });
            html += '</div>';
        }
        list.innerHTML = html;
    }

    async function completeTask(id) {
        const el = document.getElementById('task-' + id);
        if (el) el.classList.add('loading');
        await fetch('/api/workflow/tasks/' + id + '/complete', { method: 'POST' });
        if (el) el.style.opacity = '0.3';
        setTimeout(() => loadTasks(), 500);
    }

    // ── Follow-ups ──
    async function loadFollowups() {
        const advisor = getAdvisor();
        const url = advisor ? '/api/workflow/followups?advisor=' + encodeURIComponent(advisor) : '/api/workflow/followups';
        const resp = await fetch(url);
        const followups = await resp.json();

        document.getElementById('followups-count').textContent = followups.length;
        const list = document.getElementById('followups-list');
        const empty = document.getElementById('followups-empty');

        if (!followups.length) { list.innerHTML = ''; empty.classList.remove('hidden'); return; }
        empty.classList.add('hidden');

        let html = '';
        followups.forEach(f => {
            const isWA = f.channel === 'WhatsApp';
            const channelBadge = isWA
                ? '<span class="badge badge-whatsapp">WhatsApp</span>'
                : '<span class="badge badge-email">Email</span>';

            const dateBadge = '<span class="badge badge-upcoming">' + formatDate(f.scheduled_date) + '</span>';

            // Escape message for textarea
            const msgEscaped = (f.message || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');

            html += '<div class="card p-4 mb-3" id="fu-' + f.id + '">'
                + '<div class="flex items-center justify-between mb-2">'
                + '<div>'
                + '<span class="font-semibold text-gray-900 text-sm">' + (f.client_name || '') + '</span>'
                + '<span class="text-xs text-gray-400 ml-2">' + (f.touchpoint || '') + '</span>'
                + '</div>'
                + '<div class="flex gap-1.5">' + channelBadge + dateBadge + '</div>'
                + '</div>'

                // Message preview / edit
                + '<textarea id="msg-' + f.id + '" class="w-full text-sm text-gray-700 border rounded-lg p-2 mb-3" rows="3">' + msgEscaped + '</textarea>'

                // Action buttons
                + '<div class="flex gap-2">';

            if (isWA && f.whatsapp_link) {
                html += '<a href="' + f.whatsapp_link + '" target="_blank" class="whatsapp-btn text-white text-xs font-medium px-3 py-1.5 rounded-lg inline-flex items-center gap-1">'
                    + '<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347z"/><path d="M12 0C5.373 0 0 5.373 0 12c0 2.625.846 5.059 2.284 7.034L.789 23.492l4.627-1.475A11.932 11.932 0 0012 24c6.627 0 12-5.373 12-12S18.627 0 12 0zm0 21.818c-2.168 0-4.19-.581-5.938-1.593l-.424-.252-2.748.877.877-2.687-.276-.44A9.787 9.787 0 012.182 12c0-5.414 4.404-9.818 9.818-9.818S21.818 6.586 21.818 12s-4.404 9.818-9.818 9.818z"/></svg>'
                    + 'Send on WhatsApp</a>';
            }

            if (!isWA && f.client_email) {
                html += '<button onclick="sendEmail(\\'' + f.id + '\\')" class="email-btn text-white text-xs font-medium px-3 py-1.5 rounded-lg">Send Email</button>';
            }

            // For WhatsApp Day 0, also show "Mark as Sent" after they send manually
            if (isWA) {
                html += '<button onclick="markSent(\\'' + f.id + '\\')" class="done-btn text-white text-xs font-medium px-3 py-1.5 rounded-lg">Mark Sent</button>';
            }

            html += '<button onclick="skipFollowup(\\'' + f.id + '\\')" class="skip-btn text-white text-xs font-medium px-3 py-1.5 rounded-lg">Skip</button>'
                + '<button onclick="snoozeFollowup(\\'' + f.id + '\\')" class="text-xs text-gray-500 hover:text-gray-700 px-2 py-1.5 border rounded-lg">Snooze 2d</button>'
                + '</div></div>';
        });
        list.innerHTML = html;
    }

    async function sendEmail(id) {
        const msg = document.getElementById('msg-' + id).value;
        const el = document.getElementById('fu-' + id);
        if (el) el.classList.add('loading');
        await fetch('/api/workflow/followups/' + id + '/send', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ message: msg })
        });
        if (el) el.style.opacity = '0.3';
        setTimeout(() => loadFollowups(), 500);
    }

    async function markSent(id) {
        const el = document.getElementById('fu-' + id);
        if (el) el.classList.add('loading');
        await fetch('/api/workflow/followups/' + id + '/send', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({})
        });
        if (el) el.style.opacity = '0.3';
        setTimeout(() => loadFollowups(), 500);
    }

    async function skipFollowup(id) {
        const el = document.getElementById('fu-' + id);
        if (el) el.classList.add('loading');
        await fetch('/api/workflow/followups/' + id + '/skip', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ reason: 'Skipped from dashboard' })
        });
        if (el) el.style.opacity = '0.3';
        setTimeout(() => loadFollowups(), 500);
    }

    async function snoozeFollowup(id) {
        const el = document.getElementById('fu-' + id);
        if (el) el.classList.add('loading');
        await fetch('/api/workflow/followups/' + id + '/snooze', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ days: 2 })
        });
        if (el) el.style.opacity = '0.3';
        setTimeout(() => loadFollowups(), 500);
    }

    // ── Load all ──
    function loadAll() { loadTasks(); loadFollowups(); }
    loadAll();
    setInterval(loadAll, 60000); // refresh every minute
    </script>
</body>
</html>"""
