/**
 * codebase-manager.js - 代码库管理模块
 * 处理代码库列表、上传、删除等功能
 */

// 代码库管理模块
const CodebaseManager = (function() {
    // 私有变量
    let codebasesGrid;
    let codebasesLoading;
    let noCodebasesEl;
    let manageStatusDiv;
    let uploadForm;
    let uploadStatusDiv;
    let fileInput;
    let fileNameDisplay;
    let API_BASE_URL;
    let WEB_API_BASE_URL;
    let indexingPolls = {}; // 存储索引状态轮询的定时器ID

    // 初始化函数
    function init(config) {
        // 保存配置
        API_BASE_URL = config.API_BASE_URL;
        WEB_API_BASE_URL = config.WEB_API_BASE_URL;
        
        // 初始化DOM元素引用
        codebasesGrid = document.getElementById('codebases-grid');
        codebasesLoading = document.getElementById('codebases-loading');
        noCodebasesEl = document.getElementById('no-codebases');
        manageStatusDiv = document.getElementById('manage-status');
        uploadForm = document.getElementById('upload-form');
        uploadStatusDiv = document.getElementById('upload-status');
        fileInput = document.getElementById('codebase-file');
        fileNameDisplay = document.getElementById('file-name-display');
        
        // 绑定事件
        bindEvents();

        // 在初始化时加载代码库列表
        fetchCodebases();
    }

    // 事件绑定
    function bindEvents() {
        // 文件选择事件
        if (fileInput) {
            fileInput.addEventListener('change', handleFileSelect);
        }
        
        // 上传表单提交
        if (uploadForm) {
            uploadForm.addEventListener('submit', handleUploadFormSubmit);
        }
        
        // 代码库网格点击事件委托
        if (codebasesGrid) {
            codebasesGrid.addEventListener('click', handleCodebaseGridClick);
        }
        
        // 刷新按钮点击事件
        const refreshButton = document.getElementById('refresh-codebases');
        if (refreshButton) {
            refreshButton.addEventListener('click', fetchCodebases);
        }
    }

    // 文件选择处理
    function handleFileSelect() {
        const wrapper = fileInput.closest('.file-upload-wrapper');
        
        if (fileInput.files && fileInput.files.length > 0) {
            const fileName = fileInput.files[0].name;
            if (fileNameDisplay) {
                fileNameDisplay.textContent = fileName;
            }
            wrapper.classList.add('has-file');
        } else {
            if (fileNameDisplay) {
                fileNameDisplay.textContent = '未选择文件';
            }
            wrapper.classList.remove('has-file');
        }
    }

    // 上传表单提交处理
    async function handleUploadFormSubmit(e) {
        e.preventDefault();
        
        const formData = new FormData(uploadForm);
        const codebaseName = formData.get('name');
        
        if (!fileInput || !fileInput.files || fileInput.files.length === 0) {
            UI.showStatus(uploadStatusDiv, '请选择ZIP文件', 'error');
            return;
        }
        
        if (!codebaseName || !codebaseName.trim()) {
            UI.showStatus(uploadStatusDiv, '请输入代码库名称', 'error');
            return;
        }
        
        UI.showStatus(uploadStatusDiv, '正在上传，请稍候...', 'info');
        
        try {
            const response = await fetch(`${WEB_API_BASE_URL}/codebases`, {
                method: 'POST',
                body: formData,
            });
            
            const result = await response.json();
            
            if (response.ok) {
                UI.showStatus(uploadStatusDiv, `代码库 '${result.codebase_name}' 上传成功，请在卡片中点击"索引"按钮开始索引`, 'success');
                uploadForm.reset();
                
                // 重置文件上传显示
                const wrapper = fileInput.closest('.file-upload-wrapper');
                if (wrapper) {
                    wrapper.classList.remove('has-file');
                }
                if (fileNameDisplay) {
                    fileNameDisplay.textContent = '未选择文件';
                }
                
                fetchCodebases(); // 刷新列表
            } else {
                throw new Error(result.detail || '上传失败');
            }
        } catch (error) {
            console.error('Upload error:', error);
            UI.showStatus(uploadStatusDiv, `上传失败: ${error.message}`, 'error');
        }
    }

    // 代码库网格点击处理
    async function handleCodebaseGridClick(e) {
        // 找到最近的按钮，不管是什么标签（button或a）
        const button = e.target.closest('button[data-name], a[data-name]'); 
        if (!button) return;
        
        const codebaseName = button.dataset.name;
        if (!codebaseName) return;
        
        if (button.classList.contains('search-btn')) {
            Search.openModal(codebaseName);
        } else if (button.classList.contains('strong-search-btn')) {
            StrongSearch.openModal(codebaseName);
        } else if (button.classList.contains('browse-btn')) {
            FileExplorer.openModal(codebaseName);
        } else if (button.classList.contains('ast-btn')) {
            AstViewer.openModal(codebaseName);
        } else if (button.classList.contains('index-btn')) {
            await handleReindexCodebase(codebaseName);
        } else if (button.classList.contains('delete-btn')) {
            await handleDeleteCodebase(codebaseName);
        }
    }

    // 重新索引代码库
    async function handleReindexCodebase(codebaseName) {
        if (confirm(`确定要${isIndexing(codebaseName) ? '重新开始' : '开始'}索引代码库 "${codebaseName}" 吗？`)) {
            UI.showStatus(manageStatusDiv, `正在为 ${codebaseName} 触发索引...`, 'info');
            try {
                // 在发送请求前先更新UI状态，避免需要等待后端更新
                updateCardStatus(codebaseName, true, false, false, 0);
                
                // 设置轮询来检查索引状态 - 提前开始轮询
                startPollingIndexStatus(codebaseName);
                
                const response = await fetch(`${WEB_API_BASE_URL}/codebases/${codebaseName}/index`, { method: 'POST' });
                const result = await response.json();
                
                if (response.ok) {
                    // 请求成功，状态UI已提前更新，无需再次更新
                    UI.showStatus(manageStatusDiv, `已触发 ${codebaseName} 的索引过程，请等待完成`, 'success');
                } else {
                    // 如果请求失败，恢复UI状态
                    updateCardStatus(codebaseName, false, false, false, 0);
                    clearInterval(indexingPolls[codebaseName]);
                    delete indexingPolls[codebaseName];
                    throw new Error(result.message || '触发索引失败');
                }
            } catch (error) {
                // 出错时也要恢复UI状态
                updateCardStatus(codebaseName, false, false, false, 0);
                if (indexingPolls[codebaseName]) {
                    clearInterval(indexingPolls[codebaseName]);
                    delete indexingPolls[codebaseName];
                }
                UI.showStatus(manageStatusDiv, `为 ${codebaseName} 触发索引失败: ${error.message}`, 'error');
            }
        }
    }
    
    // 开始轮询索引状态
    function startPollingIndexStatus(codebaseName) {
        // 如果已有轮询，先清除
        if (indexingPolls[codebaseName]) {
            clearInterval(indexingPolls[codebaseName]);
        }
        
        console.log(`开始轮询 ${codebaseName} 的索引状态`);
        
        // 创建新的轮询间隔
        indexingPolls[codebaseName] = setInterval(async () => {
            try {
                // 获取代码库信息
                const response = await fetch(`${API_BASE_URL}/codebases`);
                if (!response.ok) {
                    throw new Error('获取代码库信息失败');
                }
                
                const codebases = await response.json();
                const codebase = codebases.find(cb => cb.name === codebaseName);
                
                if (!codebase) {
                    console.warn(`找不到代码库 ${codebaseName}，停止轮询`);
                    clearInterval(indexingPolls[codebaseName]);
                    delete indexingPolls[codebaseName];
                    return;
                }
                
                console.log(`代码库 ${codebaseName} 状态:`, codebase.indexing_status, codebase.indexed);
                
                // 始终更新卡片状态，确保LSP状态显示正确
                updateCardStatus(codebaseName, codebase.indexing_status === 'indexing', codebase.indexed, codebase.analyzer_ready, codebase.analyzer_progress || 0);
                
                // 检查是否可以停止轮询 - 只有在索引完成和LSP就绪时才停止
                if (codebase.indexing_status !== 'indexing' && codebase.analyzer_ready === true) {
                    console.log(`代码库 ${codebaseName} 索引已${codebase.indexed ? '完成' : '失败'}且LSP已就绪`);
                    clearInterval(indexingPolls[codebaseName]);
                    delete indexingPolls[codebaseName];
                    
                    // 更新整个列表以获取最新状态
                    fetchCodebases();
                }
            } catch (error) {
                console.error(`轮询 ${codebaseName} 索引状态出错:`, error);
            }
        }, 3000); // 每3秒检查一次
    }
    
    // 判断代码库是否正在索引
    function isIndexing(codebaseName) {
        return !!indexingPolls[codebaseName];
    }
    
    // 更新卡片的索引状态显示
    function updateCardStatus(codebaseName, isIndexing, indexed, analyzerReady, analyzerProgress) {
        const card = Array.from(document.querySelectorAll('.codebase-card')).find(
            card => card.dataset.name === codebaseName
        );
        
        if (!card) return;
        
        if (indexed) {
            card.classList.remove('non-indexed');
        } else {
            card.classList.add('non-indexed');
        }
        
        // 查找状态徽章
        let statusBadge = card.querySelector('.status-badge');
        
        if (isIndexing) {
            // 设置为索引中状态
            if (statusBadge) {
                statusBadge.className = 'status-badge indexing';
                statusBadge.innerHTML = '<span class="indexing-spinner"></span> 正在索引...';
            }
            
            // 禁用索引按钮
            const indexButton = card.querySelector('.index-btn');
            if (indexButton) {
                indexButton.disabled = true;
                indexButton.classList.add('disabled');
            }
        } else {
            // 索引完成或失败
            if (statusBadge) {
                statusBadge.className = `status-badge ${indexed ? 'indexed' : 'pending'}`;
                statusBadge.innerHTML = `<i class="fas ${indexed ? 'fa-check-circle' : 'fa-exclamation-circle'}"></i> ${indexed ? '已索引' : '索引失败'}`;
            }
            
            // 启用索引按钮
            const indexButton = card.querySelector('.index-btn');
            if (indexButton) {
                indexButton.disabled = false;
                indexButton.classList.remove('disabled');
            }
        }
        
        // 更新或添加LSP状态显示 - 无论是否正在索引都显示
        let lspStatusElem = card.querySelector('.lsp-status-badge');
        if (!lspStatusElem) {
            lspStatusElem = document.createElement('span');
            lspStatusElem.className = 'lsp-status-badge';
            // 找到codebase-status容器并添加LSP状态徽章
            const statusContainer = card.querySelector('.codebase-status');
            if (statusContainer) {
                statusContainer.appendChild(lspStatusElem);
            }
        }
        
        // 更新LSP状态 - 根据analyzerReady和analyzerProgress决定显示方式
        if (analyzerReady) {
            lspStatusElem.className = 'lsp-status-badge ready';
            lspStatusElem.innerHTML = '<i class="fas fa-check-circle"></i> LSP就绪';
        } else if (analyzerProgress > 0) {
            const progressPercent = Math.round(analyzerProgress * 100);
            lspStatusElem.className = 'lsp-status-badge preparing';
            lspStatusElem.innerHTML = `<i class="fas fa-spinner fa-spin"></i> LSP准备中 ${progressPercent}%`;
        } else {
            lspStatusElem.className = 'lsp-status-badge not-ready';
            lspStatusElem.innerHTML = '<i class="fas fa-times-circle"></i> LSP未就绪';
        }
    }

    // 删除代码库
    async function handleDeleteCodebase(codebaseName) {
        // 正在索引的代码库不能删除
        if (isIndexing(codebaseName)) {
            UI.showStatus(manageStatusDiv, `代码库 ${codebaseName} 正在索引中，无法删除`, 'error');
            return;
        }
        
        if (confirm(`确定要删除代码库 "${codebaseName}" 吗？此操作无法撤销。`)) {
            UI.showStatus(manageStatusDiv, `正在删除 ${codebaseName}...`, 'info');
            try {
                const response = await fetch(`${WEB_API_BASE_URL}/codebases/${codebaseName}`, { method: 'DELETE' });
                const result = await response.json();
                if (response.ok && result.success) {
                    UI.showStatus(manageStatusDiv, `代码库 ${codebaseName} 已删除`, 'success');
                    fetchCodebases();
                } else {
                    throw new Error(result.message || '删除失败');
                }
            } catch (error) {
                UI.showStatus(manageStatusDiv, `删除 ${codebaseName} 失败: ${error.message}`, 'error');
            }
        }
    }

    // 获取代码库列表
    async function fetchCodebases() {
        console.log("开始获取代码库列表...");
        
        if (!codebasesGrid) {
            console.error("错误: codebasesGrid元素不存在!");
            return;
        }
        
        UI.toggleLoading(codebasesLoading, true);
        
        try {
            console.log(`正在从 ${API_BASE_URL}/codebases 获取数据...`);
            const response = await fetch(`${API_BASE_URL}/codebases`);
            
            console.log("API响应状态:", response.status, response.statusText);
            
            if (!response.ok) {
                throw new Error(`API Error: ${response.status} ${response.statusText}`);
            }
            
            const codebases = await response.json();
            console.log("成功获取代码库数据:", codebases);
            
            renderCodebaseCards(codebases);
            
            // 检查哪些代码库正在索引，开始轮询
            codebases.forEach(codebase => {
                if (codebase.indexing_status === 'indexing' && !indexingPolls[codebase.name]) {
                    console.log(`发现正在索引的代码库: ${codebase.name}，开始轮询状态`);
                    startPollingIndexStatus(codebase.name);
                }
            });
        } catch (error) {
            console.error('获取代码库列表时出错:', error);
            console.error('错误详情:', error.stack);
            UI.showStatus(manageStatusDiv, `无法加载代码库列表: ${error.message}`, 'error');
        } finally {
            UI.toggleLoading(codebasesLoading, false);
        }
    }

    // 渲染代码库卡片
    function renderCodebaseCards(codebases) {
        if (!codebasesGrid) return;
        codebasesGrid.innerHTML = '';
        
        if (codebases.length === 0) {
            if (noCodebasesEl) noCodebasesEl.classList.remove('hidden');
            return;
        }
        
        if (noCodebasesEl) noCodebasesEl.classList.add('hidden');
        
        codebases.forEach((cb, index) => {
            const card = document.createElement('div');
            card.className = 'codebase-card';
            
            // 根据索引状态添加类名 - 只考虑indexed状态，不考虑轮询或indexing_status
            console.log("渲染卡片:", cb.name, "indexed =", cb.indexed);
            if (!cb.indexed) {
                card.classList.add('non-indexed');
            }
            
            card.classList.add(`delay-${(index % 5) * 100}`);
            card.dataset.name = cb.name;
            
            // 根据索引状态确定状态徽章
            let statusBadgeHTML = '';
            if (cb.indexing_status === 'indexing') {
                statusBadgeHTML = `
                    <span class="status-badge indexing">
                        <span class="indexing-spinner"></span> 正在索引...
                    </span>
                `;
            } else if (cb.indexed) {
                statusBadgeHTML = `
                    <span class="status-badge indexed">
                        <i class="fas fa-check-circle"></i> 已索引
                    </span>
                `;
            } else {
                statusBadgeHTML = `
                    <span class="status-badge pending">
                        <i class="fas fa-clock"></i> 未索引
                    </span>
                `;
            }
            
            // 添加LSP状态徽章 - 根据analyzer_ready和analyzer_progress生成不同的显示
            let lspBadgeHTML = '';
            console.log("LSP状态:", cb.analyzer_ready, cb.analyzer_progress);
            if (cb.analyzer_ready) {
                lspBadgeHTML = `
                    <span class="lsp-status-badge ready">
                        <i class="fas fa-check-circle"></i> LSP就绪
                    </span>
                `;
            } else if (cb.analyzer_progress > 0) {
                const progressPercent = Math.round(cb.analyzer_progress * 100);
                lspBadgeHTML = `
                    <span class="lsp-status-badge preparing">
                        <i class="fas fa-spinner fa-spin"></i> LSP准备中 ${progressPercent}%
                    </span>
                `;
            } else {
                lspBadgeHTML = `
                    <span class="lsp-status-badge not-ready">
                        <i class="fas fa-times-circle"></i> LSP未就绪
                    </span>
                `;
            }
            
            card.innerHTML = `
                <div class="codebase-card-header">
                    <div class="codebase-name">
                        <i class="fas fa-database"></i>
                        ${Utils.escapeHtml(cb.name)}
                    </div>
                    <div class="codebase-status">
                        ${statusBadgeHTML}
                        ${lspBadgeHTML}
                    </div>
                </div>
                <div class="codebase-card-body">
                    <div class="codebase-info">
                        <div class="codebase-info-item">
                            <i class="fas fa-folder" style="font-size: 20px;"></i>
                            <span style="margin-left: 10px; font-size: 12px;">${Utils.escapeHtml(cb.code_path.split('/').slice(0, -1).join('/'))} </span>
                        </div>
                    </div>
                    <div class="codebase-actions">
                        <button class="btn btn-success search-btn" data-name="${Utils.escapeHtml(cb.name)}" title="执行常规搜索">
                            <i class="fas fa-search"></i> 常规搜索
                        </button>
                        <button class="btn btn-warning strong-search-btn" data-name="${Utils.escapeHtml(cb.name)}" title="执行强效智能搜索">
                            <i class="fas fa-brain"></i> 强效搜索
                        </button>
                        <button class="btn btn-info browse-btn" data-name="${Utils.escapeHtml(cb.name)}" title="浏览代码文件">
                            <i class="fas fa-folder-open"></i> 浏览文件
                        </button>
                        <button class="btn btn-secondary ast-btn" data-name="${Utils.escapeHtml(cb.name)}" title="查看代码结构树">
                            <i class="fas fa-project-diagram"></i> 查看AST
                        </button>
                        <button class="btn btn-primary index-btn ${cb.indexing_status === 'indexing' ? 'disabled' : ''}" 
                                data-name="${Utils.escapeHtml(cb.name)}" 
                                title="${cb.indexed ? '重新索引' : '开始索引'}"
                                ${cb.indexing_status === 'indexing' ? 'disabled' : ''}>
                            <i class="fas fa-sync-alt"></i> ${cb.indexed ? '重新索引' : '索引'}
                        </button>
                        <button class="btn btn-danger delete-btn" data-name="${Utils.escapeHtml(cb.name)}" title="删除此代码库">
                            <i class="fas fa-trash-alt"></i> 删除
                        </button>
                    </div>
                </div>
            `;
            
            codebasesGrid.appendChild(card);
            
            // 添加淡入动画
            setTimeout(() => {
                card.style.opacity = '1';
                card.style.transform = 'translateY(0)';
            }, 50);
            
            // 如果正在索引，开始轮询
            if (cb.indexing_status === 'indexing' && !indexingPolls[cb.name]) {
                startPollingIndexStatus(cb.name);
            }
        });
    }

    // 对外暴露API
    return {
        init,
        fetchCodebases,
        renderCodebaseCards
    };
})();

// 将模块添加到全局命名空间
window.CodebaseManager = CodebaseManager; 