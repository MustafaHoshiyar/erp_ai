document.addEventListener('DOMContentLoaded', () => {
    // Auth Check
    if (!localStorage.getItem('auth_token')) {
        window.location.href = 'login.html';
        return; // Stop rendering and redirect
    }

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

    // Sidebar Elements
    const sidebar = document.getElementById('sidebar');
    const sidebarOverlay = document.getElementById('sidebar-overlay');
    const openSidebarBtn = document.getElementById('open-sidebar-btn');
    const closeSidebarBtn = document.getElementById('close-sidebar-btn');
    const savedReportsList = document.getElementById('saved-reports-list');

    // Mock Client ID for Phase 2 demo
    const CLIENT_ID = "DEMO_CLIENT_123";

    // Token Usage Elements
    const totalTokensEl = document.getElementById('total-tokens');
    const requestCountEl = document.getElementById('request-count');
    const avgTokensEl = document.getElementById('avg-tokens');
    const resetTokensBtn = document.getElementById('reset-tokens-btn');

    // Modal Elements
    const modalBackdrop = document.getElementById('modal-backdrop');
    const customPromptModal = document.getElementById('custom-prompt-modal');
    const promptModalTitle = document.getElementById('prompt-modal-title');
    const promptModalMessage = document.getElementById('prompt-modal-message');
    const promptModalInput = document.getElementById('prompt-modal-input');
    const promptModalCancel = document.getElementById('prompt-modal-cancel');
    const promptModalSubmit = document.getElementById('prompt-modal-submit');

    const customConfirmModal = document.getElementById('custom-confirm-modal');
    const confirmModalTitle = document.getElementById('confirm-modal-title');
    const confirmModalMessage = document.getElementById('confirm-modal-message');
    const confirmModalCancel = document.getElementById('confirm-modal-cancel');
    const confirmModalSubmit = document.getElementById('confirm-modal-submit');

    // Custom Modal Logic
    function showCustomPrompt(message, title = "Enter Value") {
        return new Promise((resolve) => {
            promptModalTitle.textContent = title;
            promptModalMessage.textContent = message;
            promptModalInput.value = '';

            modalBackdrop.classList.remove('hidden');
            customPromptModal.classList.remove('hidden');
            promptModalInput.focus();

            const cleanup = () => {
                modalBackdrop.classList.add('hidden');
                customPromptModal.classList.add('hidden');
                promptModalCancel.removeEventListener('click', onCancel);
                promptModalSubmit.removeEventListener('click', onSubmit);
                promptModalInput.removeEventListener('keydown', onKeydown);
            };

            const onCancel = () => { cleanup(); resolve(null); };
            const onSubmit = () => { cleanup(); resolve(promptModalInput.value); };
            const onKeydown = (e) => {
                if (e.key === 'Enter') onSubmit();
                if (e.key === 'Escape') onCancel();
            };

            promptModalCancel.addEventListener('click', onCancel);
            promptModalSubmit.addEventListener('click', onSubmit);
            promptModalInput.addEventListener('keydown', onKeydown);
        });
    }

    function showCustomConfirm(message, title = "Confirm Action") {
        return new Promise((resolve) => {
            confirmModalTitle.textContent = title;
            confirmModalMessage.textContent = message;

            modalBackdrop.classList.remove('hidden');
            customConfirmModal.classList.remove('hidden');

            const cleanup = () => {
                modalBackdrop.classList.add('hidden');
                customConfirmModal.classList.add('hidden');
                confirmModalCancel.removeEventListener('click', onCancel);
                confirmModalSubmit.removeEventListener('click', onSubmit);
            };

            const onCancel = () => { cleanup(); resolve(false); };
            const onSubmit = () => { cleanup(); resolve(true); };

            confirmModalCancel.addEventListener('click', onCancel);
            confirmModalSubmit.addEventListener('click', onSubmit);
        });
    }

    // Sidebar Logic
    function toggleSidebar() {
        if (window.innerWidth > 768) {
            sidebar.classList.toggle('collapsed');
        } else {
            sidebar.classList.toggle('open');
            sidebarOverlay.classList.toggle('active');
            // Load reports if opening on mobile
            if (sidebar.classList.contains('open') && savedReportsList.children.length === 0) {
                loadSavedReports();
            }
        }
    }

    openSidebarBtn.addEventListener('click', toggleSidebar);
    closeSidebarBtn.addEventListener('click', toggleSidebar);
    sidebarOverlay.addEventListener('click', toggleSidebar);

    // New Chat button - reset to initial state
    const newChatBtn = document.getElementById('new-chat-btn');
    newChatBtn.addEventListener('click', () => {
        // Clear chat history
        chatHistory = [];

        // Clear all messages from results area
        resultsArea.innerHTML = '';

        // Re-center the prompt bar and show welcome header
        promptArea.classList.add('prompt-centered');
        welcomeHeader.classList.remove('hidden');

        // Reset input
        promptInput.value = '';
        promptInput.style.height = 'auto';
        generateBtn.disabled = true;

        // Close sidebar on mobile
        if (window.innerWidth <= 768) {
            sidebar.classList.remove('open');
            sidebarOverlay.classList.remove('active');
        }

        promptInput.focus();
    });

    // Initial load for desktop where sidebar is visible
    loadSavedReports();
    fetchTokenStats();  // Load token stats on startup

    async function loadSavedReports() {
        savedReportsList.innerHTML = '<div class="text-muted" style="padding: 1rem;">Loading...</div>';
        try {
            const res = await fetch(`/api/reports/${CLIENT_ID}`);
            const reports = await res.json();

            savedReportsList.innerHTML = '';
            if (reports.length === 0) {
                savedReportsList.innerHTML = '<div class="text-muted" style="padding: 1rem;">No saved reports yet.</div>';
                return;
            }

            reports.forEach(report => {
                const item = document.createElement('div');
                item.className = 'saved-report-item';
                item.style.position = 'relative'; // For absolute positioning of delete bn
                item.innerHTML = `
                    <button class="delete-report-btn" title="Delete Report" data-id="${report.id}">&times;</button>
                    <h4>${report.name}</h4>
                    <p>${report.original_prompt}</p>
                    <div class="date">${new Date(report.created_at).toLocaleDateString()}</div>
                `;

                item.addEventListener('click', (e) => {
                    if (e.target.classList.contains('delete-report-btn')) return;
                    if (window.innerWidth <= 768) {
                        toggleSidebar();
                    }
                    executeSavedReport(report);
                });

                // Add delete button logic
                const deleteBtn = item.querySelector('.delete-report-btn');
                deleteBtn.addEventListener('click', async (e) => {
                    e.stopPropagation();
                    const confirmed = await showCustomConfirm(`Are you sure you want to delete "${report.name}"?`, "Delete Report");
                    if (confirmed) {
                        try {
                            const delRes = await fetch(`/api/reports/${report.id}`, { method: 'DELETE' });
                            if (delRes.ok) {
                                item.remove();
                                if (savedReportsList.children.length === 0) {
                                    savedReportsList.innerHTML = '<div class="text-muted" style="padding: 1rem;">No saved reports yet.</div>';
                                }
                            } else {
                                alert("Failed to delete report.");
                            }
                        } catch (err) {
                            alert("Error: " + err.message);
                        }
                    }
                });

                savedReportsList.appendChild(item);
            });
        } catch (err) {
            console.error(err);
            savedReportsList.innerHTML = '<div class="text-error" style="padding: 1rem;">Failed to load saved reports.</div>';
        }
    }

    async function executeSavedReport(report) {
        // UI Transition: Move prompt bar to bottom
        if (promptArea.classList.contains('prompt-centered')) {
            promptArea.classList.remove('prompt-centered');
            welcomeHeader.classList.add('hidden');
        }

        addUserMessage(`[Loaded Saved Report] ${report.name}: ${report.original_prompt}`);

        const aiMessageNode = createAiMessagePlaceholder();
        resultsArea.appendChild(aiMessageNode);
        scrollToBottom();

        try {
            const response = await fetch(`/api/reports/execute/${report.id}`, {
                method: 'POST'
            });

            if (!response.ok) throw new Error("Failed to execute saved report.");

            const result = await response.json();

            // Format to match what populateAiMessage expects
            populateAiMessage(aiMessageNode, result, report.chart_config);

        } catch (err) {
            showAiError(aiMessageNode, err.message);
        }
    }

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

            // 5. Update token usage stats
            if (result.tokens_used) {
                fetchTokenStats();
            }

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

    function populateAiMessage(messageNode, result, preLoadedChartConfig = null) {
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
        const saveReportBtn = messageNode.querySelector('.save-report-btn');
        let currentChart = null;
        let lastChartConfig = null; // Store config for saving

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

        if (saveReportBtn) {
            saveReportBtn.style.display = 'none'; // Initially hide when data renders
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
                    const fullDataPayload = exportData;
                    const responseFull = await fetch('/api/generate_chart_config', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ columns, data_sample: fullDataPayload })
                    });
                    const fullConfig = await responseFull.json();

                    if (currentChart) {
                        currentChart.destroy();
                    }

                    lastChartConfig = fullConfig; // Save for the 'Save Report' button
                    chartContainer.style.display = 'block';
                    currentChart = new Chart(canvas, fullConfig);

                    if (saveReportBtn) {
                        saveReportBtn.style.display = 'flex'; // Show save button
                    }

                } catch (e) {
                    console.error("Dashboard error:", e);
                    alert("Could not generate dashboard: " + e.message);
                } finally {
                    dashboardBtn.innerHTML = originalBtnContent;
                    dashboardBtn.disabled = false;
                }
            });
        }

        // Setup Save Report
        if (saveReportBtn && result.sql) {
            saveReportBtn.addEventListener('click', async () => {
                const reportName = await showCustomPrompt("Enter a name for this saved report:", "Save Report");
                if (!reportName) return;

                const originalBtnContent = saveReportBtn.innerHTML;
                saveReportBtn.innerHTML = '<div class="spinner" style="width:16px; height:16px; border-width:2px; border-color: currentColor; border-right-color: transparent;"></div>';
                saveReportBtn.disabled = true;

                // Find the user prompt that generated this
                // In a real app we'd track the prompt ID accurately. Here we just grab the last user prompt from chatHistory
                let originalPrompt = "Unknown prompt";
                for (let i = chatHistory.length - 1; i >= 0; i--) {
                    if (chatHistory[i].role === 'user') {
                        originalPrompt = chatHistory[i].content;
                        break;
                    }
                }

                try {
                    const response = await fetch('/api/reports/save', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            client_id: CLIENT_ID,
                            name: reportName,
                            original_prompt: originalPrompt,
                            sql_query: result.sql,
                            chart_config: lastChartConfig // Include the chart config if it was generated
                        })
                    });

                    if (!response.ok) throw new Error("Failed to save report.");

                    saveReportBtn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--success-color)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg>';
                    setTimeout(() => saveReportBtn.innerHTML = originalBtnContent, 2000);

                } catch (e) {
                    alert(e.message);
                    saveReportBtn.innerHTML = originalBtnContent;
                } finally {
                    saveReportBtn.disabled = false;
                }
            });
        } else if (saveReportBtn) {
            saveReportBtn.style.display = 'none'; // Only show save if it generated SQL and a chart
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
            // Add Sr column header
            const thSr = document.createElement('th');
            thSr.textContent = 'Sr';
            trHead.appendChild(thSr);
            headers.forEach(header => {
                const th = document.createElement('th');
                th.textContent = header.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
                trHead.appendChild(th);
            });
            thead.appendChild(trHead);

            // Body
            data.forEach((row, index) => {
                const tr = document.createElement('tr');
                // Add Sr column value
                const tdSr = document.createElement('td');
                tdSr.textContent = index + 1;
                tr.appendChild(tdSr);
                headers.forEach(header => {
                    const td = document.createElement('td');
                    td.textContent = row[header] !== null && row[header] !== undefined ? row[header] : '—';
                    tr.appendChild(td);
                });
                tbody.appendChild(tr);
            });

            dataSection.classList.remove('hidden');

            // Wire up collapsible toggle
            const collapseBtn = messageNode.querySelector('.collapse-toggle-btn');
            const collapsibleBody = messageNode.querySelector('.collapsible-body');
            const collapsibleHeader = messageNode.querySelector('.collapsible-header');

            if (collapseBtn && collapsibleBody) {
                const toggleCollapse = () => {
                    collapseBtn.classList.toggle('collapsed');
                    collapsibleBody.classList.toggle('collapsed');
                };
                collapseBtn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    toggleCollapse();
                });
                // Also allow clicking the title area
                const titleGroup = messageNode.querySelector('.section-title-group');
                if (titleGroup) {
                    titleGroup.addEventListener('click', (e) => {
                        if (e.target !== collapseBtn && !collapseBtn.contains(e.target)) {
                            toggleCollapse();
                        }
                    });
                }
            }
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

        // Render Pre-loaded Chart if it exists
        if (preLoadedChartConfig && chartContainer && canvas) {
            chartContainer.style.display = 'block';
            lastChartConfig = preLoadedChartConfig;
            currentChart = new Chart(canvas, preLoadedChartConfig);
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

    // --- Token Usage Stats ---
    async function fetchTokenStats() {
        try {
            const res = await fetch('/api/token-stats');
            const stats = await res.json();
            totalTokensEl.textContent = formatNumber(stats.total_tokens);
            requestCountEl.textContent = formatNumber(stats.request_count);
            const avg = stats.request_count > 0
                ? Math.round(stats.total_tokens / stats.request_count)
                : 0;
            avgTokensEl.textContent = formatNumber(avg);
        } catch (err) {
            console.error('Failed to fetch token stats:', err);
        }
    }

    function formatNumber(num) {
        return num.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ',');
    }

    resetTokensBtn.addEventListener('click', async () => {
        const confirmed = await showCustomConfirm(
            'This will reset your session token counter to zero. Continue?',
            'Reset Token Stats'
        );
        if (!confirmed) return;

        try {
            await fetch('/api/token-stats/reset', { method: 'POST' });
            fetchTokenStats();
        } catch (err) {
            console.error('Failed to reset token stats:', err);
        }
    });

    const logoutBtn = document.getElementById('logout-btn');
    if (logoutBtn) {
        logoutBtn.addEventListener('click', () => {
            localStorage.removeItem('auth_token');
            window.location.href = 'login.html';
        });
    }
});
