chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    if (request.action === "getReelData") {
        // Grab the Reel ID from the URL (e.g., DWMcs9lCFvn)
        const reelId = window.location.pathname.split('/reel/')[1]?.replace('/', '');

        // Grab the caption
        const caption = document.querySelector('h1')?.innerText || document.title;

        if (reelId) {
            sendResponse({
                reelId: reelId,
                caption: caption,
                pageUrl: window.location.href
            });
        } else {
            sendResponse({ error: "Not on a Reel page." });
        }
    }
    return true;
});