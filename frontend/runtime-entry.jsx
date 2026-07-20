// Runtime-ESM entry for ServerKit's no-rebuild loader (same pattern as
// serverkit-gpu). CSS is imported as a STRING (?inline) and injected once at
// module load, so the single dist/index.mjs the panel blob-imports carries its
// own styles. Shared libs (react, react-router-dom, serverkit-sdk) are
// externalized by vite.config and resolved to the panel's singletons via its
// import map; tramo + lucide-react are bundled.
import css from './styles/tramo-automations.scss?inline';
import { AutomationsPage } from './components/AutomationsPage.jsx';
import { AutomationEditorPage } from './components/AutomationEditorPage.jsx';

if (typeof document !== 'undefined' && !document.getElementById('serverkit-tramo-styles')) {
    const style = document.createElement('style');
    style.id = 'serverkit-tramo-styles';
    style.textContent = css;
    document.head.appendChild(style);
}

// Named exports match the `component` values in plugin.json's route
// contributions; resolveComponent(slug, name) picks them up at runtime.
// Deliberately NO default export (PluginLoader auto-renders those globally).
export { AutomationsPage, AutomationEditorPage };
