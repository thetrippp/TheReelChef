document.addEventListener('DOMContentLoaded', function () {
    const saveBtn = document.getElementById('save');
    const status = document.getElementById('status');

    saveBtn.addEventListener('click', async () => {
        status.innerText = "Searching for Reel...";
        const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });

        chrome.tabs.sendMessage(tab.id, { action: "getReelData" }, (response) => {
            if (chrome.runtime.lastError || !response) {
                status.innerText = "Error: Refresh the page.";
                return;
            }

            if (response.error) {
                status.innerText = "Wait... " + response.error;
                return;
            }

            status.innerText = "Sending to Chef (1-5MB)...";

            fetch('http://localhost:5001/api/save', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(response)
            })
                .then(() => status.innerText = "Success! Go to App.")
                .catch(() => status.innerText = "Is the Python app running?");
        });
    });
});