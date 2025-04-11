/**
 * strong-search.js - 强效搜索模块
 * 处理强效搜索和WebSocket实时通信
 */

// 强效搜索模块
const StrongSearch = (function() {
    // 私有变量
    let currentStrongSearchCodebase = null;
    let strongSearchSocket = null;
    let strongSearchClientId = null;
    let isStrongSearching = false;
    let toolCallMap = {}; // 存储工具调用ID和对应DOM元素的映射
    let toolCallsByName = {}; // 按工具名称存储最近的工具调用
    
    let strongSearchModal;
    let strongSearchModalClose;
    let strongSearchModalCodebaseNameEl;
    let strongSearchConnectionStatus;
    let strongSearchModalForm;
    let strongSearchModalQueryInput;
    let strongSearchModalSubmitBtn;
    let strongSearchModalStopBtn;
    let strongSearchModalResultsArea;
    let strongSearchModalProgressBar;
    let strongSearchModalLogContainer;
    let strongSearchModalResultContainer;
    let strongSearchModalResultAnswer;
    let strongSearchModalRelevantFiles;
    let strongSearchModalTime;
    let strongSearchModalTabButtons;
    let strongSearchModalTabContents;
    
    let API_BASE_URL;
    let WEB_API_BASE_URL;

    // 生成唯一ID作为工具调用的标识
    function generateToolCallId(toolName, timestamp) {
        return `tool-call-${toolName}-${timestamp}`;
    }

    // 格式化JSON字符串，使其更具可读性
    function formatJsonString(jsonStr) {
        try {
            // 如果输入已经是对象，直接格式化
            if (typeof jsonStr === 'object') {
                return Utils.escapeHtml(JSON.stringify(jsonStr, null, 2));
            }
            
            // 尝试解析字符串为JSON对象
            const parsedObj = JSON.parse(jsonStr);
            // 重新格式化为带缩进的字符串
            return Utils.escapeHtml(JSON.stringify(parsedObj, null, 2));
        } catch (e) {
            // 如果不是有效的JSON，直接返回原始字符串
            return Utils.escapeHtml(jsonStr);
        }
    }

    // 初始化函数
    function init(config) {
        // 保存配置
        API_BASE_URL = config.API_BASE_URL;
        WEB_API_BASE_URL = config.WEB_API_BASE_URL;
        
        // 初始化DOM元素引用
        strongSearchModal = document.getElementById('strong-search-modal');
        strongSearchModalClose = document.getElementById('strong-search-modal-close');
        strongSearchModalCodebaseNameEl = document.getElementById('strong-search-modal-codebase-name');
        strongSearchConnectionStatus = document.getElementById('strong-search-connection-status');
        strongSearchModalForm = document.getElementById('strong-search-modal-form');
        strongSearchModalQueryInput = document.getElementById('strong-search-modal-query');
        strongSearchModalSubmitBtn = document.getElementById('strong-search-modal-submit');
        strongSearchModalStopBtn = document.getElementById('strong-search-modal-stop');
        strongSearchModalResultsArea = document.getElementById('strong-search-modal-results-area');
        strongSearchModalProgressBar = document.getElementById('strong-search-modal-progress-bar');
        strongSearchModalLogContainer = document.getElementById('strong-search-modal-log-container');
        strongSearchModalResultContainer = document.getElementById('strong-search-modal-result-container');
        strongSearchModalResultAnswer = document.getElementById('strong-search-modal-result-answer');
        strongSearchModalRelevantFiles = document.getElementById('strong-search-modal-relevant-files');
        strongSearchModalTime = document.getElementById('strong-search-modal-time');
        strongSearchModalTabButtons = strongSearchModal ? strongSearchModal.querySelectorAll('.tabs .tab-button') : [];
        strongSearchModalTabContents = strongSearchModal ? strongSearchModal.querySelectorAll('.strong-search-tab-panel') : [];
        
        // 绑定事件
        bindEvents();
    }

    // 事件绑定
    function bindEvents() {
        // 强效搜索模态框关闭按钮
        if (strongSearchModalClose) {
            strongSearchModalClose.addEventListener('click', closeModal);
        }
        
        // 强效搜索模态框背景点击关闭
        if (strongSearchModal) {
            strongSearchModal.addEventListener('click', (e) => {
                if (e.target === strongSearchModal) {
                    closeModal();
                }
            });
        }
        
        // 强效搜索表单提交
        if (strongSearchModalForm) {
            strongSearchModalForm.addEventListener('submit', (e) => {
                e.preventDefault();
                startStrongSearch();
            });
        }
        
        // 停止按钮
        if (strongSearchModalStopBtn) {
            strongSearchModalStopBtn.addEventListener('click', stopStrongSearch);
        }
        
        // 现代化标签页切换 - 使用专用类名和内联样式
        strongSearchModalTabButtons.forEach(button => {
            button.addEventListener('click', () => {
                const tabId = button.getAttribute('data-tab');
                
                // 1. 更新标签按钮状态
                strongSearchModalTabButtons.forEach(btn => {
                    btn.classList.remove('active');
                });
                
                // 为激活按钮添加类
                button.classList.add('active');
                
                // 2. 隐藏所有标签内容 - 使用CSS类
                strongSearchModalTabContents.forEach(content => {
                    content.classList.remove('active');
                    content.style.display = 'none';
                });
                
                // 3. 显示当前标签内容 - 使用CSS类
                const activeContent = document.getElementById(`tab-${tabId}`);
                if (activeContent) {
                    activeContent.classList.add('active');
                    activeContent.style.display = 'block';
                    
                    // 添加简单的淡入效果
                    activeContent.style.opacity = '0';
                    activeContent.style.transition = 'opacity 0.3s ease';
                    setTimeout(() => {
                        activeContent.style.opacity = '1';
                    }, 50);
                }
            });
        });
    }

    // 打开强效搜索模态框
    function openModal(codebaseName) {
        if (!strongSearchModal) return;
        currentStrongSearchCodebase = codebaseName;
        strongSearchModalCodebaseNameEl.textContent = codebaseName;
        resetStrongSearchUI(); // 重置UI
        UI.openModal(strongSearchModal);
        
        // 打开模态框时立即连接WebSocket，以提高用户体验
        connectStrongSearchWebSocket().catch(error => {
            console.error("WebSocket连接失败:", error);
            addStrongSearchLog("WebSocket连接失败，请重试", "error");
        });
    }
    
    // 关闭强效搜索模态框
    function closeModal() {
        disconnectStrongSearchWebSocket(); // 关闭时断开WebSocket连接
        UI.closeModal(strongSearchModal);
        currentStrongSearchCodebase = null;
        isStrongSearching = false;
    }
    
    // 重置强效搜索UI - 使用现代化样式
    function resetStrongSearchUI() {
        if (!strongSearchModal) return;
        if (strongSearchModalForm) strongSearchModalForm.reset();
        if (strongSearchModalResultsArea) strongSearchModalResultsArea.classList.add('hidden');
        if (strongSearchModalLogContainer) strongSearchModalLogContainer.innerHTML = '';
        if (strongSearchModalResultAnswer) strongSearchModalResultAnswer.innerHTML = '';
        if (strongSearchModalRelevantFiles) strongSearchModalRelevantFiles.innerHTML = '';
        if (strongSearchModalTime) strongSearchModalTime.textContent = '';
        updateStrongSearchProgressBar(0); // 重置进度条
        updateStrongSearchConnectionStatus('disconnected');
        updateStrongSearchUIState();
        
        // 清空工具调用映射
        toolCallMap = {};
        toolCallsByName = {};
        
        // 重置标签页到默认状态 - 使用现代化样式
        if (strongSearchModalTabButtons.length > 0) {
            // 1. 更新标签按钮状态
            strongSearchModalTabButtons.forEach(btn => {
                btn.classList.remove('active');
            });
            
            // 为第一个按钮添加激活样式
            strongSearchModalTabButtons[0].classList.add('active');
        }
        
        if (strongSearchModalTabContents.length > 0) {
            // 2. 隐藏所有标签内容
            strongSearchModalTabContents.forEach(content => {
                content.classList.remove('active');
                content.style.display = 'none';
            });
            
            // 3. 显示日志标签内容
            const logsTab = strongSearchModal.querySelector('#tab-strong-search-logs');
            if(logsTab) {
                logsTab.classList.add('active');
                logsTab.style.display = 'block';
                logsTab.style.opacity = '1';
            }
            
            // 确保结果标签页不显示
            const resultsTab = strongSearchModal.querySelector('#tab-strong-search-final-result');
            if(resultsTab) {
                resultsTab.classList.remove('active'); 
                resultsTab.style.display = 'none';
            }
        }
    }
    
    // 更新强效搜索WebSocket连接状态显示
    function updateStrongSearchConnectionStatus(status) {
        if (!strongSearchConnectionStatus) return;
        strongSearchConnectionStatus.classList.remove('status-connected', 'status-connecting', 'status-disconnected');
        let icon = 'fa-plug';
        let text = '未连接';
        
        if (status === 'connecting') {
            strongSearchConnectionStatus.classList.add('status-connecting');
            icon = 'fa-sync fa-spin';
            text = '正在连接...';
        } else if (status === 'connected') {
            strongSearchConnectionStatus.classList.add('status-connected');
            icon = 'fa-plug';
            text = '已连接';
        } else { // disconnected or error
            strongSearchConnectionStatus.classList.add('status-disconnected');
            icon = 'fa-plug';
            text = '连接已断开';
        }
        strongSearchConnectionStatus.innerHTML = `<i class="fas ${icon}"></i> ${text}`;
    }
    
    // 获取新的强效搜索客户端ID
    async function getStrongSearchClientId() {
        try {
            const response = await fetch(`${WEB_API_BASE_URL}/strong_search/new_client_id`);
            if (!response.ok) throw new Error(`API请求失败: ${response.status}`);
            const data = await response.json();
            return data.client_id;
        } catch (error) {
            console.error('获取强效搜索客户端ID出错:', error);
            addStrongSearchLog('无法获取客户端ID: ' + error.message, 'error');
            throw error; // 重新抛出以阻止连接尝试
        }
    }
    
    // 连接强效搜索WebSocket
    async function connectStrongSearchWebSocket() {
        if (strongSearchSocket && strongSearchSocket.readyState === WebSocket.OPEN) {
            console.log('WebSocket已连接');
            return true; // 已经连接
        }
        
        try {
            strongSearchClientId = await getStrongSearchClientId();
            updateStrongSearchConnectionStatus('connecting');
            
            // 使用API_BASE_URL中的主机和协议，确保连接到API服务器
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            // 从API_BASE_URL解析主机和端口
            const apiUrl = new URL(API_BASE_URL);
            // 构建WebSocket URL，确保连接到API服务器(30089端口)
            const wsUrl = `${protocol}//${apiUrl.host}/ws/strong_search/${strongSearchClientId}`;
            
            console.log('连接到WebSocket:', wsUrl);
            strongSearchSocket = new WebSocket(wsUrl);
            
            return new Promise((resolve, reject) => {
                strongSearchSocket.onopen = () => {
                    console.log('WebSocket连接已建立');
                    updateStrongSearchConnectionStatus('connected');
                    addStrongSearchLog('WebSocket连接成功', 'success');
                    resolve(true);
                };
                
                strongSearchSocket.onmessage = (event) => {
                    try {
                        const data = JSON.parse(event.data);
                        handleStrongSearchWebSocketMessage(data);
                    } catch (e) {
                        console.error("解析WebSocket消息失败:", e, event.data);
                        addStrongSearchLog("收到无法解析的消息", "error");
                    }
                };
                
                strongSearchSocket.onclose = (event) => {
                    console.log('WebSocket连接已关闭', event);
                    updateStrongSearchConnectionStatus('disconnected');
                    if (isStrongSearching) {
                        addStrongSearchLog('WebSocket连接意外断开', 'error');
                    }
                    isStrongSearching = false;
                    updateStrongSearchUIState();
                    strongSearchSocket = null;
                };
                
                strongSearchSocket.onerror = (error) => {
                    console.error('WebSocket错误:', error);
                    updateStrongSearchConnectionStatus('disconnected');
                    addStrongSearchLog('WebSocket连接错误', 'error');
                    isStrongSearching = false;
                    updateStrongSearchUIState();
                    strongSearchSocket = null;
                    reject(new Error('WebSocket连接失败')); // 在初始连接错误时拒绝
                };
            });
        } catch (error) {
            updateStrongSearchConnectionStatus('disconnected');
            return false;
        }
    }
    
    // 断开强效搜索WebSocket连接
    function disconnectStrongSearchWebSocket() {
        if (strongSearchSocket) {
            console.log('正在断开WebSocket连接...');
            strongSearchSocket.close();
            strongSearchSocket = null;
            strongSearchClientId = null;
            updateStrongSearchConnectionStatus('disconnected');
        }
    }
    
    // 处理强效搜索WebSocket消息
    async function handleStrongSearchWebSocketMessage(data) {
        console.log('收到WebSocket消息:', data);
        switch (data.type) {
            case 'log':
                const level = data.level || '';
                const message = data.message || '';
                
                // 特殊处理工具调用相关的日志
                if (level === 'tool_call' || level === 'tool_call_decision' || level === 'tool_output' || level === 'agent_thinking') {
                    // 显示工具调用和输出
                    addStrongSearchLog(message, level);
                } else {
                    // 处理普通日志
                    addStrongSearchLog(message, level);
                }
                break;
            case 'progress':
                updateStrongSearchProgressBar(data.progress, data.status);
                break;
            case 'result':
                await displayStrongSearchResult(data.result);
                isStrongSearching = false;
                updateStrongSearchUIState();
                break;
            case 'error':
                addStrongSearchLog(data.error, 'error');
                isStrongSearching = false;
                updateStrongSearchUIState();
                break;
            default:
                console.warn('收到未知类型的WebSocket消息:', data);
                addStrongSearchLog(`收到未知消息: ${JSON.stringify(data)}`, 'warning');
        }
    }
    
    // 添加强效搜索日志条目 - 保持最新日志可见
    function addStrongSearchLog(message, level = 'info') {
        if (!strongSearchModalLogContainer) return;

        const entry = document.createElement('div');
        entry.className = `log-entry log-${level}`; // 应用基本样式和级别样式
        const timestamp = new Date().toLocaleTimeString();
        let formattedMessage = '';
        let isToolCall = false;
        
        // 处理工具输出，尝试匹配之前的工具调用
        if (level === 'tool_output' && typeof message === 'object' && message.tool_name) {
            const toolName = message.tool_name;
            const outputPreview = message.output_preview || "[无输出]";
            const timestamp = message.timestamp || Date.now();
            
            // 查找对应的工具调用 - 优先使用精确匹配
            const toolCallId = generateToolCallId(toolName, timestamp);
            let toolCallEntry = toolCallMap[toolCallId];
            
            // 如果没找到精确匹配，尝试使用工具名称找到最近的工具调用
            if (!toolCallEntry && toolCallsByName[toolName]) {
                toolCallEntry = toolCallsByName[toolName];
                console.log(`使用工具名称匹配工具调用: ${toolName}`);
            }
            
            if (toolCallEntry) {
                // 找到工具调用条目内的输出容器
                let outputContainer = toolCallEntry.querySelector('.tool-output-container');
                
                // 显示输出容器
                if (outputContainer) {
                    outputContainer.style.display = 'block';
                    outputContainer.innerHTML = '';
                } else {
                    // 如果没有找到容器（旧版本的banner），创建一个
                    outputContainer = document.createElement('div');
                    outputContainer.className = 'tool-output-container';
                    outputContainer.style.marginTop = '12px';
                    outputContainer.style.paddingTop = '12px';
                    outputContainer.style.borderTop = '1px dashed #e5e7eb';
                    toolCallEntry.appendChild(outputContainer);
                }
                
                // 填充输出内容 - 移除 max-height
                outputContainer.innerHTML = 
                    `<div style="margin-top: 8px; cursor: pointer;" onclick="this.nextElementSibling.style.display = this.nextElementSibling.style.display === 'none' ? 'block' : 'none';">
                        <div style="display: flex; justify-content: space-between; align-items: center; padding: 8px; border: 1px solid #e5e7eb; border-radius: 4px; background-color: #f9fafb;">
                            <div>
                                <i class="fas fa-reply" style="color: #37b24d; margin-right: 8px;"></i>
                                <span style="font-weight: 500; color: #2b6cb0;">输出结果</span>
                            </div>
                            <span style="font-weight: 400; color: #6b7280; font-size: 0.9em;">点击查看详情</span>
                        </div>
                    </div>
                    <div style="display: none; margin-top: 0.5rem;">
                        <pre style="background-color: #f1f3f5; padding: 0.75rem; border-radius: 3px; font-size: 0.85em; overflow-y: auto; border: 1px solid #dee2e6; white-space: pre-wrap;">${formatJsonString(outputPreview)}</pre> 
                    </div>`;
                
                // 已经处理了这个输出，不需要创建新条目
                return;
            }
            // 如果没找到对应调用，就当普通日志处理
            console.log(`未找到匹配的工具调用: ${toolName} (${timestamp})`);
        }

        // 智能解析消息，优先处理结构化对象
        if (typeof message === 'object' && message !== null) {
            // 检查是否是工具调用
            if (message.tool_name) {
                isToolCall = true;
                const toolName = message.tool_name || '未知工具';
                const params = message.parameters ? JSON.stringify(message.parameters, null, 2) : '{}';
                const msgTimestamp = message.timestamp || Date.now();
                const isOutput = message.is_output || false;
                
                if (level === 'tool_call_decision') {
                    //不需要
                } else if (level === 'tool_call') {
                    // 标准工具调用 - 创建Banner样式 - 移除参数 max-height
                    formattedMessage = 
                        `<div class="tool-call-banner" style="border: 1px solid #e9ecef; border-radius: 6px; background-color: #f8f9fa; padding: 12px; margin-bottom: 10px;">
                            <div style="display: flex; align-items: center; margin-bottom: 8px;">
                                <i class="fas fa-wrench" style="color: #f76707; margin-right: 10px;"></i>
                                <span style="font-weight: 600; color: #1a202c;">调用工具: ${Utils.escapeHtml(toolName)}</span>
                            </div>
                            <div style="cursor: pointer;" onclick="this.nextElementSibling.style.display = this.nextElementSibling.style.display === 'none' ? 'block' : 'none';">
                                <div style="display: flex; justify-content: space-between; align-items: center; padding: 8px; border: 1px solid #e5e7eb; border-radius: 4px; background-color: #f9fafb;">
                                    <div>
                                        <i class="fas fa-share" style="color: #37b24d; margin-right: 8px;"></i>
                                        <span style="font-weight: 500; color: #2b6cb0;">输入参数</span>
                                    </div>
                                    <span style="font-weight: 400; color: #6b7280; font-size: 0.9em;">点击查看详情</span>
                                </div>
                            </div>
                            <div style="display: none; margin-top: 0.5rem;">
                                <pre style="background-color: #f1f3f5; padding: 0.75rem; border-radius: 3px; font-size: 0.85em; overflow-y: auto; border: 1px solid #dee2e6; white-space: pre-wrap;">${formatJsonString(params)}</pre> 
                            </div>
                            <div class="tool-output-container" style="display: none;"></div>
                        </div>`;
                    
                    // 存储这个工具调用，以便后续将输出匹配回来
                    const toolCallId = generateToolCallId(toolName, msgTimestamp);
                    toolCallMap[toolCallId] = entry;
                    
                    // 同时按工具名称存储最近的工具调用
                    toolCallsByName[toolName] = entry;
                }
            } else if (level === 'agent_thinking') {
                // 特殊处理Agent思考/决策消息 - 移除宽度限制，让其填充父容器
                formattedMessage = 
                    `<div>` + // 使用简单的 div 包裹
                    `<div style="margin-bottom: 8px;">🧠 <strong>Agent 思考/决策</strong></div>` +
                    `<div style="margin-left: 20px; background-color: #f0f7ff; border-left: 3px solid #3b82f6; padding: 12px; border-radius: 4px; font-style: italic; color: #1e40af;">` +
                    `${typeof message === 'string' ? Utils.escapeHtml(message) : formatJsonString(JSON.stringify(message, null, 2))}` +
                    `</div>` +
                    `</div>`; // 关闭容器
            } else {
                // 如果是其他对象，格式化为JSON
                formattedMessage = `<pre style="background-color: #f9fafb; padding: 0.5rem; border-radius: 4px; border: 1px solid #e5e7eb; font-size: 0.9em; white-space: pre-wrap;">${formatJsonString(JSON.stringify(message, null, 2))}</pre>`;
            }
        } else if (typeof message === 'string') {
            // 检查是否是Agent思考/决策消息
            if (level === 'agent_thinking') {
                 // 特殊处理Agent思考/决策消息 - 移除宽度限制
                formattedMessage = 
                    `<div>` + // 使用简单的 div 包裹
                    `<div style="margin-bottom: 8px;">🧠 <strong>Agent 思考/决策</strong></div>` +
                    `<div style="margin-left: 20px; background-color: #f0f7ff; border-left: 3px solid #3b82f6; padding: 12px; border-radius: 4px; font-style: italic; color: #1e40af;">` +
                    `${Utils.escapeHtml(message)}` +
                    `</div>` +
                    `</div>`; // 关闭容器
            } else {
                // 尝试解析字符串形式的工具调用
                try {
                    // 简单的检查，看它是否像一个 JSON 对象并包含 tool_name
                    if (message.trim().startsWith('{') && message.includes('"tool_name":')) {
                        const parsed = JSON.parse(message);
                        if (parsed.tool_name) {
                            isToolCall = true;
                            const toolName = parsed.tool_name || '未知工具';
                            const params = parsed.parameters ? JSON.stringify(parsed.parameters, null, 2) : '{}';
                            const msgTimestamp = parsed.timestamp || Date.now();
                            
                             // 标准工具调用 - 创建Banner样式 - 移除参数 max-height
                            formattedMessage = 
                                `<div class="tool-call-banner" style="border: 1px solid #e9ecef; border-radius: 6px; background-color: #f8f9fa; padding: 12px; margin-bottom: 10px;">
                                    <div style="display: flex; align-items: center; margin-bottom: 8px;">
                                        <i class="fas fa-wrench" style="color: #f76707; margin-right: 10px;"></i>
                                        <span style="font-weight: 600; color: #1a202c;">调用工具: ${Utils.escapeHtml(toolName)}</span>
                                    </div>
                                    <div style="cursor: pointer;" onclick="this.nextElementSibling.style.display = this.nextElementSibling.style.display === 'none' ? 'block' : 'none';">
                                        <div style="display: flex; justify-content: space-between; align-items: center; padding: 8px; border: 1px solid #e5e7eb; border-radius: 4px; background-color: #f9fafb;">
                                            <div>
                                                <i class="fas fa-share" style="color: #37b24d; margin-right: 8px;"></i>
                                                <span style="font-weight: 500; color: #2b6cb0;">输入参数</span>
                                            </div>
                                            <span style="font-weight: 400; color: #6b7280; font-size: 0.9em;">点击查看详情</span>
                                        </div>
                                    </div>
                                    <div style="display: none; margin-top: 0.5rem;">
                                        <pre style="background-color: #f1f3f5; padding: 0.75rem; border-radius: 3px; font-size: 0.85em; overflow-y: auto; border: 1px solid #dee2e6; white-space: pre-wrap;">${formatJsonString(params)}</pre>
                                    </div>
                                    <div class="tool-output-container" style="display: none;"></div>
                                </div>`;
                                
                            // 存储这个工具调用，以便后续将输出匹配回来
                            const toolCallId = generateToolCallId(toolName, msgTimestamp);
                            toolCallMap[toolCallId] = entry;
                            
                            // 同时按工具名称存储最近的工具调用
                            toolCallsByName[toolName] = entry;
                        }
                    }
                } catch (e) {
                    // 解析失败，当作普通字符串处理
                }
            }
            
            // 如果不是工具调用字符串，则正常显示
            if (!formattedMessage) {
                formattedMessage = Utils.escapeHtml(message);
            }
        } else {
            // 其他类型，转为字符串
            formattedMessage = Utils.escapeHtml(String(message));
        }

        // 添加级别对应的图标
        let iconClass = 'fa-info-circle';
        if (isToolCall) {
            if (level === 'tool_call_decision') {
                iconClass = 'fa-lightbulb'; // 决策用灯泡图标
            } else if (level === 'tool_output') {
                iconClass = 'fa-reply'; // 输出用回复图标
            } else {
                iconClass = 'fa-wrench'; // 工具调用用扳手图标
            }
        } else if (level === 'agent_thinking') {
            iconClass = 'fa-brain'; // 思考用大脑图标
        } else {
            switch (level) {
                case 'error': iconClass = 'fa-exclamation-circle'; break;
                case 'warning': iconClass = 'fa-exclamation-triangle'; break;
                case 'success': iconClass = 'fa-check-circle'; break;
                case 'debug': iconClass = 'fa-bug'; break;
                case 'trace': iconClass = 'fa-shoe-prints'; break;
            }
        }

        if (formattedMessage.length > 0){
            entry.innerHTML = `<i class="fas ${iconClass}" style="margin-right: 8px; min-width: 14px; text-align: center;"></i> <span class="log-timestamp">[${timestamp}]</span> ${formattedMessage}`;
            
            // 在容器末尾添加新日志（最新的在底部）
            strongSearchModalLogContainer.appendChild(entry);
            
            // 限制日志条目数量，从顶部移除最旧的
            const maxLogEntries = 200;
            while (strongSearchModalLogContainer.children.length > maxLogEntries) {
                strongSearchModalLogContainer.removeChild(strongSearchModalLogContainer.firstChild);
            }
            
            // 自动滚动到底部
            strongSearchModalLogContainer.scrollTop = strongSearchModalLogContainer.scrollHeight;
        }
    }
    
    // 更新强效搜索进度条
    function updateStrongSearchProgressBar(progress, status = '') {
        if (!strongSearchModalProgressBar) return;
        const percent = Math.max(0, Math.min(100, Math.round(progress * 100)));
        strongSearchModalProgressBar.style.width = `${percent}%`;
        strongSearchModalProgressBar.textContent = `${percent}%`;
        if (status) {
            strongSearchModalProgressBar.setAttribute('title', status);
        }
    }
    
    // 显示强效搜索结果 - 使用现代化样式和文件内容获取
    async function displayStrongSearchResult(result) { // 标记为异步
        if (!strongSearchModalResultContainer) return;

        // 在结果标签页中填充内容，而不是覆盖实时日志
        try {
            // 清空结果容器
            strongSearchModalResultContainer.innerHTML = '';
            
            // 添加回答部分 - 移除宽度限制，添加左右内边距
            const answerDiv = document.createElement('div');
            answerDiv.className = 'result-answer-container';
            answerDiv.style.margin = '0 0 2rem 0'; // 只设置底部外边距
            answerDiv.style.padding = '1rem 1.5rem'; // 上下 1rem, 左右 1.5rem
            answerDiv.style.backgroundColor = '#f9fafb';
            answerDiv.style.borderRadius = '0.5rem';
            answerDiv.style.border = '1px solid #e5e7eb';
            
            const answerTitle = document.createElement('h4');
            answerTitle.innerHTML = '<i class="fas fa-lightbulb" style="color: #4f46e5; margin-right: 0.5rem;"></i> 搜索回答';
            answerTitle.style.marginBottom = '1rem';
            answerTitle.style.paddingBottom = '0.5rem';
            answerTitle.style.borderBottom = '1px solid #e5e7eb';
            answerDiv.appendChild(answerTitle);
            
            const answerContent = document.createElement('div');
            answerContent.className = 'answer-content';
            // 直接使用result中的answer，而不是引用可能为空的strongSearchModalResultAnswer
            if (result.answer) {
                answerContent.innerHTML = marked.parse(result.answer);
            } else {
                answerContent.innerHTML = '<p style="font-style: italic; color: #6b7280; text-align: center;">未提供搜索回答。</p>';
            }
            answerDiv.appendChild(answerContent);
            
            strongSearchModalResultContainer.appendChild(answerDiv);
            
            // 创建并添加项目结构区域 - 移除宽度限制，添加左右内边距
            const projectStructureDiv = document.createElement('div');
            projectStructureDiv.className = 'project-structure-container';
            projectStructureDiv.style.margin = '0 0 2rem 0'; // 只设置底部外边距
            projectStructureDiv.style.padding = '1rem 1.5rem'; // 上下 1rem, 左右 1.5rem
            projectStructureDiv.style.backgroundColor = '#f9fafb';
            projectStructureDiv.style.borderRadius = '0.5rem';
            projectStructureDiv.style.border = '1px solid #e5e7eb';
            
            const projectStructureTitle = document.createElement('h4');
            projectStructureTitle.innerHTML = '<i class="fas fa-project-diagram" style="color: #4f46e5; margin-right: 0.5rem;"></i> 项目结构';
            projectStructureTitle.style.marginBottom = '1rem';
            projectStructureTitle.style.paddingBottom = '0.5rem';
            projectStructureTitle.style.borderBottom = '1px solid #e5e7eb';
            
            const projectStructureContent = document.createElement('div');
            projectStructureContent.className = 'project-structure-content';
            projectStructureContent.style.overflowY = 'auto';
            projectStructureContent.style.fontFamily = 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace';
            projectStructureContent.style.fontSize = '0.85rem';
            
            // 处理项目结构数据
            if (result.project_structure && typeof result.project_structure === 'object') {
                // 尝试格式化项目结构
                try {
                    // 检查是否有新格式的结构 (包含text_tree)
                    let structureDisplay = '';
                    if (result.project_structure.text_tree) {
                        // 新格式：使用文本树
                        structureDisplay = result.project_structure.text_tree;
                        // 将文本树中的换行转换为HTML换行
                        structureDisplay = structureDisplay.replace(/\n/g, '<br>');
                        // 为缩进添加不间断空格以保持格式
                        structureDisplay = structureDisplay.replace(/ {4}/g, '&nbsp;&nbsp;&nbsp;&nbsp;');
                        
                        // 为树形结构添加基本样式
                        const structureTextElement = document.createElement('div');
                        structureTextElement.style.fontFamily = 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace';
                        structureTextElement.style.whiteSpace = 'pre-wrap';
                        structureTextElement.style.fontSize = '0.85rem';
                        structureTextElement.style.lineHeight = '1.5';
                        structureTextElement.innerHTML = structureDisplay;
                        projectStructureContent.appendChild(structureTextElement);
                    }
                } catch (error) {
                    projectStructureContent.textContent = '无法解析项目结构数据';
                    console.error('解析项目结构时出错:', error);
                }
            } else {
                projectStructureContent.textContent = '未提供项目结构信息';
            }
            
            projectStructureDiv.appendChild(projectStructureTitle);
            projectStructureDiv.appendChild(projectStructureContent);
            strongSearchModalResultContainer.appendChild(projectStructureDiv);
            
            // 显示相关文件区域 - 移除宽度限制，添加左右内边距
            const relevantFilesDiv = document.createElement('div');
            relevantFilesDiv.className = 'relevant-files-container';
            relevantFilesDiv.style.margin = '0 0 1rem 0'; // 只设置底部外边距
            relevantFilesDiv.style.padding = '1rem 1.5rem'; // 上下 1rem, 左右 1.5rem
            relevantFilesDiv.style.backgroundColor = '#f9fafb';
            relevantFilesDiv.style.borderRadius = '0.5rem';
            relevantFilesDiv.style.border = '1px solid #e5e7eb';
            
            const relevantFilesTitle = document.createElement('h4');
            relevantFilesTitle.innerHTML = '<i class="fas fa-file-code" style="color: #4f46e5; margin-right: 0.5rem;"></i> 相关文件';
            relevantFilesTitle.style.marginBottom = '1rem';
            relevantFilesTitle.style.paddingBottom = '0.5rem';
            relevantFilesTitle.style.borderBottom = '1px solid #e5e7eb';
            relevantFilesDiv.appendChild(relevantFilesTitle);
            
            // 直接使用result中的相关文件，而不依赖strongSearchModalRelevantFiles
            const relevantFilesContent = document.createElement('div');
            relevantFilesContent.className = 'relevant-files-content';
            const files = result.relevant_files || [];

            if (files.length === 0) {
                relevantFilesContent.innerHTML = '<p style="font-style: italic; color: #6b7280; text-align: center; padding: 1rem;">未找到相关文件。</p>';
            } else {
                const fileListUl = document.createElement('ul');
                fileListUl.style.listStyle = 'none';
                fileListUl.style.padding = '0';
                fileListUl.style.margin = '0';

                // 批量获取文件内容
                let fileContents = {};
                if (files.length > 0 && currentStrongSearchCodebase) {
                    try {
                        const response = await fetch(`${WEB_API_BASE_URL}/codebases/${currentStrongSearchCodebase}/files/batch`, {
                            method: 'POST',
                            headers: {
                                'Content-Type': 'application/json',
                            },
                            body: JSON.stringify({ file_paths: files })
                        });
                        if (response.ok) {
                            const batchResult = await response.json();
                            fileContents = batchResult.contents || {};
                        } else {
                            console.error("批量获取文件内容失败:", response.status);
                            files.forEach(file => fileContents[file] = "错误: 无法加载内容");
                        }
                    } catch (error) {
                        console.error("批量获取文件内容API调用失败:", error);
                        files.forEach(file => fileContents[file] = "错误: 加载内容时发生网络错误");
                    }
                } else {
                    files.forEach(file => fileContents[file] = "无法加载内容 (未提供代码库名称或文件列表)");
                }

                // 渲染每个文件
                files.forEach(file => {
                    const li = document.createElement('li');
                    li.style.marginBottom = '1rem';
                    li.style.padding = '0.75rem';
                    li.style.backgroundColor = 'white';
                    li.style.borderRadius = '0.5rem';
                    li.style.boxShadow = '0 1px 2px rgba(0,0,0,0.05)';
                    li.style.border = '1px solid #e5e7eb';

                    const fileNameH5 = document.createElement('div');
                    fileNameH5.innerHTML = `<i class="fas fa-file-alt" style="color: #4f46e5; margin-right: 0.5rem;"></i> <span style="font-weight: 500;">${Utils.escapeHtml(file)}</span>`;
                    fileNameH5.style.marginBottom = '0.5rem';
                    fileNameH5.style.cursor = 'pointer';
                    
                    // 创建可折叠的内容展示
                    const contentContainer = document.createElement('div');
                    contentContainer.style.display = 'none';
                    contentContainer.style.marginTop = '0.5rem';
                    
                    // 点击文件名切换内容显示/隐藏
                    fileNameH5.addEventListener('click', () => {
                        contentContainer.style.display = contentContainer.style.display === 'none' ? 'block' : 'none';
                        // 显示时添加小动画效果
                        if (contentContainer.style.display === 'block') {
                            contentContainer.style.opacity = '0';
                            contentContainer.style.transition = 'opacity 0.3s ease';
                            setTimeout(() => {
                                contentContainer.style.opacity = '1';
                            }, 10);
                        }
                    });

                    const contentPre = document.createElement('pre');
                    contentPre.style.overflow = 'auto';
                    contentPre.style.backgroundColor = '#f8f9fa';
                    contentPre.style.padding = '0.75rem';
                    contentPre.style.borderRadius = '0.25rem';
                    contentPre.style.fontSize = '0.85rem';
                    contentPre.style.fontFamily = 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace';
                    contentPre.style.marginTop = '0.5rem';
                    contentPre.style.border = '1px solid #ddd';

                    const contentCode = document.createElement('code');
                    contentCode.textContent = fileContents[file] || "无法加载内容。";
                    contentPre.appendChild(contentCode);

                    contentContainer.appendChild(contentPre);
                    li.appendChild(fileNameH5);
                    li.appendChild(contentContainer);
                    fileListUl.appendChild(li);
                });
                
                relevantFilesContent.appendChild(fileListUl);
            }
            
            relevantFilesDiv.appendChild(relevantFilesContent);
            strongSearchModalResultContainer.appendChild(relevantFilesDiv);

            // 显示执行时间
            const executionTime = result.execution_time || 0;
            const timeElement = document.createElement('div');
            timeElement.textContent = `搜索耗时: ${executionTime.toFixed(2)} 秒`;
            timeElement.style.textAlign = 'center';
            timeElement.style.fontStyle = 'italic';
            timeElement.style.color = '#6b7280';
            timeElement.style.marginTop = '1rem'; // 确保时间显示在卡片下方
            strongSearchModalResultContainer.appendChild(timeElement);

            // 切换到结果标签页
            const resultsTabButton = strongSearchModal.querySelector('.tab-button[data-tab="strong-search-final-result"]');
            if (resultsTabButton) {
                // 1. 更新标签按钮状态
                strongSearchModalTabButtons.forEach(btn => {
                    btn.classList.remove('active');
                });
                
                // 为激活按钮添加类
                resultsTabButton.classList.add('active');
                
                // 2. 隐藏所有标签内容
                strongSearchModalTabContents.forEach(content => {
                    content.classList.remove('active');
                    content.style.display = 'none';
                });
                
                // 3. 显示结果标签内容
                const resultsContent = document.getElementById('tab-strong-search-final-result');
                if (resultsContent) {
                    resultsContent.classList.add('active');
                    resultsContent.style.display = 'block';
                    
                    // 添加简单的淡入效果
                    resultsContent.style.opacity = '0';
                    resultsContent.style.transition = 'opacity 0.3s ease';
                    setTimeout(() => {
                        resultsContent.style.opacity = '1';
                    }, 50);
                }
            }

            // 添加日志
            addStrongSearchLog('搜索完成，结果已显示', 'success');
        } catch (error) {
            console.error('显示搜索结果时出错:', error);
            addStrongSearchLog('显示搜索结果时出错: ' + error.message, 'error');
        }
    }
    
    // 开始强效搜索 - 不清除之前的日志
    async function startStrongSearch() {
        if (isStrongSearching || !currentStrongSearchCodebase || !strongSearchModalQueryInput) return;
        
        const query = strongSearchModalQueryInput.value.trim();
        if (!query) {
            addStrongSearchLog('请输入查询内容', 'warning');
            return;
        }
        
        // 显示结果区域但不清除之前的日志
        if (strongSearchModalResultsArea) strongSearchModalResultsArea.classList.remove('hidden');
        
        // 添加分隔线表明新的搜索开始
        addStrongSearchLog('--------- 新的搜索开始 ---------', 'info');
        
        // 切换回日志标签页
        const logsTabButton = strongSearchModal ? strongSearchModal.querySelector('.tab-button[data-tab="strong-search-logs"]') : null;
        if (logsTabButton) logsTabButton.click();

        updateStrongSearchProgressBar(0, '准备搜索...');
        addStrongSearchLog(`准备开始强效搜索: "${query}"`, 'info');
        
        isStrongSearching = true;
        updateStrongSearchUIState();
        
        try {
            // 连接WebSocket
            const connected = await connectStrongSearchWebSocket();
            if (!connected) {
                throw new Error("WebSocket连接失败");
            }
            
            // 发送搜索请求
            if (strongSearchSocket && strongSearchSocket.readyState === WebSocket.OPEN) {
                strongSearchSocket.send(JSON.stringify({
                    codebase_name: currentStrongSearchCodebase,
                    query: query
                }));
                addStrongSearchLog('搜索请求已发送', 'info');
                updateStrongSearchProgressBar(0.05, '请求已发送...'); 
            } else {
                throw new Error("WebSocket未连接，无法发送请求");
            }
            
        } catch (error) {
            console.error("开始强效搜索失败:", error);
            addStrongSearchLog(`启动搜索失败: ${error.message}`, 'error');
            isStrongSearching = false;
            updateStrongSearchUIState();
        }
    }
    
    // 停止强效搜索
    function stopStrongSearch() {
        if (!isStrongSearching) return;
        addStrongSearchLog('正在尝试停止搜索...', 'warning');
        disconnectStrongSearchWebSocket(); // 断开以停止
        isStrongSearching = false;
        updateStrongSearchUIState();
        updateStrongSearchProgressBar(0, '搜索已停止');
    }
    
    // 更新强效搜索UI状态 (按钮等)
    function updateStrongSearchUIState() {
        if (!strongSearchModal) return;
        if (isStrongSearching) {
            strongSearchModalSubmitBtn.disabled = true;
            strongSearchModalStopBtn.disabled = false;
            strongSearchModalQueryInput.disabled = true;
        } else {
            strongSearchModalSubmitBtn.disabled = false;
            strongSearchModalStopBtn.disabled = true;
            strongSearchModalQueryInput.disabled = false;
        }
    }

    // 对外暴露API
    return {
        init,
        openModal,
        closeModal,
        startStrongSearch,
        stopStrongSearch
    };
})();

// 将模块添加到全局命名空间
window.StrongSearch = StrongSearch; 