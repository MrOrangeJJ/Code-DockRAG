/**
 * ui-helpers.js - UI操作辅助函数
 * 提供UI交互的通用操作函数
 */

// 显示状态消息
function showStatus(element, message, type = 'info') {
    if (!element) return;
    
    // 创建新元素以应用动画
    const statusPara = document.createElement('p');
    statusPara.className = type === 'info' ? '' : `status-${type}`;
    statusPara.textContent = message;
    
    // 清除现有消息并添加新消息
    element.innerHTML = '';
    element.appendChild(statusPara);
    
    // 5秒后自动清除消息
    setTimeout(() => {
        if (statusPara.parentElement) {
            statusPara.style.opacity = '0';
            statusPara.style.transform = 'translateY(-10px)';
            statusPara.style.transition = 'opacity 0.5s ease, transform 0.5s ease';
            
            setTimeout(() => {
                if (statusPara.parentElement) {
                    element.innerHTML = '';
                }
            }, 500);
        }
    }, 5000);
}

// 显示/隐藏加载状态
function toggleLoading(element, show) {
    if (!element) return;
    if (show) {
        element.classList.remove('hidden');
    } else {
        element.classList.add('hidden');
    }
}

// 通用打开模态框函数
function openModal(modalElement) {
    if (!modalElement) return;
    
    modalElement.classList.add('open');
    document.body.style.overflow = 'hidden'; // 防止背景滚动
}

// 通用关闭模态框函数
function closeModal(modalElement) {
    if (!modalElement) return;
    
    // 添加关闭动画
    const modalContent = modalElement.querySelector('.modal-content');
    if (modalContent) {
        modalContent.style.transform = 'scale(0.95)';
        modalContent.style.opacity = '0';
        modalContent.style.transition = 'transform 0.3s ease, opacity 0.3s ease';
    }
    
    modalElement.style.opacity = '0';
    modalElement.style.transition = 'opacity 0.3s ease';
    
    setTimeout(() => {
        modalElement.classList.remove('open');
        document.body.style.overflow = '';
        
        // 重置样式以便下次打开
        if (modalContent) {
            modalContent.style.transform = '';
            modalContent.style.opacity = '';
            modalContent.style.transition = '';
        }
        modalElement.style.opacity = '';
        modalElement.style.transition = '';
    }, 300);
}

// 添加按钮点击波纹效果
function addRippleEffect(e) {
    const target = e.target.closest('.btn');
    if (!target) return;
    
    const ripple = document.createElement('span');
    const rect = target.getBoundingClientRect();
    const size = Math.max(rect.width, rect.height);
    const x = e.clientX - rect.left - size / 2;
    const y = e.clientY - rect.top - size / 2;
    
    ripple.style.width = ripple.style.height = `${size}px`;
    ripple.style.left = `${x}px`;
    ripple.style.top = `${y}px`;
    ripple.className = 'ripple';
    
    const rippleContainer = document.createElement('span');
    rippleContainer.className = 'ripple-container';
    rippleContainer.appendChild(ripple);
    
    target.appendChild(rippleContainer);
    
    setTimeout(() => {
        rippleContainer.remove();
    }, 600);
}

// 对外暴露的API
window.UI = {
    showStatus,
    toggleLoading,
    openModal,
    closeModal,
    addRippleEffect
}; 