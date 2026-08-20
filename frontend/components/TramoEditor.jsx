// TramoEditor — the tramo canvas surface.
//
// In the standalone runtime-ESM build everything ships in ONE dist/index.mjs
// (inlineDynamicImports collapses the lazy split), so tramo's own canvas +
// inspector CSS is imported as a STRING (?inline) and injected once at module
// load — a regular css import would be extracted to a separate asset the
// panel never loads.
import { useEffect } from 'react';
import { Canvas, RightRail, useWorkflow } from 'tramo/react';
import tramoCss from 'tramo/styles.css?inline';
import { api } from 'serverkit-sdk';
import { EmptyState } from './primitives.jsx';
import { registry } from '../registry.js';
import { useTranslation } from 'serverkit-sdk';

if (typeof document !== 'undefined' && !document.getElementById('serverkit-tramo-editor-styles')) {
    const style = document.createElement('style');
    style.id = 'serverkit-tramo-editor-styles';
    style.textContent = tramoCss;
    document.head.appendChild(style);
}

const TramoEditor = ({ slug, onSaveStateChange }) => {
    const { t } = useTranslation();
    const handle = useWorkflow({
        registry,
        key: slug,
        loadDoc: async () => {
            const data = await api.request(`/tramo/workflows/${slug}`);
            const doc = data.doc || { version: 1, id: slug, name: slug, nodes: [], edges: [], meta: {} };
            // The editor's Canvas reads `doc.meta.mcpServers` unconditionally, so a
            // doc without `meta` crashes it. Guarantee `meta` for brand-new
            // workflows and any doc persisted by an older version.
            if (!doc.meta) doc.meta = {};
            return doc;
        },
        saveDoc: async (doc) => {
            await api.request(`/tramo/workflows/${slug}`, { method: 'PUT', body: { doc } });
        },
    });

    // Surface the debounced save lifecycle up to the page's top strip.
    useEffect(() => {
        if (onSaveStateChange) onSaveStateChange(handle.saveState);
    }, [handle.saveState, onSaveStateChange]);

    if (!handle.ready) {
        return (
            <div className="tramo-editor__loading">
                <EmptyState loading title={t('tramo.tramoEditor.loadingWorkflow', 'Loading workflow...')} />
            </div>
        );
    }

    return (
        <div className="tramo-editor">
            <div className="tramo-editor__canvas">
                <Canvas workflow={handle} />
            </div>
            <div className="tramo-editor__rail">
                <RightRail
                    selection={handle.selection}
                    registry={handle.registry}
                    onApply={handle.applyPatch}
                    onClose={handle.clearSelection}
                    saveState={handle.saveState}
                    doc={handle.doc}
                />
            </div>
        </div>
    );
};

export default TramoEditor;
