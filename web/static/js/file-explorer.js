/**
 * file-explorer.js - 文件浏览器模块
 * 处理文件浏览、查看、上传和删除功能
 */

// 文件浏览器模块
const FileExplorer = (function() {
    // 私有变量
    let currentExplorerCodebase = null;
    let currentExplorerPath = '';
    
    let fileExplorerModal;
    let explorerClose;
    let explorerCodebaseNameEl;
    let fileBreadcrumb;
    let fileList;
    let fileExplorerLoading;
    let explorerStatusDiv;
    let fileContentView;
    let contentFileName;
    let fileContent;
    let backToListBtn;
    let uploadFileBtn;
    let createFolderBtn;
    let fileUploadForm;
    let explorerFileInput;
    let explorerFileName;
    let uploadDirectory;
    let cancelUploadBtn;
    let folderCreateForm;
    let folderNameInput;
    let createDirectory;
    let cancelFolderBtn;
    
    let API_BASE_URL;
    let WEB_API_BASE_URL;

    // 初始化函数
    function init(config) {
        // 保存配置
        API_BASE_URL = config.API_BASE_URL;
        WEB_API_BASE_URL = config.WEB_API_BASE_URL;
        
        // 初始化DOM元素引用
        fileExplorerModal = document.getElementById('file-explorer-modal');
        explorerClose = document.getElementById('explorer-close');
        explorerCodebaseNameEl = document.getElementById('explorer-codebase-name');
        fileBreadcrumb = document.getElementById('file-breadcrumb');
        fileList = document.getElementById('file-list');
        fileExplorerLoading = document.getElementById('file-explorer-loading');
        explorerStatusDiv = document.getElementById('explorer-status');
        fileContentView = document.getElementById('file-content-view');
        contentFileName = document.getElementById('content-file-name');
        fileContent = document.getElementById('file-content');
        backToListBtn = document.getElementById('back-to-list');
        uploadFileBtn = document.getElementById('upload-file-btn');
        createFolderBtn = document.getElementById('create-folder-btn');
        fileUploadForm = document.getElementById('file-upload-form');
        explorerFileInput = document.getElementById('explorer-file-input');
        explorerFileName = document.getElementById('explorer-file-name');
        uploadDirectory = document.getElementById('upload-directory');
        cancelUploadBtn = document.getElementById('cancel-upload');
        folderCreateForm = document.getElementById('folder-create-form');
        folderNameInput = document.getElementById('folder-name');
        createDirectory = document.getElementById('create-directory');
        cancelFolderBtn = document.getElementById('cancel-folder');
        
        // 绑定事件
        bindEvents();
    }

    // 事件绑定
    function bindEvents() {
        // 文件浏览器事件 - 面包屑导航
        if (fileBreadcrumb) {
            fileBreadcrumb.addEventListener('click', handleBreadcrumbClick);
        }
        
        // 文件浏览器事件 - 文件列表点击
        if (fileList) {
            fileList.addEventListener('click', handleFileListClick);
        }
        
        // 文件浏览器事件 - 返回列表按钮
        if (backToListBtn) {
            backToListBtn.addEventListener('click', handleBackToListClick);
        }
        
        // 文件浏览器事件 - 上传文件按钮
        if (uploadFileBtn) {
            uploadFileBtn.addEventListener('click', handleUploadFileClick);
        }
        
        // 文件浏览器事件 - 取消上传按钮
        if (cancelUploadBtn) {
            cancelUploadBtn.addEventListener('click', handleCancelUploadClick);
        }
        
        // 文件浏览器事件 - 文件上传表单
        if (fileUploadForm) {
            fileUploadForm.addEventListener('submit', handleFileUploadSubmit);
        }
        
        // 文件浏览器事件 - 新建文件夹按钮
        if (createFolderBtn) {
            createFolderBtn.addEventListener('click', handleCreateFolderClick);
        }
        
        // 文件浏览器事件 - 取消新建文件夹按钮
        if (cancelFolderBtn) {
            cancelFolderBtn.addEventListener('click', handleCancelFolderClick);
        }
        
        // 文件浏览器事件 - 新建文件夹表单
        if (folderCreateForm) {
            folderCreateForm.addEventListener('submit', handleFolderCreateSubmit);
        }
        
        // 文件浏览器事件 - 关闭按钮
        if (explorerClose) {
            explorerClose.addEventListener('click', closeModal);
        }
        
        // 文件浏览器事件 - 背景点击关闭
        if (fileExplorerModal) {
            fileExplorerModal.addEventListener('click', (e) => {
                if (e.target === fileExplorerModal) {
                    closeModal();
                }
            });
        }
        
        // 文件浏览器事件 - 上传文件字段
        if (explorerFileInput) {
            explorerFileInput.addEventListener('change', handleExplorerFileInputChange);
        }
    }

    // 面包屑导航点击处理
    function handleBreadcrumbClick(e) {
        e.preventDefault();
        
        const link = e.target.closest('a');
        if (!link) return;
        
        const path = link.dataset.path || '';
        currentExplorerPath = path;
        updateBreadcrumb();
        loadFileList();
    }

    // 文件列表点击处理
    function handleFileListClick(e) {
        const fileItem = e.target.closest('.file-item');
        if (!fileItem) return;
        
        const path = fileItem.dataset.path;
        const type = fileItem.dataset.type;
        
        // 处理删除按钮点击
        const deleteBtn = e.target.closest('.file-action.delete');
        if (deleteBtn) {
            deleteFile(path, type);
            return;
        }
        
        // 处理查看文件按钮点击
        const viewBtn = e.target.closest('.file-action.view');
        if (viewBtn) {
            loadFileContent(path);
            return;
        }
        
        // 处理目录点击
        if (type === 'directory') {
            currentExplorerPath = path;
            updateBreadcrumb();
            loadFileList();
        }
        // 处理文件点击
        else {
            loadFileContent(path);
        }
    }

    // 返回列表按钮点击处理
    function handleBackToListClick() {
        if (fileContentView) {
            fileContentView.classList.add('hidden');
        }
        if (fileList) {
            fileList.classList.remove('hidden');
        }
    }

    // 上传文件按钮点击处理
    function handleUploadFileClick() {
        if (fileUploadForm) {
            if (uploadDirectory) {
                uploadDirectory.value = currentExplorerPath;
            }
            
            fileUploadForm.classList.remove('hidden');
            folderCreateForm.classList.add('hidden');
        }
    }

    // 取消上传按钮点击处理
    function handleCancelUploadClick() {
        if (fileUploadForm) {
            fileUploadForm.classList.add('hidden');
            fileUploadForm.reset();
        }
    }

    // 文件上传表单提交处理
    function handleFileUploadSubmit(e) {
        e.preventDefault();
        
        const formData = new FormData(fileUploadForm);
        uploadFileToCodebase(formData);
    }

    // 新建文件夹按钮点击处理
    function handleCreateFolderClick() {
        if (folderCreateForm) {
            if (createDirectory) {
                createDirectory.value = currentExplorerPath;
            }
            
            folderCreateForm.classList.remove('hidden');
            fileUploadForm.classList.add('hidden');
        }
    }

    // 取消新建文件夹按钮点击处理
    function handleCancelFolderClick() {
        if (folderCreateForm) {
            folderCreateForm.classList.add('hidden');
            folderCreateForm.reset();
        }
    }

    // 新建文件夹表单提交处理
    function handleFolderCreateSubmit(e) {
        e.preventDefault();
        
        const folderName = folderNameInput.value.trim();
        if (!folderName) {
            alert('请输入文件夹名称');
            return;
        }
        
        createFolder(folderName);
    }

    // 上传文件字段变化处理
    function handleExplorerFileInputChange() {
        const wrapper = explorerFileInput.closest('.file-upload-wrapper');
        
        if (explorerFileInput.files && explorerFileInput.files.length > 0) {
            const fileName = explorerFileInput.files[0].name;
            if (explorerFileName) {
                explorerFileName.textContent = fileName;
            }
            wrapper.classList.add('has-file');
        } else {
            if (explorerFileName) {
                explorerFileName.textContent = '未选择文件';
            }
            wrapper.classList.remove('has-file');
        }
    }

    // 打开文件浏览器模态框
    function openModal(codebaseName) {
        if (!fileExplorerModal) return;
        
        currentExplorerCodebase = codebaseName;
        currentExplorerPath = '';
        explorerCodebaseNameEl.textContent = codebaseName;
        
        // 重置面包屑导航
        if (fileBreadcrumb) {
            fileBreadcrumb.innerHTML = '<li class="breadcrumb-item active"><a href="#" data-path="">根目录</a></li>';
        }
        
        // 重置文件列表和状态
        if (fileList) {
            fileList.innerHTML = '';
        }
        
        // 隐藏文件内容视图
        if (fileContentView) {
            fileContentView.classList.add('hidden');
        }
        
        // 隐藏上传表单
        if (fileUploadForm) {
            fileUploadForm.classList.add('hidden');
        }
        
        // 隐藏创建文件夹表单
        if (folderCreateForm) {
            folderCreateForm.classList.add('hidden');
        }
        
        // 加载文件列表
        loadFileList();
        
        UI.openModal(fileExplorerModal);
    }
    
    // 关闭文件浏览器模态框
    function closeModal() {
        UI.closeModal(fileExplorerModal);
        currentExplorerCodebase = null;
        currentExplorerPath = '';
    }
    
    // 加载文件列表
    async function loadFileList() {
        if (!fileList || !currentExplorerCodebase) return;
        
        UI.toggleLoading(fileExplorerLoading, true);
        
        if (fileContentView) {
            fileContentView.classList.add('hidden');
        }
        
        try {
            const response = await fetch(`${WEB_API_BASE_URL}/codebases/${currentExplorerCodebase}/files?path=${encodeURIComponent(currentExplorerPath)}`);
            
            if (!response.ok) {
                throw new Error(`API Error: ${response.status} ${response.statusText}`);
            }
            
            const files = await response.json();
            renderFileList(files);
        } catch (error) {
            console.error('Error loading files:', error);
            UI.showStatus(explorerStatusDiv, `无法加载文件列表: ${error.message}`, 'error');
            fileList.innerHTML = '<div class="empty-state"><i class="fas fa-exclamation-circle"></i><p>加载文件失败</p></div>';
        } finally {
            UI.toggleLoading(fileExplorerLoading, false);
        }
    }
    
    // 渲染文件列表
    function renderFileList(files) {
        if (!fileList) return;
        
        fileList.innerHTML = '';
        
        if (files.length === 0) {
            fileList.innerHTML = '<div class="empty-state"><i class="fas fa-folder-open"></i><p>此目录为空</p></div>';
            return;
        }
        
        files.forEach(file => {
            const fileItem = document.createElement('div');
            fileItem.className = 'file-item';
            fileItem.dataset.path = file.path;
            fileItem.dataset.type = file.type;
            
            const sizeText = file.size ? Utils.formatFileSize(file.size) : '';
            const dateText = Utils.formatDate(new Date(file.modified * 1000));
            
            fileItem.innerHTML = `
                <div class="file-item-icon ${file.type}">
                    <i class="fas ${file.type === 'directory' ? 'fa-folder' : 'fa-file-code'}"></i>
                </div>
                <div class="file-item-name">${Utils.escapeHtml(file.name)}</div>
                <div class="file-item-meta">
                    ${sizeText ? `<span class="file-size">${sizeText}</span> · ` : ''}
                    <span class="file-date">${dateText}</span>
                </div>
                <div class="file-item-actions">
                    ${file.type !== 'directory' ? `
                        <button class="file-action view" title="查看">
                            <i class="fas fa-eye"></i>
                        </button>
                    ` : ''}
                    <button class="file-action delete" title="删除">
                        <i class="fas fa-trash-alt"></i>
                    </button>
                </div>
            `;
            
            fileList.appendChild(fileItem);
        });
    }
    
    // 更新面包屑导航
    function updateBreadcrumb() {
        if (!fileBreadcrumb) return;
        
        fileBreadcrumb.innerHTML = '<li class="breadcrumb-item"><a href="#" data-path="">根目录</a></li>';
        
        if (!currentExplorerPath) {
            fileBreadcrumb.querySelector('li').classList.add('active');
            return;
        }
        
        const pathParts = currentExplorerPath.split('/');
        let currentPath = '';
        
        pathParts.forEach((part, index) => {
            if (!part) return;
            
            currentPath += (currentPath ? '/' : '') + part;
            
            const item = document.createElement('li');
            item.className = 'breadcrumb-item';
            if (index === pathParts.length - 1) {
                item.classList.add('active');
            }
            
            item.innerHTML = `<a href="#" data-path="${Utils.escapeHtml(currentPath)}">${Utils.escapeHtml(part)}</a>`;
            fileBreadcrumb.appendChild(item);
        });
    }
    
    // 加载文件内容
    async function loadFileContent(filePath) {
        if (!currentExplorerCodebase || !filePath) return;
        
        const fileContentDiv = document.getElementById('fileContent');
        const fileContentHeader = document.getElementById('fileContentHeader');
        if (!fileContentDiv || !fileContentHeader) return;
        
        UI.showStatus(explorerStatusDiv, '正在加载文件内容...', 'info');
        UI.toggleLoading(fileExplorerLoading, true);
        
        try {
            // 路径中可能包含特殊字符，需要编码
            const encodedFilePath = encodeURIComponent(filePath);
            const response = await fetch(`${WEB_API_BASE_URL}/codebases/${currentExplorerCodebase}/files/${encodedFilePath}`);
            
            if (!response.ok) {
                throw new Error(`API Error: ${response.status} ${response.statusText}`);
            }
            
            const data = await response.json();
            
            fileList.classList.add('hidden');
            fileContentDiv.classList.remove('hidden');
            
            // 更新文件头部信息
            fileContentHeader.textContent = filePath;
            
            // 显示文件内容
            const contentElement = document.getElementById('fileContentText');
            if (contentElement) {
                contentElement.textContent = data.content;
                
                // 高亮代码
                if (typeof hljs !== 'undefined') {
                    hljs.highlightElement(contentElement);
                }
            }
            
            UI.showStatus(explorerStatusDiv, '文件内容加载成功', 'success', 2000);
        } catch (error) {
            console.error('Error loading file content:', error);
            UI.showStatus(explorerStatusDiv, `无法加载文件内容: ${error.message}`, 'error');
        } finally {
            UI.toggleLoading(fileExplorerLoading, false);
        }
    }
    
    // 删除文件
    async function deleteFile(filePath, fileType) {
        if (!currentExplorerCodebase || !filePath) return;
        
        const typeText = fileType === 'directory' ? '目录' : '文件';
        const fileName = filePath.split('/').pop();
        
        if (!confirm(`确定要删除${typeText} "${fileName}" 吗？此操作无法撤销。`)) {
            return;
        }
        
        UI.showStatus(explorerStatusDiv, `正在删除${typeText}...`, 'info');
        
        try {
            const encodedFilePath = encodeURIComponent(filePath);
            const response = await fetch(`${WEB_API_BASE_URL}/codebases/${currentExplorerCodebase}/files/${encodedFilePath}`, {
                method: 'DELETE',
            });
            
            if (!response.ok) {
                throw new Error(`API Error: ${response.status} ${response.statusText}`);
            }
            
            const result = await response.json();
            
            if (result.success) {
                UI.showStatus(explorerStatusDiv, result.message, 'success');
                // 刷新文件列表
                loadFileList();
                // 由于文件修改，刷新代码库列表以更新索引状态
                if (typeof CodebaseManager !== 'undefined' && CodebaseManager.fetchCodebases) {
                    CodebaseManager.fetchCodebases();
                }
            } else {
                throw new Error(result.message || `删除${typeText}失败`);
            }
        } catch (error) {
            console.error('Error deleting file:', error);
            UI.showStatus(explorerStatusDiv, `删除${typeText}失败: ${error.message}`, 'error');
        }
    }

    // 上传文件
    async function uploadFileToCodebase(formData) {
        if (!currentExplorerCodebase) return;
        
        UI.showStatus(explorerStatusDiv, '正在上传文件...', 'info');
        
        try {
            const response = await fetch(`${WEB_API_BASE_URL}/codebases/${currentExplorerCodebase}/files`, {
                method: 'POST',
                body: formData,
            });
            
            if (!response.ok) {
                throw new Error(`API Error: ${response.status} ${response.statusText}`);
            }
            
            const result = await response.json();
            
            if (result.success) {
                UI.showStatus(explorerStatusDiv, result.message, 'success');
                // 隐藏上传表单
                if (fileUploadForm) {
                    fileUploadForm.classList.add('hidden');
                    fileUploadForm.reset();
                }
                // 刷新文件列表
                loadFileList();
                // 由于文件修改，刷新代码库列表以更新索引状态
                if (typeof CodebaseManager !== 'undefined' && CodebaseManager.fetchCodebases) {
                    CodebaseManager.fetchCodebases();
                }
            } else {
                throw new Error(result.message || '上传文件失败');
            }
        } catch (error) {
            console.error('Error uploading file:', error);
            UI.showStatus(explorerStatusDiv, `上传文件失败: ${error.message}`, 'error');
        }
    }
    
    // 新建文件夹
    async function createFolder(folderName) {
        if (!currentExplorerCodebase || !folderName) return;
        
        const fullPath = currentExplorerPath ? `${currentExplorerPath}/${folderName}` : folderName;
        
        UI.showStatus(explorerStatusDiv, `正在创建文件夹 "${folderName}"...`, 'info');
        
        try {
            // 创建一个临时文件表示文件夹的存在
            const formData = new FormData();
            const placeholder = new File([''], '.placeholder', { type: 'text/plain' });
            formData.append('file', placeholder);
            formData.append('directory', fullPath);
            
            const response = await fetch(`${WEB_API_BASE_URL}/codebases/${currentExplorerCodebase}/files`, {
                method: 'POST',
                body: formData,
            });
            
            if (!response.ok) {
                throw new Error(`API Error: ${response.status} ${response.statusText}`);
            }
            
            const result = await response.json();
            
            if (result.success) {
                UI.showStatus(explorerStatusDiv, `文件夹 "${folderName}" 创建成功`, 'success');
                // 隐藏创建文件夹表单
                if (folderCreateForm) {
                    folderCreateForm.classList.add('hidden');
                    folderCreateForm.reset();
                }
                // 刷新文件列表
                loadFileList();
            } else {
                throw new Error(result.message || '创建文件夹失败');
            }
        } catch (error) {
            console.error('Error creating folder:', error);
            UI.showStatus(explorerStatusDiv, `创建文件夹失败: ${error.message}`, 'error');
        }
    }

    // 对外暴露API
    return {
        init,
        openModal,
        closeModal,
        loadFileList,
        loadFileContent
    };
})();

// 将模块添加到全局命名空间
window.FileExplorer = FileExplorer; 