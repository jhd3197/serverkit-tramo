// Runtime-ESM entry for ServerKit's no-rebuild loader (same pattern as
// serverkit-gpu). CSS is imported as a STRING (?inline) and injected once at
// module load, so the single dist/index.mjs the panel blob-imports carries its
// own styles. Shared libs (react, react-router-dom, serverkit-sdk) are
// externalized by vite.config and resolved to the panel's singletons via its
// import map; tramo + lucide-react are bundled.
import css from './styles/tramo-automations.scss?inline';
import { AutomationsPage } from './components/AutomationsPage.jsx';
import { AutomationEditorPage } from './components/AutomationEditorPage.jsx';

// Translations. Registered against the PANEL's i18next singleton (shared via
// its vendor import map), additively and under this extension's own
// `tramo` namespace — never init() or changeLanguage(), which the panel
// owns and which would reconfigure or switch the language everywhere.
//
// The English bundle is generated from the inline t('key', 'English')
// defaults, so a key with no bundle still renders its default. More locales
// drop in beside en.json with one addResourceBundle line each.
import i18next from 'i18next';
import en from './locales/en.json';
import es from './locales/es.json';

for (const [language, bundle] of Object.entries({ en, es })) {
    i18next.addResourceBundle(language, 'translation', bundle, true, false);
}


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
