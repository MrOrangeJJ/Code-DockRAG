/**
 * main.js - 应用程序入口
 * 初始化所有模块，添加全局事件处理
 */

document.addEventListener('DOMContentLoaded', () => {
    console.log("DOM内容加载完成，初始化应用...");
    
    // 配置信息 - 从服务器注入的配置中获取API端口
    const config = {
        // 优先使用服务器注入的配置，如果不存在则使用默认值
        // API_BASE_URL: window.CODE_DOCK_CONFIG ? 
        //     `${window.location.protocol}//${window.location.hostname}:${window.CODE_DOCK_CONFIG.API_PORT}` : 
        //     `${window.location.protocol}//${window.location.hostname}:30089`,
        // WEB_API_BASE_URL: window.CODE_DOCK_CONFIG ? 
        //     `${window.location.protocol}//${window.location.hostname}:${window.CODE_DOCK_CONFIG.API_PORT}` : 
        //     `${window.location.protocol}//${window.location.hostname}:30089`
        API_BASE_URL: `${window.location.protocol}//${window.location.hostname}:${window.CODE_DOCK_CONFIG.API_PORT}`,
        WEB_API_BASE_URL: `${window.location.protocol}//${window.location.hostname}:${window.CODE_DOCK_CONFIG.API_PORT}`
    };

    // 预加载所有CSS文件，确保所有组件可用
    function preloadCSS() {
        const cssComponents = [
            'variables.css',
            'base.css', 
            'layout.css',
            'forms.css',
            'buttons.css',
            'cards.css',
            'modals.css',
            'explorer.css'
        ];
        
        cssComponents.forEach(file => {
            const link = document.createElement('link');
            link.rel = 'preload';
            link.href = `/static/css/components/${file}`;
            link.as = 'style';
            document.head.appendChild(link);
        });
    }
    
    // 预加载CSS
    preloadCSS();

    // 初始化模块
    CodebaseManager.init(config);
    Search.init(config);
    StrongSearch.init(config);
    FileExplorer.init(config);
    AstViewer.init(config);
    Settings.init(config);

    // 添加全局按钮点击波纹效果
    document.addEventListener('click', UI.addRippleEffect);

    // Escape 键关闭所有模态框
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            const openModalHandlers = {
                'file-explorer-modal': FileExplorer.closeModal,
                'ast-view-modal': AstViewer.closeModal,
                'search-modal': Search.closeModal,
                'strong-search-modal': StrongSearch.closeModal,
                'settings-modal': Settings.closeSettingsModal
            };
            
            // 检查所有可能打开的模态框
            for (const [modalId, closeHandler] of Object.entries(openModalHandlers)) {
                const modal = document.getElementById(modalId);
                if (modal && modal.classList.contains('open')) {
                    closeHandler();
                    break; // 一次只关闭一个模态框
                }
            }
        }
    });

    // 通用模态框背景点击关闭事件
    window.addEventListener('click', (e) => {
        if (e.target.classList.contains('modal')) {
            const openModalHandlers = {
                'file-explorer-modal': FileExplorer.closeModal,
                'ast-view-modal': AstViewer.closeModal,
                'search-modal': Search.closeModal,
                'strong-search-modal': StrongSearch.closeModal,
                'settings-modal': Settings.closeSettingsModal
            };
            
            const modalId = e.target.id;
            if (openModalHandlers[modalId]) {
                openModalHandlers[modalId]();
            }
        }
    });

    // 其他辅助功能按钮
    const refreshCodebasesBtn = document.getElementById('refresh-codebases');
    if (refreshCodebasesBtn) {
        refreshCodebasesBtn.addEventListener('click', CodebaseManager.fetchCodebases);
    }

    const uploadFirstCodebaseBtn = document.getElementById('upload-first-codebase');
    if (uploadFirstCodebaseBtn) {
        uploadFirstCodebaseBtn.addEventListener('click', () => {
            // 滚动到上传表单
            const uploadSection = document.querySelector('.upload-section');
            if (uploadSection) {
                uploadSection.scrollIntoView({ behavior: 'smooth' });
            }
        });
    }

    // 显示API地址
    const apiUrlDisplay = document.getElementById('api-url');
    if (apiUrlDisplay) {
        apiUrlDisplay.textContent = config.API_BASE_URL || '未配置';
    }

    console.log("应用程序初始化完成");
}); 