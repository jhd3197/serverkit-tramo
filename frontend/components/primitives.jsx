// Local stand-ins for the host components these pages need that are NOT on
// the serverkit-sdk surface (Button, Input, Label, Modal, ConfirmDialog,
// EmptyState). They render the same host design-system classes the core
// components emit (.btn-*, .ui-input, .ui-label, .ui-dialog-*, .sk-modal*,
// .sk-confirm*, .empty-state, .skeleton), so the pages look identical without
// importing host internals — which a runtime-ESM bundle cannot do.
import { useEffect } from 'react';
import { createPortal } from 'react-dom';
import { Inbox, X, AlertTriangle, AlertCircle, Info } from 'lucide-react';
import { useTranslation } from 'serverkit-sdk';

// Mirrors frontend/src/components/ui/button.jsx's variant/size -> class map.
const VARIANT_CLASSES = {
    default: 'btn-primary',
    primary: 'btn-primary',
    destructive: 'btn-danger',
    danger: 'btn-danger',
    outline: 'btn-secondary',
    secondary: 'btn-soft',
    ghost: 'btn-ghost',
    link: 'btn-link',
};
const SIZE_CLASSES = { sm: 'btn-sm', lg: 'btn-lg', icon: 'btn-icon' };

export function Button({ variant = 'default', size, className = '', children, ...props }) {
    const classes = [
        'btn',
        VARIANT_CLASSES[variant] || 'btn-primary',
        SIZE_CLASSES[size] || '',
        className,
    ].filter(Boolean).join(' ');
    return (
        <button type="button" data-slot="button" className={classes} {...props}>
            {children}
        </button>
    );
}

// Mirrors frontend/src/components/ui/input.jsx (input.ui-input).
export function Input({ className = '', type, ...props }) {
    return (
        <input
            type={type}
            data-slot="input"
            className={['ui-input', className].filter(Boolean).join(' ')}
            {...props}
        />
    );
}

// Mirrors frontend/src/components/ui/label.jsx (Radix Label.Root renders a
// plain <label class="ui-label">).
export function Label({ className = '', children, ...props }) {
    return (
        <label
            data-slot="label"
            className={['ui-label', className].filter(Boolean).join(' ')}
            {...props}
        >
            {children}
        </label>
    );
}

// Shared overlay scaffold mirroring frontend/src/components/ui/dialog.jsx's
// rendered markup (.ui-dialog-overlay + .ui-dialog-content). Closes on
// overlay click and Escape; rendered into a body portal like Radix does.
function DialogShell({ onClose, contentClassName, labelledBy, children }) {
    useEffect(() => {
        const onKey = (e) => { if (e.key === 'Escape') onClose?.(); };
        document.addEventListener('keydown', onKey);
        return () => document.removeEventListener('keydown', onKey);
    }, [onClose]);

    return createPortal(
        <>
            <div className="ui-dialog-overlay" onClick={onClose} />
            <div
                role="dialog"
                aria-modal="true"
                aria-labelledby={labelledBy}
                className={contentClassName}
            >
                {children}
            </div>
        </>,
        document.body,
    );
}

// Mirrors frontend/src/components/Modal.jsx (which wraps ui/dialog):
// .sk-modal--<size> picks the max-width; header/body/footer classes are the
// host's .sk-modal__* block.
export function Modal({
    open,
    onClose,
    title,
    children,
    footer,
    className = '',
    size = 'md',
}) {
    const { t } = useTranslation();
    if (!open) return null;
    return (
        <DialogShell
            onClose={onClose}
            contentClassName={`ui-dialog-content sk-modal sk-modal--${size}${className ? ` ${className}` : ''}`}
        >
            {title && (
                <div className="sk-modal__header">
                    <h2 className="ui-dialog-title">{title}</h2>
                </div>
            )}
            <button type="button" className="ui-dialog-close" onClick={onClose}>
                <X />
                <span className="sr-only">{t('tramo.primitives.close', 'Close')}</span>
            </button>
            <div className="sk-modal__body">{children}</div>
            {footer && <div className="sk-modal__footer">{footer}</div>}
        </DialogShell>
    );
}

const CONFIRM_ICONS = { danger: AlertTriangle, warning: AlertCircle, info: Info };

// Mirrors frontend/src/components/ConfirmDialog.jsx (which wraps
// ui/alert-dialog): .sk-confirm content card with the icon head, title,
// description and a footer holding outline cancel + variant action buttons.
// The host usage renders it conditionally, so mounting == open; `isOpen`
// (default true) is honoured for parity with the host prop.
export function ConfirmDialog({
    isOpen = true,
    title,
    message,
    details,
    confirmText = 'Confirm',
    cancelText = 'Cancel',
    variant = 'danger',
    onConfirm,
    onCancel,
}) {
    if (!isOpen) return null;
    const Icon = CONFIRM_ICONS[variant] || AlertTriangle;
    return (
        <DialogShell onClose={onCancel} contentClassName="ui-dialog-content sk-confirm">
            <div className="ui-dialog-header">
                <div className="sk-confirm__head">
                    <div className={`sk-confirm__icon sk-confirm__icon--${variant}`}>
                        <Icon size={24} />
                    </div>
                    <div className="sk-confirm__body">
                        <h2 className="ui-dialog-title">{title}</h2>
                        {message && <p className="ui-dialog-description">{message}</p>}
                        {details && <p className="sk-confirm__details">{details}</p>}
                    </div>
                </div>
            </div>
            <div className="ui-dialog-footer sk-confirm__footer">
                <Button variant="outline" onClick={onCancel}>{cancelText}</Button>
                <Button
                    variant={variant === 'danger' ? 'destructive' : 'primary'}
                    onClick={onConfirm}
                >
                    {confirmText}
                </Button>
            </div>
        </DialogShell>
    );
}

// Mirrors the host Skeleton's rendered markup (span.skeleton.skeleton--*).
function Skeleton({ variant = 'line', width }) {
    return (
        <span
            className={`skeleton skeleton--${variant}`}
            style={width != null ? { width: typeof width === 'number' ? `${width}px` : width } : undefined}
            aria-hidden="true"
        />
    );
}

// Mirrors frontend/src/components/EmptyState.jsx's rendered markup so the host
// .empty-state / .skeleton-panel styles apply unchanged.
export function EmptyState({
    icon: Icon = Inbox,
    title = 'No items found',
    description = '',
    action = null,
    size = 'default',
    loading = false,
}) {
    const { t } = useTranslation();
    if (loading) {
        return (
            <div
                className={`empty-state empty-state--${size} empty-state--loading`}
                role="status"
                aria-busy="true"
                aria-label={title || t('tramo.primitives.loading', 'Loading')}
            >
                <div className="skeleton-panel">
                    <div className="skeleton-panel__head">
                        <Skeleton variant="avatar" />
                        <div className="skeleton-panel__head-text">
                            <Skeleton variant="title" width="42%" />
                            <Skeleton variant="line" width="26%" />
                        </div>
                    </div>
                    <div className="skeleton-panel__cards">
                        <Skeleton variant="card" />
                        <Skeleton variant="card" />
                        <Skeleton variant="card" />
                    </div>
                    <div className="skeleton-panel__rows">
                        <Skeleton variant="line" width="100%" />
                        <Skeleton variant="line" width="92%" />
                        <Skeleton variant="line" width="76%" />
                    </div>
                </div>
            </div>
        );
    }

    return (
        <div className={`empty-state empty-state--${size}`}>
            <div className="empty-state__icon">
                <Icon size={size === 'lg' ? 64 : 48} />
            </div>
            <h3 className="empty-state__title">{title}</h3>
            {description && (
                <p className="empty-state__description">{description}</p>
            )}
            {action && (
                <div className="empty-state__action">{action}</div>
            )}
        </div>
    );
}
