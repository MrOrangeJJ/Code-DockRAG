/**
 * settings.js - 系统设置模块
 * 处理设置模态框和API设置更新
 */

const Settings = (function() {
    // 私有变量
    let settingsModal;
    let settingsForm;
    let settingsCloseBtn;
    let settingsBtn;
    let settingsResetBtn;
    let settingsStatus;
    let modelNameInput;
    let modelBaseUrlInput;
    let modelApiKeyInput;
    let maxTurnsInput;
    
    let API_BASE_URL;
    
    // 初始化函数
    function init(config) {
        API_BASE_URL = config.API_BASE_URL;
        
        // 初始化DOM元素引用
        settingsModal = document.getElementById('settings-modal');
        settingsForm = document.getElementById('settings-form');
        settingsCloseBtn = document.getElementById('settings-modal-close');
        settingsBtn = document.getElementById('settings-btn');
        settingsResetBtn = document.getElementById('settings-reset');
        settingsStatus = document.getElementById('settings-status');
        modelNameInput = document.getElementById('model-name');
        modelBaseUrlInput = document.getElementById('model-base-url');
        modelApiKeyInput = document.getElementById('model-api-key');
        maxTurnsInput = document.getElementById('strong-search-max-turns');
        
        // 绑定事件
        bindEvents();
    }
    
    // 绑定事件
    function bindEvents() {
        if (settingsBtn) {
            settingsBtn.addEventListener('click', openSettingsModal);
        }
        
        if (settingsCloseBtn) {
            settingsCloseBtn.addEventListener('click', closeSettingsModal);
        }
        
        if (settingsForm) {
            settingsForm.addEventListener('submit', saveSettings);
        }
        
        if (settingsResetBtn) {
            settingsResetBtn.addEventListener('click', resetForm);
        }
        
        // 模态框背景点击关闭
        if (settingsModal) {
            settingsModal.addEventListener('click', (e) => {
                if (e.target === settingsModal) {
                    closeSettingsModal();
                }
            });
        }
    }
    
    // 打开设置模态框
    function openSettingsModal() {
        if (!settingsModal) return;
        
        // 加载当前设置
        loadCurrentSettings().then(() => {
            UI.openModal(settingsModal);
        }).catch(error => {
            console.error('加载设置失败:', error);
            showSettingsStatus('加载当前设置失败，请重试', 'error');
            UI.openModal(settingsModal);
        });
    }
    
    // 关闭设置模态框
    function closeSettingsModal() {
        UI.closeModal(settingsModal);
    }
    
    // 加载当前设置
    async function loadCurrentSettings() {
        try {
            const response = await fetch(`${API_BASE_URL}/settings/env`);
            if (!response.ok) {
                throw new Error(`API请求失败: ${response.status}`);
            }
            
            const data = await response.json();
            if (data.status === 'success') {
                const settings = data.settings;
                
                // 更新表单字段
                modelNameInput.value = settings.MODEL_NAME || '';
                modelBaseUrlInput.value = settings.MODEL_BASE_URL || '';
                // API密钥不显示实际值，用户可以重新输入
                modelApiKeyInput.value = '';
                maxTurnsInput.value = settings.STRONG_SEARCH_MAX_TURNS || '';
                
                // 清除状态消息
                clearSettingsStatus();
            } else {
                throw new Error('加载设置时出错');
            }
        } catch (error) {
            console.error('加载设置时出错:', error);
            showSettingsStatus('加载设置失败: ' + error.message, 'error');
            throw error;
        }
    }
    
    // 保存设置
    async function saveSettings(e) {
        e.preventDefault();
        
        try {
            // 收集表单数据
            const formData = {
                model_name: modelNameInput.value.trim() || null,
                model_base_url: modelBaseUrlInput.value.trim() || null,
                model_api_key: modelApiKeyInput.value.trim() || null,
                strong_search_max_turns: maxTurnsInput.value ? parseInt(maxTurnsInput.value) : null,
            };
            
            // 移除所有为null的字段
            Object.keys(formData).forEach(key => {
                if (formData[key] === null) {
                    delete formData[key];
                }
            });
            
            // 提交到API
            showSettingsStatus('正在保存设置...', 'info');
            const response = await fetch(`${API_BASE_URL}/settings/env`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(formData)
            });
            
            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.detail || `请求失败: ${response.status}`);
            }
            
            const data = await response.json();
            
            if (data.status === 'success') {
                showSettingsStatus('设置已成功保存', 'success');
                
                // 清空API密钥输入框
                modelApiKeyInput.value = '';
                
                // 3秒后自动关闭模态框
                setTimeout(() => {
                    closeSettingsModal();
                }, 3000);
            } else {
                throw new Error(data.message || '保存设置失败');
            }
        } catch (error) {
            console.error('保存设置时出错:', error);
            showSettingsStatus('保存设置失败: ' + error.message, 'error');
        }
    }
    
    // 重置表单
    function resetForm() {
        if (settingsForm) {
            settingsForm.reset();
            loadCurrentSettings().catch(error => {
                console.error('重置表单时出错:', error);
            });
        }
    }
    
    // 显示状态消息
    function showSettingsStatus(message, type = 'info') {
        if (!settingsStatus) return;
        
        settingsStatus.textContent = message;
        settingsStatus.className = `status-message status-${type}`;
        settingsStatus.style.display = 'block';
    }
    
    // 清除状态消息
    function clearSettingsStatus() {
        if (!settingsStatus) return;
        
        settingsStatus.textContent = '';
        settingsStatus.className = 'status-message';
        settingsStatus.style.display = 'none';
    }
    
    // 公开API
    return {
        init,
        openSettingsModal,
        closeSettingsModal
    };
})(); 