/**
 * 用户体验优化模块
 * 提供加载状态、操作反馈、快捷操作等
 */

class UXEnhancements {
    constructor() {
        this.loadingStates = new Map();
        this.notifications = [];
        this.init();
    }

    init() {
        // 创建全局加载指示器
        this.createGlobalLoader();
        // 创建通知容器
        this.createNotificationContainer();
        // 绑定快捷键
        this.bindKeyboardShortcuts();
        // 自动保存草稿
        this.initAutoSave();
    }

    // ============================================================
    // 全局加载状态
    // ============================================================

    createGlobalLoader() {
        const loader = document.createElement('div');
        loader.id = 'globalLoader';
        loader.innerHTML = `
            <div class="loader-overlay">
                <div class="loader-spinner">
                    <div class="spinner"></div>
                    <div class="loader-text">加载中...</div>
                </div>
            </div>
        `;
        loader.style.cssText = `
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            z-index: 99999;
            display: none;
        `;

        const style = document.createElement('style');
        style.textContent = `
            .loader-overlay {
                position: absolute;
                top: 0;
                left: 0;
                right: 0;
                bottom: 0;
                background: rgba(15, 23, 42, 0.8);
                backdrop-filter: blur(4px);
                display: flex;
                align-items: center;
                justify-content: center;
            }
            .loader-spinner {
                text-align: center;
            }
            .spinner {
                width: 48px;
                height: 48px;
                border: 4px solid rgba(99, 102, 241, 0.2);
                border-top-color: #6366f1;
                border-radius: 50%;
                animation: spin 1s linear infinite;
                margin: 0 auto 16px;
            }
            @keyframes spin {
                to { transform: rotate(360deg); }
            }
            .loader-text {
                color: #e2e8f0;
                font-size: 14px;
                font-weight: 500;
            }
        `;

        document.head.appendChild(style);
        document.body.appendChild(loader);
        this.globalLoader = loader;
    }

    showGlobalLoader(text = '加载中...') {
        const loader = document.getElementById('globalLoader');
        const loaderText = loader.querySelector('.loader-text');
        loaderText.textContent = text;
        loader.style.display = 'block';
    }

    hideGlobalLoader() {
        const loader = document.getElementById('globalLoader');
        loader.style.display = 'none';
    }

    // ============================================================
    // 按钮加载状态
    // ============================================================

    setButtonLoading(button, loading = true) {
        if (typeof button === 'string') {
            button = document.querySelector(button);
        }

        if (!button) return;

        if (loading) {
            button.dataset.originalText = button.innerHTML;
            button.disabled = true;
            button.innerHTML = `
                <span class="spinner-border spinner-border-sm me-2" role="status"></span>
                处理中...
            `;
        } else {
            button.disabled = false;
            button.innerHTML = button.dataset.originalText || button.innerHTML;
        }
    }

    // ============================================================
    // 通知系统
    // ============================================================

    createNotificationContainer() {
        const container = document.createElement('div');
        container.id = 'notificationContainer';
        container.style.cssText = `
            position: fixed;
            top: 20px;
            right: 20px;
            z-index: 10000;
            display: flex;
            flex-direction: column;
            gap: 10px;
            max-width: 400px;
        `;
        document.body.appendChild(container);
        this.notificationContainer = container;
    }

    showNotification(message, type = 'info', duration = 3000) {
        const id = Date.now();
        const notification = document.createElement('div');
        notification.id = `notification-${id}`;

        const icons = {
            success: '✅',
            error: '❌',
            warning: '⚠️',
            info: 'ℹ️'
        };

        const colors = {
            success: { bg: '#d1fae5', border: '#10b981', text: '#065f46' },
            error: { bg: '#fee2e2', border: '#ef4444', text: '#991b1b' },
            warning: { bg: '#fef3c7', border: '#f59e0b', text: '#92400e' },
            info: { bg: '#dbeafe', border: '#3b82f6', text: '#1e40af' }
        };

        const color = colors[type] || colors.info;

        notification.innerHTML = `
            <div style="
                background: ${color.bg};
                border: 1px solid ${color.border};
                border-radius: 8px;
                padding: 12px 16px;
                display: flex;
                align-items: flex-start;
                gap: 12px;
                box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
                animation: slideInRight 0.3s ease-out;
            ">
                <span style="font-size: 18px;">${icons[type]}</span>
                <div style="flex: 1;">
                    <div style="font-weight: 600; color: ${color.text}; margin-bottom: 4px;">
                        ${type.charAt(0).toUpperCase() + type.slice(1)}
                    </div>
                    <div style="color: ${color.text}; font-size: 14px; opacity: 0.9;">
                        ${message}
                    </div>
                </div>
                <button onclick="this.parentElement.parentElement.remove()" style="
                    background: none;
                    border: none;
                    color: ${color.text};
                    cursor: pointer;
                    font-size: 18px;
                    opacity: 0.7;
                    padding: 0;
                ">×</button>
            </div>
        `;

        this.notificationContainer.appendChild(notification);

        // 自动移除
        if (duration > 0) {
            setTimeout(() => {
                if (notification.parentElement) {
                    notification.style.animation = 'slideOutRight 0.3s ease-in';
                    setTimeout(() => notification.remove(), 300);
                }
            }, duration);
        }

        return id;
    }

    removeNotification(id) {
        const notification = document.getElementById(`notification-${id}`);
        if (notification) {
            notification.remove();
        }
    }

    // ============================================================
    // 确认对话框
    // ============================================================

    showConfirm(title, message, onConfirm, onCancel) {
        const modal = document.createElement('div');
        modal.innerHTML = `
            <div class="modal fade show" style="display: block; background: rgba(0,0,0,0.5);">
                <div class="modal-dialog modal-dialog-centered">
                    <div class="modal-content" style="background: #1e293b; border: 1px solid #334155; border-radius: 12px;">
                        <div class="modal-header" style="border-bottom: 1px solid #334155;">
                            <h5 class="modal-title" style="color: #f1f5f9;">${title}</h5>
                            <button type="button" class="btn-close" onclick="this.closest('.modal').remove()"></button>
                        </div>
                        <div class="modal-body">
                            <p style="color: #cbd5e1; margin: 0;">${message}</p>
                        </div>
                        <div class="modal-footer" style="border-top: 1px solid #334155;">
                            <button type="button" class="btn btn-secondary" onclick="this.closest('.modal').remove()">
                                取消
                            </button>
                            <button type="button" class="btn btn-primary" id="confirmBtn">
                                确认
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        `;

        document.body.appendChild(modal);

        const confirmBtn = modal.querySelector('#confirmBtn');
        confirmBtn.addEventListener('click', () => {
            modal.remove();
            if (onConfirm) onConfirm();
        });

        modal.querySelector('.btn-secondary').addEventListener('click', () => {
            modal.remove();
            if (onCancel) onCancel();
        });
    }

    // ============================================================
    // 进度条
    // ============================================================

    showProgress(title, progress = 0) {
        let progressModal = document.getElementById('progressModal');

        if (!progressModal) {
            progressModal = document.createElement('div');
            progressModal.id = 'progressModal';
            progressModal.innerHTML = `
                <div class="modal fade show" style="display: block; background: rgba(0,0,0,0.5);">
                    <div class="modal-dialog modal-dialog-centered">
                        <div class="modal-content" style="background: #1e293b; border: 1px solid #334155; border-radius: 12px;">
                            <div class="modal-body" style="padding: 24px;">
                                <h5 style="color: #f1f5f9; margin-bottom: 16px;" id="progressTitle">${title}</h5>
                                <div style="background: #334155; border-radius: 8px; height: 12px; overflow: hidden;">
                                    <div id="progressBar" style="
                                        background: linear-gradient(90deg, #6366f1, #818cf8);
                                        height: 100%;
                                        width: ${progress}%;
                                        transition: width 0.3s ease;
                                        border-radius: 8px;
                                    "></div>
                                </div>
                                <div style="display: flex; justify-content: space-between; margin-top: 8px;">
                                    <span style="color: #94a3b8; font-size: 14px;" id="progressText">${progress}%</span>
                                    <span style="color: #94a3b8; font-size: 14px;" id="progressStatus">处理中...</span>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            `;
            document.body.appendChild(progressModal);
        }

        return {
            update: (newProgress, status) => {
                const bar = document.getElementById('progressBar');
                const text = document.getElementById('progressText');
                const statusEl = document.getElementById('progressStatus');
                const titleEl = document.getElementById('progressTitle');

                if (bar) bar.style.width = `${newProgress}%`;
                if (text) text.textContent = `${newProgress}%`;
                if (statusEl && status) statusEl.textContent = status;
                if (titleEl && title) titleEl.textContent = title;
            },
            complete: (message) => {
                const statusEl = document.getElementById('progressStatus');
                const bar = document.getElementById('progressBar');

                if (statusEl) statusEl.textContent = message || '完成';
                if (bar) {
                    bar.style.width = '100%';
                    bar.style.background = 'linear-gradient(90deg, #10b981, #34d399)';
                }

                setTimeout(() => {
                    const modal = document.getElementById('progressModal');
                    if (modal) modal.remove();
                }, 1500);
            },
            close: () => {
                const modal = document.getElementById('progressModal');
                if (modal) modal.remove();
            }
        };
    }

    // ============================================================
    // 快捷键
    // ============================================================

    bindKeyboardShortcuts() {
        document.addEventListener('keydown', (e) => {
            // Ctrl + R: 刷新数据
            if (e.ctrlKey && e.key === 'r') {
                e.preventDefault();
                if (typeof refreshAll === 'function') {
                    refreshAll();
                }
            }

            // Ctrl + H: 健康检查
            if (e.ctrlKey && e.key === 'h') {
                e.preventDefault();
                if (typeof batchHealthCheck === 'function') {
                    batchHealthCheck();
                }
            }

            // Ctrl + T: 打开终端
            if (e.ctrlKey && e.key === 't') {
                e.preventDefault();
                const terminalInput = document.getElementById('terminalInput');
                if (terminalInput) {
                    terminalInput.focus();
                }
            }

            // Escape: 关闭模态框
            if (e.key === 'Escape') {
                const modals = document.querySelectorAll('.modal.show');
                modals.forEach(modal => {
                    const closeBtn = modal.querySelector('.btn-close');
                    if (closeBtn) closeBtn.click();
                });
            }
        });
    }

    // ============================================================
    // 自动保存
    // ============================================================

    initAutoSave() {
        // 自动保存表单数据
        const forms = document.querySelectorAll('form[data-autosave]');
        forms.forEach(form => {
            const inputs = form.querySelectorAll('input, textarea, select');
            inputs.forEach(input => {
                // 恢复保存的数据
                const savedValue = localStorage.getItem(`autosave_${input.name}`);
                if (savedValue) {
                    input.value = savedValue;
                }

                // 监听变化
                input.addEventListener('change', () => {
                    localStorage.setItem(`autosave_${input.name}`, input.value);
                });
            });
        });
    }

    // ============================================================
    // 工具函数
    // ============================================================

    formatBytes(bytes, decimals = 2) {
        if (bytes === 0) return '0 Bytes';
        const k = 1024;
        const dm = decimals < 0 ? 0 : decimals;
        const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + ' ' + sizes[i];
    }

    formatDuration(seconds) {
        if (seconds < 60) return `${seconds}秒`;
        if (seconds < 3600) return `${Math.floor(seconds / 60)}分${seconds % 60}秒`;
        return `${Math.floor(seconds / 3600)}时${Math.floor((seconds % 3600) / 60)}分`;
    }

    copyToClipboard(text) {
        if (navigator.clipboard) {
            navigator.clipboard.writeText(text).then(() => {
                this.showNotification('已复制到剪贴板', 'success');
            });
        } else {
            const textarea = document.createElement('textarea');
            textarea.value = text;
            document.body.appendChild(textarea);
            textarea.select();
            document.execCommand('copy');
            document.body.removeChild(textarea);
            this.showNotification('已复制到剪贴板', 'success');
        }
    }

    debounce(func, wait) {
        let timeout;
        return function executedFunction(...args) {
            const later = () => {
                clearTimeout(timeout);
                func(...args);
            };
            clearTimeout(timeout);
            timeout = setTimeout(later, wait);
        };
    }

    throttle(func, limit) {
        let inThrottle;
        return function(...args) {
            if (!inThrottle) {
                func.apply(this, args);
                inThrottle = true;
                setTimeout(() => inThrottle = false, limit);
            }
        };
    }
}

// ============================================================
// 添加动画样式
// ============================================================

const animationStyles = document.createElement('style');
animationStyles.textContent = `
    @keyframes slideInRight {
        from {
            transform: translateX(100%);
            opacity: 0;
        }
        to {
            transform: translateX(0);
            opacity: 1;
        }
    }

    @keyframes slideOutRight {
        from {
            transform: translateX(0);
            opacity: 1;
        }
        to {
            transform: translateX(100%);
            opacity: 0;
        }
    }

    @keyframes fadeIn {
        from { opacity: 0; }
        to { opacity: 1; }
    }

    @keyframes fadeOut {
        from { opacity: 1; }
        to { opacity: 0; }
    }

    @keyframes slideUp {
        from {
            transform: translateY(20px);
            opacity: 0;
        }
        to {
            transform: translateY(0);
            opacity: 1;
        }
    }

    @keyframes pulse {
        0%, 100% { opacity: 1; }
        50% { opacity: 0.5; }
    }

    .animate-fade-in {
        animation: fadeIn 0.3s ease-out;
    }

    .animate-slide-up {
        animation: slideUp 0.3s ease-out;
    }

    .animate-pulse {
        animation: pulse 2s infinite;
    }
`;
document.head.appendChild(animationStyles);

// ============================================================
// 全局实例
// ============================================================

const ux = new UXEnhancements();

// 导出
window.UXEnhancements = UXEnhancements;
window.ux = ux;

// 便捷方法
window.showNotification = (msg, type, duration) => ux.showNotification(msg, type, duration);
window.showConfirm = (title, msg, onConfirm, onCancel) => ux.showConfirm(title, msg, onConfirm, onCancel);
window.showProgress = (title, progress) => ux.showProgress(title, progress);
window.showGlobalLoader = (text) => ux.showGlobalLoader(text);
window.hideGlobalLoader = () => ux.hideGlobalLoader();
window.setButtonLoading = (btn, loading) => ux.setButtonLoading(btn, loading);
window.copyToClipboard = (text) => ux.copyToClipboard(text);
