// Automations (tramo) list/runs/settings page. SDK-surface imports (api,
// PageTopbar, Pill, useToast, router hooks) come from 'serverkit-sdk' —
// externalized to the panel's singletons at build time; Button/Input/Label/
// Modal/ConfirmDialog/EmptyState are local stand-ins rendering the same host
// design-system classes (see ./primitives.jsx). Styles are injected once by
// runtime-entry.jsx (?inline), so there is no stylesheet import here.
import { useCallback, useEffect, useState } from 'react';
import {
    Workflow, RefreshCw, Plus, Trash2, Rocket, Pencil, Play, LayoutTemplate,
    Server, Power, KeyRound, CheckCircle2, X, Send, Github, MessageSquare,
    Zap, MousePointerClick, Clock, Webhook, Check, Search, Star,
    Upload, FileJson,
} from 'lucide-react';
import { api, PageTopbar, Pill, useToast, useParams, useNavigate } from 'serverkit-sdk';
import { Button, Input, Label, Modal, ConfirmDialog, EmptyState } from './primitives.jsx';

// Route-driven tabs (manifest maps /automations and /automations/:tab here).
const TABS = [
    { slug: 'workflows', to: '/automations', label: 'Workflows', end: true },
    { slug: 'templates', to: '/automations/templates', label: 'Templates' },
    { slug: 'runs', to: '/automations/runs', label: 'Runs' },
    { slug: 'settings', to: '/automations/settings', label: 'Settings' },
];
const VALID_TABS = TABS.map((t) => t.slug);

// Favorited template ids live in the browser for now (per-device). A server-side
// favorites store can replace this later without touching the card UI.
const FAVORITES_KEY = 'tramo:favorite-templates';
const readFavorites = () => {
    try {
        const raw = JSON.parse(localStorage.getItem(FAVORITES_KEY) || '[]');
        return new Set(Array.isArray(raw) ? raw : []);
    } catch {
        return new Set();
    }
};

// Presentation for the starter templates (icon + accent + tags). Keyed by the
// backend template id; unknown ids fall back to a neutral card so new templates
// still render cleanly.
const TEMPLATE_META = {
    'backup-failed-telegram': { Icon: Send, brand: 'telegram', tags: ['Backups', 'Telegram'] },
    'nightly-health-github': { Icon: Github, brand: 'github', tags: ['Schedule', 'GitHub'] },
    'panel-event-discord': { Icon: MessageSquare, brand: 'discord', tags: ['Events', 'Discord'] },
};
const DEFAULT_TEMPLATE_META = { Icon: Zap, brand: 'default', tags: [] };

// Trigger choices for a new workflow. Each seeds a valid builtin tramo trigger
// node so the editor opens with the trigger already placed. Panel events arrive
// at a webhook-trigger on the /sk/events path (the events bridge posts there),
// so no custom node type is needed.
const TRIGGERS = [
    {
        id: 'manual', Icon: MousePointerClick, title: 'Manually trigger',
        subtitle: 'Run it on demand from the Automations page',
        node: () => ({ id: 'trigger', type: 'manual-trigger', position: { x: 80, y: 120 }, config: {} }),
    },
    {
        id: 'schedule', Icon: Clock, title: 'On a schedule',
        subtitle: 'Run on a cron schedule, e.g. every night',
        node: () => ({ id: 'trigger', type: 'cron-trigger', position: { x: 80, y: 120 }, config: { expression: '0 3 * * *' } }),
    },
    {
        id: 'event', Icon: Zap, title: 'On a panel event',
        subtitle: 'React to app, backup, health, or security events',
        node: () => ({ id: 'trigger', type: 'webhook-trigger', position: { x: 80, y: 120 }, config: { path: '/sk/events', method: 'POST' } }),
    },
    {
        id: 'webhook', Icon: Webhook, title: 'Incoming webhook',
        subtitle: 'Trigger from an external HTTP request',
        node: () => ({ id: 'trigger', type: 'webhook-trigger', position: { x: 80, y: 120 }, config: { path: '/hooks/my-hook', method: 'POST' } }),
    },
];

// Run status → Pill colour.
const runPill = (status) => {
    const kind = status === 'succeeded' || status === 'success' ? 'green'
        : status === 'running' || status === 'pending' ? 'amber'
            : status === 'failed' || status === 'error' ? 'red'
                : status === 'awaiting_approval' ? 'cyan' : 'gray';
    return <Pill kind={kind}>{status || 'unknown'}</Pill>;
};

// Host lifecycle state → Pill colour.
const hostPill = (state) => {
    const kind = state === 'ready' ? 'green'
        : state === 'unhealthy' ? 'amber'
            : state === 'stopped' ? 'gray' : 'red';
    return <Pill kind={kind}>{state || 'not_installed'}</Pill>;
};

const formatDuration = (start, finish) => {
    if (!start || !finish) return '—';
    const ms = new Date(finish).getTime() - new Date(start).getTime();
    if (Number.isNaN(ms) || ms < 0) return '—';
    if (ms < 1000) return `${ms}ms`;
    return `${(ms / 1000).toFixed(1)}s`;
};

const AutomationsPage = () => {
    const toast = useToast();
    const navigate = useNavigate();
    const { tab } = useParams();
    const activeTab = VALID_TABS.includes(tab) ? tab : 'workflows';

    const [busy, setBusy] = useState(false);
    const [confirmDialog, setConfirmDialog] = useState(null);

    // Workflows tab
    const [workflows, setWorkflows] = useState([]);
    const [wfLoading, setWfLoading] = useState(false);
    const [newModal, setNewModal] = useState(false);
    const [newName, setNewName] = useState('');
    const [newTrigger, setNewTrigger] = useState('manual');
    const [templates, setTemplates] = useState([]);
    const [templatesLoading, setTemplatesLoading] = useState(false);
    const [templateSearch, setTemplateSearch] = useState('');
    const [favorites, setFavorites] = useState(readFavorites);
    const [importModal, setImportModal] = useState(false);
    const [importName, setImportName] = useState('');
    const [importText, setImportText] = useState('');

    // Runs tab
    const [runs, setRuns] = useState([]);
    const [approvals, setApprovals] = useState([]);
    const [runsLoading, setRunsLoading] = useState(false);

    // Settings tab
    const [host, setHost] = useState(null);
    const [settings, setSettings] = useState(null);
    const [settingsLoading, setSettingsLoading] = useState(false);
    const [settingsSection, setSettingsSection] = useState('engine');
    const [installPort, setInstallPort] = useState('');
    const [newSecret, setNewSecret] = useState({ name: '', value: '' });
    const [hostPortDraft, setHostPortDraft] = useState('');

    // ── Loaders ──
    const loadWorkflows = useCallback(async () => {
        setWfLoading(true);
        try {
            const data = await api.request('/tramo/workflows');
            setWorkflows(data.workflows || []);
        } catch (error) {
            toast.error(`Could not load workflows: ${error.message}`);
        } finally {
            setWfLoading(false);
        }
    }, [toast]);

    const loadRuns = useCallback(async () => {
        setRunsLoading(true);
        try {
            const [runData, apprData] = await Promise.all([
                api.request('/tramo/runs?limit=100'),
                api.request('/tramo/approvals'),
            ]);
            setRuns(runData.runs || []);
            setApprovals(apprData.approvals || []);
        } catch (error) {
            toast.error(`Could not load runs: ${error.message}`);
        } finally {
            setRunsLoading(false);
        }
    }, [toast]);

    const loadSettings = useCallback(async () => {
        setSettingsLoading(true);
        try {
            const [statusData, settingsData] = await Promise.all([
                api.request('/tramo/host/status'),
                api.request('/tramo/settings'),
            ]);
            setHost(statusData);
            setSettings(settingsData);
            setHostPortDraft(String(settingsData.host_port ?? statusData.host_port ?? ''));
        } catch (error) {
            toast.error(`Could not load settings: ${error.message}`);
        } finally {
            setSettingsLoading(false);
        }
    }, [toast]);

    const loadTemplates = useCallback(async () => {
        setTemplatesLoading(true);
        try {
            const data = await api.request('/tramo/templates');
            setTemplates(data.templates || []);
        } catch (error) {
            toast.error(`Could not load templates: ${error.message}`);
        } finally {
            setTemplatesLoading(false);
        }
    }, [toast]);

    useEffect(() => {
        if (activeTab === 'workflows') loadWorkflows();
        else if (activeTab === 'templates') loadTemplates();
        else if (activeTab === 'runs') loadRuns();
        else if (activeTab === 'settings') loadSettings();
    }, [activeTab, loadWorkflows, loadTemplates, loadRuns, loadSettings]);

    const toggleFavorite = (id) => {
        setFavorites((prev) => {
            const next = new Set(prev);
            if (next.has(id)) next.delete(id); else next.add(id);
            try { localStorage.setItem(FAVORITES_KEY, JSON.stringify([...next])); } catch { /* ignore */ }
            return next;
        });
    };

    // ── Workflow actions ──
    const openNewModal = () => {
        setNewName('');
        setNewTrigger('manual');
        setNewModal(true);
    };

    const handleCreate = async () => {
        if (!newName.trim()) { toast.error('Name is required.'); return; }
        const trigger = TRIGGERS.find((t) => t.id === newTrigger) || TRIGGERS[0];
        const doc = { name: newName.trim(), nodes: [trigger.node()], edges: [] };
        setBusy(true);
        try {
            const wf = await api.request('/tramo/workflows', {
                method: 'POST', body: { name: newName.trim(), doc },
            });
            setNewModal(false);
            setNewName('');
            toast.success(`Workflow "${wf.name}" created`);
            navigate(`/automations/edit/${wf.slug}`);
        } catch (error) {
            toast.error(`Could not create workflow: ${error.message}`);
        } finally {
            setBusy(false);
        }
    };

    const handleFromTemplate = async (template) => {
        setBusy(true);
        try {
            const wf = await api.request(`/tramo/workflows/from-template/${template.id}`, { method: 'POST', body: {} });
            toast.success(`Created "${wf.name}" from ${template.name}`);
            navigate(`/automations/edit/${wf.slug}`);
        } catch (error) {
            toast.error(`Could not create from template: ${error.message}`);
        } finally {
            setBusy(false);
        }
    };

    const openImportModal = () => {
        setImportName('');
        setImportText('');
        setImportModal(true);
    };

    const handleImportFile = async (e) => {
        const file = e.target.files?.[0];
        if (!file) return;
        try {
            setImportText(await file.text());
            if (!importName.trim()) setImportName(file.name.replace(/\.json$/i, ''));
        } catch {
            toast.error('Could not read that file.');
        }
        e.target.value = '';
    };

    const handleImport = async () => {
        let doc;
        try {
            doc = JSON.parse(importText);
        } catch {
            toast.error('That is not valid JSON. Paste a tramo workflow document.');
            return;
        }
        if (!doc || typeof doc !== 'object' || !Array.isArray(doc.nodes)) {
            toast.error('That JSON does not look like a workflow (missing a nodes array).');
            return;
        }
        const name = importName.trim() || doc.name || 'Imported automation';
        setBusy(true);
        try {
            const wf = await api.request('/tramo/workflows', {
                method: 'POST', body: { name, doc: { ...doc, name } },
            });
            setImportModal(false);
            toast.success(`Imported "${wf.name}"`);
            navigate(`/automations/edit/${wf.slug}`);
        } catch (error) {
            toast.error(`Could not import: ${error.message}`);
        } finally {
            setBusy(false);
        }
    };

    const handleToggleEnabled = async (wf) => {
        try {
            await api.request(`/tramo/workflows/${wf.slug}`, { method: 'PUT', body: { enabled: !wf.enabled } });
            await loadWorkflows();
        } catch (error) {
            toast.error(`Could not update workflow: ${error.message}`);
        }
    };

    const handleDeleteWorkflow = (wf) => {
        setConfirmDialog({
            title: `Delete ${wf.name}?`,
            message: 'This removes the workflow and its stored document. Deployed runs already recorded are kept.',
            confirmText: 'Delete',
            variant: 'danger',
            onConfirm: async () => {
                setConfirmDialog(null);
                try {
                    await api.request(`/tramo/workflows/${wf.slug}`, { method: 'DELETE' });
                    toast.success('Workflow deleted');
                    await loadWorkflows();
                } catch (error) {
                    toast.error(error.message);
                }
            },
            onCancel: () => setConfirmDialog(null),
        });
    };

    const handleDeploy = async () => {
        setBusy(true);
        try {
            const res = await api.request('/tramo/deploy', { method: 'POST' });
            toast.success(res?.message || 'Deployed to the tramo engine');
            await loadWorkflows();
        } catch (error) {
            toast.error(`Deploy failed: ${error.message}`);
        } finally {
            setBusy(false);
        }
    };

    const handleRunWorkflow = async (wf) => {
        setBusy(true);
        try {
            const res = await api.request(`/tramo/workflows/${wf.slug}/run`, { method: 'POST', body: {} });
            const status = res?.run?.status || res?.result?.status || 'started';
            toast.success(`Run ${status} — see the Runs tab`);
        } catch (error) {
            toast.error(`Run failed: ${error.message}`);
        } finally {
            setBusy(false);
        }
    };

    // ── Run actions ──
    const handleApprove = async (runId) => {
        setBusy(true);
        try {
            await api.request(`/tramo/runs/${runId}/approve`, { method: 'POST', body: {} });
            toast.success('Approved');
            await loadRuns();
        } catch (error) {
            toast.error(`Approve failed: ${error.message}`);
        } finally {
            setBusy(false);
        }
    };

    const handleReplay = async (runId) => {
        setBusy(true);
        try {
            await api.request(`/tramo/runs/${runId}/replay`, { method: 'POST' });
            toast.success('Replay queued');
            await loadRuns();
        } catch (error) {
            toast.error(`Replay failed: ${error.message}`);
        } finally {
            setBusy(false);
        }
    };

    // ── Host / settings actions ──
    const handleInstall = async () => {
        setBusy(true);
        try {
            const body = installPort ? { host_port: Number(installPort) } : {};
            await api.request('/tramo/host/install', { method: 'POST', body });
            toast.success('tramo engine installed');
            setInstallPort('');
            await loadSettings();
        } catch (error) {
            toast.error(`Install failed: ${error.message}`);
        } finally {
            setBusy(false);
        }
    };

    const handleUninstall = (keepData) => {
        setConfirmDialog({
            title: 'Remove tramo engine',
            message: keepData
                ? 'Remove the tramo container? Workflow data stays on disk and a reinstall picks it back up.'
                : 'Remove the tramo container AND delete all engine data? This cannot be undone.',
            confirmText: 'Remove',
            variant: 'danger',
            onConfirm: async () => {
                setConfirmDialog(null);
                try {
                    await api.request(`/tramo/host/install?keep_data=${keepData}`, { method: 'DELETE' });
                    toast.success('tramo engine removed');
                    await loadSettings();
                } catch (error) {
                    toast.error(`Uninstall failed: ${error.message}`);
                }
            },
            onCancel: () => setConfirmDialog(null),
        });
    };

    const handleControl = async (action) => {
        setBusy(true);
        try {
            await api.request(`/tramo/host/control/${action}`, { method: 'POST' });
            toast.success(`Engine ${action} requested`);
            await loadSettings();
        } catch (error) {
            toast.error(`Could not ${action} engine: ${error.message}`);
        } finally {
            setBusy(false);
        }
    };

    const handleAddSecret = async () => {
        if (!newSecret.name.trim() || !newSecret.value) { toast.error('Name and value are required.'); return; }
        setBusy(true);
        try {
            await api.request('/tramo/settings', {
                method: 'PUT',
                body: { pack_secrets: { [newSecret.name.trim()]: newSecret.value } },
            });
            toast.success(`Secret ${newSecret.name.trim()} saved`);
            setNewSecret({ name: '', value: '' });
            await loadSettings();
        } catch (error) {
            toast.error(`Could not save secret: ${error.message}`);
        } finally {
            setBusy(false);
        }
    };

    const handleToggleBridge = async () => {
        setBusy(true);
        try {
            await api.request('/tramo/settings', {
                method: 'PUT',
                body: { events_bridge_enabled: !settings?.events_bridge_enabled },
            });
            await loadSettings();
        } catch (error) {
            toast.error(`Could not update events bridge: ${error.message}`);
        } finally {
            setBusy(false);
        }
    };

    const handleSaveHostPort = async () => {
        const port = Number(hostPortDraft);
        if (!port) { toast.error('Enter a valid port.'); return; }
        setBusy(true);
        try {
            await api.request('/tramo/settings', { method: 'PUT', body: { host_port: port } });
            toast.success('Host port updated');
            await loadSettings();
        } catch (error) {
            toast.error(`Could not update host port: ${error.message}`);
        } finally {
            setBusy(false);
        }
    };

    // ── Renderers ──
    const renderTemplates = () => {
        const q = templateSearch.trim().toLowerCase();
        const filtered = templates.filter((t) => !q
            || t.name.toLowerCase().includes(q)
            || (t.description || '').toLowerCase().includes(q));
        // Favorites float to the top; otherwise preserve the incoming order.
        const sorted = [...filtered].sort(
            (a, b) => (favorites.has(a.id) ? 0 : 1) - (favorites.has(b.id) ? 0 : 1));
        return (
            <div className="tramo-templates">
                <div className="tramo-templates__bar">
                    <div className="tramo-search">
                        <Search size={15} />
                        <input
                            type="text"
                            placeholder="Search templates..."
                            value={templateSearch}
                            onChange={(e) => setTemplateSearch(e.target.value)}
                        />
                    </div>
                    <span className="tramo-templates__count">
                        {filtered.length} template{filtered.length === 1 ? '' : 's'}
                    </span>
                </div>
                {templatesLoading ? (
                    <EmptyState loading title="Loading templates..." />
                ) : sorted.length === 0 ? (
                    <EmptyState
                        icon={LayoutTemplate}
                        title={q ? 'No templates match your search' : 'No templates yet'}
                        description={q ? 'Try a different search.' : 'Import your own to get started.'}
                    />
                ) : (
                    <div className="tramo-tpl-grid">
                        {sorted.map((t) => {
                            const meta = TEMPLATE_META[t.id] || DEFAULT_TEMPLATE_META;
                            const { Icon } = meta;
                            const fav = favorites.has(t.id);
                            return (
                                <div className="tramo-card" key={t.id}>
                                    <div className="tramo-card__top">
                                        <span className={`tramo-card__icon tramo-card__icon--${meta.brand}`}>
                                            <Icon size={20} />
                                        </span>
                                        <button
                                            type="button"
                                            className={`tramo-card__fav${fav ? ' is-fav' : ''}`}
                                            onClick={() => toggleFavorite(t.id)}
                                            title={fav ? 'Remove from favorites' : 'Add to favorites'}
                                            aria-pressed={fav}
                                        >
                                            <Star size={16} />
                                        </button>
                                    </div>
                                    <h4 className="tramo-card__name">{t.name}</h4>
                                    {t.description && <p className="tramo-card__desc">{t.description}</p>}
                                    {meta.tags.length > 0 && (
                                        <div className="tramo-card__tags">
                                            {meta.tags.map((tag) => (
                                                <span className="tramo-card__tag" key={tag}>{tag}</span>
                                            ))}
                                        </div>
                                    )}
                                    <div className="tramo-card__foot">
                                        <Button variant="default" size="sm" disabled={busy} onClick={() => handleFromTemplate(t)}>
                                            <Plus size={14} /> Use template
                                        </Button>
                                    </div>
                                </div>
                            );
                        })}
                    </div>
                )}
            </div>
        );
    };

    const renderWorkflows = () => (
        <div className="card">
            <div className="card-body">
                {wfLoading ? <EmptyState loading title="Loading workflows..." />
                    : workflows.length === 0 ? (
                        <EmptyState
                            icon={Workflow}
                            title="No automations yet"
                            description="Create a workflow on the visual canvas, or start from a template. Enable it and deploy to run it headless on the tramo engine."
                        />
                    ) : (
                        <table className="sk-dtable">
                            <thead>
                                <tr>
                                    <th>Name</th><th>Enabled</th><th>State</th><th>Version</th><th>Updated</th><th /></tr>
                            </thead>
                            <tbody>
                                {workflows.map((wf) => (
                                    <tr key={wf.id ?? wf.slug}>
                                        <td className="sk-cell-mono">{wf.name}</td>
                                        <td>
                                            <button
                                                type="button"
                                                className={`tramo-toggle${wf.enabled ? ' tramo-toggle--on' : ''}`}
                                                onClick={() => handleToggleEnabled(wf)}
                                                aria-pressed={wf.enabled}
                                                title={wf.enabled ? 'Disable' : 'Enable'}
                                            >
                                                <span className="tramo-toggle__knob" />
                                            </button>
                                        </td>
                                        <td>
                                            {wf.dirty
                                                ? <Pill kind="amber" title="Edited since last deploy">undeployed</Pill>
                                                : <Pill kind="green">deployed</Pill>}
                                        </td>
                                        <td className="sk-cell-mono">{wf.doc_version ?? '—'}</td>
                                        <td className="sk-cell-mono">{wf.updated_at ? new Date(wf.updated_at).toLocaleString() : '—'}</td>
                                        <td className="tramo-row-actions">
                                            <Button variant="secondary" size="sm" disabled={busy} onClick={() => handleRunWorkflow(wf)} title="Run now">
                                                <Play size={14} />
                                            </Button>
                                            <Button variant="secondary" size="sm" onClick={() => navigate(`/automations/edit/${wf.slug}`)} title="Edit">
                                                <Pencil size={14} />
                                            </Button>
                                            <Button variant="destructive" size="sm" onClick={() => handleDeleteWorkflow(wf)} title="Delete">
                                                <Trash2 size={14} />
                                            </Button>
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    )}
            </div>
        </div>
    );

    const renderRuns = () => (
        <>
            {approvals.length > 0 && (
                <div className="card tramo-approvals">
                    <div className="card-header">
                        <h3>Pending approvals <span className="sec-count">· {approvals.length}</span></h3>
                    </div>
                    <div className="card-body">
                        {approvals.map((a) => (
                            <div className="tramo-approval" key={a.run_id}>
                                <div className="tramo-approval__info">
                                    <span className="sk-cell-mono">{a.workflow_slug || a.workflow || '—'}</span>
                                    <span className="text-muted">{a.node || a.message || 'Awaiting approval'}</span>
                                </div>
                                <Button variant="default" size="sm" disabled={busy} onClick={() => handleApprove(a.run_id)}>
                                    <CheckCircle2 size={14} /> Approve
                                </Button>
                            </div>
                        ))}
                    </div>
                </div>
            )}
            <div className="card">
                <div className="card-body">
                    {runsLoading ? <EmptyState loading title="Loading runs..." />
                        : runs.length === 0 ? (
                            <EmptyState icon={Play} title="No runs yet" description="Deploy an enabled workflow, then trigger it or wait for a matching event." />
                        ) : (
                            <table className="sk-dtable">
                                <thead>
                                    <tr>
                                        <th>Status</th><th>Workflow</th><th>Source</th><th>Duration</th><th>Tokens</th><th>Error</th><th /></tr>
                                </thead>
                                <tbody>
                                    {runs.map((r) => (
                                        <tr key={r.run_id}>
                                            <td>{runPill(r.status)}</td>
                                            <td className="sk-cell-mono">{r.workflow_slug || '—'}</td>
                                            <td><Pill kind="gray">{r.source || 'manual'}</Pill></td>
                                            <td className="sk-cell-mono">{formatDuration(r.started_at, r.finished_at)}</td>
                                            <td className="sk-cell-mono">{r.usage?.total_tokens ?? r.usage?.tokens ?? '—'}</td>
                                            <td className="sk-cell-mono tramo-truncate" title={r.error || ''}>{r.error || '—'}</td>
                                            <td className="tramo-row-actions">
                                                <Button variant="secondary" size="sm" disabled={busy} onClick={() => handleReplay(r.run_id)} title="Replay">
                                                    <RefreshCw size={14} />
                                                </Button>
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        )}
                </div>
            </div>
        </>
    );

    const SETTINGS_SECTIONS = [
        { id: 'engine', label: 'Engine', Icon: Server },
        { id: 'general', label: 'Events & port', Icon: Zap },
        { id: 'secrets', label: 'Pack secrets', Icon: KeyRound },
    ];

    const renderSettings = () => {
        const state = host?.state || 'not_installed';
        const installed = !!host?.installed;
        const notSupported = !installed && !!host?.error;

        const engineCard = (
                <div className="card">
                    <div className="card-header">
                        <h3><Server size={16} /> Automation engine</h3>
                    </div>
                    <div className="card-body">
                        {settingsLoading && !host ? <EmptyState loading title="Loading engine status..." /> : (
                            <>
                                <div className="sec-rows">
                                    <div className="sk-info-row">
                                        <span className="k">Status</span>
                                        {hostPill(state)}
                                    </div>
                                    <div className="sk-info-row">
                                        <span className="k">Container</span>
                                        <span className="v sk-cell-mono">{host?.container || '—'}</span>
                                    </div>
                                    <div className="sk-info-row">
                                        <span className="k">Image</span>
                                        <span className="v sk-cell-mono">{host?.image || '—'}</span>
                                    </div>
                                    <div className="sk-info-row">
                                        <span className="k">Host port</span>
                                        <span className="v sk-cell-mono">{host?.host_port ?? '—'}</span>
                                    </div>
                                    {host?.version && (
                                        <div className="sk-info-row">
                                            <span className="k">Version</span>
                                            <span className="v sk-cell-mono">{host.version}</span>
                                        </div>
                                    )}
                                </div>

                                {notSupported && (
                                    <div className="tramo-note">
                                        Docker is required to run the tramo engine, and it is not available on this
                                        host (the engine does not run on Windows dev boxes). You can still design
                                        workflows; deploying and running them needs a Linux host with Docker.
                                        <div className="tramo-note__detail">{host.error}</div>
                                    </div>
                                )}

                                <div className="tramo-host-actions">
                                    {!installed ? (
                                        <div className="tramo-install">
                                            <div className="form-group">
                                                <Label>Host port (optional)</Label>
                                                <Input
                                                    type="number"
                                                    value={installPort}
                                                    placeholder={String(host?.host_port ?? 3737)}
                                                    onChange={(e) => setInstallPort(e.target.value)}
                                                />
                                            </div>
                                            <Button variant="default" size="sm" onClick={handleInstall} disabled={busy}>
                                                <Power size={14} /> Install engine
                                            </Button>
                                        </div>
                                    ) : (
                                        <>
                                            <Button variant="outline" size="sm" onClick={() => handleControl('restart')} disabled={busy}>
                                                <RefreshCw size={14} /> Restart
                                            </Button>
                                            {host?.running ? (
                                                <Button variant="outline" size="sm" onClick={() => handleControl('stop')} disabled={busy}>
                                                    <Power size={14} /> Stop
                                                </Button>
                                            ) : (
                                                <Button variant="default" size="sm" onClick={() => handleControl('start')} disabled={busy}>
                                                    <Power size={14} /> Start
                                                </Button>
                                            )}
                                            <Button variant="secondary" size="sm" onClick={() => handleUninstall(true)} disabled={busy}>
                                                Remove (keep data)
                                            </Button>
                                            <Button variant="destructive" size="sm" onClick={() => handleUninstall(false)} disabled={busy}>
                                                <Trash2 size={14} /> Remove + data
                                            </Button>
                                        </>
                                    )}
                                </div>
                            </>
                        )}
                    </div>
                </div>
        );

        const generalCard = (
            <div className="card">
                <div className="card-header"><h3><Zap size={16} /> Events &amp; port</h3></div>
                <div className="card-body tramo-settings">
                    <div className="tramo-field">
                        <div className="tramo-field__label">
                            <Label>Events bridge</Label>
                            <p className="text-muted">Forward panel events to tramo so workflows can react to them.</p>
                        </div>
                        <button
                            type="button"
                            className={`tramo-toggle${settings?.events_bridge_enabled ? ' tramo-toggle--on' : ''}`}
                            onClick={handleToggleBridge}
                            disabled={busy}
                            aria-pressed={!!settings?.events_bridge_enabled}
                        >
                            <span className="tramo-toggle__knob" />
                        </button>
                    </div>
                    <div className="tramo-field tramo-field--inline">
                        <div className="tramo-field__label">
                            <Label>Host port</Label>
                            <p className="text-muted">Port the tramo container is published on.</p>
                        </div>
                        <div className="tramo-field__control">
                            <Input type="number" value={hostPortDraft} onChange={(e) => setHostPortDraft(e.target.value)} />
                            <Button variant="secondary" size="sm" onClick={handleSaveHostPort} disabled={busy}>Save</Button>
                        </div>
                    </div>
                </div>
            </div>
        );

        const secretsCard = (
            <div className="card sec-flush">
                <div className="card-header">
                    <h3><KeyRound size={16} /> Pack secrets</h3>
                </div>
                <div className="card-body">
                    <p className="text-muted">
                        Credentials integration packs need (API keys, tokens). Values are write-only — they are
                        stored encrypted and never shown again after saving.
                    </p>
                    {(settings?.pack_secret_names?.length ?? 0) === 0 ? (
                        <p className="text-muted">No pack secrets set yet.</p>
                    ) : (
                        <div className="tramo-secret-list">
                            {settings.pack_secret_names.map((name) => (
                                <div className="tramo-secret" key={name}>
                                    <span className="sk-cell-mono">{name}</span>
                                    <Pill kind="green">set</Pill>
                                </div>
                            ))}
                        </div>
                    )}
                    <div className="tramo-secret-add">
                        <div className="form-group">
                            <Label>Name</Label>
                            <Input
                                type="text"
                                value={newSecret.name}
                                placeholder="TELEGRAM_BOT_TOKEN"
                                onChange={(e) => setNewSecret((s) => ({ ...s, name: e.target.value }))}
                            />
                        </div>
                        <div className="form-group">
                            <Label>Value</Label>
                            <Input
                                type="password"
                                value={newSecret.value}
                                onChange={(e) => setNewSecret((s) => ({ ...s, value: e.target.value }))}
                            />
                        </div>
                        <Button variant="default" size="sm" onClick={handleAddSecret} disabled={busy}>
                            <Plus size={14} /> Add secret
                        </Button>
                    </div>
                </div>
            </div>
        );

        return (
            <div className="settings-layout tramo-settings-layout">
                <nav className="settings-nav">
                    {SETTINGS_SECTIONS.map(({ id, label, Icon }) => (
                        <Button
                            key={id}
                            variant="ghost"
                            className={`settings-nav-item ${settingsSection === id ? 'active' : ''}`}
                            onClick={() => setSettingsSection(id)}
                        >
                            <Icon size={18} /> {label}
                        </Button>
                    ))}
                </nav>
                <div className="settings-content">
                    {settingsSection === 'engine' && engineCard}
                    {settingsSection === 'general' && generalCard}
                    {settingsSection === 'secrets' && secretsCard}
                </div>
            </div>
        );
    };

    const topbarTabs = TABS.map(({ to, label, end }) => ({ to, label, end }));

    // Actions live in the topbar (like Domains / WordPress) and are contextual
    // to the active tab, so the content area carries no second header row.
    let topbarActions = null;
    if (activeTab === 'workflows') {
        topbarActions = (
            <>
                <Button variant="outline" size="sm" onClick={handleDeploy} disabled={busy}>
                    <Rocket size={14} /> Deploy
                </Button>
                <Button variant="default" size="sm" onClick={openNewModal}>
                    <Plus size={14} /> New workflow
                </Button>
            </>
        );
    } else if (activeTab === 'templates') {
        topbarActions = (
            <Button variant="default" size="sm" onClick={openImportModal}>
                <Upload size={14} /> Import template
            </Button>
        );
    } else if (activeTab === 'runs') {
        topbarActions = (
            <Button variant="outline" size="sm" onClick={loadRuns} disabled={runsLoading}>
                <RefreshCw size={14} /> Refresh
            </Button>
        );
    } else if (activeTab === 'settings') {
        topbarActions = (
            <Button variant="outline" size="sm" onClick={loadSettings} disabled={settingsLoading}>
                <RefreshCw size={14} /> Refresh
            </Button>
        );
    }

    return (
        <div className="page-container page-container--full-bleed sk-tabgroup tramo-page">
            <PageTopbar
                icon={<Workflow size={18} />}
                title="Automations"
                tabs={topbarTabs}
                actions={topbarActions}
            />

            <div className="sk-tabgroup__content">
                <div className="sk-tabgroup__inner">
                    {activeTab === 'workflows' && renderWorkflows()}
                    {activeTab === 'templates' && renderTemplates()}
                    {activeTab === 'runs' && renderRuns()}
                    {activeTab === 'settings' && renderSettings()}
                </div>
            </div>

            {/* New workflow modal — two-column: explainer + name/trigger picker */}
            <Modal
                open={newModal}
                onClose={() => setNewModal(false)}
                title="Create an automation"
                size="2xl"
                className="tramo-newflow-modal"
                footer={(
                    <>
                        <Button variant="outline" onClick={() => setNewModal(false)}>Cancel</Button>
                        <Button variant="default" onClick={handleCreate} disabled={busy || !newName.trim()}>
                            <Plus size={14} /> Create
                        </Button>
                    </>
                )}
            >
                <div className="tramo-newflow">
                    <aside className="tramo-newflow__hero">
                        <span className="tramo-newflow__hero-badge"><Workflow size={26} /></span>
                        <div className="tramo-newflow__hero-diagram" aria-hidden="true">
                            <span className="tramo-newflow__hero-node"><Zap size={15} /></span>
                            <span className="tramo-newflow__hero-line" />
                            <span className="tramo-newflow__hero-node"><Workflow size={15} /></span>
                            <span className="tramo-newflow__hero-line" />
                            <span className="tramo-newflow__hero-node"><Send size={15} /></span>
                        </div>
                        <h3 className="tramo-newflow__hero-title">Automate the boring parts</h3>
                        <p className="tramo-newflow__hero-text">
                            Chain triggers and actions on a visual canvas that runs headless
                            on the tramo engine. Pick a starting trigger below, then design
                            the rest in the editor.
                        </p>
                        <ul className="tramo-newflow__hero-list">
                            <li>Message yourself on Telegram when a backup fails</li>
                            <li>Open a GitHub issue on a nightly health check</li>
                            <li>Relay any panel event to a Discord channel</li>
                        </ul>
                    </aside>

                    <div className="tramo-newflow__form">
                        <div className="form-group">
                            <Label>Automation name</Label>
                            <Input
                                type="text"
                                value={newName}
                                autoFocus
                                placeholder="Notify me when a backup fails"
                                onChange={(e) => setNewName(e.target.value)}
                                onKeyDown={(e) => { if (e.key === 'Enter' && newName.trim()) handleCreate(); }}
                            />
                        </div>

                        <div className="tramo-newflow__triggers">
                            <span className="tramo-newflow__triggers-label">How should it start?</span>
                            <div className="tramo-trigger-list" role="radiogroup" aria-label="Trigger">
                                {TRIGGERS.map((tr) => {
                                    const { Icon } = tr;
                                    const selected = newTrigger === tr.id;
                                    return (
                                        <button
                                            type="button"
                                            key={tr.id}
                                            role="radio"
                                            aria-checked={selected}
                                            className={`tramo-trigger${selected ? ' is-selected' : ''}`}
                                            onClick={() => setNewTrigger(tr.id)}
                                        >
                                            <span className="tramo-trigger__icon"><Icon size={18} /></span>
                                            <span className="tramo-trigger__body">
                                                <span className="tramo-trigger__title">{tr.title}</span>
                                                <span className="tramo-trigger__sub">{tr.subtitle}</span>
                                            </span>
                                            <span className="tramo-trigger__check">
                                                {selected && <Check size={15} />}
                                            </span>
                                        </button>
                                    );
                                })}
                            </div>
                        </div>
                    </div>
                </div>
            </Modal>

            {/* Import template / workflow modal */}
            <Modal
                open={importModal}
                onClose={() => setImportModal(false)}
                title="Import a template"
                size="lg"
                footer={(
                    <>
                        <Button variant="outline" onClick={() => setImportModal(false)}>Cancel</Button>
                        <Button variant="default" onClick={handleImport} disabled={busy || !importText.trim()}>
                            <Upload size={14} /> Import
                        </Button>
                    </>
                )}
            >
                <p className="tramo-tpl-intro">
                    Paste a tramo workflow document (JSON), or load one from a file. It is
                    created as a new automation you can edit and deploy.
                </p>
                <div className="form-group">
                    <Label>Name (optional)</Label>
                    <Input
                        type="text"
                        value={importName}
                        placeholder="My imported automation"
                        onChange={(e) => setImportName(e.target.value)}
                    />
                </div>
                <div className="form-group">
                    <div className="tramo-import__labelrow">
                        <Label>Workflow JSON</Label>
                        <label className="tramo-import__file">
                            <FileJson size={14} /> Load file
                            <input type="file" accept="application/json,.json" onChange={handleImportFile} hidden />
                        </label>
                    </div>
                    <textarea
                        className="tramo-import__text"
                        value={importText}
                        placeholder={'{\n  "name": "My flow",\n  "nodes": [],\n  "edges": []\n}'}
                        onChange={(e) => setImportText(e.target.value)}
                        spellCheck={false}
                    />
                </div>
            </Modal>

            {confirmDialog && (
                <ConfirmDialog
                    title={confirmDialog.title}
                    message={confirmDialog.message}
                    confirmText={confirmDialog.confirmText}
                    variant={confirmDialog.variant}
                    onConfirm={confirmDialog.onConfirm}
                    onCancel={confirmDialog.onCancel}
                />
            )}
        </div>
    );
};

export { AutomationsPage };
export default AutomationsPage;
