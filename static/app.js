// Global state
let currentUserId = null;
let pollInterval = null;

// DOM elements
const userIdInput = document.getElementById('userIdInput');
const setUserBtn = document.getElementById('setUserBtn');
const currentUserDisplay = document.getElementById('currentUserDisplay');
const currentUserIdSpan = document.getElementById('currentUserId');
const wsiPathInput = document.getElementById('wsiPathInput');
const branchInput = document.getElementById('branchInput');
const jobTypeSelect = document.getElementById('jobTypeSelect');
const createWorkflowBtn = document.getElementById('createWorkflowBtn');
const createMessage = document.getElementById('createMessage');
const workflowsContainer = document.getElementById('workflowsContainer');

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
    // Load user ID from localStorage
    const savedUserId = localStorage.getItem('userId');
    if (savedUserId) {
        userIdInput.value = savedUserId;
        setCurrentUser(savedUserId);
    }

    // Set up event listeners
    setUserBtn.addEventListener('click', handleSetUser);
    createWorkflowBtn.addEventListener('click', handleCreateWorkflow);
});

/**
 * Set the current user ID and start polling
 */
function setCurrentUser(userId) {
    currentUserId = userId;
    currentUserIdSpan.textContent = userId;
    currentUserDisplay.style.display = 'block';
    
    // Start polling workflows
    startPolling();
}

/**
 * Handle "Set User" button click
 */
function handleSetUser() {
    const userId = userIdInput.value.trim();
    if (!userId) {
        alert('Please enter a user ID');
        return;
    }
    
    // Save to localStorage
    localStorage.setItem('userId', userId);
    setCurrentUser(userId);
}

/**
 * API fetch helper that adds X-User-ID header
 */
async function apiFetch(path, options = {}) {
    if (!currentUserId) {
        alert('Please set User ID first');
        throw new Error('User ID not set');
    }

    const url = `http://127.0.0.1:8000${path}`;
    const headers = {
        'X-User-ID': currentUserId,
        ...options.headers,
    };

    // Add Content-Type for JSON requests
    if (options.body && typeof options.body === 'object') {
        headers['Content-Type'] = 'application/json';
        options.body = JSON.stringify(options.body);
    }

    try {
        const response = await fetch(url, {
            ...options,
            headers,
        });

        if (!response.ok) {
            const errorText = await response.text();
            throw new Error(`Request failed: ${response.status} ${errorText}`);
        }

        return await response.json();
    } catch (error) {
        console.error('API request failed:', error);
        alert('Request failed: ' + error.message);
        throw error;
    }
}

/**
 * Handle "Create Workflow" button click
 */
async function handleCreateWorkflow() {
    if (!currentUserId) {
        alert('Please set User ID first');
        return;
    }

    const wsiPath = wsiPathInput.value.trim();
    const branch = branchInput.value.trim();
    const jobType = jobTypeSelect.value;

    if (!wsiPath || !branch) {
        alert('Please fill in all fields');
        return;
    }

    // Disable button during request
    createWorkflowBtn.disabled = true;
    createMessage.innerHTML = '';

    try {
        const body = {
            jobs: [{
                branch,
                job_type: jobType,
                wsi_path: wsiPath,
            }],
        };

        await apiFetch('/workflows', {
            method: 'POST',
            body,
        });

        // Clear form
        wsiPathInput.value = '';
        branchInput.value = '';
        jobTypeSelect.value = 'CELL_SEGMENTATION';

        // Show success message
        createMessage.innerHTML = '<div class="message message-success">Workflow created successfully!</div>';

        // Refresh workflows list
        await loadWorkflows();
    } catch (error) {
        createMessage.innerHTML = '<div class="message message-error">Failed to create workflow</div>';
    } finally {
        createWorkflowBtn.disabled = false;
    }
}

/**
 * Load and render workflows
 */
async function loadWorkflows() {
    if (!currentUserId) {
        return;
    }

    try {
        const workflows = await apiFetch('/workflows');
        
        if (workflows.length === 0) {
            workflowsContainer.innerHTML = '<p style="color: #999;">No workflows yet. Create one above.</p>';
            return;
        }

        workflowsContainer.innerHTML = workflows.map(workflow => renderWorkflow(workflow)).join('');
        
        // Attach cancel button handlers
        workflows.forEach(workflow => {
            workflow.jobs.forEach(job => {
                if (job.status === 'PENDING') {
                    const cancelBtn = document.getElementById(`cancel-${job.job_id}`);
                    if (cancelBtn) {
                        cancelBtn.addEventListener('click', () => handleCancelJob(job.job_id));
                    }
                }
            });
        });
    } catch (error) {
        console.error('Failed to load workflows:', error);
    }
}

/**
 * Render a single workflow card
 */
function renderWorkflow(workflow) {
    const jobsHtml = workflow.jobs.map(job => renderJob(job)).join('');
    
    return `
        <div class="workflow-card">
            <div class="workflow-header">
                <div>
                    <strong>Workflow</strong>
                    <span class="workflow-id">${workflow.workflow_id}</span>
                </div>
            </div>
            <div class="progress-container">
                <div class="progress-text">Progress: ${workflow.progress.toFixed(1)}%</div>
                <div class="progress-bar">
                    <div class="progress-fill" style="width: ${workflow.progress}%"></div>
                </div>
            </div>
            <div class="jobs-list">
                <strong>Jobs:</strong>
                ${jobsHtml}
            </div>
        </div>
    `;
}

/**
 * Render a single job item
 */
function renderJob(job) {
    const statusClass = `status-${job.status.toLowerCase()}`;
    const cancelBtn = job.status === 'PENDING' 
        ? `<button class="cancel-btn" id="cancel-${job.job_id}">Cancel</button>`
        : '';
    
    return `
        <div class="job-item">
            <div class="job-info">
                <span><strong>ID:</strong> ${job.job_id.substring(0, 8)}...</span>
                <span><strong>Branch:</strong> ${job.branch}</span>
                <span><strong>Type:</strong> ${job.job_type}</span>
                <span class="job-status ${statusClass}">${job.status}</span>
                <span><strong>Progress:</strong> ${job.progress.toFixed(1)}%</span>
            </div>
            ${cancelBtn}
        </div>
    `;
}

/**
 * Handle cancel job button click
 */
async function handleCancelJob(jobId) {
    if (!confirm('Are you sure you want to cancel this job?')) {
        return;
    }

    try {
        await apiFetch(`/jobs/${jobId}/cancel`, {
            method: 'POST',
        });

        // Refresh workflows list
        await loadWorkflows();
    } catch (error) {
        console.error('Failed to cancel job:', error);
    }
}

/**
 * Start polling workflows every 2 seconds
 */
function startPolling() {
    // Clear existing interval if any
    if (pollInterval) {
        clearInterval(pollInterval);
    }

    // Load immediately
    loadWorkflows();

    // Then poll every 2 seconds
    pollInterval = setInterval(() => {
        loadWorkflows();
    }, 2000);
}

/**
 * Stop polling workflows
 */
function stopPolling() {
    if (pollInterval) {
        clearInterval(pollInterval);
        pollInterval = null;
    }
}

