/**
 * search.js - 常规搜索模块
 * 处理常规搜索功能
 */

// 搜索模块
const Search = (function() {
    // 私有变量
    let currentSearchCodebase = null;
    
    let searchModal;
    let searchModalClose;
    let searchModalForm;
    let searchModalCodebaseNameEl;
    let searchModalQueryInput;
    let searchModalRerankCheckbox;
    let searchModalLoading;
    let searchModalStatusDiv;
    let searchModalResultsEl;
    
    let API_BASE_URL;
    let WEB_API_BASE_URL;

    // 初始化函数
    function init(config) {
        // 保存配置
        API_BASE_URL = config.API_BASE_URL;
        WEB_API_BASE_URL = config.WEB_API_BASE_URL;
        
        // 调试输出
        console.log('[搜索模块] 初始化，API基址:', API_BASE_URL);
        
        // 初始化DOM元素引用
        searchModal = document.getElementById('search-modal');
        searchModalClose = document.getElementById('search-modal-close');
        searchModalForm = document.getElementById('search-modal-form');
        searchModalCodebaseNameEl = document.getElementById('search-modal-codebase-name');
        searchModalQueryInput = document.getElementById('search-modal-query');
        searchModalRerankCheckbox = document.getElementById('search-modal-rerank');
        searchModalLoading = document.getElementById('search-modal-loading');
        searchModalStatusDiv = document.getElementById('search-modal-status');
        searchModalResultsEl = document.getElementById('search-modal-results');
        
        // 检查必要元素是否存在
        if (!searchModal || !searchModalResultsEl) {
            console.error('[搜索模块] 初始化失败: 找不到必要的DOM元素');
            return;
        }
        
        console.log('[搜索模块] DOM元素引用已初始化');
        
        // 绑定事件
        bindEvents();
        console.log('[搜索模块] 初始化完成');
    }

    // 事件绑定
    function bindEvents() {
        try {
            // 搜索模态框关闭按钮
            if (searchModalClose) {
                searchModalClose.addEventListener('click', closeModal);
            }
            
            // 搜索模态框背景点击关闭
            if (searchModal) {
                searchModal.addEventListener('click', (e) => {
                    if (e.target === searchModal) {
                        closeModal();
                    }
                });
            }
            
            // 搜索表单提交
            if (searchModalForm) {
                searchModalForm.addEventListener('submit', (e) => {
                    e.preventDefault();
                    performSearch();
                });
            }
            console.log('[搜索模块] 事件绑定完成');
        } catch (error) {
            console.error('[搜索模块] 绑定事件时出错:', error);
        }
    }

    // 打开搜索模态框
    function openModal(codebaseName) {
        if (!searchModal) {
            console.error('[搜索模块] 无法打开模态框: 找不到搜索模态框元素');
            return;
        }
        
        console.log('[搜索模块] 打开搜索模态框, 代码库:', codebaseName);
        
        currentSearchCodebase = codebaseName;
        searchModalCodebaseNameEl.textContent = codebaseName;
        
        // 清空结果和重置表单
        if (searchModalResultsEl) {
            searchModalResultsEl.innerHTML = '';
        }
        
        if (searchModalForm) {
            searchModalForm.reset();
        }
        
        // 隐藏加载指示器
        if (searchModalLoading) {
            UI.toggleLoading(searchModalLoading, false);
        }
        
        // 打开模态框
        UI.openModal(searchModal);
    }
    
    // 关闭搜索模态框
    function closeModal() {
        if (!searchModal) return;
        
        console.log('[搜索模块] 关闭搜索模态框');
        UI.closeModal(searchModal);
        currentSearchCodebase = null;
    }
    
    // 创建状态消息HTML
    function createStatusMessage(message, type) {
        return `<div class="status-message"><p class="status-${type}">${message}</p></div>`;
    }
    
    // 执行搜索
    async function performSearch() {
        // 检查状态
        if (!currentSearchCodebase) {
            console.error('[搜索模块] 无法执行搜索: 没有选择代码库');
            return;
        }
        
        if (!searchModalQueryInput || !searchModalResultsEl) {
            console.error('[搜索模块] 无法执行搜索: 找不到查询输入框或结果容器');
            return;
        }
        
        // 获取查询参数
        const query = searchModalQueryInput.value.trim();
        const rerank = searchModalRerankCheckbox ? searchModalRerankCheckbox.checked : false;
        
        // 清空结果区域并验证输入
        searchModalResultsEl.innerHTML = '';
        
        if (!query) {
            searchModalResultsEl.innerHTML = createStatusMessage('请输入查询内容', 'warning');
            return;
        }
        
        console.log('[搜索模块] 执行搜索:', query, '代码库:', currentSearchCodebase, '重排序:', rerank);
        
        // 显示加载状态
        if (searchModalLoading) {
            UI.toggleLoading(searchModalLoading, true);
        }
        
        // 显示临时消息
        searchModalResultsEl.innerHTML = createStatusMessage('正在搜索中...', 'info');
        
        try {
            // 发送请求到API
            console.log('[搜索模块] 发送请求到:', `${API_BASE_URL}/search`);
            
            const response = await fetch(`${API_BASE_URL}/search`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    codebase_name: currentSearchCodebase,
                    query: query,
                    rerank: rerank
                })
            });
            
            // 处理HTTP错误
            if (!response.ok) {
                throw new Error(`搜索请求失败: ${response.status} ${response.statusText}`);
            }
            
            // 解析响应
            const result = await response.json();
            console.log('[搜索模块] 收到API响应:', result);
            
            // 验证响应格式
            if (!result || typeof result !== 'object') {
                throw new Error('API返回格式异常: 未接收到有效数据');
            }
            
            // 检查文件列表
            const files = result.files;
            if (!files || !Array.isArray(files)) {
                throw new Error('API返回格式异常: 缺少文件列表或格式错误');
            }
            
            // 处理空结果情况
            if (files.length === 0) {
                searchModalResultsEl.innerHTML = createStatusMessage('未找到任何匹配的文件。', 'info');
                return;
            }
            
            // 成功获取结果
            console.log(`[搜索模块] 找到 ${files.length} 个匹配文件`);
            
            // 清空结果区域
            searchModalResultsEl.innerHTML = '';
            
            // 显示成功消息
            const successMessageDiv = document.createElement('div');
            successMessageDiv.className = 'status-message';
            successMessageDiv.innerHTML = `<p class="status-success">查询 "${escapeHtml(result.query)}" 完成，找到 ${files.length} 个相关文件</p>`;
            searchModalResultsEl.appendChild(successMessageDiv);
            
            // 渲染搜索结果
            renderSearchResults(files);
            
        } catch (error) {
            console.error('[搜索模块] 搜索出错:', error);
            searchModalResultsEl.innerHTML = createStatusMessage(`搜索出错: ${error.message}`, 'error');
        } finally {
            // 隐藏加载状态
            if (searchModalLoading) {
                UI.toggleLoading(searchModalLoading, false);
            }
        }
    }
    
    // HTML转义函数
    function escapeHtml(text) {
        if (typeof text !== 'string') return '';
        const map = {
            '&': '&amp;',
            '<': '&lt;',
            '>': '&gt;',
            '"': '&quot;',
            "'": '&#039;'
        };
        return text.replace(/[&<>"']/g, m => map[m]);
    }
    
    // 渲染搜索结果 - 采用与强效搜索类似的卡片样式
    function renderSearchResults(files) {
        if (!searchModalResultsEl) {
            console.error('[搜索模块] 无法渲染搜索结果: 找不到结果容器');
            return;
        }
        
        if (!files || !Array.isArray(files) || files.length === 0) {
            console.warn('[搜索模块] 没有文件可渲染');
            return;
        }

        console.log('[搜索模块] 开始渲染', files.length, '个搜索结果');
        
        // 创建结果容器 div (代替 ol)
        const resultContainer = document.createElement('div');
        resultContainer.className = 'search-result-list';
        resultContainer.style.marginTop = '1rem';
        
        // 遍历渲染每个文件
        let validFilesCount = 0;
        
        files.forEach((file, index) => {
            // 验证文件对象结构
            if (!file || typeof file !== 'object' || !file.file_path) {
                console.warn(`[搜索模块] 第${index+1}个结果无效:`, file);
                return;
            }
            
            console.log(`[搜索模块] 渲染文件 ${index+1}/${files.length}:`, file.file_path);
            validFilesCount++;
            
            // 创建结果卡片 div (代替 li)
            const resultCard = document.createElement('div');
            resultCard.className = 'search-result-item';
            
            // 创建文件名标题
            const fileName = document.createElement('h4');
            fileName.innerHTML = `<i class="fas fa-file-code" style="color: var(--color-primary); margin-right: 5px;"></i> ${escapeHtml(file.file_path)}`;
            fileName.style.borderBottom = '1px solid #e5e7eb';
            fileName.style.paddingBottom = '0.5rem';
            fileName.style.marginBottom = '1rem';
            
            // 创建分数/符号信息区域 (保持不变)
            const symbolsDiv = document.createElement('div');
            symbolsDiv.style.marginBottom = '1rem';
            symbolsDiv.style.fontSize = '0.9rem';
            symbolsDiv.style.color = '#6b7280';
            
            // 生成分数/符号HTML (保持不变)
            let symbolsHtml = '';
            if (file.score) { // 添加分数显示
                 symbolsHtml += `<p style="margin: 0.25rem 0;"><i class="fas fa-star" style="margin-right: 5px; color: #f59e0b;"></i><strong>相关度:</strong> ${file.score.toFixed(3)}</p>`;
            }
            if (file.matched_classes && Array.isArray(file.matched_classes) && file.matched_classes.length > 0) {
                symbolsHtml += `<p style="margin: 0.25rem 0;"><i class="fas fa-cubes" style="margin-right: 5px;"></i><strong>相关类:</strong> ${file.matched_classes.map(escapeHtml).join(', ')}</p>`;
            }
            if (file.matched_functions && Array.isArray(file.matched_functions) && file.matched_functions.length > 0) {
                symbolsHtml += `<p style="margin: 0.25rem 0;"><i class="fas fa-code" style="margin-right: 5px;"></i><strong>相关函数:</strong> ${file.matched_functions.map(escapeHtml).join(', ')}</p>`;
            }
            if (!symbolsHtml) {
                symbolsHtml = '<p style="margin: 0.25rem 0; font-style: italic;">未直接匹配到特定函数或类。</p>';
            }
            symbolsDiv.innerHTML = symbolsHtml;
            
            // 创建可点击的文件内容标题 (代替 summary)
            const contentHeader = document.createElement('div');
            contentHeader.textContent = '显示/隐藏文件内容';
            contentHeader.className = 'collapsible-header';
            contentHeader.style.marginTop = '1rem'; // 与原details间距一致
            
            // 创建文件内容容器 (代替 pre)
            const contentContainer = document.createElement('div');
            contentContainer.className = 'collapsible-content';
            
            const fileContentPre = document.createElement('pre');
            fileContentPre.style.overflow = 'auto';
            fileContentPre.style.backgroundColor = '#f8f9fa';
            fileContentPre.style.padding = '1rem';
            fileContentPre.style.borderRadius = '0.25rem';
            fileContentPre.style.fontSize = '0.9rem';
            fileContentPre.style.fontFamily = 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace';
            fileContentPre.style.border = '1px solid #e5e7eb';
            
            const fileContentCode = document.createElement('code');
            fileContentCode.textContent = '加载中...'; // 默认显示加载中
            fileContentPre.appendChild(fileContentCode);
            contentContainer.appendChild(fileContentPre);
            
            // 添加点击事件到标题
            contentHeader.addEventListener('click', async function() {
                const isOpening = contentContainer.style.display === 'none';
                contentContainer.style.display = isOpening ? 'block' : 'none';
                
                // 只在展开且内容为加载中时加载文件内容
                if (isOpening && fileContentCode.textContent === '加载中...') {
                    try {
                        console.log('[搜索模块] 加载文件内容:', file.file_path);
                        
                        // 调用API获取文件内容
                        const response = await fetch(`${WEB_API_BASE_URL}/codebases/${currentSearchCodebase}/files/batch`, {
                            method: 'POST',
                            headers: {
                                'Content-Type': 'application/json',
                            },
                            body: JSON.stringify({
                                file_paths: [file.file_path]
                            })
                        });
                        
                        if (!response.ok) {
                            throw new Error(`获取文件内容失败: ${response.status} ${response.statusText}`);
                        }
                        
                        const result = await response.json();
                        console.log('[搜索模块] 文件内容API返回:', result);
                        
                        if (!result || !result.contents) {
                            throw new Error('文件内容API返回数据格式异常');
                        }
                        
                        const fileContent = result.contents[file.file_path];
                        
                        if (fileContent && !fileContent.startsWith('错误:')) {
                            fileContentCode.textContent = fileContent;
                        } else {
                            fileContentCode.textContent = fileContent || '无法加载文件内容';
                            fileContentCode.style.color = 'red';
                        }
                    } catch (error) {
                        console.error('[搜索模块] 加载文件内容时出错:', error);
                        fileContentCode.textContent = `无法加载文件内容: ${error.message}`;
                        fileContentCode.style.color = 'red';
                    }
                }
            });
            
            // 组装DOM结构
            resultCard.appendChild(fileName);
            resultCard.appendChild(symbolsDiv);
            resultCard.appendChild(contentHeader);
            resultCard.appendChild(contentContainer);
            
            // 添加到结果列表
            resultContainer.appendChild(resultCard);
        });
        
        // 添加结果列表到结果区域
        if (validFilesCount > 0) {
            searchModalResultsEl.appendChild(resultContainer);
            console.log('[搜索模块] 搜索结果渲染完成, 显示了', validFilesCount, '个文件');
        } else {
            searchModalResultsEl.innerHTML += createStatusMessage('无法显示搜索结果: 所有结果均无效', 'warning');
            console.warn('[搜索模块] 所有搜索结果均无效，未能渲染');
        }
    }

    // 对外暴露API
    return {
        init,
        openModal,
        closeModal,
        performSearch
    };
})();

// 将模块添加到全局命名空间
window.Search = Search; 