import { Suspense, lazy, useCallback, useEffect, useState } from 'react';
import { ArrowLeft, Play, Rocket, Check, AlertCircle, Loader2 } from 'lucide-react';
import { api, Pill, useToast, useParams, useNavigate } from 'serverkit-sdk';
import { Button, EmptyState } from './primitives.jsx';
import { useTranslation } from 'serverkit-sdk';

// The tramo editor is the heavy chunk (canvas engine + 21 integration packs +
// tramo/styles.css). Lazy-load it so it never lands in the panel entry bundle.
const TramoEditor = lazy(() => import('./TramoEditor.jsx'));

// Map the editor's save lifecycle to a small header indicator.
const SaveIndicator = ({ state }) => {
    const { t } = useTranslation();
    const status = state?.status || 'idle';
    if (status === 'saving' || status === 'pending') {
        return <span className="tramo-save tramo-save--busy"><Loader2 size={13} className="tramo-spin" /> {t('tramo.automationEditorPage.saving', 'Saving…')}</span>;
    }
    if (status === 'saved') {
        return <span className="tramo-save tramo-save--ok"><Check size={13} /> {t('tramo.automationEditorPage.saved', 'Saved')}</span>;
    }
    if (status === 'error') {
        return <span className="tramo-save tramo-save--err"><AlertCircle size={13} /> {state?.error || 'Save failed'}</span>;
    }
    return <span className="tramo-save tramo-save--idle">{t('tramo.automationEditorPage.allChangesSaved', 'All changes saved')}</span>;
};

const AutomationEditorPage = () => {
    const { t } = useTranslation();
    const { slug } = useParams();
    const navigate = useNavigate();
    const toast = useToast();

    const [workflow, setWorkflow] = useState(null);
    const [saveState, setSaveState] = useState(null);
    const [busy, setBusy] = useState(false);

    // Header metadata (name, enabled) — the doc itself is owned by the editor.
    useEffect(() => {
        let cancelled = false;
        (async () => {
            try {
                const data = await api.request(`/tramo/workflows/${slug}`);
                if (!cancelled) setWorkflow(data);
            } catch (error) {
                if (!cancelled) toast.error(t('tramo.automationEditorPage.couldNotLoadWorkflow', 'Could not load workflow: {{message}}', { message: error.message }));
            }
        })();
        return () => { cancelled = true; };
    }, [slug, toast]);

    const onSaveStateChange = useCallback((s) => setSaveState(s), []);

    const handleRun = async () => {
        setBusy(true);
        try {
            const res = await api.request(`/tramo/workflows/${slug}/run`, { method: 'POST', body: {} });
            const status = res?.run?.status || res?.result?.status || 'started';
            toast.success(t('tramo.automationEditorPage.runSeeRunsForDetails', 'Run {{status}} — see Runs for details', { status: status }), {
                action: { label: t('tramo.automationEditorPage.viewRuns', 'View runs'), onClick: () => navigate('/automations/runs') },
            });
        } catch (error) {
            toast.error(t('tramo.automationEditorPage.runFailed', 'Run failed: {{message}}', { message: error.message }));
        } finally {
            setBusy(false);
        }
    };

    const handleDeploy = async () => {
        setBusy(true);
        try {
            const res = await api.request('/tramo/deploy', { method: 'POST' });
            toast.success(res?.message || t('tramo.automationEditorPage.deployedToTheTramoEngine', 'Deployed to the tramo engine'));
        } catch (error) {
            toast.error(t('tramo.automationEditorPage.deployFailed', 'Deploy failed: {{message}}', { message: error.message }));
        } finally {
            setBusy(false);
        }
    };

    return (
        <div className="tramo-editor-page">
            <div className="tramo-editor-page__bar">
                <div className="tramo-editor-page__left">
                    <Button variant="ghost" size="sm" onClick={() => navigate('/automations')} title={t('tramo.automationEditorPage.backToAutomations', 'Back to Automations')}>
                        <ArrowLeft size={16} />
                    </Button>
                    <div className="tramo-editor-page__title">
                        <span className="tramo-editor-page__name">{workflow?.name || slug}</span>
                        {workflow && (
                            <Pill kind={workflow.enabled ? 'green' : 'gray'}>
                                {workflow.enabled ? 'enabled' : 'disabled'}
                            </Pill>
                        )}
                    </div>
                    <SaveIndicator state={saveState} />
                </div>
                <div className="tramo-editor-page__actions">
                    <Button variant="secondary" size="sm" onClick={handleRun} disabled={busy}>
                        <Play size={14} /> {t('tramo.automationEditorPage.run', 'Run')}
                    </Button>
                    <Button variant="default" size="sm" onClick={handleDeploy} disabled={busy}>
                        <Rocket size={14} /> {t('tramo.automationEditorPage.deploy', 'Deploy')}
                    </Button>
                </div>
            </div>

            <div className="tramo-editor-page__body">
                <Suspense fallback={<EmptyState loading title={t('tramo.automationEditorPage.loadingEditor', 'Loading editor...')} />}>
                    <TramoEditor slug={slug} onSaveStateChange={onSaveStateChange} />
                </Suspense>
            </div>
        </div>
    );
};

export { AutomationEditorPage };
export default AutomationEditorPage;
