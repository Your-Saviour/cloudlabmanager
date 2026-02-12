const $ = (sel) => document.querySelector(sel);
const app = $("#app");

// --- API helpers ---

function getToken() { return localStorage.getItem("token"); }
function setToken(t) { localStorage.setItem("token", t); }
function clearToken() { localStorage.removeItem("token"); }

let currentUser = null;
let inventoryTypes = [];

const INVENTORY_ICONS = {
    server: "&#9635;",
    service: "&#11041;",
    credential: "&#128273;",
    user: "&#9679;",
    deployment: "&#9654;",
};

async function loadInventoryTypes() {
    if (inventoryTypes.length > 0) return inventoryTypes;
    const data = await apiJson("/api/inventory/types");
    if (data) inventoryTypes = data.types || [];
    return inventoryTypes;
}

function getTypeConfig(slug) {
    return inventoryTypes.find(t => t.slug === slug);
}

async function renderInventory(activeSubTab) {
    app.innerHTML = `<div class="loading">Loading inventory...</div>`;

    await loadInventoryTypes();

    // Determine the active sub-tab
    if (!activeSubTab) activeSubTab = inventoryTypes.length > 0 ? inventoryTypes[0].slug : "tags";

    // Fetch counts for each type
    const fetches = inventoryTypes.map(t =>
        hasPermission(`inventory.${t.slug}.view`)
            ? apiJson(`/api/inventory/${t.slug}?per_page=1`)
            : Promise.resolve(null)
    );
    const results = await Promise.all(fetches);
    const accentColors = ["accent-amber", "accent-blue", "accent-cyan", "accent-green"];
    const showTags = hasPermission("inventory.tags.manage");

    app.innerHTML = `
        <div class="page-header view-enter stagger-1">
            <h2>Inventory</h2>
        </div>

        <div class="stat-grid view-enter stagger-2">
            ${inventoryTypes.map((t, i) => {
                const typeData = results[i];
                const count = typeData ? (typeData.total || 0) : 0;
                return `<div class="stat-card ${accentColors[i % accentColors.length]}" style="cursor:pointer" data-subtab="${t.slug}">
                    <div class="stat-value">${count}</div>
                    <div class="stat-label">${t.label}s</div>
                </div>`;
            }).join("")}
        </div>

        <div class="inventory-subtabs view-enter stagger-3">
            ${inventoryTypes.map(t =>
                `<button class="inventory-subtab${activeSubTab === t.slug ? " active" : ""}" data-subtab="${t.slug}">${t.label}s</button>`
            ).join("")}
            ${showTags ? `<button class="inventory-subtab${activeSubTab === "tags" ? " active" : ""}" data-subtab="tags">Tags</button>` : ""}
        </div>

        <div id="inventory-subcontent" class="view-enter stagger-4"></div>
    `;

    // Render the active sub-tab content
    const subContent = document.getElementById("inventory-subcontent");
    if (activeSubTab === "tags") {
        await renderTagsInline(subContent);
    } else {
        await renderInventoryListInline(subContent, activeSubTab);
    }

    // Sub-tab click handlers
    document.querySelectorAll(".inventory-subtab").forEach(btn => {
        btn.addEventListener("click", () => {
            const tab = btn.dataset.subtab;
            navigate(tab === inventoryTypes[0]?.slug ? "inventory" : `inventory-${tab}`);
        });
    });

    // Stat card click handlers
    document.querySelectorAll(".stat-card[data-subtab]").forEach(card => {
        card.addEventListener("click", () => {
            const tab = card.dataset.subtab;
            navigate(tab === inventoryTypes[0]?.slug ? "inventory" : `inventory-${tab}`);
        });
    });
}

async function renderInventoryListInline(container, typeSlug) {
    container.innerHTML = `<div class="loading">Loading...</div>`;

    const typeConfig = getTypeConfig(typeSlug);
    if (!typeConfig) {
        container.innerHTML = `<div class="empty-state"><div>Unknown inventory type: ${escapeHtml(typeSlug)}</div></div>`;
        return;
    }

    const data = await apiJson(`/api/inventory/${typeSlug}`);
    if (!data) return;

    const objects = data.objects || [];
    const fields = typeConfig.fields || [];
    const actions = typeConfig.actions || [];
    const columnFields = fields.filter(f => f.type !== "secret" && f.type !== "json" && f.type !== "text").slice(0, 6);
    const canCreate = hasPermission(`inventory.${typeSlug}.create`);
    const typeLevelActions = actions.filter(a => a.scope === "type");
    const objectActions = actions.filter(a => a.scope !== "type");

    let scriptsMap = {};
    if (typeSlug === "service") {
        const svcData = await apiJson("/api/services");
        if (svcData && svcData.services) {
            svcData.services.forEach(s => { scriptsMap[s.name] = s.scripts || []; });
        }
    }

    container.innerHTML = `
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:1rem;">
            <div>
                <h3>${escapeHtml(typeConfig.label)}s</h3>
                <small>${objects.length} total</small>
            </div>
            <div style="display:flex;gap:0.5rem;align-items:center;">
                ${typeLevelActions.map(a =>
                    `<button class="btn btn-primary btn-sm type-action-btn" data-action="${escapeHtml(a.name)}">${escapeHtml(a.label)}</button>`
                ).join("")}
                ${canCreate ? `<button class="btn btn-primary btn-sm" id="create-object-btn">New ${escapeHtml(typeConfig.label)}</button>` : ""}
            </div>
        </div>

        ${objects.length === 0 ? `
            <div class="empty-state">
                <div class="empty-icon">&#9670;</div>
                <div>No ${typeConfig.label.toLowerCase()}s found.</div>
            </div>
        ` : typeSlug === "service" ? renderServiceList(objects, objectActions, scriptsMap) : `
            <table class="data-table">
                <thead>
                    <tr>
                        ${columnFields.map(f => `<th>${escapeHtml(f.name.replace(/_/g, " ").replace(/\b\w/g, l => l.toUpperCase()))}</th>`).join("")}
                        <th>Tags</th>
                        <th>Actions</th>
                    </tr>
                </thead>
                <tbody>
                    ${objects.map(obj => {
                        const d = obj.data || {};
                        const tags = obj.tags || [];
                        return `<tr>
                            ${columnFields.map(f => {
                                let val = d[f.name];
                                if (Array.isArray(val)) val = val.join(", ");
                                if (f.name === "power_status" && val) {
                                    return `<td>${val === "running"
                                        ? '<span class="badge badge-running">running</span>'
                                        : `<span class="badge badge-pending">${escapeHtml(String(val))}</span>`}</td>`;
                                }
                                if (f.name === "ip_address") return `<td style="font-family:var(--font-mono);font-size:0.8rem;">${escapeHtml(String(val || ""))}</td>`;
                                return `<td>${escapeHtml(String(val || ""))}</td>`;
                            }).join("")}
                            <td>${tags.map(t => `<span class="tag-pill" style="--tag-color:${t.color || '#4a5a70'}">${escapeHtml(t.name)}</span>`).join(" ")}</td>
                            <td class="instance-actions">
                                ${renderObjActions(typeSlug, obj, objectActions)}
                            </td>
                        </tr>`;
                    }).join("")}
                </tbody>
            </table>
        `}
    `;

    // Event handlers
    const createBtn = document.getElementById("create-object-btn");
    if (createBtn) createBtn.addEventListener("click", () => navigate(`inventory-${typeSlug}-new`));

    document.querySelectorAll(".type-action-btn").forEach(btn => {
        btn.addEventListener("click", async () => {
            const actionName = btn.dataset.action;
            const action = typeLevelActions.find(a => a.name === actionName);
            if (!action) return;
            const yes = await confirm(`Run ${action.label}?`, `This will execute ${action.label}.`);
            if (!yes) return;
            btn.setAttribute("aria-busy", "true");
            const res = await apiJson(`/api/inventory/${typeSlug}/actions/${actionName}`, { method: "POST" });
            if (res && res.job_id) navigate("job-" + res.job_id);
            else btn.removeAttribute("aria-busy");
        });
    });

    document.querySelectorAll(".ssh-btn").forEach(btn => {
        btn.addEventListener("click", () => openSSHTerminal(btn.dataset.hostname, btn.dataset.ip));
    });

    document.querySelectorAll(".obj-action-btn").forEach(btn => {
        btn.addEventListener("click", async () => {
            const objId = btn.dataset.id;
            const actionName = btn.dataset.action;
            const action = objectActions.find(a => a.name === actionName);
            if (!action) return;
            const yes = await confirm(`Run ${action.label}?`, "This action will be executed on the selected object.");
            if (!yes) return;
            btn.setAttribute("aria-busy", "true");
            const res = await apiJson(`/api/inventory/${typeSlug}/${objId}/actions/${actionName}`, { method: "POST" });
            if (res && res.job_id) navigate("job-" + res.job_id);
            else btn.removeAttribute("aria-busy");
        });
    });

    // Service-specific: run/stop/config/files buttons
    bindServiceActionHandlers(typeSlug, objects, scriptsMap);
}

async function renderTagsInline(container) {
    container.innerHTML = `<div class="loading">Loading tags...</div>`;
    const data = await apiJson("/api/inventory/tags");
    if (!data) return;

    const tags = data.tags || [];

    container.innerHTML = `
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:1rem;">
            <h3>Tags</h3>
            <button class="btn btn-primary btn-sm" id="create-tag-btn">New Tag</button>
        </div>
        ${tags.length === 0 ? `
            <div class="empty-state">
                <div class="empty-icon">&#9899;</div>
                <div>No tags created yet.</div>
            </div>
        ` : `
            <table class="data-table">
                <thead>
                    <tr>
                        <th>Tag</th>
                        <th>Color</th>
                        <th>Objects</th>
                        <th>Actions</th>
                    </tr>
                </thead>
                <tbody>
                    ${tags.map(t => `
                        <tr>
                            <td><span class="tag-pill" style="--tag-color:${t.color || '#4a5a70'}">${escapeHtml(t.name)}</span></td>
                            <td><input type="color" value="${t.color || '#4a5a70'}" class="tag-color-input" data-id="${t.id}" data-name="${escapeHtml(t.name)}"></td>
                            <td>${t.object_count || 0}</td>
                            <td class="instance-actions">
                                <button class="btn btn-danger btn-sm tag-delete-btn" data-id="${t.id}" data-name="${escapeHtml(t.name)}">Delete</button>
                            </td>
                        </tr>
                    `).join("")}
                </tbody>
            </table>
        `}
    `;

    document.getElementById("create-tag-btn").addEventListener("click", () => {
        const overlay = document.createElement("div");
        overlay.className = "confirm-overlay";
        overlay.innerHTML = `
            <div class="confirm-box input-modal">
                <h4>Create Tag</h4>
                <form id="tag-create-form">
                    <div class="form-group">
                        <label>Name *</label>
                        <input type="text" name="name" required placeholder="Tag name">
                    </div>
                    <div class="form-group">
                        <label>Color</label>
                        <input type="color" name="color" value="#4a5a70">
                    </div>
                    <p class="form-error" id="tag-create-error" style="display:none;"></p>
                    <div class="actions">
                        <button type="button" class="btn" id="tag-create-cancel">Cancel</button>
                        <button type="submit" class="btn btn-primary">Create</button>
                    </div>
                </form>
            </div>
        `;
        document.body.appendChild(overlay);
        overlay.querySelector("#tag-create-cancel").onclick = () => overlay.remove();
        overlay.querySelector("#tag-create-form").addEventListener("submit", async (e) => {
            e.preventDefault();
            const fd = new FormData(e.target);
            const res = await api("/api/inventory/tags", {
                method: "POST",
                body: JSON.stringify({ name: fd.get("name"), color: fd.get("color") }),
            });
            if (!res) return;
            if (res.ok) { overlay.remove(); renderTagsInline(container); }
            else {
                const err = await res.json();
                const errEl = overlay.querySelector("#tag-create-error");
                errEl.textContent = err.detail || "Failed";
                errEl.style.display = "block";
            }
        });
    });

    document.querySelectorAll(".tag-color-input").forEach(input => {
        input.addEventListener("change", async () => {
            await api(`/api/inventory/tags/${input.dataset.id}`, {
                method: "PUT",
                body: JSON.stringify({ name: input.dataset.name, color: input.value }),
            });
            renderTagsInline(container);
        });
    });

    document.querySelectorAll(".tag-delete-btn").forEach(btn => {
        btn.addEventListener("click", async () => {
            const yes = await confirm(`Delete tag "${btn.dataset.name}"?`, "Objects will keep their data but lose this tag.");
            if (!yes) return;
            await api(`/api/inventory/tags/${btn.dataset.id}`, { method: "DELETE" });
            renderTagsInline(container);
        });
    });
}

function setCurrentUser(user) {
    currentUser = user;
    localStorage.setItem("currentUser", JSON.stringify(user));
    updateNavUser();
    updateNavPermissions();
}

function loadCurrentUser() {
    try {
        const stored = localStorage.getItem("currentUser");
        if (stored) currentUser = JSON.parse(stored);
    } catch (e) { currentUser = null; }
}

function clearCurrentUser() {
    currentUser = null;
    localStorage.removeItem("currentUser");
}

function hasPermission(codename) {
    if (!currentUser || !currentUser.permissions) return false;
    // Wildcard admin check
    if (currentUser.permissions.includes("*")) return true;
    return currentUser.permissions.includes(codename);
}

async function api(path, opts = {}) {
    const headers = { "Content-Type": "application/json", ...(opts.headers || {}) };
    const token = getToken();
    if (token) headers["Authorization"] = `Bearer ${token}`;
    const res = await fetch(path, { ...opts, headers });
    if (res.status === 401) { clearToken(); clearCurrentUser(); navigate("login"); return null; }
    return res;
}

async function apiJson(path, opts = {}) {
    const res = await api(path, opts);
    if (!res) return null;
    return res.json();
}

// --- Routing ---

function navigate(view) { window.location.hash = view; }

function currentView() {
    return window.location.hash.replace("#", "") || "dashboard";
}

window.addEventListener("hashchange", render);

// --- Auth state ---

function updateNavVisibility() {
    const token = getToken();
    document.body.classList.toggle("no-auth", !token);
}

function updateNavUser() {
    const nameEl = $("#nav-user-name");
    if (nameEl && currentUser) {
        nameEl.textContent = currentUser.display_name || currentUser.username || "";
    } else if (nameEl) {
        nameEl.textContent = "";
    }
}

function updateNavPermissions() {
    document.querySelectorAll("[data-perm]").forEach(el => {
        const perm = el.getAttribute("data-perm");
        const allowed = hasPermission(perm);
        el.classList.toggle("perm-visible", allowed);
        // For elements without .nav-admin, fall back to inline display
        if (!el.classList.contains("nav-admin")) {
            el.style.display = allowed ? "" : "none";
        }
    });
}

// User dropdown toggle
const navUserBtn = $("#nav-user-btn");
const navUserDropdown = $("#nav-user-dropdown");
if (navUserBtn && navUserDropdown) {
    navUserBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        navUserDropdown.classList.toggle("open");
    });
    document.addEventListener("click", () => {
        navUserDropdown.classList.remove("open");
    });
}

$("#logout-link").addEventListener("click", (e) => {
    e.preventDefault();
    clearToken();
    clearCurrentUser();
    navigate("login");
});

// --- Confirmation dialog ---

function confirm(message, details) {
    return new Promise((resolve) => {
        const overlay = document.createElement("div");
        overlay.className = "confirm-overlay";
        overlay.innerHTML = `
            <div class="confirm-box">
                <h4>${message}</h4>
                ${details ? `<p>${details}</p>` : ""}
                <div class="actions">
                    <button class="btn" id="confirm-no">Cancel</button>
                    <button class="btn btn-primary" id="confirm-yes">Confirm</button>
                </div>
            </div>
        `;
        document.body.appendChild(overlay);
        overlay.querySelector("#confirm-yes").onclick = () => { overlay.remove(); resolve(true); };
        overlay.querySelector("#confirm-no").onclick = () => { overlay.remove(); resolve(false); };
    });
}

// --- Badge helper ---

function badge(status) {
    return `<span class="badge badge-${status}">${status}</span>`;
}

// --- Relative time helper ---

function relativeTime(dateStr) {
    if (!dateStr) return "";
    const now = Date.now();
    const then = new Date(dateStr).getTime();
    const diff = now - then;
    const mins = Math.floor(diff / 60000);
    if (mins < 1) return "just now";
    if (mins < 60) return `${mins}m ago`;
    const hours = Math.floor(mins / 60);
    if (hours < 24) return `${hours}h ago`;
    const days = Math.floor(hours / 24);
    return `${days}d ago`;
}

// --- Escape HTML helper ---

function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
}

// --- Views ---

async function renderLogin() {
    app.innerHTML = `
        <div class="auth-container view-enter">
            <div class="auth-card">
                <h2>Welcome back</h2>
                <p class="auth-subtitle">Sign in to CloudLab Manager</p>
                <form id="login-form">
                    <div class="form-group">
                        <label for="login-user">Username</label>
                        <input id="login-user" name="username" required autocomplete="username">
                    </div>
                    <div class="form-group">
                        <label for="login-pass">Password</label>
                        <input id="login-pass" name="password" type="password" required autocomplete="current-password">
                    </div>
                    <button type="submit" class="btn btn-primary" style="width:100%;margin-top:0.5rem;">Sign In</button>
                </form>
                <p class="form-error" id="login-error">Invalid credentials</p>
                <p class="auth-link"><a href="#forgot-password">Forgot Password?</a></p>
            </div>
        </div>
    `;
    $("#login-form").addEventListener("submit", async (e) => {
        e.preventDefault();
        const fd = new FormData(e.target);
        const res = await fetch("/api/auth/login", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ username: fd.get("username"), password: fd.get("password") }),
        });
        if (res.ok) {
            const data = await res.json();
            setToken(data.access_token);
            if (data.user) {
                setCurrentUser({
                    id: data.user.id,
                    username: data.user.username,
                    display_name: data.user.display_name,
                    email: data.user.email,
                    permissions: data.permissions || [],
                });
            }
            navigate("dashboard");
        } else {
            const el = $("#login-error");
            el.style.display = "block";
        }
    });
}

async function renderSetup() {
    app.innerHTML = `
        <div class="auth-container view-enter">
            <div class="auth-card">
                <h2>Initial Setup</h2>
                <p class="auth-subtitle">Create admin account and configure vault access</p>
                <form id="setup-form">
                    <div class="form-group">
                        <label for="setup-user">Username</label>
                        <input id="setup-user" name="username" required autocomplete="username">
                    </div>
                    <div class="form-group">
                        <label for="setup-pass">Password</label>
                        <input id="setup-pass" name="password" type="password" required autocomplete="new-password">
                    </div>
                    <div class="form-group">
                        <label for="setup-vault">Vault Password</label>
                        <input id="setup-vault" name="vault_password" type="password" required>
                        <small>Ansible vault password used to decrypt secrets.yml</small>
                    </div>
                    <button type="submit" class="btn btn-primary" style="width:100%;margin-top:0.5rem;">Complete Setup</button>
                </form>
                <p class="form-error" id="setup-error"></p>
            </div>
        </div>
    `;
    $("#setup-form").addEventListener("submit", async (e) => {
        e.preventDefault();
        const fd = new FormData(e.target);
        const res = await fetch("/api/auth/setup", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                username: fd.get("username"),
                password: fd.get("password"),
                vault_password: fd.get("vault_password"),
            }),
        });
        if (res.ok) {
            const data = await res.json();
            setToken(data.access_token);
            if (data.user) {
                setCurrentUser({
                    id: data.user.id,
                    username: data.user.username,
                    display_name: data.user.display_name,
                    email: data.user.email,
                    permissions: data.permissions || [],
                });
            }
            navigate("dashboard");
        } else {
            const err = await res.json();
            const el = $("#setup-error");
            el.textContent = err.detail || "Setup failed";
            el.style.display = "block";
        }
    });
}

async function renderDashboard() {
    app.innerHTML = `<div class="loading">Loading dashboard...</div>`;

    await loadInventoryTypes();

    // Fetch counts for each type + jobs + service outputs
    const fetches = [apiJson("/api/jobs")];
    for (const t of inventoryTypes) {
        if (hasPermission(`inventory.${t.slug}.view`)) {
            fetches.push(apiJson(`/api/inventory/${t.slug}?per_page=1`));
        } else {
            fetches.push(Promise.resolve(null));
        }
    }
    if (hasPermission("services.view")) {
        fetches.push(apiJson("/api/services/outputs"));
    } else {
        fetches.push(Promise.resolve(null));
    }
    if (hasPermission("costs.view")) {
        fetches.push(apiJson("/api/costs"));
    } else {
        fetches.push(Promise.resolve(null));
    }
    const results = await Promise.all(fetches);
    const jobsData = results[0];
    if (!jobsData) return;

    const outputsData = results[results.length - 2];
    const costData = results[results.length - 1];

    const jobs = jobsData.jobs || [];
    const running = jobs.filter(j => j.status === "running").length;
    const completed = jobs.filter(j => j.status === "completed").length;
    const failed = jobs.filter(j => j.status === "failed").length;

    // Build quick links from service outputs
    const quickLinks = [];
    if (outputsData && outputsData.outputs) {
        for (const [svcName, outputs] of Object.entries(outputsData.outputs)) {
            for (const out of outputs) {
                if (out.type === "url" && out.value) {
                    quickLinks.push({ service: svcName, label: out.label || svcName, url: out.value });
                }
            }
        }
    }

    const showStopAll = hasPermission("system.stop_all");
    const accentColors = ["accent-amber", "accent-blue", "accent-cyan", "accent-green"];

    app.innerHTML = `
        <div class="page-header view-enter stagger-1">
            <h2>Dashboard</h2>
            ${showStopAll ? `<button class="btn btn-danger btn-sm" id="stop-all-btn">Stop All Instances</button>` : ""}
        </div>

        <div class="stat-grid view-enter stagger-2">
            ${inventoryTypes.map((t, i) => {
                const typeData = results[i + 1];
                const count = typeData ? (typeData.total || 0) : 0;
                return `<div class="stat-card ${accentColors[i % accentColors.length]}">
                    <div class="stat-value">${count}</div>
                    <div class="stat-label">${t.label}s</div>
                </div>`;
            }).join("")}
            <div class="stat-card accent-blue">
                <div class="stat-value">${running}</div>
                <div class="stat-label">Running Jobs</div>
            </div>
            <div class="stat-card accent-green">
                <div class="stat-value">${completed}</div>
                <div class="stat-label">Completed</div>
            </div>
            <div class="stat-card accent-red">
                <div class="stat-value">${failed}</div>
                <div class="stat-label">Failed</div>
            </div>
            ${costData ? `<div class="stat-card accent-amber" style="cursor:pointer" onclick="window.location.hash='costs'">
                <div class="stat-value">$${parseFloat(costData.total_monthly_cost || 0).toFixed(2)}</div>
                <div class="stat-label">Monthly Cost</div>
            </div>` : ""}
        </div>

        ${quickLinks.length > 0 ? `
        <div class="view-enter stagger-3">
            <div class="section-label">Quick Links</div>
            <div class="quick-links-grid">
                ${quickLinks.map(link => `
                    <a href="${escapeHtml(link.url)}" target="_blank" rel="noopener" class="quick-link-card">
                        <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M6 3H3v10h10v-3"/><path d="M9 2h5v5"/><path d="M14 2L7 9"/></svg>
                        <div class="quick-link-info">
                            <div class="quick-link-label">${escapeHtml(link.label)}</div>
                            <div class="quick-link-service">${escapeHtml(link.service)}</div>
                        </div>
                    </a>
                `).join("")}
            </div>
        </div>
        ` : ""}

        <div class="view-enter stagger-${quickLinks.length > 0 ? "4" : "3"}">
            <div class="section-label">Recent Activity</div>
            ${jobs.length === 0 ? `
                <div class="empty-state">
                    <div class="empty-icon">&#9635;</div>
                    <div>No jobs yet. Deploy a service to get started.</div>
                </div>
            ` : `
                <div class="job-list">
                    ${jobs.slice(0, 10).map(j => `
                        <div class="job-item" onclick="window.location.hash='job-${j.id}'">
                            <div class="job-info">
                                <div class="job-title">${j.service} — ${j.script || j.action}${j.deployment_id ? ` <span class="deployment-badge">${j.deployment_id}</span>` : ""}</div>
                                <div class="job-time">${relativeTime(j.started_at)}</div>
                            </div>
                            <div>${badge(j.status)}</div>
                        </div>
                    `).join("")}
                </div>
            `}
        </div>
    `;

    if (showStopAll) {
        $("#stop-all-btn").addEventListener("click", async () => {
            const yes = await confirm("Stop All Instances?", "This will destroy all running Vultr instances. This action cannot be undone.");
            if (!yes) return;
            const res = await apiJson("/api/services/actions/stop-all", { method: "POST" });
            if (res) navigate("job-" + res.job_id);
        });
    }
}

function renderObjActions(typeSlug, obj, actions) {
    const d = obj.data || {};
    return actions.map(a => {
        if (a.type === "builtin" && a.name === "ssh") {
            if (d.power_status !== "running") return "";
            if (!hasPermission(`inventory.${typeSlug}.ssh`) && !hasPermission("instances.ssh")) return "";
            return `<button class="btn btn-primary btn-sm ssh-btn" data-hostname="${escapeHtml(d.hostname || "")}" data-ip="${escapeHtml(d.ip_address || "")}">SSH</button>`;
        }
        if (a.type === "builtin_config") {
            if (!hasPermission(`inventory.${typeSlug}.config`) && !hasPermission("services.config.view")) return "";
            return `<button class="svc-link config-link-btn" data-name="${escapeHtml(d.name || "")}" title="Edit Config">Config</button>`;
        }
        if (a.type === "builtin_files") {
            if (!hasPermission(`inventory.${typeSlug}.files`) && !hasPermission("services.files.view")) return "";
            return `<button class="svc-link files-link-btn" data-name="${escapeHtml(d.name || "")}" title="Files">Files</button>`;
        }
        if (a.type === "dynamic_scripts") return ""; // Handled by service row rendering
        if (a.type === "script" || a.type === "script_stop" || a.type === "playbook") {
            const btnClass = (a.name === "destroy" || a.name === "stop") ? "btn-danger" : "btn-primary";
            return `<button class="btn ${btnClass} btn-sm obj-action-btn" data-id="${obj.id}" data-action="${escapeHtml(a.name)}">${escapeHtml(a.label)}</button>`;
        }
        return "";
    }).join("");
}

function renderServiceList(objects, actions, scriptsMap) {
    return `<div class="service-roster">
        ${objects.map((obj, i) => {
            const d = obj.data || {};
            const name = d.name || "";
            const scripts = scriptsMap[name] || [{name: "deploy", label: "Deploy", file: "deploy.sh"}];
            const tags = obj.tags || [];
            const canDeploy = hasPermission("inventory.service.deploy") || hasPermission("services.deploy");
            const canStop = hasPermission("inventory.service.stop") || hasPermission("services.stop");
            const canConfig = hasPermission("inventory.service.config") || hasPermission("services.config.view");
            const canFiles = hasPermission("inventory.service.files") || hasPermission("services.files.view");
            return `
                <div class="service-row" style="animation-delay: ${0.1 + i * 0.04}s">
                    <div class="service-row-info">
                        <div class="service-name">
                            ${escapeHtml(name)}
                            <button class="svc-outputs-toggle" data-name="${escapeHtml(name)}" title="View outputs">
                                <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 3l5 5-5 5"/></svg>
                            </button>
                        </div>
                        <div class="service-path">${escapeHtml(d.service_dir || "")}
                            ${tags.map(t => `<span class="tag-pill tag-pill-sm" style="--tag-color:${t.color || '#4a5a70'}">${escapeHtml(t.name)}</span>`).join(" ")}
                        </div>
                    </div>
                    <div class="service-row-links">
                        ${canConfig ? `<button class="svc-link config-link-btn" data-name="${escapeHtml(name)}" title="Edit Config">
                            <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M11.5 1.5l3 3L5 14H2v-3L11.5 1.5z"/></svg>
                            Config
                        </button>` : ""}
                        ${canFiles ? `<button class="svc-link files-link-btn" data-name="${escapeHtml(name)}" title="Files">
                            <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M2 3h5l2 2h5v8H2V3z"/></svg>
                            Files
                        </button>` : ""}
                    </div>
                    <div class="service-row-actions">
                        ${canDeploy ? `
                        <select class="script-select" data-name="${escapeHtml(name)}" data-obj-id="${obj.id}">
                            ${scripts.map(sc => `<option value="${escapeHtml(sc.name)}">${escapeHtml(sc.label)}</option>`).join("")}
                        </select>
                        <button class="btn btn-primary btn-sm svc-run-btn" data-name="${escapeHtml(name)}" data-obj-id="${obj.id}">Run</button>` : ""}
                        ${canStop ? `<button class="btn btn-danger btn-sm svc-stop-btn" data-name="${escapeHtml(name)}" data-obj-id="${obj.id}">Stop</button>` : ""}
                    </div>
                </div>
                <div class="service-outputs-panel" id="svc-outputs-${escapeHtml(name)}" style="display:none;"></div>`;
        }).join("")}
    </div>`;
}

function bindServiceActionHandlers(typeSlug, objects, scriptsMap) {
    document.querySelectorAll(".config-link-btn").forEach(btn => {
        btn.addEventListener("click", () => navigate("service-config-" + btn.dataset.name));
    });
    document.querySelectorAll(".files-link-btn").forEach(btn => {
        btn.addEventListener("click", () => navigate("service-files-" + btn.dataset.name));
    });
    document.querySelectorAll(".svc-run-btn").forEach(btn => {
        btn.addEventListener("click", async () => {
            const name = btn.dataset.name;
            const objId = btn.dataset.objId;
            const select = btn.parentElement.querySelector(".script-select");
            const scriptName = select.value;
            const scripts = scriptsMap[name] || [];
            const scriptDef = scripts.find(s => s.name === scriptName) || { name: scriptName, label: scriptName };

            let inputs = {};
            if (scriptDef.inputs && scriptDef.inputs.length > 0) {
                const result = await showInputModal(name, scriptDef);
                if (!result) return;
                inputs = result;
            } else {
                const yes = await confirm(`Run ${scriptDef.label} for ${name}?`, scriptDef.description || "This will run the selected script.");
                if (!yes) return;
            }

            btn.setAttribute("aria-busy", "true");
            const res = await apiJson(`/api/inventory/service/${objId}/actions/run_script`, {
                method: "POST",
                body: JSON.stringify({ script: scriptName, inputs }),
            });
            if (res && res.job_id) navigate("job-" + res.job_id);
            else btn.removeAttribute("aria-busy");
        });
    });
    document.querySelectorAll(".svc-stop-btn").forEach(btn => {
        btn.addEventListener("click", async () => {
            const name = btn.dataset.name;
            const objId = btn.dataset.objId;
            const yes = await confirm(`Stop ${name}?`, "This will stop instances for this service.");
            if (!yes) return;
            btn.setAttribute("aria-busy", "true");
            const res = await apiJson(`/api/inventory/service/${objId}/actions/stop`, { method: "POST" });
            if (res && res.job_id) navigate("job-" + res.job_id);
            else btn.removeAttribute("aria-busy");
        });
    });
    // Outputs toggle
    document.querySelectorAll(".svc-outputs-toggle").forEach(btn => {
        btn.addEventListener("click", async (e) => {
            e.stopPropagation();
            const name = btn.dataset.name;
            const panel = document.getElementById(`svc-outputs-${name}`);
            if (!panel) return;
            if (panel.style.display !== "none") {
                panel.style.display = "none";
                btn.classList.remove("open");
                return;
            }
            btn.classList.add("open");
            panel.style.display = "block";
            panel.innerHTML = `<div class="loading" style="padding:0.5rem;">Loading...</div>`;
            const res = await apiJson(`/api/services/${encodeURIComponent(name)}/outputs`);
            const outputs = (res && res.outputs) || [];
            if (outputs.length === 0) {
                panel.innerHTML = `<div class="svc-outputs-empty">No outputs yet</div>`;
                return;
            }
            panel.innerHTML = `<div class="svc-outputs-list">
                ${outputs.map((o, idx) => {
                    if (o.type === "url") {
                        return `<div class="svc-output-item">
                            <span class="svc-output-label">${escapeHtml(o.label || o.name)}</span>
                            <a class="svc-output-url svc-url-link" data-idx="${idx}" target="_blank" rel="noopener">${escapeHtml(o.value)}</a>
                        </div>`;
                    }
                    if (o.type === "credential") {
                        const id = `cred-${name}-${o.name}`;
                        return `<div class="svc-output-item">
                            <span class="svc-output-label">${escapeHtml(o.label || o.name)}${o.username ? ` (${escapeHtml(o.username)})` : ""}</span>
                            <span class="svc-output-secret" id="${id}">
                                <code class="secret-value" style="filter:blur(4px);user-select:none;">${escapeHtml(o.value || "")}</code>
                                <button class="btn btn-ghost btn-xs reveal-btn" data-target="${id}">Reveal</button>
                                <button class="btn btn-ghost btn-xs copy-btn" data-idx="${idx}">Copy</button>
                            </span>
                        </div>`;
                    }
                    return `<div class="svc-output-item">
                        <span class="svc-output-label">${escapeHtml(o.label || o.name)}</span>
                        <span>${escapeHtml(o.value || "")}</span>
                    </div>`;
                }).join("")}
            </div>`;
            // Set href attributes safely via DOM
            panel.querySelectorAll(".svc-url-link").forEach(a => {
                const o = outputs[parseInt(a.dataset.idx)];
                if (o) a.href = o.value;
            });
            // Bind reveal/copy buttons
            panel.querySelectorAll(".reveal-btn").forEach(rb => {
                rb.addEventListener("click", () => {
                    const target = document.getElementById(rb.dataset.target);
                    const code = target.querySelector(".secret-value");
                    if (code.style.filter) { code.style.filter = ""; code.style.userSelect = ""; rb.textContent = "Hide"; }
                    else { code.style.filter = "blur(4px)"; code.style.userSelect = "none"; rb.textContent = "Reveal"; }
                });
            });
            panel.querySelectorAll(".copy-btn").forEach(cb => {
                cb.addEventListener("click", () => {
                    const o = outputs[parseInt(cb.dataset.idx)];
                    navigator.clipboard.writeText(o ? o.value || "" : "");
                    cb.textContent = "Copied";
                    setTimeout(() => cb.textContent = "Copy", 1500);
                });
            });
        });
    });
}

// --- Script input modal ---

function showInputModal(serviceName, scriptDef) {
    return new Promise(async (resolve) => {
        const inputs = scriptDef.inputs || [];

        // Pre-fetch data for special input types
        let deploymentsData = [];
        let sshKeysData = [];
        if (inputs.some(i => i.type === "deployment_select")) {
            try {
                const res = await apiJson("/api/services/active-deployments");
                if (res) deploymentsData = res.deployments || [];
            } catch (e) { /* ignore */ }
        }
        if (inputs.some(i => i.type === "ssh_key_select")) {
            try {
                const res = await apiJson("/api/auth/ssh-keys");
                if (res) sshKeysData = res.keys || [];
            } catch (e) { /* ignore */ }
        }

        const overlay = document.createElement("div");
        overlay.className = "confirm-overlay";
        overlay.innerHTML = `
            <div class="confirm-box input-modal">
                <h4>Run ${scriptDef.label} — ${serviceName}</h4>
                ${scriptDef.description ? `<p>${scriptDef.description}</p>` : ""}
                <form id="input-modal-form">
                    ${inputs.map(inp => {
                        if (inp.type === "deployment_select") {
                            return `
                                <div class="form-group">
                                    <label>${inp.label}${inp.required ? ' *' : ''}</label>
                                    ${inp.description ? `<small>${inp.description}</small>` : ""}
                                    <select name="${inp.name}" class="input-modal-select" ${inp.required ? 'required' : ''}>
                                        <option value="">Select a service...</option>
                                        ${deploymentsData.map(d => `<option value="${d.name}">${d.name}</option>`).join("")}
                                    </select>
                                    ${deploymentsData.length === 0 ? '<small style="color:var(--accent-red)">No active deployments found</small>' : ''}
                                </div>`;
                        }
                        if (inp.type === "ssh_key_select") {
                            return `
                                <div class="form-group">
                                    <label>${inp.label}${inp.required ? ' *' : ''}</label>
                                    ${inp.description ? `<small>${inp.description}</small>` : ""}
                                    <div class="ssh-key-select" data-input="${inp.name}">
                                        ${sshKeysData.length === 0
                                            ? '<small style="color:var(--accent-red)">No users have SSH keys. Generate keys from Profile page.</small>'
                                            : sshKeysData.map(k => `
                                                <label class="ssh-key-option">
                                                    <input type="checkbox" value="${escapeHtml(k.ssh_public_key)}" data-username="${escapeHtml(k.username)}">
                                                    <span class="ssh-key-option-name">${escapeHtml(k.display_name || k.username)}</span>
                                                    <span class="ssh-key-option-user">${escapeHtml(k.username)}${k.is_self ? ' (you)' : ''}</span>
                                                </label>
                                            `).join("")}
                                    </div>
                                </div>`;
                        }
                        if (inp.type === "list") {
                            return `
                                <div class="form-group">
                                    <label>${inp.label}${inp.required ? ' *' : ''}</label>
                                    ${inp.description ? `<small>${inp.description}</small>` : ""}
                                    <div class="list-input-group" data-input="${inp.name}">
                                        <div class="list-input-entries">
                                            <div class="list-input-entry">
                                                <input type="text" class="list-input-field" placeholder="Enter value">
                                                <button type="button" class="btn btn-ghost btn-sm list-remove-btn">x</button>
                                            </div>
                                        </div>
                                        <button type="button" class="btn btn-ghost btn-sm list-add-btn">+ Add</button>
                                    </div>
                                </div>`;
                        }
                        return `
                            <div class="form-group">
                                <label>${inp.label}${inp.required ? ' *' : ''}</label>
                                ${inp.description ? `<small>${inp.description}</small>` : ""}
                                <input type="text" name="${inp.name}" ${inp.required ? 'required' : ''} placeholder="Enter value">
                            </div>`;
                    }).join("")}
                    <div class="actions">
                        <button type="button" class="btn" id="input-modal-cancel">Cancel</button>
                        <button type="submit" class="btn btn-primary">Run</button>
                    </div>
                </form>
            </div>
        `;
        document.body.appendChild(overlay);

        // List add/remove handlers
        overlay.querySelectorAll(".list-add-btn").forEach(btn => {
            btn.addEventListener("click", () => {
                const entries = btn.previousElementSibling;
                const entry = document.createElement("div");
                entry.className = "list-input-entry";
                entry.innerHTML = `
                    <input type="text" class="list-input-field" placeholder="Enter value">
                    <button type="button" class="btn btn-ghost btn-sm list-remove-btn">x</button>
                `;
                entries.appendChild(entry);
                entry.querySelector(".list-remove-btn").addEventListener("click", () => {
                    if (entries.children.length > 1) entry.remove();
                });
            });
        });

        overlay.querySelectorAll(".list-remove-btn").forEach(btn => {
            btn.addEventListener("click", () => {
                const entries = btn.closest(".list-input-entries");
                if (entries.children.length > 1) btn.closest(".list-input-entry").remove();
            });
        });

        overlay.querySelector("#input-modal-cancel").onclick = () => { overlay.remove(); resolve(null); };

        overlay.querySelector("#input-modal-form").addEventListener("submit", (e) => {
            e.preventDefault();
            // Validate ssh_key_select required fields
            for (const inp of inputs) {
                if (inp.type === "ssh_key_select" && inp.required) {
                    const group = overlay.querySelector(`.ssh-key-select[data-input="${inp.name}"]`);
                    const checked = group.querySelectorAll('input[type="checkbox"]:checked');
                    if (checked.length === 0) {
                        let errEl = group.parentElement.querySelector(".input-modal-error");
                        if (!errEl) {
                            errEl = document.createElement("small");
                            errEl.className = "input-modal-error";
                            errEl.style.color = "var(--accent-red)";
                            group.parentElement.appendChild(errEl);
                        }
                        errEl.textContent = "Select at least one SSH key";
                        return;
                    }
                }
            }
            const result = {};
            inputs.forEach(inp => {
                if (inp.type === "deployment_select") {
                    const sel = overlay.querySelector(`[name="${inp.name}"]`);
                    result[inp.name] = sel ? sel.value : "";
                } else if (inp.type === "ssh_key_select") {
                    const group = overlay.querySelector(`.ssh-key-select[data-input="${inp.name}"]`);
                    const checked = Array.from(group.querySelectorAll('input[type="checkbox"]:checked'));
                    result[inp.name] = checked.map(cb => cb.value).join(",");
                } else if (inp.type === "list") {
                    const group = overlay.querySelector(`[data-input="${inp.name}"]`);
                    const values = Array.from(group.querySelectorAll(".list-input-field"))
                        .map(f => f.value.trim())
                        .filter(v => v);
                    result[inp.name] = values;
                } else {
                    const field = overlay.querySelector(`[name="${inp.name}"]`);
                    result[inp.name] = field ? field.value.trim() : "";
                }
            });
            overlay.remove();
            resolve(result);
        });
    });
}

// Legacy redirects
function renderInstances() { navigate("inventory-server"); }
function renderServices() { navigate("inventory-service"); }

async function renderJobs() {
    app.innerHTML = `<div class="loading">Loading jobs...</div>`;
    const data = await apiJson("/api/jobs");
    if (!data) return;

    const jobs = data.jobs || [];

    app.innerHTML = `
        <div class="page-header view-enter stagger-1">
            <h2>Jobs</h2>
            <small>${jobs.length} total</small>
        </div>
        <div class="view-enter stagger-2">
            ${jobs.length === 0 ? `
                <div class="empty-state">
                    <div class="empty-icon">▶</div>
                    <div>No jobs recorded yet.</div>
                </div>
            ` : `
                <div class="job-list">
                    ${jobs.map(j => `
                        <div class="job-item" onclick="window.location.hash='job-${j.id}'">
                            <div class="job-info">
                                <div class="job-title">${j.service} — ${j.script || j.action}${j.deployment_id ? ` <span class="deployment-badge">${j.deployment_id}</span>` : ""}</div>
                                <div class="job-time">${j.started_at ? new Date(j.started_at).toLocaleString() : ""}</div>
                            </div>
                            <div>${badge(j.status)}</div>
                        </div>
                    `).join("")}
                </div>
            `}
        </div>
    `;
}

async function renderJobDetail(jobId) {
    app.innerHTML = `<div class="loading">Loading job...</div>`;

    const data = await apiJson(`/api/jobs/${jobId}`);
    if (!data) return;

    app.innerHTML = `
        <div class="view-enter stagger-1">
            <div class="page-header">
                <div style="display:flex;align-items:center;gap:1rem;">
                    <h2>${data.service} — ${data.script || data.action}</h2>
                    ${data.deployment_id ? `<span class="deployment-badge">${data.deployment_id}</span>` : ""}
                    ${badge(data.status)}
                </div>
            </div>
        </div>

        <div class="timestamp-row view-enter stagger-2">
            <span>Started: ${data.started_at ? new Date(data.started_at).toLocaleString() : "—"}</span>
            ${data.finished_at ? `<span>Finished: ${new Date(data.finished_at).toLocaleString()}</span>` : ""}
        </div>

        <div class="view-enter stagger-3">
            <div class="job-terminal" id="terminal"></div>
        </div>

        <a href="#jobs" class="back-link view-enter stagger-4">&#8592; Back to Jobs</a>
    `;

    const terminal = $("#terminal");

    if (data.status === "running") {
        terminal.textContent = data.output.join("\n");
        terminal.scrollTop = terminal.scrollHeight;

        const interval = setInterval(async () => {
            const updated = await apiJson(`/api/jobs/${jobId}`);
            if (!updated) { clearInterval(interval); return; }
            terminal.textContent = updated.output.join("\n");
            terminal.scrollTop = terminal.scrollHeight;
            if (updated.status !== "running") {
                clearInterval(interval);
                const badgeEl = app.querySelector(".badge");
                if (badgeEl) badgeEl.outerHTML = badge(updated.status);
            }
        }, 1000);
    } else {
        terminal.textContent = data.output.join("\n");
    }
}

function updateLineNumbers(editor, lineNumbersEl) {
    const lines = editor.value.split("\n").length;
    lineNumbersEl.innerHTML = Array.from({ length: lines }, (_, i) =>
        `<span>${i + 1}</span>`
    ).join("");
}

function syncScroll(editor, lineNumbersEl) {
    lineNumbersEl.scrollTop = editor.scrollTop;
}

async function renderServiceConfig(name) {
    app.innerHTML = `<div class="loading">Loading config...</div>`;
    const data = await apiJson(`/api/services/${name}/configs`);
    if (!data) return;

    const configs = (data.configs || []).filter(c => c.exists);
    if (configs.length === 0) {
        app.innerHTML = `
            <div class="view-enter">
                <div class="empty-state">
                    <div class="empty-icon">▣</div>
                    <div>No config files found for ${name}.</div>
                </div>
                <a href="#services" class="back-link">&#8592; Back to Scripts</a>
            </div>
        `;
        return;
    }

    const activeTab = configs[0].name;

    app.innerHTML = `
        <div class="page-header view-enter stagger-1">
            <div>
                <h2>${name}</h2>
                <small>${data.service_dir}</small>
            </div>
        </div>
        <div class="config-editor-container view-enter stagger-2">
            <div class="config-tabs">
                ${configs.map(c => `
                    <button class="config-tab ${c.name === activeTab ? "active" : ""}" data-file="${c.name}">${c.name}</button>
                `).join("")}
            </div>
            <div class="editor-wrapper">
                <div class="line-numbers" id="line-numbers"></div>
                <textarea class="yaml-editor" id="yaml-editor" spellcheck="false"></textarea>
            </div>
            <div class="config-editor-footer">
                <div class="editor-status" id="editor-status">Ready</div>
                <div class="config-editor-actions">
                    <a href="#services" class="btn btn-ghost btn-sm">Cancel</a>
                    <button class="btn btn-primary btn-sm" id="save-btn">Save</button>
                </div>
            </div>
        </div>
        <a href="#services" class="back-link view-enter stagger-3">&#8592; Back to Scripts</a>
    `;

    const editor = $("#yaml-editor");
    const lineNumbers = $("#line-numbers");
    const status = $("#editor-status");
    let currentFile = activeTab;

    editor.addEventListener("input", () => updateLineNumbers(editor, lineNumbers));
    editor.addEventListener("scroll", () => syncScroll(editor, lineNumbers));

    async function loadFile(filename) {
        editor.value = "";
        status.textContent = "Loading...";
        status.className = "editor-status";
        const res = await apiJson(`/api/services/${name}/configs/${filename}`);
        if (res) {
            editor.value = res.content;
            updateLineNumbers(editor, lineNumbers);
            status.textContent = "Ready";
        } else {
            status.textContent = "Failed to load";
            status.className = "editor-status status-error";
        }
    }

    // Tab switching
    document.querySelectorAll(".config-tab").forEach(tab => {
        tab.addEventListener("click", async () => {
            document.querySelectorAll(".config-tab").forEach(t => t.classList.remove("active"));
            tab.classList.add("active");
            currentFile = tab.dataset.file;
            await loadFile(currentFile);
        });
    });

    // Save
    $("#save-btn").addEventListener("click", async () => {
        status.textContent = "Saving...";
        status.className = "editor-status";
        const res = await api(`/api/services/${name}/configs/${currentFile}`, {
            method: "PUT",
            body: JSON.stringify({ content: editor.value }),
        });
        if (!res) return;
        if (res.ok) {
            status.textContent = "Saved";
            status.className = "editor-status status-saved";
        } else {
            const err = await res.json();
            status.textContent = err.detail || "Error saving";
            status.className = "editor-status status-error";
        }
    });

    // Load initial file
    await loadFile(activeTab);
}

// --- File size helper ---

function formatSize(bytes) {
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
    return (bytes / (1024 * 1024)).toFixed(1) + " MB";
}

// --- Service Files View ---

async function renderServiceFiles(name) {
    app.innerHTML = `<div class="loading">Loading files...</div>`;

    let activeTab = "inputs";

    async function loadTab(subdir) {
        activeTab = subdir;
        const data = await apiJson(`/api/services/${name}/files/${subdir}`);
        if (!data) return;
        const files = data.files || [];
        const fileCount = files.length;

        app.innerHTML = `
            <div class="page-header view-enter stagger-1">
                <div>
                    <h2>${name}</h2>
                    <small>/services/${name}/</small>
                </div>
            </div>
            <div class="config-editor-container view-enter stagger-2">
                <div class="config-tabs">
                    <button class="config-tab ${activeTab === "inputs" ? "active" : ""}" data-tab="inputs">Inputs</button>
                    <button class="config-tab ${activeTab === "outputs" ? "active" : ""}" data-tab="outputs">Outputs</button>
                </div>
                <div class="files-content">
                    <div class="files-toolbar">
                        <span class="files-dir-label">${activeTab}/ &mdash; ${fileCount} file${fileCount !== 1 ? "s" : ""}</span>
                        <div>
                            <button class="btn btn-primary btn-sm upload-btn-styled" id="upload-btn">Upload</button>
                            <input type="file" id="file-input" style="display:none">
                        </div>
                    </div>
                    ${files.length === 0 ? `
                        <div class="empty-state">
                            <div class="empty-icon">◇</div>
                            <div>No files in ${activeTab}/</div>
                        </div>
                    ` : `
                        <table class="data-table">
                            <thead>
                                <tr>
                                    <th>Filename</th>
                                    <th>Size</th>
                                    <th>Modified</th>
                                    <th>Actions</th>
                                </tr>
                            </thead>
                            <tbody>
                                ${files.map(f => `
                                    <tr>
                                        <td><span class="file-name-cell">${f.name}</span></td>
                                        <td class="file-size-cell">${formatSize(f.size)}</td>
                                        <td>${relativeTime(f.modified)}</td>
                                        <td class="file-actions">
                                            <a href="/api/services/${name}/files/${activeTab}/${encodeURIComponent(f.name)}" class="btn btn-ghost btn-sm" download="${f.name}">Download</a>
                                            ${f.size <= 102400 ? `<button class="btn btn-ghost btn-sm file-edit-btn" data-file="${f.name}">Edit</button>` : ""}
                                            <button class="btn btn-danger btn-sm file-delete-btn" data-file="${f.name}">Delete</button>
                                        </td>
                                    </tr>
                                `).join("")}
                            </tbody>
                        </table>
                    `}
                </div>
            </div>
            <div id="file-editor-area"></div>
            <a href="#services" class="back-link view-enter stagger-3">&#8592; Back to Scripts</a>
        `;

        // Tab switching
        document.querySelectorAll(".config-tab").forEach(tab => {
            tab.addEventListener("click", () => loadTab(tab.dataset.tab));
        });

        // Upload
        const uploadBtn = document.getElementById("upload-btn");
        const fileInput = document.getElementById("file-input");
        uploadBtn.addEventListener("click", () => fileInput.click());
        fileInput.addEventListener("change", async () => {
            const file = fileInput.files[0];
            if (!file) return;
            uploadBtn.setAttribute("aria-busy", "true");
            const formData = new FormData();
            formData.append("file", file);
            const token = getToken();
            const res = await fetch(`/api/services/${name}/files/${activeTab}`, {
                method: "POST",
                headers: { "Authorization": `Bearer ${token}` },
                body: formData,
            });
            if (res.ok) {
                loadTab(activeTab);
            } else {
                const err = await res.json();
                alert(err.detail || "Upload failed");
                uploadBtn.removeAttribute("aria-busy");
            }
        });

        // Download links need auth header — attach token via click handler
        document.querySelectorAll("a[download]").forEach(link => {
            link.addEventListener("click", async (e) => {
                e.preventDefault();
                const token = getToken();
                const res = await fetch(link.href, {
                    headers: { "Authorization": `Bearer ${token}` },
                });
                if (!res.ok) return;
                const blob = await res.blob();
                const url = URL.createObjectURL(blob);
                const a = document.createElement("a");
                a.href = url;
                a.download = link.getAttribute("download");
                a.click();
                URL.revokeObjectURL(url);
            });
        });

        // Edit buttons
        document.querySelectorAll(".file-edit-btn").forEach(btn => {
            btn.addEventListener("click", async () => {
                const filename = btn.dataset.file;
                const editorArea = document.getElementById("file-editor-area");
                editorArea.innerHTML = `<div class="loading">Loading file...</div>`;

                const token = getToken();
                const res = await fetch(`/api/services/${name}/files/${activeTab}/${encodeURIComponent(filename)}`, {
                    headers: { "Authorization": `Bearer ${token}` },
                });
                if (!res.ok) {
                    editorArea.innerHTML = `<p style="color:var(--accent-red)">Could not load file</p>`;
                    return;
                }
                const text = await res.text();

                editorArea.innerHTML = `
                    <div class="inline-editor">
                        <div class="config-editor-container">
                            <div class="config-tabs">
                                <span class="config-tab active">${filename}</span>
                            </div>
                            <div class="editor-wrapper">
                                <div class="line-numbers" id="file-line-numbers"></div>
                                <textarea class="yaml-editor" id="file-editor" spellcheck="false">${text.replace(/</g, "&lt;")}</textarea>
                            </div>
                            <div class="config-editor-footer">
                                <div class="editor-status" id="file-editor-status">Editing</div>
                                <div class="config-editor-actions">
                                    <button class="btn btn-ghost btn-sm" id="file-editor-cancel">Cancel</button>
                                    <button class="btn btn-primary btn-sm" id="file-editor-save">Save</button>
                                </div>
                            </div>
                        </div>
                    </div>
                `;

                const fileEditor = document.getElementById("file-editor");
                const fileLineNumbers = document.getElementById("file-line-numbers");
                updateLineNumbers(fileEditor, fileLineNumbers);
                fileEditor.addEventListener("input", () => updateLineNumbers(fileEditor, fileLineNumbers));
                fileEditor.addEventListener("scroll", () => syncScroll(fileEditor, fileLineNumbers));

                // Scroll to editor
                editorArea.scrollIntoView({ behavior: "smooth", block: "start" });

                document.getElementById("file-editor-cancel").addEventListener("click", () => {
                    editorArea.innerHTML = "";
                });

                document.getElementById("file-editor-save").addEventListener("click", async () => {
                    const status = document.getElementById("file-editor-status");
                    status.textContent = "Saving...";
                    status.className = "editor-status";
                    const saveRes = await api(`/api/services/${name}/files/${activeTab}/${encodeURIComponent(filename)}`, {
                        method: "PUT",
                        body: JSON.stringify({ content: document.getElementById("file-editor").value }),
                    });
                    if (!saveRes) return;
                    if (saveRes.ok) {
                        status.textContent = "Saved";
                        status.className = "editor-status status-saved";
                        loadTab(activeTab);
                    } else {
                        const err = await saveRes.json();
                        status.textContent = err.detail || "Error saving";
                        status.className = "editor-status status-error";
                    }
                });
            });
        });

        // Delete buttons
        document.querySelectorAll(".file-delete-btn").forEach(btn => {
            btn.addEventListener("click", async () => {
                const filename = btn.dataset.file;
                const yes = await confirm(`Delete ${filename}?`, "A backup will be created before deletion.");
                if (!yes) return;
                btn.setAttribute("aria-busy", "true");
                const res = await api(`/api/services/${name}/files/${activeTab}/${encodeURIComponent(filename)}`, {
                    method: "DELETE",
                });
                if (res && res.ok) {
                    loadTab(activeTab);
                } else {
                    btn.removeAttribute("aria-busy");
                }
            });
        });
    }

    await loadTab("inputs");
}

// --- SSH Terminal ---

const SSH_THEME = {
    background: "#080c14",
    foreground: "#c8d8e8",
    cursor: "#f0a030",
    cursorAccent: "#080c14",
    selectionBackground: "#f0a03040",
    black: "#0a0c10",
    red: "#f04040",
    green: "#30e870",
    yellow: "#f0a030",
    blue: "#4088f0",
    magenta: "#c060f0",
    cyan: "#40d0f0",
    white: "#c8d8e8",
    brightBlack: "#4a5a70",
    brightRed: "#f06060",
    brightGreen: "#50ff90",
    brightYellow: "#f5c050",
    brightBlue: "#60a8ff",
    brightMagenta: "#d080ff",
    brightCyan: "#60e8ff",
    brightWhite: "#e8edf5",
};

function initSSHTerminal(container, statusEl, hostname, opts = {}) {
    const term = new Terminal({
        cursorBlink: true,
        cursorStyle: "block",
        fontFamily: "'JetBrains Mono', monospace",
        fontSize: 14,
        lineHeight: 1.2,
        theme: SSH_THEME,
    });

    const fitAddon = new FitAddon.FitAddon();
    term.loadAddon(fitAddon);
    if (typeof WebLinksAddon !== "undefined") {
        term.loadAddon(new WebLinksAddon.WebLinksAddon());
    }

    term.open(container);

    // Wait for container to have real dimensions before fitting.
    // In fullpage mode the layout isn't resolved until the next frame.
    function doFit() {
        if (container.clientHeight > 50) {
            fitAddon.fit();
        } else {
            // Container hasn't been laid out yet, retry
            requestAnimationFrame(doFit);
        }
    }
    requestAnimationFrame(doFit);

    const protocol = location.protocol === "https:" ? "wss:" : "ws:";
    let wsUrl = `${protocol}//${location.host}/api/inventory/server/ssh/${encodeURIComponent(hostname)}?token=${encodeURIComponent(getToken())}`;
    if (opts.user) {
        wsUrl += `&user=${encodeURIComponent(opts.user)}`;
    }
    const ws = new WebSocket(wsUrl);
    let connected = false;

    ws.onopen = () => {
        fitAddon.fit();
        term.focus();
    };

    ws.onmessage = (event) => {
        const msg = JSON.parse(event.data);
        if (msg.type === "output") {
            term.write(msg.data);
        } else if (msg.type === "connected") {
            connected = true;
            statusEl.className = "ssh-status ssh-status-connected";
            statusEl.innerHTML = `<span class="ssh-status-dot"></span>Connected`;
            if (opts.onConnected) opts.onConnected(msg);
        } else if (msg.type === "error") {
            statusEl.className = "ssh-status ssh-status-error";
            statusEl.innerHTML = `<span class="ssh-status-dot"></span>${msg.message}`;
            term.write(connected
                ? `\r\n\x1b[33m[${msg.message}]\x1b[0m\r\n`
                : `\r\n\x1b[31m${msg.message}\x1b[0m\r\n`);
        }
    };

    ws.onclose = () => {
        if (connected) {
            statusEl.className = "ssh-status ssh-status-disconnected";
            statusEl.innerHTML = `<span class="ssh-status-dot"></span>Disconnected`;
            term.write("\r\n\x1b[2m[Connection closed]\x1b[0m\r\n");
        }
    };

    ws.onerror = () => {
        statusEl.className = "ssh-status ssh-status-error";
        statusEl.innerHTML = `<span class="ssh-status-dot"></span>Connection error`;
    };

    term.onData((data) => {
        if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: "input", data }));
    });
    term.onResize(({ cols, rows }) => {
        if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: "resize", cols, rows }));
    });

    const resizeObserver = new ResizeObserver(() => { fitAddon.fit(); });
    resizeObserver.observe(container);

    return { term, ws, fitAddon, resizeObserver, cleanup() {
        resizeObserver.disconnect();
        ws.close();
        term.dispose();
    }};
}

function openSSHTerminal(hostname, ip) {
    const overlay = document.createElement("div");
    overlay.className = "ssh-overlay";
    overlay.innerHTML = `
        <div class="ssh-modal">
            <div class="ssh-header">
                <div class="ssh-header-info">
                    <span class="ssh-hostname">${hostname}</span>
                    <span class="ssh-ip">${ip}</span>
                    <span class="ssh-user-field">
                        <span class="ssh-user-label">user:</span>
                        <input type="text" class="ssh-user-input" placeholder="root" spellcheck="false" />
                    </span>
                    <span class="ssh-status ssh-status-connecting">
                        <span class="ssh-status-dot"></span>
                        Connecting...
                    </span>
                </div>
                <div class="ssh-header-actions">
                    <button class="btn btn-ghost btn-sm ssh-newtab-btn" title="Open in new tab">New Tab</button>
                    <button class="btn btn-ghost btn-sm ssh-close-btn">Close</button>
                </div>
            </div>
            <div class="ssh-terminal-container" id="ssh-terminal-container"></div>
        </div>
    `;
    document.body.appendChild(overlay);

    const container = overlay.querySelector("#ssh-terminal-container");
    const statusEl = overlay.querySelector(".ssh-status");
    const userInput = overlay.querySelector(".ssh-user-input");
    let currentUser = null;
    let session = null;

    function connect(user) {
        if (session) session.cleanup();
        container.innerHTML = "";
        statusEl.className = "ssh-status ssh-status-connecting";
        statusEl.innerHTML = `<span class="ssh-status-dot"></span>Connecting...`;
        session = initSSHTerminal(container, statusEl, hostname, {
            user: user || undefined,
            onConnected(msg) {
                currentUser = msg.user;
                if (!userInput.value && msg.default_user) {
                    userInput.placeholder = msg.default_user;
                }
            },
        });
    }

    userInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
            e.preventDefault();
            connect(userInput.value.trim() || undefined);
        }
        e.stopPropagation();
    });

    connect();

    overlay.querySelector(".ssh-close-btn").addEventListener("click", () => {
        if (session) session.cleanup();
        overlay.remove();
    });

    overlay.querySelector(".ssh-newtab-btn").addEventListener("click", () => {
        if (session) session.cleanup();
        overlay.remove();
        let hash = `#ssh-${encodeURIComponent(hostname)}--${encodeURIComponent(ip)}`;
        const u = userInput.value.trim() || currentUser;
        if (u) hash += `--${encodeURIComponent(u)}`;
        window.open(hash, "_blank");
    });

    overlay.addEventListener("keydown", (e) => {
        if (e.key === "Escape" && e.ctrlKey) {
            if (session) session.cleanup();
            overlay.remove();
        }
    });
}

async function renderSSHPage(hostname, ip, initialUser) {
    document.body.classList.add("ssh-fullpage");

    app.innerHTML = `
        <div class="ssh-page">
            <div class="ssh-header">
                <div class="ssh-header-info">
                    <span class="ssh-hostname">${hostname}</span>
                    <span class="ssh-ip">${ip}</span>
                    <span class="ssh-user-field">
                        <span class="ssh-user-label">user:</span>
                        <input type="text" class="ssh-user-input" placeholder="root" spellcheck="false" value="${initialUser ? initialUser.replace(/"/g, '&quot;') : ''}" />
                    </span>
                    <span class="ssh-status ssh-status-connecting">
                        <span class="ssh-status-dot"></span>
                        Connecting...
                    </span>
                </div>
                <div class="ssh-header-actions">
                    <a href="#instances" class="btn btn-ghost btn-sm" id="ssh-back-btn">Back</a>
                </div>
            </div>
            <div class="ssh-terminal-container" id="ssh-page-terminal"></div>
        </div>
    `;

    const container = document.getElementById("ssh-page-terminal");
    const statusEl = app.querySelector(".ssh-status");
    const userInput = app.querySelector(".ssh-user-input");
    let currentUser = initialUser || null;
    let session = null;

    function connect(user) {
        if (session) session.cleanup();
        container.innerHTML = "";
        statusEl.className = "ssh-status ssh-status-connecting";
        statusEl.innerHTML = `<span class="ssh-status-dot"></span>Connecting...`;
        session = initSSHTerminal(container, statusEl, hostname, {
            user: user || undefined,
            onConnected(msg) {
                currentUser = msg.user;
                if (!userInput.value && msg.default_user) {
                    userInput.placeholder = msg.default_user;
                }
            },
        });
    }

    userInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
            e.preventDefault();
            const newUser = userInput.value.trim() || undefined;
            connect(newUser);
            // Update hash URL to reflect new user
            let hash = `ssh-${encodeURIComponent(hostname)}--${encodeURIComponent(ip)}`;
            if (newUser) hash += `--${encodeURIComponent(newUser)}`;
            history.replaceState(null, "", `#${hash}`);
        }
        e.stopPropagation();
    });

    connect(initialUser || undefined);

    document.getElementById("ssh-back-btn").addEventListener("click", () => {
        if (session) session.cleanup();
        document.body.classList.remove("ssh-fullpage");
    });

    // Cleanup on hash change (navigating away)
    function onHashChange() {
        if (!currentView().startsWith("ssh-")) {
            if (session) session.cleanup();
            document.body.classList.remove("ssh-fullpage");
            window.removeEventListener("hashchange", onHashChange);
        }
    }
    window.addEventListener("hashchange", onHashChange);
}

// --- Inventory Detail / Create / Tags ---

async function renderInventoryDetail(typeSlug, objId) {
    app.innerHTML = `<div class="loading">Loading...</div>`;
    await loadInventoryTypes();
    const typeConfig = getTypeConfig(typeSlug);
    if (!typeConfig) {
        app.innerHTML = `<div class="empty-state"><div>Unknown type</div></div>`;
        return;
    }

    const data = await apiJson(`/api/inventory/${typeSlug}/${objId}`);
    if (!data) return;

    const fields = typeConfig.fields || [];
    const d = data.data || {};
    const tags = data.tags || [];
    const canEdit = hasPermission(`inventory.${typeSlug}.edit`);
    const canDelete = hasPermission(`inventory.${typeSlug}.delete`);

    // Load all tags for tag editor
    const allTagsData = await apiJson("/api/inventory/tags");
    const allTags = (allTagsData && allTagsData.tags) || [];

    app.innerHTML = `
        <div class="page-header view-enter stagger-1">
            <div>
                <h2>${escapeHtml(typeConfig.label)} Detail</h2>
                <small>ID: ${objId}</small>
            </div>
            <div style="display:flex;gap:0.5rem;">
                ${canDelete ? `<button class="btn btn-danger btn-sm" id="delete-obj-btn">Delete</button>` : ""}
            </div>
        </div>

        <div class="view-enter stagger-2">
            <form id="detail-form" class="role-edit-form">
                ${fields.map(f => {
                    const val = d[f.name] || "";
                    const readonly = f.readonly ? "readonly" : "";
                    const disabled = f.readonly ? "disabled" : "";
                    if (f.type === "enum" && f.options) {
                        return `<div class="form-group">
                            <label>${escapeHtml(f.name.replace(/_/g, " ").replace(/\b\w/g, l => l.toUpperCase()))}${f.required ? " *" : ""}</label>
                            <select name="${escapeHtml(f.name)}" ${disabled}>
                                <option value="">--</option>
                                ${f.options.map(o => `<option value="${escapeHtml(o)}" ${val === o ? "selected" : ""}>${escapeHtml(o)}</option>`).join("")}
                            </select>
                        </div>`;
                    }
                    if (f.type === "text") {
                        return `<div class="form-group">
                            <label>${escapeHtml(f.name.replace(/_/g, " ").replace(/\b\w/g, l => l.toUpperCase()))}</label>
                            <textarea name="${escapeHtml(f.name)}" ${readonly} rows="4">${escapeHtml(String(val))}</textarea>
                        </div>`;
                    }
                    if (f.type === "secret") {
                        return `<div class="form-group">
                            <label>${escapeHtml(f.name.replace(/_/g, " ").replace(/\b\w/g, l => l.toUpperCase()))}</label>
                            <input type="password" name="${escapeHtml(f.name)}" value="${val ? "••••••••" : ""}" ${readonly} placeholder="${val ? "Stored" : "Empty"}">
                        </div>`;
                    }
                    return `<div class="form-group">
                        <label>${escapeHtml(f.name.replace(/_/g, " ").replace(/\b\w/g, l => l.toUpperCase()))}${f.required ? " *" : ""}</label>
                        <input type="text" name="${escapeHtml(f.name)}" value="${escapeHtml(Array.isArray(val) ? val.join(", ") : String(val))}" ${readonly}>
                    </div>`;
                }).join("")}

                <div class="form-group">
                    <label>Tags</label>
                    <div class="tags-editor" id="tags-editor">
                        ${tags.map(t => `<span class="tag-pill tag-removable" data-id="${t.id}" style="--tag-color:${t.color || '#4a5a70'}">${escapeHtml(t.name)} <span class="tag-remove">&times;</span></span>`).join(" ")}
                        <select id="add-tag-select" class="tag-add-select">
                            <option value="">+ Add tag</option>
                            ${allTags.filter(at => !tags.some(t => t.id === at.id)).map(at => `<option value="${at.id}">${escapeHtml(at.name)}</option>`).join("")}
                        </select>
                    </div>
                </div>

                ${canEdit ? `
                    <p class="form-error" id="detail-error" style="display:none;"></p>
                    <p class="form-success" id="detail-success" style="display:none;">Saved.</p>
                    <div class="form-actions">
                        <a href="#inventory-${typeSlug}" class="btn btn-ghost">Back</a>
                        <button type="submit" class="btn btn-primary">Save</button>
                    </div>
                ` : `<div class="form-actions"><a href="#inventory-${typeSlug}" class="btn btn-ghost">Back</a></div>`}
            </form>
        </div>
    `;

    // Save handler
    if (canEdit) {
        document.getElementById("detail-form").addEventListener("submit", async (e) => {
            e.preventDefault();
            const fd = new FormData(e.target);
            const updatedData = {};
            fields.forEach(f => {
                if (!f.readonly) {
                    let val = fd.get(f.name);
                    if (f.type === "secret" && val === "••••••••") return; // Don't update unchanged secrets
                    updatedData[f.name] = val || "";
                }
            });
            const errEl = document.getElementById("detail-error");
            const successEl = document.getElementById("detail-success");
            errEl.style.display = "none";
            successEl.style.display = "none";
            const res = await api(`/api/inventory/${typeSlug}/${objId}`, {
                method: "PUT",
                body: JSON.stringify({ data: updatedData }),
            });
            if (!res) return;
            if (res.ok) {
                successEl.style.display = "block";
            } else {
                const err = await res.json();
                errEl.textContent = err.detail || "Failed to save";
                errEl.style.display = "block";
            }
        });
    }

    // Delete handler
    const deleteBtn = document.getElementById("delete-obj-btn");
    if (deleteBtn) {
        deleteBtn.addEventListener("click", async () => {
            const yes = await confirm("Delete this object?", "This action cannot be undone.");
            if (!yes) return;
            const res = await api(`/api/inventory/${typeSlug}/${objId}`, { method: "DELETE" });
            if (res && res.ok) navigate(`inventory-${typeSlug}`);
        });
    }

    // Tag add
    document.getElementById("add-tag-select").addEventListener("change", async (e) => {
        const tagId = e.target.value;
        if (!tagId) return;
        await api(`/api/inventory/${typeSlug}/${objId}/tags`, {
            method: "POST",
            body: JSON.stringify({ tag_ids: [parseInt(tagId)] }),
        });
        renderInventoryDetail(typeSlug, objId);
    });

    // Tag remove
    document.querySelectorAll(".tag-remove").forEach(btn => {
        btn.addEventListener("click", async (e) => {
            e.stopPropagation();
            const tagId = btn.parentElement.dataset.id;
            await api(`/api/inventory/${typeSlug}/${objId}/tags/${tagId}`, { method: "DELETE" });
            renderInventoryDetail(typeSlug, objId);
        });
    });
}

async function renderInventoryCreate(typeSlug) {
    app.innerHTML = `<div class="loading">Loading...</div>`;
    await loadInventoryTypes();
    const typeConfig = getTypeConfig(typeSlug);
    if (!typeConfig) {
        app.innerHTML = `<div class="empty-state"><div>Unknown type</div></div>`;
        return;
    }

    const fields = typeConfig.fields || [];

    app.innerHTML = `
        <div class="page-header view-enter stagger-1">
            <h2>New ${escapeHtml(typeConfig.label)}</h2>
        </div>
        <div class="view-enter stagger-2">
            <form id="create-form" class="role-edit-form">
                ${fields.filter(f => !f.readonly).map(f => {
                    if (f.type === "enum" && f.options) {
                        return `<div class="form-group">
                            <label>${escapeHtml(f.name.replace(/_/g, " ").replace(/\b\w/g, l => l.toUpperCase()))}${f.required ? " *" : ""}</label>
                            <select name="${escapeHtml(f.name)}" ${f.required ? "required" : ""}>
                                <option value="">--</option>
                                ${f.options.map(o => `<option value="${escapeHtml(o)}" ${f.default === o ? "selected" : ""}>${escapeHtml(o)}</option>`).join("")}
                            </select>
                        </div>`;
                    }
                    if (f.type === "text") {
                        return `<div class="form-group">
                            <label>${escapeHtml(f.name.replace(/_/g, " ").replace(/\b\w/g, l => l.toUpperCase()))}${f.required ? " *" : ""}</label>
                            <textarea name="${escapeHtml(f.name)}" rows="4" ${f.required ? "required" : ""}></textarea>
                        </div>`;
                    }
                    if (f.type === "secret") {
                        return `<div class="form-group">
                            <label>${escapeHtml(f.name.replace(/_/g, " ").replace(/\b\w/g, l => l.toUpperCase()))}${f.required ? " *" : ""}</label>
                            <input type="password" name="${escapeHtml(f.name)}" ${f.required ? "required" : ""}>
                        </div>`;
                    }
                    return `<div class="form-group">
                        <label>${escapeHtml(f.name.replace(/_/g, " ").replace(/\b\w/g, l => l.toUpperCase()))}${f.required ? " *" : ""}</label>
                        <input type="text" name="${escapeHtml(f.name)}" value="${escapeHtml(f.default || "")}" ${f.required ? "required" : ""}>
                    </div>`;
                }).join("")}
                <p class="form-error" id="create-error" style="display:none;"></p>
                <div class="form-actions">
                    <a href="#inventory-${typeSlug}" class="btn btn-ghost">Cancel</a>
                    <button type="submit" class="btn btn-primary">Create</button>
                </div>
            </form>
        </div>
    `;

    document.getElementById("create-form").addEventListener("submit", async (e) => {
        e.preventDefault();
        const fd = new FormData(e.target);
        const data = {};
        fields.forEach(f => {
            if (!f.readonly) {
                data[f.name] = fd.get(f.name) || "";
            }
        });
        const res = await api(`/api/inventory/${typeSlug}`, {
            method: "POST",
            body: JSON.stringify({ data }),
        });
        if (!res) return;
        if (res.ok) {
            const created = await res.json();
            navigate(`inventory-${typeSlug}-${created.id}`);
        } else {
            const err = await res.json();
            const errEl = document.getElementById("create-error");
            errEl.textContent = err.detail || "Failed to create";
            errEl.style.display = "block";
        }
    });
}

// --- Users Management ---

async function renderUsers() {
    app.innerHTML = `<div class="loading">Loading users...</div>`;
    const [usersData, rolesData] = await Promise.all([
        apiJson("/api/users"),
        apiJson("/api/roles"),
    ]);
    if (!usersData) return;

    const users = usersData.users || [];
    const roles = (rolesData && rolesData.roles) || [];

    app.innerHTML = `
        <div class="page-header view-enter stagger-1">
            <h2>Users</h2>
            ${hasPermission("users.create") ? `<button class="btn btn-primary btn-sm" id="invite-btn">Invite User</button>` : ""}
        </div>
        <div class="view-enter stagger-2">
            ${users.length === 0 ? `
                <div class="empty-state">
                    <div class="empty-icon">&#9679;</div>
                    <div>No users found.</div>
                </div>
            ` : `
                <table class="data-table">
                    <thead>
                        <tr>
                            <th>Username</th>
                            <th>Display Name</th>
                            <th>Email</th>
                            <th>Role</th>
                            <th>Status</th>
                            <th>Last Login</th>
                            <th>Actions</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${users.map(u => `
                            <tr>
                                <td>${escapeHtml(u.username)}</td>
                                <td>${escapeHtml(u.display_name || "")}</td>
                                <td>${escapeHtml(u.email || "")}</td>
                                <td>${u.roles && u.roles.length ? u.roles.map(r => escapeHtml(r.name)).join(", ") : '<span class="badge badge-pending">none</span>'}</td>
                                <td>${u.is_active
                                    ? '<span class="badge badge-running">active</span>'
                                    : '<span class="badge badge-failed">inactive</span>'}</td>
                                <td>${u.last_login_at ? relativeTime(u.last_login_at) : "never"}</td>
                                <td class="instance-actions">
                                    ${hasPermission("users.edit") ? `<button class="btn btn-ghost btn-sm user-edit-btn" data-id="${u.id}">Edit</button>` : ""}
                                    ${hasPermission("users.edit") && u.id !== (currentUser && currentUser.id)
                                        ? `<button class="btn btn-danger btn-sm user-toggle-btn" data-id="${u.id}" data-active="${u.is_active}">${u.is_active ? "Deactivate" : "Activate"}</button>`
                                        : ""}
                                </td>
                            </tr>
                        `).join("")}
                    </tbody>
                </table>
            `}
        </div>
    `;

    // Invite button
    const inviteBtn = document.getElementById("invite-btn");
    if (inviteBtn) {
        inviteBtn.addEventListener("click", () => {
            const overlay = document.createElement("div");
            overlay.className = "confirm-overlay";
            overlay.innerHTML = `
                <div class="confirm-box input-modal">
                    <h4>Invite User</h4>
                    <form id="invite-form">
                        <div class="form-group">
                            <label>Username *</label>
                            <input type="text" name="username" required placeholder="Username">
                        </div>
                        <div class="form-group">
                            <label>Email *</label>
                            <input type="email" name="email" required placeholder="Email address">
                        </div>
                        <div class="form-group">
                            <label>Display Name</label>
                            <input type="text" name="display_name" placeholder="Display name">
                        </div>
                        <div class="form-group">
                            <label>Role</label>
                            <select name="role_id">
                                <option value="">-- No role --</option>
                                ${roles.map(r => `<option value="${r.id}">${escapeHtml(r.name)}</option>`).join("")}
                            </select>
                        </div>
                        <p class="form-error" id="invite-error" style="display:none;"></p>
                        <div class="actions">
                            <button type="button" class="btn" id="invite-cancel">Cancel</button>
                            <button type="submit" class="btn btn-primary">Send Invite</button>
                        </div>
                    </form>
                </div>
            `;
            document.body.appendChild(overlay);

            overlay.querySelector("#invite-cancel").onclick = () => overlay.remove();
            overlay.querySelector("#invite-form").addEventListener("submit", async (e) => {
                e.preventDefault();
                const fd = new FormData(e.target);
                const roleVal = fd.get("role_id");
                const body = {
                    username: fd.get("username"),
                    email: fd.get("email"),
                    display_name: fd.get("display_name") || undefined,
                    role_ids: roleVal ? [parseInt(roleVal)] : [],
                };
                const res = await api("/api/users/invite", {
                    method: "POST",
                    body: JSON.stringify(body),
                });
                if (!res) return;
                if (res.ok) {
                    const data = await res.json();
                    overlay.remove();
                    // Show invite link
                    const linkOverlay = document.createElement("div");
                    linkOverlay.className = "confirm-overlay";
                    linkOverlay.innerHTML = `
                        <div class="confirm-box">
                            <h4>Invite Sent</h4>
                            <p>Share this link with the user to complete registration:</p>
                            <div class="form-group">
                                <input type="text" value="${data.invite_url || (location.origin + '/#accept-invite-' + data.token)}" readonly style="font-family:var(--font-mono);font-size:0.8rem;" id="invite-link-input">
                            </div>
                            <div class="actions">
                                <button class="btn btn-primary" id="invite-copy-btn">Copy Link</button>
                                <button class="btn" id="invite-done-btn">Done</button>
                            </div>
                        </div>
                    `;
                    document.body.appendChild(linkOverlay);
                    linkOverlay.querySelector("#invite-copy-btn").addEventListener("click", () => {
                        const input = linkOverlay.querySelector("#invite-link-input");
                        input.select();
                        navigator.clipboard.writeText(input.value);
                    });
                    linkOverlay.querySelector("#invite-done-btn").addEventListener("click", () => {
                        linkOverlay.remove();
                        renderUsers();
                    });
                } else {
                    const err = await res.json();
                    const errEl = overlay.querySelector("#invite-error");
                    errEl.textContent = err.detail || "Failed to invite user";
                    errEl.style.display = "block";
                }
            });
        });
    }

    // Edit user buttons
    document.querySelectorAll(".user-edit-btn").forEach(btn => {
        btn.addEventListener("click", async () => {
            const userId = btn.dataset.id;
            const userData = await apiJson(`/api/users/${userId}`);
            if (!userData) return;
            const u = userData.user || userData;

            const overlay = document.createElement("div");
            overlay.className = "confirm-overlay";
            overlay.innerHTML = `
                <div class="confirm-box input-modal">
                    <h4>Edit User: ${escapeHtml(u.username)}</h4>
                    <form id="user-edit-form">
                        <div class="form-group">
                            <label>Display Name</label>
                            <input type="text" name="display_name" value="${escapeHtml(u.display_name || "")}" placeholder="Display name">
                        </div>
                        <div class="form-group">
                            <label>Email</label>
                            <input type="email" name="email" value="${escapeHtml(u.email || "")}" placeholder="Email">
                        </div>
                        <div class="form-group">
                            <label>Role</label>
                            <select name="role_id">
                                <option value="">-- No role --</option>
                                ${roles.map(r => `<option value="${r.id}" ${u.roles && u.roles.some(ur => ur.id === r.id) ? "selected" : ""}>${escapeHtml(r.name)}</option>`).join("")}
                            </select>
                        </div>
                        <p class="form-error" id="user-edit-error" style="display:none;"></p>
                        <div class="actions">
                            <button type="button" class="btn" id="user-edit-cancel">Cancel</button>
                            <button type="submit" class="btn btn-primary">Save</button>
                        </div>
                    </form>
                </div>
            `;
            document.body.appendChild(overlay);

            overlay.querySelector("#user-edit-cancel").onclick = () => overlay.remove();
            overlay.querySelector("#user-edit-form").addEventListener("submit", async (e) => {
                e.preventDefault();
                const fd = new FormData(e.target);
                const body = {
                    display_name: fd.get("display_name"),
                    email: fd.get("email"),
                };
                const res = await api(`/api/users/${userId}`, {
                    method: "PUT",
                    body: JSON.stringify(body),
                });
                if (!res) return;
                if (!res.ok) {
                    const err = await res.json();
                    const errEl = overlay.querySelector("#user-edit-error");
                    errEl.textContent = err.detail || "Failed to update user";
                    errEl.style.display = "block";
                    return;
                }
                // Assign role if changed
                const roleVal = fd.get("role_id");
                const roleIds = roleVal ? [parseInt(roleVal)] : [];
                const roleRes = await api(`/api/users/${userId}/roles`, {
                    method: "PUT",
                    body: JSON.stringify({ role_ids: roleIds }),
                });
                if (roleRes && !roleRes.ok) {
                    const err = await roleRes.json();
                    const errEl = overlay.querySelector("#user-edit-error");
                    errEl.textContent = err.detail || "Failed to assign role";
                    errEl.style.display = "block";
                    return;
                }
                overlay.remove();
                renderUsers();
            });
        });
    });

    // Toggle active/deactivate buttons
    document.querySelectorAll(".user-toggle-btn").forEach(btn => {
        btn.addEventListener("click", async () => {
            const userId = btn.dataset.id;
            const isActive = btn.dataset.active === "true";
            const yes = await confirm(
                `${isActive ? "Deactivate" : "Activate"} this user?`,
                isActive ? "The user will no longer be able to log in." : "The user will be able to log in again."
            );
            if (!yes) return;
            btn.setAttribute("aria-busy", "true");
            const res = await api(`/api/users/${userId}`, {
                method: "PUT",
                body: JSON.stringify({ is_active: !isActive }),
            });
            if (res && res.ok) {
                renderUsers();
            } else {
                btn.removeAttribute("aria-busy");
            }
        });
    });
}

// --- Roles Management ---

async function renderRoles() {
    app.innerHTML = `<div class="loading">Loading roles...</div>`;
    const data = await apiJson("/api/roles");
    if (!data) return;

    const roles = data.roles || [];

    app.innerHTML = `
        <div class="page-header view-enter stagger-1">
            <h2>Roles</h2>
            ${hasPermission("roles.create") ? `<button class="btn btn-primary btn-sm" id="create-role-btn">Create Role</button>` : ""}
        </div>
        <div class="view-enter stagger-2">
            ${roles.length === 0 ? `
                <div class="empty-state">
                    <div class="empty-icon">&#9670;</div>
                    <div>No roles defined yet.</div>
                </div>
            ` : `
                <table class="data-table">
                    <thead>
                        <tr>
                            <th>Name</th>
                            <th>Description</th>
                            <th>Users</th>
                            <th>Permissions</th>
                            <th>Actions</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${roles.map(r => `
                            <tr>
                                <td><strong>${escapeHtml(r.name)}</strong></td>
                                <td>${escapeHtml(r.description || "")}</td>
                                <td>${r.user_count !== undefined ? r.user_count : "-"}</td>
                                <td>${r.permission_count !== undefined ? r.permission_count : (r.permissions ? r.permissions.length : "-")}</td>
                                <td class="instance-actions">
                                    ${hasPermission("roles.edit") ? `<button class="btn btn-ghost btn-sm role-edit-btn" data-id="${r.id}">Edit</button>` : ""}
                                    ${hasPermission("roles.delete") && !r.is_system ? `<button class="btn btn-danger btn-sm role-delete-btn" data-id="${r.id}" data-name="${escapeHtml(r.name)}">Delete</button>` : ""}
                                </td>
                            </tr>
                        `).join("")}
                    </tbody>
                </table>
            `}
        </div>
    `;

    // Create role
    const createBtn = document.getElementById("create-role-btn");
    if (createBtn) {
        createBtn.addEventListener("click", () => {
            navigate("role-edit-new");
        });
    }

    // Edit role buttons
    document.querySelectorAll(".role-edit-btn").forEach(btn => {
        btn.addEventListener("click", () => {
            navigate("role-edit-" + btn.dataset.id);
        });
    });

    // Delete role buttons
    document.querySelectorAll(".role-delete-btn").forEach(btn => {
        btn.addEventListener("click", async () => {
            const roleId = btn.dataset.id;
            const roleName = btn.dataset.name;
            const yes = await confirm(`Delete role "${roleName}"?`, "Users with this role will lose their role assignment.");
            if (!yes) return;
            btn.setAttribute("aria-busy", "true");
            const res = await api(`/api/roles/${roleId}`, { method: "DELETE" });
            if (res && res.ok) {
                renderRoles();
            } else {
                btn.removeAttribute("aria-busy");
            }
        });
    });
}

// --- Role Edit ---

async function renderRoleEdit(id) {
    app.innerHTML = `<div class="loading">Loading role...</div>`;
    const isNew = id === "new";

    const [permData, roleData] = await Promise.all([
        apiJson("/api/roles/permissions"),
        isNew ? Promise.resolve(null) : apiJson(`/api/roles/${id}`),
    ]);
    if (!permData) return;

    // permData.permissions is grouped by category: { "instances": [{id, codename, label}, ...], ... }
    const groupedPerms = permData.permissions || {};
    const role = roleData ? (roleData.role || roleData) : { name: "", description: "", permissions: [] };
    const rolePermissions = new Set((role.permissions || []).map(p => typeof p === "string" ? p : p.codename));

    // Build a codename->id map for submission
    const permIdMap = {};
    const categories = {};
    Object.entries(groupedPerms).forEach(([cat, perms]) => {
        categories[cat] = [];
        perms.forEach(p => {
            permIdMap[p.codename] = p.id;
            categories[cat].push({ codename: p.codename, label: p.label || p.codename, id: p.id });
        });
    });

    app.innerHTML = `
        <div class="page-header view-enter stagger-1">
            <h2>${isNew ? "Create Role" : "Edit Role"}</h2>
        </div>
        <div class="view-enter stagger-2">
            <form id="role-form" class="role-edit-form">
                <div class="form-group">
                    <label>Role Name *</label>
                    <input type="text" name="name" value="${escapeHtml(role.name)}" required placeholder="e.g. Operator">
                </div>
                <div class="form-group">
                    <label>Description</label>
                    <input type="text" name="description" value="${escapeHtml(role.description || "")}" placeholder="Brief description of this role">
                </div>
                <div class="form-group">
                    <label>Permissions</label>
                    <div class="permissions-grid">
                        ${Object.entries(categories).sort(([a], [b]) => a.localeCompare(b)).map(([cat, perms]) => `
                            <div class="permission-category">
                                <div class="permission-category-header">${escapeHtml(cat)}</div>
                                ${perms.map(p => `
                                    <label class="permission-checkbox">
                                        <input type="checkbox" name="permissions" value="${escapeHtml(p.codename)}" ${rolePermissions.has(p.codename) ? "checked" : ""}>
                                        <span>${escapeHtml(p.label)}</span>
                                    </label>
                                `).join("")}
                            </div>
                        `).join("")}
                    </div>
                </div>
                <p class="form-error" id="role-error" style="display:none;"></p>
                <div class="form-actions">
                    <a href="#roles" class="btn btn-ghost">Cancel</a>
                    <button type="submit" class="btn btn-primary">${isNew ? "Create" : "Save"}</button>
                </div>
            </form>
        </div>
        <a href="#roles" class="back-link view-enter stagger-3">&#8592; Back to Roles</a>
    `;

    document.getElementById("role-form").addEventListener("submit", async (e) => {
        e.preventDefault();
        const fd = new FormData(e.target);
        const selectedPerms = fd.getAll("permissions");
        const body = {
            name: fd.get("name"),
            description: fd.get("description"),
            permission_ids: selectedPerms.map(codename => permIdMap[codename]).filter(Boolean),
        };

        const url = isNew ? "/api/roles" : `/api/roles/${id}`;
        const method = isNew ? "POST" : "PUT";
        const res = await api(url, { method, body: JSON.stringify(body) });
        if (!res) return;
        if (res.ok) {
            navigate("roles");
        } else {
            const err = await res.json();
            const errEl = document.getElementById("role-error");
            errEl.textContent = err.detail || "Failed to save role";
            errEl.style.display = "block";
        }
    });
}

// --- Profile ---

async function renderProfile() {
    app.innerHTML = `<div class="loading">Loading profile...</div>`;
    const data = await apiJson("/api/auth/me");
    if (!data) return;

    const user = data;

    app.innerHTML = `
        <div class="page-header view-enter stagger-1">
            <h2>Profile</h2>
        </div>
        <div class="view-enter stagger-2">
            <div class="profile-section">
                <h3>Account Details</h3>
                <form id="profile-form">
                    <div class="form-group">
                        <label>Username</label>
                        <input type="text" value="${escapeHtml(user.username)}" disabled>
                    </div>
                    <div class="form-group">
                        <label>Display Name</label>
                        <input type="text" name="display_name" value="${escapeHtml(user.display_name || "")}" placeholder="Your display name">
                    </div>
                    <div class="form-group">
                        <label>Email</label>
                        <input type="email" name="email" value="${escapeHtml(user.email || "")}" placeholder="Email address">
                    </div>
                    <p class="form-error" id="profile-error" style="display:none;"></p>
                    <p class="form-success" id="profile-success" style="display:none;">Profile updated.</p>
                    <div class="form-actions">
                        <button type="submit" class="btn btn-primary">Save Changes</button>
                    </div>
                </form>
            </div>

            <div class="profile-section" style="margin-top:2rem;">
                <h3>SSH Key</h3>
                <div id="ssh-key-section">
                    ${user.ssh_public_key
                        ? `<div>
                            <textarea class="ssh-key-display" readonly>${escapeHtml(user.ssh_public_key)}</textarea>
                            <div class="btn-group" style="margin-top:0.75rem;">
                                <button class="btn btn-danger btn-sm" id="ssh-key-remove">Remove Key</button>
                                <button class="btn btn-sm" id="ssh-key-regenerate">Regenerate</button>
                            </div>
                           </div>`
                        : `<p style="margin-bottom:0.75rem;">No SSH key configured. Generate one to use with service deployments.</p>
                           <button class="btn btn-primary btn-sm" id="ssh-key-generate">Generate SSH Key</button>`
                    }
                </div>
            </div>

            <div class="profile-section" style="margin-top:2rem;">
                <h3>Change Password</h3>
                <form id="password-form">
                    <div class="form-group">
                        <label>Current Password</label>
                        <input type="password" name="current_password" required autocomplete="current-password">
                    </div>
                    <div class="form-group">
                        <label>New Password</label>
                        <input type="password" name="new_password" required autocomplete="new-password">
                    </div>
                    <div class="form-group">
                        <label>Confirm New Password</label>
                        <input type="password" name="confirm_password" required autocomplete="new-password">
                    </div>
                    <p class="form-error" id="password-error" style="display:none;"></p>
                    <p class="form-success" id="password-success" style="display:none;">Password changed successfully.</p>
                    <div class="form-actions">
                        <button type="submit" class="btn btn-primary">Change Password</button>
                    </div>
                </form>
            </div>
        </div>
    `;

    // Profile update
    document.getElementById("profile-form").addEventListener("submit", async (e) => {
        e.preventDefault();
        const fd = new FormData(e.target);
        const errEl = document.getElementById("profile-error");
        const successEl = document.getElementById("profile-success");
        errEl.style.display = "none";
        successEl.style.display = "none";

        const res = await api("/api/auth/me", {
            method: "PUT",
            body: JSON.stringify({
                display_name: fd.get("display_name"),
                email: fd.get("email"),
            }),
        });
        if (!res) return;
        if (res.ok) {
            const updated = await res.json();
            const u = updated.user || updated;
            if (currentUser) {
                currentUser.display_name = u.display_name || currentUser.display_name;
                currentUser.email = u.email || currentUser.email;
                setCurrentUser(currentUser);
            }
            successEl.style.display = "block";
        } else {
            const err = await res.json();
            errEl.textContent = err.detail || "Failed to update profile";
            errEl.style.display = "block";
        }
    });

    // Password change
    document.getElementById("password-form").addEventListener("submit", async (e) => {
        e.preventDefault();
        const fd = new FormData(e.target);
        const errEl = document.getElementById("password-error");
        const successEl = document.getElementById("password-success");
        errEl.style.display = "none";
        successEl.style.display = "none";

        const newPass = fd.get("new_password");
        const confirmPass = fd.get("confirm_password");
        if (newPass !== confirmPass) {
            errEl.textContent = "Passwords do not match";
            errEl.style.display = "block";
            return;
        }

        const res = await api("/api/auth/change-password", {
            method: "POST",
            body: JSON.stringify({
                current_password: fd.get("current_password"),
                new_password: newPass,
            }),
        });
        if (!res) return;
        if (res.ok) {
            successEl.style.display = "block";
            e.target.reset();
        } else {
            const err = await res.json();
            errEl.textContent = err.detail || "Failed to change password";
            errEl.style.display = "block";
        }
    });

    // SSH key handlers
    async function handleGenerateKey() {
        const res = await api("/api/auth/me/ssh-key", { method: "POST" });
        if (!res || !res.ok) return;
        const data = await res.json();
        // Show one-time private key modal
        const keyOverlay = document.createElement("div");
        keyOverlay.className = "confirm-overlay";
        keyOverlay.innerHTML = `
            <div class="confirm-box input-modal">
                <h4>SSH Key Generated</h4>
                <p>Save your private key now — it will not be shown again.</p>
                <textarea class="ssh-key-display" readonly style="height:200px;margin-bottom:0.75rem;">${escapeHtml(data.private_key)}</textarea>
                <div class="actions">
                    <button class="btn btn-sm" id="ssh-download-key">Download Private Key</button>
                    <button class="btn btn-primary btn-sm" id="ssh-key-done">Done</button>
                </div>
            </div>
        `;
        document.body.appendChild(keyOverlay);
        keyOverlay.querySelector("#ssh-download-key").onclick = () => {
            const blob = new Blob([data.private_key], { type: "text/plain" });
            const a = document.createElement("a");
            a.href = URL.createObjectURL(blob);
            a.download = "cloudlab_ed25519";
            a.click();
            URL.revokeObjectURL(a.href);
        };
        keyOverlay.querySelector("#ssh-key-done").onclick = () => {
            keyOverlay.remove();
            renderProfile();
        };
    }

    async function handleRemoveKey() {
        const res = await api("/api/auth/me/ssh-key", { method: "DELETE" });
        if (res && res.ok) renderProfile();
    }

    const genBtn = document.getElementById("ssh-key-generate");
    if (genBtn) genBtn.onclick = handleGenerateKey;

    const removeBtn = document.getElementById("ssh-key-remove");
    if (removeBtn) removeBtn.onclick = handleRemoveKey;

    const regenBtn = document.getElementById("ssh-key-regenerate");
    if (regenBtn) regenBtn.onclick = handleGenerateKey;
}

// --- Audit Log ---

async function renderAuditLog() {
    app.innerHTML = `<div class="loading">Loading audit log...</div>`;

    let page = 1;
    let filterAction = "";
    let filterUsername = "";

    async function loadAuditPage() {
        const params = new URLSearchParams({ page, per_page: 50 });
        if (filterAction) params.set("action", filterAction);
        if (filterUsername) params.set("username", filterUsername);

        const data = await apiJson(`/api/audit?${params}`);
        if (!data) return;

        const entries = data.entries || data.logs || [];
        const totalPages = data.total_pages || Math.ceil((data.total || 1) / (data.per_page || 50)) || 1;
        const total = data.total || entries.length;

        app.innerHTML = `
            <div class="page-header view-enter stagger-1">
                <h2>Audit Log</h2>
                <small>${total} total entries</small>
            </div>
            <div class="view-enter stagger-2">
                <div class="audit-filters">
                    <div class="form-group" style="display:inline-block;margin-right:1rem;">
                        <label>Action</label>
                        <input type="text" id="filter-action" value="${escapeHtml(filterAction)}" placeholder="Filter by action...">
                    </div>
                    <div class="form-group" style="display:inline-block;margin-right:1rem;">
                        <label>Username</label>
                        <input type="text" id="filter-username" value="${escapeHtml(filterUsername)}" placeholder="Filter by user...">
                    </div>
                    <button class="btn btn-primary btn-sm" id="filter-apply-btn" style="vertical-align:bottom;">Apply</button>
                    <button class="btn btn-ghost btn-sm" id="filter-clear-btn" style="vertical-align:bottom;">Clear</button>
                </div>
                ${entries.length === 0 ? `
                    <div class="empty-state">
                        <div class="empty-icon">&#9656;</div>
                        <div>No audit entries found.</div>
                    </div>
                ` : `
                    <table class="data-table">
                        <thead>
                            <tr>
                                <th>Timestamp</th>
                                <th>User</th>
                                <th>Action</th>
                                <th>Resource</th>
                                <th>Details</th>
                                <th>IP</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${entries.map(e => `
                                <tr>
                                    <td>${e.created_at ? new Date(e.created_at).toLocaleString() : ""}</td>
                                    <td>${escapeHtml(e.username || "")}</td>
                                    <td><span class="badge badge-${e.action === 'error' ? 'failed' : 'pending'}">${escapeHtml(e.action || "")}</span></td>
                                    <td>${escapeHtml(e.resource || "")}</td>
                                    <td class="audit-details">${escapeHtml(typeof e.details === "object" ? JSON.stringify(e.details) : (e.details || ""))}</td>
                                    <td style="font-family:var(--font-mono);font-size:0.8rem;">${escapeHtml(e.ip_address || "")}</td>
                                </tr>
                            `).join("")}
                        </tbody>
                    </table>
                    <div class="pagination">
                        ${page > 1 ? `<button class="btn btn-ghost btn-sm" id="page-prev">Previous</button>` : ""}
                        <span class="pagination-info">Page ${page} of ${totalPages}</span>
                        ${page < totalPages ? `<button class="btn btn-ghost btn-sm" id="page-next">Next</button>` : ""}
                    </div>
                `}
            </div>
        `;

        // Filter handlers
        document.getElementById("filter-apply-btn").addEventListener("click", () => {
            filterAction = document.getElementById("filter-action").value.trim();
            filterUsername = document.getElementById("filter-username").value.trim();
            page = 1;
            loadAuditPage();
        });

        document.getElementById("filter-clear-btn").addEventListener("click", () => {
            filterAction = "";
            filterUsername = "";
            page = 1;
            loadAuditPage();
        });

        // Pagination
        const prevBtn = document.getElementById("page-prev");
        if (prevBtn) prevBtn.addEventListener("click", () => { page--; loadAuditPage(); });
        const nextBtn = document.getElementById("page-next");
        if (nextBtn) nextBtn.addEventListener("click", () => { page++; loadAuditPage(); });
    }

    await loadAuditPage();
}

// --- Accept Invite (no auth required) ---

async function renderAcceptInvite(token) {
    app.innerHTML = `
        <div class="auth-container view-enter">
            <div class="auth-card">
                <h2>Welcome to CloudLab</h2>
                <p class="auth-subtitle">Set your password to complete registration</p>
                <form id="accept-form">
                    <div class="form-group">
                        <label for="accept-pass">Password</label>
                        <input id="accept-pass" name="password" type="password" required autocomplete="new-password">
                    </div>
                    <div class="form-group">
                        <label for="accept-confirm">Confirm Password</label>
                        <input id="accept-confirm" name="confirm_password" type="password" required autocomplete="new-password">
                    </div>
                    <button type="submit" class="btn btn-primary" style="width:100%;margin-top:0.5rem;">Set Password</button>
                </form>
                <p class="form-error" id="accept-error" style="display:none;"></p>
                <p class="form-success" id="accept-success" style="display:none;"></p>
            </div>
        </div>
    `;

    document.getElementById("accept-form").addEventListener("submit", async (e) => {
        e.preventDefault();
        const fd = new FormData(e.target);
        const errEl = document.getElementById("accept-error");
        const successEl = document.getElementById("accept-success");
        errEl.style.display = "none";
        successEl.style.display = "none";

        const password = fd.get("password");
        const confirmPassword = fd.get("confirm_password");
        if (password !== confirmPassword) {
            errEl.textContent = "Passwords do not match";
            errEl.style.display = "block";
            return;
        }

        const res = await fetch("/api/auth/accept-invite", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ token, password }),
        });
        if (res.ok) {
            const data = await res.json();
            successEl.textContent = "Account activated! Redirecting to login...";
            successEl.style.display = "block";
            if (data.access_token) {
                setToken(data.access_token);
                if (data.user) {
                    setCurrentUser({
                        id: data.user.id,
                        username: data.user.username,
                        display_name: data.user.display_name,
                        email: data.user.email,
                        permissions: data.permissions || [],
                    });
                }
                setTimeout(() => navigate("dashboard"), 1000);
            } else {
                setTimeout(() => navigate("login"), 1500);
            }
        } else {
            const err = await res.json();
            errEl.textContent = err.detail || "Failed to accept invite. The link may have expired.";
            errEl.style.display = "block";
        }
    });
}

// --- Forgot Password (no auth required) ---

async function renderForgotPassword() {
    app.innerHTML = `
        <div class="auth-container view-enter">
            <div class="auth-card">
                <h2>Reset Password</h2>
                <p class="auth-subtitle">Enter your email to receive a password reset link</p>
                <form id="forgot-form">
                    <div class="form-group">
                        <label for="forgot-email">Email</label>
                        <input id="forgot-email" name="email" type="email" required placeholder="Your email address">
                    </div>
                    <button type="submit" class="btn btn-primary" style="width:100%;margin-top:0.5rem;">Send Reset Link</button>
                </form>
                <p class="form-error" id="forgot-error" style="display:none;"></p>
                <p class="form-success" id="forgot-success" style="display:none;"></p>
                <p class="auth-link"><a href="#login">Back to Login</a></p>
            </div>
        </div>
    `;

    document.getElementById("forgot-form").addEventListener("submit", async (e) => {
        e.preventDefault();
        const fd = new FormData(e.target);
        const errEl = document.getElementById("forgot-error");
        const successEl = document.getElementById("forgot-success");
        errEl.style.display = "none";
        successEl.style.display = "none";

        const res = await fetch("/api/auth/forgot-password", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ email: fd.get("email") }),
        });
        if (res.ok) {
            successEl.textContent = "If an account with that email exists, a reset link has been sent.";
            successEl.style.display = "block";
            e.target.reset();
        } else {
            const err = await res.json();
            errEl.textContent = err.detail || "Failed to send reset email";
            errEl.style.display = "block";
        }
    });
}

// --- Reset Password (no auth required) ---

async function renderResetPassword(token) {
    app.innerHTML = `
        <div class="auth-container view-enter">
            <div class="auth-card">
                <h2>Set New Password</h2>
                <p class="auth-subtitle">Enter your new password below</p>
                <form id="reset-form">
                    <div class="form-group">
                        <label for="reset-pass">New Password</label>
                        <input id="reset-pass" name="password" type="password" required autocomplete="new-password">
                    </div>
                    <div class="form-group">
                        <label for="reset-confirm">Confirm Password</label>
                        <input id="reset-confirm" name="confirm_password" type="password" required autocomplete="new-password">
                    </div>
                    <button type="submit" class="btn btn-primary" style="width:100%;margin-top:0.5rem;">Reset Password</button>
                </form>
                <p class="form-error" id="reset-error" style="display:none;"></p>
                <p class="form-success" id="reset-success" style="display:none;"></p>
                <p class="auth-link"><a href="#login">Back to Login</a></p>
            </div>
        </div>
    `;

    document.getElementById("reset-form").addEventListener("submit", async (e) => {
        e.preventDefault();
        const fd = new FormData(e.target);
        const errEl = document.getElementById("reset-error");
        const successEl = document.getElementById("reset-success");
        errEl.style.display = "none";
        successEl.style.display = "none";

        const password = fd.get("password");
        const confirmPassword = fd.get("confirm_password");
        if (password !== confirmPassword) {
            errEl.textContent = "Passwords do not match";
            errEl.style.display = "block";
            return;
        }

        const res = await fetch("/api/auth/reset-password", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ token, password }),
        });
        if (res.ok) {
            successEl.textContent = "Password reset successfully! Redirecting to login...";
            successEl.style.display = "block";
            setTimeout(() => navigate("login"), 1500);
        } else {
            const err = await res.json();
            errEl.textContent = err.detail || "Failed to reset password. The link may have expired.";
            errEl.style.display = "block";
        }
    });
}

// --- Costs ---

async function renderCosts() {
    app.innerHTML = `<div class="loading">Loading cost data...</div>`;

    const [costData, tagData, regionData] = await Promise.all([
        apiJson("/api/costs"),
        apiJson("/api/costs/by-tag"),
        apiJson("/api/costs/by-region"),
    ]);

    if (!costData) return;

    const instances = costData.instances || [];
    const tags = (tagData && tagData.tags) || [];
    const regions = (regionData && regionData.regions) || [];
    const account = costData.account || {};
    const showRefresh = hasPermission("costs.refresh");
    const sourceLabel = costData.source === "playbook" ? "Vultr API" : "Computed from cache";

    app.innerHTML = `
        <div class="page-header view-enter stagger-1">
            <h2>Costs</h2>
            <div style="display:flex;gap:8px;align-items:center">
                <span class="badge badge-neutral" style="font-size:11px">${escapeHtml(sourceLabel)}</span>
                ${costData.cached_at ? `<span style="font-size:11px;opacity:0.5">Updated ${relativeTime(costData.cached_at)}</span>` : ""}
                ${showRefresh ? `<button class="btn btn-primary btn-sm" id="cost-refresh-btn">Refresh</button>` : ""}
            </div>
        </div>

        <div class="stat-grid view-enter stagger-2">
            <div class="stat-card accent-amber">
                <div class="stat-value">$${parseFloat(costData.total_monthly_cost || 0).toFixed(2)}</div>
                <div class="stat-label">Monthly Cost</div>
            </div>
            <div class="stat-card accent-blue">
                <div class="stat-value">${instances.length}</div>
                <div class="stat-label">Active Instances</div>
            </div>
            <div class="stat-card accent-cyan">
                <div class="stat-value">$${parseFloat(account.pending_charges || 0).toFixed(2)}</div>
                <div class="stat-label">Pending Charges</div>
            </div>
            <div class="stat-card accent-green">
                <div class="stat-value">$${Math.abs(parseFloat(account.balance || 0)).toFixed(2)}</div>
                <div class="stat-label">Account Balance</div>
            </div>
        </div>

        ${tags.length > 0 ? `
        <div class="view-enter stagger-3">
            <div class="section-label">Cost by Tag</div>
            <p style="font-size:11px;opacity:0.5;margin:0 0 8px">Instances with multiple tags are counted under each tag.</p>
            <div class="table-wrapper">
                <table class="data-table">
                    <thead><tr><th>Tag</th><th>Instances</th><th>Monthly Cost</th></tr></thead>
                    <tbody>
                        ${tags.map(t => `<tr>
                            <td><span class="badge badge-neutral">${escapeHtml(t.tag)}</span></td>
                            <td>${t.instance_count}</td>
                            <td>$${parseFloat(t.monthly_cost).toFixed(2)}</td>
                        </tr>`).join("")}
                    </tbody>
                </table>
            </div>
        </div>
        ` : ""}

        ${regions.length > 0 ? `
        <div class="view-enter stagger-4">
            <div class="section-label">Cost by Region</div>
            <div class="table-wrapper">
                <table class="data-table">
                    <thead><tr><th>Region</th><th>Instances</th><th>Monthly Cost</th></tr></thead>
                    <tbody>
                        ${regions.map(r => `<tr>
                            <td>${escapeHtml(r.region)}</td>
                            <td>${r.instance_count}</td>
                            <td>$${parseFloat(r.monthly_cost).toFixed(2)}</td>
                        </tr>`).join("")}
                    </tbody>
                </table>
            </div>
        </div>
        ` : ""}

        <div class="view-enter stagger-5">
            <div class="section-label">Per-Instance Breakdown</div>
            <div class="table-wrapper">
                <table class="data-table">
                    <thead><tr><th>Label</th><th>Plan</th><th>Region</th><th>Tags</th><th>Status</th><th>Monthly</th><th>Hourly</th></tr></thead>
                    <tbody>
                        ${instances.length === 0 ? `<tr><td colspan="7" style="text-align:center;opacity:0.5">No instances found</td></tr>` :
                        instances.sort((a, b) => parseFloat(b.monthly_cost) - parseFloat(a.monthly_cost)).map(inst => `<tr>
                            <td><strong>${escapeHtml(inst.label)}</strong><div style="font-size:11px;opacity:0.5">${escapeHtml(inst.hostname || "")}</div></td>
                            <td><code>${escapeHtml(inst.plan)}</code></td>
                            <td>${escapeHtml(inst.region)}</td>
                            <td>${(inst.tags || []).map(t => `<span class="badge badge-neutral" style="margin:1px">${escapeHtml(t)}</span>`).join(" ")}</td>
                            <td>${badge(inst.power_status)}</td>
                            <td>$${parseFloat(inst.monthly_cost).toFixed(2)}</td>
                            <td>$${parseFloat(inst.hourly_cost).toFixed(4)}</td>
                        </tr>`).join("")}
                    </tbody>
                </table>
            </div>
        </div>
    `;

    if (showRefresh) {
        document.getElementById("cost-refresh-btn").addEventListener("click", async () => {
            const res = await apiJson("/api/costs/refresh", { method: "POST" });
            if (res) navigate("job-" + res.job_id);
        });
    }
}

// --- Main render ---

async function render() {
    updateNavVisibility();
    loadCurrentUser();
    updateNavUser();
    updateNavPermissions();

    const view = currentView();

    // Public views that don't need auth or setup check
    const publicViews = ["forgot-password"];
    const isAcceptInvite = view.startsWith("accept-invite-");
    const isResetPassword = view.startsWith("reset-password-");

    if (isAcceptInvite) {
        const token = view.replace("accept-invite-", "");
        return renderAcceptInvite(token);
    }
    if (isResetPassword) {
        const token = view.replace("reset-password-", "");
        return renderResetPassword(token);
    }
    if (view === "forgot-password") {
        return renderForgotPassword();
    }

    const statusRes = await fetch("/api/auth/status");
    const statusData = await statusRes.json();

    if (!statusData.setup_complete) {
        navigate("setup");
        await renderSetup();
        return;
    }

    const token = getToken();

    if (!token && view !== "login" && view !== "setup") {
        navigate("login");
        await renderLogin();
        return;
    }

    // Fetch current user and permissions from server (keeps nav in sync with role changes)
    if (token) {
        try {
            const meData = await apiJson("/api/auth/me");
            if (meData) {
                const u = meData.user || meData;
                setCurrentUser({
                    id: u.id,
                    username: u.username,
                    display_name: u.display_name,
                    email: u.email,
                    permissions: u.permissions || meData.permissions || [],
                });
            }
        } catch (e) { /* ignore */ }
    }

    // Load inventory types for nav
    await loadInventoryTypes();

    // Highlight active nav
    document.querySelectorAll("[data-nav]").forEach(a => {
        const href = a.getAttribute("href");
        if (href === "#inventory") {
            a.classList.toggle("active", view === "inventory" || view.startsWith("inventory-") || view === "tags");
        } else {
            a.classList.toggle("active", href === "#" + view);
        }
    });

    if (view === "login") return renderLogin();
    if (view === "setup") return renderSetup();
    if (view === "dashboard") return renderDashboard();
    if (view === "instances") return renderInstances();
    if (view === "services") return renderServices();
    if (view === "jobs") return renderJobs();
    if (view === "costs") return renderCosts();
    if (view === "tags") return renderInventory("tags");
    if (view.startsWith("job-")) return renderJobDetail(view.replace("job-", ""));
    if (view.startsWith("service-config-")) return renderServiceConfig(view.replace("service-config-", ""));
    if (view.startsWith("service-files-")) return renderServiceFiles(view.replace("service-files-", ""));
    if (view.startsWith("ssh-")) {
        const parts = view.replace("ssh-", "").split("--");
        const sshHostname = decodeURIComponent(parts[0]);
        const sshIp = decodeURIComponent(parts[1] || "");
        const sshUser = parts[2] ? decodeURIComponent(parts[2]) : undefined;
        return renderSSHPage(sshHostname, sshIp, sshUser);
    }
    // Inventory routes: inventory, inventory-{slug}, inventory-{slug}-new, inventory-{slug}-{id}
    if (view === "inventory") return renderInventory();
    if (view.startsWith("inventory-")) {
        const rest = view.replace("inventory-", "");
        // Check for "new" suffix
        const newMatch = rest.match(/^(.+)-new$/);
        if (newMatch) return renderInventoryCreate(newMatch[1]);
        // Check for numeric ID suffix
        const detailMatch = rest.match(/^(.+)-(\d+)$/);
        if (detailMatch) return renderInventoryDetail(detailMatch[1], parseInt(detailMatch[2]));
        // Otherwise it's a sub-tab within inventory hub
        return renderInventory(rest);
    }
    if (view === "users") return renderUsers();
    if (view === "roles") return renderRoles();
    if (view.startsWith("role-edit-")) return renderRoleEdit(view.replace("role-edit-", ""));
    if (view === "audit") return renderAuditLog();
    if (view === "profile") return renderProfile();

    return renderDashboard();
}

// Initial render
render();
