const API_URL = "/api/chat";
const SESSION_KEY = "jarana_session_id";

let messagesEl;
let inputEl;
let sendBtn;

function getSessionId() {
    return sessionStorage.getItem(SESSION_KEY);
}

function setSessionId(id) {
    sessionStorage.setItem(SESSION_KEY, id);
}

function formatTime() {
    const now = new Date();
    const hh = String(now.getHours()).padStart(2, "0");
    const mm = String(now.getMinutes()).padStart(2, "0");
    return `${hh}:${mm}`;
}

function appendMessage(text, sender) {
    const wrapper = document.createElement("div");
    wrapper.className = `message ${sender}`;

    const bubble = document.createElement("div");
    bubble.className = "message-bubble";
    bubble.textContent = text;
    wrapper.appendChild(bubble);

    const meta = document.createElement("div");
    meta.className = "message-meta";
    meta.textContent = formatTime();
    wrapper.appendChild(meta);

    messagesEl.appendChild(wrapper);
    scrollToBottom();
}

function showTyping() {
    const indicator = document.createElement("div");
    indicator.className = "typing-indicator";
    indicator.innerHTML = "<span></span><span></span><span></span>";
    messagesEl.appendChild(indicator);
    scrollToBottom();
}

function hideTyping() {
    const indicators = messagesEl.getElementsByClassName("typing-indicator");
    while (indicators.length > 0) {
        indicators[0].remove();
    }
}

function scrollToBottom() {
    messagesEl.scrollTop = messagesEl.scrollHeight;
}

async function sendMessage() {
    const message = inputEl.value.trim();
    if (!message) return;

    const originalInput = inputEl.value;
    inputEl.value = "";
    inputEl.style.height = "auto";
    sendBtn.disabled = true;

    appendMessage(message, "user");
    showTyping();

    try {
        const response = await fetch(API_URL, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                session_id: getSessionId(),
                message: message,
            }),
        });

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        const data = await response.json();
        setSessionId(data.session_id);
        hideTyping();
        appendMessage(data.message, "bot");
    } catch (err) {
        console.error(err);
        hideTyping();
        appendMessage("전송 실패. 다시 시도해주세요.", "bot");
        inputEl.value = originalInput;
    } finally {
        sendBtn.disabled = false;
        inputEl.focus();
    }
}

window.addEventListener("DOMContentLoaded", () => {
    messagesEl = document.getElementById("messages");
    inputEl = document.getElementById("message-input");
    sendBtn = document.getElementById("send-button");

    inputEl.addEventListener("input", () => {
        inputEl.style.height = "auto";
        inputEl.style.height = Math.min(inputEl.scrollHeight, 120) + "px";
    });

    inputEl.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && !e.shiftKey && !e.isComposing && e.keyCode !== 229) {
            e.preventDefault();
            sendMessage();
        }
    });

    sendBtn.addEventListener("click", sendMessage);

    appendMessage(
        "안녕하세요! Jarana 고객센터입니다. 무엇을 도와드릴까요?",
        "bot"
    );
    inputEl.focus();
});
