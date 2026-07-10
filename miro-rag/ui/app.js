/**
 * app.js
 *
 * Claude-like minimalist UI logic for MIRO AI.
 */

document.addEventListener('DOMContentLoaded', () => {
    // -- DOM references --
    const chatForm       = document.getElementById('chat-form');
    const chatInput      = document.getElementById('chat-input');
    const chatMessages   = document.getElementById('chat-messages');
    const sendBtn        = document.getElementById('send-btn');
    const newChatBtn     = document.getElementById('new-chat-btn');
    const convList       = document.getElementById('conversation-list');
    const chatTitle      = document.getElementById('chat-title');
    const mainContainer  = document.getElementById('main-container');
    
    const sidebar        = document.getElementById('sidebar');
    const sidebarOverlay = document.getElementById('sidebar-overlay');
    const sidebarToggle  = document.getElementById('sidebar-toggle-btn');
    const sidebarClose   = document.getElementById('sidebar-close-btn');
    const attachBtn      = document.getElementById('attach-btn');
    
    // Quick action pills
    const actionPills    = document.querySelectorAll('.action-pill');

    // -- Dev JWT token (uid=2) --
    const JWT_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1aWQiOjIsImdyb3VwcyI6WyJiYXNlLmdyb3VwX3VzZXIiXSwiY29tcGFueV9pZCI6MX0.XQ6GlIsc0ScpmVEmLDwPGwpOK09sHr1gBapnWVzmjz4";

    // -- State --
    let conversations = loadConversations();
    let activeConvId  = null;

    // =========================================================================
    // LocalStorage helpers
    // =========================================================================

    function loadConversations() {
        try {
            return JSON.parse(localStorage.getItem('miro_conversations') || '[]');
        } catch (_e) {
            return [];
        }
    }

    function saveConversations() {
        try {
            localStorage.setItem('miro_conversations', JSON.stringify(conversations));
        } catch (_e) {
            // ignore
        }
    }

    function generateId() {
        return Date.now().toString(36) + Math.random().toString(36).substring(2, 8);
    }

    // =========================================================================
    // Conversation management
    // =========================================================================

    function createConversation() {
        const conv = {
            id: generateId(),
            title: 'Nouvelle conversation',
            messages: [],
            createdAt: Date.now(),
        };
        conversations.unshift(conv);
        saveConversations();
        return conv;
    }

    function getConversation(id) {
        return conversations.find(c => c.id === id) || null;
    }

    function setActiveConversation(id) {
        activeConvId = id;
        renderConversationList();
        renderMessages();
        closeSidebar();
    }

    function updateConversationTitle(conv) {
        const firstUserMsg = conv.messages.find(m => m.role === 'user');
        if (firstUserMsg && conv.title === 'Nouvelle conversation') {
            conv.title = firstUserMsg.text.substring(0, 30);
            if (firstUserMsg.text.length > 30) conv.title += '...';
            saveConversations();
            renderConversationList();
        }
    }

    // =========================================================================
    // UI Rendering
    // =========================================================================

    function renderConversationList() {
        convList.innerHTML = '';
        if (conversations.length === 0) return;

        // Only show last 30 days or simply all
        conversations.forEach(conv => {
            const item = document.createElement('div');
            item.className = 'conv-item' + (conv.id === activeConvId ? ' active' : '');
            item.textContent = conv.title;
            item.addEventListener('click', () => setActiveConversation(conv.id));
            convList.appendChild(item);
        });
    }

    function renderMessages() {
        chatMessages.innerHTML = '';

        const conv = getConversation(activeConvId);
        if (!conv || conv.messages.length === 0) {
            // Empty state -> Show welcome screen
            mainContainer.classList.add('is-empty');
            chatTitle.textContent = 'MIRO AI';
            return;
        }

        // Has messages -> Hide welcome screen, show chat
        mainContainer.classList.remove('is-empty');
        chatTitle.textContent = conv.title;

        conv.messages.forEach(msg => {
            if (msg.role === 'user') {
                appendUserBubble(msg.text);
            } else if (msg.role === 'error') {
                appendErrorBubble(msg.text);
            } else {
                appendAIBubble(msg.text);
            }
        });

        scrollToBottom();
    }

    function appendUserBubble(text) {
        mainContainer.classList.remove('is-empty');
        const div = document.createElement('div');
        div.className = 'message user-message';
        div.innerHTML = `
            <div class="message-body">
                <div class="message-content"><p>${escapeHTML(text)}</p></div>
            </div>`;
        chatMessages.appendChild(div);
    }

    function appendAIBubble(text) {
        const div = document.createElement('div');
        div.className = 'message ai-message';
        div.innerHTML = `
            <div class="avatar"><i class="fa-solid fa-robot"></i></div>
            <div class="message-body">
                <div class="message-content"><p>${formatAnswer(text)}</p></div>
            </div>`;
        chatMessages.appendChild(div);
    }

    function appendErrorBubble(text) {
        const div = document.createElement('div');
        div.className = 'message ai-message';
        div.innerHTML = `
            <div class="avatar" style="background:var(--danger);"><i class="fa-solid fa-triangle-exclamation"></i></div>
            <div class="message-body">
                <div class="message-content error-content"><p>${escapeHTML(text)}</p></div>
            </div>`;
        chatMessages.appendChild(div);
    }

    function showTyping() {
        const id = 'typing-' + Date.now();
        const div = document.createElement('div');
        div.className = 'message ai-message';
        div.id = id;
        div.innerHTML = `
            <div class="avatar"><i class="fa-solid fa-robot"></i></div>
            <div class="message-body">
                <div class="message-content">
                    <div class="typing-indicator">
                        <div class="typing-dot"></div>
                        <div class="typing-dot"></div>
                        <div class="typing-dot"></div>
                    </div>
                </div>
            </div>`;
        chatMessages.appendChild(div);
        scrollToBottom();
        return id;
    }

    function removeTyping(id) {
        const el = document.getElementById(id);
        if (el) el.remove();
    }

    function scrollToBottom() {
        chatMessages.scrollTop = chatMessages.scrollHeight;
    }

    function escapeHTML(str) {
        const div = document.createElement('div');
        div.appendChild(document.createTextNode(str));
        return div.innerHTML;
    }

    function formatAnswer(text) {
        return escapeHTML(text).replace(/\n/g, '<br>');
    }

    // =========================================================================
    // Interactions
    // =========================================================================

    // Input changes
    chatInput.addEventListener('input', () => {
        if (chatInput.value.trim().length > 0) {
            sendBtn.disabled = false;
            sendBtn.style.background = 'var(--text-1)';
            sendBtn.style.color = 'var(--bg-main)';
        } else {
            sendBtn.disabled = true;
            sendBtn.style.background = 'transparent';
            sendBtn.style.color = 'var(--text-3)';
        }
    });

    // Quick action pills
    actionPills.forEach(pill => {
        pill.addEventListener('click', () => {
            chatInput.value = pill.getAttribute('data-prompt');
            sendBtn.disabled = false;
            sendBtn.style.background = 'var(--text-1)';
            sendBtn.style.color = 'var(--bg-main)';
            chatForm.dispatchEvent(new Event('submit'));
        });
    });

    // Sidebar
    sidebarToggle.addEventListener('click', () => {
        if (window.innerWidth <= 900) {
            sidebar.classList.add('open');
            sidebarOverlay.classList.add('visible');
        } else {
            sidebar.classList.toggle('collapsed');
        }
    });

    function closeSidebar() {
        if (window.innerWidth <= 900) {
            sidebar.classList.remove('open');
            sidebarOverlay.classList.remove('visible');
        }
    }
    sidebarClose.addEventListener('click', closeSidebar);
    sidebarOverlay.addEventListener('click', closeSidebar);

    // New conversation
    newChatBtn.addEventListener('click', () => {
        const conv = createConversation();
        setActiveConversation(conv.id);
        chatInput.focus();
    });

    // Attach button
    attachBtn.addEventListener('click', () => {
        alert("Fichier joint (placeholder pour l'intégration Odoo).");
    });

    // Form submission
    chatForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const question = chatInput.value.trim();
        if (!question) return;

        let conv = getConversation(activeConvId);
        if (!conv) {
            conv = createConversation();
            activeConvId = conv.id;
            renderConversationList();
        }

        // Update state & UI
        conv.messages.push({ role: 'user', text: question });
        updateConversationTitle(conv);
        saveConversations();
        appendUserBubble(question);
        scrollToBottom();

        // Disable input during request
        chatInput.value = '';
        chatInput.disabled = true;
        sendBtn.disabled = true;
        sendBtn.style.background = 'transparent';
        sendBtn.style.color = 'var(--text-3)';
        const typingId = showTyping();

        // Check simulated user in Day 3
        const uid = document.getElementById('user-selector')?.value || 2;

        try {
            const resp = await fetch('http://127.0.0.1:8000/api/v1/ask', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': 'Bearer ' + JWT_TOKEN,
                },
                body: JSON.stringify({
                    question: question,
                    session_id: conv.id,
                    user_uid: parseInt(uid),
                    company_id: 1,
                    skills: {},
                }),
            });

            removeTyping(typingId);

            if (!resp.ok) {
                let detail = 'Erreur serveur (' + resp.status + ')';
                try {
                    const errBody = await resp.json();
                    detail = errBody.detail || detail;
                } catch (_e) {}
                conv.messages.push({ role: 'error', text: detail });
                appendErrorBubble(detail);
            } else {
                const data = await resp.json();
                conv.messages.push({ role: 'assistant', text: data.answer });
                appendAIBubble(data.answer);
            }
        } catch (err) {
            removeTyping(typingId);
            const errText = 'Impossible de contacter le serveur MIRO AI.';
            conv.messages.push({ role: 'error', text: errText });
            appendErrorBubble(errText);
        }

        saveConversations();
        scrollToBottom();
        chatInput.disabled = false;
        chatInput.focus();
    });

    // Init
    if (conversations.length === 0) {
        const first = createConversation();
        activeConvId = first.id;
    } else {
        activeConvId = conversations[0].id;
    }

    renderConversationList();
    renderMessages();
    chatInput.focus();
});
