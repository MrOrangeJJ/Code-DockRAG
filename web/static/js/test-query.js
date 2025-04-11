/**
 * test-query.js - 测试查询模块
 * 处理简单的测试查询功能
 */

// 测试查询模块
const TestQuery = (function() {
    // 私有变量
    let currentTestCodebase = null;
    
    let queryTestModal;
    let modalClose;
    let testQueryForm;
    let modalCodebaseNameEl;
    let testQueryResultsEl;
    
    let API_BASE_URL;

    // 初始化函数
    function init(config) {
        // 保存配置
        API_BASE_URL = config.API_BASE_URL;
        
        // 初始化DOM元素引用
        queryTestModal = document.getElementById('query-test-modal');
        modalClose = document.getElementById('modal-close');
        testQueryForm = document.getElementById('test-query-form');
        modalCodebaseNameEl = document.getElementById('modal-codebase-name');
        testQueryResultsEl = document.getElementById('test-query-results');
        
        // 绑定事件
        bindEvents();
    }

    // 事件绑定
    function bindEvents() {
        // 模态框关闭按钮
        if (modalClose) {
            modalClose.addEventListener('click', closeModal);
        }
        
        // 模态框背景点击关闭
        if (queryTestModal) {
            queryTestModal.addEventListener('click', (e) => {
                if (e.target === queryTestModal) {
                    closeModal();
                }
            });
        }
        
        // 测试查询表单提交
        if (testQueryForm) {
            testQueryForm.addEventListener('submit', handleTestQuerySubmit);
        }
    }

    // 测试查询表单提交处理
    async function handleTestQuerySubmit(e) {
        e.preventDefault();
        
        if (!currentTestCodebase) return;
        
        const queryInput = document.getElementById('test-query');
        const rerankInput = document.getElementById('test-rerank');
        
        if (!queryInput || !queryInput.value.trim()) {
            alert('请输入查询内容');
            return;
        }
        
        const query = queryInput.value.trim();
        const rerank = rerankInput ? rerankInput.checked : false;
        
        testQueryResultsEl.innerHTML = '<div class="loading-container"><div class="loader"></div><p>正在执行查询...</p></div>';
        
        try {
            const response = await fetch(`${API_BASE_URL}/search`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    codebase_name: currentTestCodebase,
                    query,
                    rerank
                }),
            });
            
            const result = await response.json();
            
            if (response.ok) {
                renderTestQueryResults(result);
            } else {
                throw new Error(result.detail || `查询失败 (${response.status})`);
            }
        } catch (error) {
            console.error('Test query error:', error);
            testQueryResultsEl.innerHTML = `<div class="status-message"><p class="status-error">查询出错: ${error.message}</p></div>`;
        }
    }

    // 打开测试查询模态框
    function openModal(codebaseName) {
        if (!queryTestModal) return;
        
        currentTestCodebase = codebaseName;
        modalCodebaseNameEl.textContent = codebaseName;
        testQueryResultsEl.innerHTML = '';
        
        // 重置表单
        if (testQueryForm) {
            testQueryForm.reset();
        }
        
        UI.openModal(queryTestModal);
    }
    
    // 关闭测试查询模态框
    function closeModal() {
        UI.closeModal(queryTestModal);
        currentTestCodebase = null;
    }
    
    // 渲染测试查询结果
    function renderTestQueryResults(result) {
        if (!testQueryResultsEl) return;
        
        let html = `
            <h3>查询: ${Utils.escapeHtml(result.query)}</h3>
            <p>找到 ${result.files ? result.files.length : 0} 个相关文件</p>
        `;
        
        if (!result.files || result.files.length === 0) {
            html += '<p>未找到相关文件。</p>';
        } else {
            const maxFilesToShow = 3; // 在模态框中限制显示的文件数量
            
            result.files.slice(0, maxFilesToShow).forEach((file, index) => {
                // 添加延迟类
                const delayClass = `delay-${(index % 5) * 100}`;
                
                html += `
                    <div class="file-container ${delayClass}">
                        <div class="file-header">
                            <i class="fas fa-file-code"></i>
                            ${Utils.escapeHtml(file.file_path)}
                        </div>
                        <div class="file-content">${Utils.escapeHtml(file.content)}</div>
                    </div>
                `;
            });
            
            if (result.files.length > maxFilesToShow) {
                const remainingFiles = result.files.length - maxFilesToShow;
                html += `<p class="text-center">还有 ${remainingFiles} 个文件未显示。要查看所有结果，请使用搜索页面。</p>`;
                html += `<p class="text-center"><a href="/search.html?codebase=${encodeURIComponent(currentTestCodebase)}&query=${encodeURIComponent(result.query)}&rerank=${result.rerank}" class="btn btn-primary">在搜索页查看完整结果</a></p>`;
            }
        }
        
        testQueryResultsEl.innerHTML = html;
    }

    // 对外暴露API
    return {
        init,
        openModal,
        closeModal
    };
})();

// 将模块添加到全局命名空间
window.TestQuery = TestQuery; 