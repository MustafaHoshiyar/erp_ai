document.addEventListener('DOMContentLoaded', () => {
    // Auth Check
    if (!localStorage.getItem('auth_token')) {
        window.location.href = 'login.html';
        return; // Stop rendering and redirect
    }

    let APP_ENV = 'development';
    let chatHistory = [];
    let currentConversationId = null;
    let CURRENCY_SYMBOL = '$'; // Fallback
    let CURRENCY_DECIMALS = 2;

    fetch('/api/config').then(res => res.json()).then(data => {
        APP_ENV = data.environment;
        const insightsLink = document.getElementById('menu-insights-link');
        if (insightsLink && data.insights_url) {
            insightsLink.href = data.insights_url;
        }
    }).catch(err => console.error("Failed to load config", err));

    fetch('/api/currency-info').then(res => res.json()).then(data => {
        CURRENCY_SYMBOL = data.symbol || '$';
        CURRENCY_DECIMALS = Number.isInteger(data.decimal_places) ? data.decimal_places : 2;
    }).catch(err => console.error("Failed to load currency info", err));
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
    const sidebarV2Container = document.getElementById('history-list');

    // Dynamic Client ID based on logged in user
    const CLIENT_ID = localStorage.getItem('user_email') || "DEMO_CLIENT_123";

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

    function formatCurrencyValue(value) {
        return `${value.toLocaleString(undefined, {
            minimumFractionDigits: CURRENCY_DECIMALS,
            maximumFractionDigits: CURRENCY_DECIMALS
        })} ${CURRENCY_SYMBOL}`;
    }

    function isCurrencyColumn(header) {
        const lowerHeader = String(header || '').toLowerCase();

        const nonCurrencyHints = [
            'qty',
            'quantity',
            'count',
            'units',
            'pieces',
            'days',
            'hours',
            'minutes',
            'months',
            'years',
            'percent',
            'percentage',
            'ratio',
            'index',
            'level'
        ];

        if (nonCurrencyHints.some(hint => lowerHeader.includes(hint))) {
            return false;
        }

        const currencyHints = [
            'amount',
            'total',
            'price',
            'rate',
            'cost',
            'sum',
            'revenue',
            'expense',
            'balance',
            'payment',
            'paid',
            'value',
            'valuation',
            'debit',
            'credit',
            'subtotal',
            'grand_total',
            'net_total',
            'outstanding'
        ];

        return currencyHints.some(hint => lowerHeader.includes(hint));
    }

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
            // Load history if opening on mobile
            if (sidebar.classList.contains('open') && sidebarV2Container.children.length === 0) {
                loadConversationHistory();
            }
        }
    }

    openSidebarBtn.addEventListener('click', toggleSidebar);
    closeSidebarBtn.addEventListener('click', toggleSidebar);
    sidebarOverlay.addEventListener('click', toggleSidebar);

    // New Chat button - reset to initial state
    const newChatBtn = document.getElementById('new-chat-btn');
    newChatBtn.addEventListener('click', () => {
        chatHistory = [];
        currentConversationId = null;

        // Highlight logic
        document.querySelectorAll('.history-item').forEach(i => i.classList.remove('active'));

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

    // Token toggle logic
    const tokenToggleHeader = document.getElementById('token-toggle-header');
    const tokenUsagePanel = document.getElementById('token-usage-panel');
    const tokenUsageContent = document.getElementById('token-usage-content');
    if (tokenToggleHeader) {
        tokenToggleHeader.addEventListener('click', () => {
            tokenUsagePanel.classList.toggle('collapsed');
            tokenUsageContent.classList.toggle('collapsed');
        });
    }

    // Initial load for desktop where sidebar is visible
    loadConversationHistory();
    fetchTokenStats();  // Load token stats on startup

    async function loadConversationHistory() {
        sidebarV2Container.innerHTML = '<div class="text-muted" style="padding: 1rem;">Loading...</div>';
        try {
            const res = await fetch(`/api/conversations/${CLIENT_ID}`);
            const threads = await res.json();

            sidebarV2Container.innerHTML = '';
            if (threads.length === 0) {
                sidebarV2Container.innerHTML = '<div class="text-muted" style="padding: 1rem; font-size: 0.85rem;">No history yet.</div>';
                return;
            }

            threads.forEach(thread => {
                const item = document.createElement('div');
                item.className = 'history-item';
                item.dataset.id = thread.id;
                if (currentConversationId === thread.id) {
                    item.classList.add('active');
                }

                item.innerHTML = `
                    <div class="history-item-title">${thread.title}</div>
                    <button class="delete-history-btn" title="Delete thread">
                        <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"></path><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"></path><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"></path><line x1="10" y1="11" x2="10" y2="17"></line><line x1="14" y1="11" x2="14" y2="17"></line></svg>
                    </button>
                `;

                item.addEventListener('click', (e) => {
                    if (e.target.closest('.delete-history-btn')) return;
                    if (window.innerWidth <= 768) {
                        toggleSidebar();
                    }
                    loadConversation(thread.id);
                });

                const deleteBtn = item.querySelector('.delete-history-btn');
                deleteBtn.addEventListener('click', async (e) => {
                    e.stopPropagation();
                    const confirmed = await showCustomConfirm(`Delete this entire conversation?`, "Delete History");
                    if (confirmed) {
                        try {
                            const delRes = await fetch(`/api/conversations/${thread.id}`, { method: 'DELETE' });
                            if (delRes.ok) {
                                item.remove();
                                if (currentConversationId === thread.id) {
                                    newChatBtn.click();
                                }
                                if (sidebarV2Container.children.length === 0) {
                                    sidebarV2Container.innerHTML = '<div class="text-muted" style="padding: 1rem; font-size: 0.85rem;">No history yet.</div>';
                                }
                            } else {
                                alert("Failed to delete.");
                            }
                        } catch (err) {
                            alert("Error: " + err.message);
                        }
                    }
                });

                sidebarV2Container.appendChild(item);
            });
        } catch (err) {
            console.error(err);
            sidebarV2Container.innerHTML = '<div class="text-error" style="padding: 1rem;">Failed to load.</div>';
        }
    }

    async function loadConversation(id) {
        currentConversationId = id;
        chatHistory = [];
        resultsArea.innerHTML = '';
        promptArea.classList.remove('prompt-centered');
        welcomeHeader.classList.add('hidden');

        // Update active highlight
        document.querySelectorAll('.history-item').forEach(i => i.classList.remove('active'));
        const activeItem = sidebarV2Container.querySelector(`.history-item[data-id="${id}"]`);
        if (activeItem) activeItem.classList.add('active');

        try {
            const res = await fetch(`/api/conversations/${id}/messages`);
            const messages = await res.json();

            for (const msg of messages) {
                addUserMessage(msg.user_prompt);
                const aiNode = createAiMessagePlaceholder();
                resultsArea.appendChild(aiNode);

                // If there's SQL, we need to re-execute it to get the data
                if (msg.generated_sql && msg.execution_status === 'success') {
                    try {
                        const execRes = await fetch('/api/execute-sql', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ sql: msg.generated_sql })
                        });
                        const dataRes = await execRes.json();
                        populateAiMessage(aiNode, {
                            message_id: msg.id,
                            sql: msg.generated_sql,
                            data: dataRes.data,
                            message: "Restored from history"
                        });
                    } catch (e) {
                        showAiError(aiNode, "Failed to restore data: " + e.message);
                    }
                } else {
                    populateAiMessage(aiNode, {
                        message_id: msg.id,
                        sql: msg.generated_sql,
                        message: msg.assistant_response || msg.error_message || "No data available."
                    });
                    if (msg.execution_status === 'error') {
                        showAiError(aiNode, msg.error_message);
                    }
                }

                // Update internal chat history for LLM context
                chatHistory.push({ role: 'user', content: msg.user_prompt });
                if (msg.generated_sql) {
                    chatHistory.push({ role: 'assistant', content: "```sql\n" + msg.generated_sql + "\n```" });
                } else if (msg.assistant_response) {
                    chatHistory.push({ role: 'assistant', content: msg.assistant_response });
                }
            }
            scrollToBottom();
        } catch (err) {
            console.error(err);
            alert("Failed to load conversation messages.");
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
                body: JSON.stringify({
                    prompt: promptText,
                    history: chatHistory,
                    client_id: CLIENT_ID,
                    conversation_id: currentConversationId
                })
            });

            let result = {};
            try {
                result = await response.json();
            } catch (err) { }

            if (!response.ok) {
                let errorDetail = response.statusText;
                errorDetail = result.detail || result.error || errorDetail;

                if (result.sql || result.message) {
                    result.error = result.error || `Server Error: ${errorDetail}`;
                    populateAiMessage(aiMessageNode, result);
                    return;
                }

                throw new Error(`Server Error: ${errorDetail}`);
            }

            // Store interaction in history for future prompts
            chatHistory.push({ role: 'user', content: promptText });
            if (result.sql) {
                chatHistory.push({ role: 'assistant', content: "```sql\n" + result.sql + "\n```" });
            } else if (result.message) {
                chatHistory.push({ role: 'assistant', content: result.message });
            }

            // 4. Fill AI Response Block with Data
            populateAiMessage(aiMessageNode, result);
            if (result.error) {
                showAiError(aiMessageNode, result.error);
            }

            // Update conversation ID if this was a new chat
            if (!currentConversationId && result.conversation_id) {
                currentConversationId = result.conversation_id;
                loadConversationHistory(); // Refresh sidebar to show the new thread
            }

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

        // Add thinking animation to the avatar
        const avatarSvg = node.querySelector('.ai-avatar svg');
        if (avatarSvg) {
            avatarSvg.classList.add('thinking-animation');
        }

        // Add a temporary loading indicator inside the message content
        const contentDiv = node.querySelector('.message-content');
        const loadingText = document.createElement('div');
        loadingText.className = 'placeholder-text text-muted';
        loadingText.innerHTML = 'Thinking<span class="dots">...</span>';
        loadingText.style.fontStyle = 'italic';
        contentDiv.prepend(loadingText);

        return node;
    }

    function populateAiMessage(messageNode, result, preLoadedChartConfig = null) {
        // Remove 'Thinking...' placeholder
        const placeholder = messageNode.querySelector('.placeholder-text');
        if (placeholder) placeholder.remove();

        // Remove thinking animation from avatar
        const avatarSvg = messageNode.querySelector('.ai-avatar svg');
        if (avatarSvg) {
            avatarSvg.classList.remove('thinking-animation');
        }

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
        const exportInsightsBtn = messageNode.querySelector('.export-insights-btn');
        let currentChart = null;
        let lastChartConfig = null; // Store config for saving
        let lastXCol = null;
        let lastYCols = [];

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
        if (exportInsightsBtn) {
            exportInsightsBtn.style.display = 'none'; // Initially hide until rendering completes
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

                    // To prevent token limits (OpenAI 429), limit how much data we send to the LLM to infer the structure.
                    // 30 rows is typically more than enough for the AI to understand the dataset and ranges.
                    const maxRowsForAI = 30;
                    const fullDataPayload = exportData.slice(0, maxRowsForAI);

                    // Pre-compute summaries for the AI so it can generate accurate KPIs for the FULL dataset
                    const datasetSummary = {
                        total_rows_in_full_dataset: exportData.length,
                        column_sums: {}
                    };

                    // Attempt to sum numerical columns across the entire dataset
                    if (exportData.length > 0) {
                        const numericCols = Object.keys(exportData[0]).filter(col => {
                            const lowerCol = col.toLowerCase();
                            if (lowerCol.includes('phone') || lowerCol.includes('mobile') || lowerCol === 'id' || lowerCol === 'idx' || lowerCol === 'name') return false;

                            // Check if the first row value looks like a number
                            const val = exportData[0][col];
                            return typeof val === 'number' || (typeof val === 'string' && !isNaN(parseFloat(val)) && isFinite(val));
                        });

                        numericCols.forEach(col => {
                            let sum = 0;
                            exportData.forEach(row => {
                                const val = parseFloat(row[col]);
                                if (!isNaN(val)) sum += val;
                            });
                            datasetSummary.column_sums[col] = sum;
                        });
                    }

                    const responseFull = await fetch('/api/generate_chart_config', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            columns,
                            data_sample: fullDataPayload,
                            dataset_summary: datasetSummary
                        })
                    });

                    if (!responseFull.ok) {
                        try {
                            const errorJson = await responseFull.json();
                            throw new Error(errorJson.detail || "Failed to generate chart config.");
                        } catch (e) {
                            if (e.message) throw e;
                            throw new Error("Failed to generate chart config.");
                        }
                    }

                    const fullConfig = await responseFull.json();

                    if (fullConfig.error) {
                        throw new Error(fullConfig.error);
                    }

                    if (currentChart) {
                        currentChart.destroy();
                    }

                    // Pre-existing saved configs might just be the chart config
                    const chartConfigOptions = fullConfig.chart || fullConfig;
                    const kpis = fullConfig.kpis || [];

                    lastChartConfig = fullConfig; // Save the wrapper with kpis for the 'Save Report' button

                    // Render KPIs if available
                    // Clean up any existing KPI grid
                    let existingGrid = messageNode.querySelector('.kpi-grid');
                    if (existingGrid) existingGrid.remove();

                    if (kpis.length > 0) {
                        const kpiGrid = document.createElement('div');
                        kpiGrid.className = 'kpi-grid';

                        kpis.forEach(kpi => {
                            const card = document.createElement('div');
                            card.className = 'kpi-card';

                            let trendSection = '';
                            if (kpi.trend_percentage && kpi.trend_direction) {
                                const arrow = kpi.trend_direction === 'up' ? '↑' : (kpi.trend_direction === 'down' ? '↓' : '→');
                                const trendClass = kpi.trend_direction === 'neutral' ? 'kpi-trend' : `kpi-trend ${kpi.trend_direction}`;
                                trendSection = `<div class="${trendClass}">${arrow} ${kpi.trend_percentage}%</div>`;
                            }

                            card.innerHTML = `
                                <div class="kpi-label">${kpi.label}</div>
                                <div class="kpi-value">${kpi.value}</div>
                                ${trendSection}
                            `;
                            kpiGrid.appendChild(card);
                        });

                        // Insert right before chart container
                        chartContainer.parentNode.insertBefore(kpiGrid, chartContainer);
                    }

                    // --- MAP FULL DATASET OVER AI SAMPLE DATA ---
                    // The AI config (chartConfigOptions) likely contains data mapped from the small `fullDataPayload` (30 rows).
                    // We need to inject the full `exportData` (e.g. 600+ rows) into this config.
                    if (chartConfigOptions && chartConfigOptions.data && chartConfigOptions.data.datasets && exportData.length > 0) {
                        try {
                            // 1. Identify which keys (columns) the AI intended to use
                            // We look at the first dataset and the labels array length to guess the x-axis and y-axis keys from our exportData.

                            // Guess X-axis key (Labels) by finding a column in exportData[0] whose value matches the first created label.
                            // If we can't find it reliably, we assume the first non-numeric column.
                            let xKey = columns.find(c => typeof exportData[0][c] === 'string' && isNaN(parseFloat(exportData[0][c]))) || columns[0];
                            lastXCol = xKey;

                            // Map the full labels array
                            chartConfigOptions.data.labels = exportData.map(row => {
                                let val = row[xKey];
                                // Truncate long labels
                                return (typeof val === 'string' && val.length > 25) ? val.substring(0, 22) + '...' : val;
                            });

                            // Guess Y-axis keys for each dataset
                            chartConfigOptions.data.datasets.forEach((dataset, index) => {
                                // Try to match the dataset label to a column name, or guess by looking for the AI's first data point in our columns
                                let yKey = null;

                                // Direct match
                                if (columns.includes(dataset.label)) {
                                    yKey = dataset.label;
                                } else {
                                    // Fallback: pick the first numeric column we haven't used as X
                                    const numericCols = columns.filter(col => {
                                        if (col === xKey) return false;
                                        const lowerCol = col.toLowerCase();
                                        if (lowerCol.includes('phone') || lowerCol.includes('mobile') || lowerCol === 'id' || lowerCol === 'idx') return false;
                                        return !isNaN(parseFloat(exportData[0][col]));
                                    });
                                    yKey = numericCols[Math.min(index, numericCols.length - 1)];
                                }

                                if (yKey) {
                                    dataset.data = exportData.map(row => parseFloat(row[yKey]) || 0);
                                    if (!lastYCols.includes(yKey)) {
                                        lastYCols.push(yKey);
                                    }
                                }
                            });
                        } catch (mappingError) {
                            console.warn("Failed to automatically map full dataset to AI chart config:", mappingError);
                            // It will fallback to rendering whatever data the AI returned in the config
                        }
                    }
                    // ---------------------------------------------

                    chartContainer.style.display = 'block';
                    currentChart = new Chart(canvas, chartConfigOptions);

                    if (saveReportBtn) {
                        saveReportBtn.style.display = 'flex'; // Show save button
                    }
                    if (exportInsightsBtn && result.sql) {
                        exportInsightsBtn.style.display = 'flex';
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

                    loadSavedReports();
                } catch (err) {
                    alert("Error: " + err.message);
                    saveReportBtn.innerHTML = originalBtnContent;
                } finally {
                    saveReportBtn.disabled = false;
                }
            });
        } else if (saveReportBtn) {
            saveReportBtn.style.display = 'none'; // Only show save if it generated SQL and a chart
        }

        // Setup Export to Insights
        if (exportInsightsBtn && result.sql) {
            exportInsightsBtn.style.display = 'flex';
            exportInsightsBtn.addEventListener('click', async () => {
                const modal = document.getElementById('insights-export-modal');
                const backdrop = document.getElementById('modal-backdrop');
                const titleInput = document.getElementById('insights-title-input');
                const dashSelect = document.getElementById('insights-dashboard-select');
                const newDashInput = document.getElementById('insights-new-dashboard-input');
                const cancelBtn = document.getElementById('insights-modal-cancel');
                const submitBtn = document.getElementById('insights-modal-submit');

                // Reset and Show
                titleInput.value = '';
                newDashInput.value = '';
                newDashInput.style.display = 'block'; // Default to "Create New" selected

                dashSelect.innerHTML = '<option value="_new_">-- Create New Dashboard --</option>';

                // Fetch existing dashboards
                try {
                    const res = await fetch('/api/reports/insights-dashboards');
                    if (res.ok) {
                        const data = await res.json();
                        console.log('[Export Modal] Fetched dashboards:', data.dashboards);
                        if (data.dashboards && data.dashboards.length > 0) {
                            data.dashboards.forEach(d => {
                                if (d.name && d.title) {
                                    const opt = document.createElement('option');
                                    opt.value = d.name;
                                    opt.textContent = d.title;
                                    dashSelect.appendChild(opt);
                                }
                            });
                        }
                    } else {
                        console.error('[Export Modal] Dashboard fetch failed:', res.status, res.statusText);
                    }
                } catch (e) { console.error('[Export Modal] Could not fetch dashboards:', e); }

                // Use onchange (not addEventListener) to prevent stacking on repeated opens
                dashSelect.onchange = () => {
                    if (dashSelect.value === '_new_') {
                        newDashInput.style.display = 'block';
                    } else {
                        newDashInput.style.display = 'none';
                    }
                };

                backdrop.classList.remove('hidden');
                modal.classList.remove('hidden');

                // Enter key submits the modal from any input field
                const handleKeydown = (e) => {
                    if (e.key === 'Enter') {
                        e.preventDefault();
                        handleSubmit();
                    } else if (e.key === 'Escape') {
                        e.preventDefault();
                        handleCancel();
                    }
                };
                titleInput.addEventListener('keydown', handleKeydown);
                newDashInput.addEventListener('keydown', handleKeydown);

                const cleanup = () => {
                    backdrop.classList.add('hidden');
                    modal.classList.add('hidden');
                    cancelBtn.removeEventListener('click', handleCancel);
                    submitBtn.removeEventListener('click', handleSubmit);
                    titleInput.removeEventListener('keydown', handleKeydown);
                    newDashInput.removeEventListener('keydown', handleKeydown);
                    // Reset button state
                    submitBtn.disabled = false;
                    submitBtn.innerHTML = 'Export';
                    cancelBtn.style.display = '';
                };

                const handleCancel = () => cleanup();

                const handleSubmit = async () => {
                    const title = titleInput.value.trim();
                    let dashboardName = dashSelect.value;
                    const newDashName = newDashInput.value.trim();

                    if (!title) { alert('Please enter a title'); return; }

                    if (dashboardName === '_new_') {
                        if (!newDashName) { alert('Please enter a new dashboard name'); return; }
                        dashboardName = newDashName;
                    } else {
                        // User selected an existing dashboard — use its title for the backend
                        const selectedOption = dashSelect.options[dashSelect.selectedIndex];
                        dashboardName = selectedOption.textContent;
                    }

                    if (submitBtn.disabled) return; // Prevent double clicks

                    // Show loading spinner INSIDE the modal
                    submitBtn.disabled = true;
                    submitBtn.innerHTML = '<div class="spinner" style="width:14px; height:14px; border-width:2px; display:inline-block; vertical-align:middle; margin-right:6px;"></div> Exporting...';
                    cancelBtn.style.display = 'none';

                    const originalBtnContent = exportInsightsBtn.innerHTML;

                    // Extract chart type
                    let chartType = "Bar";
                    if (lastChartConfig) {
                        try {
                            const config = JSON.parse(lastChartConfig);
                            if (config.chart && config.chart.type) {
                                chartType = config.chart.type;
                            }
                        } catch (e) { }
                    }

                    try {
                        const response = await fetch('/api/reports/export-insights', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({
                                title: title,
                                sql: result.sql,
                                chart_type: chartType,
                                dashboard_name: dashboardName,
                                x_col: lastXCol,
                                y_cols: lastYCols.length > 0 ? lastYCols : null
                            })
                        });

                        const resData = await response.json();
                        if (!response.ok) throw new Error(resData.detail || "Failed to export");

                        exportInsightsBtn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--success-color)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg>';
                        setTimeout(() => exportInsightsBtn.innerHTML = originalBtnContent, 2000);

                        // If successful, the API returns {"status": "success", "url": "..."}
                        if (resData.url) {
                            window.open(resData.url, '_blank');
                        }

                    } catch (e) {
                        alert("Export failed: " + e.message);
                    } finally {
                        cleanup();
                    }
                };

                cancelBtn.addEventListener('click', handleCancel);
                submitBtn.addEventListener('click', handleSubmit);
            });
        } else if (exportInsightsBtn) {
            exportInsightsBtn.style.display = 'none';
        }

        // Setup Feedback Buttons
        const thumbsUpBtn = messageNode.querySelector('.thumbs-up');
        const thumbsDownBtn = messageNode.querySelector('.thumbs-down');

        if (thumbsUpBtn && thumbsDownBtn && result.message_id) {
            thumbsUpBtn.addEventListener('click', async () => {
                try {
                    thumbsUpBtn.classList.add('active');
                    thumbsDownBtn.classList.remove('active');
                    await fetch('/api/conversations/feedback', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ message_id: result.message_id, feedback: 1, comment: null })
                    });
                } catch (e) { console.error("Feedback error", e); }
            });

            thumbsDownBtn.addEventListener('click', async () => {
                try {
                    const comment = await showCustomPrompt("Please tell us what went wrong so the AI can learn (Optional):", "Feedback");

                    thumbsDownBtn.classList.add('active');
                    thumbsUpBtn.classList.remove('active');
                    await fetch('/api/conversations/feedback', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ message_id: result.message_id, feedback: -1, comment: comment || null })
                    });
                } catch (e) { console.error("Feedback error", e); }
            });
        }

        // Try rendering SQL (currently removed from backend, but keeping logic if it returns)
        if (result.sql && APP_ENV !== 'production') {
            sqlOutput.textContent = result.sql;
            sqlSection.classList.remove('hidden');

            const sqlCollapseBtn = messageNode.querySelector('.sql-section .collapse-toggle-btn');
            const sqlCollapsibleBody = messageNode.querySelector('.sql-section .collapsible-body');

            if (sqlCollapseBtn && sqlCollapsibleBody) {
                const toggleSqlCollapse = () => {
                    sqlCollapseBtn.classList.toggle('collapsed');
                    sqlCollapsibleBody.classList.toggle('collapsed');
                };
                sqlCollapseBtn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    toggleSqlCollapse();
                });
                const sqlTitleGroup = messageNode.querySelector('.sql-section .section-title-group');
                if (sqlTitleGroup) {
                    sqlTitleGroup.addEventListener('click', (e) => {
                        if (e.target !== sqlCollapseBtn && !sqlCollapseBtn.contains(e.target)) {
                            toggleSqlCollapse();
                        }
                    });
                }
            }
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
                    const val = row[header];

                    if (val !== null && val !== undefined && typeof val === 'number') {
                        if (isCurrencyColumn(header)) {
                            td.textContent = formatCurrencyValue(val);
                            td.style.textAlign = 'right';
                        } else {
                            td.textContent = val;
                        }
                    } else if (val !== null && val !== undefined && !isNaN(parseFloat(val)) && isFinite(val) && typeof val === 'string' && val.trim() !== '') {
                        if (isCurrencyColumn(header)) {
                            const num = parseFloat(val);
                            td.textContent = formatCurrencyValue(num);
                            td.style.textAlign = 'right';
                        } else {
                            td.textContent = val;
                        }
                    } else {
                        td.textContent = val !== null && val !== undefined ? val : '—';
                    }
                    tr.appendChild(td);
                });
                tbody.appendChild(tr);
            });

            if (false && data.length > 1) {
                const tfoot = document.createElement('tfoot');
                const trFoot = document.createElement('tr');
                trFoot.className = 'total-row';

                // Sr column in footer
                const tdSr = document.createElement('td');
                tdSr.textContent = 'Total';
                tdSr.style.fontWeight = 'bold';
                trFoot.appendChild(tdSr);

                headers.forEach(header => {
                    const td = document.createElement('td');
                    const isNumeric = isCurrencyColumn(header);

                    if (isNumeric) {
                        let colSum = 0;
                        let hasData = false;
                        data.forEach(row => {
                            const val = parseFloat(row[header]);
                            if (!isNaN(val)) {
                                colSum += val;
                                hasData = true;
                            }
                        });

                        if (hasData) {
                            td.textContent = formatCurrencyValue(colSum);
                            td.style.textAlign = 'right';
                            td.style.fontWeight = 'bold';
                        } else {
                            td.textContent = '—';
                        }
                    } else {
                        td.textContent = '';
                    }
                    trFoot.appendChild(td);
                });
                tfoot.appendChild(trFoot);
                table.appendChild(tfoot);
            }

            dataSection.classList.remove('hidden');

            // Wire up collapsible toggle
            const collapseBtn = messageNode.querySelector('.data-section .collapse-toggle-btn');
            const collapsibleBody = messageNode.querySelector('.data-section .collapsible-body');
            const collapsibleHeader = messageNode.querySelector('.data-section .collapsible-header');

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
                const titleGroup = messageNode.querySelector('.data-section .section-title-group');
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

        // Render Pre-loaded Chart and KPIs if it exists
        if (preLoadedChartConfig && chartContainer && canvas) {
            const chartConfigOptions = preLoadedChartConfig.chart || preLoadedChartConfig;
            const kpis = preLoadedChartConfig.kpis || [];

            // Clean up any existing KPI grid
            let existingGrid = messageNode.querySelector('.kpi-grid');
            if (existingGrid) existingGrid.remove();

            if (kpis.length > 0) {
                const kpiGrid = document.createElement('div');
                kpiGrid.className = 'kpi-grid';

                kpis.forEach(kpi => {
                    const card = document.createElement('div');
                    card.className = 'kpi-card';

                    let trendSection = '';
                    if (kpi.trend_percentage && kpi.trend_direction) {
                        const arrow = kpi.trend_direction === 'up' ? '↑' : (kpi.trend_direction === 'down' ? '↓' : '→');
                        const trendClass = kpi.trend_direction === 'neutral' ? 'kpi-trend' : `kpi-trend ${kpi.trend_direction}`;
                        trendSection = `<div class="${trendClass}">${arrow} ${kpi.trend_percentage}%</div>`;
                    }

                    card.innerHTML = `
                        <div class="kpi-label">${kpi.label}</div>
                        <div class="kpi-value">${kpi.value}</div>
                        ${trendSection}
                    `;
                    kpiGrid.appendChild(card);
                });

                // Insert right before chart container
                chartContainer.parentNode.insertBefore(kpiGrid, chartContainer);
            }

            chartContainer.style.display = 'block';
            lastChartConfig = preLoadedChartConfig;
            currentChart = new Chart(canvas, chartConfigOptions);
        }
    }

    function showAiError(messageNode, errorMessage) {
        const placeholder = messageNode.querySelector('.placeholder-text');
        if (placeholder) placeholder.remove();

        const avatarSvg = messageNode.querySelector('.ai-avatar svg');
        if (avatarSvg) {
            avatarSvg.classList.remove('thinking-animation');
        }

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

    // Sidebar Menu Logic
    const menuBtn = document.getElementById('sidebar-menu-btn');
    const menuDropdown = document.getElementById('sidebar-menu-dropdown');
    const menuLogoutBtn = document.getElementById('menu-logout-btn');

    if (menuBtn && menuDropdown) {
        menuBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            menuDropdown.classList.toggle('hidden');
        });

        // Close menu when clicking outside
        document.addEventListener('click', (e) => {
            if (!menuDropdown.classList.contains('hidden') && !menuDropdown.contains(e.target) && e.target !== menuBtn) {
                menuDropdown.classList.add('hidden');
            }
        });
    }

    if (menuLogoutBtn) {
        menuLogoutBtn.addEventListener('click', () => {
            localStorage.removeItem('auth_token');
            localStorage.removeItem('user_email');
            window.location.href = 'login.html';
        });
    }
});
