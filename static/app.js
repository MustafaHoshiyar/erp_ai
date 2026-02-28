document.addEventListener('DOMContentLoaded', () => {
    let chatHistory = [];
    const form = document.getElementById('prompt-form');
    const promptInput = document.getElementById('user-prompt');
    const generateBtn = document.getElementById('generate-btn');
    const spinner = document.getElementById('loading-spinner');

    const promptArea = document.getElementById('prompt-area');
    const welcomeHeader = document.getElementById('welcome-header');
    const resultsArea = document.getElementById('results-area');

    const userMessageTemplate = document.getElementById('user-message-template');
    const aiResponseTemplate = document.getElementById('ai-response-template');

    // Auto-resize textarea
    promptInput.addEventListener('input', function () {
        this.style.height = 'auto';
        this.style.height = (this.scrollHeight) + 'px';

        // Enable/disable send button based on content
        generateBtn.disabled = this.value.trim() === '';
    });

    // Enter to submit (Shift+Enter for newline)
    promptInput.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            if (!generateBtn.disabled) {
                form.dispatchEvent(new Event('submit', { cancelable: true }));
            }
        }
    });

    form.addEventListener('submit', async (e) => {
        e.preventDefault();

        const promptText = promptInput.value.trim();
        if (!promptText) return;

        // 1. UI Transition: Move prompt bar to bottom
        if (promptArea.classList.contains('prompt-centered')) {
            promptArea.classList.remove('prompt-centered');
            welcomeHeader.classList.add('hidden');
        }

        // 2. Add User Message to History
        addUserMessage(promptText);

        // Reset input
        promptInput.value = '';
        promptInput.style.height = 'auto';
        generateBtn.disabled = true;

        // 3. Prepare AI Response Block
        const aiMessageNode = createAiMessagePlaceholder();
        resultsArea.appendChild(aiMessageNode);
        scrollToBottom();

        setLoadingState(true);

        try {
            const response = await fetch('/generate-report', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ prompt: promptText, history: chatHistory })
            });

            if (!response.ok) {
                let errorDetail = response.statusText;
                try {
                    const errorJson = await response.json();
                    errorDetail = errorJson.detail || errorDetail;
                } catch (err) { }
                throw new Error(`Server Error: ${errorDetail}`);
            }

            const result = await response.json();

            // Store interaction in history for future prompts
            chatHistory.push({ role: 'user', content: promptText });
            if (result.sql) {
                chatHistory.push({ role: 'assistant', content: "```sql\n" + result.sql + "\n```" });
            } else if (result.message) {
                chatHistory.push({ role: 'assistant', content: result.message });
            }

            // 4. Fill AI Response Block with Data
            populateAiMessage(aiMessageNode, result);

        } catch (err) {
            console.error(err);
            showAiError(aiMessageNode, err.message || 'An unexpected error occurred.');
        } finally {
            setLoadingState(false);
            scrollToBottom();
            promptInput.focus();
        }
    });

    function addUserMessage(text) {
        const clone = userMessageTemplate.content.cloneNode(true);
        const contentDiv = clone.querySelector('.message-content');
        contentDiv.textContent = text;
        resultsArea.appendChild(clone);
    }

    function createAiMessagePlaceholder() {
        const clone = aiResponseTemplate.content.cloneNode(true);
        const node = clone.querySelector('.message');

        // Add a temporary loading indicator inside the message content
        const contentDiv = node.querySelector('.message-content');
        const loadingText = document.createElement('div');
        loadingText.className = 'placeholder-text text-muted';
        loadingText.textContent = 'Thinking...';
        loadingText.style.fontStyle = 'italic';
        contentDiv.prepend(loadingText);

        return node;
    }

    function populateAiMessage(messageNode, result) {
        // Remove 'Thinking...' placeholder
        const placeholder = messageNode.querySelector('.placeholder-text');
        if (placeholder) placeholder.remove();

        const sqlSection = messageNode.querySelector('.sql-section');
        const sqlOutput = messageNode.querySelector('.sql-output');
        const copySqlBtn = messageNode.querySelector('.copy-btn');
        const dataSection = messageNode.querySelector('.data-section');
        const thead = messageNode.querySelector('.data-thead');
        const tbody = messageNode.querySelector('.data-tbody');
        const rowCountBadge = messageNode.querySelector('.row-count');
        const dashboardBtn = messageNode.querySelector('.dashboard-btn');
        const chartContainer = messageNode.querySelector('.chart-container');
        const canvas = messageNode.querySelector('.dashboard-chart');
        let currentChart = null;

        // Setup SQL Copy
        copySqlBtn.addEventListener('click', () => {
            const sql = sqlOutput.textContent;
            if (sql) {
                navigator.clipboard.writeText(sql).then(() => {
                    const originalSvg = copySqlBtn.innerHTML;
                    copySqlBtn.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--success-color)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>`;
                    setTimeout(() => copySqlBtn.innerHTML = originalSvg, 2000);
                });
            }
        });

        const exportData = result.data?.message || result.data;

        // Setup CSV Export
        const exportBtn = messageNode.querySelector('.export-btn');
        if (exportBtn) {
            exportBtn.addEventListener('click', () => {
                if (!Array.isArray(exportData) || exportData.length === 0) return;

                const headers = Object.keys(exportData[0]);
                const csvRows = [];

                // Add Headers
                csvRows.push(headers.join(','));

                // Add Data
                for (const row of exportData) {
                    const values = headers.map(header => {
                        let val = row[header] !== null && row[header] !== undefined ? row[header] : '';
                        // Escape quotes and commas
                        val = String(val).replace(/"/g, '""');
                        if (val.includes(',') || val.includes('"') || val.includes('\n')) {
                            val = `"${val}"`;
                        }
                        return val;
                    });
                    csvRows.push(values.join(','));
                }

                // Trigger Download
                const csvData = csvRows.join('\n');
                const blob = new Blob([csvData], { type: 'text/csv' });
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.setAttribute('hidden', '');
                a.setAttribute('href', url);
                a.setAttribute('download', 'erp_report.csv');
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
            });
        }

        // Setup Dashboard Generation
        if (dashboardBtn) {
            dashboardBtn.addEventListener('click', async () => {
                if (!Array.isArray(exportData) || exportData.length === 0) return;

                const originalBtnContent = dashboardBtn.innerHTML;
                dashboardBtn.innerHTML = '<div class="spinner" style="width:16px; height:16px; border-width:2px; border-color: currentColor; border-right-color: transparent;"></div>';
                dashboardBtn.disabled = true;

                try {
                    const columns = Object.keys(exportData[0]);
                    const dataSample = exportData.slice(0, 5); // Send a sample to determine types

                    const response = await fetch('/api/generate_chart_config', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json'
                        },
                        body: JSON.stringify({ columns, data_sample: dataSample })
                    });

                    if (!response.ok) throw new Error("Failed to generate chart config.");

                    const config = await response.json();

                    if (config.error) throw new Error(config.error);

                    // Inject actual data into the config from AI if it didn't do it properly
                    // The AI typically returns structure but we need to map our real data correctly
                    // For safety, we map our full data according to the labels and datasets axes the AI chose.

                    if (config.data && config.data.datasets && config.data.labels) {
                        try {
                            // Assume the first dataset label is targeting a specific column, and the labels refer to a category column
                            // Let's use the first data row objects keys since the AI might have just made mock data.

                            // Let's rely on the AI actually making a function for us or we just pass the data? 
                            // The AI was given sample data, it might have populated `data` array exactly, but we want all rows.

                            // We must reconstruct the dataset using the keys the AI intended.
                            // Looking at a standard Chart.js bar chart config, data usually looks like data.labels = [...], data.datasets[0].data = [...]

                            // Since we didn't tell it the exact JS mapping, we will send the full data to it so it populates it fully?
                            // Wait, the context window might be small. 

                            // Better approach: Let's assume the AI config tells us which column is the X axis (labels) and Y axis (datasets).
                            // But Chart.js config does not have a standard "ColumnName" field.
                            // So let's just make the AI output the actual fully populated data array in the config by sending it the full data.
                            // Re-fetching with full data mapped is safer if data size is small. Let's send up to 50 rows.
                        } catch (e) { }
                    }

                    // Actually, let's re-fetch the config with more data. Or just use what it gave us if we sent full data. Let's update the API call to send more data.
                    const fullDataPayload = exportData.slice(0, 100);
                    const responseFull = await fetch('/api/generate_chart_config', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ columns, data_sample: fullDataPayload })
                    });
                    const fullConfig = await responseFull.json();

                    if (currentChart) {
                        currentChart.destroy();
                    }

                    chartContainer.style.display = 'block';
                    currentChart = new Chart(canvas, fullConfig);

                } catch (e) {
                    console.error("Dashboard error:", e);
                    alert("Could not generate dashboard: " + e.message);
                } finally {
                    dashboardBtn.innerHTML = originalBtnContent;
                    dashboardBtn.disabled = false;
                }
            });
        }

        // Try rendering SQL (currently removed from backend, but keeping logic if it returns)
        if (result.sql) {
            sqlOutput.textContent = result.sql;
            sqlSection.classList.remove('hidden');
        }

        // Render Data Table
        const data = result.data?.message || result.data;

        if (Array.isArray(data) && data.length > 0) {
            rowCountBadge.textContent = `${data.length} row${data.length > 1 ? 's' : ''}`;

            const headers = Object.keys(data[0]);

            // Header
            const trHead = document.createElement('tr');
            headers.forEach(header => {
                const th = document.createElement('th');
                th.textContent = header.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
                trHead.appendChild(th);
            });
            thead.appendChild(trHead);

            // Body
            data.forEach(row => {
                const tr = document.createElement('tr');
                headers.forEach(header => {
                    const td = document.createElement('td');
                    td.textContent = row[header] !== null && row[header] !== undefined ? row[header] : '—';
                    tr.appendChild(td);
                });
                tbody.appendChild(tr);
            });

            dataSection.classList.remove('hidden');
        } else if (data) {
            // No rows but successful query
            rowCountBadge.textContent = '0 rows';
            const tr = document.createElement('tr');
            const td = document.createElement('td');
            td.textContent = "No data returned for this query.";
            td.style.textAlign = 'center';
            td.style.padding = '1rem';
            tr.appendChild(td);
            tbody.appendChild(tr);
            dataSection.classList.remove('hidden');
        } else {
            // Handle raw text response from AI (if any fallback exists)
            const textResponse = document.createElement('p');
            textResponse.textContent = result.message || "No data returned.";
            messageNode.querySelector('.message-content').prepend(textResponse);
        }
    }

    function showAiError(messageNode, errorMessage) {
        const placeholder = messageNode.querySelector('.placeholder-text');
        if (placeholder) placeholder.remove();

        const toast = messageNode.querySelector('.error-toast');
        toast.textContent = errorMessage;
        toast.classList.remove('hidden');
    }

    function setLoadingState(isLoading) {
        const svg = generateBtn.querySelector('svg');
        if (isLoading) {
            generateBtn.disabled = true;
            if (svg) svg.classList.add('hidden');
            spinner.classList.remove('hidden');
        } else {
            generateBtn.disabled = promptInput.value.trim() === '';
            if (svg) svg.classList.remove('hidden');
            spinner.classList.add('hidden');
        }
    }

    function scrollToBottom() {
        resultsArea.scrollTop = resultsArea.scrollHeight;
    }

    // Initialize button state
    generateBtn.disabled = true;
});
