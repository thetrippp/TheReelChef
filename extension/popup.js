class ReelChefExtension {
    constructor() {
        this.reelUrl = null;
        this.reelTitle = null;
        this.backendUrl = 'http://localhost:5001';
        this.init();
    }

    init() {
        // Get current tab URL
        chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
            const currentTab = tabs[0];
            this.reelUrl = currentTab.url;
            this.reelTitle = currentTab.title;
            this.displayReelInfo();
        });

        // Button handlers
        document.getElementById('sendBtn').addEventListener('click', () => this.sendToLibrary());
        document.getElementById('copyBtn').addEventListener('click', () => this.copyLink());
        document.getElementById('openLibraryBtn').addEventListener('click', () => this.openLibrary());
    }

    displayReelInfo() {
        // Extract readable title from URL
        const titleElement = document.getElementById('reelTitle');
        const urlElement = document.getElementById('reelUrl');

        titleElement.textContent = this.reelTitle || 'Instagram Reel';
        urlElement.textContent = this.shortenUrl(this.reelUrl);

        // Check if this is an Instagram URL
        if (!this.reelUrl.includes('instagram.com')) {
            this.showStatus('not-instagram', 'error');
            document.getElementById('sendBtn').disabled = true;
        }
    }

    shortenUrl(url) {
        if (!url) return '';
        if (url.length > 50) {
            return url.substring(0, 47) + '...';
        }
        return url;
    }

    async sendToLibrary() {
        if (!this.reelUrl) {
            this.showStatus('invalid-url', 'error');
            return;
        }

        // Get user ID from storage (set during auth)
        chrome.storage.sync.get(['userId'], async (result) => {
            const userId = result.userId;

            if (!userId) {
                this.showStatus('not-logged-in', 'error');
                return;
            }

            // Show loading state
            const sendBtn = document.getElementById('sendBtn');
            const originalText = sendBtn.textContent;
            sendBtn.disabled = true;
            sendBtn.innerHTML = '<span class="loading-spinner"></span>Sending...';

            try {
                const response = await fetch(`${this.backendUrl}/api/process-reel`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        reel_url: this.reelUrl,
                        user_id: userId
                    })
                });

                if (response.ok || response.status === 202) {
                    this.showSentView();
                } else {
                    const error = await response.json();
                    this.showStatus(error.error || 'Failed to process', 'error');
                    sendBtn.disabled = false;
                    sendBtn.textContent = originalText;
                }
            } catch (error) {
                this.showStatus(`Connection error: ${error.message}`, 'error');
                sendBtn.disabled = false;
                sendBtn.textContent = originalText;
            }
        });
    }

    copyLink() {
        navigator.clipboard.writeText(this.reelUrl).then(() => {
            const copyBtn = document.getElementById('copyBtn');
            const originalText = copyBtn.textContent;
            copyBtn.textContent = '✅ Copied!';
            setTimeout(() => {
                copyBtn.textContent = originalText;
            }, 2000);
        });
    }

    openLibrary() {
        // Open Streamlit app (adjust URL as needed)
        chrome.tabs.create({ url: 'http://localhost:8501' });
    }

    showSentView() {
        document.getElementById('content').classList.add('hidden');
        document.getElementById('afterSend').classList.remove('hidden');
    }

    showStatus(message, type) {
        const statusEl = document.getElementById('status');

        const messages = {
            'not-instagram': '⚠️ This page is not an Instagram reel',
            'invalid-url': '⚠️ Unable to get page URL',
            'not-logged-in': '🔐 Please log in to Reel Chef first',
        };

        statusEl.textContent = messages[message] || message;
        statusEl.className = `status ${type} ${!statusEl.textContent ? 'hidden' : ''}`;
    }
}

// Initialize on popup open
document.addEventListener('DOMContentLoaded', () => {
    new ReelChefExtension();
});