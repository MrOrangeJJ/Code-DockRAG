/**
 * ast-viewer.js - AST树查看器模块
 * 处理代码AST树结构查看功能
 */

// AST树查看器模块
const AstViewer = (function() {
    // 私有变量
    let currentAstCodebase = null;
    
    let astViewModal;
    let astModalClose;
    let astCodebaseNameEl;
    let astLoading;
    let astError;
    let astContent;
    let astTreeContainer;
    let astStatFiles;
    let astStatLanguages;
    let astLanguagesContainer;
    
    let API_BASE_URL;

    // 初始化函数
    function init(config) {
        // 保存配置
        API_BASE_URL = config.API_BASE_URL;
        
        // 初始化DOM元素引用
        astViewModal = document.getElementById('ast-view-modal');
        astModalClose = document.getElementById('ast-modal-close');
        astCodebaseNameEl = document.getElementById('ast-codebase-name');
        astLoading = document.getElementById('ast-loading');
        astError = document.getElementById('ast-error');
        astContent = document.getElementById('ast-content');
        astTreeContainer = document.getElementById('ast-tree-container');
        astStatFiles = document.getElementById('ast-stat-files');
        astStatLanguages = document.getElementById('ast-stat-languages');
        astLanguagesContainer = document.getElementById('ast-languages-container');
        
        // 绑定事件
        bindEvents();
    }

    // 事件绑定
    function bindEvents() {
        // AST树视图模态框关闭按钮
        if (astModalClose) {
            astModalClose.addEventListener('click', closeModal);
        }
        
        // AST树视图模态框背景点击关闭
        if (astViewModal) {
            astViewModal.addEventListener('click', (e) => {
                if (e.target === astViewModal) {
                    closeModal();
                }
            });
        }
    }
    
    // 打开AST树视图模态框
    function openModal(codebaseName) {
        if (!astViewModal) return;
        
        currentAstCodebase = codebaseName;
        astCodebaseNameEl.textContent = codebaseName;
        
        // 重置视图
        astError.classList.add('hidden');
        astContent.classList.add('hidden');
        astTreeContainer.innerHTML = '';
        
        // 显示加载状态
        UI.toggleLoading(astLoading, true);
        
        // 加载AST树结构
        loadAstStructure();
        
        UI.openModal(astViewModal);
    }
    
    // 关闭AST树视图模态框
    function closeModal() {
        UI.closeModal(astViewModal);
        currentAstCodebase = null;
    }
    
    // 加载AST树结构
    async function loadAstStructure() {
        if (!astTreeContainer || !currentAstCodebase) return;
        
        try {
            const response = await fetch(`${API_BASE_URL}/codebases/${currentAstCodebase}/ast`);
            
            if (!response.ok) {
                throw new Error(`API Error: ${response.status} ${response.statusText}`);
            }
            
            const result = await response.json();
            renderAstStructure(result.structure);
        } catch (error) {
            console.error('Error loading AST structure:', error);
            astError.classList.remove('hidden');
            astError.querySelector('p').textContent = `加载AST树结构时出错: ${error.message}`;
        } finally {
            UI.toggleLoading(astLoading, false);
        }
    }
    
    // 渲染AST树结构
    function renderAstStructure(structure) {
        if (!astTreeContainer || !astContent) return;
        
        // 显示内容区域
        astContent.classList.remove('hidden');
        
        // 更新统计信息
        if (astStatFiles) {
            astStatFiles.textContent = structure.file_count || 0;
        }
        
        // 更新语言分布
        if (astStatLanguages && structure.languages) {
            const languages = structure.languages;
            if (Object.keys(languages).length > 0) {
                const languageList = Object.entries(languages).map(([lang, count]) => {
                    return `<span class="ast-language-tag">${Utils.escapeHtml(lang)}: ${count}</span>`;
                }).join(' ');
                astStatLanguages.innerHTML = languageList;
                astLanguagesContainer.classList.remove('hidden');
            } else {
                astLanguagesContainer.classList.add('hidden');
            }
        }
        
        // 渲染文件列表
        astTreeContainer.innerHTML = '';
        
        if (!structure.files || structure.files.length === 0) {
            astTreeContainer.innerHTML = '<div class="empty-state"><i class="fas fa-exclamation-triangle"></i><p>没有找到可分析的文件</p></div>';
            return;
        }
        
        const container = document.createElement('div');
        container.className = 'ast-tree';
        
        structure.files.forEach((file) => {
            const fileItem = document.createElement('div');
            fileItem.className = 'ast-file-item';
            
            // 文件头
            const fileHeader = document.createElement('div');
            fileHeader.className = 'ast-file-header';
            fileHeader.innerHTML = `
                <div class="ast-file-name">${Utils.escapeHtml(file.path)}</div>
                <span class="ast-language-tag">${Utils.escapeHtml(file.language)}</span>
            `;
            fileItem.appendChild(fileHeader);
            
            // 文件内容 - 类和方法
            const fileContent = document.createElement('div');
            fileContent.className = 'ast-tree';
            
            // 渲染类
            if (file.classes && file.classes.length > 0) {
                file.classes.forEach((cls) => {
                    const classNode = document.createElement('div');
                    classNode.className = 'ast-node';
                    
                    const classHeader = document.createElement('div');
                    classHeader.className = 'ast-node-header';
                    classHeader.innerHTML = `
                        <span class="ast-node-type">class</span>
                        <span class="ast-node-name">${Utils.escapeHtml(cls.name)}</span>
                        <span class="ast-node-line">行 ${cls.line}</span>
                    `;
                    classNode.appendChild(classHeader);
                    
                    // 类方法
                    if (cls.methods && cls.methods.length > 0) {
                        const methodsContainer = document.createElement('div');
                        methodsContainer.className = 'ast-node-content';
                        
                        cls.methods.forEach((method) => {
                            const methodNode = document.createElement('div');
                            methodNode.className = 'ast-node-leaf';
                            methodNode.innerHTML = `
                                <span class="ast-node-type">method</span>
                                <span class="ast-node-name">${Utils.escapeHtml(method.name)}</span>
                                <span class="ast-node-line">行 ${method.line}</span>
                            `;
                            methodsContainer.appendChild(methodNode);
                        });
                        
                        classNode.appendChild(methodsContainer);
                    }
                    
                    fileContent.appendChild(classNode);
                });
            }
            
            // 渲染顶级方法
            if (file.methods && file.methods.length > 0) {
                file.methods.forEach((method) => {
                    const methodNode = document.createElement('div');
                    methodNode.className = 'ast-node-leaf';
                    methodNode.innerHTML = `
                        <span class="ast-node-type">function</span>
                        <span class="ast-node-name">${Utils.escapeHtml(method.name)}</span>
                        <span class="ast-node-line">行 ${method.line}</span>
                    `;
                    fileContent.appendChild(methodNode);
                });
            }
            
            fileItem.appendChild(fileContent);
            container.appendChild(fileItem);
        });
        
        astTreeContainer.appendChild(container);
        
        // 添加节点折叠/展开交互
        const nodeHeaders = astTreeContainer.querySelectorAll('.ast-node-header');
        nodeHeaders.forEach((header) => {
            header.addEventListener('click', () => {
                const node = header.closest('.ast-node');
                node.classList.toggle('collapsed');
            });
        });
    }

    // 对外暴露API
    return {
        init,
        openModal,
        closeModal,
        loadAstStructure
    };
})();

// 将模块添加到全局命名空间
window.AstViewer = AstViewer; 