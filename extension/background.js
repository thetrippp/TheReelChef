chrome.runtime.onInstalled.addListener(() => {
    console.log('Reel Chef extension installed');
});

// Handle messages from content script
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    if (request.action === 'getUserId') {
        chrome.storage.sync.get(['userId'], (result) => {
            sendResponse({ userId: result.userId });
        });
        return true;
    }

    if (request.action === 'setUserId') {
        chrome.storage.sync.set({ userId: request.userId });
        sendResponse({ success: true });
        return true;
    }
});

// Optional: Context menu option to send reel
chrome.contextMenus.create({
    id: 'reelChef-send',
    title: 'Add to Reel Chef',
    contexts: ['page'],
    documentUrlPatterns: ['https://www.instagram.com/*']
});

chrome.contextMenus.onClicked.addListener((info, tab) => {
    if (info.menuItemId === 'reelChef-send') {
        // Send message to popup or handle directly
        chrome.storage.sync.get(['userId'], (result) => {
            if (result.userId) {
                fetch('http://localhost:5001/api/process-reel', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        reel_url: tab.url,
                        user_id: result.userId
                    })
                });
            }
        });
    }
});